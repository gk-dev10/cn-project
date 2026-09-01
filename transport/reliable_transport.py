from __future__ import annotations

from dataclasses import dataclass, field
import itertools
import threading
import time
from typing import Any, Callable, Optional

from core.constants import (
    DEFAULT_RELIABLE_ACK_TIMEOUT_SECONDS,
    DEFAULT_RELIABLE_MAX_RETRIES,
    DEFAULT_RETRANSMISSION_CHECK_INTERVAL_SECONDS,
    DEFAULT_TTL,
    PacketType,
)
from core.node import MeshNode
from core.packet import create_packet
from transport.udp_socket import UDPSocket


ReliablePacketHandler = Callable[[dict, tuple[str, int]], None]
DeliveryFailureHandler = Callable[["DeliveryResult"], None]

RELIABLE_PACKET_TYPES = {
    PacketType.MESSAGE.value,
    PacketType.FILE_CHUNK.value,
    PacketType.STATUS.value,
}


@dataclass(slots=True)
class PendingPacket:
    sequence_number: int
    packet: dict
    address: tuple[str, int]
    sent_time: float
    retries: int = 0
    acknowledged: bool = False
    failed_reason: Optional[str] = None
    completed: threading.Event = field(default_factory=threading.Event)


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    sequence_number: int
    acknowledged: bool
    retries: int
    failed_reason: Optional[str] = None


class ReliableTransport:
    def __init__(
        self,
        node: MeshNode,
        udp_socket: Optional[UDPSocket] = None,
        ack_timeout: float = DEFAULT_RELIABLE_ACK_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_RELIABLE_MAX_RETRIES,
        check_interval: float = DEFAULT_RETRANSMISSION_CHECK_INTERVAL_SECONDS,
        on_packet: Optional[ReliablePacketHandler] = None,
        on_delivery_failed: Optional[DeliveryFailureHandler] = None,
    ):
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")

        self.node = node
        self.udp_socket = udp_socket
        self.ack_timeout = ack_timeout
        self.max_retries = max_retries
        self.check_interval = check_interval
        self.on_packet = on_packet
        self.on_delivery_failed = on_delivery_failed
        self.pending_packets: dict[int, PendingPacket] = {}
        self.received_sequences: set[tuple[str, int]] = set()
        self._sequence_numbers = itertools.count(1)
        self._ack_sequence_numbers = itertools.count(1)
        self._lock = threading.RLock()
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
            target=self._retransmission_loop,
            name=f"meshlink-reliable-transport-{self.node.node_id}",
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

    def send_message(
        self,
        destination: str,
        address: tuple[str, int],
        message: str,
        wait_for_ack: bool = True,
    ) -> DeliveryResult:
        return self.send_reliable(
            packet_type=PacketType.MESSAGE,
            destination=destination,
            address=address,
            payload=message,
            wait_for_ack=wait_for_ack,
        )

    def send_reliable(
        self,
        packet_type: PacketType | str,
        destination: str | None,
        address: tuple[str, int],
        payload: Any,
        ttl: int = DEFAULT_TTL,
        wait_for_ack: bool = True,
    ) -> DeliveryResult:
        self._ensure_started()
        sequence_number = next(self._sequence_numbers)
        packet = create_packet(
            packet_type=packet_type,
            source=self.node.node_id,
            destination=destination,
            sequence_number=sequence_number,
            ttl=ttl,
            payload=payload,
        )
        pending = PendingPacket(
            sequence_number=sequence_number,
            packet=packet,
            address=address,
            sent_time=time.time(),
        )

        with self._lock:
            self.pending_packets[sequence_number] = pending

        self.udp_socket.send_packet(packet, address)

        if not wait_for_ack:
            return DeliveryResult(sequence_number=sequence_number, acknowledged=False, retries=0)

        wait_seconds = self.ack_timeout * (self.max_retries + 1) + self.check_interval + 1
        pending.completed.wait(wait_seconds)
        if not pending.completed.is_set():
            self._mark_failed(pending, "ACK wait timed out")

        return DeliveryResult(
            sequence_number=sequence_number,
            acknowledged=pending.acknowledged,
            retries=pending.retries,
            failed_reason=pending.failed_reason,
        )

    def handle_packet(self, packet: dict, address: tuple[str, int]) -> None:
        packet_type = packet.get("type")
        if packet_type == PacketType.ACK.value:
            self._handle_ack(packet)
            return

        if packet_type not in RELIABLE_PACKET_TYPES:
            return

        if not self._is_for_this_node(packet):
            return

        self._send_ack(packet, address)

        sequence_key = (str(packet.get("source")), int(packet.get("sequence_number")))
        with self._lock:
            if sequence_key in self.received_sequences:
                return
            self.received_sequences.add(sequence_key)

        if self.on_packet:
            self.on_packet(packet, address)

    def _ensure_started(self) -> None:
        if not self.is_running:
            self.start()

    def _ensure_socket(self) -> None:
        if self.udp_socket:
            if not self.udp_socket.is_running:
                self.udp_socket.start_socket()
            return

        self.node.start_networking()
        self.udp_socket = self.node.udp_socket

    def _retransmission_loop(self) -> None:
        while self._running.is_set():
            self._retransmit_expired_packets()
            self._running.wait(self.check_interval)

    def _retransmit_expired_packets(self) -> None:
        now = time.time()
        expired_packets: list[PendingPacket] = []

        with self._lock:
            for pending in list(self.pending_packets.values()):
                if pending.completed.is_set():
                    continue
                if now - pending.sent_time >= self.ack_timeout:
                    expired_packets.append(pending)

        for pending in expired_packets:
            with self._lock:
                if pending.completed.is_set():
                    continue
                if pending.retries >= self.max_retries:
                    self._mark_failed(pending, "ACK not received")
                    continue

                pending.retries += 1
                pending.sent_time = time.time()

            self.udp_socket.send_packet(pending.packet, pending.address)

    def _handle_ack(self, packet: dict) -> None:
        if not self._is_for_this_node(packet):
            return

        payload = packet.get("payload") if isinstance(packet.get("payload"), dict) else {}
        ack_sequence_number = payload.get("ack_sequence_number")
        if not isinstance(ack_sequence_number, int):
            return

        with self._lock:
            pending = self.pending_packets.pop(ack_sequence_number, None)

        if not pending:
            return

        pending.acknowledged = True
        pending.completed.set()

    def _send_ack(self, packet: dict, address: tuple[str, int]) -> None:
        ack_packet = create_packet(
            packet_type=PacketType.ACK,
            source=self.node.node_id,
            destination=str(packet.get("source")),
            sequence_number=next(self._ack_sequence_numbers),
            ttl=DEFAULT_TTL,
            payload={
                "ack_sequence_number": packet["sequence_number"],
                "ack_type": packet["type"],
                "timestamp": time.time(),
            },
        )
        self.udp_socket.send_packet(ack_packet, address)

    def _mark_failed(self, pending: PendingPacket, reason: str) -> None:
        with self._lock:
            self.pending_packets.pop(pending.sequence_number, None)
            pending.failed_reason = reason
            pending.completed.set()

        if self.on_delivery_failed:
            self.on_delivery_failed(
                DeliveryResult(
                    sequence_number=pending.sequence_number,
                    acknowledged=False,
                    retries=pending.retries,
                    failed_reason=reason,
                )
            )

    def _is_for_this_node(self, packet: dict) -> bool:
        destination = packet.get("destination")
        return destination in {None, self.node.node_id}

