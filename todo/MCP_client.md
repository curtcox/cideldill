# MCP Client Plan for CID el Dill Breakpoint Server

## Overview

Enable the breakpoint server to act as an **MCP client** so that it can connect
to external MCP servers and use their tools, resources, and prompts. This
complements the existing MCP *server* capability — the breakpoint server can now
both **expose** its own debugging tools to AI agents and **consume** tools from
other MCP servers.

The primary motivation is to give debugging sessions access to external
capabilities: code search, documentation lookup, database queries, file system
operations, or any tool exposed by an MCP server — all accessible from the
breakpoint server's REST API and MCP server interface.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Breakpoint Server Process                   │
│                                                                     │
│  ┌───────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │  MCP Server       │  │  Flask HTTP       │  │  MCP Client     │  │
│  │  (existing)       │  │  Server           │  │  Manager (NEW)  │  │
│  │  - stdio          │  │  - REST API       │  │                 │  │
│  │  - SSE            │  │  - Web UI         │  │  Connects to    │  │
│  │                   │  │  - SSE events     │  │  external MCP   │  │
│  │  Exposes debug    │  │                   │  │  servers via     │  │
│  │  tools to AI      │  │  NEW routes:      │  │  stdio or SSE   │  │
│  │  agents           │  │  /api/mcp-tools   │  │                 │  │
│  └────────┬──────────┘  └────────┬──────────┘  └───────┬─────────┘  │
│           │                      │                      │           │
│  ┌────────▼──────────────────────▼──────────────────────▼────────┐  │
│  │              BreakpointManager + CIDStore (shared state)      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
└──────────────┬────────────────────────────────┬─────────────────────┘
               │                                │
          HTTP │ (debug clients)                │ stdio/SSE
               │                                │ (to external MCP servers)
┌──────────────▼──────────────┐   ┌─────────────▼──────────────────────┐
│  App Under Debug            │   │  External MCP Server(s)            │
│  (cideldill-client)         │   │  (filesystem, git, database, etc.) │
└─────────────────────────────┘   └────────────────────────────────────┘
```

### Key Constraints

- The MCP client manager runs **inside** the existing breakpoint server process.
  No extra processes beyond the MCP server subprocesses it spawns.
- External MCP server connections are **long-lived** — they start when the
  breakpoint server starts (or when configured at runtime) and persist until
  explicitly disconnected or the server shuts down.
- The MCP client manager is **thread-safe**. Flask request threads and the MCP
  server tool handlers can all invoke external tools concurrently.
- External tool calls are **async** under the hood (MCP SDK uses asyncio) but
  are exposed **synchronously** to Flask routes and the existing MCP server
  tool handlers via a bridging mechanism.
- The MCP client capability does **not** alter the existing MCP server, REST
  API, or web UI behavior. It is purely additive.
- When an external MCP server connection fails or is unavailable, the breakpoint
  server continues operating normally. External tool calls return clear errors.

---

## MCP Client Manager

The `MCPClientManager` is the central component. It manages connections to
external MCP servers and provides a unified interface for discovering and
calling their tools.

### Responsibilities

1. **Connection lifecycle** — connect to, disconnect from, and reconnect to
   external MCP servers.
2. **Tool discovery** — aggregate tools from all connected servers into a
   unified catalog with namespaced names to avoid collisions.
3. **Tool invocation** — route tool calls to the correct server and return
   results.
4. **Resource discovery and reading** — aggregate resources from connected
   servers.
5. **Health monitoring** — track connection status, detect failures, and
   support reconnection.
6. **Configuration** — accept server configurations at startup (from config
   file or CLI) and at runtime (via API).

### Tool Namespacing

Tools from external servers are namespaced to avoid collisions with the
breakpoint server's own tools and with tools from other connected servers.

**Format:** `<server_name>/<tool_name>`

Example: If a server named `"filesystem"` exposes a tool named `"read_file"`,
it appears as `"filesystem/read_file"` in the unified catalog.

The server name is the key used in the configuration. It must be a non-empty
string matching `[a-zA-Z0-9_-]+`.

### Async-to-Sync Bridge

The MCP Python SDK client is fully async. The breakpoint server's Flask routes
and MCP server tool handlers are synchronous. The MCPClientManager runs its own
asyncio event loop on a dedicated background thread and provides synchronous
methods that bridge into it.

```python
class MCPClientManager:
    def __init__(
        self,
        manager: BreakpointManager,
        cid_store: CIDStore,
    ) -> None:
        self._manager = manager        # for recording call records
        self._cid_store = cid_store    # for storing tool results
        self._loop: asyncio.AbstractEventLoop  # background loop
        self._thread: threading.Thread          # loop runner
        self._servers: dict[str, _ServerConnection] = {}

    def call_tool(self, namespaced_name: str, arguments: dict) -> CallToolResult:
        """Synchronous — blocks until the external tool completes."""
        server_name, tool_name = self._parse_namespaced_name(namespaced_name)
        server = self._servers[server_name]
        future = asyncio.run_coroutine_threadsafe(
            self._call_tool_async(server_name, tool_name, arguments),
            self._loop,
        )
        return future.result(timeout=server.config.timeout_s)
