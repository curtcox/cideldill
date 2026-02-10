# MCP Server Plan for CID el Dill Breakpoint Server

## Overview

Expose the breakpoint server as an MCP (Model Context Protocol) server so that
AI agents (e.g. Claude via Claude Code, Cursor, or any MCP-compatible client)
can programmatically inspect, control, and debug applications through CID el
Dill's breakpoint infrastructure.

The MCP server runs **alongside** the existing Flask HTTP server within the same
process. It reuses the same `BreakpointManager` and `CIDStore` instances — no
data duplication, no extra process.

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│              AI Agent(s) (MCP Clients)            │
│          (Claude Code, Cursor, etc.)              │
└──────┬───────────────────────────┬───────────────┘
       │ stdio (single client)     │ SSE (multi-client)
┌──────▼───────────────────────────▼───────────────┐
│              MCP Server Layer                     │
│  ┌──────────┐  ┌───────────┐  ┌───────────────┐  │
│  │  Tools   │  │ Resources │  │    Prompts    │  │
│  └──────────┘  └───────────┘  └───────────────┘  │
│  ┌──────────────────────────────────────────────┐ │
│  │  Notifications (paused / resumed / complete) │ │
│  └──────────────────────────────────────────────┘ │
│         │              │              │           │
│         ▼              ▼              ▼           │
│  ┌─────────────────────────────────────────────┐  │
│  │  BreakpointManager + CIDStore (shared)      │  │
│  └─────────────────────────────────────────────┘  │
└────────────────────▲─────────────────────────────┘
                     │ HTTP (unchanged)
┌────────────────────┴─────────────────────────────┐
│           Flask Web UI / REST API                 │
│          (existing, unchanged)                    │
└──────────────────────────────────────────────────┘
                     ▲
                     │ HTTP (unchanged)
┌────────────────────┴─────────────────────────────┐
│           Debug Client (app under debug)          │
└──────────────────────────────────────────────────┘
```

### Key Constraints

- The MCP server **does not replace** the Flask server or the web UI.
- The MCP server shares the same `BreakpointManager` instance so state is
  consistent across MCP and HTTP consumers.
- The debug client (the app being debugged) continues to communicate via HTTP.
  The MCP layer is a **consumer** of the server state, not a replacement for the
  client protocol.
- When the MCP transport closes (stdio EOF or SSE client disconnect), the Flask
  server **keeps running** so the web UI remains accessible and the debug client
  is not disrupted.

---

## Transport

Both transports are included in the initial implementation.

### stdio

The simplest MCP transport. The server is launched as a subprocess by the MCP
client. Standard in/out carry JSON-RPC messages. Inherently single-client.

**Startup command:**
```bash
python -m cideldill_server --mcp
```

When `--mcp` is passed, the server:
1. Starts the Flask HTTP server on a background thread (for debug clients).
2. Runs the MCP stdio transport on the main thread.
3. When stdin closes (MCP client disconnects), the MCP transport stops but the
   Flask server continues running.

### SSE (Server-Sent Events)

HTTP-based transport that supports multiple simultaneous MCP clients. The SSE
transport runs inside the existing Flask process on a dedicated endpoint path.

**Startup command:**
```bash
python -m cideldill_server --mcp-sse
```

When `--mcp-sse` is passed, the server:
1. Starts the Flask HTTP server with the MCP SSE endpoint mounted at
   `/mcp/sse`.
2. Multiple MCP clients can connect to the same SSE endpoint concurrently.
3. Each SSE client gets its own message stream; notifications are broadcast
   to all connected clients.

**Combined mode:**
```bash
python -m cideldill_server --mcp --mcp-sse
```

Both transports can run simultaneously. The stdio transport runs on the main
thread; the SSE transport is served by Flask alongside the web UI.

---

## MCP Notifications

The server emits MCP notifications to connected clients when debugger state
changes. Clients may also poll via tools — notifications are an optimization,
not a requirement.

### `breakpoint/execution_paused`

Emitted when a call hits a breakpoint and is paused.

```json
{
  "method": "notifications/breakpoint/execution_paused",
  "params": {
    "pause_id": "uuid-1",
    "method_name": "process",
    "pause_reason": "breakpoint",
    "paused_at": 1700000000.0
  }
}
```

### `breakpoint/execution_resumed`

Emitted when a paused execution is resumed (via MCP, HTTP, or web UI).

```json
{
  "method": "notifications/breakpoint/execution_resumed",
  "params": {
    "pause_id": "uuid-1",
    "action": "continue"
  }
}
```

### `breakpoint/call_completed`

Emitted when a call completes (success or exception).

```json
{
  "method": "notifications/breakpoint/call_completed",
  "params": {
    "call_id": "1",
    "method_name": "process",
    "status": "success"
  }
}
```

### Implementation

Notifications require an observer mechanism on `BreakpointManager`. The MCP
server registers a callback; the manager invokes it on state transitions. The
callback dispatches to all connected MCP transports (stdio + SSE clients).

```python
# Sketch: observer interface added to BreakpointManager
class BreakpointManager:
    def add_observer(self, callback: Callable[[str, dict], None]) -> None: ...
    def remove_observer(self, callback: Callable[[str, dict], None]) -> None: ...
