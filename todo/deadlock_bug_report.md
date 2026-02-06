# Bug: Serializer lock deadlock when DebugProxy objects are nested inside arguments

## Summary

`record_call_start` deadlocks when any argument passed to it (directly, or via
`async_debug_call` / `DebugProxy._wrap_method`) contains a `DebugProxy` object
reachable through its object graph. The process becomes completely unresponsive
and cannot be killed with Ctrl-C — only `kill -9` works.

The deadlock watchdog *detects* the problem but only logs a warning. The process
remains hung indefinitely.

## Affected code paths

- `async_debug_call(label, func, *args)` — serializes `args`
- `DebugProxy._wrap_method` → `wrapper()` — serializes `args`
- Both call `DebugClient.record_call_start` → `_build_call_payload` →
  `self._serializer.serialize(arg)` for each argument

## Root cause

`CIDSerializer.serialize()` in `serialization_common.py` acquires a
**non-reentrant** `threading.Lock`:

```python
# serialization_common.py:625-628
def serialize(self, obj):
    with self._lock:          # <-- acquires non-reentrant Lock
        pickled = _safe_dumps(obj)
        ...
```

When `_safe_dumps` cannot pickle an object, it falls back to `_build_snapshot`,
which calls `_safe_repr(obj)` → `repr(obj)`.

If `obj` is (or contains a field that is) a `DebugProxy`, `repr()` triggers:

```python
# debug_proxy.py:326-327
def __repr__(self) -> str:
    return self._intercept_dunder("__repr__")
```

Which calls `_wrap_method` → `record_call_start` → `_build_call_payload` →
`self._serializer.serialize(target)` → tries to acquire `self._lock` **again**.

Since `threading.Lock` is **not reentrant**, the second `acquire()` blocks
forever on the same thread. The result is a hard deadlock.

### Call stack at deadlock

```
serialize()                           # acquires self._lock
  └─ _safe_dumps(arg)
       └─ _build_snapshot(arg)
            └─ _safe_repr(nested_obj)
                 └─ repr(nested_obj)        # nested_obj is a DebugProxy
                      └─ DebugProxy.__repr__
                           └─ _intercept_dunder("__repr__")
                                └─ _wrap_method(...)
                                     └─ record_call_start(...)
                                          └─ _build_call_payload(...)
                                               └─ serialize(target)
                                                    └─ self._lock  💀 DEADLOCK
```

### Why Ctrl-C doesn't work

CPython cannot deliver `SIGINT` to a thread that is blocked on
`threading.Lock.acquire()` — the call blocks at the C level without releasing
the GIL. The only way to kill the process is `kill -9`.

## Reproduction (no NAT dependency)

The following standalone script reproduces the deadlock using only
`cideldill_client` public APIs:

```python
"""
Standalone reproduction of the serializer lock deadlock.

Run with:  python repro_deadlock.py
Expected:  Process hangs, deadlock watchdog fires after ~30s.
Kill with: kill -9 <pid>
"""

import asyncio
import dataclasses
from cideldill_client import with_debug, async_debug_call


# 1. Initialize cideldill debug (connects to server, or set CIDELDILL_URL)
with_debug()


# 2. Create an object and wrap it in a DebugProxy
class MyTool:
    def run(self, query: str) -> str:
        return f"result for {query}"

tool = MyTool()
proxied_tool = with_debug(("repro:tool", tool))


# 3. Create a container that holds the proxied object as a field.
#    This simulates a WorkflowBuilder that has DebugProxy-wrapped tools/LLMs.
@dataclasses.dataclass
class Container:
    name: str
    tool: object   # will hold the DebugProxy

container = Container(name="test", tool=proxied_tool)


# 4. Pass the container as an argument to async_debug_call.
#    Serialization of `container` will encounter `proxied_tool`,
#    call its __repr__, which re-enters record_call_start → deadlock.
async def setup(container):
    print("setup called — this should print but won't due to deadlock")

async def main():
    print(f"PID: {__import__('os').getpid()}")
    print("Calling async_debug_call — will deadlock during argument serialization...")
    await async_debug_call(
        "repro:setup",
        setup,
        container,   # <-- contains a DebugProxy field → triggers deadlock
    )
    print("Done — you will never see this")

asyncio.run(main())
```

### Alternate minimal reproduction (sync, via DebugProxy directly)

