# Bug: `DebugProxy.__getattr__` AttributeError bypasses breakpoint server reporting

## Summary

When a `DebugProxy` wraps a target that does not have a requested attribute, the resulting `AttributeError` is raised directly from `__getattr__` without being reported to the breakpoint server. This means the error is invisible in the debug UI — it only appears in the application's console/log output.

This is a significant observability gap: the debug server sees the proxied object registered and can set breakpoints on it, but never learns that a call-site interaction with that object failed.

## Affected Code

- **File:** `cideldill_client/debug_proxy.py`
- **Method:** `DebugProxy.__getattr__` (line 188–194)

```python
def __getattr__(self, name: str) -> Any:
    attr = getattr(self._target, name)  # <-- raises AttributeError directly
    if callable(attr):
        if inspect.iscoroutinefunction(attr):
            return self._wrap_async_method(attr, name)
        return self._wrap_method(attr, name)
    return attr
```

## Root Cause

`__getattr__` delegates attribute lookup to `self._target` with a bare `getattr()` call. If the target does not have the requested attribute, Python raises `AttributeError` immediately. This exception propagates up the call stack as a normal Python exception — it never passes through `record_call_start` / `record_call_complete`, so the breakpoint server is never notified.

By contrast, **method calls** on the proxy (via `__call__`, `_wrap_method`, `_wrap_async_method`) do go through the full `record_call_start` → execute → `record_call_complete` cycle, and exceptions raised during execution are reported to the server via `record_call_complete(status="exception", exception=exc)`.

## Reproduction Steps

### 1. Set up a minimal reproducer

```python
from cideldill_client import configure_debug, with_debug

# Enable debug, connecting to a running breakpoint server
configure_debug(server_url="http://localhost:5174")
with_debug("ON")

# Wrap a plain function (which has no .ainvoke attribute)
async def my_tool(*args, **kwargs):
    return {"result": "ok"}

proxied_tool = with_debug(("tool:my_tool", my_tool))
```

### 2. Access a non-existent attribute on the proxy

```python
# This raises AttributeError but the breakpoint server is NOT notified
try:
    proxied_tool.ainvoke({"name": "test"})
except AttributeError as e:
    print(f"Got error: {e}")
    # Error: 'function' object has no attribute 'ainvoke'
```

### 3. Observe

- **Console:** `AttributeError: 'function' object has no attribute 'ainvoke'` is printed/logged.
- **Breakpoint server UI:** No error event appears. The server shows `tool:my_tool` as registered but has no record of the failed interaction.

### Real-world trigger

This was discovered in a NAT (NVIDIA Agent Toolkit) debug wrapper integration. The wrapper:

1. Extracts a tool's callable via `ConfiguredFunction.instance`
2. Wraps it in an async function via `_make_tool_wrapper()` (a plain `async def`)
3. Passes that to `with_debug(("tool:asset_tool", simple_wrapper))`, producing a `DebugProxy` around the plain function
4. At runtime, the NAT workflow calls `asset_tool.ainvoke(...)` on the proxy
5. `DebugProxy.__getattr__("ainvoke")` delegates to `getattr(plain_function, "ainvoke")` → `AttributeError`
6. The error is never sent to the breakpoint server

The relevant log sequence:

```
DEBUG: get_function called for: asset_tool
DEBUG: Original function type: <class 'cideldill_client.debug_proxy.DebugProxy'>
DEBUG: Function 'asset_tool' has no .instance attribute
...
AttributeError: 'function' object has no attribute 'ainvoke'
```

## Expected Behavior

When `DebugProxy.__getattr__` fails because the target lacks the requested attribute, the breakpoint server should be notified of the failure — either as an event or as a failed call — so that the error is visible in the debug UI alongside other proxied interactions.

## Suggested Fix

Catch the `AttributeError` in `__getattr__` and report it to the debug server before re-raising:

```python
def __getattr__(self, name: str) -> Any:
    try:
        attr = getattr(self._target, name)
    except AttributeError:
        if self._is_enabled():
            try:
                call_site = {
                    "timestamp": time.time(),
                    "target_cid": self._cid,
                    "stack_trace": _build_stack_trace(skip=2),
                }
                self._client.record_event(
                    method_name=f"__getattr__({name!r})",
                    status="exception",
                    call_site=call_site,
                    exception={
                        "type": "AttributeError",
                        "message": f"{type(self._target).__name__!r} object has no attribute {name!r}",
                        "target_type": type(self._target).__qualname__,
                        "requested_attribute": name,
                    },
                )
            except Exception:
                pass  # Don't mask the original error
        raise
    if callable(attr):
        if inspect.iscoroutinefunction(attr):
            return self._wrap_async_method(attr, name)
        return self._wrap_method(attr, name)
    return attr
```

### Alternative / complementary approaches

- **Report via `record_call_complete`** with a synthetic `call_id` so the error appears in the call timeline rather than as a standalone event.
- **Add a `__getattr__` breakpoint label** during proxy construction so users can set breakpoints on attribute access itself.
- **Filter noise:** Only report `AttributeError` for attributes that look like intentional method calls (e.g., exclude dunder probing like `__len__`, `__iter__`, etc. that frameworks often speculatively check).

## Environment

- **cideldill client:** installed from source (`pip install -e ~/me/cideldill/client`)
- **Python:** 3.12
- **OS:** macOS (Apple Silicon)
