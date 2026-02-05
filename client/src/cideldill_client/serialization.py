"""Serialization utilities using dill with CID-based deduplication."""

from __future__ import annotations

from typing import Any, Callable

from . import serialization_common as _common
from .exceptions import DebugSerializationError

try:
    from .custom_picklers import (
        UnpicklablePlaceholder,
        auto_register_for_pickling,
        set_verbose_serialization_warnings as _set_custom_verbose_warnings,
    )
except Exception:  # pragma: no cover - fallback for environments without custom_picklers

    from .serialization_common import UnpicklablePlaceholder

    def auto_register_for_pickling(obj: Any, protocol: int | None = None) -> bool:
        return False

    def _set_custom_verbose_warnings(enabled: bool) -> None:
        return None


_reporter: Callable[[dict[str, Any]], None] | None = None


def set_serialization_error_reporter(
    reporter: Callable[[dict[str, Any]], None] | None,
) -> None:
    global _reporter
    _reporter = reporter


def set_verbose_serialization_warnings(enabled: bool) -> None:
    _configure()
    _common.set_verbose_serialization_warnings(enabled)
    _set_custom_verbose_warnings(enabled)


def _configure() -> None:
    _common.configure_picklers(
        auto_register_for_pickling,
        UnpicklablePlaceholder,
        DebugSerializationError,
        report_serialization_error=_reporter,
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
    "set_serialization_error_reporter",
    "set_verbose_serialization_warnings",
]
