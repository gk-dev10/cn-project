"""Module 25 - Web dashboard.

Dependency-free dashboard server using Python's built-in HTTP server.
It exposes live JSON endpoints and serves a static dashboard UI.
"""

from __future__ import annotations

from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from typing import Callable, Optional
from urllib.parse import urlparse

from application.location_service import LocationService
from application.status_broadcast import StatusBroadcastService
from core.constants import DEFAULT_DASHBOARD_HOST, DEFAULT_DASHBOARD_PORT
from core.node import MeshNode
from discovery.neighbor_manager import NeighborManager
from routing.topology import NetworkTopology
from visualization.topology_visualizer import TopologyVisualizer


MetricsProvider = Callable[[], dict]


class DashboardServer:
    def __init__(
        self,
        node: MeshNode,
        host: str = DEFAULT_DASHBOARD_HOST,
        port: int = DEFAULT_DASHBOARD_PORT,
        neighbor_manager: Optional[NeighborManager] = None,
        topology: Optional[NetworkTopology] = None,
        status_service: Optional[StatusBroadcastService] = None,
        location_service: Optional[LocationService] = None,
        metrics_provider: Optional[MetricsProvider] = None,
    ) -> None:
        self.node = node
        self.host = host
        self.port = port
        self.neighbor_manager = neighbor_manager or NeighborManager(node.neighbors, self_node_id=node.node_id)
        self.topology = topology
        self.status_service = status_service
        self.location_service = location_service
        self.metrics_provider = metrics_provider
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def start(self, block: bool = True) -> None:
        handler = partial(_DashboardHandler, dashboard=self)
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self.host, self.port = self._server.server_address

        if block:
            self._server.serve_forever()
            return

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"meshlink-dashboard-{self.port}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None

    def state(self) -> dict:
        visualizer = TopologyVisualizer(self.node, topology=self.topology)
        metrics = self.metrics_provider() if self.metrics_provider else {}
        location = self.location_service.current_payload() if self.location_service else None

        return {
            "node": self.node.as_dict(),
            "neighbors": self.neighbor_manager.as_table(),
            "routes": {destination: dict(route) for destination, route in self.node.routing_table.items()},
            "topology": visualizer.to_json_dict(),
            "metrics": metrics,
            "location": location,
            "statuses": [
                {
                    "source": status.source,
                    "status": status.status,
                    "message": status.message,
                    "timestamp": status.timestamp,
                }
                for status in self.status_service.received_statuses
            ]
            if self.status_service
            else [],
            "generated_at": time.time(),
        }

    def broadcast_status_from_dashboard(self, status: str, message: Optional[str] = None) -> dict:
        if self.status_service is None:
            return {"sent": False, "reason": "status service is not configured"}

        location = self.location_service.current_payload() if self.location_service else None
        broadcast_id = self.status_service.broadcast_status(status=status, message=message, location=location)
        return {"sent": True, "broadcast_id": broadcast_id}


class _DashboardHandler(BaseHTTPRequestHandler):
    server_version = "MeshLinkDashboard/1.0"

    def __init__(self, *args, dashboard: DashboardServer, **kwargs) -> None:
        self.dashboard = dashboard
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send_file(_asset_path("templates/index.html"), "text/html; charset=utf-8")
            return
        if path == "/api/state":
            self._send_json(self.dashboard.state())
            return
        if path == "/api/topology":
            self._send_json(self.dashboard.state()["topology"])
            return
        if path.startswith("/static/"):
            relative = path.removeprefix("/static/")
            asset = _asset_path(f"static/{relative}")
            if not _is_within_assets(asset):
                self._send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = _content_type(asset)
            self._send_file(asset, content_type)
            return

        self._send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/status":
            self._send_error(HTTPStatus.NOT_FOUND)
            return

        body = self._read_json_body()
        status = str(body.get("status", "SAFE"))
        message = body.get("message")
        response = self.dashboard.broadcast_status_from_dashboard(status=status, message=message)
        self._send_json(response, status=HTTPStatus.OK if response.get("sent") else HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args) -> None:
        return

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return body if isinstance(body, dict) else {}

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self._send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()


def _asset_path(relative: str) -> Path:
    return Path(__file__).resolve().parent / relative


def _is_within_assets(path: Path) -> bool:
    root = Path(__file__).resolve().parent
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".css":
        return "text/css; charset=utf-8"
    if suffix == ".js":
        return "application/javascript; charset=utf-8"
    if suffix == ".svg":
        return "image/svg+xml"
    return "application/octet-stream"

