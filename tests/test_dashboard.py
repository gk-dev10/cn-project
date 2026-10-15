import json
import threading
import time
import unittest
from urllib.request import Request, urlopen

from application.messaging import MessagingService
from application.location_service import LocationService
from application.status_broadcast import StatusBroadcastService
from core.constants import PacketType
from dashboard.app import DashboardServer
from core.node import MeshNode
from discovery.neighbor_manager import NeighborManager
from relay.packet_forwarder import PacketForwarder
from routing.routing_manager import RoutingManager, RoutingStrategy
from transport.reliable_transport import ReliableTransport


class DashboardServerTests(unittest.TestCase):
    def test_status_endpoint_broadcasts_with_manual_location(self):
        node = MeshNode(node_id="STATUS_A", ip="127.0.0.1", port=0)
        server = None
        status_service = None

        try:
            node.start_networking()
            status_service = StatusBroadcastService(node, udp_socket=node.udp_socket)
            status_service.start()
            location_service = LocationService()
            server = DashboardServer(
                node,
                host="127.0.0.1",
                port=0,
                status_service=status_service,
                location_service=location_service,
            )
            server.start(block=False)

            request = Request(
                f"{server.url}/api/status",
                data=json.dumps(
                    {
                        "status": "CRITICAL_SOS",
                        "message": "Demo SOS",
                        "latitude": 12.9716,
                        "longitude": 77.5946,
                        "location_label": "Shelter 4",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertTrue(payload["sent"])
            self.assertEqual(location_service.current_payload()["latitude"], 12.9716)
            self.assertEqual(location_service.current_payload()["longitude"], 77.5946)
            self.assertEqual(location_service.current_payload()["label"], "Shelter 4")
        finally:
            if server:
                server.stop()
            if status_service:
                status_service.stop()
            node.stop_networking()

    def test_message_endpoint_sends_to_active_neighbor(self):
        node_a = MeshNode(node_id="DASH_A", ip="127.0.0.1", port=0)
        node_b = MeshNode(node_id="DASH_B", ip="127.0.0.1", port=0)
        node_c = MeshNode(node_id="DASH_C", ip="127.0.0.1", port=0)
        received = threading.Event()
        server = None
        forwarder = None
        transports = []

        try:
            node_a.start_networking()
            node_b.start_networking()
            node_c.start_networking()
            node_a.add_neighbor(node_b.node_id, "127.0.0.1", node_b.port)
            node_b.add_neighbor(node_a.node_id, "127.0.0.1", node_a.port)
            node_b.add_neighbor(node_c.node_id, "127.0.0.1", node_c.port)
            node_c.add_neighbor(node_b.node_id, "127.0.0.1", node_b.port)
            node_a.update_route(node_b.node_id, node_b.node_id, cost=1)
            node_a.update_route(node_c.node_id, node_b.node_id, cost=2)
            node_b.update_route(node_a.node_id, node_a.node_id, cost=1)
            node_b.update_route(node_c.node_id, node_c.node_id, cost=1)
            node_c.update_route(node_b.node_id, node_b.node_id, cost=1)
            node_c.update_route(node_a.node_id, node_b.node_id, cost=2)

            message_services = [
                MessagingService(node_b, udp_socket=node_b.udp_socket),
                MessagingService(
                    node_c,
                    udp_socket=node_c.udp_socket,
                    on_message=lambda message: received.set(),
                ),
            ]
            message_services.insert(0, MessagingService(node_a, udp_socket=node_a.udp_socket))
            for node, messaging_service in zip(
                (node_a, node_b, node_c), message_services
            ):
                transport = ReliableTransport(
                    node,
                    udp_socket=node.udp_socket,
                    on_packet=messaging_service.handle_packet,
                    packet_types={PacketType.MESSAGE.value},
                )
                transport.start()
                transports.append(transport)

            forwarder = PacketForwarder(node_b, udp_socket=node_b.udp_socket)
            forwarder.start()
            server = DashboardServer(
                node_a,
                host="127.0.0.1",
                port=0,
                neighbor_manager=NeighborManager(node_a.neighbors, self_node_id=node_a.node_id),
                reliable_transport=transports[0],
            )
            server.start(block=False)

            request = Request(
                f"{server.url}/api/message",
                data=json.dumps(
                    {
                        "destination": "DASH_C",
                        "message": "Reliable dashboard relay test",
                        "reliable": True,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertTrue(payload["sent"])
            self.assertTrue(payload["acknowledged"])
            self.assertTrue(received.wait(1))
        finally:
            if server:
                server.stop()
            if forwarder:
                forwarder.stop()
            for transport in transports:
                transport.stop()
            node_a.stop_networking()
            node_b.stop_networking()
            node_c.stop_networking()

    def test_dashboard_serves_state_and_static_assets(self):
        node = MeshNode(node_id="DASH", ip="127.0.0.1", port=0)
        server = DashboardServer(node, host="127.0.0.1", port=0)

        try:
            server.start(block=False)
            with urlopen(f"{server.url}/api/state", timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(payload["node"]["node_id"], "DASH")
            self.assertIn("topology", payload)
            self.assertIn("events", payload)
            self.assertIn("simulation", payload)

            with urlopen(f"{server.url}/static/css/styles.css", timeout=2) as response:
                css = response.read().decode("utf-8")

            self.assertIn(".topbar", css)
        finally:
            server.stop()

    def test_adaptive_gbn_dashboard_transfer_completes_with_requested_chunks(self):
        node_a = MeshNode(node_id="GBN_A", ip="127.0.0.1", port=0)
        node_b = MeshNode(node_id="GBN_B", ip="127.0.0.1", port=0)
        server = None
        receiver = None

        try:
            node_a.start_networking()
            node_b.start_networking()
            node_a.add_neighbor(node_b.node_id, "127.0.0.1", node_b.port)
            receiver = ReliableTransport(node_b, udp_socket=node_b.udp_socket)
            receiver.start()
            server = DashboardServer(
                node_a,
                host="127.0.0.1",
                port=0,
                neighbor_manager=NeighborManager(node_a.neighbors, self_node_id=node_a.node_id),
            )
            server.start(block=False)

            request = Request(
                f"{server.url}/api/transfer",
                data=json.dumps(
                    {
                        "destination": "GBN_B",
                        "message": "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuv",
                        "chunks": 6,
                        "window_size": 4,
                        "adaptive": True,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["started"])

            deadline = time.time() + 4
            transfer = None
            while time.time() < deadline:
                transfer = server.state()["transfers"][0]
                if transfer["status"] != "running":
                    break
                time.sleep(0.02)

            self.assertEqual(transfer["status"], "completed", transfer)
            self.assertEqual(transfer["chunks_total"], 6)
            self.assertEqual(transfer["chunks_acked"], 6)
        finally:
            if server:
                server.stop()
            if receiver:
                receiver.stop()
            node_a.stop_networking()
            node_b.stop_networking()

    def test_dashboard_action_endpoints(self):
        node = MeshNode(node_id="DASH2", ip="127.0.0.1", port=0)
        routing_mgr = RoutingManager(node, strategy=RoutingStrategy.LINK_STATE)
        server = DashboardServer(node, host="127.0.0.1", port=0, routing_manager=routing_mgr)

        try:
            server.start(block=False)

            # Test simulate endpoint
            req = Request(
                f"{server.url}/api/simulate",
                data=json.dumps({"loss_rate": 0.15, "delay": 0.05}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=2) as response:
                data = json.loads(response.read().decode("utf-8"))
            self.assertTrue(data.get("success"))
            self.assertAlmostEqual(data["simulation"]["loss_rate"], 0.15)

            # Test routing strategy switch
            req = Request(
                f"{server.url}/api/routing/switch",
                data=json.dumps({"strategy": "DISTANCE_VECTOR"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=2) as response:
                data = json.loads(response.read().decode("utf-8"))
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("strategy"), "DISTANCE_VECTOR")

            # Test events endpoint
            with urlopen(f"{server.url}/api/events", timeout=2) as response:
                events_data = json.loads(response.read().decode("utf-8"))
            self.assertIn("events", events_data)
            self.assertTrue(len(events_data["events"]) >= 1)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
