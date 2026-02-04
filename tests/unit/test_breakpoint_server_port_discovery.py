"""Tests for BreakpointServer port discovery integration."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("requests")
import requests

from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer


def _start_server(server: BreakpointServer) -> threading.Thread:
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    return thread


def _wait_for_port_file(port_file: Path, timeout: float = 5.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_file.exists():
            return int(port_file.read_text())
        time.sleep(0.1)
    raise AssertionError("port discovery file not created")


def _stop_server(server: BreakpointServer, thread: threading.Thread) -> None:
    server.stop()
    thread.join(timeout=2)


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _skip_if_socket_unavailable() -> None:
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
    except PermissionError:
        pytest.skip("Socket bind not permitted in this environment")


def test_server_writes_port_to_discovery_file() -> None:
    """Test that server writes its port to the discovery file."""
    _skip_if_socket_unavailable()
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        manager = BreakpointManager()
        server = BreakpointServer(manager, port=0, port_file=port_file)

        thread = _start_server(server)
        try:
            port = _wait_for_port_file(port_file)

            assert 1024 <= port <= 65535
            response = requests.get(f"http://localhost:{port}/api/breakpoints", timeout=1)
            assert response.status_code == 200
        finally:
            _stop_server(server, thread)


def test_server_uses_specified_port_if_available() -> None:
    """Test that server uses specified port if available."""
    _skip_if_socket_unavailable()
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        manager = BreakpointManager()
        try:
            requested_port = _find_free_port()
        except PermissionError:
            pytest.skip("Socket bind not permitted in this environment")
        server = BreakpointServer(manager, port=requested_port, port_file=port_file)

        thread = _start_server(server)
        try:
            actual_port = _wait_for_port_file(port_file)

            assert actual_port == requested_port
        finally:
            _stop_server(server, thread)


def test_server_falls_back_if_port_occupied() -> None:
    """Test that server falls back to free port if requested port is occupied."""
    _skip_if_socket_unavailable()
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        port_file2 = Path(tmpdir) / "port2"
        manager1 = BreakpointManager()
        manager2 = BreakpointManager()

        try:
            requested_port = _find_free_port()
        except PermissionError:
            pytest.skip("Socket bind not permitted in this environment")
        server1 = BreakpointServer(manager1, port=requested_port, port_file=port_file)
        thread1 = _start_server(server1)
        server2 = BreakpointServer(manager2, port=requested_port, port_file=port_file2)
        thread2 = _start_server(server2)
        try:
            port1 = _wait_for_port_file(port_file)
            port2 = _wait_for_port_file(port_file2)

            assert port1 == requested_port
            assert port2 != requested_port
            assert port2 > 1024
        finally:
            _stop_server(server1, thread1)
            _stop_server(server2, thread2)