```

### Constructor Dependencies

The `MCPClientManager` receives `BreakpointManager` and `CIDStore` as
constructor arguments. It uses these to:
- Record each external tool call in `BreakpointManager.record_call()` with
  `"source": "mcp_client"` (Decision #1).
- Store tool call results in `CIDStore` for later inspection via
  `breakpoint_inspect_object` (Decision #3).

### `disconnect` vs `reconnect` Semantics

`disconnect(name)` sets the server's status to `"disconnected"`, closes the
transport (terminates the subprocess for stdio, closes the HTTP connection for
SSE), and removes the server's tools from the catalog. The server's **config
is retained** so that `reconnect(name)` can re-establish the connection using
the original configuration.

To fully remove a server (config and all), there is no separate API — just
disconnect it and it will be forgotten on process restart (since runtime
connections are ephemeral per Decision #7, and config-file connections are
re-read from the file on startup).

### `--mcp-client` Inline Parsing

The `--mcp-client` value is split on the **first** colon to produce
`name:value`. Server names match `[a-zA-Z0-9_-]+` (no colons), so the first
colon is always the separator. If `value` starts with `http://` or `https://`,
it is SSE; otherwise it is stdio (split on whitespace into command + args).

### CLI Flag Interactions

- `--mcp-clients` alone: loads the default config file
  (`~/.cideldill/mcp_clients.json`). If the file does not exist, it is a
  **silent no-op** (zero servers configured, manager still created).
- `--mcp-clients-config /path`: loads the specified config file. If the file
  does not exist, it is an **error** (FileNotFoundError).
- `--mcp-client "name:value"` alone (without `--mcp-clients`): **also creates
  the MCPClientManager** and connects the inline server(s). You do not need
  `--mcp-clients` when using `--mcp-client`.
- All three flags can be combined. Config-file servers and inline servers are
  merged. If a name appears in both, the inline definition wins.

### Auto-Reconnect Parameters

Auto-reconnection uses these constants (not configurable per-server):
- **Max attempts:** 5
- **Backoff schedule:** 1s, 2s, 4s, 8s, 16s (exponential, base 2)
- After max attempts, the server status becomes `"failed"` and no further
  automatic reconnection is attempted. Manual `reconnect(name)` resets the
  attempt counter.

### Connection Timeout vs Tool Call Timeout

The `timeout_s` config field controls **tool call timeout** (how long to wait
for a single tool call to complete). A separate **connection timeout** of 30
seconds (not configurable) applies to the initial connection establishment
(subprocess spawn + MCP initialization, or SSE handshake + MCP initialization).
If connection takes longer than 30s, the server status becomes `"error"`.

---

## Configuration

### Config file format

External MCP servers are configured via a JSON config file or via environment
variable. The format mirrors the Claude Code `mcp_servers` convention.

**File:** `~/.cideldill/mcp_clients.json` (or `$CIDELDILL_HOME/mcp_clients.json`)

```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
      "env": {},
      "transport": "stdio"
    },
    "remote-db": {
      "url": "http://db-server:8080/mcp/sse",
      "transport": "sse"
    }
  }
}
```

### CLI flags

```bash
# Start with MCP client connections from config file
python -m cideldill_server --mcp-clients

# Start with a specific config file
python -m cideldill_server --mcp-clients-config /path/to/mcp_clients.json

# Start with a single stdio server inline (command detected by absence of URL scheme)
python -m cideldill_server --mcp-client "filesystem:npx -y @modelcontextprotocol/server-filesystem /tmp"

# Start with a single SSE server inline (URL detected by http:// or https:// prefix)
python -m cideldill_server --mcp-client "remote-db:http://db-server:8080/mcp/sse"

# Multiple inline servers
python -m cideldill_server \
  --mcp-client "filesystem:npx -y @modelcontextprotocol/server-filesystem /tmp" \
  --mcp-client "remote-db:https://db.example.com/mcp/sse"
```

### Server configuration fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | string | yes (stdio) | Command to spawn the MCP server |
| `args` | list[string] | no | Command-line arguments |
| `env` | dict | no | Environment variables |
| `cwd` | string | no | Working directory for subprocess |
| `url` | string | yes (SSE) | SSE endpoint URL |
| `transport` | string | yes | `"stdio"` or `"sse"` |
| `timeout_s` | number | no | Tool call timeout in seconds (default: 30) |
| `auto_reconnect` | bool | no | Whether to auto-reconnect on failure (default: true) |

---

## REST API Extensions

### `GET /api/mcp-clients`

List all configured MCP client connections and their status.

**Returns:**
```json
{
  "clients": {
    "filesystem": {
      "status": "connected",
      "transport": "stdio",
      "tools": ["filesystem/read_file", "filesystem/write_file"],
      "connected_at": 1700000000.0
    },
    "remote-db": {
      "status": "disconnected",
      "transport": "sse",
      "tools": [],
      "error": "Connection refused"
    }
  }
}
```

### `GET /api/mcp-tools`

List all tools from all connected external MCP servers.

**Returns:**
```json
{
  "tools": [
    {
      "name": "filesystem/read_file",
      "server": "filesystem",
      "original_name": "read_file",
      "description": "Read a file from disk.",
      "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}
    }
  ]
}
```

### `POST /api/mcp-tools/call`

Call a tool on a connected external MCP server.

**Request body:**
```json
{
  "tool": "filesystem/read_file",
  "arguments": {"path": "/tmp/example.txt"}
}
```

**Returns:**
```json
{
  "result": {
    "content": [{"type": "text", "text": "file contents..."}]
  }
}
```

**Error returns:**
```json
{"error": "server_not_connected", "server": "filesystem"}
{"error": "tool_not_found", "tool": "filesystem/no_such_tool"}
{"error": "call_failed", "message": "timeout after 30s"}
```

### `GET /api/mcp-resources`

