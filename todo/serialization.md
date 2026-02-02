# Serialization Mechanism Specification

## Overview

This document specifies the exact serialization mechanism for the cideldill debugging API. All objects (arguments, return values, exceptions, proxied targets) are serialized using **dill** and identified by their **CID (Content Identifier)**.

## Design Decisions (Resolved)

| Question | Decision | Rationale |
|----------|----------|-----------|
| Dill protocol | **Fixed version (4)** | Cross-version compatibility |
| Hash algorithm | **SHA-512 only** | Stronger collision resistance, 128-char hex CID |
| Large object handling | **No limit; decompose into components** | Better deduplication via embedded CIDs |
| Partial failure | **Fail entire request** | Consistent with fail-closed policy |
| CID store eviction | **No limit (store forever)** | Debugging data is valuable; storage is cheap |
| Dill settings | **`recurse=True`** | Better closure/nested function handling |

---

## Core Components

### 1. Dill Serialization

**Why dill?**
- Handles more Python objects than standard pickle (lambdas, closures, nested functions)
- Can serialize by reference or by value
- Actively maintained, widely used

**Configuration:**
```python
import dill

# Use fixed protocol version for compatibility
DILL_PROTOCOL = 4

# Enable recursive descent for better closure handling
dill.settings['recurse'] = True

def serialize(obj) -> bytes:
    """Serialize any Python object to bytes."""
    return dill.dumps(obj, protocol=DILL_PROTOCOL)

def deserialize(data: bytes) -> Any:
    """Deserialize bytes back to Python object."""
    return dill.loads(data)
```

### 2. CID Computation

A **CID (Content Identifier)** is a **SHA-512** hash of the dill-pickled representation of an object.

```python
import hashlib
import dill

DILL_PROTOCOL = 4

def compute_cid(obj) -> str:
    """
    Compute the CID for any Python object.

    Returns a 128-character hex string (SHA-512).
    """
    pickled = dill.dumps(obj, protocol=DILL_PROTOCOL)
    return hashlib.sha512(pickled).hexdigest()
```

**Properties:**
- **Deterministic**: Same object always produces same CID
- **Collision-resistant**: SHA-512 provides 256-bit collision resistance
- **Content-addressed**: CID depends only on content, not on when/where computed
- **Fixed length**: Always 128 hex characters

### 3. Object Decomposition

Large or composite objects are **decomposed into smaller components**, each with their own CID. This enables better deduplication - if two objects share a component, that component is only stored once.

#### Decomposition Strategy

```python
@dataclass
class DecomposedObject:
    """An object decomposed into a shell with CID references."""
    cid: str                           # CID of this decomposed form
    shell_data: str                    # Base64 dill pickle of shell (with CID refs)
    components: Dict[str, 'DecomposedObject']  # CID -> decomposed component

class ObjectDecomposer:
    """
    Decomposes objects into components with embedded CID references.
    """

    # Types that should be decomposed into components
    DECOMPOSE_TYPES = (list, tuple, dict, set, frozenset)

    # Minimum size (bytes) before decomposition is attempted
    MIN_DECOMPOSE_SIZE = 1024  # 1KB

    def decompose(self, obj: Any) -> DecomposedObject:
        """
        Decompose an object into a shell with CID references.

        For small objects or atomic types, returns the object as-is.
        For large composite objects, replaces components with CID references.
        """
        # First, serialize to check size
        pickled = dill.dumps(obj, protocol=DILL_PROTOCOL)

        if len(pickled) < self.MIN_DECOMPOSE_SIZE:
            # Small object - don't decompose
            return self._make_leaf(obj, pickled)

        if isinstance(obj, dict):
            return self._decompose_dict(obj)
        elif isinstance(obj, (list, tuple)):
            return self._decompose_sequence(obj)
        elif isinstance(obj, (set, frozenset)):
            return self._decompose_set(obj)
        elif hasattr(obj, '__dict__'):
            return self._decompose_instance(obj)
        else:
            # Can't decompose - treat as leaf
            return self._make_leaf(obj, pickled)
```

#### CID Reference Marker

When an object is decomposed, components are replaced with a special **CID reference marker**:

```python
@dataclass
class CIDRef:
    """Marker indicating a reference to another object by CID."""
    cid: str

    def __repr__(self):
        return f"CIDRef({self.cid[:16]}...)"
```

#### Decomposition Examples

