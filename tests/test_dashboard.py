import json
import unittest
from urllib.request import Request, urlopen

from dashboard.app import DashboardServer
from core.node import MeshNode
from routing.routing_manager import RoutingManager, RoutingStrategy


class DashboardServerTests(unittest.TestCase):
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
