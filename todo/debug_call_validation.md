# debug_call.md — Validation Against Server Implementation

## Mismatches and Issues

### 1. `call_type` inconsistent: optional vs required across sections (Medium)

The document first introduces `call_type` as an optional parameter with default `"proxy"` (Step 3):

```python
call_type: str = "proxy",         # NEW PARAMETER
```

But the "Changes to DebugClient" section later says it should be **required** (no default):

```python
call_type,    # REQUIRED
```

Neither the server nor the client currently reference `call_type` at all. The document
should pick one convention. "Required" is more appropriate since every call site should
explicitly declare its type.

### 2. Step 1 `method_name` fallback misses `functools.partial` (Medium)

Step 1 proposes an inline fallback:

```python
method_name = alias or getattr(func, "__name__", None) or type(func).__qualname__ + ".__call__"
```

The actual `_resolve_callable_name` at `with_debug.py:280-288` also handles
`functools.partial` by recursing into `target.func`. The "Complete debug_call Flow"
section later correctly calls `_resolve_callable_name(func, None)`, but the Step 1
snippet diverges and would miss partial unwrapping. Step 1 should reference
`_resolve_callable_name` rather than inline a different version.

### 3. `_build_stack_trace` import dependency not mentioned (Low)

The document says `debug_call` should live in `with_debug.py` and lists shared
dependencies. It uses `_build_stack_trace(skip=2)` but never mentions that this function
is defined in `debug_proxy.py:19-30` and must be imported. `with_debug.py` already does
this import (`from .debug_proxy import ... _build_stack_trace`), so it works, but the
document should note this cross-module dependency.

### 4. Three different naming conventions for extracted functions (High)

The same functions are named differently in three places:

| Step 4 code | Refactoring table | Complete Flow |
|---|---|---|
| `_execute_call_action` | `execute_call_action` | `execute_call_action` |
| `_deserialize_skip_result` | `deserialize_skip_result` | (via `execute_call_action`) |
| `_deserialize_raise_exception` | `deserialize_raise_exception` | (via `execute_call_action`) |

The actual `DebugProxy` methods being extracted are:
- `_deserialize_fake_result` (not `skip_result`)
- `_deserialize_exception` (not `raise_exception`)

The document should settle on one naming scheme. The refactoring table names
(`execute_call_action`, `deserialize_skip_result`, `deserialize_raise_exception`) are
the most explicit, but they should at least match the source names for traceability.

### 5. Duplicate "func is already a DebugProxy" section (Low)

The "Edge Cases" section contains two identical subsections for "func is already a
DebugProxy" (lines ~378-392 duplicate lines ~385-392). Copy-paste error.

### 6. `_set_debug_mode` function does not exist (Medium)

The document's registration-clearing section references:

```python
def _set_debug_mode(enabled: bool) -> DebugInfo:
    if not enabled:
        ...
        _debug_call_registered.clear()
```

No such function exists. Debug toggling is handled inline within `with_debug()` at
`with_debug.py:48-176`. The `_debug_call_registered.clear()` call would need to go
inside `with_debug()` where `_state.enabled = False` is set.

## Items That Validated Successfully

- `DebugClient.record_call_start` signature matches (minus `call_type` which is new).
- `DebugClient.record_call_complete` signature matches (`call_id`, `status`, `result`, `exception`).
- `_is_debug_enabled()`, `_state`, `_resolve_server_url()`, `_state_lock` all exist in `with_debug.py`.
- `_register_callable_or_halt` and `_record_registration` signatures and locations match.
- `compute_signature` (in `function_registry.py`) and `compute_cid` (in `serialization.py`) exist and match.
- `get_function` in `function_registry.py` matches the replacement lookup pattern.
- `DebugProxy._execute_action` logic matches the proposed standalone extraction.
- `DebugProxy._wait_for_post_completion` and async variant match the document.
- `_deserialize_fake_result` correctly needs `client` for deserialization; `_deserialize_exception` does not.
- `DebugProxy`/`AsyncDebugProxy` unwrapping via `object.__getattribute__` is correct.
- Exception classes `DebugProtocolError` and `DebugServerError` exist in `exceptions.py`.
- `__init__.py` currently exports `configure_debug` and `with_debug` — adding the new exports is straightforward.
- Serialization methods (`deserialize_payload_list`, `deserialize_payload_dict`) exist on `DebugClient`.
- Server action types (`continue`, `replace`, `modify`, `skip`, `raise`, `poll`) match client handling.
