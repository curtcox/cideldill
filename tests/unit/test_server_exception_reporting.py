"""Tests for server-side exception reporting in breakpoint_server.

Verifies that the server's /api/call/complete endpoint:
1. Reads exception_type, exception_message, exception_traceback from the payload
2. Stores them in call records
3. Makes exception details searchable in the call-tree UI
4. Uses plain-text fields as fallback when dill deserialization degrades
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
