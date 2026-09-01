"""Tests for Module 14 — Bellman-Ford / Distance-Vector Computation."""

import time
import unittest

from routing.bellman_ford import (
    DVRoute,
    BellmanFordResult,
    bellman_ford_relax,
    expire_routes,
    format_dv_table,
    routes_to_vector,
)


class BellmanFordRelaxTests(unittest.TestCase):
    """Test the core Bellman-Ford relaxation logic."""

    def test_new_route_added(self):
        routes: dict[str, DVRoute] = {}
        result = bellman_ford_relax(
            self_node_id="A",
            current_routes=routes,
            neighbor_id="B",
            neighbor_cost=1,
            neighbor_vector={"C": 1},
        )
        self.assertTrue(result.changed)
        self.assertIn("B", routes)
        self.assertIn("C", routes)
        self.assertEqual(routes["B"].cost, 1)
        self.assertEqual(routes["B"].next_hop, "B")
        self.assertEqual(routes["C"].cost, 2)  # 1 (A→B) + 1 (B→C)
        self.assertEqual(routes["C"].next_hop, "B")

    def test_better_route_improves(self):
        routes = {
            "C": DVRoute(destination="C", next_hop="X", cost=5),
        }
        result = bellman_ford_relax(
            self_node_id="A",
            current_routes=routes,
            neighbor_id="B",
            neighbor_cost=1,
            neighbor_vector={"C": 1},
        )
        self.assertTrue(result.changed)
        self.assertEqual(routes["C"].cost, 2)
        self.assertEqual(routes["C"].next_hop, "B")
        self.assertIn("C", result.improved)

    def test_worse_route_not_adopted(self):
        routes = {
            "C": DVRoute(destination="C", next_hop="X", cost=1),
        }
        result = bellman_ford_relax(
            self_node_id="A",
            current_routes=routes,
            neighbor_id="B",
            neighbor_cost=1,
            neighbor_vector={"C": 5},
        )
        # Route through X (cost 1) is better than B→C (cost 6).
        self.assertEqual(routes["C"].cost, 1)
        self.assertEqual(routes["C"].next_hop, "X")

    def test_route_through_same_neighbor_updated_if_cost_increases(self):
        routes = {
            "C": DVRoute(destination="C", next_hop="B", cost=2),
        }
        result = bellman_ford_relax(
            self_node_id="A",
            current_routes=routes,
            neighbor_id="B",
            neighbor_cost=1,
            neighbor_vector={"C": 5},
        )
        # Since route to C goes through B, must update even if cost increased.
        self.assertEqual(routes["C"].cost, 6)
        self.assertIn("C", result.improved)

    def test_self_node_excluded_from_routes(self):
        routes: dict[str, DVRoute] = {}
        bellman_ford_relax(
            self_node_id="A",
            current_routes=routes,
            neighbor_id="B",
            neighbor_cost=1,
            neighbor_vector={"A": 1, "C": 2},
        )
        self.assertNotIn("A", routes)
        self.assertIn("C", routes)

    def test_direct_neighbor_always_added(self):
        routes: dict[str, DVRoute] = {}
        bellman_ford_relax(
            self_node_id="A",
            current_routes=routes,
            neighbor_id="B",
            neighbor_cost=1,
            neighbor_vector={},  # Empty vector.
        )
        self.assertIn("B", routes)
        self.assertEqual(routes["B"].cost, 1)

    def test_multiple_relaxations_converge(self):
        # A -- B -- C -- D
        routes: dict[str, DVRoute] = {}

        # B tells A about itself and C.
        bellman_ford_relax("A", routes, "B", 1, {"C": 1})
        # B tells A about D (learned from C).
        bellman_ford_relax("A", routes, "B", 1, {"C": 1, "D": 2})

        self.assertEqual(routes["B"].cost, 1)
        self.assertEqual(routes["C"].cost, 2)
        self.assertEqual(routes["D"].cost, 3)
        self.assertEqual(routes["D"].next_hop, "B")


class RouteExpiryTests(unittest.TestCase):
    def test_expire_old_routes(self):
        old_time = time.time() - 100
        routes = {
            "B": DVRoute("B", "B", 1, last_updated=old_time),
            "C": DVRoute("C", "B", 2, last_updated=time.time()),
        }
        expired = expire_routes(routes, max_age_seconds=30)
        self.assertEqual(expired, ["B"])
        self.assertNotIn("B", routes)
        self.assertIn("C", routes)

    def test_no_expiry_when_fresh(self):
        routes = {
            "B": DVRoute("B", "B", 1, last_updated=time.time()),
        }
        expired = expire_routes(routes, max_age_seconds=30)
        self.assertEqual(expired, [])
        self.assertIn("B", routes)


class VectorAndFormatTests(unittest.TestCase):
    def test_routes_to_vector(self):
        routes = {
            "B": DVRoute("B", "B", 1),
            "C": DVRoute("C", "B", 2),
        }
        vector = routes_to_vector(routes)
        self.assertEqual(vector, {"B": 1, "C": 2})

    def test_format_empty(self):
        self.assertEqual(format_dv_table({}), "(no routes)")

    def test_format_nonempty(self):
        routes = {"B": DVRoute("B", "B", 1)}
        text = format_dv_table(routes)
        self.assertIn("B", text)
        self.assertIn("Destination", text)


if __name__ == "__main__":
    unittest.main()
