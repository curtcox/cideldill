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
│                  AI Agent (MCP Client)            │
│          (Claude Code, Cursor, etc.)              │
└────────────────────┬─────────────────────────────┘
                     │ MCP (stdio or SSE transport)
┌────────────────────▼─────────────────────────────┐
│              MCP Server Layer                     │
│  ┌──────────┐  ┌───────────┐  ┌───────────────┐  │
│  │  Tools   │  │ Resources │  │    Prompts    │  │
│  └──────────┘  └───────────┘  └───────────────┘  │
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

---

## Transport

### Phase 1: stdio

The simplest MCP transport. The server is launched as a subprocess by the MCP
client. Standard in/out carry JSON-RPC messages.

**Startup command:**
```bash
python -m cideldill_server --mcp
```

When `--mcp` is passed, the server:
1. Starts the Flask HTTP server on a background thread (for debug clients).
2. Runs the MCP stdio transport on the main thread.

### Phase 2 (future): SSE

Add `--mcp-sse` flag to expose MCP over HTTP Server-Sent Events, allowing
remote MCP clients. This is deferred — stdio covers the primary use case of
local AI-assisted debugging.

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

Get the recorded call history.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `function_name` | string | no | Filter to a specific function |
| `limit` | integer | no | Maximum number of records to return |

**Returns:**
```json
{
  "calls": [
    {
      "call_id": "1",
      "method_name": "process",
      "status": "success",
      "pretty_args": [...],
      "pretty_result": "...",
      "started_at": 1700000000.0,
      "completed_at": 1700000001.0
    }
  ]
}
```

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

**Maps to:** `CIDStore.get()` + deserialization.

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

### Phase 1: Core MCP server with tools

1. Add `mcp` Python SDK as a dependency to `cideldill-server`.
2. Create `mcp_server.py` module in `server/src/cideldill_server/`.
3. Implement tool registration and handler dispatch.
4. Wire up `BreakpointManager` and `CIDStore` to tool handlers.
5. Add `--mcp` CLI flag to `__main__.py`.
6. Run Flask on a background thread when in MCP mode.

### Phase 2: Resources and prompts

7. Implement resource providers.
8. Implement prompt templates.

### Phase 3: Integration and documentation

9. Add MCP server configuration examples (Claude Code `mcp_servers` config).
10. Add usage documentation.

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
| 48 | `test_get_call_records_all` | Returns all call records |
| 49 | `test_get_call_records_filtered` | Filters by `function_name` |
| 50 | `test_get_call_records_with_limit` | Respects `limit` parameter |
| 51 | `test_get_call_records_with_exception` | Exception info included in records |

#### `breakpoint_repl_eval` tests

| # | Test | Description |
|---|------|-------------|
| 52 | `test_repl_eval_simple_expression` | Evaluates `"2 + 2"` and returns `"4"` |
| 53 | `test_repl_eval_creates_session` | Auto-creates REPL session when `session_id` is omitted |
| 54 | `test_repl_eval_reuses_session` | Reuses existing session when `session_id` is provided |
| 55 | `test_repl_eval_error_expression` | Returns `is_error: true` for invalid Python |
| 56 | `test_repl_eval_no_paused_execution` | Error when `pause_id` doesn't refer to a paused execution |
| 57 | `test_repl_eval_captures_stdout` | Captures `print()` output in `stdout` field |

#### `breakpoint_inspect_object` tests

| # | Test | Description |
|---|------|-------------|
| 58 | `test_inspect_object_exists` | Returns deserialized representation |
| 59 | `test_inspect_object_not_found` | Error when CID doesn't exist in store |
| 60 | `test_inspect_object_unpicklable` | Returns placeholder info for unpicklable objects |

#### MCP Resources tests

| # | Test | Description |
|---|------|-------------|
| 61 | `test_resource_status` | `breakpoint://status` returns counts |
| 62 | `test_resource_breakpoints` | `breakpoint://breakpoints` matches tool output |
| 63 | `test_resource_paused` | `breakpoint://paused` matches tool output |
| 64 | `test_resource_call_history` | `breakpoint://call-history` returns recent records |
| 65 | `test_resource_functions` | `breakpoint://functions` returns registered functions |
| 66 | `test_resource_status_updates_dynamically` | Status reflects changes after breakpoint operations |

#### MCP Prompts tests

| # | Test | Description |
|---|------|-------------|
| 67 | `test_prompt_debug_session_start` | Renders with current session state |
| 68 | `test_prompt_inspect_paused_call` | Renders with specific paused execution data |
| 69 | `test_prompt_inspect_paused_call_not_found` | Error for invalid pause_id |

#### Error handling tests

| # | Test | Description |
|---|------|-------------|
| 70 | `test_unknown_tool_name` | Calling a non-existent tool returns an error |
| 71 | `test_missing_required_parameter` | Missing a required parameter returns a clear error |
| 72 | `test_extra_unknown_parameter` | Extra parameters are ignored (no error) |
| 73 | `test_parameter_wrong_type` | Wrong type for a parameter returns a clear error |