**List decomposition:**
```python
# Original object
data = [large_object_a, large_object_b, small_value]

# After decomposition (conceptually):
# - large_object_a -> CID "abc123..."
# - large_object_b -> CID "def456..."
# - small_value stays inline (too small to decompose)

shell = [CIDRef("abc123..."), CIDRef("def456..."), small_value]
# Shell is serialized with its own CID
```

**Dict decomposition:**
```python
# Original object
data = {"key1": large_value, "key2": small_value}

# After decomposition:
shell = {"key1": CIDRef("abc123..."), "key2": small_value}
```

**Class instance decomposition:**
```python
# Original object
obj = MyClass()
obj.big_data = large_list
obj.name = "small"

# After decomposition:
# obj.__dict__ = {"big_data": CIDRef("abc123..."), "name": "small"}
```

#### Reassembly

When deserializing, CID references are resolved recursively:

```python
def reassemble(decomposed: DecomposedObject, store: CIDStore) -> Any:
    """
    Reassemble a decomposed object by resolving CID references.
    """
    shell = dill.loads(base64.b64decode(decomposed.shell_data))
    return _resolve_refs(shell, decomposed.components, store)

def _resolve_refs(obj: Any, components: Dict, store: CIDStore) -> Any:
    """Recursively resolve CIDRef markers."""
    if isinstance(obj, CIDRef):
        component_data = store.get(obj.cid)
        if component_data is None:
            raise CIDNotFoundError(obj.cid)
        component = dill.loads(component_data)
        return _resolve_refs(component, components, store)
    elif isinstance(obj, dict):
        return {k: _resolve_refs(v, components, store) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_refs(item, components, store) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(_resolve_refs(item, components, store) for item in obj)
    # ... handle other types
    return obj
```

### 4. Client-Side CID Cache

The client maintains an **LRU cache of 10,000 entries** tracking which CIDs have been sent to the server.

```python
from collections import OrderedDict
import threading

class CIDCache:
    """
    LRU cache tracking CIDs that have been sent to the server.

    Thread-safe. Maximum 10,000 entries.
    """

    MAX_SIZE = 10_000

    def __init__(self):
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
                    self._cache.popitem(last=False)  # Remove oldest

    def is_sent(self, cid: str) -> bool:
        """Check if a CID has been sent to the server."""
        with self._lock:
            if cid in self._cache:
                self._cache.move_to_end(cid)  # Update LRU order
                return True
            return False

    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()
```

### 5. Serialization Result Types

```python
from dataclasses import dataclass
from typing import Optional, Dict, List

@dataclass
class SerializedObject:
    """Result of serializing an object (possibly decomposed)."""
    cid: str                           # SHA-512 hash (128 hex chars)
    data: Optional[bytes]              # Dill pickle (None if CID already sent)
    data_base64: Optional[str]         # Base64-encoded data for JSON
    components: Dict[str, 'SerializedObject']  # Nested components (if decomposed)

@dataclass
class CIDReference:
    """Reference to an object by CID only (no data)."""
    cid: str

@dataclass
class CIDWithData:
    """CID with full serialized data."""
    cid: str
    data: str  # Base64-encoded dill pickle
    components: Optional[Dict[str, 'CIDWithData']] = None
```

### 6. Main Serializer Class

