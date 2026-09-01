from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from typing import Tuple

from core.constants import (
    DEFAULT_DISCOVERY_INTERVAL_SECONDS,
    DEFAULT_GBN_ACK_TIMEOUT_SECONDS,
    DEFAULT_GBN_WINDOW_SIZE,
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    DEFAULT_NEIGHBOR_TIMEOUT_SECONDS,
    DEFAULT_PORT,
    DEFAULT_RELIABLE_ACK_TIMEOUT_SECONDS,
    DEFAULT_RELIABLE_MAX_RETRIES,
    PacketType,
)
from core.node import MeshNode
from core.packet import create_packet
from discovery.discovery_service import DiscoveryService
from discovery.heartbeat_service import HeartbeatService
from discovery.neighbor_manager import NeighborManager
from routing.link_state import LinkStateService
from routing.topology import NetworkTopology
from transport.adaptive_window import AdaptiveWindowController
from transport.checksum_tracker import ChecksumTracker
from transport.reliable_transport import ReliableTransport
from transport.sliding_window import SlidingWindowReceiver, SlidingWindowSender


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
    parser = argparse.ArgumentParser(description="Run a MeshLink node for Modules 1-12.")
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
    # Module 11 — Link-State routing.
    parser.add_argument("--link-state", action="store_true", help="Enable Link-State routing with Dijkstra")
    parser.add_argument("--lsa-interval", type=float, default=5.0, help="Seconds between Link-State Advertisements")
    return parser


def print_packet(packet: dict, address: tuple[str, int]) -> None:
    print(f"Received {packet['type']} from {packet['source']} at {address[0]}:{address[1]}")
    print(f"Sequence: {packet['sequence_number']} TTL: {packet['ttl']}")
    print(f"Payload: {packet['payload']}")


def run_receiver(
    node: MeshNode,
    enable_discovery: bool = False,
    enable_link_state: bool = False,
    peers: list[tuple[str, int]] | None = None,
    discovery_interval: float = DEFAULT_DISCOVERY_INTERVAL_SECONDS,
    heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    neighbor_timeout: float = DEFAULT_NEIGHBOR_TIMEOUT_SECONDS,
    lsa_interval: float = 5.0,
) -> int:
    stopped = threading.Event()

    def handle_signal(signum: int, frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    peers = peers or []
    neighbor_manager = NeighborManager(node.neighbors, self_node_id=node.node_id)
    announced_neighbors: set[str] = set()

    def handle_neighbor_discovered(neighbor) -> None:
        if neighbor.node_id in announced_neighbors:
            return
        announced_neighbors.add(neighbor.node_id)
        print(f"Discovered neighbor: {neighbor.node_id} at {neighbor.ip}:{neighbor.port}")

    def handle_neighbor_lost(neighbor) -> None:
        print(f"Neighbor offline: {neighbor.node_id}")

    node.start_networking()
    reliable_transport = ReliableTransport(node, udp_socket=node.udp_socket, on_packet=print_packet)
    reliable_transport.start()

    discovery_service = None
    heartbeat_service = None
    link_state_service = None
    topology = None

    if enable_discovery:
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

    if enable_link_state:
        topology = NetworkTopology(self_node_id=node.node_id)
        link_state_service = LinkStateService(
            node,
            topology,
            udp_socket=node.udp_socket,
            interval=lsa_interval,
            on_route_change=lambda t: print(f"Routes updated: {len(t)} destinations"),
        )
        link_state_service.start()

    print("Node created:")
    print(f"Node ID: {node.node_id}")
    print(f"Port: {node.port}")
    print(f"Status: {node.status}")
    if enable_discovery:
        print("Discovery: ACTIVE")
    if enable_link_state:
        print("Link-State Routing: ACTIVE")
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

            if enable_link_state and link_state_service:
                table = link_state_service.current_routing_table()
                if table:
                    print(link_state_service.format_routing_table())

            last_neighbor_print = now
    finally:
        if link_state_service:
            link_state_service.stop()
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

    try:
        if reliable:
            reliable_transport = ReliableTransport(
                node,
                udp_socket=node.udp_socket,
                ack_timeout=ack_timeout,
                max_retries=max_retries,
            )
            reliable_transport.start()
            result = reliable_transport.send_message(
                destination=destination,
                address=destination_endpoint,
                message=message,
                wait_for_ack=True,
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

        packet = create_packet(
            packet_type=PacketType.MESSAGE,
            source=node.node_id,
            destination=destination,
            sequence_number=1,
            payload=message,
        )
        node.udp_socket.send_packet(packet, destination_endpoint)
        print(
            f"Sent MESSAGE packet #1 from {node.node_id} "
            f"on {local_host}:{local_port} to {destination_endpoint[0]}:{destination_endpoint[1]}"
        )
        return 0
    finally:
        if reliable_transport:
            reliable_transport.stop()
        node.stop_networking()


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
    port = args.port
    if port is None:
        port = 0 if args.send_to else DEFAULT_PORT

    node = MeshNode(node_id=args.node_id, ip=args.host, port=port)

    try:
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

        return run_receiver(
            node,
            enable_discovery=args.discover,
            enable_link_state=args.link_state,
            peers=args.peer,
            discovery_interval=args.discovery_interval,
            heartbeat_interval=args.heartbeat_interval,
            neighbor_timeout=args.neighbor_timeout,
            lsa_interval=args.lsa_interval,
        )
    except PermissionError as exc:
        print(f"Could not bind UDP socket on {node.ip}:{node.port}: {exc}", file=sys.stderr)
        if args.send_to:
            print("For send-only tests, omit --port or use --port 0 so Windows picks a free local port.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
