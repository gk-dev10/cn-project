import threading
import unittest

from core.node import MeshNode
from transport.reliable_transport import ReliableTransport


class ReliableTransportTests(unittest.TestCase):
    def test_reliable_message_is_acknowledged_and_delivered_once(self):
        received_event = threading.Event()
        received_packets = []

        def handle_packet(packet, address):
            received_packets.append(packet)
            received_event.set()

        sender_node = MeshNode(node_id="DEVICE_A", ip="127.0.0.1", port=0)
        receiver_node = MeshNode(node_id="DEVICE_B", ip="127.0.0.1", port=0)
        sender_node.start_networking()
        receiver_node.start_networking()

        sender = ReliableTransport(
            sender_node,
            udp_socket=sender_node.udp_socket,
            ack_timeout=0.1,
            max_retries=2,
            check_interval=0.005,
        )
        receiver = ReliableTransport(
            receiver_node,
            udp_socket=receiver_node.udp_socket,
            ack_timeout=0.1,
            max_retries=2,
            check_interval=0.005,
            on_packet=handle_packet,
        )

        try:
            receiver.start()
            sender.start()

            result = sender.send_message(
                destination="DEVICE_B",
                address=receiver_node.udp_socket.local_address,
                message="Reliable hello",
            )

            self.assertTrue(result.acknowledged)
            self.assertIsNone(result.failed_reason)
            self.assertTrue(received_event.wait(1))
            self.assertEqual(len(received_packets), 1)
            self.assertEqual(received_packets[0]["payload"], "Reliable hello")
            self.assertEqual(sender.pending_packets, {})
        finally:
            sender.stop()
            receiver.stop()
            sender_node.stop_networking()
            receiver_node.stop_networking()

    def test_reliable_message_fails_after_retries_without_ack(self):
        sender_node = MeshNode(node_id="DEVICE_A", ip="127.0.0.1", port=0)
        sender_node.start_networking()
        sender = ReliableTransport(
            sender_node,
            udp_socket=sender_node.udp_socket,
            ack_timeout=0.02,
            max_retries=2,
            check_interval=0.005,
        )

        try:
            sender.start()
            result = sender.send_message(
                destination="DEVICE_B",
                address=("127.0.0.1", 9),
                message="No receiver",
            )

            self.assertFalse(result.acknowledged)
            self.assertEqual(result.failed_reason, "ACK not received")
            self.assertEqual(result.retries, 2)
            self.assertEqual(sender.pending_packets, {})
        finally:
            sender.stop()
            sender_node.stop_networking()


if __name__ == "__main__":
    unittest.main()