List all resources from all connected external MCP servers.

**Returns:**
```json
{
  "resources": [
    {
      "uri": "filesystem://localhost/tmp",
      "server": "filesystem",
      "name": "Tmp Directory",
      "description": "...",
      "mime_type": "application/json"
    }
  ]
}
```

### `POST /api/mcp-resources/read`

Read a resource from a connected external MCP server.

**Request body:**
```json
{
  "server": "filesystem",
  "uri": "filesystem://localhost/tmp"
}
```

**Returns:**
```json
{
  "content": "...",
  "mime_type": "application/json"
}
```

**Error returns:**
```json
{"error": "server_not_connected", "server": "filesystem"}
{"error": "resource_not_found", "uri": "filesystem://localhost/nosuch"}
```

### `POST /api/mcp-clients/connect`

Connect to a new external MCP server at runtime.

**Request body:**
```json
{
  "name": "git-server",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-git"],
  "transport": "stdio"
}
```

**Returns:**
```json
{"status": "ok", "name": "git-server", "tools": ["git-server/log", "git-server/diff"]}
```

**Error returns:**
```json
{"error": "duplicate_name", "name": "git-server"}
{"error": "connect_failed", "name": "git-server", "message": "..."}
```

### `POST /api/mcp-clients/<name>/disconnect`

Disconnect from a specific external MCP server. The server config is retained
for future `reconnect` calls.

**Returns:**
```json
{"status": "ok", "name": "filesystem"}
```

**Error returns:**
```json
{"error": "server_not_found", "name": "nosuch"}
```

### `POST /api/mcp-clients/<name>/reconnect`

Reconnect to a disconnected external MCP server using its retained config.

**Returns:**
```json
{"status": "ok", "name": "filesystem", "tools": ["filesystem/read_file"]}
```

**Error returns:**
```json
{"error": "server_not_found", "name": "nosuch"}
{"error": "connect_failed", "name": "filesystem", "message": "..."}
```

---

## MCP Server Tool Extensions

The breakpoint server's existing MCP server interface gains new tools that
proxy to external MCP servers. This allows AI agents connected via MCP to
call external tools through the breakpoint server.

### New MCP tools (exposed by the breakpoint server's MCP server)

#### `external_list_servers`

List connected external MCP servers and their status.

**Parameters:** _(none)_

**Returns:**
```json
{
  "servers": {
    "filesystem": {"status": "connected", "tool_count": 5},
    "remote-db": {"status": "disconnected", "error": "..."}
  }
}
```

#### `external_list_tools`

List all tools from all connected external MCP servers.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `server` | string | no | Filter to a specific server |

**Returns:**
```json
{
  "tools": [
    {"name": "filesystem/read_file", "server": "filesystem", "description": "..."}
  ]
}
```

#### `external_call_tool`

Call a tool on a connected external MCP server.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `tool` | string | yes | Namespaced tool name (`server/tool`) |
| `arguments` | object | no | Tool arguments |

**Returns:**
```json
{
  "content": [{"type": "text", "text": "result..."}]
}
```

#### `external_list_resources`

List resources from connected external MCP servers.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `server` | string | no | Filter to a specific server |

**Returns:**
```json
{
  "resources": [
    {
      "uri": "filesystem://localhost/tmp",
      "server": "filesystem",
      "name": "Tmp Directory",
      "description": "...",
      "mime_type": "application/json"
    }
  ]
}
```

#### `external_read_resource`

Read a resource from a connected external MCP server.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `server` | string | yes | Server name |
| `uri` | string | yes | Resource URI |

**Returns:**
```json
{
  "content": "...",
  "mime_type": "application/json"
}
```

**Error returns:**
```json
{"error": "server_not_found", "server": "nosuch"}
{"error": "resource_not_found", "uri": "..."}
```

---

## Implementation Plan

### Phase 1: MCPClientManager core

1. Create `mcp_client_manager.py` module in `server/src/cideldill_server/`.
2. Implement `MCPClientManager` with:
   - Background asyncio event loop on a dedicated thread.
   - `connect(name, config)` — establish a connection to an external MCP server.
   - `disconnect(name)` — close a connection.
   - `list_servers()` — return connection status for all servers.
   - `list_tools()` — aggregate tools from all connected servers.
   - `call_tool(namespaced_name, arguments)` — route and execute a tool call.
3. Support stdio transport (spawn subprocess, connect via `stdio_client`).
4. Support SSE transport (connect via `sse_client`).
5. Thread-safe access from Flask request threads.

### Phase 2: Configuration and CLI

6. Parse `mcp_clients.json` config file.
7. Add `--mcp-clients` and `--mcp-clients-config` CLI flags to `__main__.py`.
8. Add `--mcp-client` inline server flag.
9. Auto-connect to configured servers on startup.

### Phase 3: REST API

10. Add `/api/mcp-clients` endpoint.
11. Add `/api/mcp-tools` and `/api/mcp-tools/call` endpoints.
12. Add `/api/mcp-resources` and `/api/mcp-resources/read` endpoints.
13. Add `/api/mcp-clients/connect`, `disconnect`, `reconnect` endpoints.

### Phase 4: MCP Server proxy tools

14. Add `external_list_servers`, `external_list_tools`, `external_call_tool`
    tools to the existing MCP server.
15. Add `external_list_resources`, `external_read_resource` tools.

### Phase 5: Error handling and reconnection

16. Implement connection health monitoring (periodic ping).
17. Implement auto-reconnection with exponential backoff.
18. Implement graceful shutdown (close all client connections on server stop).

