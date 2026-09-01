"""Module 23 - Resilience and self-healing.

The manager reacts to stale/lost neighbors by marking them offline,
removing failed links from topology, purging affected routes, and asking
the routing layer to recompute routes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Callable, Optional

from core.constants import DEFAULT_NEIGHBOR_TIMEOUT_SECONDS, DEFAULT_SELF_HEALING_INTERVAL_SECONDS, NodeStatus
from core.node import MeshNode, NodeInfo
from discovery.neighbor_manager import NeighborManager
from routing.routing_manager import RoutingManager
from routing.topology import NetworkTopology


RecoveryCallback = Callable[["RecoveryEvent"], None]


@dataclass(frozen=True, slots=True)
class RecoveryEvent:
    failed_node: str
    removed_routes: list[str]
    active_routes: dict[str, dict[str, int | str]]
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class SelfHealingStats:
    failures_detected: int = 0
    routes_removed: int = 0
    recomputations: int = 0


class SelfHealingManager:
    def __init__(
        self,
        node: MeshNode,
        neighbor_manager: Optional[NeighborManager] = None,
        topology: Optional[NetworkTopology] = None,
        routing_manager: Optional[RoutingManager] = None,
        neighbor_timeout: float = DEFAULT_NEIGHBOR_TIMEOUT_SECONDS,
        check_interval: float = DEFAULT_SELF_HEALING_INTERVAL_SECONDS,
        remove_failed_neighbors: bool = False,
        on_recovery: Optional[RecoveryCallback] = None,
    ) -> None:
        self.node = node
        self.neighbor_manager = neighbor_manager or NeighborManager(node.neighbors, self_node_id=node.node_id)
        self.topology = topology
        self.routing_manager = routing_manager
        self.neighbor_timeout = neighbor_timeout
        self.check_interval = check_interval
        self.remove_failed_neighbors = remove_failed_neighbors
        self.on_recovery = on_recovery
        self._stats = SelfHealingStats()
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    def start(self) -> None:
        if self.is_running:
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._run,
            name=f"meshlink-self-healing-{self.node.node_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
        self._thread = None

    def check_and_heal(self) -> list[RecoveryEvent]:
        stale_neighbors = (
            self.neighbor_manager.remove_stale(self.neighbor_timeout)
            if self.remove_failed_neighbors
            else self.neighbor_manager.mark_stale(self.neighbor_timeout)
        )
        return [self.handle_neighbor_lost(neighbor) for neighbor in stale_neighbors]

    def handle_neighbor_lost(self, neighbor: NodeInfo | str) -> RecoveryEvent:
        failed_node = neighbor.node_id if isinstance(neighbor, NodeInfo) else str(neighbor)
        self.neighbor_manager.mark_disconnected(failed_node)
        if failed_node in self.node.neighbors:
            self.node.neighbors[failed_node].status = NodeStatus.DISCONNECTED.value

        if self.topology:
            self.topology.remove_node(failed_node)

        removed_routes = self._purge_routes_for_failed_node(failed_node)
        self._refresh_routes()

        event = RecoveryEvent(
            failed_node=failed_node,
            removed_routes=removed_routes,
            active_routes={destination: dict(route) for destination, route in self.node.routing_table.items()},
        )

        with self._lock:
            self._stats.failures_detected += 1
            self._stats.routes_removed += len(removed_routes)

        if self.on_recovery:
            self.on_recovery(event)

        return event

    def recover_neighbor(self, node_id: str, ip: str, port: int) -> NodeInfo:
        neighbor = self.neighbor_manager.update_neighbor(node_id, ip, port)
        if self.topology:
            self.topology.add_link(self.node.node_id, node_id, cost=1)
        self._refresh_routes()
        return neighbor

    def stats(self) -> SelfHealingStats:
        with self._lock:
            return SelfHealingStats(
                failures_detected=self._stats.failures_detected,
                routes_removed=self._stats.routes_removed,
                recomputations=self._stats.recomputations,
            )

    def _purge_routes_for_failed_node(self, failed_node: str) -> list[str]:
        removed_routes = []
        for destination, route in list(self.node.routing_table.items()):
            if destination == failed_node or route.get("next_hop") == failed_node:
                removed_routes.append(destination)
                self.node.routing_table.pop(destination, None)
        return removed_routes

    def _refresh_routes(self) -> None:
        if self.routing_manager:
            self.routing_manager.refresh_routes()
            with self._lock:
                self._stats.recomputations += 1

    def _run(self) -> None:
        while self._running.is_set():
            self.check_and_heal()
            self._running.wait(self.check_interval)

