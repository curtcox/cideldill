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
┌─────────────────┐                  ┌─────────────────┐
│  MCP Client(s)  │                  │     Browser      │
│ (Claude Code,   │                  │    (Web UI)      │
│  Cursor, etc.)  │                  │                  │
└──────┬──────┬───┘                  └────────┬─────────┘
       │      │                               │
  stdio│      │SSE                         HTTP│
       │      │                               │
┌──────▼──────▼───────────────────────────────▼─────────┐
│                  Single Process                        │
│                                                        │
│  ┌─────────────────────┐   ┌────────────────────────┐  │
│  │  MCP stdio          │   │  Flask HTTP Server     │  │
│  │  transport          │   │  ┌──────────────────┐  │  │
│  │  (main thread)      │   │  │ REST API routes  │  │  │
│  └──────────┬──────────┘   │  │ Web UI routes    │  │  │
│             │              │  │ MCP SSE endpoint │  │  │
│             │              │  │  (/mcp/sse)      │  │  │
│             │              │  └────────┬─────────┘  │  │
│             │              └───────────┼────────────┘  │
│             │                          │               │
│  ┌──────────▼──────────────────────────▼────────────┐  │
│  │       MCP Tool / Resource / Prompt Handlers      │  │
│  │       Notification Dispatch                      │  │
│  └──────────────────────┬───────────────────────────┘  │
│                         │                              │
│  ┌──────────────────────▼───────────────────────────┐  │
│  │    BreakpointManager + CIDStore (shared state)   │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
└──────────────────────────────────────────┬─────────────┘
                                      HTTP │ (via Flask)
┌──────────────────────────────────────────┴─────────────┐
│              Debug Client (app under debug)              │
└─────────────────────────────────────────────────────────┘
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
- The MCP SSE transport is served **by Flask** as a route (`/mcp/sse`). The
  stdio transport runs on the main thread, separate from Flask. Both transports
  delegate to the same set of tool/resource/prompt handlers.
- In `--mcp` mode (stdio), **all logging is redirected to stderr**. Stdout is
  reserved exclusively for MCP JSON-RPC messages. Flask's startup banner and
  werkzeug request logging are sent to stderr.

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
1. Redirects all logging (Flask, werkzeug, application) to **stderr** so that
   stdout is reserved exclusively for MCP JSON-RPC messages.
2. Starts the Flask HTTP server on a background thread (for debug clients).
3. Runs the MCP stdio transport on the main thread.
4. When stdin closes (MCP client disconnects), the MCP transport stops.
5. The main thread then blocks (joins the Flask thread) so the process stays
   alive and Flask continues serving. The Flask thread is started as a
   non-daemon thread to ensure it is not killed when the main thread's MCP
   work finishes.

### SSE (Server-Sent Events)

HTTP-based transport that supports multiple simultaneous MCP clients. The SSE
transport is mounted as a Flask route at `/mcp/sse`, running inside the existing
Flask server process.

**Startup command:**
```bash
python -m cideldill_server --mcp-sse
```

When `--mcp-sse` is passed (without `--mcp`), the server:
1. Starts the Flask HTTP server normally (blocking on main thread, same as
   without any MCP flags).
2. Mounts the MCP SSE endpoint at `/mcp/sse` alongside the existing REST API
   and web UI routes.
3. Multiple MCP clients can connect concurrently. Each gets its own message
   stream; notifications are broadcast to all connected clients.
4. No stdio transport is started. Logging goes to stdout/stderr as usual.

**Combined mode:**
```bash
python -m cideldill_server --mcp --mcp-sse
```

Both transports run simultaneously. The stdio transport runs on the main
thread (with logging redirected to stderr); the SSE transport is served by
Flask alongside the web UI.

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
    "method_name": "process",
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

**Critical:** Observer callbacks must be invoked **after releasing** the
manager's `_lock`. `BreakpointManager` uses `threading.Lock()` (not `RLock`),
so if a callback tried to call any manager method that acquires the lock, it
would deadlock. The implementation pattern is:

