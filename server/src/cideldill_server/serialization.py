"""Serialization utilities using dill with CID-based deduplication."""

from __future__ import annotations

from typing import Any

from . import serialization_common as _common
from .exceptions import DebugDeadlockError, DebugSerializationError

try:
    from .custom_picklers import UnpicklablePlaceholder, auto_register_for_pickling
except Exception:  # pragma: no cover - fallback for environments without custom_picklers

    from .serialization_common import UnpicklablePlaceholder

    def auto_register_for_pickling(obj: Any, protocol: int | None = None) -> bool:
        return False


def _configure() -> None:
    _common.configure_picklers(
        auto_register_for_pickling,
        UnpicklablePlaceholder,
        DebugSerializationError,
        DebugDeadlockError,
        logger_name=__name__,
        module_key="object_module",
    )


def serialize(obj: Any, *, strict: bool = False) -> bytes:
    _configure()
    return _common.serialize(obj, strict=strict)


def deserialize(data: bytes) -> Any:
    _configure()
    return _common.deserialize(data)


def compute_cid(obj: Any) -> str:
    _configure()
    return _common.compute_cid(obj)


def _safe_dumps(
    obj: Any,
    *,
    depth: int = 0,
    max_depth: int = _common.DEFAULT_MAX_DEPTH,
    max_attributes: int = _common.DEFAULT_MAX_ATTRIBUTES,
    strict: bool = False,
    _visited: set[int] | None = None,
) -> bytes:
    _configure()
    return _common._safe_dumps(
        obj,
        depth=depth,
        max_depth=max_depth,
        max_attributes=max_attributes,
        strict=strict,
        _visited=_visited,
    )


SerializedObject = _common.SerializedObject


class CIDCache(_common.CIDCache):
    pass


class Serializer(_common.Serializer):
    def serialize(self, obj: Any) -> _common.SerializedObject:
        _configure()
        return super().serialize(obj)

    def force_serialize_with_data(self, obj: Any) -> _common.SerializedObject:
        _configure()
        return super().force_serialize_with_data(obj)

    @staticmethod
    def deserialize_base64(data_base64: str) -> Any:
        _configure()
        return _common.Serializer.deserialize_base64(data_base64)

    @staticmethod
    def verify_cid(data_base64: str, expected_cid: str) -> bool:
        _configure()
        return _common.Serializer.verify_cid(data_base64, expected_cid)


__all__ = [
    "CIDCache",
    "SerializedObject",
    "Serializer",
    "compute_cid",
    "deserialize",
    "serialize",
    "_safe_dumps",
]
