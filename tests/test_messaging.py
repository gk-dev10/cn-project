import threading
import unittest

from application.messaging import MessagingService
from core.node import MeshNode


class MessagingServiceTests(unittest.TestCase):
    def test_unreliable_message_delivered_over_udp(self):
        received = []
        event = threading.Event()

        def on_message(message):
            received.append(message)
            event.set()

        sender_node = MeshNode(node_id="DEVICE_A", ip="127.0.0.1", port=0)
        receiver_node = MeshNode(node_id="DEVICE_B", ip="127.0.0.1", port=0)
        sender_node.start_networking()
        receiver_node.start_networking()

        sender = MessagingService(sender_node, udp_socket=sender_node.udp_socket)
        receiver = MessagingService(receiver_node, udp_socket=receiver_node.udp_socket, on_message=on_message)

        try:
            receiver.start()
            result = sender.send_message(
                destination="DEVICE_B",
                address=receiver_node.udp_socket.local_address,
                text="Need medical assistance",
            )

            self.assertEqual(result.sequence_number, 1)
            self.assertFalse(result.reliable)
            self.assertTrue(event.wait(2))
            self.assertEqual(received[0].source, "DEVICE_A")
            self.assertEqual(received[0].text, "Need medical assistance")
        finally:
            receiver.stop()
            sender_node.stop_networking()
            receiver_node.stop_networking()

    def test_route_resolution_uses_next_hop(self):
        node = MeshNode(node_id="A", ip="127.0.0.1", port=0)
        node.add_neighbor("B", "127.0.0.1", 5002)
        node.update_route("C", next_hop="B", cost=2)

        service = MessagingService(node)
        address, next_hop = service.resolve_destination("C")

        self.assertEqual(address, ("127.0.0.1", 5002))
        self.assertEqual(next_hop, "B")


if __name__ == "__main__":
    unittest.main()

