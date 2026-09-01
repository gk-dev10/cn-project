from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Iterable
from typing import Callable, Optional

from core.constants import (
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    DEFAULT_NEIGHBOR_TIMEOUT_SECONDS,
    DEFAULT_STALE_CHECK_INTERVAL_SECONDS,
    DEFAULT_TTL,
    PacketType,
)
from core.node import MeshNode, NodeInfo
from core.packet import create_packet
from discovery.neighbor_manager import NeighborManager
from transport.udp_socket import UDPSocket


NeighborCallback = Callable[[NodeInfo], None]


class HeartbeatService:
    def __init__(
        self,
        node: MeshNode,
        udp_socket: Optional[UDPSocket] = None,
        neighbor_manager: Optional[NeighborManager] = None,
        interval: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        neighbor_timeout: float = DEFAULT_NEIGHBOR_TIMEOUT_SECONDS,
        stale_check_interval: float = DEFAULT_STALE_CHECK_INTERVAL_SECONDS,
        targets: Optional[Iterable[tuple[str, int]]] = None,
        remove_stale: bool = False,
        on_neighbor_lost: Optional[NeighborCallback] = None,
    ):
        self.node = node
        self.udp_socket = udp_socket
        self.neighbor_manager = neighbor_manager or NeighborManager(node.neighbors, self_node_id=node.node_id)
        self.interval = interval
        self.neighbor_timeout = neighbor_timeout
        self.stale_check_interval = stale_check_interval
        self.targets = list(targets or [])
        self.remove_stale = remove_stale
        self.on_neighbor_lost = on_neighbor_lost
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
            name=f"meshlink-heartbeat-{self.node.node_id}",
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

    def send_heartbeat(self) -> None:
        packet = self._build_packet()
        for target in self._heartbeat_targets():
            self.udp_socket.send_packet(packet, target)

    def check_failures(self) -> list[NodeInfo]:
        stale_neighbors = (
            self.neighbor_manager.remove_stale(self.neighbor_timeout)
            if self.remove_stale
            else self.neighbor_manager.mark_stale(self.neighbor_timeout)
        )
        if self.on_neighbor_lost:
            for neighbor in stale_neighbors:
                self.on_neighbor_lost(neighbor)
        return stale_neighbors

    def handle_packet(self, packet: dict, address: tuple[str, int]) -> None:
        if packet.get("type") != PacketType.HEARTBEAT.value:
            return

        payload = packet.get("payload") if isinstance(packet.get("payload"), dict) else {}
        node_id = str(payload.get("node_id") or packet.get("source") or "")
        if node_id == self.node.node_id:
            return

        advertised_ip = str(payload.get("ip") or address[0])
        ip = address[0] if advertised_ip in {"0.0.0.0", "::", ""} else advertised_ip
        port = int(payload.get("port") or address[1])
        self.neighbor_manager.update_neighbor(node_id=node_id, ip=ip, port=port)

    def _ensure_socket(self) -> None:
        if self.udp_socket:
            if not self.udp_socket.is_running:
                self.udp_socket.start_socket()
            return

        self.node.start_networking()
        self.udp_socket = self.node.udp_socket

    def _run(self) -> None:
        next_heartbeat_at = 0.0
        next_stale_check_at = 0.0

        while self._running.is_set():
            now = time.time()
            if now >= next_heartbeat_at:
                self.send_heartbeat()
                next_heartbeat_at = now + self.interval

            if now >= next_stale_check_at:
                self.check_failures()
                next_stale_check_at = now + self.stale_check_interval

            self._running.wait(min(self.interval, self.stale_check_interval, 0.2))

    def _build_packet(self) -> dict:
        return create_packet(
            packet_type=PacketType.HEARTBEAT,
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

    def _heartbeat_targets(self) -> list[tuple[str, int]]:
        targets = list(self.targets)
        targets.extend((neighbor.ip, neighbor.port) for neighbor in self.neighbor_manager.active_neighbors())
        return list(dict.fromkeys(targets))

    def _advertised_ip(self) -> str:
        if self.node.ip in {"0.0.0.0", "::"} and self.udp_socket:
            return self.udp_socket.local_address[0]
        return self.node.ip

