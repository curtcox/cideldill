"""Custom exceptions for serialization and CID storage."""

from typing import Any


class SerializationError(Exception):
    """Base class for serialization errors."""


class DebugSerializationError(SerializationError):
    """Raised when an object cannot be serialized with dill."""

    def __init__(self, obj: Any, original_error: Exception) -> None:
        self.obj = obj
        self.original_error = original_error
        message = f"Cannot serialize {type(obj).__name__}: {original_error}"
        super().__init__(message)


class CIDNotFoundError(SerializationError):
    """Raised when a CID is not found on the server."""

    def __init__(self, cid: str) -> None:
        self.cid = cid
        super().__init__(f"CID not found: {cid[:32]}...")


class CIDMismatchError(SerializationError):
    """Raised when data doesn't match its claimed CID."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
