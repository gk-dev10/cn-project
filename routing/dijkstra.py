"""Module 12 — Dijkstra's Shortest-Path Algorithm.

A pure-Python implementation using a min-heap priority queue.

Input:  a weighted graph as ``dict[str, dict[str, int]]``
        (the same structure maintained by ``NetworkTopology``).

Output: for a given source node:
    * ``distances``  — shortest cost to every reachable node
    * ``previous``   — predecessor on the shortest path (for path reconstruction)
    * routing table  — ``{destination: (next_hop, cost)}``

The implementation is a standalone function so it can be unit-tested
without any networking infrastructure.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Optional


INFINITY = float("inf")


@dataclass(frozen=True, slots=True)
class DijkstraResult:
    """Immutable result of a Dijkstra run.

    Attributes
    ----------
    source : str
        The source node for which shortest paths were computed.
    distances : dict[str, int | float]
        ``{node_id: shortest_cost}``.  Unreachable nodes have ``inf``.
    previous : dict[str, str | None]
        ``{node_id: predecessor_node_id}`` on the shortest path.
        The source maps to ``None``.
    """

    source: str
    distances: dict[str, float]
    previous: dict[str, Optional[str]]

    def shortest_path(self, destination: str) -> Optional[list[str]]:
        """Reconstruct the shortest path from *source* to *destination*.

        Returns a list of node IDs ``[source, …, destination]`` or ``None``
        if *destination* is unreachable.
        """
        if destination not in self.distances or self.distances[destination] == INFINITY:
            return None
        path: list[str] = []
        current: Optional[str] = destination
        while current is not None:
            path.append(current)
            current = self.previous.get(current)
        path.reverse()
        return path

    def next_hop(self, destination: str) -> Optional[str]:
        """Return the first hop on the shortest path to *destination*.

        Returns ``None`` if *destination* is unreachable or is the source
        itself.
        """
        path = self.shortest_path(destination)
        if path is None or len(path) < 2:
            return None
        return path[1]

    def routing_table(self) -> dict[str, tuple[str, float]]:
        """Build a routing table ``{destination: (next_hop, cost)}``.

        Only reachable, non-source destinations are included.
        """
        table: dict[str, tuple[str, float]] = {}
        for node_id, cost in self.distances.items():
            if node_id == self.source or cost == INFINITY:
                continue
            hop = self.next_hop(node_id)
            if hop is not None:
                table[node_id] = (hop, cost)
        return table


def run_dijkstra(
    graph: dict[str, dict[str, int]],
    source: str,
) -> DijkstraResult:
    """Run Dijkstra's algorithm on *graph* from *source*.

    Parameters
    ----------
    graph : dict[str, dict[str, int]]
        Adjacency list.  ``graph[node] = {neighbor: cost, …}``.
    source : str
        The starting node.

    Returns
    -------
    DijkstraResult
        Contains distances, predecessors, and convenience methods for
        path reconstruction and routing-table generation.

    Raises
    ------
    KeyError
        If *source* is not in *graph*.
    """
    if source not in graph:
        raise KeyError(f"source node {source!r} not found in graph")

    distances: dict[str, float] = {node: INFINITY for node in graph}
    distances[source] = 0
    previous: dict[str, Optional[str]] = {node: None for node in graph}
    visited: set[str] = set()

    # Priority queue: (cost, node_id)
    heap: list[tuple[float, str]] = [(0, source)]

    while heap:
        current_cost, current_node = heapq.heappop(heap)

        if current_node in visited:
            continue
        visited.add(current_node)

        for neighbor, edge_cost in graph.get(current_node, {}).items():
            if neighbor in visited:
                continue
            new_cost = current_cost + edge_cost
            if new_cost < distances.get(neighbor, INFINITY):
                distances[neighbor] = new_cost
                previous[neighbor] = current_node
                heapq.heappush(heap, (new_cost, neighbor))

    return DijkstraResult(source=source, distances=distances, previous=previous)
