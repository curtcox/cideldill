# API for Apps Being Inspected

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

#### `with_debug('ON')`

- Enables debugging globally for the current process
- Returns a `DebugInfo` object that can be interrogated
- All subsequent `with_debug(obj)` calls return debug-wrapped objects
- Network requests are made to the debug server for each intercepted call
- Breakpoints can trigger and pause execution

```python
info = with_debug('ON')
info.is_enabled()      # Returns True
info.server_url()      # Returns the debug server URL
info.connection_status()  # Returns 'connected', 'disconnected', 'error'
```

#### `with_debug('OFF')`

- Disables debugging globally for the current process
- Returns a `DebugInfo` object that can be interrogated
- All subsequent `with_debug(obj)` calls return the original object unchanged
- **No breakpoints trigger**
- **No network requests are made**
- **No calls are logged**
- Minimal performance overhead (simple passthrough)

```python
info = with_debug('OFF')
info.is_enabled()      # Returns False
info.server_url()      # Returns None
info.connection_status()  # Returns 'disabled'
```

#### `with_debug(obj)`

- When debug is ON: Returns a proxy object that intercepts all method calls
- When debug is OFF: Returns the original object unchanged (identity function)
- The proxy object is transparent - client code uses it exactly like the original

```python
# Example usage
calculator = Calculator()
calculator = with_debug(calculator)  # Wrap for debugging

# Use exactly like the original
result = calculator.add(1, 2)  # Intercepted if debug is ON
```

### Server Response Protocol

When debugging is enabled, every intercepted call follows this protocol:

1. Client sends call information to server (function name, args, call site, etc.)
2. Server responds with an action dictating client behavior
3. Client executes based on the action

#### Server Response Format

```python
{
    "action": "continue" | "poll" | "skip" | "raise" | "modify",

    # For action="continue": proceed with original call
    # No additional fields required

    # For action="poll": wait and poll until allowed to continue
    "poll_interval_ms": 100,     # How often to poll
    "poll_url": "/api/poll/{id}", # URL to poll for status

    # For action="skip": skip the call, return fake result
    "fake_result": <any>,        # The result to return instead

    # For action="raise": raise an exception instead of calling
    "exception_type": "ValueError",
    "exception_message": "Forced error for testing",

    # For action="modify": continue with modified arguments
    "modified_args": {"x": 100, "y": 200}
}
```

#### Polling Protocol (for breakpoints)

When server returns `action="poll"`, the client:

1. Does NOT execute the original call yet
2. Polls the server at the specified interval
3. Each poll response is either:
   - `{"status": "waiting"}` - continue polling
   - `{"status": "ready", "action": {...}}` - proceed with the enclosed action
4. Client continues based on the final action received

```python
# Polling sequence example
POST /api/call/start
  <- {"action": "poll", "poll_interval_ms": 50, "poll_url": "/api/poll/abc123"}

GET /api/poll/abc123
  <- {"status": "waiting"}

GET /api/poll/abc123
  <- {"status": "waiting"}

GET /api/poll/abc123
  <- {"status": "ready", "action": {"action": "continue"}}

# Now client proceeds with the call
```

### Debug Object Proxy Behavior

The debug proxy wraps objects and intercepts method calls:

```python
class DebugProxy:
    """Transparent proxy that intercepts method calls for debugging."""

    def __init__(self, target, debug_client):
        self._target = target
        self._client = debug_client

    def __getattr__(self, name):
        attr = getattr(self._target, name)
        if callable(attr):
            return self._wrap_method(attr, name)
        return attr

    def _wrap_method(self, method, name):
        def wrapper(*args, **kwargs):
            # Notify server and get action
            action = self._client.record_call_start(
                object_type=type(self._target).__name__,
                method_name=name,
                args=args,
                kwargs=kwargs,
                call_site=get_call_site()
            )

            # Execute based on action
            return self._execute_action(action, method, args, kwargs)

        return wrapper
```

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

---

## Files That Need to Be Updated

### Core Implementation Files

