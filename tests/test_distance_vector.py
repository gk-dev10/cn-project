"""Tests for Module 13 — Distance-Vector Routing Service."""

import time
import unittest

from core.node import MeshNode
from routing.distance_vector import DistanceVectorService


class DistanceVectorEndToEndTests(unittest.TestCase):
    """End-to-end tests with real UDP on localhost."""

    def test_two_nodes_exchange_vectors(self):
        """Two directly connected nodes should learn routes to each other."""
        node_a = MeshNode(node_id="A", ip="127.0.0.1", port=0)
        node_b = MeshNode(node_id="B", ip="127.0.0.1", port=0)
        node_a.start_networking()
        node_b.start_networking()

        a_port = node_a.udp_socket.local_address[1]
        b_port = node_b.udp_socket.local_address[1]
        node_a.add_neighbor("B", "127.0.0.1", b_port)
        node_b.add_neighbor("A", "127.0.0.1", a_port)

        dv_a = DistanceVectorService(node_a, node_a.udp_socket, interval=0.5)
        dv_b = DistanceVectorService(node_b, node_b.udp_socket, interval=0.5)

        try:
            dv_a.start()
            dv_b.start()
            time.sleep(2.0)

            table_a = dv_a.current_routing_table()
            self.assertIn("B", table_a)
            hop, cost = table_a["B"]
            self.assertEqual(hop, "B")
            self.assertEqual(cost, 1)

            table_b = dv_b.current_routing_table()
            self.assertIn("A", table_b)
            hop_b, cost_b = table_b["A"]
            self.assertEqual(hop_b, "A")
            self.assertEqual(cost_b, 1)

            # Routes installed in MeshNode.
            self.assertEqual(node_a.get_next_hop("B"), "B")
            self.assertEqual(node_b.get_next_hop("A"), "A")
        finally:
            dv_a.stop()
            dv_b.stop()
            node_a.stop_networking()
            node_b.stop_networking()

    def test_three_node_chain_learns_multihop(self):
        """A -- B -- C: A should discover C at cost 2 via B."""
        node_a = MeshNode(node_id="A", ip="127.0.0.1", port=0)
        node_b = MeshNode(node_id="B", ip="127.0.0.1", port=0)
        node_c = MeshNode(node_id="C", ip="127.0.0.1", port=0)
        node_a.start_networking()
        node_b.start_networking()
        node_c.start_networking()

        a_port = node_a.udp_socket.local_address[1]
        b_port = node_b.udp_socket.local_address[1]
        c_port = node_c.udp_socket.local_address[1]

        node_a.add_neighbor("B", "127.0.0.1", b_port)
        node_b.add_neighbor("A", "127.0.0.1", a_port)
        node_b.add_neighbor("C", "127.0.0.1", c_port)
        node_c.add_neighbor("B", "127.0.0.1", b_port)

        dv_a = DistanceVectorService(node_a, node_a.udp_socket, interval=0.5)
        dv_b = DistanceVectorService(node_b, node_b.udp_socket, interval=0.5)
        dv_c = DistanceVectorService(node_c, node_c.udp_socket, interval=0.5)

        try:
            dv_a.start()
            dv_b.start()
            dv_c.start()
            # DV needs 2+ rounds to propagate: B→A learns about C, then A gets it.
            time.sleep(4.0)

            table_a = dv_a.current_routing_table()
            self.assertIn("C", table_a, f"A's table: {table_a}")
            hop, cost = table_a["C"]
            self.assertEqual(hop, "B")
            self.assertEqual(cost, 2)

            table_c = dv_c.current_routing_table()
            self.assertIn("A", table_c, f"C's table: {table_c}")
            hop_c, cost_c = table_c["A"]
            self.assertEqual(hop_c, "B")
            self.assertEqual(cost_c, 2)
        finally:
            dv_a.stop()
            dv_b.stop()
            dv_c.stop()
            node_a.stop_networking()
            node_b.stop_networking()
            node_c.stop_networking()

    def test_format_routing_table(self):
        node = MeshNode(node_id="X", ip="127.0.0.1", port=0)
        node.start_networking()
        node.add_neighbor("Y", "127.0.0.1", 9999)

        dv = DistanceVectorService(node, node.udp_socket, interval=0.5)
        try:
            dv.start()
            dv.announce()
            text = dv.format_routing_table()
            self.assertIn("Y", text)
        finally:
            dv.stop()
            node.stop_networking()


if __name__ == "__main__":
    unittest.main()
