"""Custom pickle protocols for objects that dill can't handle by default.

This module provides runtime introspection-based pickling for classes that
aren't normally picklable due to metaclass issues, dynamically generated classes,
or other edge cases.
"""

from __future__ import annotations

import inspect
import logging
import ssl
import threading
from dataclasses import dataclass
from typing import Any, Callable

import dill

logger = logging.getLogger(__name__)


@dataclass
class UnpicklablePlaceholder:
    """Rich snapshot for objects that cannot be fully reconstructed."""

    type_name: str
    module: str
    qualname: str
    object_id: str
    repr_text: str
    str_text: str | None
    attributes: dict[str, Any]
    failed_attributes: dict[str, str]
    pickle_error: str
    pickle_attempts: list[str]
    capture_timestamp: float
    depth: int

    def __repr__(self) -> str:
        n_ok = len(self.attributes)
        n_fail = len(self.failed_attributes)
        return (
            f"<UnpicklablePlaceholder {self.module}.{self.qualname} "
            f"attrs={n_ok} failed={n_fail} error={self.pickle_error!r}>"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the placeholder to a JSON-serializable dict."""
        return {
            "type_name": self.type_name,
            "module": self.module,
            "qualname": self.qualname,
            "object_id": self.object_id,
            "repr_text": self.repr_text,
            "str_text": self.str_text,
            "attributes": self.attributes,
            "failed_attributes": self.failed_attributes,
            "pickle_error": self.pickle_error,
            "pickle_attempts": list(self.pickle_attempts),
            "capture_timestamp": self.capture_timestamp,
            "depth": self.depth,
        }


class PickleRegistry:
    """Registry for custom pickle reducers.

    Automatically introspects objects to create reducers when needed.
    """

    _reducers: dict[type, Callable] = {}
    _type_registry: dict[str, type] = {}
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
            cls._type_registry[cls._type_key(obj_type)] = obj_type

        def _dispatch(pickler, obj):
            reduced = reducer(obj)
            if len(reduced) == 2:
                reconstructor, args = reduced
                pickler.save_reduce(reconstructor, args, obj=obj)
            elif len(reduced) == 3:
                reconstructor, args, state = reduced
                pickler.save_reduce(reconstructor, args, state, obj=obj)
            elif len(reduced) == 4:
                reconstructor, args, state, state_setter = reduced
                pickler.save_reduce(
                    reconstructor,
                    args,
                    state,
                    obj=obj,
                    state_setter=state_setter,
                )
            else:
                raise ValueError("Reducer must return 2-4 values")

        dill.Pickler.dispatch[obj_type] = _dispatch

        logger.debug("Registered custom pickler for %s", obj_type)

    @classmethod
    def _create_auto_reducer(cls, obj_type: type) -> Callable:
        """Create an automatic reducer by introspecting the type.

        Args:
            obj_type: The type to create a reducer for.

        Returns:
            A reducer function compatible with pickle protocol.
        """
        for klass in inspect.getmro(obj_type):
            if klass is object:
                continue
            if "__getstate__" in getattr(klass, "__dict__", {}):
                return cls._reducer_for_getstate(obj_type)

        if hasattr(obj_type, "__slots__"):
            return cls._reducer_for_slots(obj_type)

        return cls._reducer_for_dict(obj_type)

    @staticmethod
    def _reducer_for_getstate(obj_type: type) -> Callable:
        """Create reducer using __getstate__/__setstate__."""

        def reducer(obj):
            state = obj.__getstate__()
            type_key = PickleRegistry._type_key(obj_type)
            return (_reconstruct_with_setstate, (type_key, obj_type, state))

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

    @staticmethod
    def _type_key(obj_type: type) -> str:
        return f"{obj_type.__module__}:{obj_type.__qualname__}:{id(obj_type)}"

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

            if hasattr(obj, "__dict__"):
                try:
                    for key, value in obj.__dict__.items():
                        if key not in state:
                            state[key] = value
                except Exception:
                    pass

            type_key = PickleRegistry._type_key(obj_type)
            return (
                _reconstruct_from_slots,
                (type_key, obj_type),
                state,
                _apply_state,
            )

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

            type_key = PickleRegistry._type_key(obj_type)
            return (
                _reconstruct_from_dict,
                (type_key, obj_type, init_args),
                state,
                _apply_state,
            )

        return reducer

    @classmethod
    def clear(cls) -> None:
        """Clear all registered reducers (useful for testing)."""
        with cls._lock:
            cls._reducers.clear()
            cls._type_registry.clear()


def _reconstruct_ssl_context(
    protocol: int,
    options: int | None,
    verify_mode: int | None,
    check_hostname: bool | None,
    minimum_version: int | None,
    maximum_version: int | None,
    ciphers: str | None,
) -> ssl.SSLContext:
    ctx = ssl.SSLContext(protocol)
    if options is not None:
        try:
            ctx.options = options
        except Exception:
            pass
    if verify_mode is not None:
        try:
            ctx.verify_mode = verify_mode
        except Exception:
            pass
    if check_hostname is not None:
        try:
            ctx.check_hostname = check_hostname
        except Exception:
            pass
    if minimum_version is not None:
        try:
            ctx.minimum_version = minimum_version
        except Exception:
            pass
    if maximum_version is not None:
        try:
            ctx.maximum_version = maximum_version
        except Exception:
            pass
    if ciphers:
        try:
            ctx.set_ciphers(ciphers)
        except Exception:
            pass
    return ctx


def _ssl_context_reducer(obj: ssl.SSLContext) -> tuple[Callable, tuple[Any, ...]]:
    try:
        cipher_list = obj.get_ciphers()
        cipher_names = [item.get("name") for item in cipher_list if item.get("name")]
        ciphers = ":".join(cipher_names) if cipher_names else None
    except Exception:
        ciphers = None

    return (
        _reconstruct_ssl_context,
        (
            obj.protocol,
            getattr(obj, "options", None),
            getattr(obj, "verify_mode", None),
            getattr(obj, "check_hostname", None),
            getattr(obj, "minimum_version", None),
            getattr(obj, "maximum_version", None),
            ciphers,
        ),
    )


try:
    PickleRegistry.register(ssl.SSLContext, _ssl_context_reducer)
except Exception:
    logger.debug("Unable to register SSLContext reducer", exc_info=True)


def auto_register_for_pickling(obj: Any, protocol: int | None = None) -> bool:
    """Attempt to auto-register a custom pickler for an object.

    Returns True if the object can be pickled (before or after auto-registration).
    """
    if protocol is None:
        protocol = dill.HIGHEST_PROTOCOL

    try:
        dill.dumps(obj, protocol=protocol)
        obj_type = type(obj)
        if obj_type not in PickleRegistry._reducers and obj_type.__module__ != "builtins":
            try:
                PickleRegistry.register(obj_type)
            except Exception:
                return True
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

def _resolve_registered_type(type_key: str, fallback_type: type) -> type:
    resolved = PickleRegistry._type_registry.get(type_key)
    return resolved or fallback_type


def _apply_state(obj: Any, state: Any) -> None:
    if not isinstance(state, dict):
        return
    for key, value in state.items():
        try:
            setattr(obj, key, value)
        except Exception:
            continue


def _reconstruct_with_setstate(*args: Any) -> Any:
    """Reconstruct object using __setstate__."""
    if isinstance(args[0], str):
        type_key, obj_type, state = args
    else:
        obj_type, state = args
        type_key = PickleRegistry._type_key(obj_type)
    resolved_type = _resolve_registered_type(type_key, obj_type)
    obj = object.__new__(resolved_type)
    if hasattr(obj, "__setstate__"):
        obj.__setstate__(state)
        return obj
    if isinstance(state, dict):
        for key, value in state.items():
            try:
                setattr(obj, key, value)
            except Exception:
                continue
    return obj


def _reconstruct_from_slots(*args: Any) -> Any:
    """Reconstruct object from slots."""
    state = None
    if isinstance(args[0], str):
        if len(args) == 3:
            type_key, obj_type, state = args
        else:
            type_key, obj_type = args
    else:
        if len(args) == 2:
            obj_type, state = args
        else:
            obj_type = args[0]
            state = None
        type_key = PickleRegistry._type_key(obj_type)
    resolved_type = _resolve_registered_type(type_key, obj_type)
    obj = object.__new__(resolved_type)
    if state is not None:
        _apply_state(obj, state)

    return obj


def _reconstruct_from_dict(*args: Any) -> Any:
    """Reconstruct object from __dict__."""
    state = None
    if isinstance(args[0], str):
        if len(args) == 4:
            type_key, obj_type, init_args, state = args
        else:
            type_key, obj_type, init_args = args
    else:
        if len(args) == 3:
            obj_type, init_args, state = args
        else:
            obj_type, init_args = args
            state = None
        type_key = PickleRegistry._type_key(obj_type)
    resolved_type = _resolve_registered_type(type_key, obj_type)
    obj = object.__new__(resolved_type)
    for key, value in init_args.items():
        try:
            setattr(obj, key, value)
        except Exception:
            continue

    if state is not None:
        _apply_state(obj, state)

    return obj


def _reconstruct_placeholder(info: dict) -> UnpicklablePlaceholder:
    """Reconstruct a placeholder for an unpicklable object."""
    return UnpicklablePlaceholder(
        type_name=str(info.get("type_name", info.get("type", "Unknown"))),
        module=info.get("module", "unknown"),
        qualname=info.get("qualname", "Unknown"),
        object_id=info.get("object_id", info.get("id", "unknown")),
        repr_text=info.get("repr_text", info.get("repr", "")),
        str_text=info.get("str_text"),
        attributes=info.get("attributes", {}),
        failed_attributes=info.get("failed_attributes", {}),
        pickle_error=info.get("pickle_error", info.get("error", "")),
        pickle_attempts=info.get("pickle_attempts", info.get("attempts", [])),
        capture_timestamp=info.get("capture_timestamp", 0.0),
        depth=info.get("depth", 0),
    )
