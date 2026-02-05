"""Tests for custom pickle protocols."""

from __future__ import annotations

import dill
import pytest

from cideldill_client.custom_picklers import (
    PickleRegistry,
    _reconstruct_from_dict,
    _reconstruct_from_slots,
    _reconstruct_placeholder,
    _reconstruct_with_setstate,
    auto_register_for_pickling,
)


class SimpleClass:
    """Simple class with __dict__."""

    def __init__(self, name: str, value: int):
        self.name = name
        self.value = value


class SlotsClass:
    """Class using __slots__."""

    __slots__ = ["x", "y", "z"]

    def __init__(self, x: int, y: int, z: int):
        self.x = x
        self.y = y
        self.z = z


class GetStateClass:
    """Class with __getstate__ and __setstate__."""

    def __init__(self, data: dict):
        self._data = data

    def __getstate__(self):
        return {"data": self._data}

    def __setstate__(self, state):
        self._data = state["data"]


class NestedSlotsClass(SlotsClass):
    """Class with inherited slots."""

    __slots__ = ["w"]

    def __init__(self, x: int, y: int, z: int, w: int):
        super().__init__(x, y, z)
        self.w = w


class ComplexClass:
    """Class with mixed state."""

    __slots__ = ["_private", "__dict__"]

    def __init__(self, public_val: int, private_val: str):
        self.public_val = public_val
        self._private = private_val


class UnpicklableClass:
    """Class that raises during default pickling."""

    def __init__(self, name: str):
        self.name = name

    def __reduce_ex__(self, protocol):
        raise TypeError("Not picklable by default")


# Test fixtures

@pytest.fixture(autouse=True)
def _clear_registry():
    PickleRegistry.clear()
    for klass in [
        SimpleClass,
        SlotsClass,
        GetStateClass,
        NestedSlotsClass,
        ComplexClass,
        UnpicklableClass,
    ]:
        dill.Pickler.dispatch.pop(klass, None)
    yield
    PickleRegistry.clear()
    for klass in [
        SimpleClass,
        SlotsClass,
        GetStateClass,
        NestedSlotsClass,
        ComplexClass,
        UnpicklableClass,
    ]:
        dill.Pickler.dispatch.pop(klass, None)


# Reconstruction functions

def test_reconstruct_with_setstate():
    obj = GetStateClass({"key": "value", "num": 42})
    state = obj.__getstate__()

    reconstructed = _reconstruct_with_setstate(GetStateClass, state)
    assert reconstructed._data == {"key": "value", "num": 42}


def test_reconstruct_from_slots():
    state = {"x": 1, "y": 2, "z": 3}

    reconstructed = _reconstruct_from_slots(SlotsClass, state)
    assert reconstructed.x == 1
    assert reconstructed.y == 2
    assert reconstructed.z == 3


def test_reconstruct_from_slots_with_inheritance():
    state = {"x": 1, "y": 2, "z": 3, "w": 4}

    reconstructed = _reconstruct_from_slots(NestedSlotsClass, state)
    assert reconstructed.x == 1
    assert reconstructed.y == 2
    assert reconstructed.z == 3
    assert reconstructed.w == 4


def test_reconstruct_from_dict():
    init_args = {"name": "test", "value": 42}
    state = {}

    reconstructed = _reconstruct_from_dict(SimpleClass, init_args, state)
    assert reconstructed.name == "test"
    assert reconstructed.value == 42


def test_reconstruct_from_dict_with_additional_state():
    init_args = {"name": "test", "value": 42}
    state = {"extra_attr": "extra_value"}

    reconstructed = _reconstruct_from_dict(SimpleClass, init_args, state)
    assert reconstructed.name == "test"
    assert reconstructed.value == 42
    assert reconstructed.extra_attr == "extra_value"


def test_reconstruct_placeholder():
    info = {
        "type_name": "SimpleClass",
        "repr": "<SimpleClass object>",
        "module": "test_custom_picklers",
        "qualname": "SimpleClass",
        "object_name": "simple_tool",
        "object_path": "test_custom_picklers.SimpleClass",
    }

    placeholder = _reconstruct_placeholder(info)
    assert "Unpicklable" in repr(placeholder)
    assert "SimpleClass" in repr(placeholder)
    assert placeholder.object_name == "simple_tool"
    assert placeholder.object_path == "test_custom_picklers.SimpleClass"


# PickleRegistry

def test_pickle_registry_register_simple_class():
    PickleRegistry.register(SimpleClass)

    obj = SimpleClass("test", 99)
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)

    assert restored.name == "test"
    assert restored.value == 99


def test_pickle_registry_register_slots_class():
    PickleRegistry.register(SlotsClass)

    obj = SlotsClass(1, 2, 3)
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)

    assert restored.x == 1
    assert restored.y == 2
    assert restored.z == 3


def test_pickle_registry_register_getstate_class():
    PickleRegistry.register(GetStateClass)

    obj = GetStateClass({"test": "data"})
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)

    assert restored._data == {"test": "data"}


def test_pickle_registry_custom_reducer():
    def custom_reducer(obj):
        return (lambda name: SimpleClass(name, 0), (obj.name,))

    PickleRegistry.register(SimpleClass, custom_reducer)

    obj = SimpleClass("custom", 999)
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)

    assert restored.name == "custom"
    assert restored.value == 0


