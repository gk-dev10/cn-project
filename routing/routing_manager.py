"""Module 15 — Routing Manager.

Provides a single, protocol-agnostic interface for routing.  The
application layer calls::

    routing_manager.get_next_hop(destination)

without caring whether the underlying strategy is **Link-State**
(Module 11) or **Distance-Vector** (Module 13).

Responsibilities:
    * Instantiate the chosen routing service based on configuration.
    * Proxy ``get_next_hop``, ``current_routing_table``,
      ``format_routing_table``, ``start``, and ``stop`` calls.
    * Allow switching strategies at runtime.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Callable, Optional

from core.node import MeshNode
from routing.distance_vector import DistanceVectorService
from routing.link_state import LinkStateService
from routing.topology import NetworkTopology
from transport.udp_socket import UDPSocket


class RoutingStrategy(str, Enum):
    """Supported routing algorithms."""

    LINK_STATE = "LINK_STATE"
    DISTANCE_VECTOR = "DISTANCE_VECTOR"


RouteChangeCallback = Callable[[dict], None]


class RoutingManager:
    """Unified routing interface for MeshLink.

    Parameters
    ----------
    node : MeshNode
        The local mesh node.
    strategy : RoutingStrategy
        Which routing algorithm to use.
    udp_socket : UDPSocket, optional
        Shared UDP socket.
    topology : NetworkTopology, optional
        Required when *strategy* is ``LINK_STATE``.  If not provided,
        a new one is created automatically.
    interval : float
        Seconds between routing announcements.
    route_expiry : float
        (DV only) Seconds until an unrefreshed route expires.
    on_route_change : optional callback
        Invoked when the routing table changes.
    """

    def __init__(
        self,
        node: MeshNode,
        strategy: RoutingStrategy = RoutingStrategy.LINK_STATE,
        udp_socket: Optional[UDPSocket] = None,
        topology: Optional[NetworkTopology] = None,
        interval: float = 5.0,
        route_expiry: float = 30.0,
        on_route_change: Optional[RouteChangeCallback] = None,
    ) -> None:
        self.node = node
        self._strategy = strategy
        self._udp_socket = udp_socket
        self._topology = topology
        self._interval = interval
        self._route_expiry = route_expiry
        self._on_route_change = on_route_change

        self._service: Optional[LinkStateService | DistanceVectorService] = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def strategy(self) -> RoutingStrategy:
        """Currently active routing strategy."""
        return self._strategy

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._service is not None and self._service.is_running

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the routing service."""
        with self._lock:
            if self._service and self._service.is_running:
                return
            self._service = self._create_service(self._strategy)
            self._service.start()

    def stop(self) -> None:
        """Stop the routing service."""
        with self._lock:
            if self._service:
                self._service.stop()
                self._service = None

    def switch_strategy(self, new_strategy: RoutingStrategy) -> None:
        """Switch to a different routing algorithm.

        Stops the current service, clears the routing table, and
        starts the new one.
        """
        with self._lock:
            was_running = self.is_running
            if was_running:
                self.stop()
            self._strategy = new_strategy
            if was_running:
                self.start()

    # ------------------------------------------------------------------
    # Route queries (protocol-agnostic)
    # ------------------------------------------------------------------

    def get_next_hop(self, destination: str) -> Optional[str]:
        """Return the next-hop node ID for *destination*, or None."""
        return self.node.get_next_hop(destination)

    def get_route(self, destination: str) -> Optional[tuple[str, float]]:
        """Return ``(next_hop, cost)`` for *destination*, or None."""
        with self._lock:
            if self._service is None:
                return None
            table = self._service.current_routing_table()
            return table.get(destination)

    def current_routing_table(self) -> dict[str, tuple[str, float]]:
        """Return the full routing table ``{dest: (next_hop, cost)}``."""
        with self._lock:
            if self._service is None:
                return {}
            return self._service.current_routing_table()

    def format_routing_table(self) -> str:
        """Pretty-print the routing table."""
        with self._lock:
            if self._service is None:
                return "(routing not started)"
            return self._service.format_routing_table()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _create_service(
        self, strategy: RoutingStrategy,
    ) -> LinkStateService | DistanceVectorService:
        if strategy == RoutingStrategy.LINK_STATE:
            topo = self._topology or NetworkTopology(self_node_id=self.node.node_id)
            self._topology = topo
            return LinkStateService(
                node=self.node,
                topology=topo,
                udp_socket=self._udp_socket or self.node.udp_socket,
                interval=self._interval,
                on_route_change=self._on_route_change,
            )

        if strategy == RoutingStrategy.DISTANCE_VECTOR:
            return DistanceVectorService(
                node=self.node,
                udp_socket=self._udp_socket or self.node.udp_socket,
                interval=self._interval,
                route_expiry=self._route_expiry,
                on_route_change=self._on_route_change,
            )

        raise ValueError(f"unsupported routing strategy: {strategy!r}")

    def __repr__(self) -> str:
        state = "running" if self.is_running else "stopped"
        return f"RoutingManager(strategy={self._strategy.value}, {state})"
