"""Unit tests for with_debug API."""

import pytest

pytest.importorskip("requests")

from cideldill.debug_proxy import AsyncDebugProxy, DebugProxy
from cideldill.with_debug import configure_debug, with_debug


class Sample:
    def add(self, x: int, y: int) -> int:
        return x + y


class AsyncCallable:
    async def __call__(self) -> str:
        return "ok"


def test_with_debug_off_returns_info() -> None:
    info = with_debug("OFF")
    assert info.is_enabled() is False
    assert info.connection_status() == "disabled"


def test_with_debug_returns_original_when_off() -> None:
    """When debug is OFF, with_debug(obj) returns the original object unchanged (NOP)."""
    with_debug("OFF")
    
    target = Sample()
    result = with_debug(target)
    
    # Should return the exact same object (true NOP)
    assert result is target
    assert type(result) is Sample
    assert not isinstance(result, DebugProxy)


def test_with_debug_off_allows_any_object_including_strings() -> None:
    """When debug is OFF, any object (including non-command strings) is returned as-is."""
    with_debug("OFF")
    
    # With debug OFF, non-command strings are just returned as-is
    result = with_debug("maybe")
    assert result == "maybe"


def test_with_debug_invalid_string_raises_when_on(monkeypatch) -> None:
    """Invalid command strings should raise ValueError when debug is ON."""
    def noop_check(self) -> None:
        return None

    monkeypatch.setattr("cideldill.debug_client.DebugClient.check_connection", noop_check)
    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")
    
    # With debug ON, non-command strings should raise
    with pytest.raises(ValueError, match="with_debug expects"):
        with_debug("maybe")


def test_with_debug_wraps_object_when_on(monkeypatch) -> None:
    """When debug is ON, with_debug(obj) returns a DebugProxy."""
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


def test_with_debug_registers_callable_for_breakpoints(monkeypatch) -> None:
    """Calling with_debug(callable) should register it for breakpoint UI/discovery."""

    def noop_check(self) -> None:
        return None

    register_calls: list[str] = []

    def record_register(self, function_name: str) -> None:
        register_calls.append(function_name)

    monkeypatch.setattr("cideldill.debug_client.DebugClient.check_connection", noop_check)
    monkeypatch.setattr(
        "cideldill.debug_client.DebugClient.register_function",
        record_register,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    def my_breakpoint_target() -> int:
        return 123

    _wrapped = with_debug(my_breakpoint_target)

    assert "my_breakpoint_target" in register_calls


def test_with_debug_nop_preserves_identity_when_off() -> None:
    """obj = with_debug(obj) is a true NOP when debug is OFF."""
    with_debug("OFF")
    
    original = Sample()
    original_id = id(original)
    
    # This should be a no-op
    original = with_debug(original)
    
    # Identity should be preserved
    assert id(original) == original_id
    assert isinstance(original, Sample)
    assert not isinstance(original, DebugProxy)


def test_with_debug_nop_zero_overhead_when_off() -> None:
    """When debug is OFF, with_debug(obj) has zero overhead."""
    with_debug("OFF")
    
    # Test with various types
    obj1 = Sample()
    obj2 = [1, 2, 3]
    obj3 = {"key": "value"}
    
    # All should return original objects
    assert with_debug(obj1) is obj1
    assert with_debug(obj2) is obj2
    assert with_debug(obj3) is obj3


def test_with_debug_async_callable_uses_async_proxy(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    monkeypatch.setattr("cideldill.debug_client.DebugClient.check_connection", noop_check)
    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    proxy = with_debug(AsyncCallable())
    assert isinstance(proxy, AsyncDebugProxy)


def test_with_debug_async_callable_returns_original_when_off() -> None:
    """When debug is OFF, async callables are also returned unchanged."""
    with_debug("OFF")
    
    target = AsyncCallable()
    result = with_debug(target)
    
    assert result is target
    assert not isinstance(result, AsyncDebugProxy)
