from __future__ import annotations

from collections.abc import Mapping
import socket
import threading
from typing import Callable, Optional

from core.constants import DEFAULT_SOCKET_BUFFER_SIZE, DEFAULT_SOCKET_TIMEOUT_SECONDS
from core.packet import PacketError, deserialize_packet, serialize_packet


PacketHandler = Callable[[dict, tuple[str, int]], None]
ErrorHandler = Callable[[Exception], None]


class UDPSocket:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5000,
        on_packet: Optional[PacketHandler] = None,
        on_error: Optional[ErrorHandler] = None,
        buffer_size: int = DEFAULT_SOCKET_BUFFER_SIZE,
        receive_timeout: float = DEFAULT_SOCKET_TIMEOUT_SECONDS,
        allow_broadcast: bool = True,
    ):
        self.host = host
        self.port = port
        self.on_packet = on_packet
        self.on_error = on_error
        self.buffer_size = buffer_size
        self.receive_timeout = receive_timeout
        self.allow_broadcast = allow_broadcast
        self._socket: Optional[socket.socket] = None
        self._receiver_thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._handler_lock = threading.RLock()
        self._packet_handlers: list[PacketHandler] = []
        if on_packet:
            self._packet_handlers.append(on_packet)

    @property
    def is_running(self) -> bool:
        return self._running.is_set() and self._socket is not None

    @property
    def local_address(self) -> tuple[str, int]:
        if not self._socket:
            return self.host, self.port
        host, port = self._socket.getsockname()
        return str(host), int(port)

    def start_socket(self) -> tuple[str, int]:
        if self.is_running:
            return self.local_address

        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if self.allow_broadcast:
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp_socket.bind((self.host, self.port))
        udp_socket.settimeout(self.receive_timeout)

        self._socket = udp_socket
        self.host, self.port = self.local_address
        self._running.set()

        self._start_receiver_thread()

        return self.local_address

    def add_packet_handler(self, handler: PacketHandler) -> None:
        with self._handler_lock:
            if handler not in self._packet_handlers:
                self._packet_handlers.append(handler)
        self._start_receiver_thread()

    def remove_packet_handler(self, handler: PacketHandler) -> None:
        with self._handler_lock:
            self._packet_handlers = [registered for registered in self._packet_handlers if registered != handler]

    def _start_receiver_thread(self) -> None:
        with self._handler_lock:
            has_handlers = bool(self._packet_handlers)
        if not self.is_running or not has_handlers:
            return

        if self._receiver_thread and self._receiver_thread.is_alive():
            return

        self._receiver_thread = threading.Thread(
            target=self._receive_loop,
            name=f"meshlink-udp-receiver-{self.port}",
            daemon=True,
        )
        self._receiver_thread.start()

    def send_packet(self, packet: Mapping | bytes, address: tuple[str, int]) -> int:
        if not self._socket:
            raise RuntimeError("UDP socket has not been started")

        data = packet if isinstance(packet, bytes) else serialize_packet(packet)
        return self._socket.sendto(data, address)

    def receive_packet(self, timeout: Optional[float] = None) -> Optional[tuple[dict, tuple[str, int]]]:
        if not self._socket:
            raise RuntimeError("UDP socket has not been started")

        previous_timeout = self._socket.gettimeout()
        if timeout is not None:
            self._socket.settimeout(timeout)

        try:
            data, address = self._socket.recvfrom(self.buffer_size)
            return deserialize_packet(data), (address[0], address[1])
        except socket.timeout:
            return None
        finally:
            if timeout is not None and self._socket:
                self._socket.settimeout(previous_timeout)

    def stop_socket(self) -> None:
        self._running.clear()
        udp_socket = self._socket
        self._socket = None

        if udp_socket:
            udp_socket.close()

        if self._receiver_thread and self._receiver_thread is not threading.current_thread():
            self._receiver_thread.join(timeout=1)
        self._receiver_thread = None

    def _receive_loop(self) -> None:
        while self._running.is_set():
            try:
                result = self.receive_packet()
            except OSError as exc:
                if self._running.is_set() and self.on_error:
                    self.on_error(exc)
                break
            except PacketError as exc:
                if self.on_error:
                    self.on_error(exc)
                continue

            if result is None:
                continue

            packet, address = result
            with self._handler_lock:
                handlers = list(self._packet_handlers)

            for handler in handlers:
                handler(packet, address)


def start_socket(
    host: str = "0.0.0.0",
    port: int = 5000,
    on_packet: Optional[PacketHandler] = None,
) -> UDPSocket:
    udp_socket = UDPSocket(host=host, port=port, on_packet=on_packet)
    udp_socket.start_socket()
    return udp_socket


def send_packet(udp_socket: UDPSocket, packet: Mapping | bytes, address: tuple[str, int]) -> int:
    return udp_socket.send_packet(packet, address)


def receive_packet(udp_socket: UDPSocket, timeout: Optional[float] = None) -> Optional[tuple[dict, tuple[str, int]]]:
    return udp_socket.receive_packet(timeout=timeout)


def stop_socket(udp_socket: UDPSocket) -> None:
    udp_socket.stop_socket()