```

---

## MCP Tools

Each tool maps to one or more existing REST API operations. Tools accept and
return JSON. All tool names are prefixed with `breakpoint_` to avoid collisions
when the MCP server is composed with other servers.

### 1. `breakpoint_list_breakpoints`

List all active breakpoints with their behaviors.

**Parameters:** _(none)_

**Returns:**
```json
{
  "breakpoints": ["func_a", "func_b"],
  "behaviors": {"func_a": "stop", "func_b": "yield"},
  "after_behaviors": {"func_a": "yield", "func_b": "exception"},
  "replacements": {}
}
```

**Maps to:** `GET /api/breakpoints`

---

### 2. `breakpoint_add`

Add a breakpoint on a function.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `function_name` | string | yes | Function to break on |
| `behavior` | string | no | `"stop"`, `"go"`, or `"yield"` (default: `"yield"`) |

**Returns:**
```json
{"status": "ok", "function_name": "my_func"}
```

**Maps to:** `POST /api/breakpoints`

---

### 3. `breakpoint_remove`

Remove a breakpoint.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `function_name` | string | yes | Function to remove breakpoint from |

**Returns:**
```json
{"status": "ok", "function_name": "my_func"}
```

**Maps to:** `DELETE /api/breakpoints/<function_name>`

---

### 4. `breakpoint_set_behavior`

Set the before-execution behavior for a breakpoint.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `function_name` | string | yes | Function name |
| `behavior` | string | yes | `"stop"`, `"go"`, or `"yield"` |

**Returns:**
```json
{"status": "ok", "function_name": "my_func", "behavior": "stop"}
```

**Maps to:** `POST /api/breakpoints/<name>/behavior`

---

### 5. `breakpoint_set_after_behavior`

Set the after-execution behavior for a breakpoint.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `function_name` | string | yes | Function name |
| `behavior` | string | yes | `"stop"`, `"go"`, `"exception"`, `"stop_exception"`, or `"yield"` |

**Returns:**
```json
{"status": "ok", "function_name": "my_func", "behavior": "exception"}
```

**Maps to:** `POST /api/breakpoints/<name>/after_behavior`

---

### 6. `breakpoint_set_replacement`

Set a replacement function for a breakpoint.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `function_name` | string | yes | Original function name |
| `replacement_function` | string | yes | Replacement function name (or empty to clear) |

**Returns:**
```json
{"status": "ok", "function_name": "my_func", "replacement_function": "alt_func"}
```

**Maps to:** `POST /api/breakpoints/<name>/replacement`

---

### 7. `breakpoint_get_default_behavior`

Get the global default behavior.

**Parameters:** _(none)_

**Returns:**
```json
{"behavior": "stop"}
```

**Maps to:** `GET /api/behavior`

---

### 8. `breakpoint_set_default_behavior`

Set the global default behavior.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `behavior` | string | yes | `"stop"`, `"go"`, `"exception"`, or `"stop_exception"` |

**Returns:**
```json
{"status": "ok", "behavior": "stop"}
```

**Maps to:** `POST /api/behavior`

---

### 9. `breakpoint_list_paused`

List all currently paused executions.

**Parameters:** _(none)_

**Returns:**
```json
{
  "paused": [
    {
      "id": "uuid-1",
      "call_data": {
        "method_name": "process",
        "pretty_args": ["hello"],
        "pretty_kwargs": {},
        "signature": "(x: str) -> str",
        "call_site": {"file": "app.py", "line": 42}
      },
      "paused_at": 1700000000.0,
      "repl_sessions": []
    }
  ]
}
```

**Maps to:** `GET /api/paused`

---

### 10. `breakpoint_continue`

Resume a paused execution.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `pause_id` | string | yes | ID of the paused execution |
| `action` | string | no | `"continue"` (default), `"skip"`, or `"raise"` |
| `modified_args` | list | no | Modified arguments (for `"continue"`) |
| `modified_kwargs` | object | no | Modified keyword arguments |
| `fake_result` | any | no | Return value (for `"skip"`) |
| `exception_type` | string | no | Exception class (for `"raise"`) |
| `exception_message` | string | no | Exception message (for `"raise"`) |
| `replacement_function` | string | no | Replace with different function |

**Returns:**
```json
{"status": "ok", "pause_id": "uuid-1"}
```

**Maps to:** `POST /api/paused/<pause_id>/continue`

---

### 11. `breakpoint_list_functions`

List all registered functions (known callable targets).

**Parameters:** _(none)_

**Returns:**
```json
{
  "functions": ["func_a", "func_b"],
  "signatures": {"func_a": "(x: int) -> int"},
  "metadata": {}
}
```

**Maps to:** `GET /api/functions`

---

### 12. `breakpoint_get_call_records`

Get the recorded call history. Returns at most `limit` records (default: 100).

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `function_name` | string | no | Filter to a specific function |
| `limit` | integer | no | Maximum records to return (default: 100) |

**Returns:**
```json
{
  "calls": [
    {
      "call_id": "1",
      "method_name": "process",
      "status": "success",
      "pretty_args": ["..."],
      "pretty_result": "...",
      "started_at": 1700000000.0,
      "completed_at": 1700000001.0
    }
  ],
  "total_count": 350,
  "truncated": true
}
```

The response includes `total_count` (the total number of matching records before
the limit was applied) and `truncated` (true if records were cut off by the
limit), so the AI agent knows whether it has seen everything.

**Maps to:** `GET /api/breakpoints/<name>/history` (per-function) and
`BreakpointManager.get_call_records()` (all).

---

### 13. `breakpoint_repl_eval`

Evaluate a Python expression in the REPL context of a paused execution.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `pause_id` | string | yes | ID of the paused execution |
| `expression` | string | yes | Python expression to evaluate |
| `session_id` | string | no | Existing REPL session ID (auto-created if omitted) |

**Returns:**
```json
{
  "session_id": "12345-1700000000.000000",
  "output": "42",
  "stdout": "",
  "is_error": false
}
```

**Maps to:** `POST /api/repl/start` + `POST /api/repl/<session_id>/eval`

---

### 14. `breakpoint_inspect_object`

Inspect a serialized object by its CID.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `cid` | string | yes | Content identifier of the object |

**Returns:**
```json
{
  "cid": "abc123...",
  "type": "list",
  "repr": "[1, 2, 3]",
  "attributes": {}
}
```

**Maps to:** `CIDStore.get()` + deserialization. Uses existing serializer
defaults: `MAX_DEPTH=3`, `MAX_ATTRIBUTES=100`.

---

## Tool Result Format

**Recommendation: all tools return a single `TextContent` item containing JSON.**

Rationale:
- MCP tools are primarily consumed by AI agents, not humans. AI agents parse
  structured JSON far more reliably than formatted prose or mixed content.
- A uniform format means every tool response can be handled identically by the
  client — no special-casing for "this tool returns code blocks but that one
  returns JSON."
- For `breakpoint_repl_eval`, the `output` and `stdout` fields contain the raw
  text from the Python REPL. The AI agent can render these however it likes
  (e.g. as a fenced code block in its response to the user). Embedding
  formatting in the tool response would couple the server to a specific
  presentation style.
- If a future need arises for richer content (images, embedded resources), the
  single-TextContent convention can be extended to a multi-item content array
  without breaking existing clients.

---

## MCP Resources

Resources provide read-only data the AI can reference.

### 1. `breakpoint://status`