| File | Current State | Required Changes |
|------|---------------|------------------|
| `src/cideldill/__init__.py` | Exports Interceptor, Logger, etc. | Add `with_debug` as primary export |
| `src/cideldill/interceptor.py` | Function-based wrapping with sync | Refactor to object proxy model, remove sync |
| `src/cideldill/breakpoint_manager.py` | Thread-based polling sync | Remove sync thread, pure request-response |
| `src/cideldill/breakpoint_server.py` | Current REST API | Add `/api/call/start`, `/api/poll/{id}` endpoints |
| `src/cideldill/inspector.py` | Stub for remote agent | Implement actual HTTP client |
| **NEW** `src/cideldill/debug_proxy.py` | Does not exist | Create DebugProxy class |
| **NEW** `src/cideldill/debug_info.py` | Does not exist | Create DebugInfo class |
| **NEW** `src/cideldill/debug_client.py` | Does not exist | Create HTTP client for server communication |
| **NEW** `src/cideldill/with_debug.py` | Does not exist | Implement `with_debug()` function |

### Test Files

| File | Current State | Required Changes |
|------|---------------|------------------|
| `tests/unit/test_interceptor.py` | Tests current wrap() API | Update for new with_debug API |
| `tests/unit/test_interceptor_realtime.py` | Tests observers/breakpoints | Refactor for request-response model |
| `tests/unit/test_breakpoint_server.py` | Tests current endpoints | Add tests for new endpoints |
| `tests/integration/test_breakpoint_workflow.py` | Tests sync-based workflow | Refactor for new workflow |
| **NEW** `tests/unit/test_with_debug.py` | Does not exist | Comprehensive with_debug tests |
| **NEW** `tests/unit/test_debug_proxy.py` | Does not exist | Proxy behavior tests |
| **NEW** `tests/unit/test_debug_client.py` | Does not exist | HTTP client tests |
| **NEW** `tests/integration/test_request_response_workflow.py` | Does not exist | End-to-end tests |

### Documentation Files

| File | Current State | Required Changes |
|------|---------------|------------------|
| `README.md` | Documents current API | Update examples to use with_debug |
| `docs/breakpoints_web_ui.md` | Current breakpoint guide | Update for new API |
| `P0_IMPLEMENTATION_SUMMARY.md` | Current feature summary | Update for new architecture |
| `done/use_cases.md` | Maps use cases to code | Update references |
| **NEW** `docs/with_debug_api.md` | Does not exist | Complete API reference |
| **NEW** `docs/migration_guide.md` | Does not exist | Guide for migrating from old API |

### Example Files

| File | Current State | Required Changes |
|------|---------------|------------------|
| `examples/p0_features_demo.py` | Uses Interceptor.wrap() | Convert to with_debug() |
| `examples/interactive_breakpoint_demo.py` | Uses sync thread | Remove sync, use new API |
| `examples/demo_call_tracking.py` | Basic tracking demo | Update for new API |
| **NEW** `examples/with_debug_basic.py` | Does not exist | Simple with_debug example |
| **NEW** `examples/with_debug_advanced.py` | Does not exist | Advanced features example |

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

def test_with_debug_on_then_off():
    """Can enable then disable debugging."""

def test_with_debug_off_then_on():
    """Can disable then enable debugging."""
```

#### 1.2 Object Wrapping Tests (Debug ON)
```python
def test_with_debug_obj_returns_proxy_when_on():
    """with_debug(obj) returns a DebugProxy when debugging is ON."""

def test_with_debug_obj_proxy_is_not_original():
    """The proxy is a different object than the original."""

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

def test_with_debug_obj_can_wrap_builtin_types():
    """Can wrap built-in types like list, dict (or gracefully decline)."""

def test_with_debug_obj_nested_wrapping():
    """Wrapping an already-wrapped object doesn't double-wrap."""
```

#### 1.3 Object Wrapping Tests (Debug OFF)
```python
def test_with_debug_obj_returns_original_when_off():
    """with_debug(obj) returns the original object when debugging is OFF."""

def test_with_debug_obj_identity_when_off():
    """with_debug(obj) is obj when debugging is OFF."""

def test_with_debug_obj_no_overhead_when_off():
    """No measurable overhead when debugging is OFF."""

