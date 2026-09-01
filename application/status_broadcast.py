"""Module 20 - Emergency status broadcast.

Broadcasts statuses such as "SAFE" through known neighbors and avoids
processing the same broadcast more than once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import itertools
import threading
import time
from typing import Callable, Optional
import uuid

from core.constants import DEFAULT_STATUS_VALUE, DEFAULT_TTL, NodeStatus, PacketType
from core.node import MeshNode
from core.packet import create_packet
from transport.udp_socket import UDPSocket


StatusCallback = Callable[["StatusMessage"], None]


@dataclass(frozen=True, slots=True)
class StatusMessage:
    broadcast_id: str
    source: str
    status: str
    message: Optional[str]
    location: Optional[dict]
    timestamp: float
    received_at: float = field(default_factory=time.time)


class StatusBroadcastService:
    def __init__(
        self,
        node: MeshNode,
        udp_socket: Optional[UDPSocket] = None,
        targets: Optional[list[tuple[str, int]]] = None,
        on_status: Optional[StatusCallback] = None,
    ) -> None:
        self.node = node
        self.udp_socket = udp_socket
        self.targets = list(targets or [])
        self.on_status = on_status
        self.seen_broadcasts: set[str] = set()
        self.received_statuses: list[StatusMessage] = []
        self._sequence_numbers = itertools.count(1)
        self._lock = threading.RLock()
        self._handler_registered = False

    def start(self) -> None:
        self._ensure_socket()
        if not self._handler_registered:
            self.udp_socket.add_packet_handler(self.handle_packet)
            self._handler_registered = True

    def stop(self) -> None:
        if self._handler_registered and self.udp_socket:
            self.udp_socket.remove_packet_handler(self.handle_packet)
            self._handler_registered = False

    def send_safe_status(self, message: Optional[str] = None, ttl: int = DEFAULT_TTL) -> str:
        return self.broadcast_status(status=DEFAULT_STATUS_VALUE, message=message, ttl=ttl)

    def broadcast_status(
        self,
        status: str,
        message: Optional[str] = None,
        location: Optional[dict] = None,
        ttl: int = DEFAULT_TTL,
    ) -> str:
        self._ensure_socket()
        broadcast_id = uuid.uuid4().hex
        payload = {
            "broadcast_id": broadcast_id,
            "origin": self.node.node_id,
            "status": status,
            "message": message,
            "location": location,
            "timestamp": time.time(),
        }
        packet = create_packet(
            packet_type=PacketType.STATUS,
            source=self.node.node_id,
            destination=None,
            sequence_number=next(self._sequence_numbers),
            ttl=ttl,
            payload=payload,
        )

        with self._lock:
            self.seen_broadcasts.add(broadcast_id)

        for target in self._fanout_targets():
            self.udp_socket.send_packet(packet, target)

        return broadcast_id

    def handle_packet(self, packet: dict, address: tuple[str, int]) -> Optional[StatusMessage]:
        if packet.get("type") != PacketType.STATUS.value:
            return None

        payload = packet.get("payload")
        if not isinstance(payload, dict):
            return None

        broadcast_id = str(payload.get("broadcast_id", ""))
        if not broadcast_id:
            return None

        with self._lock:
            if broadcast_id in self.seen_broadcasts:
                return None
            self.seen_broadcasts.add(broadcast_id)

        status_message = StatusMessage(
            broadcast_id=broadcast_id,
            source=str(payload.get("origin") or packet.get("source", "")),
            status=str(payload.get("status", "")),
            message=payload.get("message"),
            location=payload.get("location") if isinstance(payload.get("location"), dict) else None,
            timestamp=float(payload.get("timestamp", time.time())),
        )

        with self._lock:
            self.received_statuses.append(status_message)

        if self.on_status:
            self.on_status(status_message)

        self._forward_status(packet, address)
        return status_message

    def _forward_status(self, packet: dict, incoming_address: tuple[str, int]) -> None:
        ttl = int(packet.get("ttl", 0))
        if ttl <= 1:
            return

        forwarded = create_packet(
            packet_type=PacketType.STATUS,
            source=str(packet.get("source", self.node.node_id)),
            destination=None,
            sequence_number=int(packet.get("sequence_number", 0)),
            ttl=ttl - 1,
            payload=packet.get("payload"),
        )

        for target in self._fanout_targets(exclude=incoming_address):
            self.udp_socket.send_packet(forwarded, target)

    def _fanout_targets(self, exclude: Optional[tuple[str, int]] = None) -> list[tuple[str, int]]:
        targets = list(self.targets)
        targets.extend(
            (neighbor.ip, neighbor.port)
            for neighbor in self.node.neighbors.values()
            if neighbor.status == NodeStatus.ACTIVE.value
        )
        unique_targets = list(dict.fromkeys(targets))
        if exclude is None:
            return unique_targets
        return [target for target in unique_targets if target != exclude]

    def _ensure_socket(self) -> None:
        if self.udp_socket:
            if not self.udp_socket.is_running:
                self.udp_socket.start_socket()
            return

        self.node.start_networking()
        self.udp_socket = self.node.udp_socket

