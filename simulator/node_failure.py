"""Node failure simulation for Module 22."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class FailureEvent:
    node_id: str
    failed: bool
    timestamp: float = field(default_factory=time.time)


class NodeFailureSimulator:
    def __init__(self) -> None:
        self._failed_nodes: set[str] = set()
        self._events: list[FailureEvent] = []
        self._lock = threading.RLock()

    def fail_node(self, node_id: str) -> FailureEvent:
        with self._lock:
            self._failed_nodes.add(node_id)
            event = FailureEvent(node_id=node_id, failed=True)
            self._events.append(event)
            return event

    def recover_node(self, node_id: str) -> FailureEvent:
        with self._lock:
            self._failed_nodes.discard(node_id)
            event = FailureEvent(node_id=node_id, failed=False)
            self._events.append(event)
            return event

    def is_failed(self, node_id: str | None) -> bool:
        if node_id is None:
            return False
        with self._lock:
            return node_id in self._failed_nodes

    def failed_nodes(self) -> set[str]:
        with self._lock:
            return set(self._failed_nodes)

    def events(self) -> list[FailureEvent]:
        with self._lock:
            return list(self._events)