def test_with_debug_obj_no_network_when_off():
    """No network requests are made when debugging is OFF."""

def test_with_debug_obj_no_logging_when_off():
    """No calls are logged when debugging is OFF."""
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

def test_debug_info_connection_status_disconnected():
    """info.connection_status() returns 'disconnected' when server unreachable."""

def test_debug_info_connection_status_disabled():
    """info.connection_status() returns 'disabled' when OFF."""

def test_debug_info_connection_status_error():
    """info.connection_status() returns 'error' on connection errors."""
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

def test_action_poll_timeout_handling():
    """Polling times out after reasonable period."""

def test_action_poll_server_error_handling():
    """Poll errors are handled gracefully."""

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
    """action='skip' can return complex objects as fake result."""

def test_action_skip_no_side_effects():
    """action='skip' causes no side effects from original method."""
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

def test_action_modify_add_args():
    """action='modify' can add new keyword arguments."""

def test_action_modify_remove_args():
    """action='modify' can effectively remove arguments."""

def test_action_modify_preserves_unmodified_args():
    """action='modify' preserves arguments not in modified_args."""
```

### 4. Network Communication Tests

```python
def test_call_sends_function_name():
    """Call start request includes function/method name."""

def test_call_sends_args():
    """Call start request includes positional arguments."""

def test_call_sends_kwargs():
    """Call start request includes keyword arguments."""

def test_call_sends_call_site():
    """Call start request includes call site information."""

def test_call_sends_timestamp():
    """Call start request includes timestamp."""

def test_call_sends_object_type():
    """Call start request includes the object type being called."""

def test_no_network_when_debug_off():
    """No network requests when debugging is OFF."""

def test_network_error_handling():
    """Network errors are handled gracefully."""

def test_server_error_handling():
    """Server 5xx errors are handled gracefully."""

def test_timeout_handling():
    """Request timeouts are handled gracefully."""

def test_retry_on_transient_failure():
    """Transient failures are retried appropriately."""
```

### 5. DebugProxy Tests

```python
def test_proxy_intercepts_method_calls():
    """Proxy intercepts all method calls."""

def test_proxy_passes_through_attributes():
    """Proxy allows attribute access without interception."""

def test_proxy_handles_properties():
    """Proxy handles @property correctly."""

def test_proxy_handles_class_methods():
    """Proxy handles @classmethod correctly."""

def test_proxy_handles_static_methods():
    """Proxy handles @staticmethod correctly."""

def test_proxy_handles_dunder_methods():
    """Proxy handles __str__, __repr__, etc."""

def test_proxy_handles_iteration():
    """Proxy handles __iter__ for iterable objects."""

def test_proxy_handles_context_manager():
    """Proxy handles __enter__/__exit__ for context managers."""

def test_proxy_handles_callable_objects():
    """Proxy handles objects with __call__."""

def test_proxy_isinstance_check():
    """isinstance() works correctly with proxied objects."""

def test_proxy_type_check():
    """type() returns appropriate information."""

def test_proxy_thread_safety():
    """Proxy is thread-safe for concurrent calls."""
```

### 6. Server Endpoint Tests

```python
def test_endpoint_call_start_exists():
    """POST /api/call/start endpoint exists."""

def test_endpoint_call_start_returns_action():
    """POST /api/call/start returns an action."""

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
```

### 7. Configuration Tests

```python
def test_config_from_environment():
    """Server URL can be set via environment variable."""

def test_config_from_code():
    """Server URL can be set via configure_debug()."""

def test_config_code_overrides_environment():
    """Code configuration overrides environment."""

def test_config_default_url():
    """Default URL is localhost:5000."""

def test_config_custom_port():
    """Custom port can be specified."""

def test_config_https_url():
    """HTTPS URLs are supported."""

def test_config_with_auth():
    """Authentication can be configured."""
```

### 8. Integration Tests

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

def test_concurrent_calls():
    """Concurrent calls from multiple threads work."""

def test_web_ui_integration():
    """Web UI can control breakpoints."""
```

### 9. Performance Tests