Current server status summary: number of breakpoints, paused executions, total
calls recorded.

### 2. `breakpoint://breakpoints`

Full breakpoint configuration (same data as `breakpoint_list_breakpoints` tool,
exposed as a resource for context injection).

### 3. `breakpoint://paused`

Currently paused executions (same data as `breakpoint_list_paused`).

### 4. `breakpoint://call-history`

Recent call records (last 50).

### 5. `breakpoint://functions`

Registered functions and their signatures.

---

## MCP Prompts

### 1. `debug-session-start`

A prompt template that gives the AI context about the current debugging session:
active breakpoints, registered functions, recent calls, and paused executions.

### 2. `inspect-paused-call`

A prompt template for inspecting a specific paused execution with full context:
function name, arguments, call site, and stack trace.

---

## Implementation Plan

### Phase 1: Core MCP server with tools (stdio)

1. Add `mcp` Python SDK (latest stable) as a dependency to `cideldill-server`.
2. Create `mcp_server.py` module in `server/src/cideldill_server/`.
3. Implement tool registration and handler dispatch.
4. Wire up `BreakpointManager` and `CIDStore` to tool handlers.
5. Add `--mcp` CLI flag to `__main__.py`.
6. Run Flask on a background thread when in MCP mode; keep Flask alive after
   MCP transport closes.

