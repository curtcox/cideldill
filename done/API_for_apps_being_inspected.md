# API for Apps Being Inspected

## Implementation Status

**Status: Complete ✅**

Completed:
- Implemented `with_debug` entry point and global config.
- Added debug proxy, client, info, serialization, and exception modules.
- Updated breakpoint server/manager for request-response flow.
- Removed old Interceptor/Inspector API and legacy examples/tests.
- Updated documentation and examples for the new API.

## Overview

This document specifies how applications being inspected should use the debugging API. The goal is to provide a simple, clean API that eliminates the current sync mechanism in favor of a request-response model where the server controls client behavior.

## Core API Design

### The `with_debug` Function

The `with_debug` function is the single entry point for all debugging functionality:

```python
from cideldill import with_debug

# Enable debugging and get info object
info = with_debug('ON')

# Disable debugging and get info object
info = with_debug('OFF')

# Wrap an object for debugging
debug_obj = with_debug(original_obj)
```

### API Behavior by Mode

**Important**: `with_debug('ON')` or `with_debug('OFF')` is called **once at application startup**. The debug state does not change while the application is running. This simplifies implementation significantly.

#### `with_debug('ON')`

- Enables debugging **globally for all threads** in the current process
- Returns a `DebugInfo` object that can be interrogated
- All subsequent `with_debug(obj)` calls return debug-wrapped proxy objects
- Network requests are made to the debug server for each intercepted call
- Breakpoints can trigger and pause execution
- **If the server is unreachable, raises an exception** (fail-closed)

```python
info = with_debug('ON')
info.is_enabled()      # Returns True
info.server_url()      # Returns the debug server URL
info.connection_status()  # Returns 'connected', 'disconnected', 'error'
```

#### `with_debug('OFF')`

- Disables debugging **globally for all threads** in the current process
- Returns a `DebugInfo` object that can be interrogated
- All subsequent `with_debug(obj)` calls return the **original object unchanged** (true NOP)
- **No breakpoints trigger**
- **No network requests are made**
- **No calls are logged**
- **Zero performance overhead** - the object is returned as-is

```python
info = with_debug('OFF')
info.is_enabled()      # Returns False
info.server_url()      # Returns None
info.connection_status()  # Returns 'disabled'
```

#### `with_debug(obj)`

- **When debug is ON**: Returns a proxy object that intercepts all method calls and communicates with server
- **When debug is OFF**: Returns the **original object unchanged** - a true NOP with zero overhead
- When returned proxy is used, client code uses it exactly like the original
- Can wrap **any object** including built-in types (`list`, `dict`, etc.)

**When debug is ON:**
```python
# Example usage
calculator = Calculator()
calculator = with_debug(calculator)  # Returns DebugProxy

# Use exactly like the original
result = calculator.add(1, 2)  # Intercepted for debugging

# Identity is not preserved when debug is ON
assert calculator is not Calculator()  # True - it's a proxy
```

**When debug is OFF:**
```python
# Example usage
calculator = Calculator()
calculator = with_debug(calculator)  # Returns calculator unchanged (NOP)

# Use exactly like the original
result = calculator.add(1, 2)  # Direct call, no overhead

# Identity IS preserved when debug is OFF
assert calculator is calculator  # True - same object returned
```

### Serialization with Dill and CID

All objects (arguments, return values, etc.) are serialized using **dill** (not cloudpickle or JSON).

#### Content-Addressed Storage

Every object is assigned a **CID (Content Identifier)** - a hash of its dill-pickled representation.

```python
import dill
import hashlib

def compute_cid(obj):
    """Compute the CID for any object."""
    pickled = dill.dumps(obj)
    return hashlib.sha256(pickled).hexdigest()
```

#### Transmission Protocol

- First time an object is sent: Send both the **dill pickle** and the **CID**
- Subsequent times: Send **only the CID** (server already has the pickled data)
- Client maintains an **LRU cache of 10,000 entries** for recently sent CIDs
- **Server is the source of truth** for CID→data mappings

**CID Verification Protocol:**

