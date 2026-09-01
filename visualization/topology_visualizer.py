"""Module 24 - Live network topology visualization.

The visualizer is dependency-free and can emit:

* JSON-ready topology state for APIs
* ASCII adjacency tables for terminal demos
* SVG markup for the web dashboard
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import math
import time
from typing import Optional

from core.constants import NodeStatus
from core.node import MeshNode
from routing.topology import NetworkTopology


@dataclass(frozen=True, slots=True)
class VisualNode:
    node_id: str
    status: str
    is_self: bool
    x: float
    y: float

    def to_dict(self) -> dict:
        return {
            "id": self.node_id,
            "status": self.status,
            "is_self": self.is_self,
            "x": self.x,
            "y": self.y,
        }


@dataclass(frozen=True, slots=True)
class VisualLink:
    source: str
    target: str
    cost: int
    active: bool = True

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "cost": self.cost,
            "active": self.active,
        }


@dataclass(frozen=True, slots=True)
class TopologySnapshot:
    node_id: str
    nodes: list[VisualNode]
    links: list[VisualLink]
    routes: dict[str, dict[str, int | str]]
    generated_at: float

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "nodes": [node.to_dict() for node in self.nodes],
            "links": [link.to_dict() for link in self.links],
            "routes": self.routes,
            "generated_at": self.generated_at,
        }


class TopologyVisualizer:
    def __init__(self, node: MeshNode, topology: Optional[NetworkTopology] = None) -> None:
        self.node = node
        self.topology = topology

    def snapshot(self) -> TopologySnapshot:
        graph = self._graph_snapshot()
        node_ids = sorted(set(graph) | {self.node.node_id} | set(self.node.neighbors))
        positions = _circular_layout(node_ids)

        nodes = [
            VisualNode(
                node_id=node_id,
                status=self._node_status(node_id),
                is_self=node_id == self.node.node_id,
                x=positions[node_id][0],
                y=positions[node_id][1],
            )
            for node_id in node_ids
        ]
        links = self._links_from_graph(graph)
        routes = {destination: dict(route) for destination, route in self.node.routing_table.items()}

        return TopologySnapshot(
            node_id=self.node.node_id,
            nodes=nodes,
            links=links,
            routes=routes,
            generated_at=time.time(),
        )

    def to_json_dict(self) -> dict:
        return self.snapshot().to_dict()

    def to_ascii(self) -> str:
        snapshot = self.snapshot()
        if not snapshot.nodes:
            return "(empty topology)"

        lines = ["Nodes"]
        lines.append("-----")
        for node in snapshot.nodes:
            marker = "*" if node.is_self else " "
            lines.append(f"{marker} {node.node_id:<16} {node.status}")

        lines.append("")
        lines.append("Links")
        lines.append("-----")
        if not snapshot.links:
            lines.append("(none)")
        else:
            for link in snapshot.links:
                state = "active" if link.active else "offline"
                lines.append(f"{link.source} --{link.cost}-- {link.target} ({state})")

        lines.append("")
        lines.append("Routes")
        lines.append("------")
        if not snapshot.routes:
            lines.append("(none)")
        else:
            for destination, route in sorted(snapshot.routes.items()):
                lines.append(f"{destination}: next_hop={route['next_hop']} cost={route['cost']}")

        return "\n".join(lines)

    def to_svg(self, width: int = 720, height: int = 420) -> str:
        snapshot = self.snapshot()
        if not snapshot.nodes:
            return f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Empty topology"></svg>'

        scale_x = width
        scale_y = height
        node_positions = {
            node.node_id: (node.x * scale_x, node.y * scale_y)
            for node in snapshot.nodes
        }

        parts = [
            f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Mesh topology">',
            '<rect x="0" y="0" width="100%" height="100%" fill="#f8fafc"/>',
        ]

        for link in snapshot.links:
            x1, y1 = node_positions[link.source]
            x2, y2 = node_positions[link.target]
            stroke = "#64748b" if link.active else "#cbd5e1"
            dash = "" if link.active else ' stroke-dasharray="6 5"'
            parts.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="{stroke}" stroke-width="2"{dash}/>'
            )

        for node in snapshot.nodes:
            x, y = node_positions[node.node_id]
            fill = _status_color(node.status, node.is_self)
            label = html.escape(node.node_id)
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="22" fill="{fill}" stroke="#0f172a" stroke-width="2"/>')
            parts.append(
                f'<text x="{x:.1f}" y="{y + 40:.1f}" text-anchor="middle" '
                f'font-size="13" font-family="Arial, sans-serif" fill="#0f172a">{label}</text>'
            )

        parts.append("</svg>")
        return "\n".join(parts)

    def _graph_snapshot(self) -> dict[str, dict[str, int]]:
        if self.topology:
            graph = self.topology.snapshot()
        else:
            graph = {}

        graph.setdefault(self.node.node_id, {})
        for neighbor_id, neighbor in self.node.neighbors.items():
            graph.setdefault(neighbor_id, {})
            if neighbor.status == NodeStatus.ACTIVE.value:
                graph[self.node.node_id][neighbor_id] = 1
                graph[neighbor_id][self.node.node_id] = 1
        return graph

    def _links_from_graph(self, graph: dict[str, dict[str, int]]) -> list[VisualLink]:
        links = []
        seen = set()
        for source, neighbors in graph.items():
            for target, cost in neighbors.items():
                key = tuple(sorted((source, target)))
                if key in seen:
                    continue
                seen.add(key)
                links.append(
                    VisualLink(
                        source=source,
                        target=target,
                        cost=int(cost),
                        active=self._node_status(source) == NodeStatus.ACTIVE.value
                        and self._node_status(target) == NodeStatus.ACTIVE.value,
                    )
                )
        return links

    def _node_status(self, node_id: str) -> str:
        if node_id == self.node.node_id:
            return self.node.status
        neighbor = self.node.neighbors.get(node_id)
        if neighbor:
            return neighbor.status
        return NodeStatus.ACTIVE.value


def _circular_layout(node_ids: list[str]) -> dict[str, tuple[float, float]]:
    if not node_ids:
        return {}
    if len(node_ids) == 1:
        return {node_ids[0]: (0.5, 0.5)}

    radius = 0.34
    center_x = 0.5
    center_y = 0.48
    return {
        node_id: (
            center_x + radius * math.cos((2 * math.pi * index / len(node_ids)) - math.pi / 2),
            center_y + radius * math.sin((2 * math.pi * index / len(node_ids)) - math.pi / 2),
        )
        for index, node_id in enumerate(node_ids)
    }


def _status_color(status: str, is_self: bool = False) -> str:
    if is_self:
        return "#2563eb"
    if status == NodeStatus.ACTIVE.value:
        return "#16a34a"
    if status == NodeStatus.DISCONNECTED.value:
        return "#f59e0b"
    return "#94a3b8"

