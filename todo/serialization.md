# Serialization Mechanism Specification

## Overview

This document specifies the exact serialization mechanism for the cideldill debugging API. All objects (arguments, return values, exceptions, proxied targets) are serialized using **dill** and identified by their **CID (Content Identifier)**.

## Core Components

### 1. Dill Serialization

**Why dill?**
- Handles more Python objects than standard pickle (lambdas, closures, nested functions)
- Can serialize by reference or by value
- Actively maintained, widely used

```python
import dill

def serialize(obj) -> bytes:
    """Serialize any Python object to bytes."""
    return dill.dumps(obj, protocol=dill.HIGHEST_PROTOCOL)

def deserialize(data: bytes) -> Any:
    """Deserialize bytes back to Python object."""
    return dill.loads(data)
```

### 2. CID Computation

A **CID (Content Identifier)** is a SHA-256 hash of the dill-pickled representation of an object.

```python
import hashlib
import dill

def compute_cid(obj) -> str:
    """
    Compute the CID for any Python object.

    Returns a 64-character hex string (SHA-256).
    """
    pickled = dill.dumps(obj, protocol=dill.HIGHEST_PROTOCOL)
    return hashlib.sha256(pickled).hexdigest()
```

**Properties:**
- **Deterministic**: Same object always produces same CID
- **Collision-resistant**: Different objects produce different CIDs (with overwhelming probability)
- **Content-addressed**: CID depends only on content, not on when/where computed

### 3. Client-Side CID Cache

The client maintains an **LRU cache of 10,000 entries** tracking which CIDs have been sent to the server.

```python
from functools import lru_cache
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

### 4. Serialization Result Types

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class SerializedObject:
    """Result of serializing an object."""
    cid: str                      # SHA-256 hash (64 hex chars)
    data: Optional[bytes]         # Dill pickle (None if CID already sent)
    data_base64: Optional[str]    # Base64-encoded data for JSON transmission

@dataclass
class CIDReference:
    """Reference to an object by CID only (no data)."""
    cid: str

@dataclass
class CIDWithData:
    """CID with full serialized data."""
    cid: str
    data: str  # Base64-encoded dill pickle
```

### 5. Main Serializer Class

```python
import base64
import dill
import hashlib
from typing import Any, Union

class Serializer:
    """
    Handles serialization of objects with CID-based deduplication.

    Thread-safe. Uses an LRU cache to track sent CIDs.
    """

    def __init__(self, cache: Optional[CIDCache] = None):
        self._cache = cache or CIDCache()

    def serialize(self, obj: Any) -> SerializedObject:
        """
        Serialize an object and compute its CID.

        If the CID has been previously sent (in cache), returns CID only.
        Otherwise, returns CID + data and marks CID as sent.
        """
        pickled = dill.dumps(obj, protocol=dill.HIGHEST_PROTOCOL)
        cid = hashlib.sha256(pickled).hexdigest()

        if self._cache.is_sent(cid):
            return SerializedObject(cid=cid, data=None, data_base64=None)

        self._cache.mark_sent(cid)
        data_base64 = base64.b64encode(pickled).decode('ascii')
        return SerializedObject(cid=cid, data=pickled, data_base64=data_base64)

    def serialize_for_transmission(self, obj: Any) -> Union[CIDReference, CIDWithData]:
        """
        Serialize an object for network transmission.

        Returns either CIDReference (if already sent) or CIDWithData (if new).
        """
        result = self.serialize(obj)
        if result.data_base64 is None:
            return CIDReference(cid=result.cid)
        return CIDWithData(cid=result.cid, data=result.data_base64)

    def to_json_dict(self, obj: Any) -> dict:
        """
        Serialize an object to a JSON-compatible dict.

        Format: {"cid": "...", "data": "..."} or {"cid": "..."}
        """
        result = self.serialize_for_transmission(obj)
        if isinstance(result, CIDReference):
            return {"cid": result.cid}
        return {"cid": result.cid, "data": result.data}

    def force_serialize_with_data(self, obj: Any) -> CIDWithData:
        """
        Serialize an object, always including data (ignores cache).

        Used when server reports CID not found.
        """
        pickled = dill.dumps(obj, protocol=dill.HIGHEST_PROTOCOL)
        cid = hashlib.sha256(pickled).hexdigest()
        data_base64 = base64.b64encode(pickled).decode('ascii')
        self._cache.mark_sent(cid)
        return CIDWithData(cid=cid, data=data_base64)

    @staticmethod
    def deserialize(data_base64: str) -> Any:
        """Deserialize base64-encoded dill pickle."""
        pickled = base64.b64decode(data_base64)
        return dill.loads(pickled)

    @staticmethod
    def verify_cid(data_base64: str, expected_cid: str) -> bool:
        """Verify that data matches the expected CID."""
        pickled = base64.b64decode(data_base64)
        actual_cid = hashlib.sha256(pickled).hexdigest()
        return actual_cid == expected_cid
```

