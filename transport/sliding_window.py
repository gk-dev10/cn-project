"""Module 8 — Go-Back-N Sliding Window Protocol.

Implements a Go-Back-N (GBN) sender that transmits up to *window_size*
packets before requiring cumulative ACKs, and a GBN receiver that
accepts packets only in order.

Terminology
-----------
base              – sequence number of the oldest unacknowledged packet.
next_seq          – next sequence number to assign when sending.
window_size       – how many unacknowledged packets can be in flight.

Sender behaviour
~~~~~~~~~~~~~~~~
1. While ``next_seq - base < window_size``, send the next packet.
2. When ACK(n) arrives, slide *base* forward to n+1.
3. On timeout (no ACK for the *base* packet), **retransmit every
   unacknowledged packet** starting from *base*  (the "go-back-N"
   behaviour).

Receiver behaviour
~~~~~~~~~~~~~~~~~~
1. If the incoming packet has ``sequence_number == expected_seq``,
   deliver it and send a cumulative ACK for that sequence.
2. Otherwise discard the packet and re-ACK the last correctly-received
   sequence.

Data flow::

    SlidingWindowSender ──send_data()──►  UDPSocket
                                             │
                                        network
                                             │
    SlidingWindowReceiver ◄── handle_packet ──┘
            │
            └── delivers in-order data to application via callback
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.constants import DEFAULT_TTL, PacketType
from core.node import MeshNode
from core.packet import create_packet
from transport.udp_socket import UDPSocket


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_WINDOW_SIZE = 4
DEFAULT_GBN_ACK_TIMEOUT_SECONDS = 1.0
DEFAULT_GBN_MAX_RETRANSMISSIONS = 20
DEFAULT_GBN_CHECK_INTERVAL_SECONDS = 0.05

# Type aliases
WindowPacketHandler = Callable[[dict, tuple[str, int]], None]
WindowStatsHandler = Callable[["WindowStats"], None]


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class WindowStats:
    """Snapshot of sliding-window performance counters."""

    packets_sent: int = 0
    packets_acked: int = 0
    retransmissions: int = 0
    timeouts: int = 0
    window_size: int = DEFAULT_WINDOW_SIZE
    base: int = 0
    next_seq: int = 0

    @property
    def loss_rate(self) -> float:
        """Estimated loss rate based on retransmission count."""
        total = self.packets_sent + self.retransmissions
        if total == 0:
            return 0.0
        return self.retransmissions / total


# ---------------------------------------------------------------------------
# Sender
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _InFlightPacket:
    """A packet that has been sent but not yet acknowledged."""

    sequence_number: int
    packet: dict
    address: tuple[str, int]
    sent_time: float
    retries: int = 0


class SlidingWindowSender:
    """Go-Back-N sender.

    Parameters
    ----------
    node : MeshNode
        The local mesh node (provides ``node_id``).
    udp_socket : UDPSocket
        Socket used to transmit packets.
    window_size : int
        Maximum packets in flight before blocking.
    ack_timeout : float
        Seconds to wait for a cumulative ACK before retransmitting from *base*.
    max_retransmissions : int
        Maximum total retransmission rounds before declaring failure.
    on_stats : optional callback
        Invoked after every ACK or retransmission with a ``WindowStats`` snapshot.
    """

    def __init__(
        self,
        node: MeshNode,
        udp_socket: UDPSocket,
        window_size: int = DEFAULT_WINDOW_SIZE,
        ack_timeout: float = DEFAULT_GBN_ACK_TIMEOUT_SECONDS,
        max_retransmissions: int = DEFAULT_GBN_MAX_RETRANSMISSIONS,
        check_interval: float = DEFAULT_GBN_CHECK_INTERVAL_SECONDS,
        on_stats: Optional[WindowStatsHandler] = None,
    ) -> None:
        self.node = node
        self.udp_socket = udp_socket
        self.window_size = window_size
        self.ack_timeout = ack_timeout
        self.max_retransmissions = max_retransmissions
        self.check_interval = check_interval
        self.on_stats = on_stats

        # Sequence state
        self._base = 1
        self._next_seq = 1
        self._lock = threading.Lock()
        self._in_flight: dict[int, _InFlightPacket] = {}

        # Counters
        self._packets_sent = 0
        self._packets_acked = 0
        self._retransmissions = 0
        self._timeouts = 0

        # Lifecycle
        self._running = threading.Event()
        self._timer_thread: Optional[threading.Thread] = None

        # Register ACK handler
        self._handler_registered = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        if not self._handler_registered:
            self.udp_socket.add_packet_handler(self._handle_ack_packet)
            self._handler_registered = True
        self._timer_thread = threading.Thread(
            target=self._timeout_loop,
            name=f"meshlink-gbn-sender-{self.node.node_id}",
            daemon=True,
        )
        self._timer_thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._handler_registered:
            self.udp_socket.remove_packet_handler(self._handle_ack_packet)
            self._handler_registered = False
        if self._timer_thread and self._timer_thread is not threading.current_thread():
            self._timer_thread.join(timeout=1)
        self._timer_thread = None

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send(
        self,
        destination: str,
        address: tuple[str, int],
        payload: Any,
        packet_type: PacketType | str = PacketType.FILE_CHUNK,
        ttl: int = DEFAULT_TTL,
    ) -> int:
        """Queue a single payload for GBN delivery.

        Blocks if the window is full (``next_seq - base >= window_size``).
        Returns the assigned sequence number.
        """
        # Block until we have room in the window.
        while True:
            with self._lock:
                if self._next_seq - self._base < self.window_size:
                    seq = self._next_seq
                    self._next_seq += 1
                    break
            # Window full — yield CPU and retry.
            time.sleep(self.check_interval)
            if not self._running.is_set():
                raise RuntimeError("sender stopped while waiting for window space")

        packet = create_packet(
            packet_type=packet_type,
            source=self.node.node_id,
            destination=destination,
            sequence_number=seq,
            ttl=ttl,
            payload=payload,
        )

        in_flight = _InFlightPacket(
            sequence_number=seq,
            packet=packet,
            address=address,
            sent_time=time.time(),
        )

        with self._lock:
            self._in_flight[seq] = in_flight
            self._packets_sent += 1

        self.udp_socket.send_packet(packet, address)
        return seq

    def send_all(
        self,
        destination: str,
        address: tuple[str, int],
        payloads: list[Any],
        packet_type: PacketType | str = PacketType.FILE_CHUNK,
        ttl: int = DEFAULT_TTL,
    ) -> list[int]:
        """Send a list of payloads through the sliding window.  Returns assigned sequence numbers."""
        return [
            self.send(destination, address, p, packet_type=packet_type, ttl=ttl)
            for p in payloads
        ]

    def wait_all_acked(self, timeout: float = 30.0) -> bool:
        """Block until every in-flight packet is acknowledged or *timeout* elapses.

        Returns ``True`` if all packets were acknowledged.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if not self._in_flight:
                    return True
            time.sleep(self.check_interval)
        return False

    # ------------------------------------------------------------------
    # ACK handling
    # ------------------------------------------------------------------

    def _handle_ack_packet(self, packet: dict, address: tuple[str, int]) -> None:
        """Process an incoming ACK and slide the window forward."""
        if packet.get("type") != PacketType.ACK.value:
            return
        if packet.get("destination") not in (None, self.node.node_id):
            return

        payload = packet.get("payload")
        if not isinstance(payload, dict):
            return

        ack_seq = payload.get("ack_sequence_number")
        if not isinstance(ack_seq, int):
            return

        with self._lock:
            # Cumulative ACK: everything up to ack_seq is acknowledged.
            acked_keys = [k for k in self._in_flight if k <= ack_seq]
            for k in acked_keys:
                self._in_flight.pop(k, None)
                self._packets_acked += 1

            if ack_seq >= self._base:
                self._base = ack_seq + 1

        self._emit_stats()

    # ------------------------------------------------------------------
    # Timeout & retransmission
    # ------------------------------------------------------------------

    def _timeout_loop(self) -> None:
        while self._running.is_set():
            self._check_timeout()
            self._running.wait(self.check_interval)

    def _check_timeout(self) -> None:
        now = time.time()
        with self._lock:
            base_pkt = self._in_flight.get(self._base)
            if base_pkt is None:
                return
            if now - base_pkt.sent_time < self.ack_timeout:
                return

            # Timeout — retransmit everything from base onward.
            self._timeouts += 1
            to_retransmit = sorted(
                (p for p in self._in_flight.values()),
                key=lambda p: p.sequence_number,
            )

        for pkt in to_retransmit:
            if not self._running.is_set():
                break
            with self._lock:
                pkt.retries += 1
                pkt.sent_time = time.time()
                self._retransmissions += 1
            self.udp_socket.send_packet(pkt.packet, pkt.address)

        self._emit_stats()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> WindowStats:
        with self._lock:
            return WindowStats(
                packets_sent=self._packets_sent,
                packets_acked=self._packets_acked,
                retransmissions=self._retransmissions,
                timeouts=self._timeouts,
                window_size=self.window_size,
                base=self._base,
                next_seq=self._next_seq,
            )

    def _emit_stats(self) -> None:
        if self.on_stats:
            self.on_stats(self.stats())


