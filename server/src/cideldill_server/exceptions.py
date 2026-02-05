"""Custom exceptions for CID el Dill debugging."""

from __future__ import annotations

from typing import Any


class DebugError(Exception):
    """Base class for debugging errors."""


class DebugSerializationError(DebugError):
    """Raised when an object cannot be serialized with dill."""

    def __init__(self, obj: Any, original_error: Exception) -> None:
        self.obj = obj
        self.original_error = original_error
        obj_type = type(obj)
        obj_module = getattr(obj_type, "__module__", "<unknown>")
        obj_qualname = getattr(obj_type, "__qualname__", obj_type.__name__)
        obj_id = hex(id(obj))
        try:
            obj_repr = repr(obj)
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            obj_repr = "<repr failed>"
        if len(obj_repr) > 300:
            obj_repr = f"{obj_repr[:297]}..."
        message = (
            "Cannot serialize object with dill.\n"
            f"Object type: {obj_module}.{obj_qualname}\n"
            f"Object id: {obj_id}\n"
            f"Object repr: {obj_repr}\n"
            f"Original error: {original_error}\n"
            "Options:\n"
            "1. Provide a custom pickler or reducer for this type.\n"
            "2. Avoid sending this object to the debugger (wrap/return a simpler type).\n"
            "3. Disable debugging for this call path or object.\n"
        )
        super().__init__(message)


class DebugServerError(DebugError):
    """Raised when the debug server is unreachable or returns an error."""


class DebugTimeoutError(DebugError):
    """Raised when polling the debug server times out."""


class DebugProtocolError(DebugError):
    """Raised when the debug protocol response is malformed."""


class DebugCIDNotFoundError(DebugError):
    """Raised when a CID is missing on the server."""

    def __init__(self, cid: str) -> None:
        self.cid = cid
        super().__init__(f"CID not found: {cid[:32]}...")


class DebugCIDMismatchError(DebugError):
    """Raised when CID data does not match its claimed hash."""