```python
import base64
import dill
import hashlib
from typing import Any, Union, Dict

DILL_PROTOCOL = 4
dill.settings['recurse'] = True

class Serializer:
    """
    Handles serialization of objects with CID-based deduplication.

    Features:
    - Object decomposition for better deduplication
    - LRU cache tracking sent CIDs
    - Thread-safe operation
    """

    MIN_DECOMPOSE_SIZE = 1024  # 1KB threshold

    def __init__(self, cache: Optional[CIDCache] = None):
        self._cache = cache or CIDCache()

    def serialize(self, obj: Any, decompose: bool = True) -> SerializedObject:
        """
        Serialize an object and compute its CID.

        Args:
            obj: Object to serialize
            decompose: Whether to decompose large objects (default True)

        Returns:
            SerializedObject with CID, data (if new), and components
        """
        pickled = dill.dumps(obj, protocol=DILL_PROTOCOL)
        cid = hashlib.sha512(pickled).hexdigest()

        # Check if we should decompose
        components = {}
        if decompose and len(pickled) >= self.MIN_DECOMPOSE_SIZE:
            obj, components = self._decompose(obj)
            # Re-serialize after decomposition
            pickled = dill.dumps(obj, protocol=DILL_PROTOCOL)
            cid = hashlib.sha512(pickled).hexdigest()

        if self._cache.is_sent(cid):
            return SerializedObject(
                cid=cid, data=None, data_base64=None, components={}
            )

        self._cache.mark_sent(cid)
        data_base64 = base64.b64encode(pickled).decode('ascii')

        return SerializedObject(
            cid=cid,
            data=pickled,
            data_base64=data_base64,
            components=components
        )

    def _decompose(self, obj: Any) -> Tuple[Any, Dict[str, SerializedObject]]:
        """
        Decompose an object, replacing large components with CIDRef.

        Returns (modified_obj, components_dict)
        """
        components = {}

        if isinstance(obj, dict):
            new_dict = {}
            for k, v in obj.items():
                new_k, k_comps = self._maybe_replace_with_ref(k, components)
                new_v, v_comps = self._maybe_replace_with_ref(v, components)
                components.update(k_comps)
                components.update(v_comps)
                new_dict[new_k] = new_v
            return new_dict, components

        elif isinstance(obj, (list, tuple)):
            new_items = []
            for item in obj:
                new_item, item_comps = self._maybe_replace_with_ref(item, components)
                components.update(item_comps)
                new_items.append(new_item)
            if isinstance(obj, tuple):
                return tuple(new_items), components
            return new_items, components

        elif hasattr(obj, '__dict__'):
            new_dict, comps = self._decompose(obj.__dict__)
            obj.__dict__.update(new_dict)
            return obj, comps

        return obj, components

    def _maybe_replace_with_ref(
        self, obj: Any, components: Dict
    ) -> Tuple[Any, Dict[str, SerializedObject]]:
        """
        Replace object with CIDRef if large enough, otherwise return as-is.
        """
        pickled = dill.dumps(obj, protocol=DILL_PROTOCOL)

        if len(pickled) < self.MIN_DECOMPOSE_SIZE:
            return obj, {}

        # Recursively serialize the component
        serialized = self.serialize(obj, decompose=True)
        components[serialized.cid] = serialized
        return CIDRef(serialized.cid), {serialized.cid: serialized}

    def to_json_dict(self, obj: Any) -> dict:
        """
        Serialize an object to a JSON-compatible dict.

        Format:
        {
            "cid": "...",
            "data": "..." (if new),
            "components": {"cid": {...}, ...} (if decomposed)
        }
        """
        result = self.serialize(obj)

        output = {"cid": result.cid}
        if result.data_base64:
            output["data"] = result.data_base64
        if result.components:
            output["components"] = {
                cid: self._serialized_to_dict(comp)
                for cid, comp in result.components.items()
                if comp.data_base64  # Only include components with data
            }
        return output

    def _serialized_to_dict(self, s: SerializedObject) -> dict:
        d = {"cid": s.cid}
        if s.data_base64:
            d["data"] = s.data_base64
        return d

    @staticmethod
    def deserialize(data_base64: str) -> Any:
        """Deserialize base64-encoded dill pickle."""
        pickled = base64.b64decode(data_base64)
        return dill.loads(pickled)

    @staticmethod
    def compute_cid(obj: Any) -> str:
        """Compute CID without full serialization tracking."""
        pickled = dill.dumps(obj, protocol=DILL_PROTOCOL)
        return hashlib.sha512(pickled).hexdigest()

    @staticmethod
    def verify_cid(data_base64: str, expected_cid: str) -> bool:
        """Verify that data matches the expected CID."""
        pickled = base64.b64decode(data_base64)
        actual_cid = hashlib.sha512(pickled).hexdigest()
        return actual_cid == expected_cid
```

---

## Server-Side Storage

### CID Store

The server maintains a **persistent store** mapping CIDs to their pickled data. **No eviction** - data is stored forever.

