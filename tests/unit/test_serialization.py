import threading
from unittest.mock import AsyncMock

from cideldill_client.exceptions import DebugDeadlockError
from cideldill_client.serialization import CIDCache, Serializer, compute_cid, deserialize, serialize


def test_compute_cid_returns_64_char_hex():
    cid = compute_cid({"a": 1})
    assert len(cid) == 64
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
