import unittest

from core.constants import NodeStatus
from core.node import MeshNode
from discovery.neighbor_manager import NeighborManager
from resilience.self_healing import SelfHealingManager
from routing.topology import NetworkTopology


class SelfHealingManagerTests(unittest.TestCase):
    def test_failed_neighbor_purges_routes_and_topology(self):
        node = MeshNode(node_id="A", ip="127.0.0.1", port=5001)
        manager = NeighborManager(node.neighbors, self_node_id="A")
        manager.update_neighbor("B", "127.0.0.1", 5002)
        manager.update_neighbor("C", "127.0.0.1", 5003)
        node.update_route("B", "B", cost=1)
        node.update_route("C", "B", cost=2)

        topology = NetworkTopology(self_node_id="A")
        topology.add_link("A", "B")
        topology.add_link("B", "C")

        healer = SelfHealingManager(node, neighbor_manager=manager, topology=topology)

        event = healer.handle_neighbor_lost("B")

        self.assertEqual(node.neighbors["B"].status, NodeStatus.DISCONNECTED.value)
        self.assertEqual(set(event.removed_routes), {"B", "C"})
        self.assertNotIn("B", node.routing_table)
        self.assertNotIn("C", node.routing_table)
        self.assertFalse(topology.has_node("B"))
        self.assertEqual(healer.stats().failures_detected, 1)


if __name__ == "__main__":
    unittest.main()

