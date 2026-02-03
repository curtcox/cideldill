# Breakpoints Web UI

CID el Dill ships with a Flask-based breakpoint server that manages call pauses and resumes.

## Start the Server

```bash
python -m cideldill_server --port 5000
```

Open `http://localhost:5000/` to access the web UI.

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
python -m cideldill_server --port 5000

# Terminal 2: Run the demo with debugging enabled
python examples/sequence_demo.py --debug ON --iterations 10
```

You can customize the debug flag and iterations via command-line arguments:
- `--debug {ON,OFF}` or `-d {ON,OFF}`: Enable or disable debugging
- `--iterations N` or `-i N`: Set the number of iterations to run

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
