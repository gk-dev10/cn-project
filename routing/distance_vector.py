"""Module 13 — Distance-Vector Routing.

Each node periodically sends its distance vector (routing table summary)
to its direct neighbours.  Upon receiving a neighbour's vector, the node
runs Bellman-Ford relaxation (Module 14) to update its own routes.

Key differences from Link-State (Module 11):
    * Nodes do **not** flood topology information.
    * Each node only knows routes, not the full graph.
    * Convergence uses iterative Bellman-Ford relaxation.
    * Vulnerable to count-to-infinity; mitigated with route expiry and
      a maximum cost limit (``INFINITY_COST``).

Data flow::

    Timer fires
        │
        ▼
    Build distance vector from own routing table
        │
        ├─► DV_UPDATE packet to each active neighbour
        │
        ▼
    Neighbour receives DV_UPDATE
        │
        ├─► bellman_ford_relax(current_routes, neighbor_vector)
        ├─► expire_routes(...)
        └─► install changed routes into MeshNode.routing_table
"""

from __future__ import annotations

import itertools
import threading
import time
from typing import Callable, Optional

from core.constants import (
    DEFAULT_DV_ROUTE_EXPIRY_SECONDS,
    DEFAULT_DV_UPDATE_INTERVAL_SECONDS,
    DEFAULT_TTL,
    PacketType,
)
from core.node import MeshNode
from core.packet import create_packet
from routing.bellman_ford import (
    DVRoute,
    BellmanFordResult,
    bellman_ford_relax,
    expire_routes,
    format_dv_table,
    routes_to_vector,
)
from transport.udp_socket import UDPSocket


# Maximum route cost before a destination is considered unreachable.
# Helps mitigate count-to-infinity.
INFINITY_COST = 64


RouteChangeCallback = Callable[[dict[str, DVRoute]], None]


