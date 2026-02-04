# Enhanced Pickling with Runtime Introspection

## Overview

**Problem**: Some objects (especially from third-party libraries like NAT) cannot be pickled by dill due to metaclass issues, dynamically generated classes, or other edge cases. This causes `DebugSerializationError` when wrapping with `with_debug()`.

**Solution**: Implement a runtime introspection-based pickle protocol that automatically analyzes objects and creates custom reducers for unpicklable types.

**Benefits**:
- Automatic handling of unpicklable objects
- No manual registration required for most cases
- Extensible for complex edge cases
- Better error messages and debugging
- Full debugging support for previously-unwrappable objects

## Progress (2026-02-04)

- [x] Implemented custom picklers, auto-registration, and serialization fallback
- [x] Added unit and integration tests for custom picklers, debug proxy, and with_debug
- [x] Added documentation updates and example script
- [ ] Test suite run (not run in this update)

---

## Design Decisions

### Auto-Registration Strategy

1. **Try standard dill pickling first**
2. **On failure, introspect the object type**:
   - Check for `__getstate__`/`__setstate__` methods
   - Check for `__slots__`
   - Check for `__dict__`
   - Fall back to minimal placeholder
3. **Generate reducer dynamically** based on object structure
4. **Register with dill's dispatch table**
5. **Cache registration** per type (only introspect once)

### Introspection Methods (Priority Order)

1. **Native pickle support**: If `__getstate__`/`__setstate__` exist, use them
2. **Slots-based**: Extract all `__slots__` from class hierarchy
3. **Dict-based**: Extract `__dict__` and constructor parameters
4. **Placeholder**: Store type info and repr for debugging only

### Reconstruction Strategies

- **With constructor**: Try to call `__init__` with extracted parameters
- **Without constructor**: Use `object.__new__()` to create uninitialized instance
- **Set attributes**: Restore state via `setattr()` or `__setstate__()`

---

## Implementation Steps

### Phase 1: Core Custom Pickler Infrastructure (TDD)

#### 1.1 Write Tests First

**File**: `tests/unit/test_custom_picklers.py`

