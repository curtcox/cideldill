"""Unit tests for REPL UI metadata rendering."""

import json

import pytest

from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer


@pytest.fixture
def server():
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=0)
    yield server
    server.stop()


def _pause_call_data() -> dict[str, object]:
    return {
        "method_name": "demo",
        "call_id": "call-1",
        "call_site": {"stack_trace": []},
        "process_pid": 123,
        "process_start_time": 10.0,
        "process_key": "10.000000+123",
        "pretty_args": ["alpha"],
        "pretty_kwargs": {"beta": 2},
        "args": [],
        "kwargs": {},
        "signature": "(alpha, beta=2)",
    }


def test_repl_page_shows_parameter_list(server) -> None:
    pause_id = server.manager.add_paused_execution(_pause_call_data())
    session_id = server.manager.start_repl_session(pause_id)

    response = server.test_client().get(f"/api/repl/{session_id}")
    assert response.status_code == 200
    payload = json.loads(response.data)
    session = payload["session"]
    assert session["pretty_args"] == ["alpha"]
    assert session["pretty_kwargs"] == {"beta": 2}


def test_repl_page_links_help(server) -> None:
    pause_id = server.manager.add_paused_execution(_pause_call_data())
    session_id = server.manager.start_repl_session(pause_id)

    response = server.test_client().get(f"/repl/{session_id}")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "/repl-help" in html


def test_repl_help_page_renders(server) -> None:
    response = server.test_client().get("/repl-help")
    assert response.status_code == 200
    assert b"REPL Help" in response.data