### Phase 2: SSE transport

7. Add `--mcp-sse` CLI flag.
8. Mount SSE MCP endpoint at `/mcp/sse` inside Flask.
9. Support multiple simultaneous SSE clients.

### Phase 3: Notifications

10. Add observer interface to `BreakpointManager`.
11. Implement notification dispatch for `execution_paused`, `execution_resumed`,
    `call_completed`.
12. Broadcast to all connected transports (stdio + SSE clients).

### Phase 4: Resources and prompts

13. Implement resource providers.
14. Implement prompt templates.

### Phase 5: Integration and documentation

15. Add MCP server configuration examples (Claude Code `mcp_servers` config).
16. Add usage documentation.

---

## Test Plan

All tests use the `BreakpointManager` and `CIDStore` directly (no HTTP). The MCP
tools are thin wrappers, so tests verify the MCP layer's parameter handling,
error reporting, and response formatting — not the underlying manager logic
(which is already tested by the existing 401+ unit tests).

### Module: `tests/unit/test_mcp_server.py`

#### Tool registration tests

| # | Test | Description |
|---|------|-------------|
| 1 | `test_all_tools_registered` | All 14 tools are registered with the MCP server |
| 2 | `test_tool_names_prefixed` | Every tool name starts with `breakpoint_` |
| 3 | `test_tool_schemas_valid` | Every tool's input schema is valid JSON Schema |
| 4 | `test_no_duplicate_tool_names` | No two tools share the same name |

#### `breakpoint_list_breakpoints` tests

| # | Test | Description |
|---|------|-------------|
| 5 | `test_list_breakpoints_empty` | Returns empty lists when no breakpoints are set |
| 6 | `test_list_breakpoints_with_entries` | Returns all breakpoints with behaviors |
| 7 | `test_list_breakpoints_includes_replacements` | Replacement mappings are included |

#### `breakpoint_add` tests