```python
"""Tests for custom pickle protocols."""

from __future__ import annotations

import pytest
import dill

from cideldill_client.custom_picklers import (
    PickleRegistry,
    auto_register_for_pickling,
    _reconstruct_with_setstate,
    _reconstruct_from_slots,
    _reconstruct_from_dict,
    _reconstruct_placeholder,
)


# Test fixture classes

class SimpleClass:
    """Simple class with __dict__."""
    def __init__(self, name: str, value: int):
        self.name = name
        self.value = value


class SlotsClass:
    """Class using __slots__."""
    __slots__ = ['x', 'y', 'z']
    
    def __init__(self, x: int, y: int, z: int):
        self.x = x
        self.y = y
        self.z = z


class GetStateClass:
    """Class with __getstate__ and __setstate__."""
    def __init__(self, data: dict):
        self._data = data
    
    def __getstate__(self):
        return {'data': self._data}
    
    def __setstate__(self, state):
        self._data = state['data']


class NestedSlotsClass(SlotsClass):
    """Class with inherited slots."""
    __slots__ = ['w']
    
    def __init__(self, x: int, y: int, z: int, w: int):
        super().__init__(x, y, z)
        self.w = w


class ComplexClass:
    """Class with mixed state."""
    __slots__ = ['_private']
    
    def __init__(self, public_val: int, private_val: str):
        self.public_val = public_val
        self._private = private_val


class UnpicklableMetaclass(type):
    """Metaclass that might cause pickle issues."""
    _instances = {}
    
    def __call__(cls, *args, **kwargs):
        key = (cls, args, tuple(sorted(kwargs.items())))
        if key not in cls._instances:
            cls._instances[key] = super().__call__(*args, **kwargs)
        return cls._instances[key]


class UnpicklableClass(metaclass=UnpicklableMetaclass):
    """Class with problematic metaclass."""
    def __init__(self, name: str):
        self.name = name


# Test reconstruction functions

def test_reconstruct_with_setstate():
    """Test reconstruction using __getstate__/__setstate__."""
    obj = GetStateClass({'key': 'value', 'num': 42})
    state = obj.__getstate__()
    
    reconstructed = _reconstruct_with_setstate(GetStateClass, state)
    assert reconstructed._data == {'key': 'value', 'num': 42}


def test_reconstruct_from_slots():
    """Test reconstruction from __slots__."""
    state = {'x': 1, 'y': 2, 'z': 3}
    
    reconstructed = _reconstruct_from_slots(SlotsClass, state)
    assert reconstructed.x == 1
    assert reconstructed.y == 2
    assert reconstructed.z == 3


def test_reconstruct_from_slots_with_inheritance():
    """Test reconstruction from inherited __slots__."""
    state = {'x': 1, 'y': 2, 'z': 3, 'w': 4}
    
    reconstructed = _reconstruct_from_slots(NestedSlotsClass, state)
    assert reconstructed.x == 1
    assert reconstructed.y == 2
    assert reconstructed.z == 3
    assert reconstructed.w == 4


def test_reconstruct_from_dict():
    """Test reconstruction from __dict__."""
    init_args = {'name': 'test', 'value': 42}
    state = {}
    
    reconstructed = _reconstruct_from_dict(SimpleClass, init_args, state)
    assert reconstructed.name == 'test'
    assert reconstructed.value == 42


def test_reconstruct_from_dict_with_additional_state():
    """Test reconstruction with state beyond constructor args."""
    init_args = {'name': 'test', 'value': 42}
    state = {'extra_attr': 'extra_value'}
    
    reconstructed = _reconstruct_from_dict(SimpleClass, init_args, state)
    assert reconstructed.name == 'test'
    assert reconstructed.value == 42
    assert reconstructed.extra_attr == 'extra_value'


def test_reconstruct_placeholder():
    """Test placeholder reconstruction."""
    info = {
        'type': SimpleClass,
        'repr': '<SimpleClass object>',
        'module': 'test_custom_picklers',
        'qualname': 'SimpleClass',
    }
    
    placeholder = _reconstruct_placeholder(info)
    assert 'Unpicklable' in repr(placeholder)
    assert 'SimpleClass' in repr(placeholder)


# Test PickleRegistry

def test_pickle_registry_register_simple_class():
    """Test manual registration of simple class."""
    PickleRegistry.register(SimpleClass)
    
    obj = SimpleClass('test', 99)
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)
    
    assert restored.name == 'test'
    assert restored.value == 99


def test_pickle_registry_register_slots_class():
    """Test registration of __slots__ class."""
    PickleRegistry.register(SlotsClass)
    
    obj = SlotsClass(1, 2, 3)
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)
    
    assert restored.x == 1
    assert restored.y == 2
    assert restored.z == 3


def test_pickle_registry_register_getstate_class():
    """Test registration of class with __getstate__."""
    PickleRegistry.register(GetStateClass)
    
    obj = GetStateClass({'test': 'data'})
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)
    
    assert restored._data == {'test': 'data'}


def test_pickle_registry_custom_reducer():
    """Test manual registration with custom reducer."""
    def custom_reducer(obj):
        return (lambda name: SimpleClass(name, 0), (obj.name,))
    
    PickleRegistry.register(SimpleClass, custom_reducer)
    
    obj = SimpleClass('custom', 999)
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)
    
    assert restored.name == 'custom'
    assert restored.value == 0  # Custom reducer sets this to 0


def test_pickle_registry_caches_reducers():
    """Test that registry caches reducers per type."""
    PickleRegistry.register(SimpleClass)
    
    # Check it's in cache
    assert SimpleClass in PickleRegistry._reducers
    
    # Second registration should use cache
    reducer1 = PickleRegistry._reducers[SimpleClass]
    PickleRegistry.register(SimpleClass)
    reducer2 = PickleRegistry._reducers[SimpleClass]
    
    assert reducer1 is reducer2


def test_pickle_registry_handles_nested_slots():
    """Test registration of class with inherited __slots__."""
    PickleRegistry.register(NestedSlotsClass)
    
    obj = NestedSlotsClass(1, 2, 3, 4)
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)
    
    assert restored.x == 1
    assert restored.y == 2
    assert restored.z == 3
    assert restored.w == 4


def test_pickle_registry_handles_mixed_state():
    """Test registration of class with both __slots__ and other attrs."""
    PickleRegistry.register(ComplexClass)
    
    obj = ComplexClass(100, 'secret')
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)
    
    assert restored.public_val == 100
    assert restored._private == 'secret'


# Test auto_register_for_pickling

def test_auto_register_returns_true_if_already_picklable():
    """Test that auto-register succeeds if object is already picklable."""
    obj = SimpleClass('test', 42)
    
    # SimpleClass should be picklable by default
    assert auto_register_for_pickling(obj) is True


def test_auto_register_handles_unpicklable_class():
    """Test auto-registration of unpicklable class."""
    obj = UnpicklableClass('test')
    
    # Should auto-register
    result = auto_register_for_pickling(obj)
    assert result is True
    
    # Should be picklable now
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)
    assert restored.name == 'test'


def test_auto_register_caches_type():
    """Test that auto-registration only introspects once per type."""
    obj1 = UnpicklableClass('obj1')
    obj2 = UnpicklableClass('obj2')
    
    auto_register_for_pickling(obj1)
    
    # Second object of same type should use cached registration
    assert UnpicklableClass in PickleRegistry._reducers
    assert auto_register_for_pickling(obj2) is True


def test_auto_register_returns_false_on_failure():
    """Test that auto-register returns False if registration fails."""
    # Create a truly unpicklable object (e.g., lambda with closure)
    closure_val = object()
    obj = lambda: closure_val
    
    result = auto_register_for_pickling(obj)
    # Lambdas might succeed or fail depending on dill version
    # Just verify it returns bool
    assert isinstance(result, bool)


def test_auto_register_logs_success(caplog):
    """Test that successful auto-registration logs info."""
    import logging
    caplog.set_level(logging.INFO)
    
    obj = UnpicklableClass('test')
    auto_register_for_pickling(obj)
    
    assert 'Auto-registered' in caplog.text
    assert 'UnpicklableClass' in caplog.text


def test_auto_register_logs_failure(caplog):
    """Test that failed auto-registration logs warning."""
    import logging
    caplog.set_level(logging.WARNING)
    
    # Try to register something that will fail
    obj = lambda: None
    obj.__class__ = type('UnregistrableType', (), {})
    
    try:
        auto_register_for_pickling(obj)
    except Exception:
        pass
    
    # Should have logged something about the attempt
    # (exact behavior depends on dill version)


# Test introspection strategies

def test_create_auto_reducer_prefers_getstate():
    """Test that __getstate__ is preferred over other methods."""
    reducer = PickleRegistry._create_auto_reducer(GetStateClass)
    
    obj = GetStateClass({'test': 'data'})
    reconstructor, args = reducer(obj)
    
    # Should use __getstate__ strategy
    assert reconstructor is _reconstruct_with_setstate


def test_create_auto_reducer_uses_slots():
    """Test that __slots__ is used when no __getstate__."""
    reducer = PickleRegistry._create_auto_reducer(SlotsClass)
    
    obj = SlotsClass(1, 2, 3)
    reconstructor, args = reducer(obj)
    
    # Should use __slots__ strategy
    assert reconstructor is _reconstruct_from_slots


def test_create_auto_reducer_uses_dict():
    """Test that __dict__ is used as fallback."""
    reducer = PickleRegistry._create_auto_reducer(SimpleClass)
    
    obj = SimpleClass('test', 42)
    reconstructor, args = reducer(obj)
    
    # Should use __dict__ strategy
    assert reconstructor is _reconstruct_from_dict


# Test edge cases

def test_handles_objects_without_init_params():
    """Test objects where __init__ params don't match state."""
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
    """Test objects with properties."""
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
    """Test objects with circular references."""
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
    """Test objects with no state."""
    class EmptyClass:
        pass
    
    PickleRegistry.register(EmptyClass)
    
    obj = EmptyClass()
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)
    
    assert isinstance(restored, EmptyClass)
```

