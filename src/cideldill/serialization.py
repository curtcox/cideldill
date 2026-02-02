"""Serialization utilities using dill with CID-based deduplication."""

from __future__ import annotations

import base64
import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import dill

from .exceptions import CIDNotFoundError, DebugSerializationError
from .cid_store import CIDStore

DILL_PROTOCOL = 4

dill.settings["recurse"] = True


@dataclass(frozen=True)
class CIDRef:
    """Marker indicating a reference to another object by CID."""

    cid: str

    def __repr__(self) -> str:
        return f"CIDRef({self.cid[:16]}...)"

    def __hash__(self) -> int:
        return hash(self.cid)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CIDRef):
            return self.cid == other.cid
        return False


@dill.register(CIDRef)
def _pickle_cidref(pickler: dill.Pickler, obj: CIDRef) -> None:
    pickler.save_reduce(CIDRef, (obj.cid,), obj=obj)


def _safe_dumps(obj: Any) -> bytes:
    try:
        return dill.dumps(obj, protocol=DILL_PROTOCOL)
    except Exception as exc:  # noqa: BLE001 - preserve original error context
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
    return hashlib.sha512(pickled).hexdigest()


@dataclass
class SerializedObject:
    """Result of serializing an object (possibly decomposed)."""

    cid: str
    data: Optional[bytes]
    data_base64: Optional[str]
    components: Dict[str, "SerializedObject"]


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
    """Serialize objects with CID-based deduplication and decomposition."""

    MIN_DECOMPOSE_SIZE = 1024

    def __init__(self, cache: Optional[CIDCache] = None) -> None:
        self._cache = cache or CIDCache()
        self._lock = threading.Lock()

    def serialize(self, obj: Any, decompose: bool = True) -> SerializedObject:
        """Serialize an object and compute its CID."""
        with self._lock:
            pickled = _safe_dumps(obj)
            cid = hashlib.sha512(pickled).hexdigest()

            components: Dict[str, SerializedObject] = {}
            if decompose and len(pickled) >= self.MIN_DECOMPOSE_SIZE:
                obj, components = self._decompose(obj, visited=set())
                pickled = _safe_dumps(obj)
                cid = hashlib.sha512(pickled).hexdigest()

            if self._cache.is_sent(cid):
                return SerializedObject(cid=cid, data=None, data_base64=None, components={})

            self._cache.mark_sent(cid)
            data_base64 = base64.b64encode(pickled).decode("ascii")

            return SerializedObject(
                cid=cid,
                data=pickled,
                data_base64=data_base64,
                components=components,
            )

    def force_serialize_with_data(
        self, obj: Any, decompose: bool = True
    ) -> SerializedObject:
        """Serialize an object without consulting the cache."""
        with self._lock:
            pickled = _safe_dumps(obj)
            cid = hashlib.sha512(pickled).hexdigest()

            components: Dict[str, SerializedObject] = {}
            if decompose and len(pickled) >= self.MIN_DECOMPOSE_SIZE:
                obj, components = self._decompose(obj, visited=set())
                pickled = _safe_dumps(obj)
                cid = hashlib.sha512(pickled).hexdigest()

            data_base64 = base64.b64encode(pickled).decode("ascii")
            return SerializedObject(
                cid=cid,
                data=pickled,
                data_base64=data_base64,
                components=components,
            )

    def _decompose(
        self, obj: Any, visited: set[int]
    ) -> Tuple[Any, Dict[str, SerializedObject]]:
        components: Dict[str, SerializedObject] = {}

        obj_id = id(obj)
        if obj_id in visited:
            return obj, components
        visited.add(obj_id)

        if isinstance(obj, dict):
            new_dict: dict[Any, Any] = {}
            for key, value in obj.items():
                new_key, key_components = self._maybe_replace_with_ref(
                    key, components, visited
                )
                new_value, value_components = self._maybe_replace_with_ref(
                    value, components, visited
                )
                components.update(key_components)
                components.update(value_components)
                new_dict[new_key] = new_value
            return new_dict, components

        if isinstance(obj, (list, tuple)):
            new_items = []
            for item in obj:
                new_item, item_components = self._maybe_replace_with_ref(
                    item, components, visited
                )
                components.update(item_components)
                new_items.append(new_item)
            return (tuple(new_items) if isinstance(obj, tuple) else new_items), components

        if isinstance(obj, (set, frozenset)):
            new_items = []
            for item in obj:
                new_item, item_components = self._maybe_replace_with_ref(
                    item, components, visited
                )
                components.update(item_components)
                new_items.append(new_item)
            new_set = set(new_items)
            if isinstance(obj, frozenset):
                return frozenset(new_set), components
            return new_set, components

        if hasattr(obj, "__dict__"):
            new_dict, dict_components = self._decompose(obj.__dict__, visited)
            obj.__dict__.update(new_dict)
            components.update(dict_components)
            return obj, components

        return obj, components

    def _maybe_replace_with_ref(
        self, obj: Any, components: Dict[str, SerializedObject], visited: set[int]
    ) -> Tuple[Any, Dict[str, SerializedObject]]:
        obj_id = id(obj)
        if obj_id in visited:
            return obj, {}

        pickled = _safe_dumps(obj)
        if len(pickled) < self.MIN_DECOMPOSE_SIZE:
            return obj, {}

        serialized = self.serialize(obj, decompose=True)
        components[serialized.cid] = serialized
        return CIDRef(serialized.cid), {serialized.cid: serialized}

    def to_json_dict(self, obj: Any) -> dict[str, Any]:
        """Serialize an object to a JSON-compatible dict."""
        result = self.serialize(obj)
        output: dict[str, Any] = {"cid": result.cid}
        if result.data_base64:
            output["data"] = result.data_base64
        if result.components:
            output["components"] = {
                cid: self._serialized_to_dict(component)
                for cid, component in result.components.items()
                if component.data_base64
            }
        return output

    def _serialized_to_dict(self, serialized: SerializedObject) -> dict[str, Any]:
        data: dict[str, Any] = {"cid": serialized.cid}
        if serialized.data_base64:
            data["data"] = serialized.data_base64
        return data

    @staticmethod
    def deserialize(data_base64: str) -> Any:
        """Deserialize base64-encoded dill pickle."""
        pickled = base64.b64decode(data_base64)
        return dill.loads(pickled)

    @staticmethod
    def compute_cid(obj: Any) -> str:
        """Compute CID without full serialization tracking."""
        pickled = _safe_dumps(obj)
        return hashlib.sha512(pickled).hexdigest()

    @staticmethod
    def verify_cid(data_base64: str, expected_cid: str) -> bool:
        """Verify that data matches the expected CID."""
        pickled = base64.b64decode(data_base64)
        actual_cid = hashlib.sha512(pickled).hexdigest()
        return actual_cid == expected_cid


