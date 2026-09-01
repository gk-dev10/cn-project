from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

from core.constants import DEFAULT_TTL, PACKET_TYPE_VALUES, PROTOCOL_VERSION, PacketType


WIRE_BYTES_MARKER = "__meshlink_bytes__"
REQUIRED_PACKET_FIELDS = (
    "version",
    "type",
    "source",
    "destination",
    "sequence_number",
    "ttl",
    "payload_length",
    "payload",
    "checksum",
)
CHECKSUM_FIELDS = (
    "version",
    "type",
    "source",
    "destination",
    "sequence_number",
    "ttl",
    "payload_length",
    "payload",
)


class PacketError(ValueError):
    """Raised when packet data is malformed."""


class ChecksumError(PacketError):
    """Raised when a packet checksum does not match the packet body."""


def _packet_type_value(packet_type: PacketType | str) -> str:
    if isinstance(packet_type, PacketType):
        return packet_type.value

    if isinstance(packet_type, str) and packet_type in PACKET_TYPE_VALUES:
        return packet_type

    raise PacketError(f"unsupported packet type: {packet_type!r}")


def _encode_payload(payload: Any) -> Any:
    if isinstance(payload, bytes):
        return {
            WIRE_BYTES_MARKER: True,
            "data": base64.b64encode(payload).decode("ascii"),
        }
    return payload


def _decode_payload(payload: Any) -> Any:
    if isinstance(payload, dict) and payload.get(WIRE_BYTES_MARKER) is True:
        try:
            return base64.b64decode(payload["data"].encode("ascii"), validate=True)
        except (KeyError, ValueError) as exc:
            raise PacketError("invalid base64 payload encoding") from exc
    return payload


def _payload_length(payload: Any) -> int:
    if isinstance(payload, bytes):
        return len(payload)
    if isinstance(payload, str):
        return len(payload.encode("utf-8"))

    encoded = json.dumps(_encode_payload(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return len(encoded)


def _canonical_json(data: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except TypeError as exc:
        raise PacketError("packet payload must be JSON serializable or bytes") from exc


def _checksum_body(packet: Mapping[str, Any]) -> dict[str, Any]:
    body = {field: packet.get(field) for field in CHECKSUM_FIELDS}
    body["type"] = _packet_type_value(body["type"])
    body["payload"] = _encode_payload(body["payload"])
    return body


def _packet_for_wire(packet: Mapping[str, Any]) -> dict[str, Any]:
    wire_packet = {field: packet[field] for field in REQUIRED_PACKET_FIELDS}
    wire_packet["type"] = _packet_type_value(wire_packet["type"])
    wire_packet["payload"] = _encode_payload(wire_packet["payload"])
    return wire_packet


def _validate_packet(packet: Mapping[str, Any]) -> None:
    missing_fields = [field for field in REQUIRED_PACKET_FIELDS if field not in packet]
    if missing_fields:
        raise PacketError(f"packet missing fields: {', '.join(missing_fields)}")

    if packet["version"] != PROTOCOL_VERSION:
        raise PacketError(f"unsupported protocol version: {packet['version']!r}")

    _packet_type_value(packet["type"])

    if not isinstance(packet["source"], str) or not packet["source"]:
        raise PacketError("packet source must be a non-empty string")

    destination = packet["destination"]
    if destination is not None and not isinstance(destination, str):
        raise PacketError("packet destination must be a string or None")

    for field in ("sequence_number", "ttl", "payload_length"):
        if not isinstance(packet[field], int) or packet[field] < 0:
            raise PacketError(f"packet {field} must be a non-negative integer")

    actual_payload_length = _payload_length(packet["payload"])
    if packet["payload_length"] != actual_payload_length:
        raise PacketError(
            f"payload length mismatch: expected {packet['payload_length']}, got {actual_payload_length}"
        )

    if not isinstance(packet["checksum"], str) or not packet["checksum"]:
        raise ChecksumError("packet checksum is missing")


def calculate_checksum(packet: Mapping[str, Any]) -> str:
    body = _checksum_body(packet)
    return hashlib.sha256(_canonical_json(body)).hexdigest()


def verify_checksum(packet: Mapping[str, Any]) -> bool:
    checksum = packet.get("checksum")
    if not isinstance(checksum, str) or not checksum:
        return False
    return hmac.compare_digest(checksum, calculate_checksum(packet))


def create_packet(
    packet_type: PacketType | str,
    source: str,
    destination: str | None = None,
    sequence_number: int = 0,
    ttl: int = DEFAULT_TTL,
    payload: Any = None,
    version: int = PROTOCOL_VERSION,
) -> dict[str, Any]:
    packet = {
        "version": version,
        "type": _packet_type_value(packet_type),
        "source": source,
        "destination": destination,
        "sequence_number": sequence_number,
        "ttl": ttl,
        "payload_length": _payload_length(payload),
        "payload": payload,
        "checksum": "",
    }
    packet["checksum"] = calculate_checksum(packet)
    _validate_packet(packet)
    return packet


def serialize_packet(packet: Mapping[str, Any]) -> bytes:
    _validate_packet(packet)
    if not verify_checksum(packet):
        raise ChecksumError("packet checksum does not match packet body")
    return _canonical_json(_packet_for_wire(packet))


def deserialize_packet(data: bytes | str) -> dict[str, Any]:
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PacketError("packet bytes must be valid UTF-8 JSON") from exc
    else:
        text = data

    try:
        packet = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PacketError("packet data must be valid JSON") from exc

    if not isinstance(packet, dict):
        raise PacketError("packet data must decode to a JSON object")

    if "payload" in packet:
        packet["payload"] = _decode_payload(packet["payload"])

    _validate_packet(packet)
    if not verify_checksum(packet):
        raise ChecksumError("packet checksum does not match packet body")
    return packet

