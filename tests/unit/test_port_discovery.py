"""Tests for port discovery functionality."""

from __future__ import annotations

import socket
import tempfile
from pathlib import Path

import pytest

from cideldill_server.port_discovery import (
    find_free_port,
    get_discovery_file_path,
    read_port_file,
    write_port_file,
)


def test_find_free_port_returns_valid_port() -> None:
    """Test that find_free_port returns a port in valid range."""
    try:
        port = find_free_port()
    except PermissionError:
        pytest.skip("Socket bind not permitted in this environment")
    assert 1024 <= port <= 65535


def test_find_free_port_is_actually_free() -> None:
    """Test that the port returned is actually available."""
    try:
        port = find_free_port()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))
    except PermissionError:
        pytest.skip("Socket bind not permitted in this environment")


def test_write_port_file_creates_directory() -> None:
    """Test that write_port_file creates parent directory if needed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "subdir" / "port"
        write_port_file(5174, port_file)

        assert port_file.exists()
        assert port_file.read_text() == "5174"


def test_write_port_file_overwrites_existing() -> None:
    """Test that write_port_file overwrites existing file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"

        write_port_file(5174, port_file)
        assert port_file.read_text() == "5174"

        write_port_file(5175, port_file)
        assert port_file.read_text() == "5175"


def test_read_port_file_returns_port() -> None:
    """Test that read_port_file returns the port number."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        port_file.write_text("5174")

        port = read_port_file(port_file)
        assert port == 5174


def test_read_port_file_returns_none_if_missing() -> None:
    """Test that read_port_file returns None if file doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "nonexistent"
        port = read_port_file(port_file)
        assert port is None


def test_read_port_file_returns_none_if_invalid() -> None:
    """Test that read_port_file returns None if file contains invalid data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"

        port_file.write_text("not_a_number")
        assert read_port_file(port_file) is None

        port_file.write_text("99999")
        assert read_port_file(port_file) is None


def test_get_discovery_file_path_uses_env_override(tmp_path: Path, monkeypatch) -> None:
    """Test that discovery file path honors environment overrides."""
    port_file = tmp_path / "override" / "port"
    monkeypatch.setenv("CIDELDILL_PORT_FILE", str(port_file))
    path = get_discovery_file_path()
    assert path == port_file
    monkeypatch.delenv("CIDELDILL_PORT_FILE", raising=False)

    monkeypatch.setenv("CIDELDILL_HOME", str(tmp_path))
    path = get_discovery_file_path()
    assert path == tmp_path / "port"
    monkeypatch.delenv("CIDELDILL_HOME", raising=False)
