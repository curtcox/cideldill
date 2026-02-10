"""Tests for server-side exception reporting in breakpoint_server.

Verifies that the server's /api/call/complete endpoint:
1. Reads exception_type, exception_message, exception_traceback from the payload
2. Stores them in call records
3. Makes exception details searchable in the call-tree UI
4. Uses plain-text fields as fallback when dill deserialization degrades
5. Displays exception details visibly in all UI pages
6. Parses exception tracebacks into clickable source links
"""

from __future__ import annotations

import json
import threading
import time

import pytest

pytest.importorskip("dill")

from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def server():
    """Create a test server instance."""
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=0)
    yield server
    server.stop()


def _start_call(server, method_name="my_tool.ainvoke"):
    """Start a call and return the call_id."""
    client = server.test_client()
    response = client.post(
        "/api/call/start",
        data=json.dumps({
            "method_name": method_name,
            "args": [],
            "kwargs": {},
            "call_site": {"timestamp": 1000.0, "stack_trace": []},
            "call_type": "proxy",
            "process_pid": 1234,
            "process_start_time": 999.0,
        }),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    call_id = data.get("call_id")
    assert call_id is not None
    return call_id


def _complete_call_with_exception(
    server,
    call_id,
    exception_type="psycopg2.OperationalError",
    exception_message='connection to server at "localhost" failed: FATAL: role "postgres" does not exist',
    exception_traceback=(
        "Traceback (most recent call last):\n"
        '  File "sql_client.py", line 81, in get_connection\n'
        "    conn = psycopg2.connect(self.connection_string)\n"
        'psycopg2.OperationalError: connection to server at "localhost" failed\n'
    ),
):
    """Complete a call with exception plain-text fields (no dill blob)."""
    client = server.test_client()
    response = client.post(
        "/api/call/complete",
        data=json.dumps({
            "call_id": call_id,
            "status": "exception",
            "timestamp": 1001.0,
            "process_pid": 1234,
            "process_start_time": 999.0,
            "exception_type": exception_type,
            "exception_message": exception_message,
            "exception_traceback": exception_traceback,
        }),
        content_type="application/json",
    )
    assert response.status_code == 200
    return response


# ---------------------------------------------------------------------------
# Tests: Server stores plain-text exception fields
# ---------------------------------------------------------------------------


class TestServerStoresExceptionFields:
    """The server's /api/call/complete must read exception_type,
    exception_message, and exception_traceback from the client payload
    and include them in call records."""

    def test_call_record_contains_exception_type(self, server) -> None:
        """Plain-text exception_type sent by client must appear in the call record."""
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.2)

        call_id = _start_call(server)
        _complete_call_with_exception(server, call_id)

        records = server.manager.get_call_records()
        exc_records = [r for r in records if r.get("status") == "exception"]
        assert len(exc_records) == 1
        assert exc_records[0].get("exception_type") == "psycopg2.OperationalError"

    def test_call_record_contains_exception_message(self, server) -> None:
        """Plain-text exception_message sent by client must appear in the call record."""
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.2)

        call_id = _start_call(server)
        _complete_call_with_exception(server, call_id)

        records = server.manager.get_call_records()
        exc_records = [r for r in records if r.get("status") == "exception"]
        assert len(exc_records) == 1
        assert "role" in exc_records[0].get("exception_message", "")

    def test_call_record_contains_exception_traceback(self, server) -> None:
        """Plain-text exception_traceback sent by client must appear in the call record."""
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.2)

        call_id = _start_call(server)
        _complete_call_with_exception(server, call_id)

        records = server.manager.get_call_records()
        exc_records = [r for r in records if r.get("status") == "exception"]
        assert len(exc_records) == 1
        assert "psycopg2" in exc_records[0].get("exception_traceback", "")


# ---------------------------------------------------------------------------
# Tests: Exception details are searchable in the call-tree
# ---------------------------------------------------------------------------


