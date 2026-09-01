from __future__ import annotations

import argparse
import signal
import sys
import threading
from typing import Tuple

from core.constants import DEFAULT_PORT, PacketType
from core.node import MeshNode
from core.packet import create_packet


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
    parser = argparse.ArgumentParser(description="Run a MeshLink node for Modules 1-3.")
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
    return parser


def print_packet(packet: dict, address: tuple[str, int]) -> None:
    print(f"Received {packet['type']} from {packet['source']} at {address[0]}:{address[1]}")
    print(f"Sequence: {packet['sequence_number']} TTL: {packet['ttl']}")
    print(f"Payload: {packet['payload']}")


def run_receiver(node: MeshNode) -> int:
    stopped = threading.Event()

    def handle_signal(signum: int, frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    node.start_networking(on_packet=print_packet)
    print("Node created:")
    print(f"Node ID: {node.node_id}")
    print(f"Port: {node.port}")
    print(f"Status: {node.status}")
    print("Waiting for UDP packets. Press Ctrl+C to stop.")

    try:
        while not stopped.wait(0.2):
            pass
    finally:
        node.stop_networking()

    return 0


def run_sender(node: MeshNode, destination_endpoint: tuple[str, int], destination: str, message: str) -> int:
    node.start_networking()
    local_host, local_port = node.udp_socket.local_address
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
    node.stop_networking()
    return 0


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
            return run_sender(node, args.send_to, args.destination, args.message)

        return run_receiver(node)
    except PermissionError as exc:
        print(f"Could not bind UDP socket on {node.ip}:{node.port}: {exc}", file=sys.stderr)
        if args.send_to:
            print("For send-only tests, omit --port or use --port 0 so Windows picks a free local port.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