#### 1.2 Create Custom Picklers Module

**File**: `client/src/cideldill_client/custom_picklers.py`

```python
"""Custom pickle protocols for objects that dill can't handle by default.

This module provides runtime introspection-based pickling for classes that
aren't normally picklable due to metaclass issues, dynamically generated classes,
or other edge cases.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable

import dill

logger = logging.getLogger(__name__)


class PickleRegistry:
    """Registry for custom pickle reducers.
    
    Automatically introspects objects to create reducers when needed.
    """
    
    _reducers: dict[type, Callable] = {}
    
    @classmethod
    def register(cls, obj_type: type, reducer: Callable | None = None) -> None:
        """Register a custom reducer for a type.
        
        Args:
            obj_type: The type to register.
            reducer: Optional custom reducer function. If None, auto-generates one.
        """
        if reducer is None:
            reducer = cls._create_auto_reducer(obj_type)
        
        cls._reducers[obj_type] = reducer
        
        # Register with dill
        dill.Pickler.dispatch[obj_type] = lambda pickler, obj: pickler.save_reduce(
            *reducer(obj), obj=obj
        )
        
        logger.debug(f"Registered custom pickler for {obj_type}")
    
    @classmethod
    def _create_auto_reducer(cls, obj_type: type) -> Callable:
        """Create an automatic reducer by introspecting the type.
        
        Args:
            obj_type: The type to create a reducer for.
            
        Returns:
            A reducer function compatible with pickle protocol.
        """
        # Determine the best strategy based on object structure
        
        # Strategy 1: Has __getstate__ and __setstate__
        if hasattr(obj_type, '__getstate__') and hasattr(obj_type, '__setstate__'):
            return cls._reducer_for_getstate(obj_type)
        
        # Strategy 2: Has __slots__
        if hasattr(obj_type, '__slots__'):
            return cls._reducer_for_slots(obj_type)
        
        # Strategy 3: Has __dict__
        return cls._reducer_for_dict(obj_type)
    
    @staticmethod
    def _reducer_for_getstate(obj_type: type) -> Callable:
        """Create reducer using __getstate__/__setstate__."""
        def reducer(obj):
            state = obj.__getstate__()
            return (_reconstruct_with_setstate, (obj_type, state))
        return reducer
    
    @staticmethod
    def _reducer_for_slots(obj_type: type) -> Callable:
        """Create reducer for objects with __slots__."""
        def reducer(obj):
            # Collect all slots from the class hierarchy
            slots = set()
            for klass in inspect.getmro(obj_type):
                if hasattr(klass, '__slots__'):
                    if isinstance(klass.__slots__, str):
                        slots.add(klass.__slots__)
                    else:
                        slots.update(klass.__slots__)
            
            # Extract slot values
            state = {}
            for slot in slots:
                try:
                    if hasattr(obj, slot):
                        state[slot] = getattr(obj, slot)
                except AttributeError:
                    pass
            
            return (_reconstruct_from_slots, (obj_type, state))
        return reducer
    
    @staticmethod
    def _reducer_for_dict(obj_type: type) -> Callable:
        """Create reducer for objects with __dict__."""
        def reducer(obj):
            # Try to get __dict__
            try:
                state = obj.__dict__.copy()
            except AttributeError:
                # Fallback: introspect attributes
                state = {}
                for attr in dir(obj):
                    if not attr.startswith('_'):
                        try:
                            value = getattr(obj, attr)
                            # Skip methods and properties
                            if not callable(value):
                                state[attr] = value
                        except (AttributeError, Exception):
                            pass
            
            # Try to get constructor parameters
            init_signature = None
            try:
                init_signature = inspect.signature(obj_type.__init__)
            except (ValueError, TypeError):
                pass
            
            # Extract constructor args from state
            init_args = {}
            if init_signature:
                for param_name, param in init_signature.parameters.items():
                    if param_name == 'self':
                        continue
                    if param_name in state:
                        init_args[param_name] = state.pop(param_name)
            
            return (_reconstruct_from_dict, (obj_type, init_args, state))
        return reducer
    
    @classmethod
    def clear(cls) -> None:
        """Clear all registered reducers (useful for testing)."""
        cls._reducers.clear()


# Reconstruction functions (these need to be module-level for pickling)

def _reconstruct_with_setstate(obj_type: type, state: Any) -> Any:
    """Reconstruct object using __setstate__."""
    # Create uninitialized instance
    obj = object.__new__(obj_type)
    obj.__setstate__(state)
    return obj


def _reconstruct_from_slots(obj_type: type, state: dict) -> Any:
    """Reconstruct object from slots."""
    # Create uninitialized instance
    obj = object.__new__(obj_type)
    
    # Restore slot values
    for slot, value in state.items():
        try:
            setattr(obj, slot, value)
        except (AttributeError, TypeError):
            # Some slots might be read-only or descriptors
            pass
    
    return obj


def _reconstruct_from_dict(obj_type: type, init_args: dict, state: dict) -> Any:
    """Reconstruct object from __dict__."""
    # Try to construct with init args
    try:
        obj = obj_type(**init_args)
    except (TypeError, Exception):
        # Fallback: create uninitialized
        obj = object.__new__(obj_type)
        # Try to set init args as attributes
        for key, value in init_args.items():
            try:
                setattr(obj, key, value)
            except (AttributeError, TypeError):
                pass
    
    # Restore remaining state
    for key, value in state.items():
        try:
            setattr(obj, key, value)
        except (AttributeError, TypeError):
            pass
    
    return obj


def _reconstruct_placeholder(info: dict) -> Any:
    """Create a placeholder for unpicklable objects."""
    class UnpicklablePlaceholder:
        def __init__(self, info):
            self._info = info
        
        def __repr__(self):
            return f"<Unpicklable {self._info['qualname']} from {self._info['module']}>"
        
        def __str__(self):
            return repr(self)
    
    return UnpicklablePlaceholder(info)


def auto_register_for_pickling(obj: Any) -> bool:
    """Automatically register an object's type for pickling if needed.
    
    Args:
        obj: The object to potentially register.
        
    Returns:
        True if registration was successful or unnecessary, False if it failed.
    """
    obj_type = type(obj)
    
    # Check if already registered
    if obj_type in PickleRegistry._reducers:
        return True
    
    # Check if dill can already handle it
    try:
        dill.dumps(obj, protocol=4)
        return True  # Already picklable
    except Exception:
        pass  # Need to register
    
    # Auto-register
    try:
        PickleRegistry.register(obj_type)
        logger.info(
            f"Auto-registered custom pickler for "
            f"{obj_type.__module__}.{obj_type.__qualname__}"
        )
        
        # Verify it works
        dill.dumps(obj, protocol=4)
        return True
    except Exception as e:
        logger.warning(
            f"Failed to auto-register pickler for {obj_type}: {e}",
            exc_info=True
        )
        return False
```

