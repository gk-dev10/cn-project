"""Tests for Module 12 — Dijkstra's Algorithm."""

import unittest

from routing.dijkstra import INFINITY, DijkstraResult, run_dijkstra


class DijkstraSimpleTests(unittest.TestCase):
    """Test Dijkstra on small hand-crafted graphs."""

    def test_single_node(self):
        graph = {"A": {}}
        result = run_dijkstra(graph, "A")

        self.assertEqual(result.distances["A"], 0)
        self.assertEqual(result.routing_table(), {})

    def test_two_nodes(self):
        graph = {
            "A": {"B": 1},
            "B": {"A": 1},
        }
        result = run_dijkstra(graph, "A")

        self.assertEqual(result.distances["A"], 0)
        self.assertEqual(result.distances["B"], 1)
        self.assertEqual(result.next_hop("B"), "B")
        self.assertEqual(result.shortest_path("B"), ["A", "B"])

    def test_linear_three_nodes(self):
        # A --1-- B --1-- C
        graph = {
            "A": {"B": 1},
            "B": {"A": 1, "C": 1},
            "C": {"B": 1},
        }
        result = run_dijkstra(graph, "A")

        self.assertEqual(result.distances["C"], 2)
        self.assertEqual(result.next_hop("C"), "B")
        self.assertEqual(result.shortest_path("C"), ["A", "B", "C"])

    def test_diamond_topology(self):
        # A --1-- B --1-- D
        # |               |
        # 1               1
        # |               |
        # C ------1------ D
        graph = {
            "A": {"B": 1, "C": 1},
            "B": {"A": 1, "D": 1},
            "C": {"A": 1, "D": 1},
            "D": {"B": 1, "C": 1},
        }
        result = run_dijkstra(graph, "A")

        self.assertEqual(result.distances["D"], 2)
        # Next hop could be B or C (both cost 2).
        self.assertIn(result.next_hop("D"), ("B", "C"))

    def test_weighted_graph_prefers_shorter_path(self):
        # A --1-- B --1-- D   (cost 2 via B)
        # A --5-- C --1-- D   (cost 6 via C)
        graph = {
            "A": {"B": 1, "C": 5},
            "B": {"A": 1, "D": 1},
            "C": {"A": 5, "D": 1},
            "D": {"B": 1, "C": 1},
        }
        result = run_dijkstra(graph, "A")

        self.assertEqual(result.distances["D"], 2)
        self.assertEqual(result.next_hop("D"), "B")
        self.assertEqual(result.shortest_path("D"), ["A", "B", "D"])

    def test_disconnected_node(self):
        graph = {
            "A": {"B": 1},
            "B": {"A": 1},
            "C": {},
        }
        result = run_dijkstra(graph, "A")

        self.assertEqual(result.distances["C"], INFINITY)
        self.assertIsNone(result.next_hop("C"))
        self.assertIsNone(result.shortest_path("C"))

    def test_source_not_in_graph_raises(self):
        graph = {"A": {}}
        with self.assertRaises(KeyError):
            run_dijkstra(graph, "MISSING")


class DijkstraRoutingTableTests(unittest.TestCase):
    def test_routing_table_from_diamond(self):
        graph = {
            "A": {"B": 1, "C": 1},
            "B": {"A": 1, "D": 1},
            "C": {"A": 1, "D": 1},
            "D": {"B": 1, "C": 1},
        }
        result = run_dijkstra(graph, "A")
        table = result.routing_table()

        self.assertIn("B", table)
        self.assertIn("C", table)
        self.assertIn("D", table)
        self.assertNotIn("A", table)  # source excluded

        # Direct neighbors: next_hop == themselves.
        self.assertEqual(table["B"], ("B", 1))
        self.assertEqual(table["C"], ("C", 1))
        # D is 2 hops away.
        dest_hop, dest_cost = table["D"]
        self.assertIn(dest_hop, ("B", "C"))
        self.assertEqual(dest_cost, 2)

    def test_routing_table_excludes_unreachable(self):
        graph = {
            "A": {"B": 1},
            "B": {"A": 1},
            "C": {},
        }
        table = run_dijkstra(graph, "A").routing_table()
        self.assertNotIn("C", table)

    def test_larger_topology(self):
        #  A --1-- B --1-- C
        #  |               |
        #  2               1
        #  |               |
        #  D ------3------ E
        graph = {
            "A": {"B": 1, "D": 2},
            "B": {"A": 1, "C": 1},
            "C": {"B": 1, "E": 1},
            "D": {"A": 2, "E": 3},
            "E": {"C": 1, "D": 3},
        }
        result = run_dijkstra(graph, "A")

        self.assertEqual(result.distances["A"], 0)
        self.assertEqual(result.distances["B"], 1)
        self.assertEqual(result.distances["C"], 2)
        self.assertEqual(result.distances["D"], 2)
        self.assertEqual(result.distances["E"], 3)

        # Path to E: A→B→C→E (cost 3) beats A→D→E (cost 5).
        self.assertEqual(result.shortest_path("E"), ["A", "B", "C", "E"])
        self.assertEqual(result.next_hop("E"), "B")


class DijkstraResultTests(unittest.TestCase):
    def test_next_hop_for_source_is_none(self):
        graph = {"A": {"B": 1}, "B": {"A": 1}}
        result = run_dijkstra(graph, "A")
        self.assertIsNone(result.next_hop("A"))

    def test_shortest_path_to_self(self):
        graph = {"A": {"B": 1}, "B": {"A": 1}}
        result = run_dijkstra(graph, "A")
        path = result.shortest_path("A")
        self.assertEqual(path, ["A"])


if __name__ == "__main__":
    unittest.main()
