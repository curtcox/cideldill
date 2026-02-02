# Breakpoints Web UI

CID el Dill ships with a Flask-based breakpoint server that manages call pauses and resumes.

## Start the Server

```bash
python -m cideldill --port 5000
```

Open `http://localhost:5000/` to access the web UI.

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
