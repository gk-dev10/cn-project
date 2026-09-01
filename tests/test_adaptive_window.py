"""Tests for Module 9 — Adaptive Window Control."""

import unittest

from transport.adaptive_window import (
    ADDITIVE_INCREASE,
    CORRUPTION_RATE_THRESHOLD,
    LOSS_RATE_BAD_THRESHOLD,
    LOSS_RATE_GOOD_THRESHOLD,
    MIN_WINDOW_SIZE,
    MAX_WINDOW_SIZE,
    AdaptiveWindowController,
    RTTEstimator,
)
from transport.checksum_tracker import ChecksumTracker
from transport.sliding_window import SlidingWindowSender
from core.node import MeshNode


class RTTEstimatorTests(unittest.TestCase):
    def test_first_sample_sets_srtt(self):
        est = RTTEstimator()
        est.add_sample(0.5)

        self.assertAlmostEqual(est.srtt, 0.5)
        self.assertAlmostEqual(est.rttvar, 0.25)
        self.assertEqual(est.samples, 1)

    def test_rto_converges_with_stable_rtt(self):
        est = RTTEstimator()
        for _ in range(20):
            est.add_sample(0.1)

        self.assertAlmostEqual(est.srtt, 0.1, places=2)
        # RTO should be close to SRTT + small deviation.
        self.assertGreater(est.rto, 0.1)
        self.assertLess(est.rto, 0.5)

    def test_rto_increases_with_high_rtt(self):
        est = RTTEstimator()
        est.add_sample(0.1)
        old_rto = est.rto
        est.add_sample(2.0)
        self.assertGreater(est.rto, old_rto)


class AdaptiveDecisionTests(unittest.TestCase):
    """Test the decision logic directly (no threads, no sockets)."""

    def _make_controller(self, window_size=4, ack_timeout=1.0):
        node = MeshNode(node_id="TEST", ip="127.0.0.1", port=0)
        node.start_networking()
        sender = SlidingWindowSender(
            node, node.udp_socket, window_size=window_size, ack_timeout=ack_timeout,
        )
        tracker = ChecksumTracker()
        controller = AdaptiveWindowController(sender, tracker)
        self._node = node
        return controller, sender, tracker

    def tearDown(self):
        if hasattr(self, "_node"):
            self._node.stop_networking()

    def test_increase_on_good_network(self):
        controller, sender, _ = self._make_controller(window_size=4)
        decision = controller._decide(loss_rate=0.01, corruption_rate=0.0)
        self.assertEqual(decision, "increase")

    def test_decrease_on_high_loss(self):
        controller, _, _ = self._make_controller()
        decision = controller._decide(loss_rate=0.20, corruption_rate=0.0)
        self.assertEqual(decision, "decrease_loss")

    def test_decrease_on_high_corruption(self):
        controller, _, _ = self._make_controller()
        decision = controller._decide(loss_rate=0.0, corruption_rate=0.15)
        self.assertEqual(decision, "decrease_corruption")

    def test_hold_on_moderate_loss(self):
        controller, _, _ = self._make_controller()
        decision = controller._decide(loss_rate=0.10, corruption_rate=0.0)
        self.assertEqual(decision, "hold")

    def test_apply_increase_grows_window(self):
        controller, sender, _ = self._make_controller(window_size=4)
        controller._apply("increase")
        self.assertEqual(sender.window_size, 4 + ADDITIVE_INCREASE)

    def test_apply_increase_respects_max(self):
        controller, sender, _ = self._make_controller(window_size=MAX_WINDOW_SIZE)
        controller._apply("increase")
        self.assertEqual(sender.window_size, MAX_WINDOW_SIZE)

    def test_apply_decrease_loss_shrinks_window(self):
        controller, sender, _ = self._make_controller(window_size=8)
        old_timeout = sender.ack_timeout
        controller._apply("decrease_loss")
        self.assertEqual(sender.window_size, 4)  # 8 * 0.5
        self.assertGreater(sender.ack_timeout, old_timeout)

    def test_apply_decrease_respects_min(self):
        controller, sender, _ = self._make_controller(window_size=1)
        controller._apply("decrease_loss")
        self.assertEqual(sender.window_size, MIN_WINDOW_SIZE)

    def test_apply_decrease_corruption_shrinks_and_backs_off_timeout(self):
        controller, sender, _ = self._make_controller(window_size=8, ack_timeout=1.0)
        controller._apply("decrease_corruption")
        self.assertEqual(sender.window_size, 4)
        self.assertAlmostEqual(sender.ack_timeout, 2.0)

    def test_hold_does_not_change_anything(self):
        controller, sender, _ = self._make_controller(window_size=6, ack_timeout=1.0)
        controller._apply("hold")
        self.assertEqual(sender.window_size, 6)
        self.assertAlmostEqual(sender.ack_timeout, 1.0)


class AdaptiveSnapshotTests(unittest.TestCase):
    def test_snapshot_is_none_before_evaluation(self):
        node = MeshNode(node_id="TEST", ip="127.0.0.1", port=0)
        node.start_networking()
        sender = SlidingWindowSender(node, node.udp_socket)
        controller = AdaptiveWindowController(sender)
        try:
            self.assertIsNone(controller.current_snapshot())
        finally:
            node.stop_networking()

    def test_evaluate_produces_snapshot(self):
        node = MeshNode(node_id="TEST", ip="127.0.0.1", port=0)
        node.start_networking()
        sender = SlidingWindowSender(node, node.udp_socket, window_size=4)
        controller = AdaptiveWindowController(sender)
        try:
            controller._evaluate()
            snap = controller.current_snapshot()
            self.assertIsNotNone(snap)
            self.assertGreater(snap.timestamp, 0)
        finally:
            node.stop_networking()


if __name__ == "__main__":
    unittest.main()
