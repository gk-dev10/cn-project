from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from typing import Tuple

from application.file_transfer import FileTransferReceiver, FileTransferSender
from application.location_service import LocationService
from application.messaging import MessagingService
from application.status_broadcast import StatusBroadcastService
from dashboard.app import DashboardServer
from core.constants import (
    DEFAULT_DASHBOARD_HOST,
    DEFAULT_DASHBOARD_PORT,
    DEFAULT_DISCOVERY_INTERVAL_SECONDS,
    DEFAULT_FILE_CHUNK_SIZE,
    DEFAULT_GBN_ACK_TIMEOUT_SECONDS,
    DEFAULT_GBN_WINDOW_SIZE,
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    DEFAULT_NEIGHBOR_TIMEOUT_SECONDS,
    DEFAULT_PORT,
    DEFAULT_RECEIVED_FILES_DIR,
    DEFAULT_RELIABLE_ACK_TIMEOUT_SECONDS,
    DEFAULT_RELIABLE_MAX_RETRIES,
    DEFAULT_SELF_HEALING_INTERVAL_SECONDS,
    DEFAULT_SIMULATED_DELAY_SECONDS,
    DEFAULT_SIMULATED_JITTER_SECONDS,
    DEFAULT_SIMULATED_LOSS_RATE,
    DEFAULT_STATUS_VALUE,
    PacketType,
)
from core.node import MeshNode
from core.packet import create_packet
from discovery.discovery_service import DiscoveryService
from discovery.heartbeat_service import HeartbeatService
from discovery.neighbor_manager import NeighborManager
from relay.packet_forwarder import PacketForwarder
from resilience.self_healing import SelfHealingManager
from routing.routing_manager import RoutingManager, RoutingStrategy
from routing.topology import NetworkTopology
from simulator.network_simulator import NetworkSimulator
from transport.adaptive_window import AdaptiveWindowController
from transport.checksum_tracker import ChecksumTracker
from transport.reliable_transport import ReliableTransport
from transport.sliding_window import SlidingWindowReceiver, SlidingWindowSender
from visualization.topology_visualizer import TopologyVisualizer


