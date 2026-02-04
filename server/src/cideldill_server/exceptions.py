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
        message = f"Cannot serialize {type(obj).__name__}: {original_error}"
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

