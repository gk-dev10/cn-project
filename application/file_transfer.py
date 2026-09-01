"""Module 19 - File transfer application.

Files are split into metadata plus numbered chunks and sent with the
existing Go-Back-N sliding-window transport. Chunks are JSON-safe by
base64 encoding their binary data inside the packet payload.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
import threading
import time
import uuid
from typing import Callable, Optional

from core.constants import (
    DEFAULT_FILE_CHUNK_SIZE,
    DEFAULT_GBN_ACK_TIMEOUT_SECONDS,
    DEFAULT_GBN_WINDOW_SIZE,
    DEFAULT_RECEIVED_FILES_DIR,
    PacketType,
)
from core.node import MeshNode
from transport.sliding_window import SlidingWindowSender, WindowStats
from transport.udp_socket import UDPSocket


FILE_PAYLOAD_METADATA = "metadata"
FILE_PAYLOAD_CHUNK = "chunk"

FileCompleteCallback = Callable[["ReceivedFile"], None]


@dataclass(frozen=True, slots=True)
class FileMetadata:
    transfer_id: str
    file_name: str
    file_size: int
    total_chunks: int
    sha256: str
    chunk_size: int

    def to_payload(self) -> dict:
        return {
            "kind": FILE_PAYLOAD_METADATA,
            "transfer_id": self.transfer_id,
            "file_name": self.file_name,
            "file_size": self.file_size,
            "total_chunks": self.total_chunks,
            "sha256": self.sha256,
            "chunk_size": self.chunk_size,
        }


@dataclass(frozen=True, slots=True)
class FileTransferResult:
    transfer_id: str
    file_name: str
    file_size: int
    total_chunks: int
    packets_sent: int
    packets_acked: int
    retransmissions: int
    success: bool
    destination: str
    address: tuple[str, int]


@dataclass(frozen=True, slots=True)
class ReceivedFile:
    transfer_id: str
    file_name: str
    file_size: int
    total_chunks: int
    sha256: str
    path: Path
    completed_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class _IncomingTransfer:
    metadata: FileMetadata
    chunks: dict[int, bytes] = field(default_factory=dict)
    completed: bool = False


class FileTransferSender:
    def __init__(
        self,
        node: MeshNode,
        udp_socket: Optional[UDPSocket] = None,
        window_size: int = DEFAULT_GBN_WINDOW_SIZE,
        ack_timeout: float = DEFAULT_GBN_ACK_TIMEOUT_SECONDS,
    ) -> None:
        self.node = node
        self.udp_socket = udp_socket
        self.window_size = window_size
        self.ack_timeout = ack_timeout

    def send_file(
        self,
        destination: str,
        address: tuple[str, int],
        file_path: str | Path,
        chunk_size: int = DEFAULT_FILE_CHUNK_SIZE,
        wait_timeout: float = 60.0,
    ) -> FileTransferResult:
        self._ensure_socket()
        path = Path(file_path)
        metadata = build_file_metadata(path, chunk_size=chunk_size)
        payloads = [metadata.to_payload()]
        payloads.extend(iter_file_chunk_payloads(path, metadata))

        sender = SlidingWindowSender(
            self.node,
            self.udp_socket,
            window_size=self.window_size,
            ack_timeout=self.ack_timeout,
            check_interval=0.02,
        )

        try:
            sender.start()
            sender.send_all(
                destination=destination,
                address=address,
                payloads=payloads,
                packet_type=PacketType.FILE_CHUNK,
            )
            success = sender.wait_all_acked(timeout=wait_timeout)
            stats = sender.stats()
        finally:
            sender.stop()

        return _result_from_stats(metadata, stats, success, destination, address)

    def _ensure_socket(self) -> None:
        if self.udp_socket:
            if not self.udp_socket.is_running:
                self.udp_socket.start_socket()
            return

        self.node.start_networking()
        self.udp_socket = self.node.udp_socket


class FileTransferReceiver:
    def __init__(
        self,
        output_dir: str | Path = DEFAULT_RECEIVED_FILES_DIR,
        on_complete: Optional[FileCompleteCallback] = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.on_complete = on_complete
        self.transfers: dict[str, _IncomingTransfer] = {}
        self.completed_files: dict[str, ReceivedFile] = {}
        self._lock = threading.RLock()

    def handle_window_delivery(
        self,
        sequence_number: int,
        packet: dict,
        address: tuple[str, int],
    ) -> Optional[ReceivedFile]:
        return self.handle_packet(packet, address)

    def handle_packet(self, packet: dict, address: tuple[str, int]) -> Optional[ReceivedFile]:
        if packet.get("type") != PacketType.FILE_CHUNK.value:
            return None

        payload = packet.get("payload")
        if not isinstance(payload, dict):
            return None

        kind = payload.get("kind")
        if kind == FILE_PAYLOAD_METADATA:
            return self._handle_metadata(payload)
        if kind == FILE_PAYLOAD_CHUNK:
            return self._handle_chunk(payload)
        return None

    def _handle_metadata(self, payload: dict) -> Optional[ReceivedFile]:
        metadata = FileMetadata(
            transfer_id=str(payload["transfer_id"]),
            file_name=_safe_file_name(str(payload["file_name"])),
            file_size=int(payload["file_size"]),
            total_chunks=int(payload["total_chunks"]),
            sha256=str(payload["sha256"]),
            chunk_size=int(payload["chunk_size"]),
        )

        with self._lock:
            transfer = self.transfers.get(metadata.transfer_id)
            if transfer is None:
                self.transfers[metadata.transfer_id] = _IncomingTransfer(metadata=metadata)
            if metadata.total_chunks == 0:
                return self._complete_transfer(metadata.transfer_id)
        return None

    def _handle_chunk(self, payload: dict) -> Optional[ReceivedFile]:
        transfer_id = str(payload.get("transfer_id", ""))
        chunk_index = int(payload.get("chunk_index", -1))
        data = base64.b64decode(str(payload.get("data_b64", "")).encode("ascii"), validate=True)

        with self._lock:
            transfer = self.transfers.get(transfer_id)
            if transfer is None or transfer.completed:
                return None
            if not 0 <= chunk_index < transfer.metadata.total_chunks:
                return None

            transfer.chunks[chunk_index] = data
            if len(transfer.chunks) == transfer.metadata.total_chunks:
                return self._complete_transfer(transfer_id)
        return None

    def _complete_transfer(self, transfer_id: str) -> ReceivedFile:
        transfer = self.transfers[transfer_id]
        metadata = transfer.metadata
        data = b"".join(transfer.chunks[index] for index in range(metadata.total_chunks))

        if len(data) != metadata.file_size:
            raise ValueError(f"file size mismatch for transfer {transfer_id}")

        digest = hashlib.sha256(data).hexdigest()
        if digest != metadata.sha256:
            raise ValueError(f"file checksum mismatch for transfer {transfer_id}")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        target_path = _unique_output_path(self.output_dir / metadata.file_name)
        target_path.write_bytes(data)

        transfer.completed = True
        received_file = ReceivedFile(
            transfer_id=transfer_id,
            file_name=metadata.file_name,
            file_size=metadata.file_size,
            total_chunks=metadata.total_chunks,
            sha256=metadata.sha256,
            path=target_path,
        )
        self.completed_files[transfer_id] = received_file

        if self.on_complete:
            self.on_complete(received_file)

        return received_file


def build_file_metadata(file_path: str | Path, chunk_size: int = DEFAULT_FILE_CHUNK_SIZE) -> FileMetadata:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    path = Path(file_path)
    data = path.read_bytes()
    total_chunks = (len(data) + chunk_size - 1) // chunk_size
    return FileMetadata(
        transfer_id=uuid.uuid4().hex,
        file_name=_safe_file_name(path.name),
        file_size=len(data),
        total_chunks=total_chunks,
        sha256=hashlib.sha256(data).hexdigest(),
        chunk_size=chunk_size,
    )


def iter_file_chunk_payloads(file_path: str | Path, metadata: FileMetadata) -> list[dict]:
    path = Path(file_path)
    payloads = []
    with path.open("rb") as file_obj:
        for index in range(metadata.total_chunks):
            data = file_obj.read(metadata.chunk_size)
            payloads.append(
                {
                    "kind": FILE_PAYLOAD_CHUNK,
                    "transfer_id": metadata.transfer_id,
                    "chunk_index": index,
                    "total_chunks": metadata.total_chunks,
                    "data_b64": base64.b64encode(data).decode("ascii"),
                }
            )
    return payloads


def _result_from_stats(
    metadata: FileMetadata,
    stats: WindowStats,
    success: bool,
    destination: str,
    address: tuple[str, int],
) -> FileTransferResult:
    return FileTransferResult(
        transfer_id=metadata.transfer_id,
        file_name=metadata.file_name,
        file_size=metadata.file_size,
        total_chunks=metadata.total_chunks,
        packets_sent=stats.packets_sent,
        packets_acked=stats.packets_acked,
        retransmissions=stats.retransmissions,
        success=success,
        destination=destination,
        address=address,
    )


def _safe_file_name(file_name: str) -> str:
    base_name = Path(file_name).name.strip() or "received_file"
    return re.sub(r"[^A-Za-z0-9._-]", "_", base_name)


def _unique_output_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1