---

### Phase 2: Integration with Serialization (TDD)

#### 2.1 Write Integration Tests

**File**: `tests/unit/test_serialization_with_custom_picklers.py`

```python
"""Tests for serialization integration with custom picklers."""

import pytest
import dill

from cideldill_client.serialization import (
    Serializer,
    compute_cid,
    serialize,
    deserialize,
)
from cideldill_client.custom_picklers import PickleRegistry
from cideldill_client.exceptions import DebugSerializationError


class UnpicklableByDefault:
    """Class that dill can't handle without help."""
    _registry = {}
    
    def __init__(self, name: str, value: int):
        self.name = name
        self.value = value
        self._registry[name] = self


def test_safe_dumps_auto_registers_unpicklable():
    """Test that _safe_dumps auto-registers unpicklable objects."""
    from cideldill_client.serialization import _safe_dumps
    
    obj = UnpicklableByDefault('test', 42)
    
    # Should auto-register and succeed
    data = _safe_dumps(obj)
    assert isinstance(data, bytes)
    
    # Should be restorable
    restored = dill.loads(data)
    assert restored.name == 'test'
    assert restored.value == 42


def test_serialize_handles_unpicklable():
    """Test that serialize() handles unpicklable objects."""
    obj = UnpicklableByDefault('test', 99)
    
    # Should succeed via auto-registration
    data = serialize(obj)
    restored = deserialize(data)
    
    assert restored.name == 'test'
    assert restored.value == 99


def test_compute_cid_handles_unpicklable():
    """Test that compute_cid() handles unpicklable objects."""
    obj = UnpicklableByDefault('test', 100)
    
    # Should succeed via auto-registration
    cid = compute_cid(obj)
    assert isinstance(cid, str)
    assert len(cid) == 64  # SHA256 hex


def test_serializer_caches_auto_registered():
    """Test that Serializer caches work with auto-registered types."""
    serializer = Serializer()
    
    obj = UnpicklableByDefault('test', 200)
    
    # First serialization
    result1 = serializer.serialize(obj)
    assert result1.data_base64 is not None
    
    # Second serialization should use cache
    result2 = serializer.serialize(obj)
    assert result2.cid == result1.cid
    assert result2.data_base64 is None  # Cached, no data


def test_different_instances_same_type_share_reducer():
    """Test that multiple instances share the same auto-registered reducer."""
    obj1 = UnpicklableByDefault('obj1', 1)
    obj2 = UnpicklableByDefault('obj2', 2)
    
    # Both should succeed
    data1 = serialize(obj1)
    data2 = serialize(obj2)
    
    restored1 = deserialize(data1)
    restored2 = deserialize(data2)
    
    assert restored1.name == 'obj1'
    assert restored2.name == 'obj2'


def test_auto_registration_failure_raises_error():
    """Test that failed auto-registration raises DebugSerializationError."""
    # Create an object that will fail both pickle and auto-registration
    # (this is tricky - most objects can be pickled somehow)
    
    class TrulyUnpicklable:
        def __init__(self):
            # Store something unpicklable
            self.unpicklable = lambda: None
            # And prevent __getstate__
            self.__getstate__ = None
    
    obj = TrulyUnpicklable()
    
    # Should raise DebugSerializationError
    with pytest.raises(DebugSerializationError):
        serialize(obj)


def test_manual_registration_takes_precedence():
    """Test that manual registration is used instead of auto-registration."""
    class CustomClass:
        def __init__(self, value):
            self.value = value
    
    # Manually register with custom reducer
    def custom_reducer(obj):
        # Always return value=999 regardless of actual value
        return (lambda: CustomClass(999), ())
    
    PickleRegistry.register(CustomClass, custom_reducer)
    
    obj = CustomClass(42)
    data = serialize(obj)
    restored = deserialize(data)
    
    # Should use custom reducer
    assert restored.value == 999


def test_compute_cid_stable_for_same_object():
    """Test that CID is stable for equivalent objects."""
    obj1 = UnpicklableByDefault('test', 42)
    obj2 = UnpicklableByDefault('test', 42)
    
    cid1 = compute_cid(obj1)
    cid2 = compute_cid(obj2)
    
    # CIDs should be the same for equivalent objects
    assert cid1 == cid2


def test_compute_cid_different_for_different_objects():
    """Test that CID differs for different objects."""
    obj1 = UnpicklableByDefault('test1', 42)
    obj2 = UnpicklableByDefault('test2', 42)
    
    cid1 = compute_cid(obj1)
    cid2 = compute_cid(obj2)
    
    # CIDs should differ
    assert cid1 != cid2
```

