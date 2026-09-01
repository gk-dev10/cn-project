import threading
import unittest

from core.constants import PacketType
from core.node import MeshNode
from core.packet import create_packet
from simulator.network_simulator import NetworkSimulator


class NetworkSimulatorTests(unittest.TestCase):
    def test_packet_loss_drops_all_when_rate_is_one(self):
        node = MeshNode(node_id="A", ip="127.0.0.1", port=0)
        node.start_networking()
        simulator = NetworkSimulator(loss_rate=1.0, random_seed=1)
        packet = create_packet(PacketType.MESSAGE, "A", "B", payload="drop")

        try:
            result = simulator.send_packet(node.udp_socket, packet, ("127.0.0.1", 9))

            self.assertTrue(result.dropped)
            self.assertEqual(result.reason, "packet loss")
            self.assertEqual(simulator.stats().dropped_loss, 1)
        finally:
            node.stop_networking()

    def test_delayed_packet_is_delivered(self):
        event = threading.Event()
        received = []

        def on_packet(packet, address):
            received.append(packet)
            event.set()

        sender = MeshNode(node_id="A", ip="127.0.0.1", port=0)
        receiver = MeshNode(node_id="B", ip="127.0.0.1", port=0)
        sender.start_networking()
        receiver.start_networking(on_packet=on_packet)

        simulator = NetworkSimulator(loss_rate=0.0, base_delay_seconds=0.02, random_seed=1)
        packet = create_packet(PacketType.MESSAGE, "A", "B", payload="delayed")

        try:
            result = simulator.send_packet(sender.udp_socket, packet, receiver.udp_socket.local_address)
            self.assertTrue(result.accepted)
            self.assertFalse(result.delivered)

            self.assertTrue(event.wait(1))
            self.assertEqual(received[0]["payload"], "delayed")
            self.assertEqual(simulator.stats().delivered, 1)
        finally:
            sender.stop_networking()
            receiver.stop_networking()

    def test_failed_node_drops_packet(self):
        node = MeshNode(node_id="A", ip="127.0.0.1", port=0)
        node.start_networking()
        simulator = NetworkSimulator(loss_rate=0.0)
        simulator.fail_node("B")
        packet = create_packet(PacketType.MESSAGE, "A", "B", payload="blocked")

        try:
            result = simulator.send_packet(
                node.udp_socket,
                packet,
                ("127.0.0.1", 9),
                source_node="A",
                destination_node="B",
            )

            self.assertTrue(result.dropped)
            self.assertEqual(result.reason, "node failure")
            self.assertEqual(simulator.stats().dropped_node_failure, 1)
        finally:
            node.stop_networking()


if __name__ == "__main__":
    unittest.main()