class DistanceVectorService:
    """Distance-Vector routing service for a single mesh node.

    Parameters
    ----------
    node : MeshNode
        The local mesh node.
    udp_socket : UDPSocket, optional
        Socket for sending/receiving DV_UPDATE packets.
    interval : float
        Seconds between periodic DV announcements.
    route_expiry : float
        Seconds after which a route that has not been refreshed is
        removed from the table.
    on_route_change : optional callback
        Invoked with the current route table whenever it changes.
    """

    def __init__(
        self,
        node: MeshNode,
        udp_socket: Optional[UDPSocket] = None,
        interval: float = DEFAULT_DV_UPDATE_INTERVAL_SECONDS,
        route_expiry: float = DEFAULT_DV_ROUTE_EXPIRY_SECONDS,
        on_route_change: Optional[RouteChangeCallback] = None,
    ) -> None:
        self.node = node
        self.udp_socket = udp_socket
        self.interval = interval
        self.route_expiry = route_expiry
        self.on_route_change = on_route_change

        self._routes: dict[str, DVRoute] = {}
        self._seq = itertools.count(1)
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._handler_registered = False
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    def start(self) -> None:
        if self.is_running:
            return
        self._ensure_socket()
        if not self._handler_registered:
            self.udp_socket.add_packet_handler(self._handle_packet)
            self._handler_registered = True
        self._running.set()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"meshlink-dv-{self.node.node_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._handler_registered and self.udp_socket:
            self.udp_socket.remove_packet_handler(self._handle_packet)
            self._handler_registered = False
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None

    # ------------------------------------------------------------------
    # Announcement
    # ------------------------------------------------------------------

    def announce(self) -> None:
        """Send this node's distance vector to all active neighbours."""
        # 1. Ensure direct neighbours have routes.
        changed = self._sync_direct_neighbors()

        # 2. Expire stale routes.
        with self._lock:
            expired = expire_routes(self._routes, self.route_expiry)

        # 3. Build vector and send.
        with self._lock:
            vector = routes_to_vector(self._routes)

        payload = {
            "advertising_node": self.node.node_id,
            "vector": vector,  # {destination: cost, …}
            "timestamp": time.time(),
        }

        packet = create_packet(
            packet_type=PacketType.DV_UPDATE,
            source=self.node.node_id,
            destination=None,
            sequence_number=next(self._seq),
            ttl=1,  # DV updates are not flooded beyond direct neighbours.
            payload=payload,
        )

        for neighbor_id, info in list(self.node.neighbors.items()):
            if info.status != "ACTIVE":
                continue
            try:
                self.udp_socket.send_packet(packet, (info.ip, info.port))
            except OSError:
                pass

        # 4. Install routes if anything changed.
        if changed or expired:
            self._install_routes()


    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    def _handle_packet(self, packet: dict, address: tuple[str, int]) -> None:
        if packet.get("type") != PacketType.DV_UPDATE.value:
            return

        payload = packet.get("payload")
        if not isinstance(payload, dict):
            return

        advertising_node = payload.get("advertising_node", "")
        if not advertising_node or advertising_node == self.node.node_id:
            return

        vector = payload.get("vector")
        if not isinstance(vector, dict):
            return

        # Parse vector costs.
        parsed_vector: dict[str, float] = {}
        for dest, cost in vector.items():
            try:
                c = float(cost)
                if c < INFINITY_COST:
                    parsed_vector[str(dest)] = c
            except (ValueError, TypeError):
                continue

        # Determine cost to the advertising neighbour.
        neighbor_info = self.node.neighbors.get(advertising_node)
        neighbor_cost = 1  # hop-count default
        # If we don't know this neighbour, still accept the vector.

        with self._lock:
            result = bellman_ford_relax(
                self_node_id=self.node.node_id,
                current_routes=self._routes,
                neighbor_id=advertising_node,
                neighbor_cost=neighbor_cost,
                neighbor_vector=parsed_vector,
            )

            # Cap any route cost at INFINITY_COST.
            for dest in list(self._routes):
                if self._routes[dest].cost >= INFINITY_COST:
                    del self._routes[dest]

        if result.changed:
            self._install_routes()

    # ------------------------------------------------------------------
    # Route access
    # ------------------------------------------------------------------

    def current_routes(self) -> dict[str, DVRoute]:
        """Return a copy of the current routing table."""
        with self._lock:
            return {d: DVRoute(r.destination, r.next_hop, r.cost, r.last_updated) for d, r in self._routes.items()}

    def current_routing_table(self) -> dict[str, tuple[str, float]]:
        """Return ``{destination: (next_hop, cost)}`` for compatibility with LinkStateService."""
        with self._lock:
            return {d: (r.next_hop, r.cost) for d, r in self._routes.items()}

    def format_routing_table(self) -> str:
        """Pretty-print the routing table."""
        with self._lock:
            return format_dv_table(self._routes)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _sync_direct_neighbors(self) -> bool:
        """Ensure each active direct neighbour has a cost-1 route.

        Returns True if any new route was added.
        """
        now = time.time()
        added = False
        with self._lock:
            for nid, info in list(self.node.neighbors.items()):
                if info.status != "ACTIVE":
                    continue
                existing = self._routes.get(nid)
                if existing is None:
                    self._routes[nid] = DVRoute(
                        destination=nid,
                        next_hop=nid,
                        cost=1,
                        last_updated=now,
                    )
                    added = True
                elif existing.next_hop == nid and existing.cost == 1:
                    existing.last_updated = now
        return added

    def _install_routes(self) -> None:
        """Install current DV routes into MeshNode.routing_table."""
        with self._lock:
            snapshot = {d: (r.next_hop, r.cost) for d, r in self._routes.items()}

        self.node.routing_table.clear()
        for dest, (hop, cost) in snapshot.items():
            self.node.update_route(dest, next_hop=hop, cost=int(cost))

        if self.on_route_change:
            with self._lock:
                self.on_route_change(dict(self._routes))

    def _run_loop(self) -> None:
        while self._running.is_set():
            self.announce()
            self._running.wait(self.interval)

    def _ensure_socket(self) -> None:
        if self.udp_socket:
            if not self.udp_socket.is_running:
                self.udp_socket.start_socket()
            return
        self.node.start_networking()
        self.udp_socket = self.node.udp_socket
