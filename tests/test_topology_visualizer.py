import unittest

from core.node import MeshNode
from routing.topology import NetworkTopology
from visualization.topology_visualizer import TopologyVisualizer


class TopologyVisualizerTests(unittest.TestCase):
    def test_snapshot_contains_nodes_links_and_routes(self):
        node = MeshNode(node_id="A", ip="127.0.0.1", port=5002)
        node.add_neighbor("B", "127.0.0.1", 5003)
        node.update_route("B", "B", cost=1)
        topology = NetworkTopology(self_node_id="A")
        topology.add_link("A", "B")
        topology.add_link("B", "C")

        visualizer = TopologyVisualizer(node, topology=topology)
        snapshot = visualizer.to_json_dict()

        self.assertEqual(snapshot["node_id"], "A")
        self.assertEqual(len(snapshot["nodes"]), 3)
        nodes_by_id = {node["id"]: node for node in snapshot["nodes"]}
        self.assertEqual(nodes_by_id["A"]["ip"], "127.0.0.1")
        self.assertEqual(nodes_by_id["A"]["port"], 5002)
        self.assertEqual(nodes_by_id["B"]["ip"], "127.0.0.1")
        self.assertEqual(nodes_by_id["B"]["port"], 5003)
        self.assertEqual(nodes_by_id["C"]["ip"], "")
        self.assertEqual(nodes_by_id["C"]["port"], 0)
        self.assertEqual(len(snapshot["links"]), 2)
        self.assertIn("B", snapshot["routes"])
        self.assertIn("A --1-- B", visualizer.to_ascii())
        self.assertIn("<svg", visualizer.to_svg())


if __name__ == "__main__":
    unittest.main()