```python
from typing import Optional
import sqlite3
import threading
import hashlib

class CIDStore:
    """
    Server-side storage for CID -> pickled data mappings.

    Uses SQLite for persistence. Thread-safe. No eviction.
    """

    def __init__(self, db_path: str = ":memory:"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS cid_data (
                    cid TEXT PRIMARY KEY,
                    data BLOB NOT NULL,
                    created_at REAL NOT NULL,
                    size_bytes INTEGER NOT NULL
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_created ON cid_data(created_at)"
            )
            self._conn.commit()

    def store(self, cid: str, data: bytes) -> None:
        """Store CID -> data mapping. Verifies CID matches data."""
        import time

        actual_cid = hashlib.sha512(data).hexdigest()
        if actual_cid != cid:
            raise CIDMismatchError(f"CID mismatch: expected {cid}, got {actual_cid}")

        with self._lock:
            self._conn.execute(
                """INSERT OR IGNORE INTO cid_data
                   (cid, data, created_at, size_bytes) VALUES (?, ?, ?, ?)""",
                (cid, data, time.time(), len(data))
            )
            self._conn.commit()

    def store_many(self, items: Dict[str, bytes]) -> None:
        """Store multiple CID -> data mappings atomically."""
        import time
        now = time.time()

        with self._lock:
            for cid, data in items.items():
                actual_cid = hashlib.sha512(data).hexdigest()
                if actual_cid != cid:
                    raise CIDMismatchError(f"CID mismatch: expected {cid}, got {actual_cid}")

                self._conn.execute(
                    """INSERT OR IGNORE INTO cid_data
                       (cid, data, created_at, size_bytes) VALUES (?, ?, ?, ?)""",
                    (cid, data, now, len(data))
                )
            self._conn.commit()

    def get(self, cid: str) -> Optional[bytes]:
        """Retrieve data by CID. Returns None if not found."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT data FROM cid_data WHERE cid = ?", (cid,)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def get_many(self, cids: List[str]) -> Dict[str, bytes]:
        """Retrieve multiple CIDs. Returns dict of found CIDs."""
        with self._lock:
            placeholders = ','.join('?' * len(cids))
            cursor = self._conn.execute(
                f"SELECT cid, data FROM cid_data WHERE cid IN ({placeholders})",
                cids
            )
            return {row[0]: row[1] for row in cursor.fetchall()}

    def exists(self, cid: str) -> bool:
        """Check if CID exists in store."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT 1 FROM cid_data WHERE cid = ?", (cid,)
            )
            return cursor.fetchone() is not None

    def missing(self, cids: List[str]) -> List[str]:
        """Return list of CIDs that are NOT in the store."""
        found = set(self.get_many(cids).keys())
        return [cid for cid in cids if cid not in found]

    def stats(self) -> dict:
        """Return storage statistics."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT COUNT(*), SUM(size_bytes) FROM cid_data"
            )
            count, total_size = cursor.fetchone()
            return {
                "count": count or 0,
                "total_size_bytes": total_size or 0
            }
```

---

## Transmission Protocol

### Request Format (with Decomposition)

When the client sends a request, objects may include nested components:

```json
{
    "cid": "abc123...",
    "data": "<base64>",
    "components": {
        "def456...": {"cid": "def456...", "data": "<base64>"},
        "ghi789...": {"cid": "ghi789...", "data": "<base64>"}
    }
}
```

Or for cached objects (CID only):
```json
{"cid": "abc123..."}
```

### Request Processing

```python
def process_request_object(obj_dict: dict, store: CIDStore) -> Any:
    """
    Process an object from a request, handling decomposition.

    Stores all components, then deserializes and reassembles.

    Raises:
        CIDNotFoundError: If any required CID is missing
        CIDMismatchError: If any data doesn't match its CID
    """
    cid = obj_dict["cid"]

    # First, store any provided components
    if "components" in obj_dict:
        for comp_cid, comp_data in obj_dict["components"].items():
            if "data" in comp_data:
                data = base64.b64decode(comp_data["data"])
                store.store(comp_cid, data)

    # Store the main object data if provided
    if "data" in obj_dict:
        data = base64.b64decode(obj_dict["data"])
        store.store(cid, data)
        shell = dill.loads(data)
    else:
        # CID only - retrieve from store
        data = store.get(cid)
        if data is None:
            raise CIDNotFoundError(cid)
        shell = dill.loads(data)

    # Reassemble by resolving CIDRef markers
    return _resolve_refs(shell, store)

def _resolve_refs(obj: Any, store: CIDStore) -> Any:
    """Recursively resolve CIDRef markers."""
    if isinstance(obj, CIDRef):
        data = store.get(obj.cid)
        if data is None:
            raise CIDNotFoundError(obj.cid)
        resolved = dill.loads(data)
        return _resolve_refs(resolved, store)
    elif isinstance(obj, dict):
        return {_resolve_refs(k, store): _resolve_refs(v, store)
                for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_refs(item, store) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(_resolve_refs(item, store) for item in obj)
    elif isinstance(obj, (set, frozenset)):
        resolved = {_resolve_refs(item, store) for item in obj}
        return frozenset(resolved) if isinstance(obj, frozenset) else resolved
    elif hasattr(obj, '__dict__'):
        for k, v in list(obj.__dict__.items()):
            obj.__dict__[k] = _resolve_refs(v, store)
        return obj
    return obj
```

