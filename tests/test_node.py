import unittest

from core.constants import NodeStatus
from core.node import MeshNode


class MeshNodeTests(unittest.TestCase):
    def test_node_defaults_and_dict_shape(self):
        node = MeshNode(ip="127.0.0.1", port=0)

        self.assertTrue(node.node_id.startswith("DEVICE_"))
        self.assertEqual(node.ip, "127.0.0.1")
        self.assertEqual(node.port, 0)
        self.assertEqual(node.status, NodeStatus.ACTIVE.value)
        self.assertEqual(node.neighbors, {})
        self.assertEqual(node.routing_table, {})

        data = node.as_dict()
        self.assertEqual(data["node_id"], node.node_id)
        self.assertEqual(data["status"], NodeStatus.ACTIVE.value)

    def test_neighbor_lifecycle_and_routes(self):
        node = MeshNode(node_id="DEVICE_A", ip="127.0.0.1", port=5000)

        neighbor = node.add_neighbor("DEVICE_B", "127.0.0.1", 5002)
        self.assertEqual(neighbor.node_id, "DEVICE_B")
        self.assertEqual(node.neighbors["DEVICE_B"].status, NodeStatus.ACTIVE.value)

        node.mark_neighbor_disconnected("DEVICE_B")
        self.assertEqual(node.neighbors["DEVICE_B"].status, NodeStatus.DISCONNECTED.value)

        node.update_route("DEVICE_C", "DEVICE_B", cost=2)
        self.assertEqual(node.get_next_hop("DEVICE_C"), "DEVICE_B")

        node.remove_neighbor("DEVICE_B")
        self.assertNotIn("DEVICE_B", node.neighbors)


if __name__ == "__main__":
    unittest.main()

