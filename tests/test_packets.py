import unittest

from core.constants import DEFAULT_TTL, PacketType, PROTOCOL_VERSION
from core.packet import (
    ChecksumError,
    create_packet,
    deserialize_packet,
    serialize_packet,
    verify_checksum,
)


class PacketTests(unittest.TestCase):
    def test_create_packet_sets_required_fields(self):
        packet = create_packet(
            packet_type=PacketType.MESSAGE,
            source="DEVICE_A",
            destination="DEVICE_B",
            sequence_number=42,
            payload="Hello",
        )

        self.assertEqual(packet["version"], PROTOCOL_VERSION)
        self.assertEqual(packet["type"], "MESSAGE")
        self.assertEqual(packet["source"], "DEVICE_A")
        self.assertEqual(packet["destination"], "DEVICE_B")
        self.assertEqual(packet["sequence_number"], 42)
        self.assertEqual(packet["ttl"], DEFAULT_TTL)
        self.assertEqual(packet["payload"], "Hello")
        self.assertTrue(verify_checksum(packet))

    def test_packet_round_trip(self):
        packet = create_packet(PacketType.STATUS, "DEVICE_A", payload={"status": "SAFE"})

        encoded = serialize_packet(packet)
        decoded = deserialize_packet(encoded)

        self.assertEqual(decoded, packet)

    def test_binary_payload_round_trip(self):
        packet = create_packet(PacketType.FILE_CHUNK, "DEVICE_A", "DEVICE_B", payload=b"\x00\x01mesh")

        decoded = deserialize_packet(serialize_packet(packet))

        self.assertEqual(decoded["payload"], b"\x00\x01mesh")
        self.assertTrue(verify_checksum(decoded))

    def test_checksum_detects_tampering(self):
        packet = create_packet(PacketType.MESSAGE, "DEVICE_A", "DEVICE_B", payload="Original")
        tampered = dict(packet)
        tampered["payload"] = "Changed"
        tampered["payload_length"] = len("Changed")

        self.assertFalse(verify_checksum(tampered))
        with self.assertRaises(ChecksumError):
            serialize_packet(tampered)

    def test_deserialize_rejects_bad_checksum(self):
        packet = create_packet(PacketType.MESSAGE, "DEVICE_A", "DEVICE_B", payload="Original")
        encoded = serialize_packet(packet).decode("utf-8")
        corrupted = encoded.replace("Original", "Modified")

        with self.assertRaises(ChecksumError):
            deserialize_packet(corrupted)


if __name__ == "__main__":
    unittest.main()
