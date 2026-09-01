import json
import unittest
from urllib.request import urlopen

from dashboard.app import DashboardServer
from core.node import MeshNode


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

            with urlopen(f"{server.url}/static/css/styles.css", timeout=2) as response:
                css = response.read().decode("utf-8")

            self.assertIn(".topbar", css)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()