### Response for Missing CIDs

```json
{
    "error": "cid_not_found",
    "missing_cids": ["abc123...", "def456..."],
    "message": "Resend with full data"
}
```

---

## Exception Classes

```python
class SerializationError(Exception):
    """Base class for serialization errors."""
    pass

class DebugSerializationError(SerializationError):
    """Raised when an object cannot be serialized with dill."""
    def __init__(self, obj: Any, original_error: Exception):
        self.obj = obj
        self.original_error = original_error
        super().__init__(f"Cannot serialize {type(obj).__name__}: {original_error}")

class CIDNotFoundError(SerializationError):
    """Raised when a CID is not found on the server."""
    def __init__(self, cid: str):
        self.cid = cid
        super().__init__(f"CID not found: {cid[:32]}...")

class CIDMismatchError(SerializationError):
    """Raised when data doesn't match its claimed CID."""
    def __init__(self, message: str):
        super().__init__(message)
```

---

## Special Cases

### 1. None

`None` is serialized like any other object (never decomposed):
```python
cid = compute_cid(None)  # Always produces the same CID
```

### 2. Circular References

Dill handles circular references natively. Decomposition does NOT break circular references - if a component references its parent, the CIDRef system handles it:
```python
a = []
a.append(a)  # Circular reference
# Serialized as-is (not decomposed) since circularity would break
cid = compute_cid(a)  # Works correctly
```

### 3. CIDRef Marker

The `CIDRef` class is registered with dill for proper serialization:
```python
@dill.register(CIDRef)
def _pickle_cidref(pickler, obj):
    pickler.save_reduce(CIDRef, (obj.cid,), obj=obj)
```

### 4. Small Objects

Objects smaller than `MIN_DECOMPOSE_SIZE` (1KB) are never decomposed, even if composite.

### 5. Deeply Nested Decomposition

Decomposition is recursive - a large dict containing large lists will have both the dict shell and each large list as separate CIDs.

---

## Complete Test List

### 1. CID Computation Tests

```python
def test_compute_cid_returns_128_char_hex():
    """CID is a 128-character hexadecimal string (SHA-512)."""

def test_compute_cid_deterministic():
    """Same object always produces same CID."""

def test_compute_cid_same_value_same_cid():
    """Equal values produce same CID."""

def test_compute_cid_different_values_different_cid():
    """Different values produce different CIDs."""

def test_compute_cid_type_matters():
    """Same value, different type produces different CID (e.g., 1 vs 1.0)."""

def test_compute_cid_none():
    """Can compute CID for None."""

def test_compute_cid_empty_string():
    """Can compute CID for empty string."""

def test_compute_cid_empty_list():
    """Can compute CID for empty list."""

def test_compute_cid_empty_dict():
    """Can compute CID for empty dict."""

def test_compute_cid_nested_structure():
    """Can compute CID for nested data structures."""

def test_compute_cid_deep_nesting():
    """Can compute CID for deeply nested structures (100+ levels)."""

def test_compute_cid_uses_sha512():
    """CID is computed using SHA-512."""
```

### 2. Dill Serialization Tests

```python
def test_serialize_basic_types():
    """Can serialize int, float, str, bool, None."""

def test_serialize_collections():
    """Can serialize list, tuple, dict, set, frozenset."""

def test_serialize_bytes():
    """Can serialize bytes and bytearray."""

def test_serialize_class_instance():
    """Can serialize custom class instances."""

def test_serialize_class_itself():
    """Can serialize class objects (not instances)."""

def test_serialize_function():
    """Can serialize regular functions."""

def test_serialize_lambda():
    """Can serialize lambda functions."""

def test_serialize_closure():
    """Can serialize closures with captured variables."""

def test_serialize_nested_function():
    """Can serialize nested function definitions."""

def test_serialize_generator_function():
    """Can serialize generator functions (not exhausted generators)."""

def test_serialize_async_function():
    """Can serialize async function definitions."""

def test_serialize_circular_reference():
    """Can serialize objects with circular references."""

def test_serialize_self_referential_dict():
    """Can serialize dict that references itself."""

def test_serialize_datetime():
    """Can serialize datetime objects."""

def test_serialize_decimal():
    """Can serialize Decimal objects."""

def test_serialize_exception():
    """Can serialize exception objects."""

def test_serialize_traceback():
    """Can serialize traceback objects (or handle gracefully)."""

def test_serialize_large_object():
    """Can serialize large objects (1MB+)."""

def test_serialize_deeply_nested():
    """Can serialize deeply nested structures (1000+ levels)."""

def test_dill_protocol_version():
    """Serialization uses fixed protocol version 4."""

def test_dill_recurse_setting():
    """Dill recurse setting is enabled."""
```

