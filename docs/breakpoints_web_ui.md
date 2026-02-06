# Breakpoints Web UI

CID el Dill ships with a Flask-based breakpoint server that manages call pauses and resumes.

## Start the Server

```bash
python -m cideldill_server --port 5174
```

The server will automatically find a free port if 5174 is occupied. The actual port
is written to `~/.cideldill/port` for client auto-discovery. Open the web UI at the
port shown in the server output (for example `http://localhost:5174/`).

## Quick Start with Sequence Demo

The easiest way to try out breakpoints is to use the `sequence_demo` example with pre-configured breakpoints:

```bash
# On macOS, run the sequence demo with breakpoints and browser UI
run/mac/sequence_demo_breakpoints

# Customize the port and iterations
run/mac/sequence_demo_breakpoints --port 8080 --iterations 20

# Run without opening browser
run/mac/sequence_demo_breakpoints --no-browser
```

This script will:
1. Start the breakpoint server
2. Set breakpoints on key functions (`whole_numbers`, `announce_say_default`, `delay_1s`)
3. Open your browser to the breakpoint UI
4. Run the sequence demo with debugging enabled

You can then examine, enable/disable, and toggle breakpoints through the web UI to see how execution pauses and resumes.

## Manual Demo Setup

To manually run the sequence demo with debugging:

```bash
# Terminal 1: Start the breakpoint server
python -m cideldill_server --port 5174

# Terminal 2: Run the demo with debugging enabled
python examples/sequence_demo.py --debug ON --iterations 10
```

You can customize the debug flag and iterations via command-line arguments:
- `--debug {ON,OFF}` or `-d {ON,OFF}`: Enable or disable debugging
- `--iterations N` or `-i N`: Set the number of iterations to run

## Port Discovery

The server automatically handles port conflicts:

1. **Default behavior**: Attempts to use port 5174
2. **Conflict resolution**: If occupied, automatically selects a free port
3. **Discovery file**: Writes actual port to `~/.cideldill/port`
4. **Client auto-discovery**: Clients read the port from the discovery file

### Manual Port Selection

```bash
# Request specific port
python -m cideldill_server --port 8080

# Server will use 8080 if available, otherwise fallback to auto-assigned port
```

### Environment Variables

For explicit control, use the environment variable:

```bash
export CIDELDILL_SERVER_URL="http://localhost:8080"
```

Priority order:
1. `configure_debug(server_url=...)`
2. `CIDELDILL_SERVER_URL` environment variable
3. Port discovery file (`~/.cideldill/port`)
4. Default (`http://localhost:5174`)

## Call Types

Each call reported to the server includes a `call_type` field in the `/api/call/start`
payload:

- `"proxy"` — The call was intercepted by a `DebugProxy` (created via `with_debug`).
- `"inline"` — The call was made through `debug_call` / `async_debug_call`.

The web UI displays both types in the call list. Inline breakpoints behave identically
to proxy breakpoints for pause/resume, modification, and replacement.

## API Endpoints

- `POST /api/call/start` — Debug clients notify the server about a call.
- `GET /api/poll/<id>` — Debug clients poll for resume actions.
- `POST /api/call/complete` — Debug clients notify the server about completion.
- `GET /api/breakpoints` — List breakpoints.
- `POST /api/breakpoints` — Add breakpoint.
- `DELETE /api/breakpoints/<name>` — Remove breakpoint.
- `GET /api/paused` — List paused executions.
- `POST /api/paused/<id>/continue` — Resume a paused execution.

## Setting Breakpoints

Use the web UI to add or remove breakpoints. When a method name matches a breakpoint, the server responds to the debug client with an action of `poll`, which pauses execution until you resume it.

## Resuming Execution

From the UI, select **Continue** or **Skip** on a paused call. The debug client will continue based on the action returned by `/api/poll/<id>`.