---

## Server-Side Storage

### CID Store

The server maintains a persistent store mapping CIDs to their pickled data.

```python
from typing import Optional
import sqlite3
import threading

class CIDStore:
    """
    Server-side storage for CID -> pickled data mappings.

    Uses SQLite for persistence. Thread-safe.
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
                    created_at REAL NOT NULL
                )
            """)
            self._conn.commit()

    def store(self, cid: str, data: bytes) -> None:
        """Store CID -> data mapping. Verifies CID matches data."""
        import hashlib
        import time

        actual_cid = hashlib.sha256(data).hexdigest()
        if actual_cid != cid:
            raise CIDMismatchError(f"CID mismatch: expected {cid}, got {actual_cid}")

        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO cid_data (cid, data, created_at) VALUES (?, ?, ?)",
                (cid, data, time.time())
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

    def exists(self, cid: str) -> bool:
        """Check if CID exists in store."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT 1 FROM cid_data WHERE cid = ?", (cid,)
            )
            return cursor.fetchone() is not None

    def verify(self, cid: str) -> bool:
        """Verify that stored data matches CID."""
        data = self.get(cid)
        if data is None:
            return False
        import hashlib
        actual_cid = hashlib.sha256(data).hexdigest()
        return actual_cid == cid
```

---

## Transmission Protocol

### Request Format

When the client sends a request, each object is represented as either:

**CID only** (object previously sent):
```json
{"cid": "abc123..."}
```

**CID with data** (new object):
```json
{"cid": "abc123...", "data": "<base64 dill pickle>"}
```

### Request Processing

```python
def process_request_object(obj_dict: dict, store: CIDStore) -> Any:
    """
    Process an object from a request.

    If data is provided, stores it and returns deserialized object.
    If only CID, retrieves from store and returns deserialized object.

    Raises:
        CIDNotFoundError: If CID-only and CID not in store
        CIDMismatchError: If data doesn't match CID
    """
    cid = obj_dict["cid"]

    if "data" in obj_dict:
        # New data provided - store and deserialize
        data = base64.b64decode(obj_dict["data"])
        store.store(cid, data)  # Raises CIDMismatchError if mismatch
        return dill.loads(data)
    else:
        # CID only - retrieve from store
        data = store.get(cid)
        if data is None:
            raise CIDNotFoundError(cid)
        return dill.loads(data)
```

### Response for Missing CID

When the server receives a CID-only reference for an unknown CID:

```json
{
    "error": "cid_not_found",
    "missing_cids": ["abc123...", "def456..."],
    "message": "Resend with full data"
}
```

The client must then resend using `force_serialize_with_data()`.

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
        super().__init__(f"CID not found: {cid}")

class CIDMismatchError(SerializationError):
    """Raised when data doesn't match its claimed CID."""
    def __init__(self, message: str):
        super().__init__(message)
```

---

## Special Cases

### 1. None

`None` is serialized like any other object:
```python
cid = compute_cid(None)  # Always produces the same CID
```

### 2. Circular References

Dill handles circular references natively:
```python
a = []
a.append(a)  # Circular reference
cid = compute_cid(a)  # Works correctly
```

### 3. Large Objects

Large objects are serialized in full. No chunking or streaming (debugging is not performance-critical).

### 4. Unpicklable Objects

Some objects cannot be pickled even with dill:
- Open file handles
- Database connections
- Some C extension objects

These raise `DebugSerializationError`.

### 5. Functions and Lambdas

Dill can serialize most functions and lambdas:
```python
f = lambda x: x + 1
cid = compute_cid(f)  # Works

def make_adder(n):
    return lambda x: x + n