# ---------------------------------------------------------------------------
# Receiver
# ---------------------------------------------------------------------------

class SlidingWindowReceiver:
    """Go-Back-N receiver.

    Delivers packets strictly in order.  Out-of-order packets are
    silently discarded and the last cumulative ACK is re-sent.

    Parameters
    ----------
    node : MeshNode
        The local mesh node.
    udp_socket : UDPSocket
        Socket for receiving packets and sending ACKs.
    on_deliver : callback
        Called with ``(sequence_number, packet, address)`` for each
        in-order packet.
    """

    def __init__(
        self,
        node: MeshNode,
        udp_socket: UDPSocket,
        on_deliver: Optional[Callable[[int, dict, tuple[str, int]], None]] = None,
        expected_types: Optional[set[str]] = None,
    ) -> None:
        self.node = node
        self.udp_socket = udp_socket
        self.on_deliver = on_deliver
        self.expected_types = expected_types or {PacketType.FILE_CHUNK.value, PacketType.MESSAGE.value}

        self._expected_seq = 1
        self._last_ack_seq = 0
        self._ack_seq_counter = itertools.count(1)
        self._lock = threading.Lock()
        self._handler_registered = False

        # Statistics
        self._delivered = 0
        self._out_of_order = 0

    def start(self) -> None:
        if not self._handler_registered:
            self.udp_socket.add_packet_handler(self._handle_packet)
            self._handler_registered = True

    def stop(self) -> None:
        if self._handler_registered:
            self.udp_socket.remove_packet_handler(self._handle_packet)
            self._handler_registered = False

    @property
    def expected_seq(self) -> int:
        with self._lock:
            return self._expected_seq

    @property
    def delivered_count(self) -> int:
        with self._lock:
            return self._delivered

    @property
    def out_of_order_count(self) -> int:
        with self._lock:
            return self._out_of_order

    def _handle_packet(self, packet: dict, address: tuple[str, int]) -> None:
        pkt_type = packet.get("type")
        if pkt_type not in self.expected_types:
            return

        dest = packet.get("destination")
        if dest not in (None, self.node.node_id):
            return

        seq = packet.get("sequence_number")
        if not isinstance(seq, int):
            return

        in_order = False
        with self._lock:
            if seq == self._expected_seq:
                # In-order — deliver.
                self._expected_seq += 1
                self._last_ack_seq = seq
                self._delivered += 1
                in_order = True
            else:
                # Out of order — discard, re-ACK last good sequence.
                self._out_of_order += 1

            ack_seq = self._last_ack_seq

        # Always send a cumulative ACK for the last in-order packet.
        self._send_ack(ack_seq, packet, address)

        # Deliver outside the lock.
        if in_order:
            if self.on_deliver:
                self.on_deliver(seq, packet, address)

    def _send_ack(self, ack_seq: int, original_packet: dict, address: tuple[str, int]) -> None:
        ack = create_packet(
            packet_type=PacketType.ACK,
            source=self.node.node_id,
            destination=str(original_packet.get("source")),
            sequence_number=next(self._ack_seq_counter),
            ttl=DEFAULT_TTL,
            payload={
                "ack_sequence_number": ack_seq,
                "ack_type": original_packet.get("type", ""),
                "timestamp": time.time(),
            },
        )
        self.udp_socket.send_packet(ack, address)
