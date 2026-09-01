import time
import unittest

from core.constants import NodeStatus, PacketType
from core.node import MeshNode
from core.packet import create_packet
from discovery.discovery_service import DiscoveryService
from discovery.heartbeat_service import HeartbeatService
from discovery.neighbor_manager import NeighborManager


def wait_until(predicate, timeout=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class NeighborManagerTests(unittest.TestCase):
    def test_update_and_mark_stale_neighbor(self):
        manager = NeighborManager(self_node_id="DEVICE_A")

        neighbor = manager.update_neighbor("DEVICE_B", "127.0.0.1", 5002, now=100.0)

        self.assertIsNotNone(neighbor)
        self.assertEqual(manager.active_neighbors()[0].node_id, "DEVICE_B")

        stale = manager.mark_stale(timeout_seconds=5.0, now=106.0)

        self.assertEqual([neighbor.node_id for neighbor in stale], ["DEVICE_B"])
        self.assertEqual(manager.get_neighbor("DEVICE_B").status, NodeStatus.DISCONNECTED.value)
        self.assertEqual(manager.active_neighbors(), [])

    def test_remove_stale_neighbor(self):
        manager = NeighborManager(self_node_id="DEVICE_A")
        manager.update_neighbor("DEVICE_B", "127.0.0.1", 5002, now=100.0)

        removed = manager.remove_stale(timeout_seconds=5.0, now=106.0)

        self.assertEqual([neighbor.node_id for neighbor in removed], ["DEVICE_B"])
        self.assertIsNone(manager.get_neighbor("DEVICE_B"))


class DiscoveryServiceTests(unittest.TestCase):
    def test_nodes_discover_each_other_over_loopback_targets(self):
        node_a = MeshNode(node_id="DEVICE_A", ip="127.0.0.1", port=0)
        node_b = MeshNode(node_id="DEVICE_B", ip="127.0.0.1", port=0)
        node_a.start_networking()
        node_b.start_networking()

        manager_a = NeighborManager(node_a.neighbors, self_node_id=node_a.node_id)
        manager_b = NeighborManager(node_b.neighbors, self_node_id=node_b.node_id)
        service_a = DiscoveryService(
            node_a,
            udp_socket=node_a.udp_socket,
            neighbor_manager=manager_a,
            broadcast_address=None,
            targets=[node_b.udp_socket.local_address],
            interval=0.05,
        )
        service_b = DiscoveryService(
            node_b,
            udp_socket=node_b.udp_socket,
            neighbor_manager=manager_b,
            broadcast_address=None,
            targets=[node_a.udp_socket.local_address],
            interval=0.05,
        )

        try:
            service_a.start()
            service_b.start()
            service_a.send_discovery()

            discovered = wait_until(
                lambda: manager_a.get_neighbor("DEVICE_B") is not None
                and manager_b.get_neighbor("DEVICE_A") is not None
            )

            self.assertTrue(discovered)
            self.assertEqual(manager_a.get_neighbor("DEVICE_B").port, node_b.port)
            self.assertEqual(manager_b.get_neighbor("DEVICE_A").port, node_a.port)
        finally:
            service_a.stop()
            service_b.stop()
            node_a.stop_networking()
            node_b.stop_networking()


class HeartbeatServiceTests(unittest.TestCase):
    def test_heartbeat_packet_refreshes_neighbor(self):
        node_b = MeshNode(node_id="DEVICE_B", ip="127.0.0.1", port=5002)
        manager = NeighborManager(node_b.neighbors, self_node_id=node_b.node_id)
        heartbeat = HeartbeatService(node_b, neighbor_manager=manager)
        packet = create_packet(
            PacketType.HEARTBEAT,
            source="DEVICE_A",
            payload={"node_id": "DEVICE_A", "ip": "127.0.0.1", "port": 5001},
        )

        heartbeat.handle_packet(packet, ("127.0.0.1", 5001))

        neighbor = manager.get_neighbor("DEVICE_A")
        self.assertIsNotNone(neighbor)
        self.assertEqual(neighbor.status, NodeStatus.ACTIVE.value)

    def test_check_failures_marks_stale_neighbors_disconnected(self):
        node_a = MeshNode(node_id="DEVICE_A", ip="127.0.0.1", port=5001)
        manager = NeighborManager(node_a.neighbors, self_node_id=node_a.node_id)
        manager.update_neighbor("DEVICE_B", "127.0.0.1", 5002, now=time.time() - 20)
        heartbeat = HeartbeatService(node_a, neighbor_manager=manager, neighbor_timeout=1.0)

        lost = heartbeat.check_failures()

        self.assertEqual([neighbor.node_id for neighbor in lost], ["DEVICE_B"])
        self.assertEqual(manager.get_neighbor("DEVICE_B").status, NodeStatus.DISCONNECTED.value)


if __name__ == "__main__":
    unittest.main()

