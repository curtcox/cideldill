# MCP Integration

## Overview

CID el Dill exposes its breakpoint server over MCP so tools like Claude Code,
Cursor, or any MCP-compatible client can inspect and control breakpoints.

Two transports are supported:

- `stdio` (single client, launched by the MCP client)
- `SSE` (multiple clients over HTTP at `/mcp/sse`)

Both transports share the same `BreakpointManager` and `CIDStore` state as the
web UI and REST API.

## Commands

### stdio

```bash
python -m cideldill_server --mcp
```

Notes:

- In `--mcp` mode, all logging is redirected to stderr. Stdout is reserved for
  MCP JSON-RPC messages.
- The Flask server runs on a background thread so the web UI and debug client
  remain available.

### SSE

```bash
python -m cideldill_server --mcp-sse
```

This starts Flask normally and mounts the MCP SSE endpoint at `/mcp/sse`.

### Combined

```bash
python -m cideldill_server --mcp --mcp-sse
```

Runs both stdio and SSE transports simultaneously.

## Claude Code config example

```json
{
  "mcp_servers": {
    "cideldill": {
      "command": "python",
      "args": ["-m", "cideldill_server", "--mcp"],
      "env": {
        "CIDELDILL_PORT_FILE": "/tmp/cideldill-port"
      }
    }
  }
}
```

## Port discovery

By default, the server writes the selected port to `~/.cideldill/port`.
You can override this for tests or custom setups:

- `CIDELDILL_PORT_FILE=/custom/path` to set the port file
- `CIDELDILL_HOME=/custom/dir` to place `port` under a custom directory

## Troubleshooting

- Ensure the `mcp` Python SDK is installed in the server environment.
- The SSE transport mounts an ASGI app into the existing WSGI server; no extra dependencies are required beyond `mcp`.