```python
def test_debug_off_no_overhead():
    """Debug OFF has negligible overhead (<1%)."""

def test_debug_on_reasonable_overhead():
    """Debug ON overhead is reasonable for debugging."""

def test_high_frequency_calls():
    """High-frequency calls don't overwhelm the system."""

def test_large_argument_handling():
    """Large arguments are handled efficiently."""

def test_memory_usage_reasonable():
    """Memory usage doesn't grow unboundedly."""
```

### 10. Edge Cases and Error Handling

```python
def test_server_not_running():
    """Graceful handling when server is not running."""

def test_server_crashes_mid_call():
    """Graceful handling when server crashes during call."""

def test_malformed_server_response():
    """Graceful handling of malformed server responses."""

def test_unknown_action_type():
    """Graceful handling of unknown action types."""

def test_missing_required_fields():
    """Graceful handling of missing fields in response."""

def test_very_long_poll_duration():
    """Handling of very long poll durations."""

def test_rapid_on_off_toggling():
    """Rapid toggling of debug ON/OFF."""

def test_wrap_during_call():
    """Wrapping objects during an active call."""

def test_unwrap_during_call():
    """Disabling debug during an active call."""

def test_circular_references():
    """Objects with circular references."""

def test_unpicklable_objects():
    """Objects that can't be serialized."""

def test_lambda_with_closure():
    """Lambdas with closure variables."""
```

---

## Open Questions

1. **Serialization of arguments**: How should non-JSON-serializable arguments be handled? Options:
   - a) Convert to string representation
   - b) Hash the object and send hash only
   - c) Skip non-serializable args with a placeholder
   - d) Raise an error

2. **Timeout behavior**: What should happen when a poll times out?
   - a) Continue execution (fail-open)
   - b) Raise a timeout exception (fail-closed)
   - c) Configurable behavior

3. **Server unavailable behavior**: What should happen when the debug server is unreachable?
   - a) Silently continue without debugging
   - b) Raise an exception
   - c) Queue calls and retry
   - d) Configurable behavior

4. **Thread isolation**: Should `with_debug('ON')` affect all threads or just the calling thread?
   - a) Global (all threads)
   - b) Thread-local
   - c) Configurable

5. **Async support**: How should async methods and coroutines be handled?
   - a) Full async support with async proxies
   - b) Sync-only initially, async in later version
   - c) Async calls fall through without interception

6. **Object identity**: When `with_debug(obj)` returns a proxy:
   - a) Should `proxy == original` return True?
   - b) Should `proxy is original` ever return True (when OFF)?
   - c) How to handle identity-based operations?

7. **Wrapping built-in types**: Can/should we wrap built-in types like `list`, `dict`?
   - a) Yes, wrap everything
   - b) No, only wrap user-defined classes
   - c) Wrap but only intercept certain methods

8. **Call site information**: What level of call site detail should be included?
   - a) Just filename and line number
   - b) Full stack trace
   - c) Configurable depth

9. **Return value serialization**: How should complex return values be sent to the server?
   - a) Full serialization (for logging)
   - b) Type and summary only
   - c) Don't send return values to server at all

10. **Exception in proxy**: If the proxy itself throws an exception (not the wrapped code), how should this be handled?
    - a) Propagate the exception
    - b) Log and continue with original call
    - c) Different behavior for different exception types

11. **Multiple server support**: Should clients be able to connect to multiple debug servers?
    - a) Single server only
    - b) Multiple servers with routing rules
    - c) Out of scope for initial version

12. **Security considerations**: What security measures are needed?
    - a) No authentication (localhost only)
    - b) Token-based authentication
    - c) TLS/mTLS required

13. **Graceful degradation**: If network latency is high, should the system:
    - a) Accept the latency (debugging isn't performance-critical)
    - b) Switch to fire-and-forget mode
    - c) Disable debugging automatically

14. **Backward compatibility**: How should the old `Interceptor.wrap()` API coexist with `with_debug()`?
    - a) Deprecated but still functional
    - b) Removed entirely
    - c) Both APIs work but are independent

---

## Next Steps

1. Resolve all open questions through discussion
2. Update this document with answers to open questions
3. Add any additional tests identified during discussion
4. Begin implementation starting with core `with_debug()` function
5. Iterate on implementation with test-driven development
