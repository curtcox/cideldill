# Bug Report: Exception details not searchable in breakpoint server UI

## Summary

When a `DebugProxy`-wrapped tool raises an exception during execution, the exception info (fully-qualified type, message, traceback) is not searchable or visible in the breakpoint server web UI. Searching for `psycopg2` in any UI page returns no results, even though the console shows the full `psycopg2.OperationalError` traceback.

A previous fix (adding `exception_type`, `exception_message`, and `exception_traceback` as plain-text fields to the client's `record_call_complete` payload) did **not** resolve the issue. The root cause is a **client/server mismatch**: the client now sends these fields, but the server's `/api/call/complete` handler ignores them entirely.

## Root Cause Analysis

The bug spans **both** the client and the server. There are two independent problems:

### Problem 1: Server ignores plain-text exception fields (PRIMARY CAUSE)

The client's `DebugClient.record_call_complete` (lines 269–288 of `debug_client.py`) now correctly sends:

```
payload["exception_type"]      = "psycopg2.OperationalError"
payload["exception_message"]   = "connection to server at ..."
payload["exception_traceback"] = "Traceback (most recent call last): ..."
```

But the server's `call_complete()` handler (`breakpoint_server.py` line 5110) **never reads these fields**:

```python
# Server reads ONLY these exception-related fields:
exception_data = data.get("exception_data")          # dill blob
exception_cid = data.get("exception_cid")            # hash of dill blob
exception_format = data.get("exception_serialization_format", "dill")
exception_client_ref = data.get("exception_client_ref")

# These client-sent fields are SILENTLY DROPPED:
# data.get("exception_type")       ← NEVER READ
# data.get("exception_message")    ← NEVER READ
# data.get("exception_traceback")  ← NEVER READ
```

The server relies exclusively on deserializing the dill blob via `_format_payload_value({"cid": exception_cid, ...})` to produce the `pretty_exception` text used in the UI and search index.

### Problem 2: Dill serialization degrades C-extension exceptions to opaque placeholders

For exceptions from C-extension modules (e.g. `psycopg2.OperationalError`), dill serialization fails and degrades to an `UnpicklablePlaceholder`. The placeholder's `summary` field is formatted by `_placeholder_summary()` as:

```
<Unpicklable psycopg2.extensions.OperationalError attrs=N failed=M error=...>
```

While this *does* contain `psycopg2`, the actual display in the UI depends on `_format_placeholder()` → `formatPretty()` in the JavaScript, which may truncate or lose this. More critically, **the traceback is never captured anywhere in the placeholder** — it only preserves `__dict__` attributes and a repr, not `__traceback__`.

### How these interact

The server constructs `pretty_exception` solely from the deserialized CID blob. For C-extension exceptions, this produces a placeholder summary that:
- May or may not contain the module name (depends on placeholder formatting)
- **Never contains the traceback**
- Is the **only** text that enters the search index (via `_record_search_text` which JSON-dumps the call record)

The plain-text fields (`exception_type`, `exception_message`, `exception_traceback`) that the client sends — which contain the exact information needed — are discarded by the server.

## Affected Components

| Component | File | Issue |
|---|---|---|
| **Server** | `breakpoint_server.py` `call_complete()` (line 5110) | Does not read `exception_type`, `exception_message`, `exception_traceback` from payload |
| **Server** | `breakpoint_server.py` `call_record` construction (line 5192) | Does not store plain-text exception fields in call records |
| **Server** | `breakpoint_server.py` `_record_search_text()` (line 2827) | Search index only contains JSON-dumped call record, which lacks plain-text exception info |
| **Client** | `debug_client.py` `record_call_complete()` (line 248) | Sends fields correctly (after fix), but server ignores them |

## Reproduction Steps

### Minimal reproduction (no external dependencies)

The core issue can be demonstrated with a pure-Python test that simulates a C-extension exception whose dill serialization degrades to a placeholder. See **Test Cases** below.

### Full reproduction (vulnerability_prioritization_agent)

```bash
cd vulnerability_prioritization_agent
nat serve --config_file=configs/debug-config.yml
```

Send a request with no PostgreSQL running. The `asset_tool` raises `psycopg2.OperationalError`. Console shows the full traceback; breakpoint server UI does not.

## Proposed Fix

### Server-side: Read and store plain-text exception fields

In `breakpoint_server.py`, `call_complete()`, after line 5124:

```python
exception_type = data.get("exception_type")
exception_message = data.get("exception_message")
exception_traceback = data.get("exception_traceback")
```

Then when building `call_record` (around line 5192), store these as fallback/primary text:

```python
if exception_type:
    call_record["exception_type"] = exception_type
if exception_message:
    call_record["exception_message"] = exception_message
if exception_traceback:
    call_record["exception_traceback"] = exception_traceback
```

And when constructing `pretty_exception`, prefer the plain-text fields over the deserialized placeholder when the deserialized value is an `UnpicklablePlaceholder`:

```python
if pretty_exception is not None and exception_type:
    # If deserialization degraded to placeholder, use plain-text fields instead
    if isinstance(pretty_exception, dict) and pretty_exception.get("__cideldill_placeholder__"):
        pretty_exception = {
            "__cideldill_exception__": True,
            "summary": f"{exception_type}: {exception_message}",
            "type_name": exception_type.rsplit(".", 1)[-1],
            "module": exception_type.rsplit(".", 1)[0] if "." in exception_type else "builtins",
            "qualname": exception_type.rsplit(".", 1)[-1],
            "message": exception_message or "",
            "traceback": exception_traceback or "",
        }
elif not pretty_exception and exception_type:
    pretty_exception = {
        "__cideldill_exception__": True,
        "summary": f"{exception_type}: {exception_message}",
        "type_name": exception_type.rsplit(".", 1)[-1],
        "module": exception_type.rsplit(".", 1)[0] if "." in exception_type else "builtins",
        "qualname": exception_type.rsplit(".", 1)[-1],
        "message": exception_message or "",
        "traceback": exception_traceback or "",
    }
```

### UI: Display traceback and include in search

In the `renderException()` JavaScript function (line 815), render the traceback if present:

```javascript
const renderException = () => {
    if (prettyException === null || prettyException === undefined) {
        return '';
    }
    let text = escapeHtml(formatPretty(prettyException));
    if (prettyException.traceback) {
        text += '\n\n' + escapeHtml(prettyException.traceback);
    }
    return `<div class="call-data"><strong>Exception:</strong>\n${text}</div>`;
};
```

In `recordToRowData()` (breakpoint history, line 4207), include traceback in `searchText`:

```javascript
const exceptionTraceback = callData.exception_traceback || '';
// ...
searchText: `${timeText} ${callText} ${resultText} ${statusText} ${exceptionTraceback}`.toLowerCase(),
```

## Test Cases

The following tests reproduce the issue with **no external dependencies** (no psycopg2, no database, no NAT). They should be added to `tests/unit/test_exception_reporting.py`.

### Test 1: Server receives and stores plain-text exception fields

```python
class TestServerExceptionFields:
    """The server's /api/call/complete must read exception_type, exception_message,
    and exception_traceback from the client payload and include them in call records."""

    def test_call_complete_stores_exception_type_from_payload(self):
        """Plain-text exception_type sent by client must appear in the call record."""
        from cideldill_server.breakpoint_manager import BreakpointManager
        from cideldill_server.breakpoint_server import BreakpointServer

        manager = BreakpointManager()
        server = BreakpointServer(manager, port=0)
        client = server.app.test_client()

        # Simulate call/start so the server has a pending call
        start_resp = client.post("/api/call/start", json={
            "method_name": "my_tool.ainvoke",
            "target_cid": "abc123",
            "args": [],
            "kwargs": {},
            "call_site": {"timestamp": 1000.0, "stack_trace": []},
            "call_type": "proxy",
            "process_pid": 1234,
            "process_start_time": 999.0,
        })
        call_id = start_resp.get_json().get("call_id")
        assert call_id is not None

        # Simulate call/complete with exception plain-text fields
        complete_resp = client.post("/api/call/complete", json={
            "call_id": call_id,
            "status": "exception",
            "timestamp": 1001.0,
            "process_pid": 1234,
            "process_start_time": 999.0,
            "exception_type": "psycopg2.OperationalError",
            "exception_message": 'connection to server at "localhost" failed: FATAL: role "postgres" does not exist',
            "exception_traceback": (
                "Traceback (most recent call last):\n"
                '  File "sql_client.py", line 81, in get_connection\n'
                "    conn = psycopg2.connect(self.connection_string)\n"
                'psycopg2.OperationalError: connection to server at "localhost" failed\n'
            ),
        })
        assert complete_resp.status_code == 200

        # Verify the call record contains the plain-text exception fields
        records = manager.get_call_records()
        exc_records = [r for r in records if r.get("status") == "exception"]
        assert len(exc_records) == 1
        record = exc_records[0]
        assert record.get("exception_type") == "psycopg2.OperationalError"
        assert "role" in record.get("exception_message", "")
        assert "psycopg2" in record.get("exception_traceback", "")

    def test_call_complete_exception_searchable_in_call_tree(self):
        """Searching the call tree for 'psycopg2' must find the exception."""
        from cideldill_server.breakpoint_manager import BreakpointManager
        from cideldill_server.breakpoint_server import BreakpointServer

        manager = BreakpointManager()
        server = BreakpointServer(manager, port=0)
        client = server.app.test_client()

        start_resp = client.post("/api/call/start", json={
            "method_name": "my_tool.ainvoke",
            "target_cid": "abc123",
            "args": [],
            "kwargs": {},
            "call_site": {"timestamp": 1000.0, "stack_trace": []},
            "call_type": "proxy",
            "process_pid": 1234,
            "process_start_time": 999.0,
        })
        call_id = start_resp.get_json().get("call_id")

        client.post("/api/call/complete", json={
            "call_id": call_id,
            "status": "exception",
            "timestamp": 1001.0,
            "process_pid": 1234,
            "process_start_time": 999.0,
            "exception_type": "psycopg2.OperationalError",
            "exception_message": "connection failed",
            "exception_traceback": "Traceback: psycopg2.OperationalError: connection failed\n",
        })

        # Fetch the call tree index page and check that 'psycopg2' appears in searchText
        resp = client.get("/call-tree")
        assert resp.status_code == 200
        html_text = resp.data.decode("utf-8")
        assert "psycopg2" in html_text.lower()
```

### Test 2: Client sends all three plain-text fields (existing tests verify this, but add C-extension simulation)

```python
class TestClientExceptionPayloadForCExtensions:
    """Verify that record_call_complete sends exception_type with full module path
    even for exceptions that cannot be dill-serialized."""

    def test_unserialisable_exception_still_sends_plain_text_fields(self, monkeypatch):
        """Even when dill serialization degrades, the plain-text fields must be present."""
        captured = {}

        class _Response:
            status_code = 200
            text = '{"status": "ok"}'
            def json(self):
                return {"status": "ok"}

        def fake_post(url, json, timeout):
            if "/api/call/complete" in url:
                captured["payload"] = json
            return _Response()

        monkeypatch.setattr("requests.post", fake_post)

        from cideldill_client.debug_client import DebugClient
        client = DebugClient("http://localhost:5000")

        # Simulate a C-extension-like exception with a traceback
        class FakeCExtError(Exception):
            """Simulates an exception from a C extension module."""
            pass

        # Give it a non-builtins module to simulate psycopg2
        FakeCExtError.__module__ = "psycopg2"
        FakeCExtError.__qualname__ = "OperationalError"

        try:
            raise FakeCExtError("connection failed: FATAL: role does not exist")
        except FakeCExtError as exc:
            client.record_call_complete(
                call_id="test-001",
                status="exception",
                exception=exc,
            )

        payload = captured["payload"]
        assert payload["exception_type"] == "psycopg2.OperationalError"
        assert "connection failed" in payload["exception_message"]
        assert "exception_traceback" in payload
        assert "psycopg2.OperationalError" in payload["exception_traceback"]
        assert "connection failed" in payload["exception_traceback"]
```

### Test 3: End-to-end DebugProxy exception flow

```python
class TestDebugProxyExceptionReporting:
    """End-to-end: DebugProxy catches exception → client sends plain-text fields
    → server stores them in call record → searchable in UI."""

    def test_proxy_exception_produces_searchable_record(self):
        """A DebugProxy-wrapped async method that raises should produce a call record
        containing the fully-qualified exception type and traceback."""
        import asyncio
        from unittest.mock import MagicMock
        from cideldill_server.breakpoint_manager import BreakpointManager
        from cideldill_server.breakpoint_server import BreakpointServer
        from cideldill_client.debug_client import DebugClient
        from cideldill_client.debug_proxy import DebugProxy

        manager = BreakpointManager()
        server = BreakpointServer(manager, port=0)

        # Use the real Flask test server via requests mock
        flask_client = server.app.test_client()

        class FakeDBError(Exception):
            pass
        FakeDBError.__module__ = "psycopg2"
        FakeDBError.__qualname__ = "OperationalError"

        class Target:
            async def ainvoke(self, request):
                raise FakeDBError("FATAL: role does not exist")

        target = Target()
        debug_client = DebugClient.__new__(DebugClient)
        # Wire the debug client to post to the Flask test client
        # (This is a simplified wiring; a full integration test would use a real server)

        # Verify that after the proxy catches and reports the exception,
        # the call record on the server contains "psycopg2" in searchable fields.
        # (Implementation depends on test infrastructure for wiring client↔server)
```

## Environment

- **cideldill client**: `/Users/coxcu/me/cideldill/client/src/cideldill_client`
- **cideldill server**: `/Users/coxcu/me/cideldill/server/src/cideldill_server`
- **Python**: 3.12.12
- **OS**: macOS (Apple Silicon)
- **Failing library**: psycopg2 (C-extension exception type)

## Summary of Required Changes

| # | Component | File | Change |
|---|---|---|---|
| 1 | **Server** | `breakpoint_server.py` `call_complete()` | Read `exception_type`, `exception_message`, `exception_traceback` from payload |
| 2 | **Server** | `breakpoint_server.py` `call_complete()` | Store these fields in `call_record` dict |
| 3 | **Server** | `breakpoint_server.py` `call_complete()` | Use plain-text fields as fallback for `pretty_exception` when dill deserialization produces a placeholder |
| 4 | **Server** | `breakpoint_server.py` UI templates | Render `traceback` field in exception display; include in `searchText` |
| 5 | **Client** | `debug_client.py` | Already fixed — no further changes needed |