def parse_endpoint(value: str) -> Tuple[str, int]:
    if ":" not in value:
        raise argparse.ArgumentTypeError("Endpoint must use host:port format")

    host, port_text = value.rsplit(":", 1)
    if not host:
        raise argparse.ArgumentTypeError("Endpoint host is required")

    try:
        port = int(port_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Endpoint port must be an integer") from exc

    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("Endpoint port must be between 0 and 65535")

    return host, port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a MeshLink node for Modules 1-25.")
    parser.add_argument("--node-id", help="Stable node ID, for example DEVICE_A")
    parser.add_argument("--host", default="0.0.0.0", help="Local bind host")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Local UDP port. Receiver default: {DEFAULT_PORT}; sender default: 0 for an OS-chosen free port",
    )
    parser.add_argument("--send-to", type=parse_endpoint, help="Destination endpoint in host:port format")
    parser.add_argument("--destination", default="UNKNOWN", help="Destination node ID for the packet")
    parser.add_argument("--message", help="Text message to send")
    parser.add_argument("--reliable", action="store_true", help="Wait for ACKs and retransmit sent messages")
    parser.add_argument("--ack-timeout", type=float, default=DEFAULT_RELIABLE_ACK_TIMEOUT_SECONDS)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_RELIABLE_MAX_RETRIES)
    parser.add_argument("--discover", action="store_true", help="Broadcast discovery and track nearby nodes")
    parser.add_argument(
        "--peer",
        action="append",
        type=parse_endpoint,
        default=[],
        help="Extra discovery/heartbeat target in host:port format. Repeat for multiple local peers.",
    )
    parser.add_argument("--discovery-interval", type=float, default=DEFAULT_DISCOVERY_INTERVAL_SECONDS)
    parser.add_argument("--heartbeat-interval", type=float, default=DEFAULT_HEARTBEAT_INTERVAL_SECONDS)
    parser.add_argument("--neighbor-timeout", type=float, default=DEFAULT_NEIGHBOR_TIMEOUT_SECONDS)
    # Module 8 — Go-Back-N sliding window.
    parser.add_argument("--gbn", action="store_true", help="Send using Go-Back-N sliding window protocol")
    parser.add_argument("--window-size", type=int, default=DEFAULT_GBN_WINDOW_SIZE, help="GBN window size")
    parser.add_argument("--gbn-timeout", type=float, default=DEFAULT_GBN_ACK_TIMEOUT_SECONDS, help="GBN ACK timeout")
    parser.add_argument("--chunks", type=int, default=5, help="Number of chunks to split the message into for GBN demo")
    # Module 9 — Adaptive window control.
    parser.add_argument("--adaptive", action="store_true", help="Enable adaptive window control (auto-tune window size)")
    # Modules 11/13/15 — Routing (unified via RoutingManager).
    parser.add_argument("--link-state", action="store_true", help="Enable Link-State routing with Dijkstra")
    parser.add_argument("--distance-vector", action="store_true", help="Enable Distance-Vector routing with Bellman-Ford")
    parser.add_argument("--routing-interval", type=float, default=5.0, help="Seconds between routing announcements")
    parser.add_argument("--lsa-interval", type=float, default=5.0, help="(deprecated, use --routing-interval)")
    # Module 16 — Multi-hop forwarding.
    parser.add_argument("--forward", action="store_true", help="Enable multi-hop packet forwarding (relay)")
    parser.add_argument("--send-file", help="Path to a file to send using Go-Back-N file transfer")
    parser.add_argument("--receive-files", action="store_true", help="Receive FILE_CHUNK packets and reassemble files")
    parser.add_argument("--output-dir", default=DEFAULT_RECEIVED_FILES_DIR, help="Directory for received files")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_FILE_CHUNK_SIZE, help="File chunk size in bytes")
    parser.add_argument("--im-safe", action="store_true", help="Broadcast an emergency SAFE status")
    parser.add_argument("--status", help="Broadcast a custom status value, for example SAFE or NEED_HELP")
    parser.add_argument("--status-listen", action="store_true", help="Listen for and relay STATUS broadcasts")
    parser.add_argument("--latitude", type=float, help="Manual or simulated latitude for location/status payloads")
    parser.add_argument("--longitude", type=float, help="Manual or simulated longitude for location/status payloads")
    parser.add_argument("--location-label", default="MANUAL", help="Label for the configured location")
    parser.add_argument("--sim-demo", action="store_true", help="Run a standalone network condition simulator demo")
    parser.add_argument("--sim-packets", type=int, default=10, help="Packets to send in simulator demo")
    parser.add_argument("--loss-rate", type=float, default=DEFAULT_SIMULATED_LOSS_RATE, help="Simulator packet loss rate")
    parser.add_argument("--delay", type=float, default=DEFAULT_SIMULATED_DELAY_SECONDS, help="Simulator base delay in seconds")
    parser.add_argument("--jitter", type=float, default=DEFAULT_SIMULATED_JITTER_SECONDS, help="Simulator jitter in seconds")
    parser.add_argument("--fail-node", action="append", default=[], help="Mark a node failed in simulator/self-healing demos")
    parser.add_argument("--self-heal", action="store_true", help="Enable stale-neighbor route cleanup and recovery hooks")
    parser.add_argument("--self-heal-interval", type=float, default=DEFAULT_SELF_HEALING_INTERVAL_SECONDS)
    parser.add_argument("--print-topology", action="store_true", help="Print topology, links, and routes periodically")
    parser.add_argument("--dashboard", action="store_true", help="Serve the web dashboard for this node")
    parser.add_argument("--dashboard-host", default=DEFAULT_DASHBOARD_HOST)
    parser.add_argument("--dashboard-port", type=int, default=DEFAULT_DASHBOARD_PORT)
    return parser