| # | Test | Description |
|---|------|-------------|
| 8 | `test_add_breakpoint_minimal` | Add with only `function_name` |
| 9 | `test_add_breakpoint_with_behavior` | Add with explicit `behavior` |
| 10 | `test_add_breakpoint_missing_function_name` | Error when `function_name` is missing |
| 11 | `test_add_breakpoint_invalid_behavior` | Error when `behavior` is not a valid value |
| 12 | `test_add_breakpoint_duplicate` | Adding the same breakpoint twice is idempotent |

#### `breakpoint_remove` tests

| # | Test | Description |
|---|------|-------------|
| 13 | `test_remove_breakpoint_exists` | Removes an existing breakpoint |
| 14 | `test_remove_breakpoint_not_found` | Removing a non-existent breakpoint succeeds silently (idempotent) |
| 15 | `test_remove_breakpoint_clears_behavior` | Behavior and after-behavior are also cleared |

#### `breakpoint_set_behavior` tests

| # | Test | Description |
|---|------|-------------|
| 16 | `test_set_behavior_stop` | Sets behavior to `"stop"` |
| 17 | `test_set_behavior_go` | Sets behavior to `"go"` |
| 18 | `test_set_behavior_yield` | Sets behavior to `"yield"` |
| 19 | `test_set_behavior_invalid` | Error for invalid behavior string |
| 20 | `test_set_behavior_no_breakpoint` | Error when breakpoint doesn't exist |

#### `breakpoint_set_after_behavior` tests

| # | Test | Description |
|---|------|-------------|
| 21 | `test_set_after_behavior_exception` | Sets after-behavior to `"exception"` |
| 22 | `test_set_after_behavior_stop_exception` | Sets after-behavior to `"stop_exception"` |
| 23 | `test_set_after_behavior_invalid` | Error for invalid after-behavior string |
| 24 | `test_set_after_behavior_no_breakpoint` | Error when breakpoint doesn't exist |

#### `breakpoint_set_replacement` tests

| # | Test | Description |
|---|------|-------------|
| 25 | `test_set_replacement_valid` | Sets replacement function |
| 26 | `test_set_replacement_clear` | Clears replacement when empty string passed |
| 27 | `test_set_replacement_signature_mismatch` | Error when signatures don't match |
| 28 | `test_set_replacement_no_breakpoint` | Error when breakpoint doesn't exist |

#### `breakpoint_get_default_behavior` / `breakpoint_set_default_behavior` tests

| # | Test | Description |
|---|------|-------------|
| 29 | `test_get_default_behavior_initial` | Returns `"stop"` initially |
| 30 | `test_set_default_behavior_go` | Sets default to `"go"` |
| 31 | `test_set_default_behavior_exception` | Sets default to `"exception"` |
| 32 | `test_set_default_behavior_stop_exception` | Sets default to `"stop_exception"` |
| 33 | `test_set_default_behavior_invalid` | Error for invalid behavior |

#### `breakpoint_list_paused` tests

| # | Test | Description |
|---|------|-------------|
| 34 | `test_list_paused_empty` | Returns empty list when nothing is paused |
| 35 | `test_list_paused_with_entries` | Returns paused execution data with call details |
| 36 | `test_list_paused_includes_repl_sessions` | REPL session IDs are included |

#### `breakpoint_continue` tests

| # | Test | Description |
|---|------|-------------|
| 37 | `test_continue_default_action` | Resumes with `"continue"` action |
| 38 | `test_continue_skip_with_fake_result` | Resumes with `"skip"` and a fake result |
| 39 | `test_continue_raise_exception` | Resumes with `"raise"` and exception details |
| 40 | `test_continue_with_modified_args` | Resumes with modified arguments |
| 41 | `test_continue_with_modified_kwargs` | Resumes with modified kwargs |
| 42 | `test_continue_with_replacement_function` | Resumes with a replacement function |
| 43 | `test_continue_invalid_pause_id` | Error when pause_id doesn't exist |
| 44 | `test_continue_already_resumed` | Error when execution was already resumed |

#### `breakpoint_list_functions` tests

| # | Test | Description |
|---|------|-------------|
| 45 | `test_list_functions_empty` | Returns empty when no functions registered |
| 46 | `test_list_functions_with_entries` | Returns functions with signatures and metadata |

