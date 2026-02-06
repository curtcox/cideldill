# debug_call Implementation Plan

## Overview

`debug_call` is a one-shot inline breakpoint that captures a function call's inputs, sends them to the server, waits for the server's action response, executes accordingly, and reports the result. Think of it as a manually-placed `DebugProxy._wrap_method` invocation without needing to wrap the target object.

```python
from cideldill_client import debug_call

# Basic
y = debug_call(f, x, key=val)

# With alias
y = debug_call("step_3", f, x, key=val)

# Async
y = await async_debug_call(f, x)
y = await async_debug_call("step_3", f, x)
```

**When OFF:** `f(x, key=val)` — immediate call, zero server contact.
**When ON:** full round-trip to server with inspection/modification/replacement/skip/raise support.

---

## Signature

```python
def debug_call(__name_or_func, *args, **kwargs) -> Any:
    ...

async def async_debug_call(__name_or_func, *args, **kwargs) -> Any:
    ...
```

### Alias detection

The first positional arg is inspected:
- If `str` → alias name; second positional arg is the callable; remaining are call args.
- If `callable` → no alias; first positional arg is the callable; remaining are call args.
- Otherwise → `TypeError`.

```python
def _parse_debug_call_args(__name_or_func, *args):
    if isinstance(__name_or_func, str):
        alias = __name_or_func
        if not args:
            raise TypeError("debug_call with alias requires a callable as second argument")
        func = args[0]
        call_args = args[1:]
    elif callable(__name_or_func):
        alias = None
        func = __name_or_func
        call_args = args
    else:
        raise TypeError("debug_call expects a callable or (alias_str, callable, ...)")
    return alias, func, call_args
```

---

## Location

Add to `with_debug.py`. Reasons:
- Shares `_state`, `_is_debug_enabled`, `_resolve_server_url`, `_state_lock`.
- Both `with_debug` and `debug_call` are user-facing entry points with the same lifecycle dependency.
- Avoids circular imports or re-exporting shared state.

Export from `__init__.py`:

```python
__all__ = [
    "configure_debug",
    "with_debug",
    "debug_call",
    "async_debug_call",
]

from .with_debug import configure_debug, with_debug, debug_call, async_debug_call
```

---

## Behavior: Debug OFF

```python
def debug_call(__name_or_func, *args, **kwargs):
    alias, func, call_args = _parse_debug_call_args(__name_or_func, *args)
    if not _is_debug_enabled():
        return func(*call_args, **kwargs)
    ...
```

Alias is parsed (to keep the signature consistent) but discarded. Direct call, no server contact.

Async variant:

```python
async def async_debug_call(__name_or_func, *args, **kwargs):
    alias, func, call_args = _parse_debug_call_args(__name_or_func, *args)
    if not _is_debug_enabled():
        result = func(*call_args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
    ...
```

---

## Behavior: Debug ON

### Step 1: Resolve client and method name

```python
client = _state.client
if client is None:
    client = DebugClient(_resolve_server_url())
    _state.client = client

method_name = alias or getattr(func, "__name__", None) or type(func).__qualname__ + ".__call__"
signature = compute_signature(func)
```

### Step 2: Build call site

```python
call_site = {
    "timestamp": time.time(),
    "target_cid": compute_cid(func),
    "stack_trace": _build_stack_trace(skip=2),  # adjust skip to land on caller
}
```

### Step 3: record_call_start

Reuse the existing `DebugClient.record_call_start` — it already serializes target, args, kwargs individually and handles CID negotiation.

**New field in payload:** Add `call_type: "inline"` to distinguish from proxy calls.

This requires a small change to `DebugClient.record_call_start` and `_build_call_payload`:

```python
def record_call_start(
    self,
    method_name: str,
    target: Any,
    target_cid: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    call_site: dict[str, Any],
    signature: str | None = None,
    call_type: str = "proxy",         # NEW PARAMETER
) -> dict[str, Any]:
```

The `call_type` is passed through to `_build_call_payload` and included in the JSON payload. Server can ignore it today.

### Step 4: Execute action

Reuse `DebugProxy._execute_action` logic, but extracted to a standalone function since we don't have a proxy instance. Factor out as a module-level helper:

```python
def _execute_call_action(
    action: dict[str, Any],
    client: DebugClient,
    func: Callable,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    """Execute the server's action directive for a debug_call."""
    while action.get("action") == "poll":
        action = client.poll(action)

    action_type = action.get("action")
    if action_type == "continue":
        return func(*args, **kwargs)
    if action_type == "replace":
        function_name = action.get("function_name")
        if not function_name:
            raise DebugProtocolError("Missing function_name for replace action")
        replacement = get_function(function_name)
        if replacement is None:
            raise DebugProtocolError(f"Unknown replacement function: {function_name}")
        return replacement(*args, **kwargs)
    if action_type == "modify":
        modified_args = action.get("modified_args", [])
        modified_kwargs = action.get("modified_kwargs", {})
        new_args = tuple(client.deserialize_payload_list(modified_args))
        new_kwargs = client.deserialize_payload_dict(modified_kwargs)
        return func(*new_args, **new_kwargs)
    if action_type == "skip":
        return _deserialize_skip_result(action, client)
    if action_type == "raise":
        raise _deserialize_raise_exception(action)
    raise DebugProtocolError(f"Unknown action: {action_type}")
```

