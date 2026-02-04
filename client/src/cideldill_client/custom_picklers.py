"""Custom pickle protocols for objects that dill can't handle by default.

This module provides runtime introspection-based pickling for classes that
aren't normally picklable due to metaclass issues, dynamically generated classes,
or other edge cases.
"""

from __future__ import annotations

import inspect
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

import dill

logger = logging.getLogger(__name__)


@dataclass
class UnpicklablePlaceholder:
    """Placeholder for objects that cannot be fully reconstructed."""

    type_name: str
    module: str
    qualname: str
    repr_text: str

    def __repr__(self) -> str:
        return (
            f"<Unpicklable {self.module}.{self.qualname} "
            f"repr={self.repr_text!r}>"
        )


class PickleRegistry:
    """Registry for custom pickle reducers.

    Automatically introspects objects to create reducers when needed.
    """

    _reducers: dict[type, Callable] = {}
    _lock = threading.Lock()

    @classmethod
    def register(cls, obj_type: type, reducer: Callable | None = None) -> None:
        """Register a custom reducer for a type.

        Args:
            obj_type: The type to register.
            reducer: Optional custom reducer function. If None, auto-generates one.
        """
        if not isinstance(obj_type, type):
            raise TypeError("obj_type must be a type")

        with cls._lock:
            if reducer is None:
                cached = cls._reducers.get(obj_type)
                if cached is not None:
                    reducer = cached
                else:
                    reducer = cls._create_auto_reducer(obj_type)
                    cls._reducers[obj_type] = reducer
            else:
                cls._reducers[obj_type] = reducer

        dill.Pickler.dispatch[obj_type] = lambda pickler, obj: pickler.save_reduce(
            *reducer(obj), obj=obj
        )

        logger.debug("Registered custom pickler for %s", obj_type)

    @classmethod
    def _create_auto_reducer(cls, obj_type: type) -> Callable:
        """Create an automatic reducer by introspecting the type.

        Args:
            obj_type: The type to create a reducer for.

        Returns:
            A reducer function compatible with pickle protocol.
        """
        if hasattr(obj_type, "__getstate__") and hasattr(obj_type, "__setstate__"):
            return cls._reducer_for_getstate(obj_type)

        if hasattr(obj_type, "__slots__"):
            return cls._reducer_for_slots(obj_type)

        return cls._reducer_for_dict(obj_type)

    @staticmethod
    def _reducer_for_getstate(obj_type: type) -> Callable:
        """Create reducer using __getstate__/__setstate__."""

        def reducer(obj):
            state = obj.__getstate__()
            return (_reconstruct_with_setstate, (obj_type, state))

        return reducer

    @staticmethod
    def _collect_slots(obj_type: type) -> set[str]:
        slots: set[str] = set()
        for klass in inspect.getmro(obj_type):
            if hasattr(klass, "__slots__"):
                klass_slots = klass.__slots__
                if isinstance(klass_slots, str):
                    slots.add(klass_slots)
                else:
                    slots.update(klass_slots)
        slots.discard("__dict__")
        slots.discard("__weakref__")
        return slots

    @classmethod
    def _reducer_for_slots(cls, obj_type: type) -> Callable:
        """Create reducer for objects with __slots__."""

        def reducer(obj):
            slots = cls._collect_slots(obj_type)

            state = {}
            for slot in slots:
                try:
                    if hasattr(obj, slot):
                        state[slot] = getattr(obj, slot)
                except AttributeError:
                    continue

            return (_reconstruct_from_slots, (obj_type, state))

        return reducer

    @staticmethod
    def _reducer_for_dict(obj_type: type) -> Callable:
        """Create reducer for objects with __dict__."""

        def reducer(obj):
            try:
                state = obj.__dict__.copy()
            except AttributeError:
                state = {}

            if not state:
                for attr in dir(obj):
                    if attr.startswith("_"):
                        continue
                    try:
                        value = getattr(obj, attr)
                    except Exception:
                        continue
                    if callable(value):
                        continue
                    state[attr] = value

            init_signature = None
            try:
                init_signature = inspect.signature(obj_type.__init__)
            except (ValueError, TypeError):
                init_signature = None

            init_args = {}
            if init_signature:
                for param_name, param in init_signature.parameters.items():
                    if param_name == "self":
                        continue
                    if param_name in state:
                        init_args[param_name] = state.pop(param_name)

            return (_reconstruct_from_dict, (obj_type, init_args, state))

        return reducer

    @classmethod
    def clear(cls) -> None:
        """Clear all registered reducers (useful for testing)."""
        with cls._lock:
            cls._reducers.clear()


def auto_register_for_pickling(obj: Any, protocol: int | None = None) -> bool:
    """Attempt to auto-register a custom pickler for an object.

    Returns True if the object can be pickled (before or after auto-registration).
    """
    if protocol is None:
        protocol = dill.HIGHEST_PROTOCOL

    try:
        dill.dumps(obj, protocol=protocol)
        return True
    except Exception as exc:  # noqa: BLE001 - preserve context for logging
        obj_type = type(obj)

    if obj_type in PickleRegistry._reducers:
        try:
            dill.dumps(obj, protocol=protocol)
            return True
        except Exception:
            logger.warning(
                "Auto-registered reducer failed to pickle %s",
                obj_type,
                exc_info=True,
            )
            return False

    try:
        PickleRegistry.register(obj_type)
    except Exception:
        logger.warning(
            "Failed to auto-register custom pickler for %s",
            obj_type,
            exc_info=True,
        )
        return False

    try:
        dill.dumps(obj, protocol=protocol)
    except Exception:
        logger.warning(
            "Auto-registered reducer did not make %s picklable",
            obj_type,
            exc_info=True,
        )
        return False

    logger.info("Auto-registered custom pickler for %s", obj_type.__qualname__)
    return True


# Reconstruction functions (module-level for pickling)

def _reconstruct_with_setstate(obj_type: type, state: Any) -> Any:
    """Reconstruct object using __setstate__."""
    obj = object.__new__(obj_type)
    obj.__setstate__(state)
    return obj


def _reconstruct_from_slots(obj_type: type, state: dict) -> Any:
    """Reconstruct object from slots."""
    obj = object.__new__(obj_type)

    for slot, value in state.items():
        try:
            setattr(obj, slot, value)
        except (AttributeError, TypeError):
            continue

    return obj


def _reconstruct_from_dict(obj_type: type, init_args: dict, state: dict) -> Any:
    """Reconstruct object from __dict__."""
    try:
        obj = obj_type(**init_args)
    except Exception:
        obj = object.__new__(obj_type)
        for key, value in init_args.items():
            try:
                setattr(obj, key, value)
            except Exception:
                continue

    for key, value in state.items():
        try:
            setattr(obj, key, value)
        except Exception:
            continue

    return obj


def _reconstruct_placeholder(info: dict) -> UnpicklablePlaceholder:
    """Reconstruct a placeholder for an unpicklable object."""
    return UnpicklablePlaceholder(
        type_name=str(info.get("type", "Unknown")),
        module=info.get("module", "unknown"),
        qualname=info.get("qualname", "Unknown"),
        repr_text=info.get("repr", ""),
    )
