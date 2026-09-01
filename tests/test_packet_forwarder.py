"""Tests for Modules 16 & 17 — Multi-Hop Packet Forwarding + TTL Management."""

import threading
import time
import unittest

from core.constants import PacketType
from core.node import MeshNode
from core.packet import create_packet
from relay.packet_forwarder import PacketForwarder


class ForwarderLocalDeliveryTests(unittest.TestCase):
    """Packets addressed to this node are delivered locally."""

    def test_packet_for_self_delivered(self):
        node = MeshNode(node_id="B", ip="127.0.0.1", port=0)
        node.start_networking()

        delivered = []
        forwarder = PacketForwarder(
            node,
            udp_socket=node.udp_socket,
            on_local_deliver=lambda pkt, addr: delivered.append(pkt),
        )

        packet = create_packet(
            PacketType.MESSAGE, source="A", destination="B",
            sequence_number=1, payload="Hello B",
        )

        try:
            forwarder.start()
            forwarder.handle_packet(packet, ("127.0.0.1", 9999))
            self.assertEqual(len(delivered), 1)
            self.assertEqual(delivered[0]["payload"], "Hello B")

            stats = forwarder.stats()
            self.assertEqual(stats.delivered_locally, 1)
            self.assertEqual(stats.forwarded, 0)
        finally:
            forwarder.stop()
            node.stop_networking()

    def test_broadcast_packet_delivered(self):
        node = MeshNode(node_id="B", ip="127.0.0.1", port=0)
        node.start_networking()

        delivered = []
        forwarder = PacketForwarder(
            node,
            udp_socket=node.udp_socket,
            on_local_deliver=lambda pkt, addr: delivered.append(pkt),
        )

        packet = create_packet(
            PacketType.MESSAGE, source="A", destination=None,
            sequence_number=1, payload="Broadcast",
        )

        try:
            forwarder.start()
            forwarder.handle_packet(packet, ("127.0.0.1", 9999))
            self.assertEqual(len(delivered), 1)
        finally:
            forwarder.stop()
            node.stop_networking()


class ForwarderTTLTests(unittest.TestCase):
    """Packets with expired TTL are dropped."""

    def test_ttl_zero_dropped(self):
        node = MeshNode(node_id="B", ip="127.0.0.1", port=0)
        node.start_networking()

        drops = []
        forwarder = PacketForwarder(
            node,
            udp_socket=node.udp_socket,
            on_drop=lambda pkt, reason, addr: drops.append(reason),
        )

        packet = create_packet(
            PacketType.MESSAGE, source="A", destination="C",
            sequence_number=1, ttl=1, payload="Will expire",
        )

        try:
            forwarder.start()
            forwarder.handle_packet(packet, ("127.0.0.1", 9999))
            self.assertEqual(len(drops), 1)
            self.assertIn("TTL", drops[0])

            stats = forwarder.stats()
            self.assertEqual(stats.dropped_ttl, 1)
        finally:
            forwarder.stop()
            node.stop_networking()


class ForwarderNoRouteTests(unittest.TestCase):
    """Packets with no route are dropped."""

    def test_no_route_dropped(self):
        node = MeshNode(node_id="B", ip="127.0.0.1", port=0)
        node.start_networking()

        drops = []
        forwarder = PacketForwarder(
            node,
            udp_socket=node.udp_socket,
            on_drop=lambda pkt, reason, addr: drops.append(reason),
        )

        packet = create_packet(
            PacketType.MESSAGE, source="A", destination="Z",
            sequence_number=1, ttl=5, payload="No route",
        )

        try:
            forwarder.start()
            # No route to Z configured.
            forwarder.handle_packet(packet, ("127.0.0.1", 9999))
            self.assertEqual(len(drops), 1)
            self.assertIn("no route", drops[0])
        finally:
            forwarder.stop()
            node.stop_networking()


class ForwarderMultiHopTests(unittest.TestCase):
    """End-to-end multi-hop forwarding with real UDP sockets."""

    def test_packet_forwarded_through_relay(self):
        """A sends to C via B (relay). B should forward."""
        node_a = MeshNode(node_id="A", ip="127.0.0.1", port=0)
        node_b = MeshNode(node_id="B", ip="127.0.0.1", port=0)
        node_c = MeshNode(node_id="C", ip="127.0.0.1", port=0)
        node_a.start_networking()
        node_b.start_networking()
        node_c.start_networking()

        a_port = node_a.udp_socket.local_address[1]
        b_port = node_b.udp_socket.local_address[1]
        c_port = node_c.udp_socket.local_address[1]

        # B knows C as a direct neighbor and has a route.
        node_b.add_neighbor("A", "127.0.0.1", a_port)
        node_b.add_neighbor("C", "127.0.0.1", c_port)
        node_b.update_route("C", next_hop="C", cost=1)

        delivered_at_c = []
        event = threading.Event()

        forwarder_b = PacketForwarder(
            node_b,
            udp_socket=node_b.udp_socket,
        )

        forwarder_c = PacketForwarder(
            node_c,
            udp_socket=node_c.udp_socket,
            on_local_deliver=lambda pkt, addr: (delivered_at_c.append(pkt), event.set()),
        )

        try:
            forwarder_b.start()
            forwarder_c.start()

            # A sends a packet destined for C, but sends it to B.
            packet = create_packet(
                PacketType.MESSAGE, source="A", destination="C",
                sequence_number=1, ttl=5, payload="Hello C via B",
            )
            node_a.udp_socket.send_packet(packet, ("127.0.0.1", b_port))

            self.assertTrue(event.wait(3))
            self.assertEqual(len(delivered_at_c), 1)
            self.assertEqual(delivered_at_c[0]["payload"], "Hello C via B")
            self.assertEqual(delivered_at_c[0]["source"], "A")

            # Check TTL was decremented.
            self.assertEqual(delivered_at_c[0]["ttl"], 4)

            # B should have forwarding stats.
            stats_b = forwarder_b.stats()
            self.assertEqual(stats_b.forwarded, 1)
        finally:
            forwarder_b.stop()
            forwarder_c.stop()
            node_a.stop_networking()
            node_b.stop_networking()
            node_c.stop_networking()

    def test_non_forwardable_type_ignored(self):
        """Packet types not in forwardable_types are silently ignored."""
        node = MeshNode(node_id="B", ip="127.0.0.1", port=0)
        node.start_networking()

        forwarder = PacketForwarder(node, udp_socket=node.udp_socket)

        packet = create_packet(
            PacketType.HEARTBEAT, source="A", destination="C",
            sequence_number=1, payload={},
        )

        try:
            forwarder.start()
            forwarder.handle_packet(packet, ("127.0.0.1", 9999))
            stats = forwarder.stats()
            self.assertEqual(stats.total_received, 0)
        finally:
            forwarder.stop()
            node.stop_networking()


class ForwarderStatsTests(unittest.TestCase):
    def test_reset_stats(self):
        node = MeshNode(node_id="B", ip="127.0.0.1", port=0)
        node.start_networking()

        forwarder = PacketForwarder(node, udp_socket=node.udp_socket)
        packet = create_packet(
            PacketType.MESSAGE, source="A", destination="B",
            sequence_number=1, payload="X",
        )

        try:
            forwarder.start()
            forwarder.handle_packet(packet, ("127.0.0.1", 9999))
            self.assertEqual(forwarder.stats().delivered_locally, 1)

            forwarder.reset_stats()
            self.assertEqual(forwarder.stats().delivered_locally, 0)
        finally:
            forwarder.stop()
            node.stop_networking()


if __name__ == "__main__":
    unittest.main()
