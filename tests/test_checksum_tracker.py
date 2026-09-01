"""Tests for Module 7 — Checksum and Error Detection (ChecksumTracker)."""

import unittest

from core.constants import PacketType
from core.packet import create_packet, serialize_packet
from transport.checksum_tracker import ChecksumTracker, ErrorStats


class ErrorStatsTests(unittest.TestCase):
    def test_corruption_rate_zero_when_no_packets(self):
        stats = ErrorStats()
        self.assertEqual(stats.corruption_rate, 0.0)

    def test_corruption_rate_calculated_correctly(self):
        stats = ErrorStats(accepted=8, rejected=2)
        self.assertAlmostEqual(stats.corruption_rate, 0.2)

    def test_total_includes_accepted_and_rejected(self):
        stats = ErrorStats(accepted=5, rejected=3)
        self.assertEqual(stats.total, 8)


class ChecksumTrackerProcessTests(unittest.TestCase):
    def test_valid_packet_is_accepted(self):
        tracker = ChecksumTracker()
        packet = create_packet(PacketType.MESSAGE, "DEVICE_A", "DEVICE_B", sequence_number=1, payload="Hi")
        raw = serialize_packet(packet)

        result = tracker.process(raw)

        self.assertIsNotNone(result)
        self.assertEqual(result["payload"], "Hi")
        stats = tracker.aggregate_stats()
        self.assertEqual(stats.accepted, 1)
        self.assertEqual(stats.rejected, 0)

    def test_corrupted_packet_is_rejected(self):
        tracker = ChecksumTracker()
        packet = create_packet(PacketType.MESSAGE, "DEVICE_A", "DEVICE_B", sequence_number=1, payload="Original")
        raw = serialize_packet(packet)
        # Corrupt the payload bytes.
        corrupted = raw.replace(b"Original", b"Tampered")

        result = tracker.process(corrupted)

        self.assertIsNone(result)
        stats = tracker.aggregate_stats()
        self.assertEqual(stats.accepted, 0)
        self.assertEqual(stats.rejected, 1)

    def test_malformed_data_is_rejected(self):
        tracker = ChecksumTracker()
        result = tracker.process(b"not-json-at-all")

        self.assertIsNone(result)
        self.assertEqual(tracker.aggregate_stats().rejected, 1)

    def test_duplicate_packet_is_detected(self):
        tracker = ChecksumTracker()
        packet = create_packet(PacketType.MESSAGE, "DEVICE_A", "DEVICE_B", sequence_number=1, payload="Data")
        raw = serialize_packet(packet)

        first = tracker.process(raw)
        second = tracker.process(raw)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        stats = tracker.aggregate_stats()
        self.assertEqual(stats.accepted, 1)
        self.assertEqual(stats.duplicates, 1)

    def test_different_sequence_numbers_are_not_duplicates(self):
        tracker = ChecksumTracker()
        p1 = create_packet(PacketType.MESSAGE, "DEVICE_A", "DEVICE_B", sequence_number=1, payload="One")
        p2 = create_packet(PacketType.MESSAGE, "DEVICE_A", "DEVICE_B", sequence_number=2, payload="Two")

        r1 = tracker.process(serialize_packet(p1))
        r2 = tracker.process(serialize_packet(p2))

        self.assertIsNotNone(r1)
        self.assertIsNotNone(r2)
        self.assertEqual(tracker.aggregate_stats().accepted, 2)
        self.assertEqual(tracker.aggregate_stats().duplicates, 0)


class ChecksumTrackerStatsTests(unittest.TestCase):
    def test_per_source_stats(self):
        tracker = ChecksumTracker()
        p1 = create_packet(PacketType.MESSAGE, "DEVICE_A", "DEVICE_B", sequence_number=1, payload="A1")
        p2 = create_packet(PacketType.MESSAGE, "DEVICE_C", "DEVICE_B", sequence_number=1, payload="C1")

        tracker.process(serialize_packet(p1))
        tracker.process(serialize_packet(p2))

        a_stats = tracker.source_stats("DEVICE_A")
        c_stats = tracker.source_stats("DEVICE_C")
        self.assertEqual(a_stats.accepted, 1)
        self.assertEqual(c_stats.accepted, 1)

    def test_corruption_rate_aggregate(self):
        tracker = ChecksumTracker()
        good = create_packet(PacketType.MESSAGE, "DEVICE_A", "DEVICE_B", sequence_number=1, payload="Good")
        tracker.process(serialize_packet(good))
        tracker.process(b"garbage")

        rate = tracker.corruption_rate()
        self.assertAlmostEqual(rate, 0.5)

    def test_reset_clears_everything(self):
        tracker = ChecksumTracker()
        p = create_packet(PacketType.MESSAGE, "DEVICE_A", "DEVICE_B", sequence_number=1, payload="X")
        tracker.process(serialize_packet(p))
        tracker.process(b"bad")

        tracker.reset()

        stats = tracker.aggregate_stats()
        self.assertEqual(stats.accepted, 0)
        self.assertEqual(stats.rejected, 0)
        self.assertEqual(stats.duplicates, 0)

    def test_validate_packet_updates_counters(self):
        tracker = ChecksumTracker()
        packet = create_packet(PacketType.MESSAGE, "DEVICE_A", "DEVICE_B", payload="Data")

        self.assertTrue(tracker.validate_packet(packet))
        self.assertEqual(tracker.aggregate_stats().accepted, 1)

        # Tamper and re-validate.
        tampered = dict(packet)
        tampered["payload"] = "Nope"
        tampered["payload_length"] = len("Nope")
        self.assertFalse(tracker.validate_packet(tampered))
        self.assertEqual(tracker.aggregate_stats().rejected, 1)


if __name__ == "__main__":
    unittest.main()