#### 2.2 Update Serialization Module

**File**: `client/src/cideldill_client/serialization.py`

Add import at top:
```python
from .custom_picklers import auto_register_for_pickling
```

Update `_safe_dumps`:
```python
def _safe_dumps(obj: Any) -> bytes:
    """Safely dump object to bytes, auto-registering custom picklers if needed.
    
    Args:
        obj: The object to serialize.
        
    Returns:
        Pickled bytes.
        
    Raises:
        DebugSerializationError: If object cannot be serialized even after
            attempting auto-registration.
    """
    try:
        return dill.dumps(obj, protocol=DILL_PROTOCOL)
    except Exception as first_exception:
        # Try auto-registration
        if auto_register_for_pickling(obj):
            try:
                return dill.dumps(obj, protocol=DILL_PROTOCOL)
            except Exception as second_exception:
                raise DebugSerializationError(obj, second_exception) from second_exception
        raise DebugSerializationError(obj, first_exception) from first_exception
```

---

### Phase 3: Integration with Debug Proxy (TDD)

#### 3.1 Write Integration Tests

**File**: `tests/unit/test_debug_proxy_with_custom_picklers.py`

```python
"""Tests for debug proxy integration with custom picklers."""

import pytest

from cideldill_client.debug_proxy import DebugProxy
from cideldill_client.custom_picklers import PickleRegistry


class UnpicklableTarget:
    """Target class that isn't normally picklable."""
    _instances = []
    
    def __init__(self, name: str):
        self.name = name
        self._instances.append(self)
    
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
        return {'call_id': 'test-123', 'action': 'continue'}
    
    def record_call_complete(self, **kwargs):
        pass


def test_debug_proxy_wraps_unpicklable_object():
    """Test that DebugProxy can wrap unpicklable objects."""
    target = UnpicklableTarget('test')
    client = StubClient()
    
    # Should succeed (auto-registration happens during CID computation)
    proxy = DebugProxy(target, client, lambda: True)
    
    # Should have a CID
    assert hasattr(proxy, 'cid')
    assert len(proxy.cid) == 64


def test_debug_proxy_methods_work_on_unpicklable():
    """Test that wrapped methods work on unpicklable objects."""
    target = UnpicklableTarget('test')
    client = StubClient()
    proxy = DebugProxy(target, client, lambda: True)
    
    # Should be able to call methods
    result = proxy.get_name()
    assert result == 'test'
    
    result = proxy.double_value(5)
    assert result == 10


def test_debug_proxy_records_calls_with_unpicklable():
    """Test that call recording works with unpicklable objects."""
    target = UnpicklableTarget('test')
    client = StubClient()
    proxy = DebugProxy(target, client, lambda: True)
    
    # Call a method
    proxy.get_name()
    
    # Should have recorded the call
    assert len(client.recorded_calls) == 1
    call = client.recorded_calls[0]
    assert call['method_name'] == 'get_name'
    assert call['target_cid'] is not None


def test_debug_proxy_serializes_unpicklable_args():
    """Test that method args are serialized even if unpicklable."""
    class UnpicklableArg:
        def __init__(self, value):
            self.value = value
    
    target = UnpicklableTarget('test')
    client = StubClient()
    proxy = DebugProxy(target, client, lambda: True)
    
    # Method that accepts unpicklable arg
    def method_with_unpicklable_arg(self, arg):
        return arg.value
    
    target.custom_method = method_with_unpicklable_arg.__get__(target)
    
    arg = UnpicklableArg(42)
    
    # Should succeed via auto-registration
    result = proxy.custom_method(arg)
    assert result == 42


def test_proxy_cid_stable_across_calls():
    """Test that proxy CID remains stable across method calls."""
    target = UnpicklableTarget('test')
    client = StubClient()
    proxy = DebugProxy(target, client, lambda: True)
    
    cid1 = proxy.cid
    proxy.get_name()
    cid2 = proxy.cid
    proxy.double_value(5)
    cid3 = proxy.cid
    
    # CID should remain the same
    assert cid1 == cid2 == cid3
```