### Phase 6: Integration and documentation

19. Add integration tests with a mock MCP server.
20. Add usage documentation.
21. Update `docs/mcp_integration.md`.

---

## Test Plan

Tests are organized by module and follow TDD (red-green-refactor). Unit tests
use mock MCP servers (in-process) to avoid subprocess/network dependencies.
Integration tests spawn real MCP server subprocesses.

### Module: `tests/unit/test_mcp_client_manager.py`

#### Construction and lifecycle tests

| # | Test | Description |
|---|------|-------------|
| 1 | `test_manager_starts_background_loop` | MCPClientManager starts a background asyncio event loop on a dedicated thread |
| 2 | `test_manager_requires_breakpoint_manager` | Constructor requires a `BreakpointManager` instance |
| 3 | `test_manager_requires_cid_store` | Constructor requires a `CIDStore` instance |
| 4 | `test_manager_shutdown_stops_loop` | `shutdown()` stops the background loop and joins the thread |
| 5 | `test_manager_shutdown_idempotent` | Calling `shutdown()` twice does not raise |
| 6 | `test_manager_initially_has_no_servers` | `list_servers()` returns empty dict after construction |
| 7 | `test_manager_initially_has_no_tools` | `list_tools()` returns empty list after construction |

#### Server name validation tests

| # | Test | Description |
|---|------|-------------|
| 8 | `test_server_name_valid_alphanumeric` | Names like `"filesystem"`, `"my-server"`, `"db_1"` are accepted |
| 9 | `test_server_name_empty_rejected` | Empty string `""` raises ValueError |
| 10 | `test_server_name_with_slash_rejected` | Names containing `"/"` raise ValueError (slash is the namespace separator) |
| 11 | `test_server_name_with_spaces_rejected` | Names containing spaces raise ValueError |
| 12 | `test_server_name_duplicate_rejected` | Connecting with an already-connected name raises ValueError |

#### Stdio connection tests (with mock MCP server)

| # | Test | Description |
|---|------|-------------|
| 13 | `test_connect_stdio_success` | Connects to a mock stdio MCP server; status becomes `"connected"` |
| 14 | `test_connect_stdio_discovers_tools` | After connecting, `list_tools()` returns the mock server's tools with namespace prefix |
| 15 | `test_connect_stdio_invalid_command` | Connecting with a nonexistent command results in status `"error"` |
| 16 | `test_connect_stdio_server_crash_on_init` | Server that exits immediately results in status `"error"` |
| 17 | `test_disconnect_stdio_retains_config` | `disconnect(name)` terminates the subprocess, removes tools, sets status to `"disconnected"`, but retains server config for reconnect |
| 18 | `test_disconnect_unknown_server` | `disconnect("nonexistent")` raises KeyError |

#### SSE connection tests (with mock HTTP server)

| # | Test | Description |
|---|------|-------------|
| 19 | `test_connect_sse_success` | Connects to a mock SSE endpoint; status becomes `"connected"` |
| 20 | `test_connect_sse_discovers_tools` | After connecting, tools from SSE server appear in catalog |
| 21 | `test_connect_sse_invalid_url` | Connecting with an unreachable URL results in status `"error"` |
| 22 | `test_disconnect_sse` | `disconnect(name)` closes the SSE connection cleanly |

#### Tool namespacing tests

| # | Test | Description |
|---|------|-------------|
| 23 | `test_tool_names_are_namespaced` | Tool `"read_file"` from server `"fs"` appears as `"fs/read_file"` |
| 24 | `test_tools_from_multiple_servers_do_not_collide` | Two servers both exposing `"search"` appear as `"server_a/search"` and `"server_b/search"` |
| 25 | `test_tool_catalog_includes_server_name` | Each tool entry includes the `server` field |
| 26 | `test_tool_catalog_includes_original_name` | Each tool entry includes `original_name` (without namespace) |
| 27 | `test_tool_catalog_includes_description` | Tool description from the MCP server is preserved |
| 28 | `test_tool_catalog_includes_input_schema` | Tool input schema from the MCP server is preserved |

#### Tool calling tests

| # | Test | Description |
|---|------|-------------|
| 29 | `test_call_tool_success` | Calling a namespaced tool routes to the correct server and returns the result |
| 30 | `test_call_tool_with_arguments` | Arguments are passed through to the external tool |
| 31 | `test_call_tool_empty_arguments` | Calling with empty `{}` arguments works |
| 32 | `test_call_tool_server_not_connected` | Calling a tool on a disconnected server returns error |
| 33 | `test_call_tool_unknown_server` | Calling `"nosuch/tool"` returns `server_not_found` error |
| 34 | `test_call_tool_unknown_tool` | Calling `"fs/nosuch"` where `"fs"` is connected but `"nosuch"` is not a known tool returns `tool_not_found` error |
| 35 | `test_call_tool_invalid_format` | Calling with a name that has no `"/"` separator returns error |
| 36 | `test_call_tool_timeout` | Tool call that exceeds per-server `timeout_s` returns `call_timeout` error |
| 37 | `test_call_tool_server_error` | External server returning an error is propagated as a structured error |
| 38 | `test_call_tool_returns_text_content` | TextContent results from external tools are returned faithfully |
| 39 | `test_call_tool_returns_multiple_content` | Multi-item content arrays are returned faithfully |
| 40 | `test_call_tool_result_stored_in_cid_store` | Tool call result content is stored in the CIDStore and can be retrieved via CID |
| 41 | `test_call_tool_recorded_in_call_records` | Tool call is recorded in BreakpointManager call records with `"source": "mcp_client"` |
| 42 | `test_call_tool_record_includes_server_name` | Call record includes the server name and namespaced tool name |
| 43 | `test_call_tool_record_includes_arguments` | Call record includes the arguments passed to the tool |
| 44 | `test_call_tool_record_includes_result_cid` | Call record includes the CID of the stored result |
| 45 | `test_call_tool_error_recorded_in_call_records` | Failed tool calls are also recorded with error details |

