"""Tests for Module 10 — Network Topology Management."""

import unittest

from routing.topology import NetworkTopology


class TopologyBasicTests(unittest.TestCase):
    def test_empty_topology(self):
        topo = NetworkTopology()
        self.assertEqual(topo.node_count(), 0)
        self.assertEqual(topo.edge_count(), 0)
        self.assertEqual(topo.nodes(), [])

    def test_add_node(self):
        topo = NetworkTopology()
        self.assertTrue(topo.add_node("A"))
        self.assertTrue(topo.has_node("A"))
        # Adding again returns False.
        self.assertFalse(topo.add_node("A"))
        self.assertEqual(topo.node_count(), 1)

    def test_add_link_creates_bidirectional_edge(self):
        topo = NetworkTopology()
        topo.add_link("A", "B", cost=1)

        self.assertTrue(topo.has_link("A", "B"))
        self.assertTrue(topo.has_link("B", "A"))
        self.assertEqual(topo.link_cost("A", "B"), 1)
        self.assertEqual(topo.link_cost("B", "A"), 1)
        self.assertEqual(topo.node_count(), 2)
        self.assertEqual(topo.edge_count(), 1)

    def test_remove_link(self):
        topo = NetworkTopology()
        topo.add_link("A", "B", cost=1)
        self.assertTrue(topo.remove_link("A", "B"))
        self.assertFalse(topo.has_link("A", "B"))
        self.assertFalse(topo.has_link("B", "A"))
        # Nodes still exist.
        self.assertTrue(topo.has_node("A"))
        self.assertTrue(topo.has_node("B"))

    def test_remove_nonexistent_link_returns_false(self):
        topo = NetworkTopology()
        topo.add_node("A")
        self.assertFalse(topo.remove_link("A", "Z"))

    def test_remove_node_removes_all_links(self):
        topo = NetworkTopology()
        topo.add_link("A", "B", cost=1)
        topo.add_link("A", "C", cost=2)
        topo.remove_node("A")

        self.assertFalse(topo.has_node("A"))
        self.assertFalse(topo.has_link("B", "A"))
        self.assertFalse(topo.has_link("C", "A"))
        self.assertEqual(topo.edge_count(), 0)

    def test_update_cost(self):
        topo = NetworkTopology()
        topo.add_link("A", "B", cost=1)
        self.assertTrue(topo.update_cost("A", "B", 5))
        self.assertEqual(topo.link_cost("A", "B"), 5)
        self.assertEqual(topo.link_cost("B", "A"), 5)

    def test_update_cost_nonexistent_returns_false(self):
        topo = NetworkTopology()
        self.assertFalse(topo.update_cost("X", "Y", 1))

    def test_negative_cost_raises(self):
        topo = NetworkTopology()
        with self.assertRaises(ValueError):
            topo.add_link("A", "B", cost=-1)

    def test_neighbors_of(self):
        topo = NetworkTopology()
        topo.add_link("A", "B", cost=1)
        topo.add_link("A", "C", cost=2)

        neighbors = topo.neighbors_of("A")
        self.assertEqual(neighbors, {"B": 1, "C": 2})
        # Modifying returned dict doesn't affect topology.
        neighbors["Z"] = 99
        self.assertFalse(topo.has_link("A", "Z"))


class TopologySnapshotTests(unittest.TestCase):
    def test_snapshot_is_deep_copy(self):
        topo = NetworkTopology()
        topo.add_link("A", "B", cost=1)
        snap = topo.snapshot()
        snap["A"]["B"] = 999
        self.assertEqual(topo.link_cost("A", "B"), 1)


class TopologyBulkUpdateTests(unittest.TestCase):
    def test_update_from_neighbor_list(self):
        topo = NetworkTopology()
        changed = topo.update_from_neighbor_list("A", {"B": 1, "C": 1}, sequence_number=1)
        self.assertTrue(changed)
        self.assertTrue(topo.has_link("A", "B"))
        self.assertTrue(topo.has_link("A", "C"))

    def test_stale_sequence_rejected(self):
        topo = NetworkTopology()
        topo.update_from_neighbor_list("A", {"B": 1}, sequence_number=5)
        changed = topo.update_from_neighbor_list("A", {"C": 1}, sequence_number=3)
        self.assertFalse(changed)
        # Original link is still there.
        self.assertTrue(topo.has_link("A", "B"))
        self.assertFalse(topo.has_link("A", "C"))

    def test_bulk_update_removes_stale_links(self):
        topo = NetworkTopology()
        topo.update_from_neighbor_list("A", {"B": 1, "C": 1}, sequence_number=1)
        # Next update: A only knows B now.
        topo.update_from_neighbor_list("A", {"B": 1}, sequence_number=2)
        self.assertTrue(topo.has_link("A", "B"))
        self.assertFalse(topo.has_link("A", "C"))

    def test_diamond_topology(self):
        topo = NetworkTopology()
        topo.add_link("A", "B", 1)
        topo.add_link("A", "C", 1)
        topo.add_link("B", "D", 1)
        topo.add_link("C", "D", 1)

        self.assertEqual(topo.node_count(), 4)
        self.assertEqual(topo.edge_count(), 4)

        expected = {
            "A": {"B": 1, "C": 1},
            "B": {"A": 1, "D": 1},
            "C": {"A": 1, "D": 1},
            "D": {"B": 1, "C": 1},
        }
        self.assertEqual(topo.snapshot(), expected)


class TopologyChangeCallbackTests(unittest.TestCase):
    def test_on_change_called(self):
        changes = []
        topo = NetworkTopology(on_change=lambda c: changes.append(c))
        topo.add_link("A", "B", cost=1)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, "add_link")


class TopologyFormatTests(unittest.TestCase):
    def test_format_empty(self):
        topo = NetworkTopology()
        self.assertEqual(topo.format_table(), "(empty topology)")

    def test_format_nonempty(self):
        topo = NetworkTopology()
        topo.add_link("A", "B", cost=1)
        table = topo.format_table()
        self.assertIn("A", table)
        self.assertIn("B", table)


if __name__ == "__main__":
    unittest.main()
