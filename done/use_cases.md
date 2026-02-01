# Implemented Use Cases

This document tracks P0 use cases that have been successfully implemented with corresponding tests.

---

## Real-time Inspection (P0) ✅

### Observing calls in real-time

✅ **As an agent developer**, I want to see tool calls as they happen, so that I can understand what my agent is doing without adding print statements everywhere.

- **Implementation**: `Interceptor.add_observer()` / `Interceptor.set_observer()` methods
- **Events**: `call_start`, `call_complete`, `call_error`
- **Tests**: `test_real_time_observer_called_on_success`, `test_real_time_observer_called_on_exception`

✅ **As an agent developer**, I want to see the full arguments passed to each tool, so that I can verify the agent is constructing calls correctly.

- **Implementation**: Arguments captured in `call_start` event and stored in call records
- **Access**: Via `get_call_records()` or observer callbacks
- **Tests**: `test_wrapped_function_records_call`, `test_real_time_observer_called_on_success`

✅ **As an agent developer**, I want to see the return value from each tool, so that I can verify tools are returning what the agent expects.

- **Implementation**: Results captured in `call_complete` event and stored in call records
- **Access**: Via `get_call_records()` or observer callbacks
- **Tests**: `test_wrapped_function_records_call`, `test_real_time_observer_called_on_success`

✅ **As an agent developer**, I want to see exceptions raised by tools, so that I can understand why my agent's workflow failed.

- **Implementation**: Exceptions captured in `call_error` event and stored in call records
- **Access**: Via `get_call_records()` or observer callbacks  
- **Tests**: `test_wrapped_function_records_exception`, `test_real_time_observer_called_on_exception`

✅ **As a tool author**, I want to see exactly what arguments my tool receives, so that I can debug input handling issues.

- **Implementation**: Same as above - arguments captured for all calls
- **Tests**: All argument recording tests

---

## Call History Review (P0) ✅

### Reviewing history

✅ **As an agent developer**, I want to see the sequence of all calls in a session, so that I can understand the full execution path.

- **Implementation**: `Interceptor.get_call_records()` returns all calls in chronological order
- **Storage**: Persistent storage via CAS store
- **Tests**: `test_get_all_call_records`, `test_multiple_wrapped_functions`

✅ **As an agent developer**, I want to filter call history by tool name, so that I can focus on specific tools when debugging.

- **Implementation**: `Interceptor.filter_by_function(function_name)` / `CASStore.filter_by_function()`
- **Tests**: `test_filter_by_function_returns_matching_calls`, `test_filter_by_function_on_interceptor`

✅ **As an agent developer**, I want to search call history by argument values, so that I can find "the call where query was 'foo'".

- **Implementation**: `Interceptor.search_by_args(search_args)` / `CASStore.search_by_args()`
- **Supports**: Partial matching, nested values, multiple criteria
- **Tests**: `test_search_by_args_finds_matching_calls`, `test_search_by_args_partial_match`, `test_search_by_args_multiple_criteria`

✅ **As a researcher**, I want to export call history for analysis, so that I can study agent behavior patterns offline.

- **Implementation**: `Interceptor.export_history()` and `Interceptor.export_history_to_file()`
- **Format**: JSON with full call details (args, results, exceptions, timestamps, callstacks)
- **Tests**: `test_export_history_to_json`, `test_export_history_to_file`

---

## Basic Breakpoints (P0) ✅

### Pausing execution

✅ **As an agent developer**, I want to set a breakpoint on a specific tool, so that I can pause execution before that tool runs.

- **Implementation**: `Interceptor.set_breakpoint(function_name)`
- **Handler**: `Interceptor.set_pause_handler(handler)` to control what happens when paused
- **Tests**: `test_breakpoint_pauses_execution`

✅ **As an agent developer**, I want to pause all tool calls, so that I can step through execution one call at a time.

- **Implementation**: `Interceptor.set_breakpoint_on_all()`
- **Tests**: `test_breakpoint_on_all_functions`

✅ **As an agent developer**, I want to pause on exceptions, so that I can inspect state immediately when something goes wrong.

- **Implementation**: `Interceptor.set_breakpoint_on_exception()`
- **Tests**: `test_breakpoint_on_exceptions`

### Inspecting at breakpoint

✅ **As an agent developer**, I want to see the full call context when paused (function, args, kwargs, caller), so that I can understand why this call is happening.

- **Implementation**: Pause handler receives complete `call_data` with function name, args, timestamp, callstack, and call_site
- **Tests**: All breakpoint tests verify call_data contents