#### `breakpoint_get_call_records` tests

| # | Test | Description |
|---|------|-------------|
| 47 | `test_get_call_records_empty` | Returns empty list when no calls recorded |
| 48 | `test_get_call_records_all` | Returns all call records (up to default limit) |
| 49 | `test_get_call_records_filtered` | Filters by `function_name` |
| 50 | `test_get_call_records_with_limit` | Respects explicit `limit` parameter |
| 51 | `test_get_call_records_with_exception` | Exception info included in records |
| 52 | `test_get_call_records_default_limit_100` | Returns at most 100 records when limit is not specified |
| 53 | `test_get_call_records_total_count` | `total_count` reflects the true count before truncation |
| 54 | `test_get_call_records_truncated_flag` | `truncated` is true when limit cuts off records, false otherwise |

#### `breakpoint_repl_eval` tests

| # | Test | Description |
|---|------|-------------|
| 55 | `test_repl_eval_simple_expression` | Evaluates `"2 + 2"` and returns `"4"` |
| 56 | `test_repl_eval_creates_session` | Auto-creates REPL session when `session_id` is omitted |
| 57 | `test_repl_eval_reuses_session` | Reuses existing session when `session_id` is provided |
| 58 | `test_repl_eval_error_expression` | Returns `is_error: true` for invalid Python |
| 59 | `test_repl_eval_no_paused_execution` | Error when `pause_id` doesn't refer to a paused execution |
| 60 | `test_repl_eval_captures_stdout` | Captures `print()` output in `stdout` field |

#### `breakpoint_inspect_object` tests

| # | Test | Description |
|---|------|-------------|
| 61 | `test_inspect_object_exists` | Returns deserialized representation |
| 62 | `test_inspect_object_not_found` | Error when CID doesn't exist in store |
| 63 | `test_inspect_object_unpicklable` | Returns placeholder info for unpicklable objects |

#### Tool result format tests

| # | Test | Description |
|---|------|-------------|
| 64 | `test_tool_result_is_single_text_content` | Every tool returns exactly one TextContent item |
| 65 | `test_tool_result_is_valid_json` | The text content of every tool result parses as valid JSON |

#### MCP Resources tests

| # | Test | Description |
|---|------|-------------|
| 66 | `test_resource_status` | `breakpoint://status` returns counts |
| 67 | `test_resource_breakpoints` | `breakpoint://breakpoints` matches tool output |
| 68 | `test_resource_paused` | `breakpoint://paused` matches tool output |
| 69 | `test_resource_call_history` | `breakpoint://call-history` returns recent records |
| 70 | `test_resource_functions` | `breakpoint://functions` returns registered functions |
| 71 | `test_resource_status_updates_dynamically` | Status reflects changes after breakpoint operations |

#### MCP Prompts tests

| # | Test | Description |
|---|------|-------------|
| 72 | `test_prompt_debug_session_start` | Renders with current session state |
| 73 | `test_prompt_inspect_paused_call` | Renders with specific paused execution data |
| 74 | `test_prompt_inspect_paused_call_not_found` | Error for invalid pause_id |

#### Error handling tests

| # | Test | Description |
|---|------|-------------|
| 75 | `test_unknown_tool_name` | Calling a non-existent tool returns an error |
| 76 | `test_missing_required_parameter` | Missing a required parameter returns a clear error |
| 77 | `test_extra_unknown_parameter` | Extra parameters are ignored (no error) |
| 78 | `test_parameter_wrong_type` | Wrong type for a parameter returns a clear error |

#### Concurrent access tests

| # | Test | Description |
|---|------|-------------|
| 79 | `test_concurrent_add_remove_breakpoints` | Thread-safe add/remove from MCP and HTTP simultaneously |
| 80 | `test_mcp_sees_http_changes` | Breakpoint added via HTTP is visible via MCP tool |
| 81 | `test_http_sees_mcp_changes` | Breakpoint added via MCP tool is visible via HTTP API |