def process_request_object(obj_dict: dict[str, Any], store: CIDStore) -> Any:
    """Process an object from a request, handling decomposition."""
    cid = obj_dict["cid"]

    if "components" in obj_dict:
        for comp_cid, comp_data in obj_dict["components"].items():
            if "data" in comp_data:
                data = base64.b64decode(comp_data["data"])
                store.store(comp_cid, data)

    if "data" in obj_dict:
        data = base64.b64decode(obj_dict["data"])
        store.store(cid, data)
        shell = dill.loads(data)
    else:
        data = store.get(cid)
        if data is None:
            raise CIDNotFoundError(cid)
        shell = dill.loads(data)

    return _resolve_refs(shell, store)


def _resolve_refs(obj: Any, store: CIDStore) -> Any:
    """Recursively resolve CIDRef markers."""
    if isinstance(obj, CIDRef):
        data = store.get(obj.cid)
        if data is None:
            raise CIDNotFoundError(obj.cid)
        resolved = dill.loads(data)
        return _resolve_refs(resolved, store)
    if isinstance(obj, dict):
        return {_resolve_refs(key, store): _resolve_refs(value, store) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_resolve_refs(item, store) for item in obj]
    if isinstance(obj, tuple):
        return tuple(_resolve_refs(item, store) for item in obj)
    if isinstance(obj, (set, frozenset)):
        resolved = {_resolve_refs(item, store) for item in obj}
        return frozenset(resolved) if isinstance(obj, frozenset) else resolved
    if hasattr(obj, "__dict__"):
        for key, value in list(obj.__dict__.items()):
            obj.__dict__[key] = _resolve_refs(value, store)
        return obj
    return obj
