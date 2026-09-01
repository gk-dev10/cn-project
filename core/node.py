from __future__ import annotations

from dataclasses import dataclass, field
import time
import uuid
from typing import Callable, Optional

from core.constants import DEFAULT_BIND_IP, DEFAULT_PORT, NODE_ID_PREFIX, NodeStatus


@dataclass(slots=True)
class NodeInfo:
    node_id: str
    ip: str
    port: int
    last_seen: float = field(default_factory=time.time)
    status: str = NodeStatus.ACTIVE.value

    def refresh(self) -> None:
        self.last_seen = time.time()
        self.status = NodeStatus.ACTIVE.value

    def as_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "ip": self.ip,
            "port": self.port,
            "last_seen": self.last_seen,
            "status": self.status,
        }


class MeshNode:
    def __init__(self, node_id: Optional[str] = None, ip: str = DEFAULT_BIND_IP, port: int = DEFAULT_PORT):
        self.node_id = node_id or self.generate_node_id()
        self.ip = ip
        self.port = self._validate_port(port)
        self.status = NodeStatus.ACTIVE.value
        self.neighbors: dict[str, NodeInfo] = {}
        self.routing_table: dict[str, dict[str, int | str]] = {}
        self.created_at = time.time()
        self.udp_socket = None

    @staticmethod
    def _validate_port(port: int) -> int:
        if not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("port must be an integer between 0 and 65535")
        return port

    @classmethod
    def generate_node_id(cls, prefix: str = NODE_ID_PREFIX) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8].upper()}"

    def as_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "ip": self.ip,
            "port": self.port,
            "last_seen": self.created_at,
            "status": self.status,
        }

    def start_networking(self, on_packet: Optional[Callable[[dict, tuple[str, int]], None]] = None) -> tuple[str, int]:
        from transport.udp_socket import UDPSocket

        if self.udp_socket and self.udp_socket.is_running:
            return self.udp_socket.local_address

        self.udp_socket = UDPSocket(host=self.ip, port=self.port, on_packet=on_packet)
        local_host, local_port = self.udp_socket.start_socket()
        self.port = local_port
        self.status = NodeStatus.ACTIVE.value
        return local_host, local_port

    def stop_networking(self) -> None:
        if self.udp_socket:
            self.udp_socket.stop_socket()
        self.status = NodeStatus.STOPPED.value

    def add_neighbor(self, node_id: str, ip: str, port: int) -> NodeInfo:
        port = self._validate_port(port)
        if node_id in self.neighbors:
            neighbor = self.neighbors[node_id]
            neighbor.ip = ip
            neighbor.port = port
            neighbor.refresh()
            return neighbor

        neighbor = NodeInfo(node_id=node_id, ip=ip, port=port)
        self.neighbors[node_id] = neighbor
        return neighbor

    def remove_neighbor(self, node_id: str) -> None:
        self.neighbors.pop(node_id, None)

    def mark_neighbor_disconnected(self, node_id: str) -> None:
        if node_id in self.neighbors:
            self.neighbors[node_id].status = NodeStatus.DISCONNECTED.value

    def update_route(self, destination: str, next_hop: str, cost: int = 1) -> None:
        if cost < 0:
            raise ValueError("route cost must be non-negative")
        self.routing_table[destination] = {"next_hop": next_hop, "cost": cost}

    def get_next_hop(self, destination: str) -> Optional[str]:
        route = self.routing_table.get(destination)
        if not route:
            return None
        return str(route["next_hop"])

    def __repr__(self) -> str:
        return f"MeshNode(node_id={self.node_id!r}, ip={self.ip!r}, port={self.port}, status={self.status!r})"