### Modifying at breakpoint

✅ **As an agent developer**, I want to edit arguments before releasing a paused call, so that I can test "what if the agent had passed X instead".

- **Implementation**: Pause handler can return `{"action": "continue", "modified_args": {...}}`
- **Tests**: `test_modify_args_at_breakpoint`

✅ **As an agent developer**, I want to skip a tool call and provide a fake return value, so that I can test downstream behavior without running the real tool.

- **Implementation**: Pause handler can return `{"action": "skip", "fake_result": ...}`
- **Tests**: `test_skip_call_with_fake_return`

✅ **As an agent developer**, I want to force an exception on a paused call, so that I can test error handling paths.

- **Implementation**: Pause handler can return `{"action": "raise", "exception": Exception(...)}`
- **Tests**: `test_force_exception_at_breakpoint`

### Resuming execution

✅ **As an agent developer**, I want to release a single paused call, so that I can continue step-by-step.

- **Implementation**: Pause handler returns action, allowing single-step control
- **Tests**: All breakpoint tests demonstrate single-call control

✅ **As an agent developer**, I want to release all paused calls, so that I can resume normal execution.

- **Implementation**: `Interceptor.clear_breakpoints()` removes all breakpoints
- **Tests**: `test_clear_all_breakpoints`

✅ **As an agent developer**, I want to release and disable breakpoints, so that I can let the agent run to completion.

- **Implementation**: `Interceptor.remove_breakpoint(function_name)` and `Interceptor.clear_breakpoints()`
- **Tests**: `test_remove_breakpoint`, `test_clear_all_breakpoints`

---

## Implementation Summary

### Core Components

1. **CASStore**: Content-addressable storage for call data with filtering and search
2. **Interceptor**: Function wrapper with real-time observation and breakpoint support
3. **Observer Pattern**: Callbacks for real-time events (call_start, call_complete, call_error)
4. **Breakpoint System**: Flexible pause/modify/skip mechanism via pause handler

### Test Coverage

- **26 new tests** added for P0 features:
  - 8 tests for filtering and search
  - 12 tests for real-time observation and breakpoints
  - 6 tests for export functionality
- **All existing tests** continue to pass
- **98% code coverage** for Interceptor module

### Files Modified

- `src/cideldill/cas_store.py`: Added `filter_by_function()` and `search_by_args()`
- `src/cideldill/interceptor.py`: Added observer pattern, breakpoints, and export features
- `tests/unit/test_cas_store_filtering.py`: New filtering/search tests
- `tests/unit/test_interceptor_realtime.py`: New real-time and breakpoint tests
- `tests/unit/test_export_history.py`: New export tests
- `tests/unit/test_interceptor.py`: Added tests for new Interceptor methods

### API Reference

#### Real-time Observation
```python
def observer(event_type: str, call_data: dict):
    # event_type: "call_start", "call_complete", or "call_error"
    # call_data: {function_name, args, result/exception, timestamp, callstack, call_site}
    pass

interceptor.add_observer(observer)
interceptor.remove_observer(observer)
```

#### Call History
```python
# Get all calls
all_calls = interceptor.get_call_records()

# Filter by function
add_calls = interceptor.filter_by_function("add")

# Search by arguments
calls_with_x = interceptor.search_by_args({"x": 5})

# Export for analysis
json_str = interceptor.export_history(format="json")
interceptor.export_history_to_file("calls.json")
```

#### Breakpoints
```python
def pause_handler(call_data: dict) -> dict:
    # Return one of:
    # {"action": "continue"}  # Resume normally
    # {"action": "continue", "modified_args": {...}}  # Continue with modified args
    # {"action": "skip", "fake_result": ...}  # Skip and return fake result
    # {"action": "raise", "exception": Exception(...)}  # Force exception
    return {"action": "continue"}

interceptor.set_pause_handler(pause_handler)
interceptor.set_breakpoint("function_name")  # Break on specific function
interceptor.set_breakpoint_on_all()  # Break on all calls
interceptor.set_breakpoint_on_exception()  # Break when exceptions occur
interceptor.remove_breakpoint("function_name")
interceptor.clear_breakpoints()  # Remove all breakpoints
```

---

## Next Steps (P1 and beyond)

P1 features to consider in future iterations:
- Conditional breakpoints (e.g., "pause when query contains 'error'")
- Recording persistence across debugger restarts
- Replay functionality (re-execute recorded calls)
- HTTP interception (if needed for NAT apps)

See `todo/use_cases.md` for the complete roadmap.
