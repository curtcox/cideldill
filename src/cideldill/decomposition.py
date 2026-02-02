"""Object decomposition and reassembly utilities."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Dict

import dill

from .exceptions import CIDNotFoundError
from .serialization import CIDRef, DILL_PROTOCOL, _safe_dumps


@dataclass
class DecomposedObject:
    """An object decomposed into a shell with CID references."""

    cid: str
    shell_data: str
    components: Dict[str, "DecomposedObject"]


class ObjectDecomposer:
    """Decomposes objects into components with embedded CID references."""

    DECOMPOSE_TYPES = (list, tuple, dict, set, frozenset)
    MIN_DECOMPOSE_SIZE = 1024

    def decompose(self, obj: Any) -> DecomposedObject:
        """Decompose an object into a shell with CID references."""
        pickled = _safe_dumps(obj)
        if len(pickled) < self.MIN_DECOMPOSE_SIZE:
            return self._make_leaf(obj, pickled)

        if isinstance(obj, dict):
            return self._decompose_dict(obj)
        if isinstance(obj, (list, tuple)):
            return self._decompose_sequence(obj)
        if isinstance(obj, (set, frozenset)):
            return self._decompose_set(obj)
        if hasattr(obj, "__dict__"):
            return self._decompose_instance(obj)

        return self._make_leaf(obj, pickled)

    def _make_leaf(self, obj: Any, pickled: bytes) -> DecomposedObject:
        cid = self._compute_cid(pickled)
        shell_data = base64.b64encode(pickled).decode("ascii")
        return DecomposedObject(cid=cid, shell_data=shell_data, components={})

    def _decompose_dict(self, obj: dict[Any, Any]) -> DecomposedObject:
        shell: dict[Any, Any] = {}
        components: Dict[str, DecomposedObject] = {}
        for key, value in obj.items():
            new_key, key_components = self._maybe_replace_with_ref(key)
            new_value, value_components = self._maybe_replace_with_ref(value)
            components.update(key_components)
            components.update(value_components)
            shell[new_key] = new_value
        return self._make_shell(shell, components)

    def _decompose_sequence(self, obj: list[Any] | tuple[Any, ...]) -> DecomposedObject:
        items: list[Any] = []
        components: Dict[str, DecomposedObject] = {}
        for item in obj:
            new_item, item_components = self._maybe_replace_with_ref(item)
            components.update(item_components)
            items.append(new_item)
        shell = tuple(items) if isinstance(obj, tuple) else items
        return self._make_shell(shell, components)

    def _decompose_set(self, obj: set[Any] | frozenset[Any]) -> DecomposedObject:
        items: list[Any] = []
        components: Dict[str, DecomposedObject] = {}
        for item in obj:
            new_item, item_components = self._maybe_replace_with_ref(item)
            components.update(item_components)
            items.append(new_item)
        shell = set(items)
        if isinstance(obj, frozenset):
            shell = frozenset(shell)
        return self._make_shell(shell, components)

    def _decompose_instance(self, obj: Any) -> DecomposedObject:
        new_dict_decomposed = self._decompose_dict(obj.__dict__)
        shell_obj = obj
        shell_obj.__dict__.update(
            dill.loads(base64.b64decode(new_dict_decomposed.shell_data))
        )
        pickled = _safe_dumps(shell_obj)
        cid = self._compute_cid(pickled)
        shell_data = base64.b64encode(pickled).decode("ascii")
        return DecomposedObject(
            cid=cid, shell_data=shell_data, components=new_dict_decomposed.components
        )

    def _maybe_replace_with_ref(self, obj: Any) -> tuple[Any, Dict[str, DecomposedObject]]:
        pickled = _safe_dumps(obj)
        if len(pickled) < self.MIN_DECOMPOSE_SIZE:
            return obj, {}
        decomposed = self.decompose(obj)
        return CIDRef(decomposed.cid), {decomposed.cid: decomposed}

    def _make_shell(
        self, shell: Any, components: Dict[str, DecomposedObject]
    ) -> DecomposedObject:
        pickled = _safe_dumps(shell)
        cid = self._compute_cid(pickled)
        shell_data = base64.b64encode(pickled).decode("ascii")
        return DecomposedObject(cid=cid, shell_data=shell_data, components=components)

    @staticmethod
    def _compute_cid(pickled: bytes) -> str:
        import hashlib

        return hashlib.sha512(pickled).hexdigest()


def reassemble(decomposed: DecomposedObject, store: "CIDStore") -> Any:
    """Reassemble a decomposed object by resolving CID references."""
    shell = dill.loads(base64.b64decode(decomposed.shell_data))
    return _resolve_refs(shell, store)


def _resolve_refs(obj: Any, store: "CIDStore") -> Any:
    """Recursively resolve CIDRef markers."""
    if isinstance(obj, CIDRef):
        data = store.get(obj.cid)
        if data is None:
            raise CIDNotFoundError(obj.cid)
        resolved = dill.loads(data)
        return _resolve_refs(resolved, store)
    if isinstance(obj, dict):
        return {
            _resolve_refs(key, store): _resolve_refs(value, store)
            for key, value in obj.items()
        }
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


class CIDStore:
    """Protocol for CID store implementations."""

    def get(self, cid: str) -> Any:
        raise NotImplementedError