### Module: `tests/unit/test_mcp_notifications.py`

#### Notification tests

| # | Test | Description |
|---|------|-------------|
| 82 | `test_notification_on_breakpoint_hit` | `execution_paused` emitted when a call pauses |
| 83 | `test_notification_on_execution_resumed` | `execution_resumed` emitted when a paused call is resumed |
| 84 | `test_notification_on_call_completed` | `call_completed` emitted when a call finishes |
| 85 | `test_notification_includes_pause_id` | `execution_paused` notification includes `pause_id` |
| 86 | `test_notification_includes_method_name` | All notifications include `method_name` |
| 87 | `test_notification_includes_pause_reason` | `execution_paused` notification includes `pause_reason` ("breakpoint" or "exception") |
| 88 | `test_notification_resumed_includes_action` | `execution_resumed` notification includes the resume action type |
| 89 | `test_notification_completed_includes_status` | `call_completed` notification includes `status` (success/error) |
| 90 | `test_no_notification_when_no_observers` | No crash when notifications fire with no observers registered |
| 91 | `test_multiple_observers_all_notified` | All registered observers receive each notification |
| 92 | `test_observer_exception_does_not_crash_server` | An exception in one observer does not prevent other observers from being notified |
| 93 | `test_remove_observer` | Removed observers stop receiving notifications |

### Module: `tests/unit/test_mcp_observer.py`

#### BreakpointManager observer interface tests

| # | Test | Description |
|---|------|-------------|
| 94 | `test_add_observer` | `add_observer` accepts a callable |
| 95 | `test_remove_observer` | `remove_observer` removes a previously added callable |
| 96 | `test_remove_observer_not_registered` | `remove_observer` for an unregistered callable is a no-op |
| 97 | `test_observer_called_on_add_paused_execution` | Observer fires when `add_paused_execution` is called |
| 98 | `test_observer_called_on_resume_execution` | Observer fires when `resume_execution` is called |
| 99 | `test_observer_called_on_record_call` | Observer fires when `record_call` is called |

### Module: `tests/unit/test_mcp_server_cli.py`

#### CLI integration tests

| # | Test | Description |
|---|------|-------------|
| 100 | `test_mcp_flag_recognized` | `--mcp` flag is parsed without error |
| 101 | `test_mcp_starts_flask_on_background_thread` | Flask server starts on a background thread |
| 102 | `test_mcp_without_flag_no_mcp` | Without `--mcp`, no MCP server is started |
| 103 | `test_mcp_port_flag_works` | `--mcp --port 9999` starts Flask on port 9999 |
| 104 | `test_mcp_sse_flag_recognized` | `--mcp-sse` flag is parsed without error |
| 105 | `test_mcp_sse_mounts_endpoint` | SSE endpoint is accessible at `/mcp/sse` |
| 106 | `test_mcp_and_mcp_sse_combined` | Both flags work together |
| 107 | `test_flask_survives_stdio_disconnect` | Flask continues serving after MCP stdio transport closes |

### Module: `tests/integration/test_mcp_server_integration.py`

#### End-to-end MCP tests (via stdio transport)

| # | Test | Description |
|---|------|-------------|
| 108 | `test_mcp_stdio_initialize` | MCP client can initialize the server |
| 109 | `test_mcp_add_and_list_breakpoints` | Add a breakpoint via MCP, list it back |
| 110 | `test_mcp_pause_and_continue_flow` | Full pause/continue workflow via MCP |
| 111 | `test_mcp_repl_eval_at_breakpoint` | REPL eval at a paused execution via MCP |
| 112 | `test_mcp_resource_read` | Read a resource via MCP protocol |
| 113 | `test_mcp_prompt_get` | Retrieve a prompt template via MCP protocol |
| 114 | `test_mcp_and_http_interop` | Add breakpoint via MCP, verify via HTTP; vice versa |

#### End-to-end MCP tests (via SSE transport)

