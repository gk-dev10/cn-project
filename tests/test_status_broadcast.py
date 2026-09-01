import threading
import unittest

from application.status_broadcast import StatusBroadcastService
from core.node import MeshNode


class StatusBroadcastTests(unittest.TestCase):
    def test_status_broadcast_reaches_direct_peer(self):
        received = []
        event = threading.Event()

        def on_status(status_message):
            received.append(status_message)
            event.set()

        node_a = MeshNode(node_id="DEVICE_A", ip="127.0.0.1", port=0)
        node_b = MeshNode(node_id="DEVICE_B", ip="127.0.0.1", port=0)
        node_a.start_networking()
        node_b.start_networking()

        sender = StatusBroadcastService(
            node_a,
            udp_socket=node_a.udp_socket,
            targets=[node_b.udp_socket.local_address],
        )
        receiver = StatusBroadcastService(
            node_b,
            udp_socket=node_b.udp_socket,
            on_status=on_status,
        )

        try:
            receiver.start()
            sender.broadcast_status(status="SAFE", message="All clear")

            self.assertTrue(event.wait(2))
            self.assertEqual(received[0].source, "DEVICE_A")
            self.assertEqual(received[0].status, "SAFE")
            self.assertEqual(received[0].message, "All clear")
        finally:
            receiver.stop()
            sender.stop()
            node_a.stop_networking()
            node_b.stop_networking()

    def test_status_broadcast_is_relayed_once(self):
        received_at_c = []
        event = threading.Event()

        def on_status_c(status_message):
            received_at_c.append(status_message)
            event.set()

        node_a = MeshNode(node_id="A", ip="127.0.0.1", port=0)
        node_b = MeshNode(node_id="B", ip="127.0.0.1", port=0)
        node_c = MeshNode(node_id="C", ip="127.0.0.1", port=0)
        node_a.start_networking()
        node_b.start_networking()
        node_c.start_networking()

        service_a = StatusBroadcastService(
            node_a,
            udp_socket=node_a.udp_socket,
            targets=[node_b.udp_socket.local_address],
        )
        service_b = StatusBroadcastService(
            node_b,
            udp_socket=node_b.udp_socket,
            targets=[node_c.udp_socket.local_address],
        )
        service_c = StatusBroadcastService(
            node_c,
            udp_socket=node_c.udp_socket,
            on_status=on_status_c,
        )

        try:
            service_b.start()
            service_c.start()
            service_a.broadcast_status(status="SAFE")

            self.assertTrue(event.wait(2))
            self.assertEqual(len(received_at_c), 1)
            self.assertEqual(received_at_c[0].source, "A")
            self.assertEqual(received_at_c[0].status, "SAFE")
        finally:
            service_a.stop()
            service_b.stop()
            service_c.stop()
            node_a.stop_networking()
            node_b.stop_networking()
            node_c.stop_networking()


if __name__ == "__main__":
    unittest.main()

