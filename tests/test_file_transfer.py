import tempfile
import threading
from pathlib import Path
import unittest

from application.file_transfer import FileTransferReceiver, FileTransferSender, build_file_metadata
from core.constants import PacketType
from core.node import MeshNode
from transport.sliding_window import SlidingWindowReceiver


class FileTransferTests(unittest.TestCase):
    def test_metadata_describes_file_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.txt"
            source.write_bytes(b"abcdefghij")

            metadata = build_file_metadata(source, chunk_size=4)

            self.assertEqual(metadata.file_name, "sample.txt")
            self.assertEqual(metadata.file_size, 10)
            self.assertEqual(metadata.total_chunks, 3)

    def test_file_transfer_reassembles_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "source.txt"
            output_dir = tmp_path / "received"
            source.write_bytes(b"MeshLink file transfer payload")

            sender_node = MeshNode(node_id="DEVICE_A", ip="127.0.0.1", port=0)
            receiver_node = MeshNode(node_id="DEVICE_B", ip="127.0.0.1", port=0)
            sender_node.start_networking()
            receiver_node.start_networking()

            completed = []
            completed_event = threading.Event()

            def on_complete(received_file):
                completed.append(received_file)
                completed_event.set()

            receiver = FileTransferReceiver(output_dir=output_dir, on_complete=on_complete)
            window_receiver = SlidingWindowReceiver(
                receiver_node,
                receiver_node.udp_socket,
                on_deliver=receiver.handle_window_delivery,
                expected_types={PacketType.FILE_CHUNK.value},
            )
            sender = FileTransferSender(
                sender_node,
                udp_socket=sender_node.udp_socket,
                window_size=4,
                ack_timeout=0.1,
            )

            try:
                window_receiver.start()
                result = sender.send_file(
                    destination="DEVICE_B",
                    address=receiver_node.udp_socket.local_address,
                    file_path=source,
                    chunk_size=6,
                    wait_timeout=5,
                )

                self.assertTrue(result.success)
                self.assertTrue(completed_event.wait(2))
                self.assertEqual(completed[0].file_name, "source.txt")
                self.assertEqual(completed[0].path.read_bytes(), source.read_bytes())
            finally:
                window_receiver.stop()
                sender_node.stop_networking()
                receiver_node.stop_networking()


if __name__ == "__main__":
    unittest.main()