| # | Test | Description |
|---|------|-------------|
| 115 | `test_mcp_sse_initialize` | MCP client can initialize the server over SSE |
| 116 | `test_mcp_sse_add_and_list_breakpoints` | Add and list breakpoints over SSE |
| 117 | `test_mcp_sse_multiple_clients` | Two SSE clients connect simultaneously and both see state changes |
| 118 | `test_mcp_sse_client_disconnect_no_crash` | SSE client disconnecting does not crash the server |
| 119 | `test_mcp_sse_notification_received` | SSE client receives `execution_paused` notification when breakpoint is hit |

#### Cross-transport tests

| # | Test | Description |
|---|------|-------------|
| 120 | `test_stdio_and_sse_share_state` | Breakpoint added via stdio is visible to SSE client and vice versa |
| 121 | `test_notification_broadcast_to_all_transports` | Notification is delivered to both stdio and SSE clients |

---

## Resolved Decisions

Answers to the original open questions.

### 1. MCP SDK version

**Decision:** Use the latest stable release of the `mcp` Python SDK at the time
of implementation. Pin to a specific version in `pyproject.toml` (e.g.
`mcp>=1.0.0,<2.0.0`) for reproducibility.

### 2. REPL eval security

**Decision:** No additional security beyond the existing trust model. This is a
development tool running on a single trusted machine. The REPL eval via MCP
has the same permissions as the web UI REPL eval.

### 3. Tool name prefix

**Decision:** Use `breakpoint_` as the prefix for all tool names.

### 4. SSE transport

**Decision:** Include both stdio and SSE transports in the initial
implementation. SSE enables remote MCP clients and multi-client scenarios.

### 5. Object inspection depth

**Decision:** Use the existing serializer defaults (`MAX_DEPTH=3`,
`MAX_ATTRIBUTES=100`). These are appropriate for MCP output.

### 6. Call record default limit

**Decision:** Default to 100 records when the caller does not specify a `limit`.
The response includes `total_count` and `truncated` fields so the AI agent
knows whether it has seen everything.

### 7. Notification support

**Decision:** Support both notifications and polling. The server emits MCP
notifications for key events (`execution_paused`, `execution_resumed`,
`call_completed`). Clients that don't support or want notifications can
ignore them and poll via tools instead.

### 8. Flask lifecycle in MCP mode

**Decision:** Flask keeps running when the MCP transport closes. This ensures
the web UI and debug client connections are not disrupted when an AI agent
disconnects.

### 9. Multiple MCP clients

**Decision:** Support multiple simultaneous clients. stdio is inherently
single-client. SSE supports multiple concurrent clients. All clients share
the same `BreakpointManager` state. Notifications are broadcast to all
connected clients.

### 10. Tool result format

**Decision:** All tools return a single `TextContent` item containing JSON.
See the "Tool Result Format" section above for full rationale.

---

## Open Questions

_(None — all questions have been resolved.)_

---

## Dependencies

| Package | Purpose | Version |
|---------|---------|---------|
| `mcp` | MCP Python SDK | latest stable (pinned range) |

Added to `server/pyproject.toml` under `[project.dependencies]`.

---

## File Changes Summary

| File | Change |
|------|--------|
| `server/src/cideldill_server/mcp_server.py` | New — MCP server implementation (tools, resources, prompts, notifications) |
| `server/src/cideldill_server/__main__.py` | Modified — add `--mcp` and `--mcp-sse` CLI flags |
| `server/src/cideldill_server/breakpoint_manager.py` | Modified — add observer interface for notifications |
| `server/pyproject.toml` | Modified — add `mcp` dependency |
| `tests/unit/test_mcp_server.py` | New — unit tests for tools, resources, prompts, errors |
| `tests/unit/test_mcp_notifications.py` | New — notification delivery tests |
| `tests/unit/test_mcp_observer.py` | New — BreakpointManager observer interface tests |
| `tests/unit/test_mcp_server_cli.py` | New — CLI flag tests |
| `tests/integration/test_mcp_server_integration.py` | New — end-to-end tests (stdio, SSE, cross-transport) |
| `docs/mcp_integration.md` | New — usage documentation |
