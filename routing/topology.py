"""Module 10 — Network Topology Management.

Maintains the mesh network graph as an adjacency-list dictionary.
Every node in the mesh keeps a ``NetworkTopology`` instance that is
updated as neighbours are discovered, heartbeats arrive, and
link-state advertisements are flooded.

Internal representation::

    graph = {
        "A": {"B": 1, "C": 1},
        "B": {"A": 1, "D": 1},
        "C": {"A": 1, "D": 1},
        "D": {"B": 1, "C": 1},
    }

Edge costs start as simple hop-count (1).  Later modules can
incorporate latency, packet-loss, or link-quality metrics.

Thread safety: all mutations are guarded by a reentrant lock so
that the discovery service, heartbeat service, and link-state
module can update the topology concurrently.
"""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True, slots=True)
class TopologyChange:
    """Describes a single topology mutation for logging / callbacks."""

    change_type: str          # "add_link", "remove_link", "add_node", "remove_node", "update_cost"
    node_a: str
    node_b: Optional[str] = None
    cost: Optional[int] = None
    timestamp: float = field(default_factory=time.time)


class NetworkTopology:
    """Weighted, undirected graph representing the mesh network.

    Parameters
    ----------
    self_node_id : str
        The node ID of the local device.
    on_change : optional callback
        Called with a ``TopologyChange`` after every mutation.
    """

    def __init__(
        self,
        self_node_id: Optional[str] = None,
        on_change: Optional[callable] = None,
    ) -> None:
        self.self_node_id = self_node_id
        self.on_change = on_change
        self._graph: dict[str, dict[str, int]] = {}
        self._sequence_numbers: dict[str, int] = {}  # node_id -> latest LSA seq
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Graph queries
    # ------------------------------------------------------------------

    def nodes(self) -> list[str]:
        """Return all node IDs in the topology."""
        with self._lock:
            return list(self._graph.keys())

    def neighbors_of(self, node_id: str) -> dict[str, int]:
        """Return ``{neighbor_id: cost}`` for *node_id*, or empty dict."""
        with self._lock:
            return dict(self._graph.get(node_id, {}))

    def has_node(self, node_id: str) -> bool:
        with self._lock:
            return node_id in self._graph

    def has_link(self, node_a: str, node_b: str) -> bool:
        with self._lock:
            return node_b in self._graph.get(node_a, {})

    def link_cost(self, node_a: str, node_b: str) -> Optional[int]:
        """Return the cost of the direct link, or ``None`` if no link exists."""
        with self._lock:
            return self._graph.get(node_a, {}).get(node_b)

    def node_count(self) -> int:
        with self._lock:
            return len(self._graph)

    def edge_count(self) -> int:
        """Count of undirected edges (each pair counted once)."""
        with self._lock:
            total = sum(len(neighbors) for neighbors in self._graph.values())
            return total // 2

    def snapshot(self) -> dict[str, dict[str, int]]:
        """Return a deep copy of the entire graph dict."""
        with self._lock:
            return deepcopy(self._graph)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add_node(self, node_id: str) -> bool:
        """Ensure *node_id* exists in the graph.  Returns True if new."""
        with self._lock:
            if node_id in self._graph:
                return False
            self._graph[node_id] = {}
        self._emit(TopologyChange("add_node", node_a=node_id))
        return True

    def remove_node(self, node_id: str) -> bool:
        """Remove *node_id* and all its links.  Returns True if it existed."""
        with self._lock:
            if node_id not in self._graph:
                return False
            # Remove this node from all neighbours' adjacency lists.
            for neighbor_id in list(self._graph[node_id]):
                self._graph[neighbor_id].pop(node_id, None)
            del self._graph[node_id]
            self._sequence_numbers.pop(node_id, None)
        self._emit(TopologyChange("remove_node", node_a=node_id))
        return True

    def add_link(self, node_a: str, node_b: str, cost: int = 1) -> None:
        """Add or update a bidirectional link between *node_a* and *node_b*."""
        if cost < 0:
            raise ValueError("link cost must be non-negative")
        with self._lock:
            self._graph.setdefault(node_a, {})[node_b] = cost
            self._graph.setdefault(node_b, {})[node_a] = cost
        self._emit(TopologyChange("add_link", node_a=node_a, node_b=node_b, cost=cost))

    def remove_link(self, node_a: str, node_b: str) -> bool:
        """Remove the bidirectional link.  Returns True if it existed."""
        with self._lock:
            removed = False
            if node_a in self._graph and node_b in self._graph[node_a]:
                del self._graph[node_a][node_b]
                removed = True
            if node_b in self._graph and node_a in self._graph[node_b]:
                del self._graph[node_b][node_a]
                removed = True
        if removed:
            self._emit(TopologyChange("remove_link", node_a=node_a, node_b=node_b))
        return removed

    def update_cost(self, node_a: str, node_b: str, cost: int) -> bool:
        """Update the cost of an existing link.  Returns False if the link does not exist."""
        if cost < 0:
            raise ValueError("link cost must be non-negative")
        with self._lock:
            if node_b not in self._graph.get(node_a, {}):
                return False
            self._graph[node_a][node_b] = cost
            self._graph[node_b][node_a] = cost
        self._emit(TopologyChange("update_cost", node_a=node_a, node_b=node_b, cost=cost))
        return True

    # ------------------------------------------------------------------
    # Bulk updates from link-state advertisements
    # ------------------------------------------------------------------

    def update_from_neighbor_list(
        self,
        node_id: str,
        neighbors: dict[str, int],
        sequence_number: Optional[int] = None,
    ) -> bool:
        """Replace the adjacency list for *node_id* with *neighbors*.

        Used by the Link-State module to ingest a remote node's LSA.

        Parameters
        ----------
        node_id : str
            The advertising node.
        neighbors : dict[str, int]
            ``{neighbor_id: cost}`` as advertised by *node_id*.
        sequence_number : int, optional
            If provided, stale updates (lower or equal sequence) are ignored.

        Returns True if the topology was actually changed.
        """
        with self._lock:
            # Check staleness.
            if sequence_number is not None:
                last_seq = self._sequence_numbers.get(node_id, -1)
                if sequence_number <= last_seq:
                    return False
                self._sequence_numbers[node_id] = sequence_number

            old_neighbors = self._graph.get(node_id, {})
            if old_neighbors == neighbors:
                # Ensure node exists even if neighbors identical.
                self._graph.setdefault(node_id, {})
                return False

            # Remove stale links.
            for old_neighbor in set(old_neighbors) - set(neighbors):
                self._graph.get(old_neighbor, {}).pop(node_id, None)

            # Set new adjacency.
            self._graph[node_id] = dict(neighbors)
            for neighbor_id, cost in neighbors.items():
                self._graph.setdefault(neighbor_id, {})[node_id] = cost

        self._emit(TopologyChange("add_link", node_a=node_id, node_b="(bulk)"))
        return True

    def get_sequence_number(self, node_id: str) -> int:
        """Return the latest ingested LSA sequence number for *node_id*."""
        with self._lock:
            return self._sequence_numbers.get(node_id, 0)

    # ------------------------------------------------------------------
    # Convenience: build from NeighborManager
    # ------------------------------------------------------------------

    def sync_from_neighbors(self, neighbors: dict[str, Any]) -> None:
        """Rebuild local adjacency from the ``MeshNode.neighbors`` dict.

        Typically called after discovery / heartbeat changes.
        """
        if not self.self_node_id:
            return
        neighbor_costs = {nid: 1 for nid in neighbors if neighbors[nid].status == "ACTIVE"}
        self.update_from_neighbor_list(self.self_node_id, neighbor_costs)

    # ------------------------------------------------------------------
    # Pretty printing
    # ------------------------------------------------------------------

    def format_table(self) -> str:
        """Return a human-readable adjacency table."""
        with self._lock:
            if not self._graph:
                return "(empty topology)"
            lines = ["Node          Neighbors"]
            lines.append("-" * 40)
            for node_id in sorted(self._graph):
                neighbors = self._graph[node_id]
                if neighbors:
                    neighbor_str = ", ".join(
                        f"{nid}(cost={cost})" for nid, cost in sorted(neighbors.items())
                    )
                else:
                    neighbor_str = "(none)"
                lines.append(f"{node_id:14s}{neighbor_str}")
            return "\n".join(lines)

    def __repr__(self) -> str:
        return f"NetworkTopology(nodes={self.node_count()}, edges={self.edge_count()})"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _emit(self, change: TopologyChange) -> None:
        if self.on_change:
            self.on_change(change)