Async variant is identical but uses `await client.async_poll(action)` and `await` on func calls.

### Step 5: record_call_complete

```python
try:
    result = _execute_call_action(action, client, func, call_args, kwargs)
except Exception as exc:
    client.record_call_complete(call_id=call_id, status="exception", exception=exc)
    raise

post_action = client.record_call_complete(call_id=call_id, status="success", result=result)
if post_action:
    _wait_for_post_completion(post_action, client)

return result
```

---

## Refactoring: Extract from DebugProxy

Several pieces of `DebugProxy` logic will be reused by `debug_call`. To avoid duplication, extract these as module-level functions in `debug_proxy.py`:

| Current location | Extracted function | Used by |
|---|---|---|
| `DebugProxy._execute_action` | `execute_call_action(action, client, func, args, kwargs)` | `DebugProxy`, `debug_call` |
| `DebugProxy._execute_action_async` | `execute_call_action_async(...)` | `AsyncDebugProxy`, `async_debug_call` |
| `DebugProxy._deserialize_modified` | `deserialize_modified_args(action, client)` | above functions |
| `DebugProxy._deserialize_fake_result` | `deserialize_skip_result(action, client)` | above functions |
| `DebugProxy._deserialize_exception` | `deserialize_raise_exception(action)` | above functions |
| `DebugProxy._wait_for_post_completion` | `wait_for_post_completion(action, client)` | `DebugProxy`, `debug_call` |
| `DebugProxy._wait_for_post_completion_async` | `wait_for_post_completion_async(action, client)` | `AsyncDebugProxy`, `async_debug_call` |

`DebugProxy` methods become thin wrappers calling these extracted functions with `self._client`.

---

## Changes to DebugClient

### `_build_call_payload`

Add required `call_type` parameter, include in payload:

```python
def _build_call_payload(
    self,
    method_name, target, target_cid, args, kwargs, call_site, signature,
    call_type,    # REQUIRED
):
    ...
    payload = {
        ...
        "call_type": call_type,
    }
    return payload, cid_to_obj
```

### `record_call_start`

Add required `call_type` parameter, thread through to `_build_call_payload`:

```python
def record_call_start(
    self, method_name, target, target_cid, args, kwargs, call_site,
    signature,
    call_type,    # REQUIRED
):
    ...
    payload, cid_to_obj = self._build_call_payload(
        effective_name, target, target_cid, args, kwargs, call_site, signature,
        call_type=call_type,
    )
    ...
```

All existing callers in `DebugProxy._wrap_method` and `_wrap_async_method` updated to pass `call_type="proxy"` explicitly.

---

## Complete debug_call Flow (sync)

```python
def debug_call(__name_or_func, *args, **kwargs):
    alias, func, call_args = _parse_debug_call_args(__name_or_func, *args)

    if not _is_debug_enabled():
        return func(*call_args, **kwargs)

    # Unwrap existing proxies
    if isinstance(func, (DebugProxy, AsyncDebugProxy)):
        func = object.__getattribute__(func, "_target")

    client = _state.client
    if client is None:
        client = DebugClient(_resolve_server_url())
        _state.client = client

    method_name = alias or _resolve_callable_name(func, None)
    signature = compute_signature(func)
    target_cid = compute_cid(func)

    # Register on first encounter
    reg_key = (method_name, id(func))
    if reg_key not in _debug_call_registered:
        _register_callable_or_halt(
            client, target=func, name=method_name, signature=signature,
        )
        _record_registration(
            client, name=method_name, signature=signature,
            alias_name=alias, target=func,
        )
        _debug_call_registered.add(reg_key)

    call_site = {
        "timestamp": time.time(),
        "target_cid": target_cid,
        "stack_trace": _build_stack_trace(skip=2),
    }

    action = client.record_call_start(
        method_name=method_name,
        target=func,
        target_cid=target_cid,
        args=call_args,
        kwargs=kwargs,
        call_site=call_site,
        signature=signature,
        call_type="inline",
    )

    call_id = action.get("call_id")
    if not call_id:
        raise DebugProtocolError("Missing call_id in response")

    try:
        result = execute_call_action(action, client, func, call_args, kwargs)
    except Exception as exc:
        try:
            client.record_call_complete(
                call_id=call_id, status="exception", exception=exc,
            )
        except DebugServerError:
            logger.exception("Failed to report exception for debug_call (call_id=%s)", call_id)
        raise

    try:
        post_action = client.record_call_complete(
            call_id=call_id, status="success", result=result,
        )
        if post_action:
            wait_for_post_completion(post_action, client)
    except DebugServerError:
        logger.exception("Failed to report completion for debug_call (call_id=%s)", call_id)

    return result
```