```python
# Sketch: observer interface added to BreakpointManager
class BreakpointManager:
    def add_observer(self, callback: Callable[[str, dict], None]) -> None: ...
    def remove_observer(self, callback: Callable[[str, dict], None]) -> None: ...

    def add_paused_execution(self, call_data: dict) -> str:
        with self._lock:
            # ... mutate state ...
            observers = list(self._observers)  # snapshot under lock
        # Fire callbacks OUTSIDE the lock
        for cb in observers:
            try:
                cb("execution_paused", {...})
            except Exception:
                pass  # observer errors must not crash the server
        return pause_id
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

The tool first checks whether `pause_id` refers to a currently paused execution.
If not (either because the ID is invalid or because it was already resumed), it
returns an error. This is stricter than the existing HTTP endpoint, which
silently accepts unknown IDs — the MCP tool adds an explicit guard so AI agents
get clear feedback.

**Serialization format:** When the MCP tool passes `modified_args`,
`modified_kwargs`, or `fake_result` to the manager, it always uses **JSON
format** (not dill). The debug client's `preferred_format` from the original
call determines how the HTTP endpoint serializes these fields. Since MCP only
sends JSON, the MCP tool sets `preferred_format` to `"json"` when applying
`_apply_preferred_format()`.

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

**Parameter precedence:** If `replacement_function` is provided, it takes
priority over `action` — the tool sets the action to `"replace"` regardless
of the `action` parameter's value. This matches the HTTP endpoint behavior.

**Returns (success):**
```json
{"status": "ok", "pause_id": "uuid-1"}
```

**Returns (not found / already resumed):**
```json
{"error": "pause_not_found", "pause_id": "uuid-1"}
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
| `limit` | integer | no | Maximum records to return (default: 100, must be >= 1) |

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

**Data source:** Always uses `BreakpointManager.get_call_records()`, which
contains **all** recorded calls (not just calls for functions with breakpoints).
When `function_name` is provided, the tool filters this list by matching the
`method_name` field. This is distinct from `get_execution_history()`, which only
tracks calls to functions that have breakpoints set — the MCP tool intentionally
uses the broader data set.

---

### 13. `breakpoint_repl_eval`

Evaluate a Python expression in the REPL context of a paused execution.

**How it works:** The server does **not** evaluate Python itself. It acts as a
relay between the MCP client and the debug client (the paused app process):
1. The MCP tool queues an eval request for the given `pause_id`.
2. The debug client process polls `/api/poll-repl/<pause_id>`, picks up the
   request, evaluates the expression locally in the paused call's context, and
   posts the result back to `/api/call/repl-result`.
3. The MCP tool blocks until the result arrives or the timeout expires.

This means the debug client must be running and polling for eval to succeed.

**Dependency on `process_pid`:** Creating a REPL session requires
`process_pid` in the paused execution's `call_data` (this is how the manager
generates session IDs). This field is provided by the debug client when it
reports a call start. If `process_pid` is missing (e.g. in test fixtures that
use minimal call_data), the tool returns a clear error rather than an opaque
`KeyError`.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `pause_id` | string | yes | ID of the paused execution |
| `expression` | string | yes | Python expression to evaluate (must be non-empty after stripping whitespace) |
| `session_id` | string | no | Existing REPL session ID (auto-created if omitted) |
| `timeout_s` | number | no | Seconds to wait for the debug client to respond (default: 30) |

**Returns (success):**
```json
{
  "session_id": "12345-1700000000.000000",
  "output": "42",
  "stdout": "",
  "is_error": false
}
```

**Returns (timeout):**
```json
{
  "error": "eval_timeout",
  "message": "Debug client did not respond within 30s"
}
```

**Maps to:** `POST /api/repl/start` + `POST /api/repl/<session_id>/eval` +
the `/api/poll-repl` and `/api/call/repl-result` round-trip with the debug
client.

---

### 14. `breakpoint_inspect_object`

Inspect a serialized object by its CID.

**Note:** This tool requires **new server-side logic**. There is no existing
REST endpoint that returns a structured JSON representation of a deserialized
CID object (the web UI renders HTML directly). The implementation must:
1. Fetch raw bytes from `CIDStore.get(cid)`.
2. Deserialize via dill (or JSON, based on stored format).
3. Build a structured JSON representation with `type`, `repr`, and `attributes`.
4. Handle deserialization failures gracefully (return a placeholder).

Uses existing serializer defaults: `MAX_DEPTH=3`, `MAX_ATTRIBUTES=100`.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `cid` | string | yes | Content identifier of the object |

**Returns (success):**
```json
{
  "cid": "abc123...",
  "type": "list",
  "repr": "[1, 2, 3]",
  "attributes": {}
}
```

**Returns (deserialization failure):**
```json
{
  "cid": "abc123...",
  "type": "unknown",
  "repr": "<deserialization failed: ModuleNotFoundError>",
  "attributes": {},
  "error": "deserialization_failed"
}
```

**Returns (not found):**
```json
{
  "error": "cid_not_found",
  "cid": "abc123..."
}
```

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

Recent call records (last 50). This is intentionally smaller than the tool's
default limit of 100 — resources are for context injection (compact), while the
tool is for explicit queries (larger, configurable).

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

