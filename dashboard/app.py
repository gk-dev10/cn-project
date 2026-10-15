"""Module 25 - Web dashboard.

Dependency-free dashboard server using Python's built-in HTTP server.
It exposes live JSON endpoints, rich state, interactive control actions,
and serves a modern showcase UI.
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

from application.file_transfer import FileTransferSender
from application.location_service import LocationService
from application.messaging import MessagingService
from application.status_broadcast import StatusBroadcastService
from core.constants import (
    DEFAULT_DASHBOARD_HOST,
    DEFAULT_DASHBOARD_PORT,
    DEFAULT_GBN_WINDOW_SIZE,
    DEFAULT_TTL,
    PacketType,
)
from core.node import MeshNode
from core.packet import create_packet
from discovery.neighbor_manager import NeighborManager
from routing.routing_manager import RoutingManager, RoutingStrategy
from routing.topology import NetworkTopology
from transport.adaptive_window import AdaptiveWindowController
from transport.checksum_tracker import ChecksumTracker
from transport.reliable_transport import ReliableTransport
from transport.sliding_window import SlidingWindowSender
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
        messaging_service: Optional[MessagingService] = None,
        reliable_transport: Optional[ReliableTransport] = None,
        routing_manager: Optional[RoutingManager] = None,
        self_healer: Optional[object] = None,
        peers: Optional[list[tuple[str, int]]] = None,
    ) -> None:
        self.node = node
        self.host = host
        self.port = port
        self.neighbor_manager = neighbor_manager or NeighborManager(node.neighbors, self_node_id=node.node_id)
        self.topology = topology
        self.status_service = status_service
        self.location_service = location_service
        self.metrics_provider = metrics_provider
        self.messaging_service = messaging_service
        self.reliable_transport = reliable_transport
        self.routing_manager = routing_manager
        self.self_healer = self_healer
        self.peers = list(peers or [])

        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        self._events: list[dict] = []
        self._messages: list[dict] = []
        self._transfers: list[dict] = []
        self._simulation = {
            "loss_rate": 0.0,
            "delay": 0.0,
            "jitter": 0.0,
            "failed_nodes": [],
        }

        self.record_event("system", f"Dashboard initialized for node {node.node_id} on port {port}")

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

    def record_event(
        self,
        category: str,
        summary: str,
        details: Optional[dict] = None,
        level: str = "info",
    ) -> None:
        with self._lock:
            event = {
                "id": f"evt-{int(time.time() * 1000)}-{len(self._events) + 1}",
                "category": category,
                "summary": summary,
                "details": details or {},
                "level": level,
                "timestamp": time.time(),
            }
            self._events.append(event)
            if len(self._events) > 100:
                self._events.pop(0)

    def record_message(
        self,
        source: str,
        destination: Optional[str],
        text: str,
        reliable: bool = False,
        acknowledged: bool = False,
        sequence: int = 0,
        is_outgoing: bool = False,
    ) -> None:
        with self._lock:
            msg = {
                "id": f"msg-{int(time.time() * 1000)}-{len(self._messages) + 1}",
                "source": source,
                "destination": destination,
                "text": text,
                "reliable": reliable,
                "acknowledged": acknowledged,
                "sequence": sequence,
                "is_outgoing": is_outgoing,
                "timestamp": time.time(),
            }
            self._messages.append(msg)
            if len(self._messages) > 100:
                self._messages.pop(0)

    def resolve_destination_address(
        self,
        destination: str,
        override_address: Optional[tuple[str, int]] = None,
    ) -> Optional[tuple[str, int]]:
        if override_address:
            return override_address

        # Check direct neighbor.
        neighbor = self.neighbor_manager.get_neighbor(destination)
        if neighbor and neighbor.is_active:
            return (neighbor.ip, neighbor.port)

        # Check next hop in routing table.
        next_hop = self.node.get_next_hop(destination)
        if next_hop:
            hop_neighbor = self.neighbor_manager.get_neighbor(next_hop)
            if hop_neighbor and hop_neighbor.is_active:
                return (hop_neighbor.ip, hop_neighbor.port)

        # Fallback to configured peer list.
        if self.peers:
            return self.peers[0]

        return None

    def send_message_from_dashboard(
        self,
        destination: str,
        text: str,
        reliable: bool = True,
        address: Optional[tuple[str, int]] = None,
    ) -> dict:
        target_addr = self.resolve_destination_address(destination, address)
        if not target_addr:
            return {
                "sent": False,
                "reason": f"No active route or neighbor address found for destination '{destination}'",
            }

        if reliable and self.reliable_transport:
            try:
                delivery = self.reliable_transport.send_reliable(
                    packet_type=PacketType.MESSAGE,
                    destination=destination,
                    address=target_addr,
                    payload=text,
                    wait_for_ack=True,
                )
                self.record_message(
                    source=self.node.node_id,
                    destination=destination,
                    text=text,
                    reliable=True,
                    acknowledged=delivery.acknowledged,
                    sequence=delivery.sequence_number,
                    is_outgoing=True,
                )
                self.record_event(
                    "transport",
                    f"Reliable send to {destination} ({'ACKed' if delivery.acknowledged else 'Unacked'})",
                    {
                        "destination": destination,
                        "address": f"{target_addr[0]}:{target_addr[1]}",
                        "retries": delivery.retries,
                        "acknowledged": delivery.acknowledged,
                    },
                    level="info" if delivery.acknowledged else "warning",
                )
                return {
                    "sent": True,
                    "reliable": True,
                    "acknowledged": delivery.acknowledged,
                    "retries": delivery.retries,
                    "sequence_number": delivery.sequence_number,
                    "target_address": f"{target_addr[0]}:{target_addr[1]}",
                }
            except Exception as exc:
                self.record_event("error", f"Reliable send failed: {exc}", level="error")
                return {"sent": False, "reason": str(exc)}

        if self.messaging_service:
            try:
                res = self.messaging_service.send_message(
                    destination=destination,
                    text=text,
                    address=target_addr,
                    reliable=reliable,
                )
                self.record_message(
                    source=self.node.node_id,
                    destination=destination,
                    text=text,
                    reliable=reliable,
                    acknowledged=res.acknowledged,
                    sequence=res.sequence_number,
                    is_outgoing=True,
                )
                self.record_event(
                    "messaging",
                    f"Message sent to {destination} via {res.next_hop}",
                    {"address": f"{target_addr[0]}:{target_addr[1]}", "reliable": reliable},
                )
                return {
                    "sent": True,
                    "reliable": reliable,
                    "acknowledged": res.acknowledged,
                    "sequence_number": res.sequence_number,
                    "next_hop": res.next_hop,
                    "target_address": f"{target_addr[0]}:{target_addr[1]}",
                }
            except Exception as exc:
                return {"sent": False, "reason": str(exc)}

        # Direct socket fallback.
        try:
            with self._lock:
                seq = getattr(self, "_msg_seq", 1)
                self._msg_seq = seq + 1
            packet = create_packet(
                packet_type=PacketType.MESSAGE,
                source=self.node.node_id,
                destination=destination,
                sequence_number=seq,
                ttl=DEFAULT_TTL,
                payload=text,
            )
            self.node.udp_socket.send_packet(packet, target_addr)
            self.record_message(
                source=self.node.node_id,
                destination=destination,
                text=text,
                reliable=False,
                sequence=seq,
                is_outgoing=True,
            )
            self.record_event("socket", f"Raw UDP message sent to {destination}", {"target": target_addr})
            return {"sent": True, "reliable": False, "target_address": f"{target_addr[0]}:{target_addr[1]}"}
        except Exception as exc:
            return {"sent": False, "reason": str(exc)}

    def start_gbn_transfer(
        self,
        destination: str,
        message: str,
        chunks: int = 5,
        window_size: int = DEFAULT_GBN_WINDOW_SIZE,
        adaptive: bool = False,
        address: Optional[tuple[str, int]] = None,
    ) -> dict:
        target_addr = self.resolve_destination_address(destination, address)
        if not target_addr:
            return {"started": False, "reason": f"No route/address for destination '{destination}'"}

        transfer_id = f"tx-{int(time.time() * 1000)}"
        tx_info = {
            "id": transfer_id,
            "destination": destination,
            "target_address": f"{target_addr[0]}:{target_addr[1]}",
            "message_sample": message[:40] + ("..." if len(message) > 40 else ""),
            "chunks_total": chunks,
            "chunks_sent": 0,
            "chunks_acked": 0,
            "retransmissions": 0,
            "window_size": window_size,
            "adaptive": adaptive,
            "status": "running",
            "srtt": 0.0,
            "rto": 0.0,
            "started_at": time.time(),
            "completed_at": None,
        }

        with self._lock:
            self._transfers.insert(0, tx_info)
            if len(self._transfers) > 20:
                self._transfers.pop()

        def _run() -> None:
            tracker = ChecksumTracker()
            sender = SlidingWindowSender(
                self.node,
                self.node.udp_socket,
                window_size=window_size,
                ack_timeout=0.6,
                check_interval=0.02,
            )
            controller = None
            try:
                sender.start()
                if adaptive:
                    controller = AdaptiveWindowController(sender, tracker)
                    controller.start()

                chunk_size = max(1, len(message) // chunks)
                payloads = [message[i : i + chunk_size] for i in range(0, len(message), chunk_size)]
                if not payloads:
                    payloads = [message]
                tx_info["chunks_total"] = len(payloads)

                self.record_event(
                    "gbn",
                    f"Started GBN transfer {transfer_id} to {destination} ({len(payloads)} chunks, adaptive={adaptive})",
                )

                sender.send_all(
                    destination=destination,
                    address=target_addr,
                    payloads=payloads,
                    packet_type=PacketType.MESSAGE,
                )

                # Monitor loop.
                deadline = time.time() + 25.0
                while time.time() < deadline:
                    stats = sender.stats()
                    tx_info["chunks_sent"] = stats.packets_sent
                    tx_info["chunks_acked"] = stats.packets_acked
                    tx_info["retransmissions"] = stats.retransmissions
                    tx_info["window_size"] = sender.window_size
                    if controller:
                        c_stats = controller.stats()
                        tx_info["srtt"] = round(c_stats.srtt, 4)
                        tx_info["rto"] = round(c_stats.rto, 4)

                    if stats.packets_acked >= len(payloads):
                        tx_info["status"] = "completed"
                        break
                    time.sleep(0.05)
                else:
                    tx_info["status"] = "timeout"

                tx_info["completed_at"] = time.time()
                self.record_event(
                    "gbn",
                    f"GBN transfer {transfer_id} {tx_info['status']}. Sent: {tx_info['chunks_sent']}, ACKed: {tx_info['chunks_acked']}",
                    level="info" if tx_info["status"] == "completed" else "warning",
                )
            except Exception as exc:
                tx_info["status"] = "failed"
                tx_info["error"] = str(exc)
                self.record_event("error", f"GBN transfer {transfer_id} error: {exc}", level="error")
            finally:
                if controller:
                    controller.stop()
                sender.stop()

        t = threading.Thread(target=_run, name=f"meshlink-tx-{transfer_id}", daemon=True)
        t.start()

        return {"started": True, "transfer_id": transfer_id}

    def send_file_from_dashboard(
        self,
        destination: str,
        file_path: str = "README.md",
        address: Optional[tuple[str, int]] = None,
    ) -> dict:
        target_addr = self.resolve_destination_address(destination, address)
        if not target_addr:
            return {"started": False, "reason": f"No route/address for destination '{destination}'"}

        path = Path(file_path)
        if not path.exists():
            return {"started": False, "reason": f"File '{file_path}' does not exist"}

        transfer_id = f"file-{int(time.time() * 1000)}"
        file_info = {
            "id": transfer_id,
            "destination": destination,
            "target_address": f"{target_addr[0]}:{target_addr[1]}",
            "message_sample": f"File: {path.name} ({path.stat().st_size} bytes)",
            "chunks_total": max(1, path.stat().st_size // 1024),
            "chunks_sent": 0,
            "chunks_acked": 0,
            "retransmissions": 0,
            "window_size": 4,
            "adaptive": False,
            "status": "running",
            "srtt": 0.0,
            "rto": 0.0,
            "started_at": time.time(),
            "completed_at": None,
        }
        with self._lock:
            self._transfers.insert(0, file_info)
            if len(self._transfers) > 20:
                self._transfers.pop()

        def _run() -> None:
            sender = FileTransferSender(self.node, self.node.udp_socket, window_size=4)
            try:
                self.record_event("file", f"Started file transfer '{path.name}' to {destination}")
                result = sender.send_file(destination=destination, address=target_addr, file_path=path)
                file_info["status"] = "completed" if result.success else "failed"
                file_info["chunks_sent"] = result.stats.packets_sent
                file_info["chunks_acked"] = result.stats.packets_acked
                file_info["completed_at"] = time.time()
                self.record_event(
                    "file",
                    f"File '{path.name}' delivered to {destination} (SHA256: {result.sha256[:10]}...)",
                    level="info" if result.success else "warning",
                )
            except Exception as exc:
                file_info["status"] = "failed"
                self.record_event("error", f"File transfer error: {exc}", level="error")

        t = threading.Thread(target=_run, name=f"meshlink-file-{transfer_id}", daemon=True)
        t.start()
        return {"started": True, "transfer_id": transfer_id, "file_name": path.name}

    def switch_routing_strategy_from_dashboard(self, strategy_name: str) -> dict:
        if not self.routing_manager:
            return {"success": False, "reason": "Routing manager is not initialized on this node"}

        try:
            strat_clean = strategy_name.strip().upper()
            if strat_clean in ("LINK_STATE", "LS", "DIJKSTRA"):
                target_strat = RoutingStrategy.LINK_STATE
            elif strat_clean in ("DISTANCE_VECTOR", "DV", "BELLMAN_FORD"):
                target_strat = RoutingStrategy.DISTANCE_VECTOR
            else:
                return {"success": False, "reason": f"Unknown routing strategy '{strategy_name}'"}

            self.routing_manager.switch_strategy(target_strat)
            self.record_event("routing", f"Switched routing algorithm to {target_strat.value}")
            return {
                "success": True,
                "strategy": target_strat.value,
                "routes": {dst: dict(r) for dst, r in self.node.routing_table.items()},
            }
        except Exception as exc:
            return {"success": False, "reason": str(exc)}

    def configure_simulation_from_dashboard(
        self,
        loss_rate: Optional[float] = None,
        delay: Optional[float] = None,
        jitter: Optional[float] = None,
    ) -> dict:
        with self._lock:
            if loss_rate is not None:
                self._simulation["loss_rate"] = max(0.0, min(1.0, float(loss_rate)))
            if delay is not None:
                self._simulation["delay"] = max(0.0, float(delay))
            if jitter is not None:
                self._simulation["jitter"] = max(0.0, float(jitter))

        self.record_event(
            "simulator",
            f"Configured channel impairments: loss={self._simulation['loss_rate'] * 100:.1f}%, delay={self._simulation['delay']}s",
        )
        return {"success": True, "simulation": dict(self._simulation)}

    def simulate_node_failure_from_dashboard(self, node_id: str) -> dict:
        with self._lock:
            if node_id not in self._simulation["failed_nodes"]:
                self._simulation["failed_nodes"].append(node_id)

        # Trigger self-healer if active.
        neighbor = self.neighbor_manager.get_neighbor(node_id)
        if neighbor and self.self_healer and hasattr(self.self_healer, "handle_neighbor_lost"):
            self.self_healer.handle_neighbor_lost(neighbor)

        # Remove neighbor directly as offline.
        self.neighbor_manager.remove_neighbor(node_id)

        # Update topology.
        if self.topology:
            self.topology.remove_node(node_id)

        self.record_event(
            "resilience",
            f"Simulated link/node failure for {node_id}; triggered self-healing route pruning",
            level="warning",
        )
        return {"success": True, "failed_node": node_id}

    def broadcast_status_from_dashboard(
        self,
        status: str,
        message: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        location_label: Optional[str] = None,
    ) -> dict:
        if self.status_service is None:
            return {"sent": False, "reason": "status service is not configured"}

        if self.location_service and (latitude is not None or longitude is not None or location_label):
            self.location_service.update_coordinates(
                latitude=latitude if latitude is not None else self.location_service.latitude,
                longitude=longitude if longitude is not None else self.location_service.longitude,
                label=location_label or self.location_service.label,
            )

        location = self.location_service.current_payload() if self.location_service else None
        broadcast_id = self.status_service.broadcast_status(status=status, message=message, location=location)

        self.record_event(
            "status",
            f"Broadcasted status [{status}]: {message or 'No message'}",
            {"broadcast_id": broadcast_id, "location": location},
            level="warning" if status != "SAFE" else "info",
        )
        return {"sent": True, "broadcast_id": broadcast_id}

    def state(self) -> dict:
        visualizer = TopologyVisualizer(self.node, topology=self.topology)
        metrics = self.metrics_provider() if self.metrics_provider else {}
        location = self.location_service.current_payload() if self.location_service else None

        active_strategy = "LINK_STATE"
        if self.routing_manager and hasattr(self.routing_manager, "strategy"):
            active_strategy = str(self.routing_manager.strategy.value)

        with self._lock:
            events_copy = list(self._events)
            messages_copy = list(self._messages)
            transfers_copy = list(self._transfers)
            sim_copy = dict(self._simulation)

        return {
            "node": self.node.as_dict(),
            "neighbors": self.neighbor_manager.as_table(),
            "routes": {destination: dict(route) for destination, route in self.node.routing_table.items()},
            "topology": visualizer.to_json_dict(),
            "metrics": metrics,
            "location": location,
            "routing_strategy": active_strategy,
            "events": events_copy[-30:],
            "messages": messages_copy[-30:],
            "transfers": transfers_copy[:5],
            "simulation": sim_copy,
            "peers": [f"{h}:{p}" for h, p in self.peers],
            "statuses": [
                {
                    "source": s.source,
                    "status": s.status,
                    "message": s.message,
                    "timestamp": s.timestamp,
                    "location": getattr(s, "location", None),
                }
                for s in (self.status_service.received_statuses if self.status_service else [])
            ],
            "generated_at": time.time(),
        }


class _DashboardHandler(BaseHTTPRequestHandler):
    server_version = "MeshLinkDashboard/2.0"

    def __init__(self, *args, dashboard: DashboardServer, **kwargs) -> None:
        self.dashboard = dashboard
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            dist_index = _asset_path("dist/index.html")
            if dist_index.exists():
                self._send_file(dist_index, "text/html; charset=utf-8")
                return
            self._send_file(_asset_path("templates/index.html"), "text/html; charset=utf-8")
            return
        if path == "/api/state":
            self._send_json(self.dashboard.state())
            return
        if path == "/api/topology":
            self._send_json(self.dashboard.state()["topology"])
            return
        if path == "/api/events":
            self._send_json({"events": self.dashboard.state()["events"]})
            return
        if path.startswith("/assets/"):
            relative = path.removeprefix("/assets/")
            asset = _asset_path(f"dist/assets/{relative}")
            if not _is_within_assets(asset):
                self._send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = _content_type(asset)
            self._send_file(asset, content_type)
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
        body = self._read_json_body()

        if path == "/api/status":
            status = str(body.get("status", "SAFE"))
            message = body.get("message")
            lat = body.get("latitude")
            lon = body.get("longitude")
            lbl = body.get("location_label")
            res = self.dashboard.broadcast_status_from_dashboard(
                status=status,
                message=message,
                latitude=float(lat) if lat is not None else None,
                longitude=float(lon) if lon is not None else None,
                location_label=lbl,
            )
            self._send_json(res, status=HTTPStatus.OK if res.get("sent") else HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/message":
            destination = str(body.get("destination", "")).strip()
            text = str(body.get("message", "")).strip()
            reliable = bool(body.get("reliable", True))
            address_str = body.get("address")
            addr_tuple = _parse_address(address_str) if address_str else None

            if not destination or not text:
                self._send_json({"sent": False, "reason": "Both destination and message are required"}, HTTPStatus.BAD_REQUEST)
                return

            res = self.dashboard.send_message_from_dashboard(
                destination=destination,
                text=text,
                reliable=reliable,
                address=addr_tuple,
            )
            self._send_json(res, status=HTTPStatus.OK if res.get("sent") else HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/transfer":
            destination = str(body.get("destination", "")).strip()
            message = str(body.get("message", "MeshLink automated test payload for GBN chunking")).strip()
            chunks = int(body.get("chunks", 5))
            window_size = int(body.get("window_size", DEFAULT_GBN_WINDOW_SIZE))
            adaptive = bool(body.get("adaptive", False))
            address_str = body.get("address")
            addr_tuple = _parse_address(address_str) if address_str else None

            if not destination:
                self._send_json({"started": False, "reason": "Destination is required"}, HTTPStatus.BAD_REQUEST)
                return

            res = self.dashboard.start_gbn_transfer(
                destination=destination,
                message=message,
                chunks=chunks,
                window_size=window_size,
                adaptive=adaptive,
                address=addr_tuple,
            )
            self._send_json(res, status=HTTPStatus.OK if res.get("started") else HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/file/send":
            destination = str(body.get("destination", "")).strip()
            file_path = str(body.get("file_path", "README.md")).strip()
            address_str = body.get("address")
            addr_tuple = _parse_address(address_str) if address_str else None
            res = self.dashboard.send_file_from_dashboard(destination, file_path=file_path, address=addr_tuple)
            self._send_json(res, status=HTTPStatus.OK if res.get("started") else HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/routing/switch":
            strategy = str(body.get("strategy", "LINK_STATE"))
            res = self.dashboard.switch_routing_strategy_from_dashboard(strategy)
            self._send_json(res, status=HTTPStatus.OK if res.get("success") else HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/simulate":
            loss = body.get("loss_rate")
            delay = body.get("delay")
            jitter = body.get("jitter")
            res = self.dashboard.configure_simulation_from_dashboard(loss_rate=loss, delay=delay, jitter=jitter)
            self._send_json(res, HTTPStatus.OK)
            return

        if path == "/api/chaos/node-fail":
            node_id = str(body.get("node_id", "")).strip()
            if not node_id:
                self._send_json({"success": False, "reason": "node_id is required"}, HTTPStatus.BAD_REQUEST)
                return
            res = self.dashboard.simulate_node_failure_from_dashboard(node_id)
            self._send_json(res, HTTPStatus.OK)
            return

        self._send_error(HTTPStatus.NOT_FOUND)

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


def _parse_address(addr_str: Optional[str]) -> Optional[tuple[str, int]]:
    if not addr_str or ":" not in addr_str:
        return None
    parts = addr_str.strip().split(":", 1)
    try:
        return (parts[0], int(parts[1]))
    except ValueError:
        return None


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
    if suffix == ".json":
        return "application/json; charset=utf-8"
    return "application/octet-stream"
