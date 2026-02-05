"""Tests for with_debug object wrapping behavior."""

from __future__ import annotations

import pytest
import requests

pytest.importorskip("requests")

from cideldill_client.with_debug import configure_debug, with_debug


class MockObject:
    """Mock object with attributes and methods to test wrapping."""

    def __init__(self, name: str, value: int) -> None:
        self.name = name
        self.value = value
        self.config = {"setting": "test", "enabled": True}

    def get_value(self) -> int:
        """Method that should be callable on wrapped object."""
        return self.value

    def process(self, x: int) -> int:
        """Method with parameters."""
        return self.value + x


@pytest.fixture()
def debug_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable debug mode while stubbing out server calls."""

    def noop_check(self) -> None:
        return None

    def record_call_start(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return {"action": "continue", "call_id": "1"}

    def record_call_complete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None

    def post_ok(self, path, payload):  # type: ignore[no-untyped-def]
        return {"status": "ok"}

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_start",
        record_call_start,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_complete",
        record_call_complete,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._post_json",
        post_ok,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")
    yield
    with_debug("OFF")


def test_with_debug_without_name_returns_compatible_wrapper(debug_enabled: None) -> None:
    """with_debug(obj) returns a compatible wrapped object."""
    original = MockObject("test", 42)

    wrapped = with_debug(original)

    assert wrapped is not None
    assert wrapped is not original
    assert hasattr(wrapped, "config")
    assert wrapped.config == {"setting": "test", "enabled": True}
    assert wrapped.get_value() == 42
    assert wrapped.process(10) == 52


def test_with_debug_with_name_returns_compatible_wrapper(debug_enabled: None) -> None:
    """with_debug((name, obj)) returns a compatible wrapped object."""
    original = MockObject("test", 42)

    wrapped = with_debug(("named_object", original))

    assert not isinstance(wrapped, tuple)
    assert hasattr(wrapped, "config")
    assert wrapped.config == {"setting": "test", "enabled": True}
    assert wrapped.get_value() == 42
    assert wrapped.process(10) == 52


def test_with_debug_preserves_type_compatibility(debug_enabled: None) -> None:
    """Wrapped objects should work where original types are expected."""

    def function_expecting_mock(obj: MockObject) -> int:
        return obj.value + len(obj.config)

    original = MockObject("test", 42)
    wrapped = with_debug(("typed_object", original))

    assert function_expecting_mock(wrapped) == 44
