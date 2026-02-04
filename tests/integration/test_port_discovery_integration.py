"""Integration tests for port discovery workflow."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import pytest

pytest.importorskip("requests")
import requests


def _read_port(port_file: Path) -> Optional[int]:
    try:
        return int(port_file.read_text())
    except (OSError, ValueError):
        return None


def _wait_for_port_file(port_file: Path, timeout: float = 10.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_file.exists():
            port = _read_port(port_file)
            if port is not None:
                return port
        time.sleep(0.5)
    raise AssertionError("Discovery file not created")


def _wait_for_port_value(port_file: Path, expected: int, timeout: float = 10.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_file.exists():
            port = _read_port(port_file)
            if port is not None and port == expected:
                return port
        time.sleep(0.5)
    raise AssertionError(f"Discovery file did not contain port {expected}")


def _wait_for_port_change(port_file: Path, previous: int, timeout: float = 10.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_file.exists():
            port = _read_port(port_file)
            if port is not None and port != previous:
                return port
        time.sleep(0.5)
    raise AssertionError("Discovery file did not update to a new port")


def test_server_client_discovery_workflow() -> None:
    """Test complete workflow: server starts, client discovers port."""
    repo_root = Path(__file__).resolve().parents[2]
    server_script = repo_root / "run" / "mac" / "breakpoint_server"

    port_file = Path.home() / ".cideldill" / "port"
    if port_file.exists():
        port_file.unlink()

    server_proc = subprocess.Popen(
        [sys.executable, str(server_script), "--port", "5174"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        actual_port = _wait_for_port_file(port_file)
        assert 1024 <= actual_port <= 65535

        response = requests.get(f"http://localhost:{actual_port}/api/breakpoints", timeout=2)
        assert response.status_code == 200

        from cideldill_client.with_debug import _resolve_server_url

        url = _resolve_server_url()
        assert f"localhost:{actual_port}" in url
    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        if port_file.exists():
            port_file.unlink()


def test_server_handles_port_conflict() -> None:
    """Test that server recovers from port conflict."""
    repo_root = Path(__file__).resolve().parents[2]
    server_script = repo_root / "run" / "mac" / "breakpoint_server"
    port_file = Path.home() / ".cideldill" / "port"
    port_file.unlink(missing_ok=True)
    port_dir = port_file.parent
    port_dir.mkdir(parents=True, exist_ok=True)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        if sock.connect_ex(("127.0.0.1", 5174)) == 0:
            pytest.skip("Port 5174 already in use by another process")

    server1 = subprocess.Popen(
        [sys.executable, str(server_script), "--port", "5174"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_for_port_value(port_file, 5174)
        server2 = subprocess.Popen(
            [sys.executable, str(server_script), "--port", "5174"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            port = _wait_for_port_change(port_file, 5174)
            response = requests.get(f"http://localhost:{port}/api/breakpoints", timeout=2)
            assert response.status_code == 200
        finally:
            server2.terminate()
            try:
                server2.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server2.kill()
    finally:
        server1.terminate()
        try:
            server1.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server1.kill()
        port_file = Path.home() / ".cideldill" / "port"
        if port_file.exists():
            port_file.unlink()


@pytest.mark.integration
def test_sequence_demo_uses_discovered_port() -> None:
    """Test that sequence_demo_breakpoints works with port discovery."""
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "run" / "mac" / "sequence_demo_breakpoints"

    proc = subprocess.Popen(
        [
            sys.executable,
            str(script),
            "--iterations",
            "1",
            "--behavior",
            "go",
            "--no-browser",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = proc.communicate(timeout=30)
        assert proc.returncode == 0, f"Script failed: {stderr}"

        output = stdout + stderr
        assert "port" in output.lower()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        port_file = Path.home() / ".cideldill" / "port"
        if port_file.exists():
            port_file.unlink()