### 3. Serialization Failure Tests

```python
def test_serialize_open_file_raises():
    """Serializing open file handle raises DebugSerializationError."""

def test_serialize_socket_raises():
    """Serializing socket raises DebugSerializationError."""

def test_serialize_lock_raises():
    """Serializing threading.Lock raises DebugSerializationError."""

def test_serialize_thread_raises():
    """Serializing Thread object raises DebugSerializationError."""

def test_serialize_generator_instance_raises():
    """Serializing exhausted generator raises DebugSerializationError."""

def test_serialization_error_includes_type():
    """DebugSerializationError includes the type that failed."""

def test_serialization_error_includes_original():
    """DebugSerializationError includes the original exception."""

def test_partial_failure_fails_entire_request():
    """If any object fails to serialize, entire request fails."""
```

### 4. Object Decomposition Tests

```python
def test_decompose_small_object_unchanged():
    """Objects below MIN_DECOMPOSE_SIZE are not decomposed."""

def test_decompose_large_list():
    """Large list is decomposed into shell with CIDRefs."""

def test_decompose_large_dict():
    """Large dict is decomposed into shell with CIDRefs."""

def test_decompose_large_tuple():
    """Large tuple is decomposed into shell with CIDRefs."""

def test_decompose_large_set():
    """Large set is decomposed into shell with CIDRefs."""

def test_decompose_class_instance():
    """Class instance with large __dict__ is decomposed."""

def test_decompose_nested_structure():
    """Nested structures are recursively decomposed."""

def test_decompose_preserves_small_values():
    """Small values within large structures stay inline."""

def test_decompose_generates_components():
    """Decomposition produces correct components dict."""

def test_decompose_cidref_serializable():
    """CIDRef markers are themselves serializable."""

def test_decompose_does_not_break_circular():
    """Circular references are not decomposed (would break)."""

def test_decompose_shared_component_deduped():
    """Same component appearing twice shares one CID."""

def test_decompose_threshold_configurable():
    """MIN_DECOMPOSE_SIZE threshold is respected."""
```

### 5. Reassembly Tests

```python
def test_reassemble_simple_object():
    """Can reassemble object with no CIDRefs."""

def test_reassemble_with_cidref():
    """Can reassemble object containing CIDRefs."""

def test_reassemble_nested_cidrefs():
    """Can reassemble deeply nested CIDRefs."""

def test_reassemble_dict_with_cidref_keys():
    """Can reassemble dict where keys are CIDRefs."""

def test_reassemble_class_instance():
    """Can reassemble class instance with CIDRef in __dict__."""

def test_reassemble_missing_component_raises():
    """Missing component CID raises CIDNotFoundError."""

def test_reassemble_preserves_types():
    """Reassembly preserves original types (list, tuple, etc.)."""

def test_reassemble_preserves_identity():
    """Shared components maintain identity after reassembly."""
```

### 6. Deserialization Tests

```python
def test_deserialize_basic_types():
    """Can deserialize int, float, str, bool, None."""

def test_deserialize_collections():
    """Can deserialize list, tuple, dict, set."""

def test_deserialize_class_instance():
    """Can deserialize custom class instances."""

def test_deserialize_function():
    """Can deserialize functions and they work."""

def test_deserialize_lambda():
    """Can deserialize lambdas and they work."""

def test_deserialize_closure():
    """Can deserialize closures and captured variables work."""

def test_deserialize_circular_reference():
    """Can deserialize circular references correctly."""

def test_deserialize_preserves_identity():
    """Circular reference identity is preserved after deserialize."""

def test_roundtrip_equality():
    """serialize then deserialize produces equal object."""

def test_roundtrip_function_behavior():
    """Deserialized function behaves same as original."""

def test_roundtrip_with_decomposition():
    """Decomposed object reassembles to equal original."""
```