```python
"""
Sync reproduction: pass a DebugProxy-containing object to a proxied method.
"""

from cideldill_client import with_debug


with_debug()

class Inner:
    def do_work(self):
        return 42

class Outer:
    def process(self, helper):
        return helper.do_work()

inner = Inner()
proxied_inner = with_debug(("repro:inner", inner))

outer = Outer()
proxied_outer = with_debug(("repro:outer", outer))

# Calling a method on proxied_outer with proxied_inner as an argument.
# record_call_start serializes proxied_inner → repr → re-enters → deadlock.
proxied_outer.process(proxied_inner)
```

## Observed behavior

1. Process hangs during `record_call_start`.
2. After ~30 seconds, deadlock watchdog logs:
   ```
   Potential deadlock detected in cideldill client: operation=record_call_start
   age=30.7s active_operations=2 timeout=30.0s
   ```
3. Two identical stack traces shown, both blocked at `serialization_common.py`
   line 627 (`with self._lock:`).
4. Process is unresponsive to Ctrl-C. Must be killed with `kill -9`.

## Suggested fixes (in order of preference)

### Fix 1: Use `threading.RLock` instead of `threading.Lock` (one-line fix)

```python
# serialization_common.py:623
-        self._lock = threading.Lock()
+        self._lock = threading.RLock()
```

This allows reentrant acquisition on the same thread. The inner `serialize()`
call from `DebugProxy.__repr__` would succeed instead of deadlocking.

**Pros:** Minimal change, fixes the deadlock entirely.
**Cons:** Masks the fact that serialization is doing unexpected re-entrant work
(calling `record_call_start` during `repr` of arguments). Performance impact is
negligible.

### Fix 2: Detect `DebugProxy` during serialization and skip `repr` interception

In `_safe_repr`, check if the object is a `DebugProxy` and access its
`_target.__repr__` directly to avoid triggering `_intercept_dunder`:

```python
# serialization_common.py, in _safe_repr:
def _safe_repr(obj, *, max_length=MAX_REPR_LENGTH):
    try:
        # Bypass DebugProxy interception to avoid re-entering record_call_start
        target = object.__getattribute__(obj, "_target") if _is_debug_proxy(obj) else None
        text = repr(target) if target is not None else repr(obj)
    except Exception as exc:
        text = f"<repr failed: {type(exc).__name__}: {exc}>"
    return _truncate_text(text, max_length)
```

**Pros:** Avoids re-entrancy entirely; serialization never triggers debug
recording as a side effect.
**Cons:** Introduces a coupling between serialization and `DebugProxy`.

### Fix 3: Make `DebugProxy.__repr__` non-intercepting

Have `__repr__` delegate to the target directly without going through
`_intercept_dunder` / `_wrap_method`:

```python
# debug_proxy.py
def __repr__(self) -> str:
    return repr(self._target)
```

**Pros:** Eliminates the most common re-entrancy vector.
**Cons:** Loses debug tracing of `__repr__` calls (arguably not useful anyway).

### Fix 4: Detect and report the deadlock instead of hanging silently

If none of the above are desired, at minimum the deadlock watchdog should
**terminate the blocked operation** rather than just logging a warning. Options:

- Use `self._lock.acquire(timeout=N)` and raise a clear
  `CideldillDeadlockError` if the timeout expires.
- The error message should explain *why* it happened (DebugProxy in serialized
  argument graph) and suggest the user avoid passing proxy-wrapped objects as
  arguments.

```python
# serialization_common.py:625-628
def serialize(self, obj):
    acquired = self._lock.acquire(timeout=30.0)
    if not acquired:
        raise CideldillDeadlockError(
            f"Serializer lock deadlock detected while serializing {type(obj).__name__}. "
            f"This usually means a DebugProxy object was encountered during argument "
            f"serialization, causing re-entrant record_call_start. "
            f"Avoid passing DebugProxy-wrapped objects as arguments to "
            f"async_debug_call or other proxied methods."
        )
    try:
        pickled = _safe_dumps(obj)
        cid = hashlib.sha256(pickled).hexdigest()
        ...
    finally:
        self._lock.release()
```

## Recommendation

**Apply Fix 1 (RLock) *and* Fix 2 or Fix 3** together:

- The `RLock` is a safety net that prevents *any* reentrant deadlock in the
  serializer, regardless of the cause.
- Fix 2 or 3 eliminates the unnecessary re-entrant work (serialization should
  never trigger debug recording as a side effect).
- Fix 4 should be applied regardless as defense-in-depth — a locked-up process
  that ignores Ctrl-C is the worst possible failure mode.
