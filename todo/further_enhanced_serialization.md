# Further Enhanced Serialization: Graceful Degradation

## Problem Statement

When cideldill encounters an object that can't be pickled (e.g., `ChatOpenAI` with embedded `SSLContext`), it currently raises `DebugSerializationError` and halts. This loses all debugging data for that call.

**Key insight**: The primary use case is *examination* (viewing snapshots later), not *restoration* (reconstructing live objects). We should capture maximum introspectable state even when full pickling fails.

**Risk to avoid**: Prematurely concluding something is unpicklable when improved logic could handle it. False negatives mean lost debugging data.

---

## Design Goals

| Priority | Goal |
|----------|------|
| 1 | Never lose debugging data due to serialization failures |
| 2 | Capture rich state for examination, not just metadata |
| 3 | Preserve full pickling when possible (don't degrade unnecessarily) |
| 4 | Make it obvious in the UI which objects degraded and why |
| 5 | Provide diagnostic info to improve future pickling support |

---

## Approach

### Serialization Waterfall

```
1. Try dill.dumps() directly
   ↓ (fails)
2. Try auto_register_for_pickling() + retry
   ↓ (fails)
3. Build UnpicklablePlaceholder with rich attribute snapshot
   ↓ (recurse on each attribute with depth limit)
4. Return pickled placeholder (always succeeds)
```

### Enhanced UnpicklablePlaceholder

```python
@dataclass
class UnpicklablePlaceholder:
    """Rich snapshot for objects that cannot be fully pickled.
    
    Designed for examination, not restoration.
    """
    
    # Identity
    type_name: str
    module: str
    qualname: str
    object_id: str  # hex(id(obj)) at capture time
    
    # Representation
    repr_text: str  # truncated repr
    str_text: str | None  # truncated str() if different from repr
    
    # State snapshot
    attributes: dict[str, Any]  # successfully pickled attributes
    failed_attributes: dict[str, str]  # attr_name -> error description
    
    # Diagnostic info
    pickle_error: str  # the original error that triggered degradation
    pickle_attempts: list[str]  # log of what was tried
    
    # Metadata
    capture_timestamp: float
    depth: int  # how deep in the object graph this placeholder is
```

---

## Implementation Plan

### Phase 1: Core Serialization Changes

**File: `serialization.py`**

1. Add `max_depth` parameter to `_safe_dumps()` (default: 3)

2. Implement `_build_snapshot()`:
   - Iterate attributes via `__dict__`, `__slots__`, and safe `dir()` inspection
   - Recursively attempt `_safe_dumps()` on each attribute
   - Classify into `attributes` (success) vs `failed_attributes` (with error message)
   - Respect depth limit to avoid infinite recursion

3. Modify `_safe_dumps()` waterfall:
   ```python
   def _safe_dumps(obj: Any, *, depth: int = 0, max_depth: int = 3) -> bytes:
       attempts = []
       
       # Attempt 1: Direct pickle
       try:
           return dill.dumps(obj, protocol=DILL_PROTOCOL)
       except Exception as exc:
           first_error = exc
           attempts.append(f"dill.dumps: {type(exc).__name__}: {exc}")
       
       # Attempt 2: Auto-register custom pickler
       if auto_register_for_pickling(obj, protocol=DILL_PROTOCOL):
           try:
               return dill.dumps(obj, protocol=DILL_PROTOCOL)
           except Exception as exc:
               attempts.append(f"auto_register retry: {type(exc).__name__}: {exc}")
       else:
           attempts.append("auto_register: no reducer found")
       
       # Attempt 3: Graceful degradation to placeholder
       if depth >= max_depth:
           placeholder = _minimal_placeholder(obj, first_error, attempts, depth)
       else:
           placeholder = _build_snapshot(obj, first_error, attempts, depth, max_depth)
       
       return dill.dumps(placeholder, protocol=DILL_PROTOCOL)
   ```

4. Add helper `_minimal_placeholder()` for depth-limited cases (just metadata + repr)

5. Add helper `_iter_attributes()`:
   ```python
   def _iter_attributes(obj: Any) -> Iterator[tuple[str, Any]]:
       """Yield (name, value) for all accessible attributes."""
       seen = set()
       
       # __dict__ first (most common)
       if hasattr(obj, "__dict__"):
           for name, value in obj.__dict__.items():
               if not name.startswith("_"):
                   seen.add(name)
                   yield name, value
       
       # __slots__ 
       for klass in type(obj).__mro__:
           for slot in getattr(klass, "__slots__", ()):
               if slot not in seen and not slot.startswith("_"):
                   try:
                       yield slot, getattr(obj, slot)
                       seen.add(slot)
                   except AttributeError:
                       pass
       
       # Optionally: public properties via dir()
       # (configurable, may be expensive)
   ```

6. Add `_safe_repr()` and `_safe_str()` helpers with length limits and exception handling

### Phase 2: Update UnpicklablePlaceholder

**File: `custom_picklers.py`**

1. Expand `UnpicklablePlaceholder` dataclass with new fields (see above)

2. Update `__repr__()` to show summary:
   ```python
   def __repr__(self) -> str:
       n_ok = len(self.attributes)
       n_fail = len(self.failed_attributes)
       return (
           f"<UnpicklablePlaceholder {self.module}.{self.qualname} "
           f"attrs={n_ok} failed={n_fail} error={self.pickle_error!r}>"
       )
   ```

3. Add `to_dict()` method for JSON serialization in web UI

4. Keep `_reconstruct_placeholder()` working for backward compat

### Phase 3: Public API Surface

**File: `serialization.py`**

1. Keep `serialize()` and `compute_cid()` unchanged externally
   - They now internally use graceful degradation
   - CID computation still works (placeholder is deterministic for same input)

2. Add optional flag for strict mode (raise instead of degrade):
   ```python
   def serialize(obj: Any, *, strict: bool = False) -> bytes:
       ...
   ```

3. Consider: Should `compute_cid()` warn/log when it degrades? 
   - Probably yes, at DEBUG level

### Phase 4: Logging & Diagnostics

1. Add structured logging when degradation occurs:
   ```python
   logger.info(
       "Serialization degraded to placeholder",
       extra={
           "type": type(obj).__qualname__,
           "module": type(obj).__module__,
           "error": str(first_error),
           "captured_attrs": len(placeholder.attributes),
           "failed_attrs": list(placeholder.failed_attributes.keys()),
       }
   )
   ```

2. Consider: Accumulate stats for end-of-session summary?

---

## Edge Cases & Considerations

### Recursive/Circular References

- Depth limit handles unbounded recursion
- For true circular refs within depth limit: track `id()` of visited objects
  ```python
  def _build_snapshot(..., _visited: set[int] | None = None):
      if _visited is None:
          _visited = set()
      if id(obj) in _visited:
          return _circular_ref_placeholder(obj)
      _visited.add(id(obj))
      ...
  ```

### Large Collections

- If `obj.__dict__` has 10,000 items, snapshot is expensive
- Add configurable `max_attributes` limit (default: 100?)
- Capture first N + note "and N more..."

### Properties That Have Side Effects

- `dir()` + `getattr()` can trigger property getters
- Some getters mutate state or do I/O
- Mitigation: Only inspect `__dict__` and `__slots__` by default
- Optional "deep inspection" mode that uses `dir()`

### Private Attributes

- Current plan skips `_`-prefixed attributes
- Reconsidered: these often contain the interesting state
- Option: include `_single_underscore`, skip `__dunder__` and `__mangled`

### Thread Safety

- `_safe_dumps` may be called from multiple threads
- Current `Serializer` class has a lock
- Ensure placeholder building doesn't introduce races
- `id()` is safe; attribute access on shared objects may not be

---

## Testing Plan

### Unit Tests

1. **Basic degradation**: Object with unpicklable attr → placeholder with partial state
2. **Depth limit**: Deeply nested unpicklable → stops at max_depth
3. **Circular reference**: Self-referential object → doesn't infinite loop
4. **Mixed success**: Object with 5 picklable + 2 unpicklable attrs → captures 5
5. **Repr failure**: Object where `repr()` raises → still creates placeholder
6. **Large object**: 10k attributes → respects max_attributes limit

### Integration Tests

1. **ChatOpenAI scenario**: Wrap LangChain client, verify partial capture
2. **Database connection**: Similar SSL/socket scenario
3. **End-to-end**: Call through DebugProxy, verify server receives placeholder

### Property-Based Tests (Hypothesis)

1. Generate arbitrary objects, verify serialization never raises
2. Verify: `deserialize(serialize(obj))` returns either `obj` or `UnpicklablePlaceholder`

---

## Migration & Compatibility

### Backward Compatibility

- `DebugSerializationError` still exists, but only raised if `strict=True`
- Existing code that catches this exception continues to work
- Server must handle `UnpicklablePlaceholder` in payloads (may already via dill)

### Server-Side Changes

- Web UI should render `UnpicklablePlaceholder` specially:
  - Show type/module/error prominently
  - Expandable tree of `attributes` 
  - Collapsed section for `failed_attributes` with error details
- Consider: Different visual treatment (yellow warning badge?)

### Versioning

- Bump client version to 0.2.0 (new behavior, backward compatible)
- Document in changelog

---

## Open Questions

1. **Should CID change when degradation occurs?**
   - Currently: Yes, because pickled bytes differ
   - This means same logical object could have different CIDs across runs if pickling flakiness
   - Acceptable? Probably yes for examination use case

2. **Include `__dunder__` attributes?**
   - `__class__`, `__module__` → yes (identity)
   - `__dict__` → already handled
   - `__weakref__` → skip
   - Others → probably skip

3. **Configurable degradation policy?**
   - Global setting: strict | warn | silent
   - Per-call setting via context manager?
   - Over-engineering risk—start simple

4. **Placeholder serialization itself fails?**
   - Extremely unlikely if we only store primitives + successfully-pickled values
   - But `repr_text` could contain weird bytes?
   - Safety: wrap placeholder pickling in try/except, fall back to minimal

---

## Implementation Order

1. `UnpicklablePlaceholder` expansion (custom_picklers.py)
2. `_iter_attributes()`, `_safe_repr()` helpers (serialization.py)
3. `_build_snapshot()` implementation (serialization.py)
4. Modified `_safe_dumps()` waterfall (serialization.py)
5. Unit tests for new behavior
6. Integration test with real unpicklable object (mock SSLContext)
7. Manual test with actual ChatOpenAI
8. Server UI updates (separate PR)
