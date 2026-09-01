"""Tests for Module 11 — Link-State Routing Service."""

import threading
import time
import unittest

from core.node import MeshNode
from routing.link_state import LinkStateService
from routing.topology import NetworkTopology


class LinkStateRoutingTests(unittest.TestCase):
    """End-to-end tests with real UDP sockets on localhost."""

    def test_two_nodes_discover_routes(self):
        """Two directly connected nodes should build routing tables for each other."""
        node_a = MeshNode(node_id="DEVICE_A", ip="127.0.0.1", port=0)
        node_b = MeshNode(node_id="DEVICE_B", ip="127.0.0.1", port=0)
        node_a.start_networking()
        node_b.start_networking()

        # Each node knows the other as a direct neighbor.
        b_port = node_b.udp_socket.local_address[1]
        a_port = node_a.udp_socket.local_address[1]
        node_a.add_neighbor("DEVICE_B", "127.0.0.1", b_port)
        node_b.add_neighbor("DEVICE_A", "127.0.0.1", a_port)

        topo_a = NetworkTopology(self_node_id="DEVICE_A")
        topo_b = NetworkTopology(self_node_id="DEVICE_B")

        route_changes_a = []
        route_changes_b = []

        ls_a = LinkStateService(
            node_a, topo_a,
            udp_socket=node_a.udp_socket,
            interval=0.5,
            on_route_change=lambda t: route_changes_a.append(t),
        )
        ls_b = LinkStateService(
            node_b, topo_b,
            udp_socket=node_b.udp_socket,
            interval=0.5,
            on_route_change=lambda t: route_changes_b.append(t),
        )

        try:
            ls_a.start()
            ls_b.start()

            # Wait for a couple of LSA cycles.
            time.sleep(2.0)

            # Node A should have a route to B.
            table_a = ls_a.current_routing_table()
            self.assertIn("DEVICE_B", table_a)
            hop_a, cost_a = table_a["DEVICE_B"]
            self.assertEqual(hop_a, "DEVICE_B")
            self.assertEqual(cost_a, 1)

            # Node B should have a route to A.
            table_b = ls_b.current_routing_table()
            self.assertIn("DEVICE_A", table_b)
            hop_b, cost_b = table_b["DEVICE_A"]
            self.assertEqual(hop_b, "DEVICE_A")
            self.assertEqual(cost_b, 1)

            # Routes are installed in MeshNode.
            self.assertEqual(node_a.get_next_hop("DEVICE_B"), "DEVICE_B")
            self.assertEqual(node_b.get_next_hop("DEVICE_A"), "DEVICE_A")

        finally:
            ls_a.stop()
            ls_b.stop()
            node_a.stop_networking()
            node_b.stop_networking()

    def test_three_node_chain_discovers_multihop_route(self):
        """A -- B -- C should let A discover a 2-hop route to C via B."""
        node_a = MeshNode(node_id="A", ip="127.0.0.1", port=0)
        node_b = MeshNode(node_id="B", ip="127.0.0.1", port=0)
        node_c = MeshNode(node_id="C", ip="127.0.0.1", port=0)
        node_a.start_networking()
        node_b.start_networking()
        node_c.start_networking()

        a_port = node_a.udp_socket.local_address[1]
        b_port = node_b.udp_socket.local_address[1]
        c_port = node_c.udp_socket.local_address[1]

        # A <-> B
        node_a.add_neighbor("B", "127.0.0.1", b_port)
        node_b.add_neighbor("A", "127.0.0.1", a_port)
        # B <-> C
        node_b.add_neighbor("C", "127.0.0.1", c_port)
        node_c.add_neighbor("B", "127.0.0.1", b_port)

        topo_a = NetworkTopology(self_node_id="A")
        topo_b = NetworkTopology(self_node_id="B")
        topo_c = NetworkTopology(self_node_id="C")

        ls_a = LinkStateService(node_a, topo_a, udp_socket=node_a.udp_socket, interval=0.5)
        ls_b = LinkStateService(node_b, topo_b, udp_socket=node_b.udp_socket, interval=0.5)
        ls_c = LinkStateService(node_c, topo_c, udp_socket=node_c.udp_socket, interval=0.5)

        try:
            ls_a.start()
            ls_b.start()
            ls_c.start()

            # Allow enough time for LSAs to propagate A→B→C and C→B→A.
            time.sleep(3.0)

            # A should know about C (2 hops, via B).
            table_a = ls_a.current_routing_table()
            self.assertIn("C", table_a, f"A's routing table: {table_a}")
            hop_to_c, cost_to_c = table_a["C"]
            self.assertEqual(hop_to_c, "B")
            self.assertEqual(cost_to_c, 2)

            # C should know about A (2 hops, via B).
            table_c = ls_c.current_routing_table()
            self.assertIn("A", table_c, f"C's routing table: {table_c}")
            hop_to_a, cost_to_a = table_c["A"]
            self.assertEqual(hop_to_a, "B")
            self.assertEqual(cost_to_a, 2)

        finally:
            ls_a.stop()
            ls_b.stop()
            ls_c.stop()
            node_a.stop_networking()
            node_b.stop_networking()
            node_c.stop_networking()

    def test_announce_produces_routing_table(self):
        """A single call to announce() should produce a routing table."""
        node = MeshNode(node_id="X", ip="127.0.0.1", port=0)
        node.start_networking()
        peer = MeshNode(node_id="Y", ip="127.0.0.1", port=0)
        peer.start_networking()

        node.add_neighbor("Y", "127.0.0.1", peer.udp_socket.local_address[1])
        topo = NetworkTopology(self_node_id="X")

        ls = LinkStateService(node, topo, udp_socket=node.udp_socket)

        try:
            ls.start()
            ls.announce()
            table = ls.current_routing_table()
            self.assertIn("Y", table)
        finally:
            ls.stop()
            node.stop_networking()
            peer.stop_networking()

    def test_format_routing_table(self):
        node = MeshNode(node_id="X", ip="127.0.0.1", port=0)
        node.start_networking()
        node.add_neighbor("Y", "127.0.0.1", 9999)
        topo = NetworkTopology(self_node_id="X")

        ls = LinkStateService(node, topo, udp_socket=node.udp_socket)

        try:
            ls.start()
            ls.announce()
            formatted = ls.format_routing_table()
            self.assertIn("Destination", formatted)
            self.assertIn("Y", formatted)
        finally:
            ls.stop()
            node.stop_networking()


if __name__ == "__main__":
    unittest.main()
