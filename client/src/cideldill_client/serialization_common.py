"""Shared serialization utilities using dill with CID-based deduplication."""

from __future__ import annotations

import base64
import hashlib
import logging
import threading
import time
import traceback
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

import dill

logger = logging.getLogger(__name__)
_module_key = "module"

DILL_PROTOCOL = 4
MAX_REPR_LENGTH = 300
DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_ATTRIBUTES = 100

dill.settings["recurse"] = True


@dataclass
class UnpicklablePlaceholder:  # noqa: D401 - fallback placeholder
    """Fallback placeholder for objects that cannot be fully reconstructed."""

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
    object_name: str | None = None
    object_path: str | None = None

    def __repr__(self) -> str:
        n_ok = len(self.attributes)
        n_fail = len(self.failed_attributes)
        return (
            f"<UnpicklablePlaceholder {self.module}.{self.qualname} "
            f"attrs={n_ok} failed={n_fail} error={self.pickle_error!r}>"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type_name": self.type_name,
            "module": self.module,
            "qualname": self.qualname,
            "object_name": self.object_name,
            "object_path": self.object_path,
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


# These are configured by callers (client/server) as needed.
_unpicklable_placeholder_cls: type[UnpicklablePlaceholder] = UnpicklablePlaceholder

def _default_auto_register_for_pickling(obj: Any, protocol: int | None = None) -> bool:
    return False


auto_register_for_pickling = _default_auto_register_for_pickling
DebugSerializationError: type[Exception] = Exception
DebugDeadlockError: type[Exception] = Exception
ReportSerializationError: Callable[[dict[str, Any]], None] | None = None
_report_guard = threading.local()
_verbose_serialization_warnings = False


def configure_picklers(
    auto_register: Any,
    placeholder_cls: type[UnpicklablePlaceholder] | None = None,
    debug_serialization_error: type[Exception] | None = None,
    debug_deadlock_error: type[Exception] | None = None,
    report_serialization_error: Callable[[dict[str, Any]], None] | None = None,
    logger_name: str | None = None,
    module_key: str | None = None,
) -> None:
    """Configure pickling helpers used by this module."""
    global auto_register_for_pickling
    global _unpicklable_placeholder_cls
    global DebugSerializationError
    global DebugDeadlockError
    global ReportSerializationError
    global logger
    global _module_key

    auto_register_for_pickling = auto_register
    if placeholder_cls is not None:
        _unpicklable_placeholder_cls = placeholder_cls
    if debug_serialization_error is not None:
        DebugSerializationError = debug_serialization_error
    if debug_deadlock_error is not None:
        DebugDeadlockError = debug_deadlock_error
    if report_serialization_error is not None:
        ReportSerializationError = report_serialization_error
    if logger_name is not None:
        logger = logging.getLogger(logger_name)
    if module_key is not None:
        _module_key = module_key


def set_verbose_serialization_warnings(enabled: bool) -> None:
    global _verbose_serialization_warnings
    _verbose_serialization_warnings = enabled
    pickling_warning = getattr(dill, "PicklingWarning", Warning)
    if enabled:
        warnings.filterwarnings("default", category=pickling_warning)
    else:
        warnings.filterwarnings("ignore", category=pickling_warning)


# Default to suppress pickling warnings unless explicitly enabled.
set_verbose_serialization_warnings(False)


def _truncate_text(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


def _safe_repr(obj: Any, *, max_length: int = MAX_REPR_LENGTH) -> str:
    try:
        text = repr(obj)
    except Exception as exc:  # noqa: BLE001
        text = f"<repr failed: {type(exc).__name__}: {exc}>"
    return _truncate_text(text, max_length)


def _safe_str(obj: Any, repr_text: str, *, max_length: int = MAX_REPR_LENGTH) -> str | None:
    try:
        text = str(obj)
    except Exception as exc:  # noqa: BLE001
        text = f"<str failed: {type(exc).__name__}: {exc}>"
    text = _truncate_text(text, max_length)
    if text == repr_text:
        return None
    return text


def _resolve_object_name(obj: Any) -> str:
    for attr in ("_cideldill_alias_name", "__name__", "name", "tool_name", "function_name"):
        try:
            value = getattr(obj, attr)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(value, str) and value:
            return value
    qualname = getattr(obj, "__qualname__", None)
    if isinstance(qualname, str) and qualname:
        return qualname
    obj_type = type(obj)
    return getattr(obj_type, "__qualname__", obj_type.__name__)


def _resolve_object_path(module: str, qualname: str) -> str:
    if module:
        return f"{module}.{qualname}"
    return qualname


def _format_traceback(error: Exception) -> tuple[str, list[dict[str, Any]]]:
    tb = getattr(error, "__traceback__", None)
    if tb is None:
        return "", []
    frames = traceback.extract_tb(tb)
    stack_trace: list[dict[str, Any]] = []
    for frame in frames:
        stack_trace.append({
            "filename": frame.filename,
            "lineno": frame.lineno,
            "function": frame.name,
            "code_context": frame.line.strip() if frame.line else None,
        })
    formatted = "".join(traceback.format_exception(type(error), error, tb))
    return formatted, stack_trace


def _report_serialization_error(
    obj: Any,
    error: Exception,
    attempts: list[str],
    *,
    depth: int,
    placeholder_bytes: bytes | None = None,
    placeholder_obj: Any | None = None,
) -> None:
    reporter = ReportSerializationError
    if reporter is None:
        return
    if getattr(_report_guard, "active", False):
        return
    _report_guard.active = True
    try:
        obj_type = type(obj)
        repr_text = _safe_repr(obj)
        object_name = _resolve_object_name(obj)
        formatted_tb, stack_trace = _format_traceback(error)
        report_payload = {
            "event_type": "pickle_error",
            "timestamp": time.time(),
            "object_type": f"{obj_type.__module__}.{getattr(obj_type, '__qualname__', obj_type.__name__)}",
            "object_name": object_name,
            "object_id": hex(id(obj)),
            "object_repr": repr_text,
            "error": f"{type(error).__name__}: {error}",
            "attempts": list(attempts),
            "traceback": _truncate_text(formatted_tb, 8000),
            "call_site": {
                "timestamp": time.time(),
                "stack_trace": stack_trace,
            },
        }
        if placeholder_bytes is not None:
            report_payload["placeholder_cid"] = hashlib.sha256(placeholder_bytes).hexdigest()
            report_payload["placeholder_data"] = base64.b64encode(placeholder_bytes).decode("ascii")
        if placeholder_obj is not None and hasattr(placeholder_obj, "to_dict"):
            try:
                report_payload["placeholder_summary"] = placeholder_obj.to_dict()
            except Exception:
                pass
        reporter(report_payload)
    except Exception:
        return
    finally:
        _report_guard.active = False


def _should_include_attr(name: str) -> bool:
    if name.startswith("__") and name.endswith("__"):
        return False
    return True


def _iter_attributes(obj: Any) -> Iterator[tuple[str, Any]]:
    """Yield (name, value) for accessible attributes.

    Only inspects __dict__ and __slots__ to avoid property side effects.
    """
    seen: set[str] = set()

    if hasattr(obj, "__dict__"):
        for name, value in obj.__dict__.items():
            if not _should_include_attr(name):
                continue
            seen.add(name)
            yield name, value

    for klass in type(obj).__mro__:
        slots = getattr(klass, "__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        for slot in slots:
            if slot in ("__dict__", "__weakref__"):
                continue
            if slot in seen or not _should_include_attr(slot):
                continue
            try:
                yield slot, getattr(obj, slot)
                seen.add(slot)
            except AttributeError:
                continue


def _is_snapshot_container_value(value: Any) -> bool:
    return isinstance(value, (dict, list, tuple, set, frozenset))


def _iter_snapshot_members(obj: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str):
                yield key, value
            else:
                yield f"[{_safe_repr(key, max_length=80)}]", value
        return

    if isinstance(obj, (list, tuple)):
        for idx, value in enumerate(obj):
            yield f"[{idx}]", value
        return

    if isinstance(obj, (set, frozenset)):
        for idx, value in enumerate(sorted(obj, key=lambda item: _safe_repr(item, max_length=80))):
            yield f"[{idx}]", value
        return

    yield from _iter_attributes(obj)


def _is_simple_snapshot_value(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool, bytes, type(None)))


def _minimal_placeholder(
    obj: Any,
    error: Exception,
    attempts: list[str],
    depth: int,
) -> UnpicklablePlaceholder:
    obj_type = type(obj)
    repr_text = _safe_repr(obj)
    str_text = _safe_str(obj, repr_text)
    object_name = _resolve_object_name(obj)
    object_path = _resolve_object_path(
        obj_type.__module__,
        getattr(obj_type, "__qualname__", obj_type.__name__),
    )
    placeholder_cls = _unpicklable_placeholder_cls
    return placeholder_cls(
        type_name=obj_type.__name__,
        module=obj_type.__module__,
        qualname=getattr(obj_type, "__qualname__", obj_type.__name__),
        object_name=object_name,
        object_path=object_path,
        object_id=hex(id(obj)),
        repr_text=repr_text,
        str_text=str_text,
        attributes={},
        failed_attributes={},
        pickle_error=f"{type(error).__name__}: {error}",
        pickle_attempts=list(attempts),
        capture_timestamp=time.time(),
        depth=depth,
    )


def _circular_ref_placeholder(obj: Any, depth: int) -> UnpicklablePlaceholder:
    obj_type = type(obj)
    repr_text = _safe_repr(obj)
    str_text = _safe_str(obj, repr_text)
    object_name = _resolve_object_name(obj)
    object_path = _resolve_object_path(
        obj_type.__module__,
        getattr(obj_type, "__qualname__", obj_type.__name__),
    )
    placeholder_cls = _unpicklable_placeholder_cls
    return placeholder_cls(
        type_name=obj_type.__name__,
        module=obj_type.__module__,
        qualname=getattr(obj_type, "__qualname__", obj_type.__name__),
        object_name=object_name,
        object_path=object_path,
        object_id=hex(id(obj)),
        repr_text=repr_text,
        str_text=str_text,
        attributes={},
        failed_attributes={},
        pickle_error="circular_reference",
        pickle_attempts=["circular_reference"],
        capture_timestamp=time.time(),
        depth=depth,
    )


def _build_snapshot(
    obj: Any,
    error: Exception,
    attempts: list[str],
    depth: int,
    max_depth: int,
    max_attributes: int,
    visited: set[int],
) -> UnpicklablePlaceholder:
    obj_type = type(obj)
    repr_text = _safe_repr(obj)
    str_text = _safe_str(obj, repr_text)
    object_name = _resolve_object_name(obj)
    object_path = _resolve_object_path(
        obj_type.__module__,
        getattr(obj_type, "__qualname__", obj_type.__name__),
    )

    attributes: dict[str, Any] = {}
    failed_attributes: dict[str, str] = {}

    visited.add(id(obj))

    items = list(_iter_snapshot_members(obj))
    for idx, (name, value) in enumerate(items):
        if idx >= max_attributes:
            remaining = len(items) - max_attributes
            if remaining > 0:
                failed_attributes["__skipped__"] = f"{remaining} more attributes skipped"
            break

        try:
            nested_bytes = _safe_dumps(
                value,
                depth=depth + 1,
                max_depth=max_depth,
                max_attributes=max_attributes,
                strict=False,
                _visited=visited,
            )
            nested_value = dill.loads(nested_bytes)
            if isinstance(nested_value, _unpicklable_placeholder_cls):
                attributes[name] = nested_value
                failed_attributes[name] = nested_value.pickle_error
            elif _is_simple_snapshot_value(nested_value):
                attributes[name] = nested_value
            elif _is_snapshot_container_value(nested_value):
                attributes[name] = nested_value
            else:
                attributes[name] = _safe_repr(nested_value)
        except Exception as exc:  # noqa: BLE001 - snapshotting should be best-effort
            failed_attributes[name] = f"{type(exc).__name__}: {exc}"

    placeholder_cls = _unpicklable_placeholder_cls
    return placeholder_cls(
        type_name=obj_type.__name__,
        module=obj_type.__module__,
        qualname=getattr(obj_type, "__qualname__", obj_type.__name__),
        object_name=object_name,
        object_path=object_path,
        object_id=hex(id(obj)),
        repr_text=repr_text,
        str_text=str_text,
        attributes=attributes,
        failed_attributes=failed_attributes,
        pickle_error=f"{type(error).__name__}: {error}",
        pickle_attempts=list(attempts),
        capture_timestamp=time.time(),
        depth=depth,
    )


def _try_pickle(obj: Any, attempts: list[str]) -> bytes:
    pickling_warning = getattr(dill, "PicklingWarning", Warning)

    def _dill_dumps_with_warnings(target: Any) -> bytes:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always", pickling_warning)
            data = dill.dumps(target, protocol=DILL_PROTOCOL)
        if _verbose_serialization_warnings and captured:
            for warn in captured:
                logger.debug("PicklingWarning: %s", warn.message)
            for warn in captured:
                warnings.warn(warn.message, category=pickling_warning, stacklevel=3)
        return data

    try:
        return _dill_dumps_with_warnings(obj)
    except Exception as exc:  # noqa: BLE001 - preserve original error context
        attempts.append(f"dill.dumps: {type(exc).__name__}: {exc}")
        first_error = exc

    if auto_register_for_pickling(obj, protocol=DILL_PROTOCOL):
        try:
            return _dill_dumps_with_warnings(obj)
        except Exception as exc:  # noqa: BLE001 - preserve original error context
            attempts.append(f"auto_register retry: {type(exc).__name__}: {exc}")
            raise exc

    attempts.append("auto_register: no reducer found")
    raise first_error


def _safe_dumps(
    obj: Any,
    *,
    depth: int = 0,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_attributes: int = DEFAULT_MAX_ATTRIBUTES,
    strict: bool = False,
    _visited: set[int] | None = None,
) -> bytes:
    if _visited is None:
        _visited = set()
    if id(obj) in _visited:
        placeholder = _circular_ref_placeholder(obj, depth)
        return dill.dumps(placeholder, protocol=DILL_PROTOCOL)

    attempts: list[str] = []
    try:
        return _try_pickle(obj, attempts)
    except Exception as exc:  # noqa: BLE001 - preserve original error context
        last_error = exc

    if strict:
        raise DebugSerializationError(obj, last_error) from last_error

    if depth >= max_depth:
        placeholder = _minimal_placeholder(obj, last_error, attempts, depth)
    else:
        placeholder = _build_snapshot(
            obj,
            last_error,
            attempts,
            depth,
            max_depth,
            max_attributes,
            _visited,
        )

    pickled: bytes | None = None
    placeholder_obj: Any | None = None
    try:
        pickled = dill.dumps(placeholder, protocol=DILL_PROTOCOL)
        placeholder_obj = placeholder
    except Exception as exc:  # noqa: BLE001 - extremely defensive
        attempts.append(f"placeholder.dumps: {type(exc).__name__}: {exc}")
        minimal = _minimal_placeholder(obj, last_error, attempts, depth)
        try:
            pickled = dill.dumps(minimal, protocol=DILL_PROTOCOL)
            placeholder_obj = minimal
        except Exception as minimal_exc:  # noqa: BLE001 - final fallback
            attempts.append(f"minimal_placeholder.dumps: {type(minimal_exc).__name__}: {minimal_exc}")
            fallback_payload = {
                "type": type(obj).__qualname__,
                _module_key: type(obj).__module__,
                "repr": _safe_repr(obj),
                "error": str(last_error),
                "attempts": list(attempts),
                "timestamp": time.time(),
            }
            pickled = dill.dumps(fallback_payload, protocol=DILL_PROTOCOL)
            placeholder_obj = None

    _report_serialization_error(
        obj,
        last_error,
        attempts,
        depth=depth,
        placeholder_bytes=pickled,
        placeholder_obj=placeholder_obj,
    )

    logger.info(
        "Serialization degraded to placeholder",
        extra={
            "type": type(obj).__qualname__,
            _module_key: type(obj).__module__,
            "object_name": _resolve_object_name(obj),
            "error": str(last_error),
            "captured_attrs": len(placeholder.attributes),
            "failed_attrs": list(placeholder.failed_attributes.keys()),
        },
    )

    return pickled


def serialize(obj: Any, *, strict: bool = False) -> bytes:
    """Serialize any Python object to bytes."""
    return _safe_dumps(obj, strict=strict)


def deserialize(data: bytes) -> Any:
    """Deserialize bytes back to Python object."""
    return dill.loads(data)


def compute_cid(obj: Any) -> str:
    """Compute the CID for any Python object."""
    pickled = _safe_dumps(obj)
    return hashlib.sha256(pickled).hexdigest()


@dataclass
class SerializedObject:
    """Result of serializing an object for transmission."""

    cid: str
    data: Optional[bytes]
    data_base64: Optional[str]


class CIDCache:
    """LRU cache tracking CIDs that have been sent to the server."""

    MAX_SIZE = 10_000

    def __init__(self) -> None:
        self._cache: OrderedDict[str, bool] = OrderedDict()
        self._lock = threading.Lock()

    def mark_sent(self, cid: str) -> None:
        """Mark a CID as having been sent to the server."""
        with self._lock:
            if cid in self._cache:
                self._cache.move_to_end(cid)
            else:
                self._cache[cid] = True
                if len(self._cache) > self.MAX_SIZE:
                    self._cache.popitem(last=False)

    def is_sent(self, cid: str) -> bool:
        """Check if a CID has been sent to the server."""
        with self._lock:
            if cid in self._cache:
                self._cache.move_to_end(cid)
                return True
            return False

    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()


class Serializer:
    """Serialize objects with CID-based deduplication."""

    def __init__(self, cache: Optional[CIDCache] = None, *, lock_timeout_s: float = 30.0) -> None:
        self._cache = cache or CIDCache()
        self._lock = threading.RLock()
        self._lock_timeout_s = lock_timeout_s

    def _acquire_lock(self, obj: Any) -> None:
        acquired = self._lock.acquire(timeout=self._lock_timeout_s)
        if not acquired:
            raise DebugDeadlockError(
                "Serializer lock deadlock detected while serializing "
                f"{type(obj).__name__}. This usually means a DebugProxy object "
                "was encountered during argument serialization, causing "
                "re-entrant record_call_start. Avoid passing DebugProxy-wrapped "
                "objects as arguments to async_debug_call or other proxied methods."
            )

    def serialize(self, obj: Any) -> SerializedObject:
        """Serialize an object and compute its CID."""
        self._acquire_lock(obj)
        try:
            pickled = _safe_dumps(obj)
            cid = hashlib.sha256(pickled).hexdigest()
            if self._cache.is_sent(cid):
                return SerializedObject(cid=cid, data=None, data_base64=None)
            self._cache.mark_sent(cid)
            data_base64 = base64.b64encode(pickled).decode("ascii")
            return SerializedObject(cid=cid, data=pickled, data_base64=data_base64)
        finally:
            self._lock.release()

    def force_serialize_with_data(self, obj: Any) -> SerializedObject:
        """Serialize an object without consulting the cache."""
        self._acquire_lock(obj)
        try:
            pickled = _safe_dumps(obj)
            cid = hashlib.sha256(pickled).hexdigest()
            data_base64 = base64.b64encode(pickled).decode("ascii")
            return SerializedObject(cid=cid, data=pickled, data_base64=data_base64)
        finally:
            self._lock.release()

    @staticmethod
    def deserialize_base64(data_base64: str) -> Any:
        """Deserialize base64-encoded dill pickle."""
        pickled = base64.b64decode(data_base64)
        return dill.loads(pickled)

    @staticmethod
    def verify_cid(data_base64: str, expected_cid: str) -> bool:
        """Verify that data matches the expected CID."""
        pickled = base64.b64decode(data_base64)
        actual_cid = hashlib.sha256(pickled).hexdigest()
        return actual_cid == expected_cid
