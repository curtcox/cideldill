"""Unit tests for with_debug API."""

import pytest

pytest.importorskip("requests")

from cideldill.debug_proxy import DebugProxy
from cideldill.with_debug import configure_debug, with_debug


class Sample:
    def add(self, x: int, y: int) -> int:
        return x + y


def test_with_debug_off_returns_info() -> None:
    info = with_debug("OFF")
    assert info.is_enabled() is False
    assert info.connection_status() == "disabled"


def test_with_debug_invalid_raises() -> None:
    with pytest.raises(ValueError):
        with_debug("maybe")


def test_with_debug_wraps_object(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    monkeypatch.setattr("cideldill.debug_client.DebugClient.check_connection", noop_check)
    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    target = Sample()
    proxy = with_debug(target)
    assert isinstance(proxy, DebugProxy)
    assert proxy is not target
    assert proxy == proxy
