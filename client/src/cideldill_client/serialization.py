"""Serialization utilities using dill with CID-based deduplication."""

from __future__ import annotations

import base64
import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional

import dill

from .custom_picklers import auto_register_for_pickling
from .exceptions import DebugSerializationError

DILL_PROTOCOL = 4

dill.settings["recurse"] = True


def _safe_dumps(obj: Any) -> bytes:
    try:
        return dill.dumps(obj, protocol=DILL_PROTOCOL)
    except Exception as exc:  # noqa: BLE001 - preserve original error context
        if auto_register_for_pickling(obj, protocol=DILL_PROTOCOL):
            try:
                return dill.dumps(obj, protocol=DILL_PROTOCOL)
            except Exception as second_exc:  # noqa: BLE001
                raise DebugSerializationError(obj, second_exc) from second_exc
        raise DebugSerializationError(obj, exc) from exc


def serialize(obj: Any) -> bytes:
    """Serialize any Python object to bytes."""
    return _safe_dumps(obj)


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