class TestExceptionSearchable:
    """Searching the call tree for exception details must find the exception."""

    def test_exception_type_searchable_in_call_tree(self, server) -> None:
        """Searching the call-tree detail for 'psycopg2' must find the exception."""
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.2)

        call_id = _start_call(server)
        _complete_call_with_exception(server, call_id)

        # Get the call-tree index to find the process key
        records = server.manager.get_call_records()
        assert len(records) == 1
        process_key = records[0]["process_key"]

        # Fetch the call-tree detail page
        client = server.test_client()
        resp = client.get(f"/call-tree/{process_key}")
        assert resp.status_code == 200
        html_text = resp.data.decode("utf-8")

        # The exception type must be in the page's search-indexable data
        assert "psycopg2" in html_text.lower()

    def test_exception_traceback_searchable_in_call_tree(self, server) -> None:
        """The traceback text must be present in the call-tree page data."""
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.2)

        call_id = _start_call(server)
        _complete_call_with_exception(server, call_id)

        records = server.manager.get_call_records()
        process_key = records[0]["process_key"]

        client = server.test_client()
        resp = client.get(f"/call-tree/{process_key}")
        assert resp.status_code == 200
        html_text = resp.data.decode("utf-8")

        # The traceback content should be present
        assert "sql_client.py" in html_text


# ---------------------------------------------------------------------------
# Tests: Plain-text fields used as fallback when no dill blob
# ---------------------------------------------------------------------------


class TestExceptionFallbackWithoutDill:
    """When no exception CID/data is present (dill serialization failed
    completely), the plain-text fields should still produce a displayable
    exception in the call record."""

    def test_exception_field_constructed_from_plain_text(self, server) -> None:
        """call_record['exception'] should be constructed from plain-text
        fields when no exception_cid is provided."""
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.2)

        call_id = _start_call(server)
        _complete_call_with_exception(
            server,
            call_id,
            exception_type="psycopg2.OperationalError",
            exception_message="connection failed",
            exception_traceback="Traceback: psycopg2.OperationalError\n",
        )

        records = server.manager.get_call_records()
        exc_records = [r for r in records if r.get("status") == "exception"]
        assert len(exc_records) == 1
        record = exc_records[0]

        # The 'exception' field should contain useful info from plain text
        exc = record.get("exception")
        assert exc is not None
        # It should contain the exception type info
        assert "psycopg2" in str(exc) or "OperationalError" in str(exc)


# ---------------------------------------------------------------------------
# Tests: Exception details displayed in call-tree detail page
# ---------------------------------------------------------------------------


class TestCallTreeDetailExceptionDisplay:
    """The call-tree detail page must render exception type, message,
    and traceback in a human-readable way — not as raw JSON."""

    def test_exception_summary_visible_in_call_tree_detail(self, server) -> None:
        """The call-tree detail page's formatPretty JS function must handle
        __cideldill_exception__ objects to produce a human-readable summary."""
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.2)

        call_id = _start_call(server)
        _complete_call_with_exception(server, call_id)

        records = server.manager.get_call_records()
        process_key = records[0]["process_key"]

        client = server.test_client()
        resp = client.get(f"/call-tree/{process_key}")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # The call-tree JS formatPretty must include __cideldill_exception__
        # handling so that exception summary is rendered, not raw JSON
        assert "value.__cideldill_exception__" in html

    def test_traceback_rendered_in_call_tree_node_detail(self, server) -> None:
        """The traceback should be rendered in the node detail panel
        of the call-tree page."""
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.2)

        call_id = _start_call(server)
        _complete_call_with_exception(server, call_id)

        records = server.manager.get_call_records()
        process_key = records[0]["process_key"]

        client = server.test_client()
        resp = client.get(f"/call-tree/{process_key}")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # The JS rendering code must handle traceback display
        assert "exception_traceback" in html or "node.exception_traceback" in html


# ---------------------------------------------------------------------------
# Tests: Exception details displayed in main dashboard paused cards
# ---------------------------------------------------------------------------


class TestDashboardExceptionDisplay:
    """The main dashboard's formatPretty must handle __cideldill_exception__
    objects so paused-on-exception cards show readable text."""

    def test_dashboard_formatPretty_handles_exception_objects(self, server) -> None:
        """The main dashboard formatPretty JS function must recognize
        __cideldill_exception__ objects and return the summary."""
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.2)

        client = server.test_client()
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # The JS must contain __cideldill_exception__ handling
        assert "__cideldill_exception__" in html


