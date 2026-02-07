"""Unit tests for REPL HTML pages."""

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
        "call_site": {
            "stack_trace": [
                {
                    "filename": __file__,
                    "lineno": 1,
                    "function": "test_callstack_page_renders",
                    "code_context": "def test_callstack_page_renders(server) -> None:",
                }
            ]
        },
        "process_pid": 123,
        "process_start_time": 10.0,
        "process_key": "10.000000+123",
    }


def test_callstack_page_renders(server) -> None:
    pause_id = server.manager.add_paused_execution(_pause_call_data())

    response = server.test_client().get(f"/callstack/{pause_id}")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "Call Stack" in html
    assert "demo" in html


def test_callstack_page_returns_404(server) -> None:
    response = server.test_client().get("/callstack/missing")
    assert response.status_code == 404


def test_repl_page_renders_for_session(server) -> None:
    pause_id = server.manager.add_paused_execution(_pause_call_data())
    session_id = server.manager.start_repl_session(pause_id)

    response = server.test_client().get(f"/repl/{session_id}")
    assert response.status_code == 200
    assert session_id.encode("utf-8") in response.data


def test_repls_page_renders(server) -> None:
    response = server.test_client().get("/repls")
    assert response.status_code == 200
    assert b"REPL Sessions" in response.data


def test_call_tree_shows_repl_badge(server) -> None:
    process_key = "10.000000+123"
    server.manager.record_call({
        "call_id": "call-1",
        "method_name": "demo",
        "status": "success",
        "pretty_args": [],
        "pretty_kwargs": {},
        "signature": None,
        "call_site": {"timestamp": 1.0, "stack_trace": []},
        "process_pid": 123,
        "process_start_time": 10.0,
        "process_key": process_key,
        "started_at": 1.0,
        "completed_at": 1.0,
        "repl_sessions": ["123-1.000000"],
    })

    response = server.test_client().get(f"/call-tree/{process_key}")
    assert response.status_code == 200
    assert b"REPL" in response.data