1. Client sends CID-only (no data) for objects it believes server has
2. Server checks its database:
   - If CID exists: Verifies data integrity, proceeds normally
   - If CID missing: Returns error, client must resend with full data
   - If CID mismatch (data doesn't match): Returns `DebugCIDMismatchError`
3. Client evicts oldest CIDs from its cache when limit reached

```python
# Request format
{
    "method_name": "calculate",
    "target_cid": "abc123...",           # CID of the proxied object
    "args": [
        {"cid": "def456...", "data": "<base64 dill pickle>"},  # First time or cache miss
        {"cid": "ghi789..."}                                    # In client cache
    ],
    "call_site": {
        "stack_trace": [...],
        "timestamp": 1234567890.123,
        "target_cid": "abc123..."
    }
}

# Server response for missing CID
{
    "error": "cid_not_found",
    "missing_cids": ["ghi789..."],
    "message": "Resend with full data"
}
```

### Call Site Information

Every intercepted call includes comprehensive call site information:

```python
call_site = {
    "timestamp": 1234567890.123456,      # Unix timestamp with microseconds
    "target_cid": "abc123...",           # CID of the object being called
    "stack_trace": [                     # Full stack trace
        {
            "filename": "/path/to/file.py",
            "lineno": 42,
            "function": "main",
            "code_context": "result = calculator.add(1, 2)",
            "locals": {...}              # Optional: local variables
        },
        {
            "filename": "/path/to/other.py",
            "lineno": 15,
            "function": "helper",
            "code_context": "return do_calculation()",
            "locals": {...}
        }
        # ... all frames up to the call
    ]
}
```

### Server Response Protocol

When debugging is enabled, every intercepted call follows this protocol:

1. Client sends call information to server (function name, args as dill+CID, call site)
2. Server responds with an action dictating client behavior
3. Client executes based on the action

#### Server Response Format

Every response from `/api/call/start` includes a **timestamp-based call ID** for tracking:

```python
{
    "call_id": "1234567890.123456-001",  # Timestamp-based ID (Unix timestamp + sequence)
    "action": "continue" | "poll" | "skip" | "raise" | "modify",

    # For action="continue": proceed with original call
    # No additional fields required

    # For action="poll": wait and poll until allowed to continue
    "poll_interval_ms": 100,     # How often to poll
    "poll_url": "/api/poll/{id}", # URL to poll for status
    "timeout_ms": 60000,          # When to give up (raises exception)

    # For action="skip": skip the call, return fake result
    "fake_result_cid": "xyz...", # CID of result (if known)
    "fake_result_data": "...",   # Base64 dill pickle (if new)

    # For action="raise": raise an exception instead of calling
    "exception_type": "ValueError",
    "exception_message": "Forced error for testing",

    # For action="modify": continue with modified arguments
    "modified_args": [           # Positional args as CID or CID+data
        {"cid": "abc...", "data": "..."},
        {"cid": "def..."}
    ],
    "modified_kwargs": {         # Keyword args as CID or CID+data
        "x": {"cid": "ghi...", "data": "..."}
    }
}
```

#### Polling Protocol (for breakpoints)

When server returns `action="poll"`, the client:

1. Does NOT execute the original call yet
2. Polls the server at the specified interval
3. Each poll response is either:
   - `{"status": "waiting"}` - continue polling
   - `{"status": "ready", "action": {...}}` - proceed with the enclosed action
4. **If timeout is reached, raises `DebugTimeoutError`** (fail-closed)
5. Client continues based on the final action received

```python
# Polling sequence example
POST /api/call/start
  <- {"action": "poll", "poll_interval_ms": 50, "poll_url": "/api/poll/abc123", "timeout_ms": 60000}

GET /api/poll/abc123
  <- {"status": "waiting"}

GET /api/poll/abc123
  <- {"status": "waiting"}

GET /api/poll/abc123
  <- {"status": "ready", "action": {"action": "continue"}}

# Now client proceeds with the call
```

### Call Completion Protocol

After every call completes (whether successful or exception), the client notifies the server:

```python
# Successful completion
POST /api/call/complete
{
    "call_id": "abc123...",              # ID from call/start response
    "timestamp": 1234567890.456789,      # Completion timestamp
    "status": "success",
    "result_cid": "xyz789...",           # CID of return value
    "result_data": "..."                 # Base64 dill pickle (if new CID)
}

# Exception completion
POST /api/call/complete
{
    "call_id": "abc123...",
    "timestamp": 1234567890.456789,
    "status": "exception",
    "exception_type": "ValueError",
    "exception_message": "invalid input",
    "exception_cid": "exc123...",        # CID of full exception object
    "exception_data": "..."              # Base64 dill pickle (if new CID)
}
```

The server responds with acknowledgment:

```python
{"status": "ok"}
```

### Async Support

The debug proxy provides **full async support** with async-aware proxies:

```python
class AsyncDebugProxy:
    """Async-aware proxy that intercepts both sync and async method calls."""

    async def _wrap_async_method(self, method, name):
        async def wrapper(*args, **kwargs):
            # Notify server and get action (sync HTTP call)
            action = self._client.record_call_start(...)

            # Handle polling asynchronously if needed
            if action["action"] == "poll":
                action = await self._async_poll(action)

            # Execute based on action
            if action["action"] == "continue":
                return await method(*args, **kwargs)
            # ... handle other actions

        return wrapper
```

- Sync methods on proxied objects work synchronously
- Async methods on proxied objects work asynchronously
- Server communication is always synchronous HTTP (debugging latency is acceptable)
- Async polling uses `asyncio.sleep()` instead of `time.sleep()`

### Debug Object Proxy Behavior

The debug proxy wraps objects and intercepts **all** method calls including dunder methods:

```python
class DebugProxy:
    """Transparent proxy that intercepts all method calls for debugging."""

    def __init__(self, target, debug_client, is_enabled_func):
        object.__setattr__(self, '_target', target)
        object.__setattr__(self, '_client', debug_client)
        object.__setattr__(self, '_is_enabled', is_enabled_func)
        object.__setattr__(self, '_cid', compute_cid(target))

    def __getattr__(self, name):
        attr = getattr(self._target, name)
        if callable(attr):
            if self._is_enabled():
                return self._wrap_method(attr, name)
            else:
                return attr  # No-op when disabled
        return attr

    # Intercept ALL dunder methods for built-in types
    def __str__(self):
        return self._intercept_dunder('__str__')

    def __repr__(self):
        return self._intercept_dunder('__repr__')

    def __iter__(self):
        return self._intercept_dunder('__iter__')

    def __len__(self):
        return self._intercept_dunder('__len__')

    def __getitem__(self, key):
        return self._intercept_dunder('__getitem__', key)

    def __setitem__(self, key, value):
        return self._intercept_dunder('__setitem__', key, value)

    # ... all other dunder methods

    def __eq__(self, other):
        # Proxy equality is always False vs non-proxy
        if not isinstance(other, DebugProxy):
            return False
        return self._target == other._target

    def __hash__(self):
        return hash(self._target)
```

### Error Handling

All errors follow a **fail-closed** policy:

| Scenario | Behavior |
|----------|----------|
| Server unreachable on `with_debug('ON')` | Raises `DebugServerError` |
| Server unreachable during call | Raises `DebugServerError` |
| Poll timeout | Raises `DebugTimeoutError` |
| Malformed server response | Raises `DebugProtocolError` |
| Unknown action type | Raises `DebugProtocolError` |
| Proxy internal error | **Propagates the exception** |
| Object cannot be dill pickled | Raises `DebugSerializationError` |
| CID not found on server | Raises `DebugCIDNotFoundError` (client should resend with data) |
| CID data mismatch on server | Raises `DebugCIDMismatchError` |

### Configuration

Debug server connection is configured via:

```python
# Option 1: Environment variable
export CIDELDILL_SERVER_URL="http://localhost:5000"

# Option 2: Explicit configuration before enabling
from cideldill import configure_debug
configure_debug(server_url="http://localhost:5000")
info = with_debug('ON')

# Option 3: Auto-discovery (default)
# Looks for server on localhost:5000
```

**Security Model**: No authentication, localhost only. The server should only bind to 127.0.0.1.

---

## Design Decisions (Resolved)

| Question | Decision | Rationale |
|----------|----------|-----------|
| Serialization | **Dill** | More capable than cloudpickle, handles more Python objects |
| Timeout behavior | **Fail-closed** (raise exception) | Debugging should be explicit; silent failures hide problems |
| Server unavailable | **Raise exception** | Same rationale; debugging is opt-in and should fail loudly |
| Thread isolation | **Global** | Debugging is typically for entire application, not per-thread |
| Async support | **Full async proxies** | Modern Python apps use async; must be first-class |
| Object identity | **Never True** | Proxies are distinct objects; identity checks should reflect this |
| Built-in wrapping | **Wrap everything** | Consistent behavior; no special cases |
| Call site info | **Full stack + timestamp + CID** | Maximum observability for debugging |
| Return values | **Dill + CID deduplication** | Efficient transmission, full fidelity |
| Proxy exceptions | **Propagate** | Don't hide infrastructure errors |
| Multiple servers | **Single only** | Simplicity; can extend later if needed |
| Security | **No auth, localhost only** | Development tool; not designed for production |
| Latency | **Accept it** | Debugging isn't performance-critical |
| Old API | **Remove entirely** | Clean break; no maintenance burden |
| CID session tracking | **Never reset; server is source of truth** | Client uses finite LRU cache; server validates all CIDs |
| Async server calls | **Always sync** | Simpler implementation; debugging latency acceptable |
| Built-in arithmetic | **Intercept all dunders** | Consistent with "wrap everything"; simpler implementation |
| Dill failure | **No fallback** | Raise `DebugSerializationError`; fail-closed policy |
| Call completion | **Yes, notify server** | POST /api/call/complete with result CID and timestamp |
| Proxy for None | **Wrap in proxy** | Consistent behavior; no special cases |
| CID cache size | **10,000 entries** | Balance between memory usage and hit rate |
| Call ID format | **Timestamp-based** | Human-readable, sortable, includes sequence number |
| Arithmetic return type | **Raw value (unwrapped)** | Simpler implementation; avoids proxy explosion |
| Debug state changes | **Startup only** | with_debug('ON'/'OFF') called once; state never changes at runtime |

---

## Files That Need to Be Updated

### Core Implementation Files

| File | Current State | Required Changes |
|------|---------------|------------------|
| `src/cideldill/__init__.py` | Exports Interceptor, Logger, etc. | Export only `with_debug`, `configure_debug`; remove old exports |
| `src/cideldill/interceptor.py` | Function-based wrapping with sync | **DELETE** - replaced by new implementation |
| `src/cideldill/breakpoint_manager.py` | Thread-based polling sync | Simplify to pure state management, remove sync thread |
| `src/cideldill/breakpoint_server.py` | Current REST API | Add `/api/call/start`, `/api/poll/{id}` endpoints; update for dill/CID |
| `src/cideldill/inspector.py` | Stub for remote agent | **DELETE** - replaced by debug_client |
| `src/cideldill/cas_store.py` | SHA256-based CAS | Update to use dill serialization |
| **NEW** `src/cideldill/debug_proxy.py` | Does not exist | Create DebugProxy and AsyncDebugProxy classes |
| **NEW** `src/cideldill/debug_info.py` | Does not exist | Create DebugInfo class |
| **NEW** `src/cideldill/debug_client.py` | Does not exist | Create HTTP client for server communication |
| **NEW** `src/cideldill/with_debug.py` | Does not exist | Implement `with_debug()` function and global state |
| **NEW** `src/cideldill/serialization.py` | Does not exist | Dill serialization and CID computation |
| **NEW** `src/cideldill/exceptions.py` | Does not exist | Custom exception classes |

### Dependencies

| Package | Purpose |
|---------|---------|
| `dill` | Object serialization (more capable than pickle/cloudpickle) |
| `requests` | HTTP client for server communication |
| `flask` | Already present for breakpoint server |

### Test Files

| File | Current State | Required Changes |
|------|---------------|------------------|
| `tests/unit/test_interceptor.py` | Tests current wrap() API | **DELETE** - old API removed |
| `tests/unit/test_interceptor_realtime.py` | Tests observers/breakpoints | **DELETE** - old API removed |
| `tests/unit/test_breakpoint_server.py` | Tests current endpoints | Update for new endpoints |
| `tests/integration/test_breakpoint_workflow.py` | Tests sync-based workflow | Refactor for new workflow |
| **NEW** `tests/unit/test_with_debug.py` | Does not exist | Comprehensive with_debug tests |
| **NEW** `tests/unit/test_debug_proxy.py` | Does not exist | Proxy behavior tests |
| **NEW** `tests/unit/test_async_proxy.py` | Does not exist | Async proxy tests |
| **NEW** `tests/unit/test_debug_client.py` | Does not exist | HTTP client tests |
| **NEW** `tests/unit/test_serialization.py` | Does not exist | Dill/CID tests |
| **NEW** `tests/unit/test_builtin_wrapping.py` | Does not exist | Built-in type proxy tests |
| **NEW** `tests/integration/test_request_response_workflow.py` | Does not exist | End-to-end tests |
| **NEW** `tests/integration/test_async_workflow.py` | Does not exist | Async end-to-end tests |

### Documentation Files

| File | Current State | Required Changes |
|------|---------------|------------------|
| `README.md` | Documents current API | Complete rewrite for with_debug API |
| `docs/breakpoints_web_ui.md` | Current breakpoint guide | Update for new API |
| `P0_IMPLEMENTATION_SUMMARY.md` | Current feature summary | **DELETE** - superseded |
| `done/use_cases.md` | Maps use cases to code | Update for new architecture |
| **NEW** `docs/with_debug_api.md` | Does not exist | Complete API reference |

### Example Files

| File | Current State | Required Changes |
|------|---------------|------------------|
| `examples/p0_features_demo.py` | Uses Interceptor.wrap() | **DELETE** - old API |
| `examples/interactive_breakpoint_demo.py` | Uses sync thread | **DELETE** - old API |
| `examples/demo_call_tracking.py` | Basic tracking demo | **DELETE** - old API |
| **NEW** `examples/with_debug_basic.py` | Does not exist | Simple with_debug example |
| **NEW** `examples/with_debug_async.py` | Does not exist | Async example |
| **NEW** `examples/with_debug_builtins.py` | Does not exist | Built-in types example |

---

## Complete Test List

### 1. `with_debug` Function Tests

#### 1.1 Mode Switching Tests
```python
def test_with_debug_on_enables_debugging():
    """with_debug('ON') enables debugging globally."""

def test_with_debug_off_disables_debugging():
    """with_debug('OFF') disables debugging globally."""

def test_with_debug_on_returns_debug_info():
    """with_debug('ON') returns a DebugInfo object."""

def test_with_debug_off_returns_debug_info():
    """with_debug('OFF') returns a DebugInfo object."""

def test_with_debug_on_is_case_insensitive():
    """with_debug('on'), with_debug('On'), with_debug('ON') all work."""

def test_with_debug_off_is_case_insensitive():
    """with_debug('off'), with_debug('Off'), with_debug('OFF') all work."""

def test_with_debug_invalid_string_raises():
    """with_debug('invalid') raises ValueError."""

def test_with_debug_on_twice_is_idempotent():
    """Calling with_debug('ON') twice doesn't cause issues."""

def test_with_debug_off_twice_is_idempotent():
    """Calling with_debug('OFF') twice doesn't cause issues."""

def test_with_debug_on_affects_all_threads():
    """with_debug('ON') enables debugging for all threads."""

def test_with_debug_off_affects_all_threads():
    """with_debug('OFF') disables debugging for all threads."""

def test_with_debug_on_requires_server():
    """with_debug('ON') raises if server unreachable."""
```

#### 1.2 Object Wrapping Tests (Debug ON)
```python
def test_with_debug_obj_returns_proxy_when_on():
    """with_debug(obj) returns a DebugProxy when debugging is ON."""

def test_with_debug_obj_proxy_is_not_original():
    """The proxy is a different object than the original (is)."""

def test_with_debug_obj_proxy_not_equal_original():
    """The proxy is not equal to the original (==)."""

def test_with_debug_obj_proxy_has_same_methods():
    """The proxy has all the same methods as the original."""

def test_with_debug_obj_proxy_method_calls_intercepted():
    """Method calls on the proxy are sent to the server."""

def test_with_debug_obj_proxy_preserves_return_values():
    """Method return values are preserved through the proxy."""

def test_with_debug_obj_proxy_preserves_exceptions():
    """Exceptions from the original are propagated through the proxy."""

def test_with_debug_obj_proxy_preserves_attributes():
    """Non-callable attributes are accessible on the proxy."""

def test_with_debug_obj_can_wrap_class_instances():
    """Can wrap any class instance."""

def test_with_debug_obj_can_wrap_functions():
    """Can wrap standalone functions."""

def test_with_debug_obj_can_wrap_lambdas():
    """Can wrap lambda functions."""

def test_with_debug_obj_nested_wrapping():
    """Wrapping an already-wrapped object doesn't double-wrap."""

def test_with_debug_obj_computes_cid():
    """Proxy has a CID computed from the target."""

def test_with_debug_none_returns_proxy():
    """with_debug(None) returns a proxy wrapping None."""

def test_with_debug_none_proxy_works():
    """Proxy wrapping None behaves correctly."""
```

#### 1.3 Object Wrapping Tests (Debug OFF)
```python
def test_with_debug_obj_returns_noop_proxy_when_off():
    """with_debug(obj) returns a no-op proxy when debugging is OFF."""

def test_with_debug_obj_noop_proxy_not_original():
    """No-op proxy is still not the original object."""

def test_with_debug_obj_noop_proxy_not_equal_original():
    """No-op proxy is not equal to original."""

def test_with_debug_obj_no_network_when_off():
    """No network requests are made when debugging is OFF."""

def test_with_debug_obj_no_logging_when_off():
    """No calls are logged when debugging is OFF."""

def test_with_debug_obj_noop_proxy_minimal_overhead():
    """No-op proxy has minimal overhead."""
```

### 2. DebugInfo Object Tests

```python
def test_debug_info_is_enabled_true_when_on():
    """info.is_enabled() returns True when debug is ON."""

def test_debug_info_is_enabled_false_when_off():
    """info.is_enabled() returns False when debug is OFF."""

def test_debug_info_server_url_when_on():
    """info.server_url() returns the server URL when ON."""

def test_debug_info_server_url_none_when_off():
    """info.server_url() returns None when OFF."""

def test_debug_info_connection_status_connected():
    """info.connection_status() returns 'connected' when server reachable."""

def test_debug_info_connection_status_disabled():
    """info.connection_status() returns 'disabled' when OFF."""
```

### 3. Server Response Handling Tests

#### 3.1 Continue Action
```python
def test_action_continue_executes_original():
    """action='continue' executes the original method."""

def test_action_continue_returns_original_result():
    """action='continue' returns what the original method returns."""

def test_action_continue_propagates_exceptions():
    """action='continue' propagates exceptions from original method."""
```

#### 3.2 Poll Action
```python
def test_action_poll_does_not_execute_immediately():
    """action='poll' does not execute the method immediately."""

def test_action_poll_polls_at_specified_interval():
    """Client polls at the interval specified by server."""

def test_action_poll_stops_when_ready():
    """Polling stops when server returns status='ready'."""

def test_action_poll_executes_final_action():
    """Client executes the action from the ready response."""

def test_action_poll_timeout_raises_exception():
    """Polling timeout raises DebugTimeoutError."""

def test_action_poll_server_error_raises_exception():
    """Poll errors raise DebugServerError."""

def test_action_poll_can_lead_to_continue():
    """Poll can resolve to continue action."""

def test_action_poll_can_lead_to_skip():
    """Poll can resolve to skip action."""

def test_action_poll_can_lead_to_modify():
    """Poll can resolve to modify action."""

def test_action_poll_can_lead_to_raise():
    """Poll can resolve to raise action."""
```

#### 3.3 Skip Action
```python
def test_action_skip_does_not_execute_original():
    """action='skip' does not execute the original method."""

def test_action_skip_returns_fake_result():
    """action='skip' returns the fake_result from server."""

def test_action_skip_fake_result_none():
    """action='skip' can return None as fake result."""

def test_action_skip_fake_result_complex_type():
    """action='skip' can return complex dill-pickled objects as fake result."""

def test_action_skip_no_side_effects():
    """action='skip' causes no side effects from original method."""

def test_action_skip_result_by_cid():
    """action='skip' can return result by CID reference."""
```

#### 3.4 Raise Action
```python
def test_action_raise_does_not_execute_original():
    """action='raise' does not execute the original method."""

def test_action_raise_raises_specified_exception():
    """action='raise' raises the specified exception type."""

def test_action_raise_exception_message():
    """action='raise' includes the specified message."""

def test_action_raise_custom_exception_types():
    """action='raise' can raise custom exception types."""

def test_action_raise_builtin_exceptions():
    """action='raise' can raise built-in exception types."""
```

#### 3.5 Modify Action
```python
def test_action_modify_executes_with_new_args():
    """action='modify' executes with modified arguments."""

def test_action_modify_partial_args():
    """action='modify' can modify only some arguments."""

def test_action_modify_add_kwargs():
    """action='modify' can add new keyword arguments."""

def test_action_modify_preserves_unmodified_args():
    """action='modify' preserves arguments not in modified_args."""

def test_action_modify_args_by_cid():
    """action='modify' can specify args by CID reference."""

def test_action_modify_args_with_data():
    """action='modify' can include new dill-pickled arg data."""
```

### 4. Serialization Tests

```python
def test_compute_cid_deterministic():
    """Same object always produces same CID."""

def test_compute_cid_different_for_different_objects():
    """Different objects produce different CIDs."""

def test_dill_serialize_basic_types():
    """Can serialize basic Python types."""

def test_dill_serialize_class_instances():
    """Can serialize class instances."""

def test_dill_serialize_functions():
    """Can serialize functions."""

def test_dill_serialize_lambdas():
    """Can serialize lambdas."""

def test_dill_serialize_closures():
    """Can serialize closures with captured variables."""

def test_dill_serialize_circular_references():
    """Can serialize objects with circular references."""

def test_dill_failure_raises_serialization_error():
    """Objects that can't be dill pickled raise DebugSerializationError."""

def test_cid_deduplication_first_send():
    """First send includes both CID and data."""

def test_cid_deduplication_subsequent_send():
    """Subsequent send includes only CID."""

def test_cid_lru_cache_eviction():
    """Client evicts oldest CIDs when cache limit reached."""

def test_cid_cache_miss_resend():
    """Client resends data when server reports CID not found."""

def test_cid_server_verification():
    """Server verifies CID matches stored data."""

def test_cid_mismatch_raises_error():
    """CID mismatch on server raises DebugCIDMismatchError."""

def test_cid_not_found_raises_error():
    """CID not found on server raises DebugCIDNotFoundError."""

def test_cid_recovery_after_not_found():
    """Client recovers by resending full data after CID not found."""
```

### 5. Network Communication Tests

```python
def test_call_sends_method_name():
    """Call start request includes method name."""

def test_call_sends_args_as_cid_and_data():
    """Call start request includes args as CID+data."""

def test_call_sends_kwargs_as_cid_and_data():
    """Call start request includes kwargs as CID+data."""

def test_call_sends_full_stack_trace():
    """Call start request includes full stack trace."""

def test_call_sends_timestamp():
    """Call start request includes timestamp."""

def test_call_sends_target_cid():
    """Call start request includes CID of proxied object."""

def test_no_network_when_debug_off():
    """No network requests when debugging is OFF."""

def test_server_unreachable_raises_exception():
    """Server unreachable raises DebugServerError."""

def test_server_5xx_raises_exception():
    """Server 5xx errors raise DebugServerError."""

def test_request_timeout_raises_exception():
    """Request timeout raises DebugServerError."""

def test_malformed_response_raises_exception():
    """Malformed server response raises DebugProtocolError."""
```

### 6. DebugProxy Tests

```python
def test_proxy_intercepts_method_calls():
    """Proxy intercepts all method calls."""

def test_proxy_passes_through_attributes():
    """Proxy allows attribute access."""

def test_proxy_handles_properties():
    """Proxy handles @property correctly."""

def test_proxy_handles_class_methods():
    """Proxy handles @classmethod correctly."""

def test_proxy_handles_static_methods():
    """Proxy handles @staticmethod correctly."""

def test_proxy_intercepts_str():
    """Proxy intercepts __str__."""

def test_proxy_intercepts_repr():
    """Proxy intercepts __repr__."""

def test_proxy_intercepts_iter():
    """Proxy intercepts __iter__."""

def test_proxy_intercepts_len():
    """Proxy intercepts __len__."""

def test_proxy_intercepts_getitem():
    """Proxy intercepts __getitem__."""

def test_proxy_intercepts_setitem():
    """Proxy intercepts __setitem__."""

def test_proxy_intercepts_delitem():
    """Proxy intercepts __delitem__."""

def test_proxy_intercepts_contains():
    """Proxy intercepts __contains__."""

def test_proxy_intercepts_call():
    """Proxy intercepts __call__ for callable objects."""

def test_proxy_handles_context_manager():
    """Proxy handles __enter__/__exit__ for context managers."""

def test_proxy_equality_false_vs_non_proxy():
    """proxy == non_proxy is always False."""

def test_proxy_equality_compares_targets():
    """proxy1 == proxy2 compares underlying targets."""

def test_proxy_hash_matches_target():
    """hash(proxy) == hash(target)."""

def test_proxy_thread_safety():
    """Proxy is thread-safe for concurrent calls."""

def test_proxy_internal_error_propagates():
    """Proxy internal errors propagate as exceptions."""
```

### 7. Built-in Type Wrapping Tests

```python
def test_wrap_list():
    """Can wrap list objects."""

def test_wrap_list_append_intercepted():
    """list.append() is intercepted."""

def test_wrap_list_getitem_intercepted():
    """list[i] is intercepted."""

def test_wrap_list_setitem_intercepted():
    """list[i] = x is intercepted."""

def test_wrap_list_iter_intercepted():
    """for x in list is intercepted."""

def test_wrap_dict():
    """Can wrap dict objects."""

def test_wrap_dict_getitem_intercepted():
    """dict[key] is intercepted."""

def test_wrap_dict_setitem_intercepted():
    """dict[key] = value is intercepted."""

def test_wrap_dict_keys_intercepted():
    """dict.keys() is intercepted."""

def test_wrap_set():
    """Can wrap set objects."""

def test_wrap_set_add_intercepted():
    """set.add() is intercepted."""

def test_wrap_tuple():
    """Can wrap tuple objects (immutable)."""

def test_wrap_string():
    """Can wrap string objects."""

def test_wrap_int():
    """Can wrap int objects."""

def test_wrap_float():
    """Can wrap float objects."""

def test_wrap_int_add_returns_raw():
    """Wrapped int + int returns raw int, not proxy."""

def test_wrap_int_mul_returns_raw():
    """Wrapped int * int returns raw int, not proxy."""

def test_wrap_float_arithmetic_returns_raw():
    """Arithmetic on wrapped float returns raw float."""
```

### 8. Async Proxy Tests

```python
def test_async_proxy_wraps_async_methods():
    """Async proxy can wrap objects with async methods."""

def test_async_proxy_awaitable():
    """Async method calls are awaitable."""

def test_async_proxy_poll_uses_asyncio_sleep():
    """Async polling uses asyncio.sleep not time.sleep."""

def test_async_proxy_concurrent_calls():
    """Multiple async calls can be in flight concurrently."""

def test_async_proxy_timeout_raises():
    """Async poll timeout raises DebugTimeoutError."""

def test_async_proxy_mixed_sync_async():
    """Object with both sync and async methods works correctly."""

def test_async_proxy_generator():
    """Async generators are handled correctly."""

def test_async_proxy_context_manager():
    """Async context managers (__aenter__/__aexit__) work."""
```

### 9. Server Endpoint Tests

```python
def test_endpoint_call_start_exists():
    """POST /api/call/start endpoint exists."""

def test_endpoint_call_start_accepts_dill_data():
    """POST /api/call/start accepts dill-pickled data."""

def test_endpoint_call_start_returns_action():
    """POST /api/call/start returns an action."""

def test_endpoint_call_start_returns_call_id():
    """POST /api/call/start returns a timestamp-based call_id."""

def test_call_id_format_is_timestamp_based():
    """Call ID format is Unix timestamp with sequence number."""

def test_endpoint_call_start_stores_cid_data():
    """POST /api/call/start stores CID->data mapping."""

def test_endpoint_poll_exists():
    """GET /api/poll/{id} endpoint exists."""

def test_endpoint_poll_returns_status():
    """GET /api/poll/{id} returns status."""

def test_endpoint_poll_waiting():
    """GET /api/poll/{id} returns waiting when paused."""

def test_endpoint_poll_ready():
    """GET /api/poll/{id} returns ready when resumed."""

def test_endpoint_poll_not_found():
    """GET /api/poll/{unknown} returns 404."""

def test_endpoint_breakpoint_triggers_poll():
    """Hitting a breakpoint causes poll action."""

def test_endpoint_call_complete_exists():
    """POST /api/call/complete endpoint exists."""

def test_endpoint_call_complete_success():
    """POST /api/call/complete handles successful completion."""

def test_endpoint_call_complete_exception():
    """POST /api/call/complete handles exception completion."""

def test_endpoint_call_complete_stores_result():
    """POST /api/call/complete stores result CID."""

def test_endpoint_cid_not_found_response():
    """Server returns cid_not_found error for missing CIDs."""

def test_endpoint_cid_verification():
    """Server verifies CID data integrity."""
```

### 10. Configuration Tests

```python
def test_config_from_environment():
    """Server URL can be set via CIDELDILL_SERVER_URL."""

def test_config_from_code():
    """Server URL can be set via configure_debug()."""

def test_config_code_overrides_environment():
    """Code configuration overrides environment."""

def test_config_default_url():
    """Default URL is http://localhost:5000."""

def test_config_custom_port():
    """Custom port can be specified."""

def test_config_localhost_only():
    """Non-localhost URLs are rejected (security)."""
```

### 11. Integration Tests

```python
def test_full_workflow_debug_on():
    """Complete workflow with debugging ON."""

def test_full_workflow_debug_off():
    """Complete workflow with debugging OFF."""

def test_breakpoint_pause_and_resume():
    """Can pause at breakpoint and resume."""

def test_breakpoint_modify_args():
    """Can modify arguments at breakpoint."""

def test_breakpoint_skip_call():
    """Can skip call at breakpoint."""

def test_breakpoint_force_exception():
    """Can force exception at breakpoint."""

def test_multiple_objects_wrapped():
    """Multiple objects can be wrapped simultaneously."""

def test_nested_method_calls():
    """Nested method calls are all intercepted."""

def test_recursive_method_calls():
    """Recursive calls are handled correctly."""

def test_concurrent_calls_multiple_threads():
    """Concurrent calls from multiple threads work."""

def test_web_ui_integration():
    """Web UI can control breakpoints."""

def test_cid_deduplication_across_calls():
    """CIDs are deduplicated across multiple calls."""

def test_call_completion_on_success():
    """Server receives call completion for successful calls."""

def test_call_completion_on_exception():
    """Server receives call completion for failed calls."""

def test_call_completion_includes_timestamp():
    """Call completion includes accurate timestamp."""

def test_call_completion_result_cid():
    """Call completion includes result CID."""
```

### 12. Error Handling Tests

```python
def test_server_not_running_on_enable():
    """with_debug('ON') raises when server not running."""

def test_server_crashes_mid_call():
    """Server crash during call raises DebugServerError."""

def test_malformed_server_response():
    """Malformed response raises DebugProtocolError."""

def test_unknown_action_type():
    """Unknown action raises DebugProtocolError."""

def test_missing_required_fields():
    """Missing fields in response raises DebugProtocolError."""

def test_poll_timeout_raises():
    """Poll timeout raises DebugTimeoutError."""

def test_dill_failure_raises():
    """Dill pickle failure raises DebugSerializationError."""

def test_wrap_during_active_call():
    """Wrapping objects during an active call works."""

def test_circular_reference_serialization():
    """Objects with circular references serialize correctly."""

def test_cid_not_found_error():
    """DebugCIDNotFoundError raised when server missing CID."""

def test_cid_mismatch_error():
    """DebugCIDMismatchError raised when CID data doesn't match."""

def test_cid_recovery_resend():
    """Client resends full data after CID not found error."""
```

---

## Open Questions

**All questions have been resolved.** The design is complete and ready for implementation.

---

## Next Steps

1. Begin implementation starting with core `with_debug()` function
2. Implement serialization module (dill + CID computation)
3. Implement DebugProxy and AsyncDebugProxy classes
4. Update server with new endpoints (`/api/call/start`, `/api/call/complete`, `/api/poll/{id}`)
5. Write tests following the comprehensive test list above
6. Remove old API (Interceptor, Inspector, etc.)
7. Update documentation
