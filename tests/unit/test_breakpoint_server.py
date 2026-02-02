"""Unit tests for Breakpoint Web Server.

This test suite validates the web server API endpoints for breakpoint management.
"""

import json
import threading
import time

import pytest

pytest.importorskip("dill")

from cideldill.breakpoint_manager import BreakpointManager
from cideldill.breakpoint_server import BreakpointServer
from cideldill.serialization import Serializer


@pytest.fixture
def server():
    """Create a test server instance."""
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=0)  # port=0 for random available port
    yield server
    server.stop()


def test_can_create_server() -> None:
    """Test that server can be instantiated."""
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=0)
    assert server is not None
    server.stop()


def test_server_can_start_and_stop() -> None:
    """Test that server can start and stop."""
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=0)
    
    # Start in background thread
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)  # Give it time to start
    
    assert server.is_running()
    
    server.stop()
    time.sleep(0.2)
    
    assert not server.is_running()


def test_get_breakpoints_endpoint(server) -> None:
    """Test GET /api/breakpoints endpoint."""
    # Start server
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)
    
    # Add some breakpoints
    server.manager.add_breakpoint("func1")
    server.manager.add_breakpoint("func2")
    
    # Test endpoint
    response = server.test_client().get("/api/breakpoints")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert "func1" in data["breakpoints"]
    assert "func2" in data["breakpoints"]


def test_add_breakpoint_endpoint(server) -> None:
    """Test POST /api/breakpoints endpoint."""
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)
    
    response = server.test_client().post(
        "/api/breakpoints",
        data=json.dumps({"function_name": "my_func"}),
        content_type="application/json"
    )
    
    assert response.status_code == 200
    assert "my_func" in server.manager.get_breakpoints()


def test_delete_breakpoint_endpoint(server) -> None:
    """Test DELETE /api/breakpoints/<name> endpoint."""
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)
    
    # Add a breakpoint first
    server.manager.add_breakpoint("my_func")
    
    # Delete it
    response = server.test_client().delete("/api/breakpoints/my_func")
    assert response.status_code == 200
    assert "my_func" not in server.manager.get_breakpoints()


def test_get_paused_executions_endpoint(server) -> None:
    """Test GET /api/paused endpoint."""
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)
    
    # Add a paused execution
    call_data = {"function_name": "add", "args": {"a": 1, "b": 2}}
    pause_id = server.manager.add_paused_execution(call_data)
    
    response = server.test_client().get("/api/paused")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data["paused"]) == 1
    assert data["paused"][0]["call_data"]["function_name"] == "add"


def test_continue_execution_endpoint(server) -> None:
    """Test POST /api/paused/<id>/continue endpoint."""
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)
    
    # Add a paused execution
    call_data = {"function_name": "add", "args": {"a": 1, "b": 2}}
    pause_id = server.manager.add_paused_execution(call_data)
    
    # Continue it
    response = server.test_client().post(
        f"/api/paused/{pause_id}/continue",
        data=json.dumps({"action": "continue"}),
        content_type="application/json"
    )
    
    assert response.status_code == 200
    assert len(server.manager.get_paused_executions()) == 0


def test_get_port_number(server) -> None:
    """Test that we can get the port number."""
    # When using port=0, Flask will assign a random port
    # The get_port() will still return 0 until the server binds
    # This is expected behavior
    port = server.get_port()
    assert port == 0  # Initial port value from fixture


def test_root_page_serves_html(server) -> None:
    """Test that the root page serves HTML UI."""
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)
    
    response = server.test_client().get("/")
    assert response.status_code == 200
    assert b"Interactive Breakpoints" in response.data
    assert b"CID el Dill" in response.data
    # Check for key UI elements
    assert b"pausedExecutions" in response.data
    assert b"breakpointsList" in response.data


def test_call_start_returns_continue_when_no_breakpoint(server) -> None:
    """Test POST /api/call/start returns continue action."""
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    serializer = Serializer()
    target = {"x": 1}
    target_payload = serializer.force_serialize_with_data(target)

    response = server.test_client().post(
        "/api/call/start",
        data=json.dumps({
            "method_name": "noop",
            "target": {"cid": target_payload.cid, "data": target_payload.data_base64},
            "args": [],
            "kwargs": {},
            "call_site": {"timestamp": 123.0},
        }),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["action"] == "continue"


def test_poll_waits_until_resume_action(server) -> None:
    """Test /api/poll waits for resume action."""
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    pause_id = server.manager.add_paused_execution({"method_name": "noop"})
    response = server.test_client().get(f"/api/poll/{pause_id}")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "waiting"

    server.manager.resume_execution(pause_id, {"action": "continue"})
    response = server.test_client().get(f"/api/poll/{pause_id}")
    data = json.loads(response.data)
    assert data["status"] == "ready"
