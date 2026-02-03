"""Tests for client port discovery."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cideldill_client import configure_debug
from cideldill_client import with_debug as with_debug_module
from cideldill_client.with_debug import _resolve_server_url


def _reset_state() -> None:
    with_debug_module._state.server_url = None
    with_debug_module._state.enabled = False


def test_resolve_server_url_uses_env_variable_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that CIDELDILL_SERVER_URL takes precedence."""
    _reset_state()
    monkeypatch.setenv("CIDELDILL_SERVER_URL", "http://localhost:8080")

    url = _resolve_server_url()
    assert url == "http://localhost:8080"


def test_resolve_server_url_reads_discovery_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that server URL is read from discovery file."""
    _reset_state()
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        port_file.write_text("5175")

        monkeypatch.delenv("CIDELDILL_SERVER_URL", raising=False)
        monkeypatch.setattr(
            "cideldill_client.port_discovery.get_discovery_file_path",
            lambda: port_file,
        )

        url = _resolve_server_url()
        assert url == "http://localhost:5175"


def test_resolve_server_url_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that default URL is used if no env or discovery file."""
    _reset_state()
    monkeypatch.delenv("CIDELDILL_SERVER_URL", raising=False)
    monkeypatch.setattr(
        "cideldill_client.port_discovery.get_discovery_file_path",
        lambda: Path("/nonexistent/port"),
    )

    url = _resolve_server_url()
    assert url == "http://localhost:5174"


def test_resolve_server_url_ignores_invalid_discovery_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that invalid discovery file is ignored."""
    _reset_state()
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        port_file.write_text("invalid")

        monkeypatch.delenv("CIDELDILL_SERVER_URL", raising=False)
        monkeypatch.setattr(
            "cideldill_client.port_discovery.get_discovery_file_path",
            lambda: port_file,
        )

        url = _resolve_server_url()
        assert url == "http://localhost:5174"


def test_configured_server_url_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that configure_debug() takes precedence over discovery file."""
    _reset_state()
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        port_file.write_text("5175")

        monkeypatch.setattr(
            "cideldill_client.port_discovery.get_discovery_file_path",
            lambda: port_file,
        )

        configure_debug(server_url="http://localhost:9999")
        url = _resolve_server_url()
        assert url == "http://localhost:9999"

    configure_debug(server_url=None)
    _reset_state()
