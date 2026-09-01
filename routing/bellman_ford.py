"""Module 14 — Bellman-Ford / Distance-Vector Route Computation.

A pure-Python implementation of the Bellman-Ford relaxation step used
by the Distance-Vector protocol.

Unlike Dijkstra (which runs on a full topology graph), Bellman-Ford
works with **partial information**: each node only knows its own
routing table and the distance vectors advertised by its direct
neighbours.

Core concept::

    For every destination D advertised by neighbor N:
        new_cost = cost(self → N) + cost_advertised_by_N(N → D)
        if new_cost < current_cost(self → D):
            update route: next_hop = N, cost = new_cost

This module is a standalone function so it can be tested without
networking infrastructure.
"""

from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional


INFINITY = float("inf")


@dataclass(slots=True)
class DVRoute:
    """A single entry in a Distance-Vector routing table.

    Attributes
    ----------
    destination : str
        Target node ID.
    next_hop : str
        The direct neighbour to forward packets through.
    cost : float
        Cumulative cost to reach *destination* via *next_hop*.
    last_updated : float
        Timestamp of the last update (for expiry).
    """

    destination: str
    next_hop: str
    cost: float
    last_updated: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class BellmanFordResult:
    """Outcome of a single relaxation pass.

    Attributes
    ----------
    changed : bool
        Whether any route was added or improved.
    added : list[str]
        Destinations that were newly added.
    improved : list[str]
        Destinations whose cost decreased.
    """

    changed: bool
    added: list[str] = field(default_factory=list)
    improved: list[str] = field(default_factory=list)


def bellman_ford_relax(
    self_node_id: str,
    current_routes: dict[str, DVRoute],
    neighbor_id: str,
    neighbor_cost: int,
    neighbor_vector: dict[str, float],
    now: Optional[float] = None,
) -> BellmanFordResult:
    """Apply one Bellman-Ford relaxation from a single neighbour.

    Parameters
    ----------
    self_node_id : str
        This node's ID (excluded from route targets).
    current_routes : dict[str, DVRoute]
        Current routing table — **mutated in-place** if routes improve.
    neighbor_id : str
        The advertising neighbour.
    neighbor_cost : int
        Direct cost to *neighbor_id* (typically 1 for hop-count).
    neighbor_vector : dict[str, float]
        ``{destination: cost}`` as advertised by *neighbor_id*.
    now : float, optional
        Current timestamp; defaults to ``time.time()``.

    Returns
    -------
    BellmanFordResult
        Whether the table changed, and which destinations were affected.
    """
    ts = now if now is not None else time.time()
    added: list[str] = []
    improved: list[str] = []

    # Always ensure there is a direct route to the neighbour itself.
    if neighbor_id != self_node_id:
        existing = current_routes.get(neighbor_id)
        if existing is None:
            current_routes[neighbor_id] = DVRoute(
                destination=neighbor_id,
                next_hop=neighbor_id,
                cost=neighbor_cost,
                last_updated=ts,
            )
            added.append(neighbor_id)
        elif neighbor_cost < existing.cost:
            existing.next_hop = neighbor_id
            existing.cost = neighbor_cost
            existing.last_updated = ts
            improved.append(neighbor_id)
        else:
            # Refresh timestamp even if cost unchanged.
            if existing.next_hop == neighbor_id:
                existing.last_updated = ts

    # Relax each destination advertised by the neighbour.
    for dest, advertised_cost in neighbor_vector.items():
        if dest == self_node_id:
            continue

        new_cost = neighbor_cost + advertised_cost
        existing = current_routes.get(dest)

        if existing is None:
            current_routes[dest] = DVRoute(
                destination=dest,
                next_hop=neighbor_id,
                cost=new_cost,
                last_updated=ts,
            )
            added.append(dest)
        elif new_cost < existing.cost:
            existing.next_hop = neighbor_id
            existing.cost = new_cost
            existing.last_updated = ts
            improved.append(dest)
        elif existing.next_hop == neighbor_id:
            # The route goes through this neighbour — update cost even
            # if it increased (path may have become longer).
            if new_cost != existing.cost:
                existing.cost = new_cost
                existing.last_updated = ts
                improved.append(dest)
            else:
                existing.last_updated = ts

    changed = bool(added or improved)
    return BellmanFordResult(changed=changed, added=added, improved=improved)


def expire_routes(
    routes: dict[str, DVRoute],
    max_age_seconds: float,
    now: Optional[float] = None,
) -> list[str]:
    """Remove routes that have not been refreshed within *max_age_seconds*.

    Returns the list of expired destination IDs.
    """
    ts = now if now is not None else time.time()
    cutoff = ts - max_age_seconds
    expired: list[str] = []
    for dest in list(routes):
        if routes[dest].last_updated < cutoff:
            del routes[dest]
            expired.append(dest)
    return expired


def routes_to_vector(routes: dict[str, DVRoute]) -> dict[str, float]:
    """Convert a routing table to a distance vector ``{dest: cost}``."""
    return {dest: route.cost for dest, route in routes.items()}


def format_dv_table(routes: dict[str, DVRoute]) -> str:
    """Pretty-print a distance-vector routing table."""
    if not routes:
        return "(no routes)"
    lines = [f"{'Destination':<16}{'Next Hop':<16}{'Cost':>6}"]
    lines.append("-" * 38)
    for dest in sorted(routes):
        r = routes[dest]
        lines.append(f"{r.destination:<16}{r.next_hop:<16}{r.cost:>6.0f}")
    return "\n".join(lines)