#### Resource discovery tests

| # | Test | Description |
|---|------|-------------|
| 46 | `test_list_resources_empty` | No resources when no servers connected |
| 47 | `test_list_resources_from_connected_server` | Resources from connected server include server name |
| 48 | `test_list_resources_multiple_servers` | Resources from multiple servers are aggregated |
| 49 | `test_list_resources_filter_by_server` | Filtering by server name returns only that server's resources |
| 50 | `test_read_resource_success` | Reading a resource from a connected server returns content |
| 51 | `test_read_resource_server_not_connected` | Error when server is not connected |
| 52 | `test_read_resource_not_found` | Error when resource URI is not found on the server |

#### Concurrent access tests

| # | Test | Description |
|---|------|-------------|
| 53 | `test_concurrent_tool_calls_same_server` | Multiple threads calling tools on the same server concurrently |
| 54 | `test_concurrent_tool_calls_different_servers` | Multiple threads calling tools on different servers concurrently |
| 55 | `test_connect_while_calling_tool` | Connecting a new server while a tool call is in progress on another |
| 56 | `test_disconnect_while_calling_tool` | Disconnecting a server while a tool call is in progress on it returns error for the in-flight call |

#### Reconnection tests

| # | Test | Description |
|---|------|-------------|
| 57 | `test_reconnect_after_disconnect` | `reconnect(name)` re-establishes a previously disconnected connection using retained config |
| 58 | `test_reconnect_discovers_fresh_tools` | After reconnection, tool list is refreshed (may have changed) |
| 59 | `test_auto_reconnect_on_connection_loss` | When auto_reconnect is true, manager attempts reconnection after detecting connection loss |
| 60 | `test_auto_reconnect_exponential_backoff` | Reconnection attempts use exponential backoff (1s, 2s, 4s, 8s, 16s) with max 5 attempts |
| 61 | `test_auto_reconnect_max_attempts` | Auto-reconnection gives up after 5 attempts and sets status to `"failed"` |
| 62 | `test_no_auto_reconnect_when_disabled` | When auto_reconnect is false, no reconnection is attempted |
| 63 | `test_reconnect_unknown_server` | `reconnect("nonexistent")` raises KeyError |
| 64 | `test_manual_reconnect_resets_attempt_counter` | After `reconnect()`, auto-reconnect attempt counter resets to 0 |

#### Health monitoring tests

| # | Test | Description |
|---|------|-------------|
| 65 | `test_ping_connected_server` | Pinging a connected server succeeds |
| 66 | `test_ping_disconnected_server` | Pinging a disconnected server returns error |
| 67 | `test_connection_status_reflects_reality` | After server process dies, status eventually becomes `"disconnected"` |

#### Sampling request handling tests

| # | Test | Description |
|---|------|-------------|
| 68 | `test_sampling_request_raises_not_implemented` | Server-initiated `sampling/createMessage` raises `NotImplementedError` |
| 69 | `test_sampling_rejection_does_not_crash_connection` | After rejecting a sampling request, the connection remains usable for tool calls |

### Module: `tests/unit/test_mcp_client_config.py`

#### Config file parsing tests

| # | Test | Description |
|---|------|-------------|
| 70 | `test_parse_valid_config` | Parses a valid `mcp_clients.json` with multiple servers |
| 71 | `test_parse_empty_config` | Empty `{"servers": {}}` parses to zero server configs |
| 72 | `test_parse_missing_file` | Missing config file raises FileNotFoundError |
| 73 | `test_parse_invalid_json` | Malformed JSON raises ValueError |
| 74 | `test_parse_missing_transport` | Server entry without `transport` raises ValueError |
| 75 | `test_parse_stdio_missing_command` | Stdio entry without `command` raises ValueError |
| 76 | `test_parse_sse_missing_url` | SSE entry without `url` raises ValueError |
| 77 | `test_parse_unknown_transport` | Transport other than `"stdio"` or `"sse"` raises ValueError |
| 78 | `test_parse_optional_fields_defaulted` | Missing optional fields (`env`, `args`, `timeout_s`, `auto_reconnect`) get defaults |
| 79 | `test_parse_timeout_must_be_positive` | `timeout_s` of 0 or negative raises ValueError |
| 80 | `test_parse_env_must_be_dict` | `env` field that is not a dict raises ValueError |
| 81 | `test_default_config_path` | Default path is `~/.cideldill/mcp_clients.json` |
| 82 | `test_config_path_from_env` | `$CIDELDILL_MCP_CLIENTS_CONFIG` overrides default path |
| 83 | `test_config_path_respects_cideldill_home` | `$CIDELDILL_HOME/mcp_clients.json` is used when `$CIDELDILL_HOME` is set |

### Module: `tests/unit/test_mcp_client_cli.py`

#### CLI flag tests