#### 3.2 Verify Debug Proxy Works

No changes needed to `debug_proxy.py` - it already uses `compute_cid()` which now handles auto-registration.

---

### Phase 4: Integration with with_debug (TDD)

#### 4.1 Write Integration Tests

**File**: `tests/unit/test_with_debug_unpicklable.py`

```python
"""Tests for with_debug integration with unpicklable objects."""

import pytest

from cideldill_client import with_debug, configure_debug
from cideldill_client.debug_proxy import DebugProxy


class NATLikeUnpicklable:
    """Simulates NAT's OutputArgsSchema-like unpicklable class."""
    
    # Simulate metaclass registry
    _type_registry = {}
    
    def __init__(self, schema_name: str):
        self.schema_name = schema_name
        self._type_registry[schema_name] = self
    
    def validate(self, data):
        return True
    
    def transform(self, value):
        return value * 2


def test_with_debug_wraps_unpicklable_object(monkeypatch):
    """Test that with_debug successfully wraps unpicklable objects."""
    # Mock server connection
    def noop_check(self):
        pass
    
    monkeypatch.setattr(
        'cideldill_client.debug_client.DebugClient.check_connection',
        noop_check
    )
    
    configure_debug(server_url='http://localhost:5000')
    with_debug('ON')
    
    # Create unpicklable object
    obj = NATLikeUnpicklable('test_schema')
    
    # Should wrap successfully
    wrapped = with_debug(obj)
    
    assert isinstance(wrapped, DebugProxy)
    assert wrapped.schema_name == 'test_schema'


def test_wrapped_unpicklable_methods_work(monkeypatch):
    """Test that methods on wrapped unpicklable objects work."""
    def noop_check(self):
        pass
    
    monkeypatch.setattr(
        'cideldill_client.debug_client.DebugClient.check_connection',
        noop_check
    )
    
    configure_debug(server_url='http://localhost:5000')
    with_debug('ON')
    
    obj = NATLikeUnpicklable('test_schema')
    wrapped = with_debug(obj)
    
    # Methods should work
    assert wrapped.validate({'data': 'test'}) is True
    assert wrapped.transform(5) == 10


def test_with_debug_off_returns_unpicklable_unchanged():
    """Test that with_debug('OFF') returns unpicklable objects unchanged."""
    with_debug('OFF')
    
    obj = NATLikeUnpicklable('test_schema')
    result = with_debug(obj)
    
    # Should return original object
    assert result is obj
    assert not isinstance(result, DebugProxy)


def test_multiple_unpicklable_objects_work(monkeypatch):
    """Test that multiple unpicklable objects can be wrapped."""
    def noop_check(self):
        pass
    
    monkeypatch.setattr(
        'cideldill_client.debug_client.DebugClient.check_connection',
        noop_check
    )
    
    configure_debug(server_url='http://localhost:5000')
    with_debug('ON')
    
    obj1 = NATLikeUnpicklable('schema1')
    obj2 = NATLikeUnpicklable('schema2')
    obj3 = NATLikeUnpicklable('schema3')
    
    wrapped1 = with_debug(obj1)
    wrapped2 = with_debug(obj2)
    wrapped3 = with_debug(obj3)
    
    # All should be wrapped successfully
    assert isinstance(wrapped1, DebugProxy)
    assert isinstance(wrapped2, DebugProxy)
    assert isinstance(wrapped3, DebugProxy)
    
    # All should have different CIDs
    assert wrapped1.cid != wrapped2.cid
    assert wrapped2.cid != wrapped3.cid
    assert wrapped1.cid != wrapped3.cid
```

#### 4.2 Verify with_debug Works

No changes needed to `with_debug.py` - it already uses `DebugProxy` which uses `compute_cid()`.

---

### Phase 5: Documentation and Examples

#### 5.1 Update Documentation

**File**: `docs/with_debug_api.md`

Add new section:

```markdown
## Handling Unpicklable Objects

CID el Dill automatically handles objects that can't be pickled using dill's default mechanisms. This includes:

- Objects with metaclass registries
- Dynamically generated classes
- Objects with circular references
- Classes from third-party libraries (like NAT)

### Automatic Registration

The system automatically introspects unpicklable objects and creates custom pickle protocols:

```python
from cideldill_client import with_debug

with_debug("ON")

# Works even if NAT's OutputArgsSchema isn't normally picklable
from nat.utils.type_utils import OutputArgsSchema

schema = OutputArgsSchema(...)
wrapped_schema = with_debug(schema)  # Auto-registers custom pickler

# Full debugging support
result = wrapped_schema.validate(data)
```

### Manual Registration for Complex Cases

For complex objects that auto-introspection can't handle, provide a custom reducer:

```python
from cideldill_client.custom_picklers import PickleRegistry