# ---------------------------------------------------------------------------
# Tests: Exception details displayed in breakpoint history detail page
# ---------------------------------------------------------------------------


class TestBreakpointHistoryDetailExceptionDisplay:
    """The breakpoint history detail page must render exception info
    in a human-readable format, not as raw JSON."""

    def test_format_pretty_for_html_renders_exception_summary(self, server) -> None:
        """_format_pretty_for_html should produce a human-readable string
        for __cideldill_exception__ dicts, not raw JSON."""
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.2)

        # Set up a breakpoint so execution recording happens
        server.manager.add_breakpoint("my_tool.ainvoke")
        server.manager.set_default_behavior("go")

        call_id = _start_call(server)
        _complete_call_with_exception(
            server,
            call_id,
            exception_type="psycopg2.OperationalError",
            exception_message="connection failed",
            exception_traceback="Traceback (most recent call last):\n  psycopg2.OperationalError: connection failed\n",
        )

        # Get the execution records for the breakpoint history
        records = server.manager.get_execution_history("my_tool.ainvoke")
        assert len(records) >= 1
        record_id = records[0].get("id", "0")

        client = server.test_client()
        resp = client.get(f"/breakpoint/my_tool.ainvoke/history/{record_id}")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # The exception type should appear as readable text
        assert "psycopg2.OperationalError" in html
        # The traceback should appear
        assert "connection failed" in html
        # It should NOT show raw JSON keys as visible content
        assert "__cideldill_exception__" not in html


# ---------------------------------------------------------------------------
# Tests: Traceback parsing and source frame linking
# ---------------------------------------------------------------------------

SAMPLE_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "/Users/coxcu/me/cideldill/client/src/cideldill_client/debug_proxy.py", line 322, in wrapper\n'
    "    result = await self._execute_action_async(action, method, args, kwargs, frame=frame)\n"
    "             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n"
    '  File "/Users/coxcu/work/project/sql_client.py", line 81, in get_connection\n'
    "    conn = psycopg2.connect(self.connection_string)\n"
    "           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n"
    "psycopg2.OperationalError: connection failed\n"
)


class TestTracebackSourceLinks:
    """Exception tracebacks should be parsed and rendered with clickable
    links to /frame/source pages, matching the existing stack trace style."""

    def test_frame_source_route_exists(self, server) -> None:
        """A /frame/source route must exist to render source by file+line."""
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.2)

        client = server.test_client()
        # Request a non-existent file — should return 404, not 405 (method not allowed)
        resp = client.get("/frame/source?file=/nonexistent.py&line=1")
        assert resp.status_code in (200, 404), (
            f"Expected 200 or 404, got {resp.status_code}"
        )

    def test_call_tree_has_traceback_parser_js(self, server) -> None:
        """The call-tree detail page must include JS that parses Python
        tracebacks into structured frames with clickable links."""
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.2)

        call_id = _start_call(server)
        _complete_call_with_exception(
            server, call_id, exception_traceback=SAMPLE_TRACEBACK,
        )

        records = server.manager.get_call_records()
        process_key = records[0]["process_key"]

        client = server.test_client()
        resp = client.get(f"/call-tree/{process_key}")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # Must contain a function that parses traceback text into frames
        assert "renderTraceback" in html or "parseTraceback" in html

    def test_call_tree_traceback_contains_frame_links(self, server) -> None:
        """The rendered traceback should link to /frame/source pages."""
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.2)

        call_id = _start_call(server)
        _complete_call_with_exception(
            server, call_id, exception_traceback=SAMPLE_TRACEBACK,
        )

        records = server.manager.get_call_records()
        process_key = records[0]["process_key"]

        client = server.test_client()
        resp = client.get(f"/call-tree/{process_key}")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # The JS rendering code must reference /frame/source for traceback links
        assert "/frame/source" in html

    def test_dashboard_traceback_contains_frame_links(self, server) -> None:
        """The dashboard renderException should also link traceback frames."""
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.2)

        client = server.test_client()
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # The dashboard page must include traceback rendering with links
        assert "renderTraceback" in html or "parseTraceback" in html