**Arguments:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `pause_id` | string | yes | ID of the paused execution to inspect |

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

Unit tests exercise the MCP tool handlers by calling them directly with a
`BreakpointManager` and `CIDStore` instance — no HTTP server needed for most
tests. The underlying manager logic is already covered by the existing 401+
unit tests, so MCP tests focus on the MCP layer's parameter validation, error
reporting, response formatting, and any new logic (e.g. `breakpoint_inspect_object`
builds structured JSON from raw deserialized objects, which is new). CLI tests
and integration tests require the full server stack.

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
| 21 | `test_set_after_behavior_stop` | Sets after-behavior to `"stop"` |
| 22 | `test_set_after_behavior_go` | Sets after-behavior to `"go"` |
| 23 | `test_set_after_behavior_exception` | Sets after-behavior to `"exception"` |
| 24 | `test_set_after_behavior_stop_exception` | Sets after-behavior to `"stop_exception"` |
| 25 | `test_set_after_behavior_yield` | Sets after-behavior to `"yield"` |
| 26 | `test_set_after_behavior_invalid` | Error for invalid after-behavior string |
| 27 | `test_set_after_behavior_no_breakpoint` | Error when breakpoint doesn't exist |

#### `breakpoint_set_replacement` tests

| # | Test | Description |
|---|------|-------------|
| 28 | `test_set_replacement_valid` | Sets replacement function |
| 29 | `test_set_replacement_clear` | Clears replacement when empty string passed |
| 30 | `test_set_replacement_signature_mismatch` | Error when signatures don't match |
| 31 | `test_set_replacement_no_signatures_registered` | Error when neither function has a registered signature |
| 32 | `test_set_replacement_no_breakpoint` | Error when breakpoint doesn't exist |

#### `breakpoint_get_default_behavior` / `breakpoint_set_default_behavior` tests

| # | Test | Description |
|---|------|-------------|
| 33 | `test_get_default_behavior_initial` | Returns `"stop"` initially |
| 34 | `test_set_default_behavior_go` | Sets default to `"go"` |
| 35 | `test_set_default_behavior_exception` | Sets default to `"exception"` |
| 36 | `test_set_default_behavior_stop_exception` | Sets default to `"stop_exception"` |
| 37 | `test_set_default_behavior_invalid` | Error for invalid behavior |

#### `breakpoint_list_paused` tests

| # | Test | Description |
|---|------|-------------|
| 38 | `test_list_paused_empty` | Returns empty list when nothing is paused |
| 39 | `test_list_paused_with_entries` | Returns paused execution data with call details |
| 40 | `test_list_paused_includes_repl_sessions` | REPL session IDs are included |

#### `breakpoint_continue` tests

| # | Test | Description |
|---|------|-------------|
| 41 | `test_continue_default_action` | Resumes with `"continue"` action |
| 42 | `test_continue_skip_with_fake_result` | Resumes with `"skip"` and a fake result |
| 43 | `test_continue_raise_exception` | Resumes with `"raise"` and exception details |
| 44 | `test_continue_with_modified_args` | Resumes with modified arguments |
| 45 | `test_continue_with_modified_kwargs` | Resumes with modified kwargs |
| 46 | `test_continue_with_replacement_function` | Resumes with a replacement function |
| 47 | `test_continue_replacement_overrides_action` | When both `action` and `replacement_function` are provided, `replacement_function` takes priority (action becomes `"replace"`) |
| 48 | `test_continue_invalid_pause_id` | Error when pause_id was never a paused execution |
| 49 | `test_continue_already_resumed` | Error when execution was already resumed (pause_id no longer in paused set) |
| 50 | `test_continue_uses_json_format` | `modified_args` and `fake_result` are serialized with JSON format, not dill |

#### `breakpoint_list_functions` tests

| # | Test | Description |
|---|------|-------------|
| 51 | `test_list_functions_empty` | Returns empty when no functions registered |
| 52 | `test_list_functions_with_entries` | Returns functions with signatures and metadata |

#### `breakpoint_get_call_records` tests

| # | Test | Description |
|---|------|-------------|
| 53 | `test_get_call_records_empty` | Returns empty list when no calls recorded |
| 54 | `test_get_call_records_all` | Returns all call records (up to default limit) |
| 55 | `test_get_call_records_filtered` | Filters by `function_name` |
| 56 | `test_get_call_records_with_limit` | Respects explicit `limit` parameter |
| 57 | `test_get_call_records_with_exception` | Exception info included in records |
| 58 | `test_get_call_records_default_limit_100` | Returns at most 100 records when limit is not specified |
| 59 | `test_get_call_records_total_count` | `total_count` reflects the true count before truncation |
| 60 | `test_get_call_records_truncated_flag` | `truncated` is true when limit cuts off records, false otherwise |
| 61 | `test_get_call_records_limit_zero_is_error` | `limit=0` returns a validation error (must be >= 1) |