def print_packet(packet: dict, address: tuple[str, int]) -> None:
    print(f"Received {packet['type']} from {packet['source']} at {address[0]}:{address[1]}")
    print(f"Sequence: {packet['sequence_number']} TTL: {packet['ttl']}")
    print(f"Payload: {packet['payload']}")


def print_message(message) -> None:
    print(f"Message from {message.source}: {message.text}")


def print_received_file(received_file) -> None:
    print(
        f"Received file {received_file.file_name} "
        f"({received_file.file_size} bytes) -> {received_file.path}"
    )


def print_status(status_message) -> None:
    suffix = f" - {status_message.message}" if status_message.message else ""
    print(f"Status from {status_message.source}: {status_message.status}{suffix}")


def build_location_service(
    latitude: float | None = None,
    longitude: float | None = None,
    label: str = "MANUAL",
) -> LocationService:
    service = LocationService()
    if latitude is None and longitude is None:
        return service
    if latitude is None or longitude is None:
        raise ValueError("both --latitude and --longitude are required when setting location")
    service.set_location(latitude=latitude, longitude=longitude, label=label)
    return service


def print_recovery(event) -> None:
    removed = ", ".join(event.removed_routes) if event.removed_routes else "none"
    print(f"Self-healing: removed failed node {event.failed_node}; purged routes: {removed}")


def build_runtime_metrics(
    neighbor_manager: NeighborManager,
    routing_manager: RoutingManager | None = None,
    forwarder: PacketForwarder | None = None,
    file_receiver: FileTransferReceiver | None = None,
    self_healer: SelfHealingManager | None = None,
) -> dict:
    metrics = {
        "connected_nodes": len(neighbor_manager.active_neighbors()),
        "known_nodes": len(neighbor_manager.all_neighbors()),
    }

    if routing_manager:
        metrics["routes"] = len(routing_manager.current_routing_table())

    if forwarder:
        stats = forwarder.stats()
        metrics.update(
            {
                "packets_forwarded": stats.forwarded,
                "packets_delivered": stats.delivered_locally,
                "packets_dropped": stats.dropped_ttl + stats.dropped_no_route + stats.dropped_checksum,
            }
        )

    if file_receiver:
        metrics["files_received"] = len(file_receiver.completed_files)

    if self_healer:
        stats = self_healer.stats()
        metrics.update(
            {
                "failures_detected": stats.failures_detected,
                "routes_removed": stats.routes_removed,
                "route_recomputations": stats.recomputations,
            }
        )

    return metrics