### 7. CID Cache Tests

```python
def test_cache_initially_empty():
    """New cache reports no CIDs sent."""

def test_cache_mark_sent():
    """Can mark CID as sent."""

def test_cache_is_sent_returns_true():
    """is_sent returns True for marked CIDs."""

def test_cache_is_sent_returns_false():
    """is_sent returns False for unmarked CIDs."""

def test_cache_max_size_enforced():
    """Cache does not exceed MAX_SIZE entries."""

def test_cache_lru_eviction():
    """Oldest entries are evicted when cache is full."""

def test_cache_lru_access_updates_order():
    """Accessing a CID moves it to end (prevents eviction)."""

def test_cache_clear():
    """Can clear the cache."""

def test_cache_thread_safety():
    """Cache is thread-safe under concurrent access."""

def test_cache_thread_safety_mark_and_check():
    """Concurrent mark_sent and is_sent are safe."""

def test_cache_128_char_cids():
    """Cache handles 128-character SHA-512 CIDs."""
```

### 8. Serializer Class Tests

```python
def test_serializer_new_object_includes_data():
    """First serialization includes CID and data."""

def test_serializer_cached_object_excludes_data():
    """Second serialization includes only CID."""

def test_serializer_to_json_dict_new():
    """to_json_dict returns {cid, data} for new objects."""

def test_serializer_to_json_dict_cached():
    """to_json_dict returns {cid} for cached objects."""

def test_serializer_to_json_dict_with_components():
    """to_json_dict includes components for decomposed objects."""

def test_serializer_force_serialize_always_includes_data():
    """force_serialize_with_data always includes data."""

def test_serializer_verify_cid_correct():
    """verify_cid returns True for matching data."""

def test_serializer_verify_cid_incorrect():
    """verify_cid returns False for non-matching data."""

def test_serializer_thread_safety():
    """Serializer is thread-safe under concurrent use."""

def test_serializer_decompose_flag():
    """decompose=False prevents decomposition."""
```

### 9. CID Store Tests

```python
def test_store_and_retrieve():
    """Can store data and retrieve it by CID."""

def test_store_verifies_cid():
    """store() verifies CID matches data."""

def test_store_mismatch_raises():
    """store() raises CIDMismatchError on mismatch."""

def test_store_duplicate_ignored():
    """Storing same CID twice doesn't raise."""

def test_get_nonexistent_returns_none():
    """get() returns None for unknown CID."""

def test_exists_true():
    """exists() returns True for stored CID."""

def test_exists_false():
    """exists() returns False for unknown CID."""

def test_store_thread_safety():
    """Store is thread-safe under concurrent access."""

def test_store_persistence():
    """Data persists across store instances (file-backed)."""

def test_store_many_atomic():
    """store_many is atomic - all or nothing."""

def test_get_many():
    """Can retrieve multiple CIDs at once."""

def test_missing():
    """missing() returns list of unknown CIDs."""

def test_stats():
    """stats() returns count and total size."""

def test_store_no_eviction():
    """Store keeps all data forever (no eviction)."""

def test_store_128_char_cids():
    """Store handles 128-character SHA-512 CIDs."""
```

### 10. Protocol Tests

```python
def test_process_request_with_data():
    """Can process request with CID + data."""

def test_process_request_cid_only():
    """Can process request with CID only (data in store)."""

def test_process_request_cid_not_found():
    """CID-only request for unknown CID raises CIDNotFoundError."""

def test_process_request_cid_mismatch():
    """Request with mismatched CID/data raises CIDMismatchError."""

def test_process_multiple_objects():
    """Can process request with multiple objects."""

def test_process_mixed_new_and_cached():
    """Can process request with mix of new and cached objects."""

def test_process_with_components():
    """Can process request with decomposed components."""

def test_process_nested_components():
    """Can process request with nested component references."""

def test_process_missing_component():
    """Missing component raises CIDNotFoundError."""
```

### 11. Base64 Encoding Tests

```python
def test_base64_encode_decode_roundtrip():
    """Base64 encoding/decoding preserves data."""

def test_base64_output_is_ascii():
    """Base64 output contains only ASCII characters."""

def test_base64_handles_binary_data():
    """Base64 correctly handles binary data with null bytes."""

def test_base64_handles_unicode():
    """Serialization handles unicode strings correctly."""
```