#### `breakpoint_repl_eval` tests

These tests use a **mock debug client** that immediately posts results back to
`/api/call/repl-result` when it receives an eval request. This simulates the
3-party relay without a real app process.

| # | Test | Description |
|---|------|-------------|
| 62 | `test_repl_eval_simple_expression` | With mock client: evaluates `"2 + 2"`, returns `"4"` |
| 63 | `test_repl_eval_creates_session` | Auto-creates REPL session when `session_id` is omitted |
| 64 | `test_repl_eval_reuses_session` | Reuses existing session when `session_id` is provided |
| 65 | `test_repl_eval_error_expression` | With mock client: returns `is_error: true` for invalid Python |
| 66 | `test_repl_eval_empty_expression` | Error when `expression` is empty or whitespace-only |
| 67 | `test_repl_eval_no_paused_execution` | Error when `pause_id` doesn't refer to a paused execution |
| 68 | `test_repl_eval_captures_stdout` | With mock client: captures `print()` output in `stdout` field |
| 69 | `test_repl_eval_timeout` | Error when debug client does not respond within timeout |
| 70 | `test_repl_eval_closed_session` | Error when `session_id` refers to a closed session |

#### `breakpoint_inspect_object` tests

| # | Test | Description |
|---|------|-------------|
| 71 | `test_inspect_object_exists` | Returns structured JSON with type, repr, attributes |
| 72 | `test_inspect_object_not_found` | Error when CID doesn't exist in store |
| 73 | `test_inspect_object_unpicklable` | Returns placeholder info for unpicklable objects |
| 74 | `test_inspect_object_corrupted_data` | Returns error when CID exists but data cannot be deserialized (corrupt bytes) |

#### Tool result format tests

| # | Test | Description |
|---|------|-------------|
| 75 | `test_tool_result_is_single_text_content` | Every tool returns exactly one TextContent item |
| 76 | `test_tool_result_is_valid_json` | The text content of every tool result parses as valid JSON |

#### MCP Resources tests

| # | Test | Description |
|---|------|-------------|
| 77 | `test_resource_status` | `breakpoint://status` returns counts |
| 78 | `test_resource_breakpoints` | `breakpoint://breakpoints` matches tool output |
| 79 | `test_resource_paused` | `breakpoint://paused` matches tool output |
| 80 | `test_resource_call_history` | `breakpoint://call-history` returns recent records |
| 81 | `test_resource_functions` | `breakpoint://functions` returns registered functions |
| 82 | `test_resource_status_updates_dynamically` | Status reflects changes after breakpoint operations |

#### MCP Prompts tests

| # | Test | Description |
|---|------|-------------|
| 83 | `test_prompt_debug_session_start` | Renders with current session state |
| 84 | `test_prompt_inspect_paused_call` | Renders with specific paused execution data |
| 85 | `test_prompt_inspect_paused_call_not_found` | Error for invalid pause_id |

#### Error handling tests

| # | Test | Description |
|---|------|-------------|
| 86 | `test_unknown_tool_name` | Calling a non-existent tool returns an error |
| 87 | `test_missing_required_parameter` | Missing a required parameter returns a clear error |
| 88 | `test_extra_unknown_parameter` | Extra parameters are ignored (no error) |
| 89 | `test_parameter_wrong_type` | Wrong type for a parameter returns a clear error |

#### Concurrent access tests

| # | Test | Description |
|---|------|-------------|
| 90 | `test_concurrent_add_remove_breakpoints` | Thread-safe add/remove from MCP and HTTP simultaneously |
| 91 | `test_mcp_sees_http_changes` | Breakpoint added via HTTP is visible via MCP tool |
| 92 | `test_http_sees_mcp_changes` | Breakpoint added via MCP tool is visible via HTTP API |

### Module: `tests/unit/test_mcp_notifications.py`

#### Notification tests