| # | Test | Description |
|---|------|-------------|
| 84 | `test_mcp_clients_flag_recognized` | `--mcp-clients` flag is parsed without error |
| 85 | `test_mcp_clients_config_flag` | `--mcp-clients-config /path` is parsed and stored |
| 86 | `test_mcp_client_inline_flag_stdio` | `--mcp-client "name:command args"` is parsed as stdio transport (split on first colon) |
| 87 | `test_mcp_client_inline_flag_sse_http` | `--mcp-client "name:http://host/path"` is parsed as SSE transport |
| 88 | `test_mcp_client_inline_flag_sse_https` | `--mcp-client "name:https://host/path"` is parsed as SSE transport |
| 89 | `test_mcp_client_inline_multiple` | Multiple `--mcp-client` flags are accumulated |
| 90 | `test_mcp_client_inline_missing_colon` | `--mcp-client "no-colon"` raises error (missing name:value separator) |
| 91 | `test_mcp_client_inline_empty_name` | `--mcp-client ":command"` raises error (empty server name) |
| 92 | `test_mcp_client_inline_empty_value` | `--mcp-client "name:"` raises error (empty command/URL) |
| 93 | `test_no_flags_no_client_manager` | Without any `--mcp-clients` or `--mcp-client` flags, no MCPClientManager is created |
| 94 | `test_mcp_clients_flag_creates_manager` | `--mcp-clients` alone creates MCPClientManager (loads default config, no-op if file missing) |
| 95 | `test_mcp_client_inline_alone_creates_manager` | `--mcp-client "name:cmd"` alone (without `--mcp-clients`) creates MCPClientManager and connects the server |
| 96 | `test_mcp_clients_shutdown_on_server_stop` | MCPClientManager.shutdown() is called when the server stops |
| 97 | `test_mcp_clients_default_config_missing_is_silent` | `--mcp-clients` with no config file at default path creates manager with zero servers (no error) |
| 98 | `test_mcp_clients_config_file_missing_is_error` | `--mcp-clients-config /nonexistent` raises FileNotFoundError |

### Module: `tests/unit/test_mcp_client_rest_api.py`

#### REST API tests

| # | Test | Description |
|---|------|-------------|
| 99 | `test_get_mcp_clients_empty` | `/api/mcp-clients` returns empty when no clients configured |
| 100 | `test_get_mcp_clients_with_connections` | `/api/mcp-clients` returns status for each configured server |
| 101 | `test_get_mcp_tools_empty` | `/api/mcp-tools` returns empty when no servers connected |
| 102 | `test_get_mcp_tools_with_connected_server` | `/api/mcp-tools` returns tools from connected servers |
| 103 | `test_post_mcp_tools_call_success` | `/api/mcp-tools/call` routes to correct server and returns result |
| 104 | `test_post_mcp_tools_call_missing_tool` | Error when `tool` field is missing from request body |
| 105 | `test_post_mcp_tools_call_server_not_connected` | Error when target server is not connected |
| 106 | `test_post_mcp_tools_call_tool_not_found` | Error when tool name is not in catalog |
| 107 | `test_get_mcp_resources` | `/api/mcp-resources` returns aggregated resources |
| 108 | `test_post_mcp_resources_read` | `/api/mcp-resources/read` reads from correct server and returns content + mime_type |
| 109 | `test_post_mcp_clients_connect_success` | `/api/mcp-clients/connect` adds a new server, returns status + tool list |
| 110 | `test_post_mcp_clients_connect_duplicate_name` | Error when connecting with an already-used name |
| 111 | `test_post_mcp_clients_disconnect` | `/api/mcp-clients/<name>/disconnect` disconnects a server, returns status ok |
| 112 | `test_post_mcp_clients_disconnect_not_found` | Disconnecting unknown server returns `server_not_found` error |
| 113 | `test_post_mcp_clients_reconnect_success` | `/api/mcp-clients/<name>/reconnect` reconnects a server, returns status + tools |
| 114 | `test_post_mcp_clients_reconnect_not_found` | Reconnecting unknown server returns `server_not_found` error |
| 115 | `test_mcp_tools_call_records_in_call_records` | External tool calls are recorded in call records with `"source": "mcp_client"` |
| 116 | `test_mcp_tools_call_result_stored_in_cid_store` | External tool call results are stored in the CIDStore |
| 117 | `test_api_unavailable_when_no_client_manager` | All `/api/mcp-*` routes return 404 or 503 when MCPClientManager is not configured |

### Module: `tests/unit/test_mcp_client_proxy_tools.py`

#### MCP server proxy tool tests

| # | Test | Description |
|---|------|-------------|
| 118 | `test_external_list_servers_empty` | Returns empty when no MCP client connections |
| 119 | `test_external_list_servers_with_connections` | Returns server status and tool counts |
| 120 | `test_external_list_tools_all` | Returns all tools from all servers |
| 121 | `test_external_list_tools_filter_by_server` | Filters tools to a specific server |
| 122 | `test_external_call_tool_success` | Proxies a tool call through to the external server |
| 123 | `test_external_call_tool_server_not_found` | Error for unknown server name |
| 124 | `test_external_call_tool_tool_not_found` | Error for unknown tool name |
| 125 | `test_external_call_tool_timeout` | Error when external tool call times out |
| 126 | `test_external_call_tool_no_client_manager` | Error when MCPClientManager is not configured |
| 127 | `test_external_list_resources_all` | Returns resources from all servers with uri, server, name, description, mime_type |
| 128 | `test_external_list_resources_filter_by_server` | Filters resources to a specific server |
| 129 | `test_external_read_resource_success` | Reads a resource from the correct server, returns content + mime_type |
| 130 | `test_external_read_resource_server_not_found` | Error for unknown server |
| 131 | `test_external_read_resource_not_found` | Error when resource is not found |
| 132 | `test_proxy_tools_registered` | All 5 proxy tools are registered with the MCP server |
| 133 | `test_proxy_tool_names_prefixed` | Proxy tool names start with `external_` |
| 134 | `test_proxy_tool_results_are_json` | All proxy tool results are single TextContent with valid JSON |