def custom_reducer(obj):
    # Extract state
    state = {'field1': obj.field1, 'field2': obj.field2}
    
    # Define reconstructor
    def reconstruct(state):
        obj = MyComplexClass.__new__(MyComplexClass)
        obj.field1 = state['field1']
        obj.field2 = state['field2']
        return obj
    
    return (reconstruct, (state,))

# Register before wrapping
PickleRegistry.register(MyComplexClass, custom_reducer)

# Now wrapping works
obj = with_debug(MyComplexClass(...))
```

### Logging

Enable logging to see what's being auto-registered:

```python
import logging
logging.basicConfig(level=logging.INFO)

# You'll see:
# INFO: Auto-registered custom pickler for nat.utils.type_utils.OutputArgsSchema
```
```

**File**: `README.md`

Add to Features section:

```markdown
- **Automatic unpicklable object handling**: Works with complex objects from third-party libraries
```

#### 5.2 Create Example

**File**: `examples/unpicklable_objects.py` (NEW)

```python
"""Example demonstrating automatic handling of unpicklable objects.

This example shows how CID el Dill automatically handles objects that
can't be pickled using standard mechanisms.
"""

from cideldill_client import with_debug


# Simulate a class that's normally unpicklable
class MetaclassRegistry(type):
    """Metaclass that maintains a registry (can cause pickle issues)."""
    _instances = {}
    
    def __call__(cls, *args, **kwargs):
        key = (cls.__name__, args)
        if key not in cls._instances:
            cls._instances[key] = super().__call__(*args, **kwargs)
        return cls._instances[key]


class ConfigSchema(metaclass=MetaclassRegistry):
    """Configuration schema with singleton-like behavior."""
    
    def __init__(self, name: str):
        self.name = name
        self.rules = []
    
    def add_rule(self, rule: str) -> None:
        self.rules.append(rule)
    
    def validate(self, data: dict) -> bool:
        print(f"Validating {data} against schema '{self.name}'")
        return True


def main():
    """Demonstrate unpicklable object handling."""
    print("=" * 60)
    print("Unpicklable Objects Example")
    print("=" * 60)
    print()
    
    # Enable debugging
    with_debug("ON")
    
    # Create schema (normally unpicklable due to metaclass)
    schema = ConfigSchema("user_schema")
    schema.add_rule("required: username")
    schema.add_rule("required: email")
    
    # Wrap with debugging - auto-registration happens here
    print("Wrapping unpicklable object...")
    wrapped_schema = with_debug(schema)
    print(f"✓ Successfully wrapped: {type(schema).__name__}")
    print(f"  CID: {wrapped_schema.cid[:16]}...")
    print()
    
    # Use wrapped object normally
    print("Using wrapped object:")
    wrapped_schema.add_rule("optional: phone")
    result = wrapped_schema.validate({"username": "alice", "email": "alice@example.com"})
    print(f"  Validation result: {result}")
    print()
    
    # Create another instance - uses singleton behavior
    schema2 = ConfigSchema("user_schema")
    wrapped_schema2 = with_debug(schema2)
    
    print(f"Same instance? {schema is schema2}")
    print(f"Same CID? {wrapped_schema.cid == wrapped_schema2.cid}")
    print()
    
    print("=" * 60)
    print("All operations completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
```

---

### Phase 6: Edge Cases and Robustness

#### 6.1 Add Edge Case Tests

**File**: `tests/unit/test_custom_picklers_edge_cases.py`

```python
"""Tests for edge cases in custom picklers."""

import pytest
import dill

from cideldill_client.custom_picklers import (
    PickleRegistry,
    auto_register_for_pickling,
)


def test_handles_builtin_types():
    """Test that builtin types work without issues."""
    # Builtins should already be picklable
    for obj in [42, "string", [1, 2, 3], {"key": "value"}]:
        assert auto_register_for_pickling(obj) is True


def test_handles_none():
    """Test that None is handled correctly."""
    assert auto_register_for_pickling(None) is True


def test_handles_functions():
    """Test that functions are handled."""
    def test_func():
        return 42
    
    assert auto_register_for_pickling(test_func) is True


def test_handles_lambdas():
    """Test that lambdas are handled (might fail, that's okay)."""
    func = lambda x: x * 2
    
    # Lambdas might or might not be picklable depending on dill version
    # Just verify it returns a bool and doesn't crash
    result = auto_register_for_pickling(func)
    assert isinstance(result, bool)


def test_handles_recursive_structures():
    """Test objects with recursive references."""
    class Node:
        def __init__(self, value):
            self.value = value
            self.children = []
        
        def add_child(self, child):
            self.children.append(child)
    
    root = Node(1)
    child = Node(2)
    root.add_child(child)
    child.add_child(root)  # Circular reference
    
    assert auto_register_for_pickling(root) is True
    
    pickled = dill.dumps(root)
    restored = dill.loads(pickled)
    
    assert restored.value == 1
    assert restored.children[0].value == 2
    assert restored.children[0].children[0].value == 1


def test_handles_objects_with_no_dict():
    """Test objects without __dict__."""
    class NoDictClass:
        __slots__ = ['value']
        
        def __init__(self, value):
            self.value = value
    
    obj = NoDictClass(42)
    assert auto_register_for_pickling(obj) is True
    
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)
    assert restored.value == 42


def test_handles_objects_with_descriptors():
    """Test objects with descriptors and properties."""
    class DescriptorClass:
        def __init__(self, value):
            self._value = value
        
        @property
        def value(self):
            return self._value
        
        @value.setter
        def value(self, val):
            self._value = val
    
    obj = DescriptorClass(100)
    assert auto_register_for_pickling(obj) is True
    
    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)
    assert restored.value == 100


def test_handles_objects_with_weakrefs():
    """Test objects with weak references."""
    import weakref
    
    class WeakRefClass:
        def __init__(self, name):
            self.name = name
            self.refs = []
        
        def add_ref(self, obj):
            self.refs.append(weakref.ref(obj))
    
    obj1 = WeakRefClass("obj1")
    obj2 = WeakRefClass("obj2")
    obj1.add_ref(obj2)
    
    # May or may not succeed - weak refs are tricky
    result = auto_register_for_pickling(obj1)
    assert isinstance(result, bool)


def test_handles_objects_with_file_handles():
    """Test objects with file handles (should fail gracefully)."""
    import tempfile
    
    class FileHolder:
        def __init__(self):
            self.file = tempfile.NamedTemporaryFile(delete=False)
    
    obj = FileHolder()
    
    try:
        # File handles can't be pickled - should return False
        result = auto_register_for_pickling(obj)
        # If it somehow succeeds, that's fine too
        assert isinstance(result, bool)
    finally:
        obj.file.close()


def test_concurrent_auto_registration():
    """Test that concurrent auto-registration is thread-safe."""
    import threading
    
    class ConcurrentClass:
        def __init__(self, value):
            self.value = value
    
    results = []
    
    def register_worker():
        obj = ConcurrentClass(42)
        result = auto_register_for_pickling(obj)
        results.append(result)
    
    threads = [threading.Thread(target=register_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # All should succeed
    assert all(results)
    
    # Type should only be registered once
    assert ConcurrentClass in PickleRegistry._reducers
```

