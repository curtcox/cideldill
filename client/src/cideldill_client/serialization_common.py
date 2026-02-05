"""Shared serialization utilities using dill with CID-based deduplication."""

from __future__ import annotations

import base64
import hashlib
import logging
import threading
import time
import traceback
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
ReportSerializationError: Callable[[dict[str, Any]], None] | None = None
_report_guard = threading.local()


def configure_picklers(
    auto_register: Any,
    placeholder_cls: type[UnpicklablePlaceholder] | None = None,
    debug_serialization_error: type[Exception] | None = None,
    report_serialization_error: Callable[[dict[str, Any]], None] | None = None,
    logger_name: str | None = None,
    module_key: str | None = None,
) -> None:
    """Configure pickling helpers used by this module."""
    global auto_register_for_pickling
    global _unpicklable_placeholder_cls
    global DebugSerializationError
    global ReportSerializationError
    global logger
    global _module_key

    auto_register_for_pickling = auto_register
    if placeholder_cls is not None:
        _unpicklable_placeholder_cls = placeholder_cls
    if debug_serialization_error is not None:
        DebugSerializationError = debug_serialization_error
    if report_serialization_error is not None:
        ReportSerializationError = report_serialization_error
    if logger_name is not None:
        logger = logging.getLogger(logger_name)
    if module_key is not None:
        _module_key = module_key


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
        formatted_tb, stack_trace = _format_traceback(error)
        report_payload = {
            "event_type": "pickle_error",
            "timestamp": time.time(),
            "object_type": f"{obj_type.__module__}.{getattr(obj_type, '__qualname__', obj_type.__name__)}",
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
    placeholder_cls = _unpicklable_placeholder_cls
    return placeholder_cls(
        type_name=obj_type.__name__,
        module=obj_type.__module__,
        qualname=getattr(obj_type, "__qualname__", obj_type.__name__),
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
    placeholder_cls = _unpicklable_placeholder_cls
    return placeholder_cls(
        type_name=obj_type.__name__,
        module=obj_type.__module__,
        qualname=getattr(obj_type, "__qualname__", obj_type.__name__),
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

    attributes: dict[str, Any] = {}
    failed_attributes: dict[str, str] = {}

    visited.add(id(obj))

    items = list(_iter_attributes(obj))
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
            else:
                attributes[name] = _safe_repr(nested_value)
        except Exception as exc:  # noqa: BLE001 - snapshotting should be best-effort
            failed_attributes[name] = f"{type(exc).__name__}: {exc}"

    placeholder_cls = _unpicklable_placeholder_cls
    return placeholder_cls(
        type_name=obj_type.__name__,
        module=obj_type.__module__,
        qualname=getattr(obj_type, "__qualname__", obj_type.__name__),
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
    try:
        return dill.dumps(obj, protocol=DILL_PROTOCOL)
    except Exception as exc:  # noqa: BLE001 - preserve original error context
        attempts.append(f"dill.dumps: {type(exc).__name__}: {exc}")
        first_error = exc

    if auto_register_for_pickling(obj, protocol=DILL_PROTOCOL):
        try:
            return dill.dumps(obj, protocol=DILL_PROTOCOL)
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

    _report_serialization_error(obj, last_error, attempts, depth=depth)

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

    logger.info(
        "Serialization degraded to placeholder",
        extra={
            "type": type(obj).__qualname__,
            _module_key: type(obj).__module__,
            "error": str(last_error),
            "captured_attrs": len(placeholder.attributes),
            "failed_attrs": list(placeholder.failed_attributes.keys()),
        },
    )

    try:
        return dill.dumps(placeholder, protocol=DILL_PROTOCOL)
    except Exception as exc:  # noqa: BLE001 - extremely defensive
        attempts.append(f"placeholder.dumps: {type(exc).__name__}: {exc}")
        minimal = _minimal_placeholder(obj, last_error, attempts, depth)
        try:
            return dill.dumps(minimal, protocol=DILL_PROTOCOL)
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
            return dill.dumps(fallback_payload, protocol=DILL_PROTOCOL)


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

    def __init__(self, cache: Optional[CIDCache] = None) -> None:
        self._cache = cache or CIDCache()
        self._lock = threading.Lock()

    def serialize(self, obj: Any) -> SerializedObject:
        """Serialize an object and compute its CID."""
        with self._lock:
            pickled = _safe_dumps(obj)
            cid = hashlib.sha256(pickled).hexdigest()
            if self._cache.is_sent(cid):
                return SerializedObject(cid=cid, data=None, data_base64=None)
            self._cache.mark_sent(cid)
            data_base64 = base64.b64encode(pickled).decode("ascii")
            return SerializedObject(cid=cid, data=pickled, data_base64=data_base64)

    def force_serialize_with_data(self, obj: Any) -> SerializedObject:
        """Serialize an object without consulting the cache."""
        with self._lock:
            pickled = _safe_dumps(obj)
            cid = hashlib.sha256(pickled).hexdigest()
            data_base64 = base64.b64encode(pickled).decode("ascii")
            return SerializedObject(cid=cid, data=pickled, data_base64=data_base64)

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
