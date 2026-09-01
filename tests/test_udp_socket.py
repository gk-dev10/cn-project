import threading
import unittest

from core.constants import PacketType
from core.packet import create_packet
from transport.udp_socket import UDPSocket


class UDPSocketTests(unittest.TestCase):
    def test_send_and_receive_packet_over_loopback(self):
        receiver = UDPSocket(host="127.0.0.1", port=0)
        sender = UDPSocket(host="127.0.0.1", port=0)

        try:
            receiver.start_socket()
            sender.start_socket()
            packet = create_packet(PacketType.MESSAGE, "DEVICE_A", "DEVICE_B", 1, payload="Hello")

            sender.send_packet(packet, receiver.local_address)
            received = receiver.receive_packet(timeout=1)

            self.assertIsNotNone(received)
            received_packet, address = received
            self.assertEqual(received_packet, packet)
            self.assertEqual(address[0], "127.0.0.1")
        finally:
            sender.stop_socket()
            receiver.stop_socket()

    def test_async_receive_callback(self):
        received_event = threading.Event()
        received_packet = {}

        def handle_packet(packet, address):
            received_packet["packet"] = packet
            received_packet["address"] = address
            received_event.set()

        receiver = UDPSocket(host="127.0.0.1", port=0, on_packet=handle_packet)
        sender = UDPSocket(host="127.0.0.1", port=0)

        try:
            receiver.start_socket()
            sender.start_socket()
            packet = create_packet(PacketType.MESSAGE, "DEVICE_A", "DEVICE_B", 1, payload="Async")

            sender.send_packet(packet, receiver.local_address)

            self.assertTrue(received_event.wait(1))
            self.assertEqual(received_packet["packet"], packet)
        finally:
            sender.stop_socket()
            receiver.stop_socket()


if __name__ == "__main__":
    unittest.main()