def run_receiver(
    node: MeshNode,
    enable_discovery: bool = False,
    routing_strategy: RoutingStrategy | None = None,
    enable_forwarding: bool = False,
    enable_file_receiver: bool = False,
    output_dir: str = DEFAULT_RECEIVED_FILES_DIR,
    enable_status_listener: bool = False,
    location_service: LocationService | None = None,
    enable_self_healing: bool = False,
    self_heal_interval: float = DEFAULT_SELF_HEALING_INTERVAL_SECONDS,
    enable_topology_print: bool = False,
    enable_dashboard: bool = False,
    dashboard_host: str = DEFAULT_DASHBOARD_HOST,
    dashboard_port: int = DEFAULT_DASHBOARD_PORT,
    peers: list[tuple[str, int]] | None = None,
    discovery_interval: float = DEFAULT_DISCOVERY_INTERVAL_SECONDS,
    heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    neighbor_timeout: float = DEFAULT_NEIGHBOR_TIMEOUT_SECONDS,
    routing_interval: float = 5.0,
) -> int:
    stopped = threading.Event()

    def handle_signal(signum: int, frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    peers = peers or []
    neighbor_manager = NeighborManager(node.neighbors, self_node_id=node.node_id)
    location_service = location_service or LocationService()
    topology = (
        NetworkTopology(self_node_id=node.node_id)
        if routing_strategy == RoutingStrategy.LINK_STATE
        or enable_self_healing
        or enable_topology_print
        or enable_dashboard
        else None
    )
    announced_neighbors: set[str] = set()
    self_healer = None

    def handle_neighbor_discovered(neighbor) -> None:
        if neighbor.node_id in announced_neighbors:
            return
        announced_neighbors.add(neighbor.node_id)
        if topology:
            topology.add_link(node.node_id, neighbor.node_id, cost=1)
        print(f"Discovered neighbor: {neighbor.node_id} at {neighbor.ip}:{neighbor.port}")

    def handle_neighbor_lost(neighbor) -> None:
        if self_healer:
            self_healer.handle_neighbor_lost(neighbor)
        print(f"Neighbor offline: {neighbor.node_id}")

    node.start_networking()
    messaging_service = MessagingService(node, udp_socket=node.udp_socket, on_message=print_message)
    reliable_transport = ReliableTransport(
        node,
        udp_socket=node.udp_socket,
        on_packet=messaging_service.handle_packet,
        packet_types={PacketType.MESSAGE.value},
    )
    reliable_transport.start()

    discovery_service = None
    heartbeat_service = None
    routing_manager = None
    forwarder = None
    file_receiver = None
    gbn_receiver = None
    status_service = None
    dashboard = None

    def handle_local_packet(packet: dict, address: tuple[str, int]) -> None:
        packet_type = packet.get("type")
        if packet_type == PacketType.MESSAGE.value:
            messaging_service.handle_packet(packet, address)
        elif packet_type == PacketType.FILE_CHUNK.value and file_receiver:
            return
        elif packet_type == PacketType.STATUS.value and status_service:
            status_service.handle_packet(packet, address)
        else:
            print_packet(packet, address)

    if enable_discovery:
        if topology:
            topology.sync_from_neighbors(node.neighbors)
 
        discovery_service = DiscoveryService(
            node,
            udp_socket=node.udp_socket,
            neighbor_manager=neighbor_manager,
            interval=discovery_interval,
            targets=peers,
            on_neighbor_discovered=handle_neighbor_discovered,
        )
        heartbeat_service = HeartbeatService(
            node,
            udp_socket=node.udp_socket,
            neighbor_manager=neighbor_manager,
            interval=heartbeat_interval,
            neighbor_timeout=neighbor_timeout,
            targets=peers,
            on_neighbor_lost=handle_neighbor_lost,
        )
        discovery_service.start()
        heartbeat_service.start()

    if routing_strategy is not None:
        routing_manager = RoutingManager(
            node,
            strategy=routing_strategy,
            udp_socket=node.udp_socket,
            topology=topology,
            interval=routing_interval,
            on_route_change=lambda t: print(f"Routes updated: {len(t)} destinations"),
        )
        routing_manager.start()

    if enable_self_healing:
        self_healer = SelfHealingManager(
            node,
            neighbor_manager=neighbor_manager,
            topology=topology,
            routing_manager=routing_manager,
            neighbor_timeout=neighbor_timeout,
            check_interval=self_heal_interval,
            on_recovery=print_recovery,
        )
        self_healer.start()

    if enable_file_receiver:
        file_receiver = FileTransferReceiver(output_dir=output_dir, on_complete=print_received_file)
        gbn_receiver = SlidingWindowReceiver(
            node,
            node.udp_socket,
            on_deliver=file_receiver.handle_window_delivery,
            expected_types={PacketType.FILE_CHUNK.value},
        )
        gbn_receiver.start()

    if enable_status_listener or enable_dashboard:
        status_service = StatusBroadcastService(
            node,
            udp_socket=node.udp_socket,
            targets=peers,
            on_status=print_status,
        )
        status_service.start()

    if enable_dashboard:
        dashboard = DashboardServer(
            node,
            host=dashboard_host,
            port=dashboard_port,
            neighbor_manager=neighbor_manager,
            topology=topology,
            status_service=status_service,
            location_service=location_service,
            metrics_provider=lambda: build_runtime_metrics(
                neighbor_manager=neighbor_manager,
                routing_manager=routing_manager,
                forwarder=forwarder,
                file_receiver=file_receiver,
                self_healer=self_healer,
            ),
        )
        dashboard.start(block=False)

    if enable_forwarding:
        forwarder = PacketForwarder(
            node,
            udp_socket=node.udp_socket,
            on_local_deliver=handle_local_packet,
            on_drop=lambda pkt, reason, addr: print(f"Dropped packet from {pkt.get('source')}: {reason}"),
            on_forward=lambda pkt, hop, addr: print(
                f"Forwarded packet from {pkt.get('source')} to {pkt.get('destination')} via {hop}"
            ),
        )
        forwarder.start()

    print("Node created:")
    print(f"Node ID: {node.node_id}")
    print(f"Port: {node.port}")
    print(f"Status: {node.status}")
    if enable_discovery:
        print("Discovery: ACTIVE")
    if routing_strategy is not None:
        print(f"Routing: {routing_strategy.value}")
    if enable_forwarding:
        print("Forwarding: ACTIVE")
    if enable_file_receiver:
        print(f"File receiver: ACTIVE ({output_dir})")
    if enable_status_listener:
        print("Status listener: ACTIVE")
    if enable_self_healing:
        print("Self-healing: ACTIVE")
    if enable_dashboard and dashboard:
        print(f"Dashboard: {dashboard.url}")
    print("Waiting for UDP packets. Press Ctrl+C to stop.")

    try:
        last_neighbor_print = 0.0
        while not stopped.wait(0.2):
            now = time.time()
            if now - last_neighbor_print < 3:
                continue

            if enable_discovery:
                active_neighbors = neighbor_manager.active_neighbors()
                if active_neighbors:
                    joined = ", ".join(
                        f"{neighbor.node_id}({neighbor.ip}:{neighbor.port})" for neighbor in active_neighbors
                    )
                    print(f"Active neighbors: {joined}")

            if routing_manager:
                table = routing_manager.current_routing_table()
                if table:
                    print(routing_manager.format_routing_table())

            if enable_topology_print:
                print(TopologyVisualizer(node, topology=topology).to_ascii())

            if forwarder:
                stats = forwarder.stats()
                if stats.total_received > 0:
                    print(
                        f"Forwarder: delivered={stats.delivered_locally} "
                        f"forwarded={stats.forwarded} "
                        f"dropped(ttl={stats.dropped_ttl}, no_route={stats.dropped_no_route})"
                    )

            last_neighbor_print = now
    finally:
        if dashboard:
            dashboard.stop()
        if self_healer:
            self_healer.stop()
        if forwarder:
            forwarder.stop()
        if status_service:
            status_service.stop()
        if gbn_receiver:
            gbn_receiver.stop()
        if routing_manager:
            routing_manager.stop()
        if heartbeat_service:
            heartbeat_service.stop()
        if discovery_service:
            discovery_service.stop()
        reliable_transport.stop()
        node.stop_networking()

    return 0


def run_sender(
    node: MeshNode,
    destination_endpoint: tuple[str, int],
    destination: str,
    message: str,
    reliable: bool = False,
    ack_timeout: float = DEFAULT_RELIABLE_ACK_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_RELIABLE_MAX_RETRIES,
) -> int:
    node.start_networking()
    local_host, local_port = node.udp_socket.local_address
    reliable_transport = None
    messaging_service = MessagingService(node, udp_socket=node.udp_socket)

    try:
        if reliable:
            reliable_transport = ReliableTransport(
                node,
                udp_socket=node.udp_socket,
                ack_timeout=ack_timeout,
                max_retries=max_retries,
                packet_types={PacketType.MESSAGE.value},
            )
            reliable_transport.start()
            messaging_service.reliable_transport = reliable_transport
            result = messaging_service.send_message(
                destination=destination,
                address=destination_endpoint,
                text=message,
                reliable=True,
            )
            if result.acknowledged:
                print(
                    f"Delivered MESSAGE packet #{result.sequence_number} from {node.node_id} "
                    f"on {local_host}:{local_port} to {destination_endpoint[0]}:{destination_endpoint[1]} "
                    f"after {result.retries} retries"
                )
                return 0

            print(
                f"Failed to deliver MESSAGE packet #{result.sequence_number}: "
                f"{result.failed_reason} after {result.retries} retries",
                file=sys.stderr,
            )
            return 1

        result = messaging_service.send_message(
            destination=destination,
            address=destination_endpoint,
            text=message,
            reliable=False,
        )
        print(
            f"Sent MESSAGE packet #{result.sequence_number} from {node.node_id} "
            f"on {local_host}:{local_port} to {destination_endpoint[0]}:{destination_endpoint[1]}"
        )
        return 0
    finally:
        if reliable_transport:
            reliable_transport.stop()
        messaging_service.stop()
        node.stop_networking()


def run_file_sender(
    node: MeshNode,
    destination_endpoint: tuple[str, int],
    destination: str,
    file_path: str,
    window_size: int = DEFAULT_GBN_WINDOW_SIZE,
    ack_timeout: float = DEFAULT_GBN_ACK_TIMEOUT_SECONDS,
    chunk_size: int = DEFAULT_FILE_CHUNK_SIZE,
) -> int:
    node.start_networking()
    local_host, local_port = node.udp_socket.local_address
    sender = FileTransferSender(
        node,
        udp_socket=node.udp_socket,
        window_size=window_size,
        ack_timeout=ack_timeout,
    )

    try:
        result = sender.send_file(
            destination=destination,
            address=destination_endpoint,
            file_path=file_path,
            chunk_size=chunk_size,
        )

        print(
            f"Sent file {result.file_name} ({result.file_size} bytes) from {node.node_id} "
            f"on {local_host}:{local_port} to {destination_endpoint[0]}:{destination_endpoint[1]}"
        )
        print(f"Transfer ID:      {result.transfer_id}")
        print(f"Chunks:           {result.total_chunks}")
        print(f"Packets sent:     {result.packets_sent}")
        print(f"Packets ACKed:    {result.packets_acked}")
        print(f"Retransmissions:  {result.retransmissions}")
        print(f"Success:          {result.success}")
        return 0 if result.success else 1
    finally:
        node.stop_networking()


def run_status_sender(
    node: MeshNode,
    targets: list[tuple[str, int]],
    status: str = DEFAULT_STATUS_VALUE,
    message: str | None = None,
    location_service: LocationService | None = None,
) -> int:
    if not targets:
        print("Status broadcast requires at least one --peer or --send-to target for local testing.", file=sys.stderr)
        return 2

    node.start_networking()
    service = StatusBroadcastService(node, udp_socket=node.udp_socket, targets=targets)
    try:
        location = location_service.current_payload() if location_service else None
        broadcast_id = service.broadcast_status(status=status, message=message, location=location)
        target_text = ", ".join(f"{host}:{port}" for host, port in targets)
        print(f"Broadcast STATUS {status} from {node.node_id} to {target_text}")
        if location:
            print(f"Location: {location['latitude']}, {location['longitude']} ({location['label']})")
        print(f"Broadcast ID: {broadcast_id}")
        time.sleep(0.1)
        return 0
    finally:
        service.stop()
        node.stop_networking()


def run_simulation_demo(
    packets: int,
    loss_rate: float,
    delay: float,
    jitter: float,
    failed_nodes: list[str],
) -> int:
    if packets < 0:
        print("--sim-packets must be non-negative", file=sys.stderr)
        return 2

    delivered_event = threading.Event()
    delivered_packets = []

    def on_packet(packet: dict, address: tuple[str, int]) -> None:
        delivered_packets.append(packet)
        if len(delivered_packets) >= packets:
            delivered_event.set()

    receiver = MeshNode(node_id="SIM_B", ip="127.0.0.1", port=0)
    sender = MeshNode(node_id="SIM_A", ip="127.0.0.1", port=0)
    receiver.start_networking(on_packet=on_packet)
    sender.start_networking()

    simulator = NetworkSimulator(
        loss_rate=loss_rate,
        base_delay_seconds=delay,
        jitter_seconds=jitter,
        random_seed=7,
    )
    for failed_node in failed_nodes:
        simulator.fail_node(failed_node)

    try:
        for index in range(packets):
            packet = create_packet(
                packet_type=PacketType.MESSAGE,
                source=sender.node_id,
                destination=receiver.node_id,
                sequence_number=index + 1,
                payload=f"simulated packet {index + 1}",
            )
            simulator.send_packet(
                sender.udp_socket,
                packet,
                receiver.udp_socket.local_address,
                source_node=sender.node_id,
                destination_node=receiver.node_id,
            )

        wait_time = max(1.0, delay + jitter + 0.5)
        delivered_event.wait(wait_time)
        simulator.wait_for_deliveries(timeout=wait_time)
        stats = simulator.stats()

        print("--- Network Simulator ---")
        print(f"Packets attempted:  {stats.attempted}")
        print(f"Packets delivered:  {stats.delivered}")
        print(f"Packets delayed:    {stats.delayed}")
        print(f"Dropped by loss:    {stats.dropped_loss}")
        print(f"Dropped by failure: {stats.dropped_node_failure}")
        print(f"Send errors:        {stats.send_errors}")
        print(f"Delivery rate:      {stats.delivery_rate:.1%}")
        if failed_nodes:
            print(f"Failed nodes:       {', '.join(failed_nodes)}")
        return 0
    finally:
        sender.stop_networking()
        receiver.stop_networking()


def run_gbn_sender(
    node: MeshNode,
    destination_endpoint: tuple[str, int],
    destination: str,
    message: str,
    window_size: int = DEFAULT_GBN_WINDOW_SIZE,
    gbn_timeout: float = DEFAULT_GBN_ACK_TIMEOUT_SECONDS,
    chunks: int = 5,
    adaptive: bool = False,
) -> int:
    """Send a message split into chunks using Go-Back-N sliding window."""
    node.start_networking()
    local_host, local_port = node.udp_socket.local_address

    tracker = ChecksumTracker()
    sender = SlidingWindowSender(
        node,
        node.udp_socket,
        window_size=window_size,
        ack_timeout=gbn_timeout,
        check_interval=0.02,
    )
    controller = None

    try:
        sender.start()

        if adaptive:
            controller = AdaptiveWindowController(sender, tracker)
            controller.start()
            print(f"Adaptive window control: ENABLED (initial window={window_size})")

        # Split message into chunks.
        chunk_size = max(1, len(message) // chunks)
        payloads = []
        for i in range(0, len(message), chunk_size):
            payloads.append(message[i : i + chunk_size])
        if not payloads:
            payloads = [message]

        print(
            f"Sending {len(payloads)} chunks via Go-Back-N (window={window_size}) "
            f"from {node.node_id} on {local_host}:{local_port} "
            f"to {destination_endpoint[0]}:{destination_endpoint[1]}"
        )

        seqs = sender.send_all(
            destination=destination,
            address=destination_endpoint,
            payloads=payloads,
            packet_type=PacketType.MESSAGE,
        )

        success = sender.wait_all_acked(timeout=30)
        stats = sender.stats()

        print(f"\n--- Go-Back-N Transfer Summary ---")
        print(f"Chunks sent:       {stats.packets_sent}")
        print(f"Chunks ACKed:      {stats.packets_acked}")
        print(f"Retransmissions:   {stats.retransmissions}")
        print(f"Timeouts:          {stats.timeouts}")
        print(f"Final window size: {stats.window_size}")
        print(f"Loss rate:         {stats.loss_rate:.1%}")

        if adaptive and controller:
            snap = controller.current_snapshot()
            if snap:
                print(f"\n--- Adaptive Window Controller ---")
                print(f"Last decision:     {snap.decision}")
                print(f"SRTT:              {snap.srtt:.4f}s")
                print(f"RTO:               {snap.rto:.4f}s")
                print(f"Corruption rate:   {snap.corruption_rate:.1%}")

        if success:
            print(f"\nAll {len(payloads)} chunks delivered successfully.")
            return 0
        else:
            print(f"\nSome chunks were not acknowledged.", file=sys.stderr)
            return 1

    finally:
        if controller:
            controller.stop()
        sender.stop()
        node.stop_networking()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.sim_demo:
        return run_simulation_demo(
            packets=args.sim_packets,
            loss_rate=args.loss_rate,
            delay=args.delay,
            jitter=args.jitter,
            failed_nodes=args.fail_node,
        )

    try:
        location_service = build_location_service(args.latitude, args.longitude, args.location_label)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    port = args.port
    if port is None:
        port = 0 if args.send_to or args.send_file or args.im_safe or args.status else DEFAULT_PORT

    node = MeshNode(node_id=args.node_id, ip=args.host, port=port)

    try:
        if args.im_safe or args.status:
            targets = list(args.peer)
            if args.send_to:
                targets.append(args.send_to)
            return run_status_sender(
                node,
                targets=targets,
                status=DEFAULT_STATUS_VALUE if args.im_safe else args.status,
                message=args.message,
                location_service=location_service,
            )

        if args.send_file:
            if not args.send_to:
                print("--send-file requires --send-to", file=sys.stderr)
                return 2
            return run_file_sender(
                node,
                args.send_to,
                args.destination,
                args.send_file,
                window_size=args.window_size,
                ack_timeout=args.gbn_timeout,
                chunk_size=args.chunk_size,
            )

        if args.send_to:
            if not args.message:
                print("--message is required when --send-to is provided", file=sys.stderr)
                return 2

            if args.gbn:
                return run_gbn_sender(
                    node,
                    args.send_to,
                    args.destination,
                    args.message,
                    window_size=args.window_size,
                    gbn_timeout=args.gbn_timeout,
                    chunks=args.chunks,
                    adaptive=args.adaptive,
                )

            return run_sender(
                node,
                args.send_to,
                args.destination,
                args.message,
                reliable=args.reliable,
                ack_timeout=args.ack_timeout,
                max_retries=args.max_retries,
            )

        # Determine routing strategy.
        routing_strategy = None
        if args.link_state:
            routing_strategy = RoutingStrategy.LINK_STATE
        elif args.distance_vector:
            routing_strategy = RoutingStrategy.DISTANCE_VECTOR

        routing_interval = args.routing_interval
        if args.lsa_interval != 5.0 and args.routing_interval == 5.0:
            routing_interval = args.lsa_interval  # backward compat

        return run_receiver(
            node,
            enable_discovery=args.discover,
            routing_strategy=routing_strategy,
            enable_forwarding=args.forward,
            enable_file_receiver=args.receive_files,
            output_dir=args.output_dir,
            enable_status_listener=args.status_listen,
            location_service=location_service,
            enable_self_healing=args.self_heal,
            self_heal_interval=args.self_heal_interval,
            enable_topology_print=args.print_topology,
            enable_dashboard=args.dashboard,
            dashboard_host=args.dashboard_host,
            dashboard_port=args.dashboard_port,
            peers=args.peer,
            discovery_interval=args.discovery_interval,
            heartbeat_interval=args.heartbeat_interval,
            neighbor_timeout=args.neighbor_timeout,
            routing_interval=routing_interval,
        )
    except PermissionError as exc:
        print(f"Could not bind UDP socket on {node.ip}:{node.port}: {exc}", file=sys.stderr)
        if args.send_to:
            print("For send-only tests, omit --port or use --port 0 so Windows picks a free local port.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