### 12. Edge Case Tests

```python
def test_very_long_string():
    """Can serialize string with 1M+ characters."""

def test_very_large_list():
    """Can serialize list with 100K+ elements."""

def test_very_large_dict():
    """Can serialize dict with 100K+ keys."""

def test_deeply_nested_100_levels():
    """Can serialize 100 levels of nesting."""

def test_recursive_class_definition():
    """Can serialize class that references itself."""

def test_mutually_recursive_objects():
    """Can serialize mutually recursive objects (A->B->A)."""

def test_object_with_slots():
    """Can serialize objects using __slots__."""

def test_object_with_custom_reduce():
    """Can serialize objects with __reduce__."""

def test_namedtuple():
    """Can serialize namedtuple instances."""

def test_dataclass():
    """Can serialize dataclass instances."""

def test_enum():
    """Can serialize Enum members."""

def test_defaultdict():
    """Can serialize defaultdict (with default_factory)."""

def test_counter():
    """Can serialize collections.Counter."""

def test_partial_function():
    """Can serialize functools.partial objects."""

def test_cidref_in_various_contexts():
    """CIDRef works in dict keys, set elements, etc."""
```

### 13. Performance Tests

```python
def test_serialize_performance_small():
    """Serialization of small objects is fast (<1ms)."""

def test_serialize_performance_large():
    """Serialization of large objects (1MB) completes (<1s)."""

def test_cid_computation_performance():
    """CID computation is fast (<1ms for small objects)."""

def test_cache_lookup_performance():
    """Cache lookup is O(1)."""

def test_cache_full_performance():
    """Cache operations remain fast when full."""

def test_decomposition_performance():
    """Decomposition doesn't significantly slow serialization."""
```

### 14. Integration Tests

```python
def test_full_workflow_new_object():
    """Complete workflow: serialize -> transmit -> store -> deserialize."""

def test_full_workflow_cached_object():
    """Complete workflow with cached CID."""

def test_full_workflow_cid_not_found_recovery():
    """Client recovers from CID not found by resending."""

def test_full_workflow_multiple_objects():
    """Complete workflow with multiple objects in one request."""

def test_full_workflow_decomposed_object():
    """Complete workflow with decomposed object and components."""

def test_client_server_roundtrip():
    """Object survives complete client->server->client roundtrip."""

def test_roundtrip_with_decomposition():
    """Decomposed object survives roundtrip and equals original."""
```

---

## Open Questions

1. **Decomposition depth limit**: Should there be a maximum depth for recursive decomposition?
   - a) No limit (decompose fully)
   - b) Fixed limit (e.g., 10 levels)
   - c) Configurable

2. **Decomposition of keys**: Should dict keys be decomposed (replaced with CIDRef)?
   - a) Yes, decompose keys too
   - b) No, only decompose values (keys must be hashable)
   - c) Only decompose non-hashable keys

3. **CIDRef hashability**: Should CIDRef be hashable (for use as dict key/set element)?
   - a) Yes, hash based on cid string
   - b) No, CIDRef should not be used as key

4. **Circular reference detection**: How to handle circular references during decomposition?
   - a) Detect and skip decomposition for circular structures
   - b) Track seen objects to avoid infinite recursion
   - c) Let dill handle it naturally (don't decompose circular refs)

5. **Component transmission order**: When sending decomposed objects, should components be sent:
   - a) All in one request (current design)
   - b) Depth-first (leaf components first)
   - c) Breadth-first

---

## Dependencies

```
dill>=0.3.6
```

No other external dependencies required. Uses standard library:
- `hashlib` for SHA-512
- `base64` for encoding
- `sqlite3` for server-side storage
- `threading` for thread safety
- `collections.OrderedDict` for LRU cache

---

## File Structure

```
src/cideldill/
├── serialization.py      # Serializer, compute_cid, CIDCache, CIDRef
├── decomposition.py      # ObjectDecomposer, reassembly logic
├── cid_store.py          # Server-side CIDStore
├── exceptions.py         # DebugSerializationError, CIDNotFoundError, CIDMismatchError
```

---

## Next Steps

1. Resolve open questions
2. Implement core serialization module
3. Implement decomposition logic
4. Implement CID store
5. Write comprehensive tests
6. Integrate with debug client and server