---

## Complete async_debug_call Flow

Identical structure, but:
- `await execute_call_action_async(...)` instead of `execute_call_action(...)`
- `await wait_for_post_completion_async(...)` for post-completion
- When OFF: `result = func(*call_args, **kwargs); return (await result) if isawaitable(result) else result`

---

## Edge Cases

### Callable detection with alias

`debug_call("step_3", f, x)` — `"step_3"` is both a `str` and technically the first positional arg. The parsing rule is unambiguous: if first arg is `str`, it's always treated as alias.

**Consequence:** You cannot `debug_call` a string-returning callable without an alias if the callable itself is a string. This is fine — strings aren't callable.

### func is already a DebugProxy

If `f` is already a `DebugProxy`, `debug_call` should unwrap it to avoid double-interception:

```python
if isinstance(func, (DebugProxy, AsyncDebugProxy)):
    func = object.__getattribute__(func, "_target")
```

### func is already a DebugProxy

If `f` is already a `DebugProxy`, `debug_call` should unwrap it to avoid double-interception:

```python
if isinstance(func, (DebugProxy, AsyncDebugProxy)):
    func = object.__getattribute__(func, "_target")
```

### Registration on first encounter

`debug_call` targets can be called repeatedly (e.g., in loops). The callable should be registered with the server on first encounter so breakpoint matching and UI autocompletion work, but not re-registered on every iteration.

Module-level tracking in `with_debug.py`:

```python
_debug_call_registered: set[tuple[str, int]] = set()
```

Inside `debug_call`, after resolving `method_name` and `func`:

```python
reg_key = (method_name, id(func))
if reg_key not in _debug_call_registered:
    _register_callable_or_halt(
        client, target=func, name=method_name, signature=signature,
    )
    _record_registration(
        client, name=method_name, signature=signature,
        alias_name=alias, target=func,
    )
    _debug_call_registered.add(reg_key)
```

Cleared when debug is toggled OFF in `_set_debug_mode`:

```python
def _set_debug_mode(enabled: bool) -> DebugInfo:
    if not enabled:
        ...
        _debug_call_registered.clear()
        ...
```

### debug_call before with_debug("ON")

`_is_debug_enabled()` returns `False` → direct call. Same as proxy behavior. No error.

---

## File Change Summary

| File | Change |
|---|---|
| `with_debug.py` | Add `debug_call`, `async_debug_call`, `_parse_debug_call_args`, `_debug_call_registered` set; clear set in `_set_debug_mode` |
| `debug_proxy.py` | Extract action execution helpers to module-level functions; `DebugProxy` methods become wrappers; pass `call_type="proxy"` explicitly |
| `debug_client.py` | Make `call_type` a required param on `record_call_start` and `_build_call_payload` |
| `__init__.py` | Export `debug_call`, `async_debug_call` |

### No changes needed

| File | Why |
|---|---|
| `serialization.py` / `serialization_common.py` | Existing serialize/deserialize reused as-is |
| `custom_picklers.py` | No new types to register |
| `function_registry.py` | Reused as-is for registration via existing `_register_callable_or_halt` |
| `exceptions.py` | Existing exceptions cover all cases |
| `server_failure.py` | Existing exit helpers sufficient |

---

## Testing Plan

1. **OFF mode:** `debug_call(f, x)` and `debug_call("alias", f, x)` both return `f(x)` with no server contact.
2. **ON mode, continue:** Server returns continue → `f(x)` executes normally.
3. **ON mode, modify:** Server returns modified args → `f(new_x)`.
4. **ON mode, skip:** Server returns fake result → `f` never called.
5. **ON mode, replace:** Server names a replacement → replacement called.
6. **ON mode, raise:** Server specifies exception → raised without calling `f`.
7. **ON mode, poll:** Server returns poll → client polls until ready.
8. **Async variants:** Mirror of all above with `async_debug_call`.
9. **Alias parsing:** Verify `str` first arg → alias, callable first arg → no alias, non-callable non-string → TypeError.
10. **DebugProxy unwrap:** `debug_call(wrapped_f, x)` unwraps before calling.
11. **`call_type` field:** Verify `"inline"` in `debug_call` payload, `"proxy"` in DebugProxy payload.
12. **Registration:** First `debug_call(f, x)` registers `f`; subsequent calls in a loop do not re-register.
13. **Registration cleared on OFF:** `with_debug("OFF")` clears `_debug_call_registered`; next `with_debug("ON")` + `debug_call` re-registers.
14. **Refactor regression:** Existing `DebugProxy` tests still pass after extraction and required `call_type`.

---

## Documentation Updates

- `docs/with_debug_api.md`: Add `debug_call` / `async_debug_call` section.
- `client/docs/usage.md`: Add inline breakpoint example to Quick Start.
- `docs/breakpoints_web_ui.md`: Note that inline breakpoints appear in the call list with `call_type: "inline"`.
