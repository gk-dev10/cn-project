"""Module 7 — Checksum and Error Detection.

Provides a ``ChecksumTracker`` that wraps the existing packet-level
``verify_checksum`` / ``calculate_checksum`` logic (core/packet.py) with
a statistics layer.  Every incoming raw datagram passes through the
tracker *before* higher layers see it:

    raw bytes  →  ChecksumTracker.process()
                     ├─ valid    →  deserialized packet forwarded
                     └─ corrupt  →  rejected, counter incremented

Tracked metrics (per source and aggregate):
    * accepted   – packets with a valid checksum
    * rejected   – packets whose checksum did not match (corrupt)
    * duplicates – packets already delivered (same source+sequence)
    * corruption_rate – rejected / (accepted + rejected)

These statistics feed into Module 9 (Adaptive Window Control).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from core.packet import (
    ChecksumError,
    PacketError,
    calculate_checksum,
    deserialize_packet,
    verify_checksum,
)


@dataclass(slots=True)
class ErrorStats:
    """Running error counters for a single source (or the aggregate)."""

    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    last_rejection_time: float = 0.0

    @property
    def total(self) -> int:
        return self.accepted + self.rejected

    @property
    def corruption_rate(self) -> float:
        """Fraction of packets that failed checksum validation."""
        if self.total == 0:
            return 0.0
        return self.rejected / self.total


class ChecksumTracker:
    """Validate incoming packets and track error statistics.

    Parameters
    ----------
    max_seen : int
        Maximum number of (source, sequence_number) pairs to remember
        for duplicate detection.  Older entries are evicted in FIFO order.
    """

    def __init__(self, max_seen: int = 10_000) -> None:
        self._lock = threading.Lock()
        self._aggregate = ErrorStats()
        self._per_source: dict[str, ErrorStats] = {}
        self._seen_keys: list[tuple[str, int]] = []
        self._seen_set: set[tuple[str, int]] = set()
        self._max_seen = max_seen

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, raw_data: bytes) -> Optional[dict[str, Any]]:
        """Deserialize *raw_data* and verify its checksum.

        Returns the deserialized packet dict on success, or ``None`` if
        the packet is corrupt, malformed, or a duplicate.
        """
        try:
            packet = deserialize_packet(raw_data)
        except ChecksumError:
            self._record_rejection(raw_data)
            return None
        except PacketError:
            # Malformed packet (missing fields, bad JSON, …).
            self._record_rejection(raw_data)
            return None

        source = str(packet.get("source", ""))
        seq = int(packet.get("sequence_number", 0))
        key = (source, seq)

        with self._lock:
            stats = self._stats_for(source)

            if key in self._seen_set:
                stats.duplicates += 1
                self._aggregate.duplicates += 1
                return None

            stats.accepted += 1
            self._aggregate.accepted += 1
            self._remember(key)

        return packet

    def validate_packet(self, packet: dict[str, Any]) -> bool:
        """Check whether an already-deserialized packet has a valid checksum.

        This is a thin convenience wrapper around ``verify_checksum`` that
        also updates the tracker counters.
        """
        source = str(packet.get("source", ""))
        valid = verify_checksum(packet)

        with self._lock:
            stats = self._stats_for(source)
            if valid:
                stats.accepted += 1
                self._aggregate.accepted += 1
            else:
                stats.rejected += 1
                stats.last_rejection_time = time.time()
                self._aggregate.rejected += 1
                self._aggregate.last_rejection_time = time.time()

        return valid

    def recalculate_checksum(self, packet: dict[str, Any]) -> str:
        """Return the expected checksum for *packet* (delegates to core)."""
        return calculate_checksum(packet)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def aggregate_stats(self) -> ErrorStats:
        """Return a *snapshot copy* of the aggregate error counters."""
        with self._lock:
            return ErrorStats(
                accepted=self._aggregate.accepted,
                rejected=self._aggregate.rejected,
                duplicates=self._aggregate.duplicates,
                last_rejection_time=self._aggregate.last_rejection_time,
            )

    def source_stats(self, source: str) -> ErrorStats:
        """Return a snapshot copy of counters for a single source node."""
        with self._lock:
            stats = self._per_source.get(source)
            if stats is None:
                return ErrorStats()
            return ErrorStats(
                accepted=stats.accepted,
                rejected=stats.rejected,
                duplicates=stats.duplicates,
                last_rejection_time=stats.last_rejection_time,
            )

    def corruption_rate(self) -> float:
        """Aggregate corruption rate (0.0–1.0)."""
        with self._lock:
            return self._aggregate.corruption_rate

    def reset(self) -> None:
        """Clear all statistics and duplicate memory."""
        with self._lock:
            self._aggregate = ErrorStats()
            self._per_source.clear()
            self._seen_keys.clear()
            self._seen_set.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _record_rejection(self, raw_data: bytes) -> None:
        """Increment rejection counters.  Best-effort source extraction."""
        source = self._try_extract_source(raw_data)
        now = time.time()
        with self._lock:
            stats = self._stats_for(source)
            stats.rejected += 1
            stats.last_rejection_time = now
            self._aggregate.rejected += 1
            self._aggregate.last_rejection_time = now

    def _stats_for(self, source: str) -> ErrorStats:
        """Return (or create) the per-source ``ErrorStats``.  Caller holds lock."""
        stats = self._per_source.get(source)
        if stats is None:
            stats = ErrorStats()
            self._per_source[source] = stats
        return stats

    def _remember(self, key: tuple[str, int]) -> None:
        """Track a (source, seq) pair for duplicate detection.  Caller holds lock."""
        self._seen_set.add(key)
        self._seen_keys.append(key)
        while len(self._seen_keys) > self._max_seen:
            evicted = self._seen_keys.pop(0)
            self._seen_set.discard(evicted)

    @staticmethod
    def _try_extract_source(raw_data: bytes) -> str:
        """Best-effort extraction of 'source' from potentially corrupt JSON."""
        try:
            import json
            text = raw_data.decode("utf-8", errors="replace")
            obj = json.loads(text)
            return str(obj.get("source", "UNKNOWN"))
        except Exception:
            return "UNKNOWN"
