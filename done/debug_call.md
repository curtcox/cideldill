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

method_name = alias or _resolve_callable_name(func, None)
signature = compute_signature(func)
```

### Step 2: Build call site

`_build_stack_trace` is defined in `debug_proxy.py` and already imported by `with_debug.py`.

```python
call_site = {
    "timestamp": time.time(),
    "target_cid": compute_cid(func),
    "stack_trace": _build_stack_trace(skip=2),  # adjust skip to land on caller
}
```

### Step 3: record_call_start

Reuse the existing `DebugClient.record_call_start` — it already serializes target, args, kwargs individually and handles CID negotiation.

**`call_type` field in payload:** `call_type: "inline"` distinguishes inline breakpoints from proxy calls.

This is already implemented: `call_type` is a required keyword-only argument on both `DebugClient.record_call_start` and `_build_call_payload`:

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
    *,
    call_type: str,
) -> dict[str, Any]:
```

All existing proxy callers pass `call_type="proxy"`. `debug_call` will pass `call_type="inline"`.

### Step 4: Execute action

Reuse `DebugProxy._execute_action` logic, but extracted to a standalone function since we don't have a proxy instance. Factor out as a module-level helper:

```python
def execute_call_action(
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
        new_args, new_kwargs = deserialize_modified_args(action, client)
        return func(*new_args, **new_kwargs)
    if action_type == "skip":
        return deserialize_fake_result(action, client)
    if action_type == "raise":
        raise deserialize_exception(action)
    raise DebugProtocolError(f"Unknown action: {action_type}")
```

Async variant is identical but uses `await client.async_poll(action)` and `await` on func calls.

### Step 5: record_call_complete

```python
try:
    result = execute_call_action(action, client, func, call_args, kwargs)
except Exception as exc:
    client.record_call_complete(call_id=call_id, status="exception", exception=exc)
    raise

post_action = client.record_call_complete(call_id=call_id, status="success", result=result)
if post_action:
    wait_for_post_completion(post_action, client)

return result
```

---

## Refactoring: Extract from DebugProxy (DONE)

All helpers extracted as module-level functions in `debug_proxy.py`. `DebugProxy` methods are thin wrappers.

---

## Changes to DebugClient (DONE)

`call_type` is now a required keyword-only argument on both `_build_call_payload` and `record_call_start`. All existing proxy callers pass `call_type="proxy"`. No further changes needed for `debug_call`; it will pass `call_type="inline"`.

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

Cleared when debug is toggled OFF inside `with_debug()` (where `_state.enabled = False` is set):

```python
# Inside with_debug(), in the OFF branch:
_debug_call_registered.clear()
```

### debug_call before with_debug("ON")

`_is_debug_enabled()` returns `False` → direct call. Same as proxy behavior. No error.

---

## File Change Summary (ALL DONE)

| File | Change | Status |
|---|---|---|
| `with_debug.py` | `debug_call`, `async_debug_call`, `_parse_debug_call_args`, `_debug_call_registered` | DONE |
| `debug_proxy.py` | Extracted action helpers to module-level functions | DONE |
| `debug_client.py` | `call_type` required keyword-only param | DONE |
| `__init__.py` | Export `debug_call`, `async_debug_call` | DONE |

---

## Testing Plan (ALL DONE — 27 tests in test_debug_call.py)

All items covered. See `tests/unit/test_debug_call.py`.

---

## Documentation Updates (ALL DONE)

- `docs/with_debug_api.md`: Added `debug_call` / `async_debug_call` section.
- `client/docs/usage.md`: Added inline breakpoint example to Quick Start.
- `docs/breakpoints_web_ui.md`: Added Call Types section noting `call_type: "inline"`.
