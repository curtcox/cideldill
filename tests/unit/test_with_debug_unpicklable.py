"""Tests for with_debug integration with unpicklable objects."""

from cideldill_client import configure_debug, with_debug
from cideldill_client.debug_proxy import DebugProxy


class NATLikeUnpicklable:
    """Simulates NAT's OutputArgsSchema-like unpicklable class."""

    _type_registry = {}

    def __init__(self, schema_name: str):
        self.schema_name = schema_name
        self._type_registry[schema_name] = self

    def __reduce_ex__(self, protocol):
        raise TypeError("Not picklable by default")

    def validate(self, data):
        return True

    def transform(self, value):
        return value * 2


def test_with_debug_wraps_unpicklable_object(monkeypatch):
    def noop_check(self):
        pass

    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.check_connection",
        noop_check,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    obj = NATLikeUnpicklable("test_schema")

    wrapped = with_debug(obj)

    assert isinstance(wrapped, DebugProxy)
    assert wrapped.schema_name == "test_schema"


def test_wrapped_unpicklable_methods_work(monkeypatch):
    def noop_check(self):
        pass

    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.check_connection",
        noop_check,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    obj = NATLikeUnpicklable("test_schema")
    wrapped = with_debug(obj)

    assert wrapped.validate({"data": "test"}) is True
    assert wrapped.transform(5) == 10


def test_with_debug_off_returns_unpicklable_unchanged():
    with_debug("OFF")

    obj = NATLikeUnpicklable("test_schema")
    result = with_debug(obj)

    assert result is obj
    assert not isinstance(result, DebugProxy)


def test_multiple_unpicklable_objects_work(monkeypatch):
    def noop_check(self):
        pass

    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.check_connection",
        noop_check,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    obj1 = NATLikeUnpicklable("schema1")
    obj2 = NATLikeUnpicklable("schema2")
    obj3 = NATLikeUnpicklable("schema3")

    wrapped1 = with_debug(obj1)
    wrapped2 = with_debug(obj2)
    wrapped3 = with_debug(obj3)

    assert isinstance(wrapped1, DebugProxy)
    assert isinstance(wrapped2, DebugProxy)
    assert isinstance(wrapped3, DebugProxy)

    assert wrapped1.cid != wrapped2.cid
    assert wrapped2.cid != wrapped3.cid
    assert wrapped1.cid != wrapped3.cid