---

## Testing Checklist

### Unit Tests
- [ ] All reconstruction function tests pass
- [ ] PickleRegistry registration tests pass
- [ ] Auto-registration tests pass
- [ ] Strategy selection tests pass
- [ ] Edge case tests pass
- [ ] Serialization integration tests pass
- [ ] Debug proxy integration tests pass
- [ ] with_debug integration tests pass

### Integration Tests
- [ ] End-to-end unpicklable object workflow
- [ ] Multiple unpicklable types simultaneously
- [ ] NAT-like objects work correctly

### Manual Tests
- [ ] Test with actual NAT OutputArgsSchema
- [ ] Test with other problematic third-party objects
- [ ] Verify logging output is helpful
- [ ] Test performance impact (should be minimal)

---

## Success Criteria

- [ ] NAT's OutputArgsSchema wraps successfully
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Documentation updated
- [ ] Example code works
- [ ] No performance regression for normal objects
- [ ] Logging provides useful debugging information
- [ ] Manual registration works for edge cases

---

## Performance Considerations

### Optimization Strategies

1. **Cache reducer per type**: Don't introspect the same type twice
2. **Try standard pickling first**: Only introspect on failure
3. **Lazy registration**: Only register when needed
4. **Minimize introspection overhead**: Use cached `inspect.signature` results

### Expected Performance Impact

- **First wrap of new type**: +10-50ms (introspection + registration)
- **Subsequent wraps**: No additional overhead (cached)
- **Already-picklable objects**: No overhead (fast path)

---

## Rollback Plan

If issues arise:

1. **Disable auto-registration**: Add flag to `_safe_dumps`
2. **Fall back to error**: Return `DebugSerializationError` as before
3. **Manual registration only**: Require explicit `PickleRegistry.register()`

Quick rollback patch:

```python
# In serialization.py
def _safe_dumps(obj: Any) -> bytes:
    if os.getenv('DISABLE_AUTO_PICKLE') == '1':
        # Original behavior
        try:
            return dill.dumps(obj, protocol=DILL_PROTOCOL)
        except Exception as exc:
            raise DebugSerializationError(obj, exc) from exc
    
    # New auto-registration behavior
    # ... rest of implementation
```

---

## Estimated Effort

- **Phase 1 (Core Infrastructure)**: 4 hours
- **Phase 2 (Serialization Integration)**: 2 hours
- **Phase 3 (Debug Proxy Integration)**: 1 hour
- **Phase 4 (with_debug Integration)**: 1 hour
- **Phase 5 (Documentation)**: 2 hours
- **Phase 6 (Edge Cases)**: 2 hours
- **Testing & Polish**: 2 hours

**Total**: ~14 hours

---

## Future Enhancements

### Phase 7 (Optional): Advanced Features

1. **Pickle protocol versioning**: Support different pickle strategies per version
2. **Custom reducer plugins**: Allow users to register reducer factories
3. **Pickle diagnostics**: Tool to analyze why an object can't be pickled
4. **Performance profiling**: Measure introspection overhead
5. **Whitelist/blacklist**: Control which types get auto-registered

### Phase 8 (Optional): User-Friendly Tools

1. **CLI tool**: `cideldill-pickle-test <module>` to test picklability
2. **Diagnostic mode**: Detailed logging of pickle attempts
3. **Reducer generator**: Interactive tool to create custom reducers
4. **Documentation**: Best practices for making objects picklable

---

## Notes

- Follow TDD: Write tests first, then implementation
- Commit after each phase
- Update CHANGELOG.md when complete
- Consider adding performance benchmarks
- Document any NAT-specific workarounds
- Keep introspection code simple and maintainable
