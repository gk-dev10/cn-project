"""Module 18 - Messaging application.

Provides a small application-layer service for sending and receiving
text messages. It uses direct neighbor addresses when available and
falls back to the node routing table for multi-hop next-hop selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Callable, Optional

from core.constants import DEFAULT_TTL, NodeStatus, PacketType
from core.node import MeshNode
from core.packet import create_packet
from routing.routing_manager import RoutingManager
from transport.reliable_transport import DeliveryResult, ReliableTransport
from transport.udp_socket import UDPSocket


MessageCallback = Callable[["ReceivedMessage"], None]


class RouteResolutionError(RuntimeError):
    """Raised when the application cannot find a next hop."""


@dataclass(frozen=True, slots=True)
class ReceivedMessage:
    source: str
    destination: Optional[str]
    text: str
    sequence_number: int
    ttl: int
    received_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class MessageSendResult:
    sequence_number: int
    destination: str
    next_hop: str
    address: tuple[str, int]
    reliable: bool
    acknowledged: bool = False
    retries: int = 0
    failed_reason: Optional[str] = None


class MessagingService:
    def __init__(
        self,
        node: MeshNode,
        udp_socket: Optional[UDPSocket] = None,
        reliable_transport: Optional[ReliableTransport] = None,
        routing_manager: Optional[RoutingManager] = None,
        on_message: Optional[MessageCallback] = None,
    ) -> None:
        self.node = node
        self.udp_socket = udp_socket
        self.reliable_transport = reliable_transport
        self.routing_manager = routing_manager
        self.on_message = on_message
        self.received_messages: list[ReceivedMessage] = []
        self._seen_messages: set[tuple[str, int]] = set()
        self._sequence_number = 1
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

    def send_message(
        self,
        destination: str,
        text: str,
        address: Optional[tuple[str, int]] = None,
        reliable: bool = False,
        ttl: int = DEFAULT_TTL,
    ) -> MessageSendResult:
        self._ensure_socket()
        resolved_address, next_hop = self.resolve_destination(destination, address)

        with self._lock:
            sequence_number = self._sequence_number
            self._sequence_number += 1

        if reliable:
            transport = self._ensure_reliable_transport()
            delivery = transport.send_reliable(
                packet_type=PacketType.MESSAGE,
                destination=destination,
                address=resolved_address,
                payload=text,
                ttl=ttl,
                wait_for_ack=True,
            )
            return self._delivery_to_result(destination, next_hop, resolved_address, delivery)

        packet = create_packet(
            packet_type=PacketType.MESSAGE,
            source=self.node.node_id,
            destination=destination,
            sequence_number=sequence_number,
            ttl=ttl,
            payload=text,
        )
        self.udp_socket.send_packet(packet, resolved_address)
        return MessageSendResult(
            sequence_number=sequence_number,
            destination=destination,
            next_hop=next_hop,
            address=resolved_address,
            reliable=False,
        )

    def handle_packet(self, packet: dict, address: tuple[str, int]) -> Optional[ReceivedMessage]:
        if packet.get("type") != PacketType.MESSAGE.value:
            return None

        destination = packet.get("destination")
        if destination not in (None, self.node.node_id):
            return None

        source = str(packet.get("source", ""))
        sequence_number = int(packet.get("sequence_number", 0))
        message_key = (source, sequence_number)

        with self._lock:
            if message_key in self._seen_messages:
                return None
            self._seen_messages.add(message_key)

        message = ReceivedMessage(
            source=source,
            destination=destination,
            text=str(packet.get("payload", "")),
            sequence_number=sequence_number,
            ttl=int(packet.get("ttl", 0)),
        )

        with self._lock:
            self.received_messages.append(message)

        if self.on_message:
            self.on_message(message)

        return message

    def resolve_destination(
        self,
        destination: str,
        address: Optional[tuple[str, int]] = None,
    ) -> tuple[tuple[str, int], str]:
        if address is not None:
            return address, destination

        direct_neighbor = self.node.neighbors.get(destination)
        if direct_neighbor and direct_neighbor.status == NodeStatus.ACTIVE.value:
            return (direct_neighbor.ip, direct_neighbor.port), destination

        next_hop = None
        if self.routing_manager:
            next_hop = self.routing_manager.get_next_hop(destination)
        if next_hop is None:
            next_hop = self.node.get_next_hop(destination)

        if next_hop is None:
            raise RouteResolutionError(f"no route to {destination}")

        neighbor = self.node.neighbors.get(next_hop)
        if neighbor is None or neighbor.status != NodeStatus.ACTIVE.value:
            raise RouteResolutionError(f"next hop {next_hop} is not active")

        return (neighbor.ip, neighbor.port), next_hop

    def _ensure_socket(self) -> None:
        if self.udp_socket:
            if not self.udp_socket.is_running:
                self.udp_socket.start_socket()
            return

        self.node.start_networking()
        self.udp_socket = self.node.udp_socket

    def _ensure_reliable_transport(self) -> ReliableTransport:
        if self.reliable_transport:
            if not self.reliable_transport.is_running:
                self.reliable_transport.start()
            return self.reliable_transport

        self.reliable_transport = ReliableTransport(
            self.node,
            udp_socket=self.udp_socket,
            packet_types={PacketType.MESSAGE.value},
        )
        self.reliable_transport.start()
        return self.reliable_transport

    @staticmethod
    def _delivery_to_result(
        destination: str,
        next_hop: str,
        address: tuple[str, int],
        delivery: DeliveryResult,
    ) -> MessageSendResult:
        return MessageSendResult(
            sequence_number=delivery.sequence_number,
            destination=destination,
            next_hop=next_hop,
            address=address,
            reliable=True,
            acknowledged=delivery.acknowledged,
            retries=delivery.retries,
            failed_reason=delivery.failed_reason,
        )

