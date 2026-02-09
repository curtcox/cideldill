import dataclasses
import threading
from unittest.mock import AsyncMock

from cideldill_client.exceptions import DebugDeadlockError
from cideldill_client.serialization import CIDCache, Serializer, compute_cid, deserialize, serialize
from cideldill_client.serialization_common import _safe_repr, _safe_str


def test_compute_cid_returns_128_char_hex():
    cid = compute_cid({"a": 1})
    assert len(cid) == 128
    int(cid, 16)


def test_cidcache_mark_and_is_sent():
    cache = CIDCache()
    cid = "a" * 128
    assert cache.is_sent(cid) is False
    cache.mark_sent(cid)
    assert cache.is_sent(cid) is True


def test_serializer_cached_object_excludes_data():
    serializer = Serializer()
    result = serializer.serialize({"hello": "world"})
    assert result.data_base64 is not None

    cached = serializer.serialize({"hello": "world"})
    assert cached.data_base64 is None


def test_serialize_roundtrip():
    payload = {"items": [1, 2, 3]}
    data = serialize(payload)
    assert deserialize(data) == payload


def test_1_simple_async_mock_with_cideldill_serialization():
    """Test 1: Serialize a simple AsyncMock using cideldill's serialization."""
    async_mock = AsyncMock()
    serialize(async_mock)


def test_serializer_allows_reentrant_serialize_in_repr():
    serializer = Serializer()

    class Unpicklable:
        def __getstate__(self):  # Force _safe_dumps to fall back to repr/snapshot
            raise RuntimeError("nope")

        def __repr__(self) -> str:
            serializer.serialize({"ok": True})
            return "Unpicklable()"

    obj = Unpicklable()
    thread = threading.Thread(target=serializer.serialize, args=(obj,), daemon=True)
    thread.start()
    thread.join(1.0)

    assert not thread.is_alive(), "serialize deadlocked on re-entrant __repr__"


def test_serializer_raises_deadlock_error_on_lock_timeout():
    serializer = Serializer(lock_timeout_s=0.01)
    serializer._lock.acquire()
    try:
        errors: list[Exception] = []

        def run() -> None:
            try:
                serializer.serialize({"ok": True})
            except Exception as exc:  # noqa: BLE001 - capture for assertion
                errors.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(1.0)
        assert not thread.is_alive(), "serialize did not return after lock timeout"
        assert errors and isinstance(errors[0], DebugDeadlockError)
    finally:
        serializer._lock.release()


def test_serializer_allows_reentrant_serialize_in_str():
    """Serializing an object whose __str__ re-enters serialize must not deadlock.

    This covers the DebugProxy.__str__ → _intercept_dunder → _wrap_method →
    record_call_start → serialize re-entrancy path.
    """
    serializer = Serializer()

    class UnpicklableWithStr:
        def __getstate__(self):
            raise RuntimeError("nope")

        def __repr__(self) -> str:
            return "UnpicklableWithStr()"

        def __str__(self) -> str:
            # Simulates DebugProxy.__str__ → _intercept_dunder → serialize
            serializer.serialize({"from_str": True})
            return "str-value"

    obj = UnpicklableWithStr()
    thread = threading.Thread(target=serializer.serialize, args=(obj,), daemon=True)
    thread.start()
    thread.join(2.0)

    assert not thread.is_alive(), "serialize deadlocked on re-entrant __str__"


def test_serialize_container_with_nested_proxy_like_object():
    """Serializing a container holding a proxy-like object must not deadlock.

    This reproduces the exact scenario from the deadlock bug report:
    a dataclass container holds an unpicklable proxy-like object whose
    __repr__ or __str__ triggers re-entrant serialization.
    """
    serializer = Serializer()

    class FakeProxy:
        """Simulates a DebugProxy that re-enters serialize on __repr__/__str__."""

        def __init__(self, target: object) -> None:
            self._target = target

        def __getstate__(self):
            raise RuntimeError("DebugProxy cannot be pickled")

        def __repr__(self) -> str:
            # Simulates the old DebugProxy.__repr__ that went through
            # _intercept_dunder → _wrap_method → record_call_start → serialize
            serializer.serialize({"repr_side_effect": True})
            return repr(self._target)

        def __str__(self) -> str:
            serializer.serialize({"str_side_effect": True})
            return str(self._target)

    class Inner:
        def do_work(self) -> int:
            return 42

    @dataclasses.dataclass
    class Container:
        name: str
        tool: object

    proxy = FakeProxy(Inner())
    container = Container(name="test", tool=proxy)

    thread = threading.Thread(
        target=serializer.serialize, args=(container,), daemon=True
    )
    thread.start()
    thread.join(3.0)

    assert not thread.is_alive(), (
        "serialize deadlocked when container holds a proxy-like object"
    )


def test_safe_repr_does_not_trigger_debug_proxy_side_effects():
    """_safe_repr should not trigger side effects on DebugProxy-like objects.

    When _safe_repr encounters a DebugProxy, it should get the repr without
    going through _intercept_dunder, which would trigger record_call_start.
    """
    side_effects: list[str] = []

    class SideEffectRepr:
        def __repr__(self) -> str:
            side_effects.append("repr_called")
            return "SideEffectRepr()"

    obj = SideEffectRepr()
    result = _safe_repr(obj)

    # repr should be called once and return the expected string
    assert result == "SideEffectRepr()"
    assert len(side_effects) == 1


def test_safe_str_does_not_trigger_debug_proxy_side_effects():
    """_safe_str should not trigger side effects on DebugProxy-like objects.

    When _safe_str encounters a DebugProxy, it should get the str without
    going through _intercept_dunder, which would trigger record_call_start.
    """
    side_effects: list[str] = []

    class SideEffectStr:
        def __repr__(self) -> str:
            return "SideEffectStr()"

        def __str__(self) -> str:
            side_effects.append("str_called")
            return "str-value"

    obj = SideEffectStr()
    result = _safe_str(obj, "SideEffectStr()")

    assert result == "str-value"
    assert len(side_effects) == 1