| # | Test | Description |
|---|------|-------------|
| 93 | `test_notification_on_breakpoint_hit` | `execution_paused` emitted when a call pauses |
| 94 | `test_notification_on_execution_resumed` | `execution_resumed` emitted when a paused call is resumed |
| 95 | `test_notification_on_call_completed` | `call_completed` emitted when a call finishes |
| 96 | `test_notification_includes_pause_id` | `execution_paused` notification includes `pause_id` |
| 97 | `test_notification_includes_method_name` | All notifications include `method_name` |
| 98 | `test_notification_includes_pause_reason` | `execution_paused` notification includes `pause_reason` ("breakpoint" or "exception") |
| 99 | `test_notification_resumed_includes_action` | `execution_resumed` notification includes the resume action type |
| 100 | `test_notification_completed_includes_status` | `call_completed` notification includes `status` (success/error) |
| 101 | `test_no_notification_when_no_observers` | No crash when notifications fire with no observers registered |
| 102 | `test_multiple_observers_all_notified` | All registered observers receive each notification |
| 103 | `test_observer_exception_does_not_crash_server` | An exception in one observer does not prevent other observers from being notified |
| 104 | `test_remove_observer` | Removed observers stop receiving notifications |

### Module: `tests/unit/test_mcp_observer.py`

#### BreakpointManager observer interface tests

| # | Test | Description |
|---|------|-------------|
| 105 | `test_add_observer` | `add_observer` accepts a callable |
| 106 | `test_remove_observer` | `remove_observer` removes a previously added callable |
| 107 | `test_remove_observer_not_registered` | `remove_observer` for an unregistered callable is a no-op |
| 108 | `test_observer_called_on_add_paused_execution` | Observer fires when `add_paused_execution` is called |
| 109 | `test_observer_called_on_resume_execution` | Observer fires when `resume_execution` is called |
| 110 | `test_observer_called_on_record_call` | Observer fires when `record_call` is called |
| 111 | `test_observer_can_read_manager_without_deadlock` | Observer callback calls `get_paused_executions()` without deadlocking (verifies callbacks fire outside the lock) |

### Module: `tests/unit/test_mcp_server_cli.py`

#### CLI integration tests

| # | Test | Description |
|---|------|-------------|
| 112 | `test_mcp_flag_recognized` | `--mcp` flag is parsed without error |
| 113 | `test_mcp_starts_flask_on_background_thread` | Flask server starts on a background thread |
| 114 | `test_mcp_without_flag_no_mcp` | Without `--mcp`, no MCP server is started |
| 115 | `test_mcp_port_flag_works` | `--mcp --port 9999` starts Flask on port 9999 |
| 116 | `test_mcp_sse_flag_recognized` | `--mcp-sse` flag is parsed without error |
| 117 | `test_mcp_sse_mounts_endpoint` | SSE endpoint is accessible at `/mcp/sse` |
| 118 | `test_mcp_and_mcp_sse_combined` | Both flags work together |
| 119 | `test_flask_survives_stdio_disconnect` | Flask continues serving after MCP stdio transport closes |
| 120 | `test_mcp_sse_only_no_stdio` | `--mcp-sse` without `--mcp` starts Flask with SSE routes but no stdio transport |
| 121 | `test_mcp_stdio_logging_redirected_to_stderr` | In `--mcp` mode, all logging goes to stderr, not stdout |

### Module: `tests/integration/test_mcp_server_integration.py`

#### End-to-end MCP tests (via stdio transport)

| # | Test | Description |
|---|------|-------------|
| 122 | `test_mcp_stdio_initialize` | MCP client can initialize the server |
| 123 | `test_mcp_add_and_list_breakpoints` | Add a breakpoint via MCP, list it back |
| 124 | `test_mcp_pause_and_continue_flow` | Full pause/continue workflow via MCP |
| 125 | `test_mcp_repl_eval_at_breakpoint` | REPL eval at a paused execution via MCP |
| 126 | `test_mcp_resource_read` | Read a resource via MCP protocol |
| 127 | `test_mcp_prompt_get` | Retrieve a prompt template via MCP protocol |
| 128 | `test_mcp_and_http_interop` | Add breakpoint via MCP, verify via HTTP; vice versa |

#### End-to-end MCP tests (via SSE transport)

| # | Test | Description |
|---|------|-------------|
| 129 | `test_mcp_sse_initialize` | MCP client can initialize the server over SSE |
| 130 | `test_mcp_sse_add_and_list_breakpoints` | Add and list breakpoints over SSE |
| 131 | `test_mcp_sse_multiple_clients` | Two SSE clients connect simultaneously and both see state changes |
| 132 | `test_mcp_sse_client_disconnect_no_crash` | SSE client disconnecting does not crash the server |
| 133 | `test_mcp_sse_notification_received` | SSE client receives `execution_paused` notification when breakpoint is hit |

#### Cross-transport tests

| # | Test | Description |
|---|------|-------------|
| 134 | `test_stdio_and_sse_share_state` | Breakpoint added via stdio is visible to SSE client and vice versa |
| 135 | `test_notification_broadcast_to_all_transports` | Notification is delivered to both stdio and SSE clients |

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
