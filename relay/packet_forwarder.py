"""Modules 16 & 17 — Multi-Hop Packet Forwarding with TTL Management.

When a node receives a packet whose destination is **not** itself, the
``PacketForwarder`` looks up the next hop in the routing table,
decrements the TTL, and forwards the packet.

Forwarding algorithm::

    Receive packet
          │
          ▼
    Verify checksum
          │
          ▼
    Is destination == self?
          │
          ├── Yes → deliver to application (on_local_deliver callback)
          │
          └── No
                 │
                 ▼
             TTL > 0?
                 │
                 ├── No → drop packet (on_drop callback)
                 │
                 └── Yes
                        │
                        ▼
                  Decrement TTL
                        │
                        ▼
                  Find next_hop via routing_manager / MeshNode
                        │
                        ├── Found → re-serialize & forward
                        │
                        └── Not found → drop (no route)

Thread safety: the forwarder is designed to be called from the
UDP socket's packet-handler thread and must not block.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.constants import PacketType
from core.node import MeshNode
from core.packet import create_packet, verify_checksum
from transport.udp_socket import UDPSocket


@dataclass(slots=True)
class ForwarderStats:
    """Running statistics for the packet forwarder."""

    delivered_locally: int = 0
    forwarded: int = 0
    dropped_ttl: int = 0
    dropped_no_route: int = 0
    dropped_checksum: int = 0

    @property
    def total_received(self) -> int:
        return (
            self.delivered_locally
            + self.forwarded
            + self.dropped_ttl
            + self.dropped_no_route
            + self.dropped_checksum
        )


# Callback signatures.
LocalDeliverCallback = Callable[[dict, tuple[str, int]], None]
DropCallback = Callable[[dict, str, tuple[str, int]], None]
ForwardCallback = Callable[[dict, str, tuple[str, int]], None]


class PacketForwarder:
    """Multi-hop packet forwarder with TTL management.

    Parameters
    ----------
    node : MeshNode
        The local mesh node (used for node_id and routing table).
    udp_socket : UDPSocket
        Socket for forwarding packets.
    on_local_deliver : callback
        Called when a packet addressed to this node arrives.
    on_drop : optional callback
        Called when a packet is dropped.  Receives ``(packet, reason, address)``.
    on_forward : optional callback
        Called after a packet is successfully forwarded.
    forwardable_types : set of PacketType values, optional
        Only these packet types are forwarded.  Others addressed to
        this node are delivered; others addressed elsewhere are ignored.
        Defaults to MESSAGE and FILE_CHUNK.
    """

    def __init__(
        self,
        node: MeshNode,
        udp_socket: Optional[UDPSocket] = None,
        on_local_deliver: Optional[LocalDeliverCallback] = None,
        on_drop: Optional[DropCallback] = None,
        on_forward: Optional[ForwardCallback] = None,
        forwardable_types: Optional[set[str]] = None,
    ) -> None:
        self.node = node
        self.udp_socket = udp_socket
        self.on_local_deliver = on_local_deliver
        self.on_drop = on_drop
        self.on_forward = on_forward
        self.forwardable_types = forwardable_types or {
            PacketType.MESSAGE.value,
            PacketType.FILE_CHUNK.value,
        }

        self._stats = ForwarderStats()
        self._lock = threading.Lock()
        self._handler_registered = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Register the forwarder as a packet handler on the socket."""
        if self._handler_registered:
            return
        self._ensure_socket()
        self.udp_socket.add_packet_handler(self.handle_packet)
        self._handler_registered = True

    def stop(self) -> None:
        """Unregister the packet handler."""
        if self._handler_registered and self.udp_socket:
            self.udp_socket.remove_packet_handler(self.handle_packet)
            self._handler_registered = False

    # ------------------------------------------------------------------
    # Core forwarding logic
    # ------------------------------------------------------------------

    def handle_packet(self, packet: dict, address: tuple[str, int]) -> None:
        """Process an incoming packet — deliver locally or forward.

        This method is called from the UDP socket's receiver thread.
        """
        pkt_type = packet.get("type", "")
        destination = packet.get("destination")

        # Only process forwardable packet types.
        if pkt_type not in self.forwardable_types:
            return

        # 1. Is this packet addressed to us (or broadcast)?
        if destination is None or destination == self.node.node_id:
            with self._lock:
                self._stats.delivered_locally += 1
            if self.on_local_deliver:
                self.on_local_deliver(packet, address)
            return

        # 2. TTL check.
        ttl = packet.get("ttl", 0)
        if ttl <= 1:
            with self._lock:
                self._stats.dropped_ttl += 1
            self._emit_drop(packet, "TTL expired", address)
            return

        # 3. Look up next hop.
        next_hop_id = self.node.get_next_hop(destination)
        if next_hop_id is None:
            with self._lock:
                self._stats.dropped_no_route += 1
            self._emit_drop(packet, f"no route to {destination}", address)
            return

        # 4. Resolve next-hop to an address.
        next_hop_info = self.node.neighbors.get(next_hop_id)
        if next_hop_info is None or next_hop_info.status != "ACTIVE":
            with self._lock:
                self._stats.dropped_no_route += 1
            self._emit_drop(packet, f"next hop {next_hop_id} not active", address)
            return

        forward_address = (next_hop_info.ip, next_hop_info.port)

        # 5. Build forwarded packet with decremented TTL.
        forwarded = create_packet(
            packet_type=pkt_type,
            source=packet.get("source", self.node.node_id),
            destination=destination,
            sequence_number=packet.get("sequence_number", 0),
            ttl=ttl - 1,
            payload=packet.get("payload"),
        )

        # 6. Send.
        try:
            self.udp_socket.send_packet(forwarded, forward_address)
        except OSError:
            with self._lock:
                self._stats.dropped_no_route += 1
            self._emit_drop(packet, f"send failed to {forward_address}", address)
            return

        with self._lock:
            self._stats.forwarded += 1

        if self.on_forward:
            self.on_forward(packet, next_hop_id, forward_address)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> ForwarderStats:
        """Return a snapshot of forwarding statistics."""
        with self._lock:
            return ForwarderStats(
                delivered_locally=self._stats.delivered_locally,
                forwarded=self._stats.forwarded,
                dropped_ttl=self._stats.dropped_ttl,
                dropped_no_route=self._stats.dropped_no_route,
                dropped_checksum=self._stats.dropped_checksum,
            )

    def reset_stats(self) -> None:
        with self._lock:
            self._stats = ForwarderStats()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _emit_drop(self, packet: dict, reason: str, address: tuple[str, int]) -> None:
        if self.on_drop:
            self.on_drop(packet, reason, address)

    def _ensure_socket(self) -> None:
        if self.udp_socket:
            if not self.udp_socket.is_running:
                self.udp_socket.start_socket()
            return
        self.node.start_networking()
        self.udp_socket = self.node.udp_socket
