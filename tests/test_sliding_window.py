"""Tests for Module 8 — Go-Back-N Sliding Window Protocol."""

import threading
import time
import unittest

from core.constants import PacketType
from core.node import MeshNode
from transport.sliding_window import (
    SlidingWindowReceiver,
    SlidingWindowSender,
    WindowStats,
)


class WindowStatsTests(unittest.TestCase):
    def test_loss_rate_zero_when_no_packets(self):
        stats = WindowStats()
        self.assertEqual(stats.loss_rate, 0.0)

    def test_loss_rate_calculated_correctly(self):
        stats = WindowStats(packets_sent=10, retransmissions=2)
        self.assertAlmostEqual(stats.loss_rate, 2 / 12)


class SlidingWindowEndToEndTests(unittest.TestCase):
    """End-to-end tests with real UDP sockets on localhost."""

    def setUp(self):
        self.sender_node = MeshNode(node_id="SENDER", ip="127.0.0.1", port=0)
        self.receiver_node = MeshNode(node_id="RECEIVER", ip="127.0.0.1", port=0)
        self.sender_node.start_networking()
        self.receiver_node.start_networking()

        self.delivered: list[tuple[int, dict]] = []
        self.delivered_event = threading.Event()
        self.expected_count = 0

    def tearDown(self):
        self.sender_node.stop_networking()
        self.receiver_node.stop_networking()

    def _on_deliver(self, seq: int, packet: dict, address: tuple[str, int]) -> None:
        self.delivered.append((seq, packet))
        if len(self.delivered) >= self.expected_count:
            self.delivered_event.set()

    def test_single_packet_delivered(self):
        self.expected_count = 1

        sender = SlidingWindowSender(
            self.sender_node,
            self.sender_node.udp_socket,
            window_size=4,
            ack_timeout=0.1,
            check_interval=0.01,
        )
        receiver = SlidingWindowReceiver(
            self.receiver_node,
            self.receiver_node.udp_socket,
            on_deliver=self._on_deliver,
        )

        try:
            receiver.start()
            sender.start()

            seq = sender.send(
                destination="RECEIVER",
                address=self.receiver_node.udp_socket.local_address,
                payload="Hello GBN",
            )

            self.assertTrue(sender.wait_all_acked(timeout=3))
            self.assertTrue(self.delivered_event.wait(3))
            self.assertEqual(len(self.delivered), 1)
            self.assertEqual(self.delivered[0][0], 1)
            self.assertEqual(self.delivered[0][1]["payload"], "Hello GBN")
        finally:
            sender.stop()
            receiver.stop()

    def test_multiple_packets_delivered_in_order(self):
        count = 6
        self.expected_count = count

        sender = SlidingWindowSender(
            self.sender_node,
            self.sender_node.udp_socket,
            window_size=3,
            ack_timeout=0.1,
            check_interval=0.01,
        )
        receiver = SlidingWindowReceiver(
            self.receiver_node,
            self.receiver_node.udp_socket,
            on_deliver=self._on_deliver,
        )

        try:
            receiver.start()
            sender.start()

            for i in range(count):
                sender.send(
                    destination="RECEIVER",
                    address=self.receiver_node.udp_socket.local_address,
                    payload=f"Chunk {i}",
                )

            self.assertTrue(sender.wait_all_acked(timeout=5))
            self.assertTrue(self.delivered_event.wait(5))
            self.assertEqual(len(self.delivered), count)
            # Verify in-order delivery.
            for i, (seq, pkt) in enumerate(self.delivered):
                self.assertEqual(seq, i + 1)
                self.assertEqual(pkt["payload"], f"Chunk {i}")
        finally:
            sender.stop()
            receiver.stop()

    def test_stats_track_sent_and_acked(self):
        self.expected_count = 2

        sender = SlidingWindowSender(
            self.sender_node,
            self.sender_node.udp_socket,
            window_size=4,
            ack_timeout=0.1,
            check_interval=0.01,
        )
        receiver = SlidingWindowReceiver(
            self.receiver_node,
            self.receiver_node.udp_socket,
            on_deliver=self._on_deliver,
        )

        try:
            receiver.start()
            sender.start()

            sender.send("RECEIVER", self.receiver_node.udp_socket.local_address, "A")
            sender.send("RECEIVER", self.receiver_node.udp_socket.local_address, "B")

            self.assertTrue(sender.wait_all_acked(timeout=3))
            stats = sender.stats()
            self.assertEqual(stats.packets_sent, 2)
            self.assertGreaterEqual(stats.packets_acked, 2)
        finally:
            sender.stop()
            receiver.stop()

    def test_send_all_convenience(self):
        self.expected_count = 3

        sender = SlidingWindowSender(
            self.sender_node,
            self.sender_node.udp_socket,
            window_size=4,
            ack_timeout=0.1,
            check_interval=0.01,
        )
        receiver = SlidingWindowReceiver(
            self.receiver_node,
            self.receiver_node.udp_socket,
            on_deliver=self._on_deliver,
        )

        try:
            receiver.start()
            sender.start()

            seqs = sender.send_all(
                destination="RECEIVER",
                address=self.receiver_node.udp_socket.local_address,
                payloads=["X", "Y", "Z"],
            )

            self.assertEqual(len(seqs), 3)
            self.assertTrue(sender.wait_all_acked(timeout=3))
            self.assertTrue(self.delivered_event.wait(3))
            self.assertEqual(len(self.delivered), 3)
        finally:
            sender.stop()
            receiver.stop()


if __name__ == "__main__":
    unittest.main()
