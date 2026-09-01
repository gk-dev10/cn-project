from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Iterable
from typing import Callable, Optional

from core.constants import (
    DEFAULT_BROADCAST_ADDRESS,
    DEFAULT_DISCOVERY_INTERVAL_SECONDS,
    DEFAULT_TTL,
    PacketType,
)
from core.node import MeshNode, NodeInfo
from core.packet import create_packet
from discovery.neighbor_manager import NeighborManager
from transport.udp_socket import UDPSocket


NeighborCallback = Callable[[NodeInfo], None]


class DiscoveryService:
    def __init__(
        self,
        node: MeshNode,
        udp_socket: Optional[UDPSocket] = None,
        neighbor_manager: Optional[NeighborManager] = None,
        broadcast_address: Optional[str] = DEFAULT_BROADCAST_ADDRESS,
        broadcast_port: Optional[int] = None,
        interval: float = DEFAULT_DISCOVERY_INTERVAL_SECONDS,
        targets: Optional[Iterable[tuple[str, int]]] = None,
        on_neighbor_discovered: Optional[NeighborCallback] = None,
    ):
        self.node = node
        self.udp_socket = udp_socket
        self.neighbor_manager = neighbor_manager or NeighborManager(node.neighbors, self_node_id=node.node_id)
        self.broadcast_address = broadcast_address
        self.broadcast_port = broadcast_port
        self.interval = interval
        self.targets = list(targets or [])
        self.on_neighbor_discovered = on_neighbor_discovered
        self._sequence_numbers = itertools.count(1)
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    def start(self) -> None:
        if self.is_running:
            return

        self._ensure_socket()
        self.udp_socket.add_packet_handler(self.handle_packet)
        self._running.set()
        self._thread = threading.Thread(
            target=self._run,
            name=f"meshlink-discovery-{self.node.node_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self.udp_socket:
            self.udp_socket.remove_packet_handler(self.handle_packet)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
        self._thread = None

    def send_discovery(self) -> None:
        for target in self._discovery_targets():
            self.udp_socket.send_packet(self._build_packet(PacketType.DISCOVERY), target)

    def handle_packet(self, packet: dict, address: tuple[str, int]) -> None:
        packet_type = packet.get("type")
        if packet_type not in {PacketType.DISCOVERY.value, PacketType.DISCOVERY_RESPONSE.value}:
            return

        neighbor = self._register_neighbor_from_packet(packet, address)
        if not neighbor:
            return

        if self.on_neighbor_discovered:
            self.on_neighbor_discovered(neighbor)

        if packet_type == PacketType.DISCOVERY.value:
            response_target = (address[0], neighbor.port)
            self.udp_socket.send_packet(self._build_packet(PacketType.DISCOVERY_RESPONSE), response_target)

    def _ensure_socket(self) -> None:
        if self.udp_socket:
            if not self.udp_socket.is_running:
                self.udp_socket.start_socket()
            return

        self.node.start_networking()
        self.udp_socket = self.node.udp_socket

    def _run(self) -> None:
        while self._running.is_set():
            self.send_discovery()
            self._running.wait(self.interval)

    def _build_packet(self, packet_type: PacketType) -> dict:
        return create_packet(
            packet_type=packet_type,
            source=self.node.node_id,
            destination=None,
            sequence_number=next(self._sequence_numbers),
            ttl=DEFAULT_TTL,
            payload={
                "node_id": self.node.node_id,
                "ip": self._advertised_ip(),
                "port": self.node.port,
                "status": self.node.status,
                "timestamp": time.time(),
            },
        )

    def _register_neighbor_from_packet(self, packet: dict, address: tuple[str, int]) -> Optional[NodeInfo]:
        payload = packet.get("payload") if isinstance(packet.get("payload"), dict) else {}
        node_id = str(payload.get("node_id") or packet.get("source") or "")
        if node_id == self.node.node_id:
            return None

        advertised_ip = str(payload.get("ip") or address[0])
        ip = address[0] if advertised_ip in {"0.0.0.0", "::", ""} else advertised_ip
        port = int(payload.get("port") or address[1])
        return self.neighbor_manager.update_neighbor(node_id=node_id, ip=ip, port=port)

    def _discovery_targets(self) -> list[tuple[str, int]]:
        targets = list(self.targets)
        if self.broadcast_address:
            targets.append((self.broadcast_address, self.broadcast_port or self.node.port))
        return list(dict.fromkeys(targets))

    def _advertised_ip(self) -> str:
        if self.node.ip in {"0.0.0.0", "::"} and self.udp_socket:
            return self.udp_socket.local_address[0]
        return self.node.ip
