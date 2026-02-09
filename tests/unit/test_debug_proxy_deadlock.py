"""Tests for the DebugProxy serializer deadlock bug.

Verifies that:
1. DebugProxy.__repr__ does not trigger _intercept_dunder (no record_call_start).
2. DebugProxy.__str__ does not trigger _intercept_dunder (no record_call_start).
3. Serializing a container holding a DebugProxy does not deadlock.
4. Serializing a DebugProxy directly does not deadlock.

See: todo/deadlock_bug_report.md
"""

from __future__ import annotations

import dataclasses
import threading

pytest = __import__("pytest")
pytest.importorskip("dill")
pytest.importorskip("requests")

from cideldill_client.debug_proxy import DebugProxy
from cideldill_client.serialization import Serializer


class _TrackingClient:
    """Stub client that tracks record_call_start invocations."""

    def __init__(self) -> None:
        self.call_start_count = 0
        self.call_start_names: list[str] = []
        self.completed: list[dict] = []

    def record_call_start(self, **kwargs) -> dict:
        self.call_start_count += 1
        self.call_start_names.append(kwargs.get("method_name", ""))
        return {"call_id": str(self.call_start_count), "action": "continue"}

    def record_call_complete(self, **kwargs) -> None:
        self.completed.append(kwargs)


class _SimpleTarget:
    """A simple target object for DebugProxy wrapping."""

    def __repr__(self) -> str:
        return "SimpleTarget()"

    def __str__(self) -> str:
        return "simple-target"

    def do_work(self) -> int:
        return 42


class _UnpicklableTarget:
    """A target that cannot be pickled, forcing _build_snapshot fallback."""

    def __getstate__(self):
        raise RuntimeError("cannot pickle")

    def __repr__(self) -> str:
        return "UnpicklableTarget()"

    def __str__(self) -> str:
        return "unpicklable-target"

    def do_work(self) -> int:
        return 42


def test_debug_proxy_repr_does_not_call_record_call_start():
    """DebugProxy.__repr__ must delegate directly to target without interception.

    If __repr__ goes through _intercept_dunder → _wrap_method →
    record_call_start, then serializing the proxy would trigger debug recording
    as a side effect, and could deadlock if the serializer lock is held.
    """
    client = _TrackingClient()
    proxy = DebugProxy(_SimpleTarget(), client, lambda: True)

    result = repr(proxy)

    assert result == "SimpleTarget()"
    assert client.call_start_count == 0, (
        f"__repr__ triggered record_call_start {client.call_start_count} times; "
        f"methods: {client.call_start_names}"
    )


def test_debug_proxy_str_does_not_call_record_call_start():
    """DebugProxy.__str__ must delegate directly to target without interception.

    Same rationale as __repr__: str() is called during serialization (_safe_str)
    and must not trigger record_call_start, which would re-enter the serializer.
    """
    client = _TrackingClient()
    proxy = DebugProxy(_SimpleTarget(), client, lambda: True)

    result = str(proxy)

    assert result == "simple-target"
    assert client.call_start_count == 0, (
        f"__str__ triggered record_call_start {client.call_start_count} times; "
        f"methods: {client.call_start_names}"
    )


def test_serialize_debug_proxy_does_not_deadlock():
    """Serializing a DebugProxy directly must not deadlock.

    The serializer calls _safe_repr and _safe_str on unpicklable objects.
    If those trigger _intercept_dunder on the proxy, re-entrant serialize
    calls would deadlock with a non-reentrant Lock.
    """
    serializer = Serializer()
    client = _TrackingClient()
    proxy = DebugProxy(_UnpicklableTarget(), client, lambda: True)

    thread = threading.Thread(target=serializer.serialize, args=(proxy,), daemon=True)
    thread.start()
    thread.join(3.0)

    assert not thread.is_alive(), "serialize deadlocked on DebugProxy"
    assert client.call_start_count == 0, (
        f"Serializing DebugProxy triggered record_call_start "
        f"{client.call_start_count} times; methods: {client.call_start_names}"
    )


def test_serialize_container_with_debug_proxy_does_not_deadlock():
    """Serializing a container holding a DebugProxy must not deadlock.

    This is the exact scenario from the deadlock bug report: a dataclass
    container holds a DebugProxy as a field. Serializing the container
    encounters the proxy during snapshot building, calls repr/str on it,
    which must not trigger record_call_start.
    """
    serializer = Serializer()
    client = _TrackingClient()
    proxy = DebugProxy(_UnpicklableTarget(), client, lambda: True)

    @dataclasses.dataclass
    class Container:
        name: str
        tool: object

    container = Container(name="test", tool=proxy)

    thread = threading.Thread(
        target=serializer.serialize, args=(container,), daemon=True
    )
    thread.start()
    thread.join(3.0)

    assert not thread.is_alive(), (
        "serialize deadlocked on container holding DebugProxy"
    )
    assert client.call_start_count == 0, (
        f"Serializing container with DebugProxy triggered record_call_start "
        f"{client.call_start_count} times; methods: {client.call_start_names}"
    )