### Module: `tests/unit/test_mcp_client_async_bridge.py`

#### Async-to-sync bridge tests

| # | Test | Description |
|---|------|-------------|
| 135 | `test_bridge_runs_coroutine_on_background_loop` | A coroutine submitted via the bridge runs on the background thread |
| 136 | `test_bridge_returns_result_to_calling_thread` | The result of the coroutine is returned to the calling thread |
| 137 | `test_bridge_propagates_exception` | An exception in the coroutine is re-raised on the calling thread |
| 138 | `test_bridge_timeout_raises` | A coroutine that takes too long raises TimeoutError |
| 139 | `test_bridge_concurrent_calls` | Multiple threads submitting coroutines concurrently all get correct results |
| 140 | `test_bridge_after_shutdown_raises` | Submitting to a shut-down bridge raises RuntimeError |

### Module: `tests/integration/test_mcp_client_integration.py`

#### End-to-end tests with real MCP servers

| # | Test | Description |
|---|------|-------------|
| 141 | `test_connect_to_mock_stdio_server` | Start a mock MCP server as subprocess, connect, list tools, call a tool |
| 142 | `test_connect_to_mock_sse_server` | Start a mock MCP SSE server, connect, list tools, call a tool |
| 143 | `test_multiple_servers_simultaneously` | Connect to two mock servers, verify tool catalogs are separate and both callable |
| 144 | `test_server_crash_recovery` | Kill a connected server process, verify status becomes disconnected, reconnect succeeds |
| 145 | `test_tool_call_through_rest_api` | Start breakpoint server with MCP client, call external tool via `/api/mcp-tools/call` |
| 146 | `test_tool_call_through_mcp_server` | Start breakpoint server as MCP server with client configured, call `external_call_tool` via MCP protocol |
| 147 | `test_connect_at_runtime_via_api` | Use `/api/mcp-clients/connect` to add a server after startup, then call its tools |
| 148 | `test_disconnect_at_runtime_via_api` | Use `/api/mcp-clients/<name>/disconnect` to remove a server, verify tools disappear |
| 149 | `test_config_file_loaded_on_startup` | With `--mcp-clients-config`, servers from config file are connected on startup |
| 150 | `test_graceful_shutdown` | Stopping the breakpoint server cleanly shuts down all MCP client connections |
| 151 | `test_tool_call_result_inspectable_via_cid` | External tool call result stored in CIDStore is retrievable via `breakpoint_inspect_object` |
| 152 | `test_inline_stdio_server_connected_on_startup` | `--mcp-client "name:command"` connects a stdio server on startup |
| 153 | `test_inline_sse_server_connected_on_startup` | `--mcp-client "name:http://url"` connects an SSE server on startup |

### Module: `tests/unit/test_mcp_client_edge_cases.py`

#### Edge case and error handling tests

| # | Test | Description |
|---|------|-------------|
| 154 | `test_server_returns_empty_tool_list` | A server with zero tools is connected; `list_tools()` works, `call_tool()` returns `tool_not_found` |
| 155 | `test_server_tool_list_changes_after_reconnect` | Server adds a new tool between disconnects; after reconnect the new tool appears |
| 156 | `test_tool_call_with_very_large_arguments` | Large argument payloads are passed through without truncation |
| 157 | `test_tool_call_with_very_large_result` | Large result payloads are returned without truncation |
| 158 | `test_server_name_collision_with_breakpoint_prefix` | Server named `"breakpoint"` works — its tools are `"breakpoint/tool"`, which does not collide with `"breakpoint_tool"` in the MCP server |
| 159 | `test_tool_with_no_input_schema` | External tools with no input_schema specified are callable with empty arguments |
| 160 | `test_unicode_in_tool_name` | Tool name containing unicode characters is handled correctly |
| 161 | `test_unicode_in_arguments` | Arguments containing unicode are passed through correctly |
| 162 | `test_tool_returning_is_error_true` | Tool result with `is_error=true` is propagated faithfully |
| 163 | `test_concurrent_connect_disconnect` | Connecting and disconnecting the same server from different threads |
| 164 | `test_call_tool_after_server_process_exit` | Calling a tool after the server process has exited returns connection error |
| 165 | `test_sse_server_url_trailing_slash` | SSE URL with trailing slash works |
| 166 | `test_sse_server_url_without_trailing_slash` | SSE URL without trailing slash works |
| 167 | `test_config_file_with_comments_rejected` | JSON with comments fails to parse with clear error |
| 168 | `test_shutdown_with_active_tool_call` | Shutdown while a tool call is in progress completes the shutdown without hanging |
| 169 | `test_connect_timeout_30s` | Connection attempt exceeding 30s connection timeout gets status `"error"` |
| 170 | `test_initialize_failure` | Server that connects but fails MCP initialization gets status `"error"` |
| 171 | `test_runtime_connection_not_persisted` | Server added via `/api/mcp-clients/connect` does not modify the config file |
| 172 | `test_runtime_connection_gone_after_restart` | After server restart, only config-file servers are reconnected (not runtime-added ones) |

---

## Resolved Decisions

Answers to the original open questions.

