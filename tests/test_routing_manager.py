"""Tests for Module 15 — Routing Manager."""

import time
import unittest

from core.node import MeshNode
from routing.routing_manager import RoutingManager, RoutingStrategy
from routing.topology import NetworkTopology


class RoutingManagerLinkStateTests(unittest.TestCase):
    def test_link_state_routes_installed(self):
        node = MeshNode(node_id="A", ip="127.0.0.1", port=0)
        node.start_networking()
        peer = MeshNode(node_id="B", ip="127.0.0.1", port=0)
        peer.start_networking()
        node.add_neighbor("B", "127.0.0.1", peer.udp_socket.local_address[1])

        mgr = RoutingManager(
            node,
            strategy=RoutingStrategy.LINK_STATE,
            udp_socket=node.udp_socket,
            interval=0.5,
        )
        try:
            mgr.start()
            self.assertTrue(mgr.is_running)
            time.sleep(1.5)

            hop = mgr.get_next_hop("B")
            self.assertEqual(hop, "B")

            table = mgr.current_routing_table()
            self.assertIn("B", table)
        finally:
            mgr.stop()
            node.stop_networking()
            peer.stop_networking()

    def test_repr(self):
        node = MeshNode(node_id="X", ip="127.0.0.1", port=0)
        mgr = RoutingManager(node, strategy=RoutingStrategy.LINK_STATE)
        self.assertIn("LINK_STATE", repr(mgr))
        self.assertIn("stopped", repr(mgr))


class RoutingManagerDVTests(unittest.TestCase):
    def test_distance_vector_routes_installed(self):
        node_a = MeshNode(node_id="A", ip="127.0.0.1", port=0)
        node_b = MeshNode(node_id="B", ip="127.0.0.1", port=0)
        node_a.start_networking()
        node_b.start_networking()

        a_port = node_a.udp_socket.local_address[1]
        b_port = node_b.udp_socket.local_address[1]
        node_a.add_neighbor("B", "127.0.0.1", b_port)
        node_b.add_neighbor("A", "127.0.0.1", a_port)

        mgr_a = RoutingManager(
            node_a,
            strategy=RoutingStrategy.DISTANCE_VECTOR,
            udp_socket=node_a.udp_socket,
            interval=0.5,
        )
        mgr_b = RoutingManager(
            node_b,
            strategy=RoutingStrategy.DISTANCE_VECTOR,
            udp_socket=node_b.udp_socket,
            interval=0.5,
        )
        try:
            mgr_a.start()
            mgr_b.start()
            time.sleep(2.0)

            self.assertEqual(mgr_a.get_next_hop("B"), "B")
            self.assertEqual(mgr_b.get_next_hop("A"), "A")
        finally:
            mgr_a.stop()
            mgr_b.stop()
            node_a.stop_networking()
            node_b.stop_networking()


class RoutingManagerSwitchTests(unittest.TestCase):
    def test_switch_strategy(self):
        node = MeshNode(node_id="X", ip="127.0.0.1", port=0)
        node.start_networking()
        node.add_neighbor("Y", "127.0.0.1", 9999)

        mgr = RoutingManager(
            node,
            strategy=RoutingStrategy.LINK_STATE,
            udp_socket=node.udp_socket,
            interval=0.5,
        )
        try:
            mgr.start()
            self.assertEqual(mgr.strategy, RoutingStrategy.LINK_STATE)
            self.assertTrue(mgr.is_running)

            mgr.switch_strategy(RoutingStrategy.DISTANCE_VECTOR)
            self.assertEqual(mgr.strategy, RoutingStrategy.DISTANCE_VECTOR)
            self.assertTrue(mgr.is_running)
        finally:
            mgr.stop()
            node.stop_networking()

    def test_format_when_not_started(self):
        node = MeshNode(node_id="X", ip="127.0.0.1", port=0)
        mgr = RoutingManager(node)
        self.assertEqual(mgr.format_routing_table(), "(routing not started)")

    def test_get_route_when_not_started(self):
        node = MeshNode(node_id="X", ip="127.0.0.1", port=0)
        mgr = RoutingManager(node)
        self.assertIsNone(mgr.get_route("Y"))


if __name__ == "__main__":
    unittest.main()
