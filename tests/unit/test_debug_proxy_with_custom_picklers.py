"""Tests for debug proxy integration with custom picklers."""

from cideldill_client.debug_proxy import DebugProxy


class UnpicklableTarget:
    """Target class that isn't normally picklable."""

    _instances = []

    def __init__(self, name: str):
        self.name = name
        self._instances.append(self)

    def __reduce_ex__(self, protocol):
        raise TypeError("Not picklable by default")

    def get_name(self) -> str:
        return self.name

    def double_value(self, x: int) -> int:
        return x * 2


class StubClient:
    """Stub client for testing."""

    def __init__(self):
        self.recorded_calls = []

    def record_call_start(self, **kwargs):
        self.recorded_calls.append(kwargs)
        return {"call_id": "test-123", "action": "continue"}

    def record_call_complete(self, **kwargs):
        return None


def test_debug_proxy_wraps_unpicklable_object():
    target = UnpicklableTarget("test")
    client = StubClient()

    proxy = DebugProxy(target, client, lambda: True)

    assert hasattr(proxy, "cid")
    assert len(proxy.cid) == 64


def test_debug_proxy_methods_work_on_unpicklable():
    target = UnpicklableTarget("test")
    client = StubClient()
    proxy = DebugProxy(target, client, lambda: True)

    result = proxy.get_name()
    assert result == "test"

    result = proxy.double_value(5)
    assert result == 10


def test_debug_proxy_records_calls_with_unpicklable():
    target = UnpicklableTarget("test")
    client = StubClient()
    proxy = DebugProxy(target, client, lambda: True)

    proxy.get_name()

    assert len(client.recorded_calls) == 1
    call = client.recorded_calls[0]
    assert call["method_name"] == "get_name"
    assert call["target_cid"] is not None


def test_debug_proxy_serializes_unpicklable_args():
    class UnpicklableArg:
        def __init__(self, value):
            self.value = value

        def __reduce_ex__(self, protocol):
            raise TypeError("Not picklable by default")

    target = UnpicklableTarget("test")
    client = StubClient()
    proxy = DebugProxy(target, client, lambda: True)

    def method_with_unpicklable_arg(self, arg):
        return arg.value

    target.custom_method = method_with_unpicklable_arg.__get__(target)

    arg = UnpicklableArg(42)

    result = proxy.custom_method(arg)
    assert result == 42


def test_proxy_cid_stable_across_calls():
    target = UnpicklableTarget("test")
    client = StubClient()
    proxy = DebugProxy(target, client, lambda: True)

    cid1 = proxy.cid
    proxy.get_name()
    cid2 = proxy.cid
    proxy.double_value(5)
    cid3 = proxy.cid

    assert cid1 == cid2 == cid3
