from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from typing import Optional

from core.constants import NodeStatus
from core.node import NodeInfo


class NeighborManager:
    def __init__(self, neighbors: Optional[dict[str, NodeInfo]] = None, self_node_id: Optional[str] = None):
        self._neighbors = neighbors if neighbors is not None else {}
        self.self_node_id = self_node_id
        self._lock = threading.RLock()

    def update_neighbor(
        self,
        node_id: str,
        ip: str,
        port: int,
        now: Optional[float] = None,
    ) -> Optional[NodeInfo]:
        if self.self_node_id and node_id == self.self_node_id:
            return None

        if not node_id:
            raise ValueError("neighbor node_id is required")

        if not 0 <= port <= 65535:
            raise ValueError("neighbor port must be between 0 and 65535")

        seen_at = time.time() if now is None else now

        with self._lock:
            neighbor = self._neighbors.get(node_id)
            if neighbor:
                neighbor.ip = ip
                neighbor.port = port
                neighbor.last_seen = seen_at
                neighbor.status = NodeStatus.ACTIVE.value
                return neighbor

            neighbor = NodeInfo(
                node_id=node_id,
                ip=ip,
                port=port,
                last_seen=seen_at,
                status=NodeStatus.ACTIVE.value,
            )
            self._neighbors[node_id] = neighbor
            return neighbor

    def get_neighbor(self, node_id: str) -> Optional[NodeInfo]:
        with self._lock:
            return self._neighbors.get(node_id)

    def remove_neighbor(self, node_id: str) -> Optional[NodeInfo]:
        with self._lock:
            return self._neighbors.pop(node_id, None)

    def mark_disconnected(self, node_id: str) -> Optional[NodeInfo]:
        with self._lock:
            neighbor = self._neighbors.get(node_id)
            if neighbor:
                neighbor.status = NodeStatus.DISCONNECTED.value
            return neighbor

    def stale_neighbors(self, timeout_seconds: float, now: Optional[float] = None) -> list[NodeInfo]:
        cutoff = (time.time() if now is None else now) - timeout_seconds
        with self._lock:
            return [
                neighbor
                for neighbor in self._neighbors.values()
                if neighbor.status == NodeStatus.ACTIVE.value and neighbor.last_seen < cutoff
            ]

    def mark_stale(self, timeout_seconds: float, now: Optional[float] = None) -> list[NodeInfo]:
        stale = self.stale_neighbors(timeout_seconds=timeout_seconds, now=now)
        with self._lock:
            for neighbor in stale:
                neighbor.status = NodeStatus.DISCONNECTED.value
        return stale

    def remove_stale(self, timeout_seconds: float, now: Optional[float] = None) -> list[NodeInfo]:
        stale = self.stale_neighbors(timeout_seconds=timeout_seconds, now=now)
        with self._lock:
            for neighbor in stale:
                self._neighbors.pop(neighbor.node_id, None)
        return stale

    def all_neighbors(self) -> list[NodeInfo]:
        with self._lock:
            return list(self._neighbors.values())

    def active_neighbors(self) -> list[NodeInfo]:
        with self._lock:
            return [
                neighbor
                for neighbor in self._neighbors.values()
                if neighbor.status == NodeStatus.ACTIVE.value
            ]

    def as_table(self, neighbors: Optional[Iterable[NodeInfo]] = None) -> list[dict]:
        selected_neighbors = self.all_neighbors() if neighbors is None else list(neighbors)
        return [neighbor.as_dict() for neighbor in selected_neighbors]