#### Concurrent access tests

| # | Test | Description |
|---|------|-------------|
| 74 | `test_concurrent_add_remove_breakpoints` | Thread-safe add/remove from MCP and HTTP simultaneously |
| 75 | `test_mcp_sees_http_changes` | Breakpoint added via HTTP is visible via MCP tool |
| 76 | `test_http_sees_mcp_changes` | Breakpoint added via MCP tool is visible via HTTP API |

### Module: `tests/unit/test_mcp_server_cli.py`

#### CLI integration tests

| # | Test | Description |
|---|------|-------------|
| 77 | `test_mcp_flag_recognized` | `--mcp` flag is parsed without error |
| 78 | `test_mcp_starts_flask_on_background_thread` | Flask server starts on a background thread |
| 79 | `test_mcp_without_flag_no_mcp` | Without `--mcp`, no MCP server is started |
| 80 | `test_mcp_port_flag_works` | `--mcp --port 9999` starts Flask on port 9999 |

### Module: `tests/integration/test_mcp_server_integration.py`

#### End-to-end MCP tests (via stdio transport)

| # | Test | Description |
|---|------|-------------|
| 81 | `test_mcp_stdio_initialize` | MCP client can initialize the server |
| 82 | `test_mcp_add_and_list_breakpoints` | Add a breakpoint via MCP, list it back |
| 83 | `test_mcp_pause_and_continue_flow` | Full pause/continue workflow via MCP |
| 84 | `test_mcp_repl_eval_at_breakpoint` | REPL eval at a paused execution via MCP |
| 85 | `test_mcp_resource_read` | Read a resource via MCP protocol |
| 86 | `test_mcp_prompt_get` | Retrieve a prompt template via MCP protocol |
| 87 | `test_mcp_and_http_interop` | Add breakpoint via MCP, verify via HTTP; vice versa |

---

## Open Questions

1. **MCP SDK version and API stability.** The Python `mcp` package is relatively
   new. Which version should we pin to? The SDK API has changed across versions
   (e.g. `FastMCP` vs lower-level server). Should we target the latest stable
   release at the time of implementation, or a specific known-good version?

2. **REPL eval security model.** The existing REPL eval executes arbitrary Python
   in the debugged process. When exposed via MCP, should there be any additional
   confirmation or safeguards, or do we rely on the same trust model as the web
   UI (i.e. this is a dev tool on a trusted machine)?

3. **Tool name prefix.** The plan uses `breakpoint_` as a prefix. Is there a
   preferred naming convention, or should we use a different prefix (e.g.
   `cideldill_`, `debug_`)?

4. **SSE transport priority.** Should SSE transport be included in the initial
   implementation, or is stdio sufficient for the first iteration? SSE would
   enable remote MCP clients but adds complexity.

5. **Object inspection depth.** `breakpoint_inspect_object` needs to return a
   serializable representation of arbitrary Python objects. What should the
   default depth/attribute limit be for MCP responses? The existing serializer
   uses `MAX_DEPTH=3` and `MAX_ATTRIBUTES=100` — are these appropriate for MCP
   output, or should MCP responses be more compact?

6. **Call record limits.** The `breakpoint_get_call_records` tool can return a
   potentially large list. Should there be a default limit (e.g. 100 records) if
   the caller doesn't specify one, to avoid overwhelming an AI agent's context
   window?

7. **Notification support.** MCP supports server-to-client notifications. Should
   the server emit notifications when breakpoints are hit (a paused execution
   appears), or should the AI agent poll via `breakpoint_list_paused`? Notifications
   would enable reactive debugging but add protocol complexity.

8. **Flask server lifecycle in MCP mode.** When the MCP stdio transport closes
   (e.g. the AI agent disconnects), should the Flask server also shut down, or
   should it keep running so the web UI remains accessible?

9. **Multiple MCP clients.** Should the server support multiple simultaneous MCP
   clients, or is single-client sufficient? The stdio transport is inherently
   single-client, but SSE could support multiple.

10. **Tool result format.** Should tool results be returned as plain JSON text
    content, or should some tools return structured content (e.g. embedded code
    blocks with syntax highlighting for REPL output)?

---

## Dependencies

| Package | Purpose | Version |
|---------|---------|---------|
| `mcp` | MCP Python SDK | latest stable |

Added to `server/pyproject.toml` under `[project.dependencies]`.

---

## File Changes Summary

| File | Change |
|------|--------|
| `server/src/cideldill_server/mcp_server.py` | New — MCP server implementation |
| `server/src/cideldill_server/__main__.py` | Modified — add `--mcp` CLI flag |
| `server/pyproject.toml` | Modified — add `mcp` dependency |
| `tests/unit/test_mcp_server.py` | New — unit tests |
| `tests/unit/test_mcp_server_cli.py` | New — CLI flag tests |
| `tests/integration/test_mcp_server_integration.py` | New — end-to-end tests |
| `docs/mcp_integration.md` | New — usage documentation |
