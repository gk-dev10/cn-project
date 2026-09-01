"""Module 9 — Adaptive Window Control.

Automatically adjusts the Go-Back-N window size and retransmission
timeout based on observed network quality.

Inputs consumed
~~~~~~~~~~~~~~~
* ``WindowStats`` from the ``SlidingWindowSender`` (Module 8).
* ``ErrorStats``  from the ``ChecksumTracker``     (Module 7).
* Measured round-trip times (RTTs) collected from ACK timestamps.

Control logic
~~~~~~~~~~~~~
* **Good network** (low loss, low corruption, low RTT):
  gradually *increase* window size (additive increase).
* **Packet loss / timeout detected**:
  aggressively *decrease* window size (multiplicative decrease).
* **High corruption**:
  decrease window and increase ACK timeout.
* **RTT increase**:
  increase ACK timeout to avoid spurious retransmissions.

The controller runs on a periodic evaluation cycle (default 2 s)
and mutates the sender's ``window_size`` and ``ack_timeout`` attributes
in place.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from transport.checksum_tracker import ChecksumTracker, ErrorStats
from transport.sliding_window import (
    DEFAULT_GBN_ACK_TIMEOUT_SECONDS,
    DEFAULT_WINDOW_SIZE,
    SlidingWindowSender,
    WindowStats,
)


# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------

MIN_WINDOW_SIZE = 1
MAX_WINDOW_SIZE = 32
ADDITIVE_INCREASE = 1
MULTIPLICATIVE_DECREASE_FACTOR = 0.5

MIN_ACK_TIMEOUT = 0.1
MAX_ACK_TIMEOUT = 10.0
RTT_SMOOTHING_ALPHA = 0.125   # RFC 6298 recommended
RTT_DEVIATION_BETA = 0.25     # RFC 6298 recommended
RTT_TIMEOUT_MULTIPLIER = 4    # RTO = SRTT + K * RTTVAR

DEFAULT_EVALUATION_INTERVAL_SECONDS = 2.0

LOSS_RATE_GOOD_THRESHOLD = 0.05      # ≤ 5% → network is fine
LOSS_RATE_BAD_THRESHOLD = 0.15       # ≥ 15% → aggressively shrink
CORRUPTION_RATE_THRESHOLD = 0.10     # ≥ 10% → back off


# ---------------------------------------------------------------------------
# RTT Estimator
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class RTTEstimator:
    """Smoothed RTT and deviation tracker (RFC 6298 style)."""

    srtt: float = 0.0
    rttvar: float = 0.0
    rto: float = DEFAULT_GBN_ACK_TIMEOUT_SECONDS
    samples: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add_sample(self, rtt: float) -> None:
        """Incorporate a new RTT measurement."""
        with self._lock:
            if self.samples == 0:
                self.srtt = rtt
                self.rttvar = rtt / 2
            else:
                self.rttvar = (1 - RTT_DEVIATION_BETA) * self.rttvar + RTT_DEVIATION_BETA * abs(self.srtt - rtt)
                self.srtt = (1 - RTT_SMOOTHING_ALPHA) * self.srtt + RTT_SMOOTHING_ALPHA * rtt
            self.rto = max(MIN_ACK_TIMEOUT, min(MAX_ACK_TIMEOUT, self.srtt + RTT_TIMEOUT_MULTIPLIER * self.rttvar))
            self.samples += 1

    def current_rto(self) -> float:
        with self._lock:
            return self.rto

    def average_rtt(self) -> float:
        with self._lock:
            return self.srtt


# ---------------------------------------------------------------------------
# Adaptive Controller Snapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AdaptiveSnapshot:
    """Immutable snapshot of the controller state for logging / dashboards."""

    window_size: int
    ack_timeout: float
    srtt: float
    rttvar: float
    rto: float
    loss_rate: float
    corruption_rate: float
    decision: str
    timestamp: float


# ---------------------------------------------------------------------------
# Adaptive Window Controller
# ---------------------------------------------------------------------------

class AdaptiveWindowController:
    """Periodically evaluates network quality and tunes the GBN sender.

    Usage::

        sender = SlidingWindowSender(...)
        tracker = ChecksumTracker()
        controller = AdaptiveWindowController(sender, tracker)
        controller.start()

        # … sender transmits data …

        controller.stop()
    """

    def __init__(
        self,
        sender: SlidingWindowSender,
        checksum_tracker: Optional[ChecksumTracker] = None,
        evaluation_interval: float = DEFAULT_EVALUATION_INTERVAL_SECONDS,
        min_window: int = MIN_WINDOW_SIZE,
        max_window: int = MAX_WINDOW_SIZE,
        on_adjust: Optional[callable] = None,
    ) -> None:
        self.sender = sender
        self.checksum_tracker = checksum_tracker
        self.evaluation_interval = evaluation_interval
        self.min_window = min_window
        self.max_window = max_window
        self.on_adjust = on_adjust

        self.rtt_estimator = RTTEstimator()

        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._history: deque[AdaptiveSnapshot] = deque(maxlen=100)
        self._prev_stats: Optional[WindowStats] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._evaluation_loop,
            name="meshlink-adaptive-window",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    # ------------------------------------------------------------------
    # RTT sample ingestion
    # ------------------------------------------------------------------

    def record_rtt(self, rtt: float) -> None:
        """Call this whenever an ACK is received, passing the round-trip time."""
        if rtt > 0:
            self.rtt_estimator.add_sample(rtt)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def current_snapshot(self) -> Optional[AdaptiveSnapshot]:
        """Most recent evaluation snapshot, or ``None``."""
        if self._history:
            return self._history[-1]
        return None

    def history(self) -> list[AdaptiveSnapshot]:
        return list(self._history)

    # ------------------------------------------------------------------
    # Core evaluation loop
    # ------------------------------------------------------------------

    def _evaluation_loop(self) -> None:
        while self._running.is_set():
            self._evaluate()
            self._running.wait(self.evaluation_interval)

    def _evaluate(self) -> None:
        stats = self.sender.stats()
        loss_rate = self._compute_interval_loss_rate(stats)
        corruption_rate = (
            self.checksum_tracker.corruption_rate()
            if self.checksum_tracker
            else 0.0
        )

        decision = self._decide(loss_rate, corruption_rate)
        self._apply(decision)

        snapshot = AdaptiveSnapshot(
            window_size=self.sender.window_size,
            ack_timeout=self.sender.ack_timeout,
            srtt=self.rtt_estimator.srtt,
            rttvar=self.rtt_estimator.rttvar,
            rto=self.rtt_estimator.current_rto(),
            loss_rate=loss_rate,
            corruption_rate=corruption_rate,
            decision=decision,
            timestamp=time.time(),
        )
        self._history.append(snapshot)
        self._prev_stats = stats

        if self.on_adjust:
            self.on_adjust(snapshot)

    def _compute_interval_loss_rate(self, stats: WindowStats) -> float:
        """Compute loss rate for the current evaluation interval only."""
        if self._prev_stats is None:
            return stats.loss_rate

        new_sent = stats.packets_sent - self._prev_stats.packets_sent
        new_retransmissions = stats.retransmissions - self._prev_stats.retransmissions
        total = new_sent + new_retransmissions
        if total == 0:
            return 0.0
        return new_retransmissions / total

    def _decide(self, loss_rate: float, corruption_rate: float) -> str:
        """Return one of: 'increase', 'decrease_loss', 'decrease_corruption', 'hold'."""
        if corruption_rate >= CORRUPTION_RATE_THRESHOLD:
            return "decrease_corruption"
        if loss_rate >= LOSS_RATE_BAD_THRESHOLD:
            return "decrease_loss"
        if loss_rate <= LOSS_RATE_GOOD_THRESHOLD:
            return "increase"
        return "hold"

    def _apply(self, decision: str) -> None:
        old_window = self.sender.window_size
        old_timeout = self.sender.ack_timeout

        if decision == "increase":
            new_window = min(self.max_window, old_window + ADDITIVE_INCREASE)
            self.sender.window_size = new_window
            # Tighten timeout towards computed RTO.
            rto = self.rtt_estimator.current_rto()
            if self.rtt_estimator.samples > 0:
                self.sender.ack_timeout = rto

        elif decision == "decrease_loss":
            new_window = max(self.min_window, int(old_window * MULTIPLICATIVE_DECREASE_FACTOR))
            self.sender.window_size = new_window
            # Back off timeout.
            self.sender.ack_timeout = min(MAX_ACK_TIMEOUT, old_timeout * 1.5)

        elif decision == "decrease_corruption":
            new_window = max(self.min_window, int(old_window * MULTIPLICATIVE_DECREASE_FACTOR))
            self.sender.window_size = new_window
            # Increase timeout more aggressively under corruption.
            self.sender.ack_timeout = min(MAX_ACK_TIMEOUT, old_timeout * 2.0)

        # "hold" — do nothing.
