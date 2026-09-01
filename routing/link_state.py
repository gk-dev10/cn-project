"""Module 11 — Link-State Routing.

Each node distributes a Link-State Advertisement (LSA) describing its
directly connected neighbours.  Every node that receives an LSA:

1. Stores it in the local ``NetworkTopology`` (Module 10).
2. Forwards (floods) it to all neighbours except the one it arrived from.
3. Re-runs Dijkstra (Module 12) to recompute shortest paths.
4. Installs the resulting routing table into the ``MeshNode``.

Flooding is bounded by:
    * **Sequence numbers** — a node only accepts an LSA if its sequence
      number is strictly higher than the last one seen from that source.
    * **Hop-based TTL** — each forwarded LSA has its TTL decremented;
      when TTL reaches 0 the packet is dropped.

Data flow::

    NeighborManager changes
           │
           ▼
    LinkStateService.announce()          ← builds own LSA
           │
           ├─► serialize as ROUTING_UPDATE packet
           │
           └─► flood to all neighbours
                     │
                     ▼
    Remote node receives ROUTING_UPDATE
           │
           ├─► topology.update_from_neighbor_list()
           ├─► re-flood to other neighbours
           └─► dijkstra  →  routing table  →  MeshNode.routing_table
"""

from __future__ import annotations

import itertools
import threading
import time
from typing import Callable, Optional

from core.constants import DEFAULT_TTL, PacketType
from core.node import MeshNode
from core.packet import create_packet
from routing.dijkstra import run_dijkstra
from routing.topology import NetworkTopology
from transport.udp_socket import UDPSocket


# Defaults
DEFAULT_LSA_INTERVAL_SECONDS = 5.0
DEFAULT_LSA_MAX_AGE_SECONDS = 30.0


# Type alias for the callback when routes change.
RouteChangeCallback = Callable[[dict[str, tuple[str, float]]], None]


class LinkStateService:
    """Link-State routing service for a single mesh node.

    Parameters
    ----------
    node : MeshNode
        The local mesh node.
    topology : NetworkTopology
        Shared topology graph (Module 10).
    udp_socket : UDPSocket
        Socket used to send and receive ROUTING_UPDATE packets.
    interval : float
        Seconds between periodic LSA announcements.
    on_route_change : optional callback
        Invoked with the new routing table whenever Dijkstra produces
        a different result.
    """

    def __init__(
        self,
        node: MeshNode,
        topology: NetworkTopology,
        udp_socket: Optional[UDPSocket] = None,
        interval: float = DEFAULT_LSA_INTERVAL_SECONDS,
        on_route_change: Optional[RouteChangeCallback] = None,
    ) -> None:
        self.node = node
        self.topology = topology
        self.udp_socket = udp_socket
        self.interval = interval
        self.on_route_change = on_route_change

        self._lsa_sequence = itertools.count(1)
        self._ack_seq = itertools.count(1)
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._handler_registered = False

        # Cache the last routing table so we can detect changes.
        self._last_routing_table: dict[str, tuple[str, float]] = {}
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
            name=f"meshlink-link-state-{self.node.node_id}",
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
    # Announcement (own LSA)
    # ------------------------------------------------------------------

    def announce(self) -> None:
        """Build and flood this node's Link-State Advertisement."""
        # 1. Sync local neighbour list into the topology graph.
        self.topology.sync_from_neighbors(self.node.neighbors)

        # 2. Build the LSA payload.
        seq = next(self._lsa_sequence)
        my_neighbors = self.topology.neighbors_of(self.node.node_id)

        lsa_payload = {
            "advertising_node": self.node.node_id,
            "sequence_number": seq,
            "neighbors": my_neighbors,  # {neighbor_id: cost, …}
            "timestamp": time.time(),
        }

        # 3. Flood to all direct neighbours.
        packet = create_packet(
            packet_type=PacketType.ROUTING_UPDATE,
            source=self.node.node_id,
            destination=None,  # broadcast / flood
            sequence_number=next(self._ack_seq),
            ttl=DEFAULT_TTL,
            payload=lsa_payload,
        )

        for neighbor_id, info in list(self.node.neighbors.items()):
            if info.status != "ACTIVE":
                continue
            try:
                self.udp_socket.send_packet(packet, (info.ip, info.port))
            except OSError:
                pass

        # 4. Recompute routes.
        self._recompute_routes()

    # ------------------------------------------------------------------
    # Receive + flood
    # ------------------------------------------------------------------

    def _handle_packet(self, packet: dict, address: tuple[str, int]) -> None:
        """Process an incoming ROUTING_UPDATE (LSA from a remote node)."""
        if packet.get("type") != PacketType.ROUTING_UPDATE.value:
            return

        payload = packet.get("payload")
        if not isinstance(payload, dict):
            return

        advertising_node = payload.get("advertising_node", "")
        if not advertising_node or advertising_node == self.node.node_id:
            return

        seq = payload.get("sequence_number")
        if not isinstance(seq, int):
            return

        neighbors = payload.get("neighbors")
        if not isinstance(neighbors, dict):
            return

        # Convert JSON keys back to int costs (JSON may deserialize as int already).
        neighbor_costs: dict[str, int] = {}
        for nid, cost in neighbors.items():
            try:
                neighbor_costs[str(nid)] = int(cost)
            except (ValueError, TypeError):
                continue

        # 1. Attempt to update topology.  Returns False if stale.
        changed = self.topology.update_from_neighbor_list(
            advertising_node, neighbor_costs, sequence_number=seq,
        )
        if not changed:
            return

        # 2. Re-flood to other neighbours (not back to sender).
        sender_id = packet.get("source", "")
        ttl = packet.get("ttl", 0)
        if ttl > 1:
            forwarded = create_packet(
                packet_type=PacketType.ROUTING_UPDATE,
                source=advertising_node,
                destination=None,
                sequence_number=next(self._ack_seq),
                ttl=ttl - 1,
                payload=payload,
            )
            for neighbor_id, info in list(self.node.neighbors.items()):
                if neighbor_id == sender_id or info.status != "ACTIVE":
                    continue
                try:
                    self.udp_socket.send_packet(forwarded, (info.ip, info.port))
                except OSError:
                    pass

        # 3. Recompute routes after topology change.
        self._recompute_routes()

    # ------------------------------------------------------------------
    # Route computation
    # ------------------------------------------------------------------

    def _recompute_routes(self) -> None:
        """Run Dijkstra on the current topology and install routes."""
        graph = self.topology.snapshot()
        if self.node.node_id not in graph:
            return

        result = run_dijkstra(graph, self.node.node_id)
        new_table = result.routing_table()

        with self._lock:
            changed = new_table != self._last_routing_table
            self._last_routing_table = new_table

        # Install into MeshNode.
        self.node.routing_table.clear()
        for dest, (hop, cost) in new_table.items():
            self.node.update_route(dest, next_hop=hop, cost=int(cost))

        if changed and self.on_route_change:
            self.on_route_change(new_table)

    def current_routing_table(self) -> dict[str, tuple[str, float]]:
        """Return the last computed routing table."""
        with self._lock:
            return dict(self._last_routing_table)

    def format_routing_table(self) -> str:
        """Pretty-print the routing table."""
        table = self.current_routing_table()
        if not table:
            return "(no routes)"
        lines = [f"{'Destination':<16}{'Next Hop':<16}{'Cost':>6}"]
        lines.append("-" * 38)
        for dest in sorted(table):
            hop, cost = table[dest]
            lines.append(f"{dest:<16}{hop:<16}{int(cost):>6}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

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
