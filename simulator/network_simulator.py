"""Network condition simulator for Module 22."""

from __future__ import annotations

from dataclasses import dataclass
import random
import threading
from typing import Callable, Optional

from core.constants import (
    DEFAULT_SIMULATED_DELAY_SECONDS,
    DEFAULT_SIMULATED_JITTER_SECONDS,
    DEFAULT_SIMULATED_LOSS_RATE,
)
from simulator.latency import LatencySimulator
from simulator.node_failure import NodeFailureSimulator
from simulator.packet_loss import PacketLossSimulator
from transport.udp_socket import UDPSocket


DeliveryCallback = Callable[[dict, tuple[str, int]], None]
DropCallback = Callable[[dict, str], None]


@dataclass(frozen=True, slots=True)
class SimulationResult:
    accepted: bool
    delivered: bool
    dropped: bool
    reason: Optional[str] = None
    delay_seconds: float = 0.0


@dataclass(slots=True)
class SimulationStats:
    attempted: int = 0
    delivered: int = 0
    delayed: int = 0
    dropped_loss: int = 0
    dropped_node_failure: int = 0
    send_errors: int = 0

    @property
    def dropped(self) -> int:
        return self.dropped_loss + self.dropped_node_failure + self.send_errors

    @property
    def delivery_rate(self) -> float:
        if self.attempted == 0:
            return 0.0
        return self.delivered / self.attempted


class NetworkSimulator:
    def __init__(
        self,
        loss_rate: float = DEFAULT_SIMULATED_LOSS_RATE,
        base_delay_seconds: float = DEFAULT_SIMULATED_DELAY_SECONDS,
        jitter_seconds: float = DEFAULT_SIMULATED_JITTER_SECONDS,
        random_seed: Optional[int] = None,
        on_drop: Optional[DropCallback] = None,
    ) -> None:
        rng = random.Random(random_seed)
        self.packet_loss = PacketLossSimulator(loss_rate=loss_rate, random_generator=rng)
        self.latency = LatencySimulator(
            base_delay_seconds=base_delay_seconds,
            jitter_seconds=jitter_seconds,
            random_generator=rng,
        )
        self.node_failure = NodeFailureSimulator()
        self.on_drop = on_drop
        self._stats = SimulationStats()
        self._timers: list[threading.Timer] = []
        self._lock = threading.RLock()

    def send_packet(
        self,
        udp_socket: UDPSocket,
        packet: dict,
        address: tuple[str, int],
        source_node: Optional[str] = None,
        destination_node: Optional[str] = None,
        on_delivered: Optional[DeliveryCallback] = None,
    ) -> SimulationResult:
        with self._lock:
            self._stats.attempted += 1

        if self.node_failure.is_failed(source_node) or self.node_failure.is_failed(destination_node):
            self._record_drop("node failure", node_failure=True, packet=packet)
            return SimulationResult(accepted=False, delivered=False, dropped=True, reason="node failure")

        if self.packet_loss.should_drop():
            self._record_drop("packet loss", packet=packet)
            return SimulationResult(accepted=False, delivered=False, dropped=True, reason="packet loss")

        delay = self.latency.delay_seconds()
        if delay > 0:
            with self._lock:
                self._stats.delayed += 1
            timer = threading.Timer(
                delay,
                self._deliver,
                args=(udp_socket, packet, address, on_delivered),
            )
            timer.daemon = True
            with self._lock:
                self._timers.append(timer)
            timer.start()
            return SimulationResult(accepted=True, delivered=False, dropped=False, delay_seconds=delay)

        return self._deliver(udp_socket, packet, address, on_delivered)

    def fail_node(self, node_id: str) -> None:
        self.node_failure.fail_node(node_id)

    def recover_node(self, node_id: str) -> None:
        self.node_failure.recover_node(node_id)

    def stats(self) -> SimulationStats:
        with self._lock:
            return SimulationStats(
                attempted=self._stats.attempted,
                delivered=self._stats.delivered,
                delayed=self._stats.delayed,
                dropped_loss=self._stats.dropped_loss,
                dropped_node_failure=self._stats.dropped_node_failure,
                send_errors=self._stats.send_errors,
            )

    def wait_for_deliveries(self, timeout: float = 5.0) -> None:
        deadline = threading.Event()
        for timer in self._pending_timers():
            remaining = max(0.0, timeout)
            timer.join(timeout=remaining)
        deadline.set()

    def _deliver(
        self,
        udp_socket: UDPSocket,
        packet: dict,
        address: tuple[str, int],
        on_delivered: Optional[DeliveryCallback],
    ) -> SimulationResult:
        try:
            udp_socket.send_packet(packet, address)
        except OSError:
            with self._lock:
                self._stats.send_errors += 1
            self._emit_drop(packet, "send error")
            return SimulationResult(accepted=False, delivered=False, dropped=True, reason="send error")

        with self._lock:
            self._stats.delivered += 1

        if on_delivered:
            on_delivered(packet, address)

        return SimulationResult(accepted=True, delivered=True, dropped=False)

    def _record_drop(self, reason: str, packet: dict, node_failure: bool = False) -> None:
        with self._lock:
            if node_failure:
                self._stats.dropped_node_failure += 1
            else:
                self._stats.dropped_loss += 1
        self._emit_drop(packet, reason)

    def _emit_drop(self, packet: dict, reason: str) -> None:
        if self.on_drop:
            self.on_drop(packet, reason)

    def _pending_timers(self) -> list[threading.Timer]:
        with self._lock:
            timers = list(self._timers)
            self._timers = [timer for timer in self._timers if timer.is_alive()]
            return timers