def test_pickle_registry_caches_reducers():
    PickleRegistry.register(SimpleClass)

    assert SimpleClass in PickleRegistry._reducers

    reducer1 = PickleRegistry._reducers[SimpleClass]
    PickleRegistry.register(SimpleClass)
    reducer2 = PickleRegistry._reducers[SimpleClass]

    assert reducer1 is reducer2


def test_pickle_registry_handles_nested_slots():
    PickleRegistry.register(NestedSlotsClass)

    obj = NestedSlotsClass(1, 2, 3, 4)
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)

    assert restored.x == 1
    assert restored.y == 2
    assert restored.z == 3
    assert restored.w == 4


def test_pickle_registry_handles_mixed_state():
    PickleRegistry.register(ComplexClass)

    obj = ComplexClass(100, "secret")
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)

    assert restored.public_val == 100
    assert restored._private == "secret"


# auto_register_for_pickling

def test_auto_register_returns_true_if_already_picklable():
    obj = SimpleClass("test", 42)

    assert auto_register_for_pickling(obj) is True


def test_auto_register_handles_unpicklable_class():
    obj = UnpicklableClass("test")

    result = auto_register_for_pickling(obj)
    assert result is True

    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)
    assert restored.name == "test"


def test_auto_register_caches_type():
    obj1 = UnpicklableClass("obj1")
    obj2 = UnpicklableClass("obj2")

    auto_register_for_pickling(obj1)

    assert UnpicklableClass in PickleRegistry._reducers
    assert auto_register_for_pickling(obj2) is True


def test_auto_register_returns_false_on_failure(monkeypatch):
    obj = UnpicklableClass("obj")

    def boom(*args, **kwargs):
        raise RuntimeError("register failed")

    monkeypatch.setattr(PickleRegistry, "register", boom)

    result = auto_register_for_pickling(obj)
    assert result is False


def test_auto_register_logs_success(caplog):
    import logging

    from cideldill_client.custom_picklers import set_verbose_serialization_warnings

    caplog.set_level(logging.DEBUG)

    obj = UnpicklableClass("test")
    set_verbose_serialization_warnings(True)
    try:
        auto_register_for_pickling(obj)
    finally:
        set_verbose_serialization_warnings(False)

    assert "Auto-registered custom pickler" in caplog.text
    assert "UnpicklableClass" in caplog.text


def test_auto_register_logs_failure(caplog, monkeypatch):
    import logging

    from cideldill_client.custom_picklers import set_verbose_serialization_warnings

    caplog.set_level(logging.DEBUG)

    def boom(*args, **kwargs):
        raise RuntimeError("register failed")

    monkeypatch.setattr(PickleRegistry, "register", boom)

    obj = UnpicklableClass("test")
    set_verbose_serialization_warnings(True)
    try:
        auto_register_for_pickling(obj)
    finally:
        set_verbose_serialization_warnings(False)

    assert "Failed to auto-register custom pickler" in caplog.text


# Introspection strategies

def test_create_auto_reducer_prefers_getstate():
    reducer = PickleRegistry._create_auto_reducer(GetStateClass)

    obj = GetStateClass({"test": "data"})
    reconstructor, args = reducer(obj)

    assert reconstructor is _reconstruct_with_setstate


def test_create_auto_reducer_uses_slots():
    reducer = PickleRegistry._create_auto_reducer(SlotsClass)

    obj = SlotsClass(1, 2, 3)
    reduced = reducer(obj)
    reconstructor, args = reduced[0], reduced[1]

    assert reconstructor is _reconstruct_from_slots


def test_create_auto_reducer_uses_dict():
    reducer = PickleRegistry._create_auto_reducer(SimpleClass)

    obj = SimpleClass("test", 42)
    reduced = reducer(obj)
    reconstructor, args = reduced[0], reduced[1]

    assert reconstructor is _reconstruct_from_dict


# Edge cases

def test_handles_objects_without_init_params():
    class WeirdClass:
        def __init__(self):
            pass

        def set_state(self, value):
            self.value = value

    PickleRegistry.register(WeirdClass)

    obj = WeirdClass()
    obj.set_state(42)

    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)

    assert restored.value == 42


def test_handles_properties():
    class PropertyClass:
        def __init__(self, value):
            self._value = value

        @property
        def value(self):
            return self._value

    PickleRegistry.register(PropertyClass)

    obj = PropertyClass(42)
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)

    assert restored.value == 42


def test_handles_circular_references():
    class Node:
        def __init__(self, value):
            self.value = value
            self.next = None

    PickleRegistry.register(Node)

    node1 = Node(1)
    node2 = Node(2)
    node1.next = node2
    node2.next = node1

    pickled = dill.dumps(node1)
    restored = dill.loads(pickled)

    assert restored.value == 1
    assert restored.next.value == 2
    assert restored.next.next.value == 1


def test_handles_empty_objects():
    class EmptyClass:
        pass

    PickleRegistry.register(EmptyClass)

    obj = EmptyClass()
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)

    assert isinstance(restored, EmptyClass)