### 1. External tool calls recorded in call records

**Decision:** Yes. External tool calls are recorded in the breakpoint server's
call records. This gives debugging visibility into what external tools were
called and what they returned. Records are tagged with
`"source": "mcp_client"` to distinguish them from app-under-debug calls.

### 2. Web UI for external tools

**Decision:** No. The web UI does **not** expose external tools in this
iteration. External tools are accessible only via the REST API and the MCP
server proxy tools. A web UI for external tools can be added later if needed.

### 3. External tool results stored in CIDStore

**Decision:** Yes. External tool call results are stored in the CIDStore.
This allows them to be inspected later via `breakpoint_inspect_object` and
provides the same content-addressed deduplication as app call records.

### 4. Tool list refresh on connected servers

**Decision:** Only on connect/reconnect. The client manager does **not**
subscribe to `notifications/tools/list_changed` in this iteration. The tool
catalog is refreshed when a connection is established (connect or reconnect).
If a server's tools change while connected, the user must reconnect to see
the new tools. Subscription can be added later.

### 5. Per-tool timeout configuration

**Decision:** One timeout per server. The `timeout_s` field in the server
configuration applies to all tool calls on that server. Per-tool overrides
are not supported. This keeps configuration simple. If a specific tool needs
more time, increase the server-level timeout.

### 6. Server-initiated sampling requests

**Decision:** Raise an exception. If a connected MCP server sends a
`sampling/createMessage` request, the client manager raises a
`NotImplementedError` (which the MCP SDK will translate to an error response
back to the server). The breakpoint server does not have an LLM and cannot
fulfill sampling requests. This can be implemented later when needed.

### 7. Runtime connection persistence

**Decision:** Ephemeral. Servers added at runtime via
`/api/mcp-clients/connect` are **not** persisted to the config file. They
exist only for the lifetime of the breakpoint server process. The config file
is the source of truth for persistent server connections.

### 8. Maximum concurrent connections

**Decision:** No limit. There is no artificial cap on the number of
concurrent MCP server connections. Each stdio connection spawns a subprocess,
so system resources (file descriptors, memory) are the practical limit.

### 9. Authentication support

**Decision:** No authentication support yet. SSE servers that require
API keys or bearer tokens are not supported in this iteration. An `auth` or
`headers` config field can be added later.

### 10. Inline SSE syntax for `--mcp-client`

**Decision:** Use URL detection to auto-discriminate transport.

The `--mcp-client` flag uses a single unified format:

```
--mcp-client "name:value"
```

Where `value` determines the transport:
- If `value` starts with `http://` or `https://`, it is treated as an **SSE**
  connection to that URL.
- Otherwise, `value` is treated as a **stdio** command (split on whitespace
  into command + args).

**Examples:**
```bash
# stdio — spawns "npx -y @modelcontextprotocol/server-filesystem /tmp"
--mcp-client "filesystem:npx -y @modelcontextprotocol/server-filesystem /tmp"

# SSE — connects to the given URL
--mcp-client "remote-db:http://db-server:8080/mcp/sse"
--mcp-client "secure-api:https://api.example.com/mcp/sse"
```

**Rationale:**
- No extra syntax to remember — the URL scheme (`http://` / `https://`) is a
  natural and unambiguous discriminator.
- Consistent with how developers already think about connections: a command
  means "run this program", a URL means "connect to this endpoint".
- No need for explicit `stdio:` or `sse:` prefixes (though these could be
  added later as aliases if the heuristic proves insufficient).
- The colon after the server name is always the first colon. Server names
  cannot contain colons (they match `[a-zA-Z0-9_-]+`), so parsing is
  unambiguous.

## Open Questions

_(None — all questions have been resolved.)_

---

## Dependencies

| Package | Purpose | Version |
|---------|---------|---------|
| `mcp` | MCP Python SDK (already a dependency — client classes are in the same package) | existing |

No new dependencies are required. The `mcp` Python SDK already includes both
server and client classes (`ClientSession`, `stdio_client`, `sse_client`).

---

## File Changes Summary

| File | Change |
|------|--------|
| `server/src/cideldill_server/mcp_client_manager.py` | New — MCPClientManager, async-to-sync bridge, connection lifecycle |
| `server/src/cideldill_server/mcp_client_config.py` | New — Config file parsing and validation |
| `server/src/cideldill_server/mcp_server.py` | Modified — add `external_*` proxy tools |
| `server/src/cideldill_server/breakpoint_server.py` | Modified — add `/api/mcp-*` REST routes |
| `server/src/cideldill_server/__main__.py` | Modified — add `--mcp-clients`, `--mcp-clients-config`, `--mcp-client` CLI flags |
| `tests/unit/test_mcp_client_manager.py` | New — MCPClientManager unit tests |
| `tests/unit/test_mcp_client_config.py` | New — config parsing tests |
| `tests/unit/test_mcp_client_cli.py` | New — CLI flag tests |
| `tests/unit/test_mcp_client_rest_api.py` | New — REST API tests |
| `tests/unit/test_mcp_client_proxy_tools.py` | New — MCP server proxy tool tests |
| `tests/unit/test_mcp_client_async_bridge.py` | New — async-to-sync bridge tests |
| `tests/unit/test_mcp_client_edge_cases.py` | New — edge case tests |
| `tests/integration/test_mcp_client_integration.py` | New — end-to-end tests |
| `docs/mcp_integration.md` | Modified — add MCP client documentation |
| `~/.cideldill/mcp_clients.json` | New (user config) — example config file |