add5 = make_adder(5)
cid = compute_cid(add5)  # Works (closure captured)
```

### 6. Classes and Instances

```python
class MyClass:
    def __init__(self, value):
        self.value = value

obj = MyClass(42)
cid = compute_cid(obj)  # Works

cid_class = compute_cid(MyClass)  # Works (class itself)
```

---

## Complete Test List

### 1. CID Computation Tests

```python
def test_compute_cid_returns_64_char_hex():
    """CID is a 64-character hexadecimal string."""

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
```

### 4. Deserialization Tests

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
```

### 5. CID Cache Tests

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
```

### 6. Serializer Class Tests

```python
def test_serializer_new_object_includes_data():
    """First serialization includes CID and data."""

def test_serializer_cached_object_excludes_data():
    """Second serialization includes only CID."""

def test_serializer_to_json_dict_new():
    """to_json_dict returns {cid, data} for new objects."""

def test_serializer_to_json_dict_cached():
    """to_json_dict returns {cid} for cached objects."""

def test_serializer_force_serialize_always_includes_data():
    """force_serialize_with_data always includes data."""

def test_serializer_verify_cid_correct():
    """verify_cid returns True for matching data."""

def test_serializer_verify_cid_incorrect():
    """verify_cid returns False for non-matching data."""

def test_serializer_thread_safety():
    """Serializer is thread-safe under concurrent use."""
```

### 7. CID Store Tests

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

def test_verify_stored_data():
    """verify() returns True for valid stored data."""

def test_store_thread_safety():
    """Store is thread-safe under concurrent access."""

def test_store_persistence():
    """Data persists across store instances (file-backed)."""
```

### 8. Protocol Tests

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
```

### 9. Base64 Encoding Tests

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

### 10. Edge Case Tests

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
```

### 11. Performance Tests

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
```

### 12. Integration Tests

```python
def test_full_workflow_new_object():
    """Complete workflow: serialize -> transmit -> store -> deserialize."""

def test_full_workflow_cached_object():
    """Complete workflow with cached CID."""

def test_full_workflow_cid_not_found_recovery():
    """Client recovers from CID not found by resending."""

def test_full_workflow_multiple_objects():
    """Complete workflow with multiple objects in one request."""

def test_client_server_roundtrip():
    """Object survives complete client->server->client roundtrip."""
```

---

## Open Questions

1. **Dill protocol version**: Should we use `dill.HIGHEST_PROTOCOL` or a fixed version for compatibility?
   - a) HIGHEST_PROTOCOL (best performance)
   - b) Fixed version (e.g., 4) for cross-version compatibility
   - c) Configurable

2. **Hash algorithm**: SHA-256 is specified, but should we support alternatives?
   - a) SHA-256 only (simplicity)
   - b) Configurable (SHA-256, SHA-512, BLAKE2)
   - c) Include algorithm in CID prefix (e.g., "sha256:abc...")

3. **Large object handling**: Should there be a size limit for serialized objects?
   - a) No limit (debugging is not performance-critical)
   - b) Warn above threshold (e.g., 10MB)
   - c) Error above threshold

4. **Partial failure**: When serializing multiple objects, if one fails, should we:
   - a) Fail the entire request
   - b) Return partial results with error markers
   - c) Skip failed objects with warnings

5. **CID store eviction**: Should the server-side CID store have a size limit or TTL?
   - a) No limit (store everything forever)
   - b) TTL-based eviction (e.g., 24 hours)
   - c) Size-based eviction (e.g., 1GB max)
   - d) Configurable

6. **Dill settings**: Should we use any special dill settings?
   - a) Default settings
   - b) `dill.settings['recurse'] = True` for better closure handling
   - c) Configurable

---

## Dependencies

```
dill>=0.3.6
```

No other external dependencies required. Uses standard library:
- `hashlib` for SHA-256
- `base64` for encoding
- `sqlite3` for server-side storage
- `threading` for thread safety
- `collections.OrderedDict` for LRU cache

---

## File Structure

```
src/cideldill/
├── serialization.py      # Serializer, compute_cid, CIDCache
├── cid_store.py          # Server-side CIDStore
├── exceptions.py         # DebugSerializationError, CIDNotFoundError, CIDMismatchError
```

---

## Next Steps

1. Resolve open questions
2. Implement core serialization module
3. Implement CID store
4. Write comprehensive tests
5. Integrate with debug client and server
