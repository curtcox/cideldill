"""Unit tests for Breakpoint Web Server.

This test suite validates the web server API endpoints for breakpoint management.
"""

import json
import re
import threading
import time

import pytest

pytest.importorskip("dill")

from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer
from cideldill_server.serialization import Serializer
from cideldill_server.serialization_common import UnpicklablePlaceholder


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
    assert data["breakpoint_behaviors"]["func1"] == "yield"
    assert data["breakpoint_behaviors"]["func2"] == "yield"


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


def test_register_function_includes_placeholder_metadata(server) -> None:
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    placeholder = UnpicklablePlaceholder(
        type_name="ConfiguredFunction",
        module="nat.builder.workflow_builder",
        qualname="ConfiguredFunction",
        object_id="0x1",
        repr_text="<ConfiguredFunction>",
        str_text=None,
        attributes={},
        failed_attributes={},
        pickle_error="TypeError: not picklable",
        pickle_attempts=["dill.dumps: TypeError"],
        capture_timestamp=0.0,
        depth=0,
        object_name="asset_tool",
        object_path="nat.builder.workflow_builder.ConfiguredFunction",
    )
    serializer = Serializer()
    serialized = serializer.force_serialize_with_data(placeholder)

    response = server.test_client().post(
        "/api/functions",
        data=json.dumps({
            "function_name": "asset_tool",
            "function_cid": serialized.cid,
            "function_data": serialized.data_base64,
        }),
        content_type="application/json",
    )

    assert response.status_code == 200

    response = server.test_client().get("/api/functions")
    assert response.status_code == 200
    data = json.loads(response.data)
    metadata = data["function_metadata"]["asset_tool"]
    assert metadata["__cideldill_placeholder__"] is True
    assert metadata["object_name"] == "asset_tool"


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


def test_call_start_tracks_client_ref_state(server) -> None:
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    serializer = Serializer()
    mutable = ["alpha"]

    def make_item(obj, client_ref):
        serialized = serializer.force_serialize_with_data(obj)
        return {
            "cid": serialized.cid,
            "data": serialized.data_base64,
            "client_ref": client_ref,
        }

    process_pid = 4242
    process_start_time = 123.456
    process_key = f"{process_start_time:.6f}+{process_pid}"

    payload1 = {
        "method_name": "noop",
        "target_cid": "t1",
        "target": make_item({"target": True}, client_ref=1),
        "args": [make_item(mutable, client_ref=99)],
        "kwargs": {},
        "call_site": {"timestamp": 0.0},
        "process_pid": process_pid,
        "process_start_time": process_start_time,
    }
    response1 = server.test_client().post(
        "/api/call/start",
        data=json.dumps(payload1),
        content_type="application/json",
    )
    assert response1.status_code == 200

    mutable.append("beta")
    payload2 = {
        "method_name": "noop",
        "target_cid": "t2",
        "target": make_item({"target": True}, client_ref=1),
        "args": [make_item(mutable, client_ref=99)],
        "kwargs": {},
        "call_site": {"timestamp": 1.0},
        "process_pid": process_pid,
        "process_start_time": process_start_time,
    }
    response2 = server.test_client().post(
        "/api/call/start",
        data=json.dumps(payload2),
        content_type="application/json",
    )
    assert response2.status_code == 200

    history = server.manager.get_object_history(process_key, 99)
    assert len(history) == 2
    assert history[0]["pretty"] == "['alpha']"
    assert history[1]["pretty"] == "['alpha', 'beta']"


def test_call_start_tracks_client_ref_for_placeholder(server) -> None:
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    placeholder = UnpicklablePlaceholder(
        type_name="ConfiguredFunction",
        module="nat.builder.workflow_builder",
        qualname="ConfiguredFunction",
        object_id="0x2",
        repr_text="<ConfiguredFunction>",
        str_text=None,
        attributes={},
        failed_attributes={},
        pickle_error="TypeError: not picklable",
        pickle_attempts=["dill.dumps: TypeError"],
        capture_timestamp=0.0,
        depth=0,
        object_name="asset_tool",
        object_path="nat.builder.workflow_builder.ConfiguredFunction",
    )
    serializer = Serializer()
    serialized = serializer.force_serialize_with_data(placeholder)

    process_pid = 1337
    process_start_time = 555.0
    process_key = f"{process_start_time:.6f}+{process_pid}"

    payload = {
        "method_name": "noop",
        "target_cid": "t1",
        "target": {
            "cid": serialized.cid,
            "data": serialized.data_base64,
            "client_ref": 777,
        },
        "args": [],
        "kwargs": {},
        "call_site": {"timestamp": 0.0},
        "process_pid": process_pid,
        "process_start_time": process_start_time,
    }

    response = server.test_client().post(
        "/api/call/start",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200

    history = server.manager.get_object_history(process_key, 777)
    assert len(history) == 1
    assert history[0]["pretty"]["__cideldill_placeholder__"] is True


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


def test_continue_execution_can_replace_function(server) -> None:
    """Test POST /api/paused/<id>/continue supports replacement function."""
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    pause_id = server.manager.add_paused_execution({"method_name": "add"})

    response = server.test_client().post(
        f"/api/paused/{pause_id}/continue",
        data=json.dumps({
            "action": "continue",
            "replacement_function": "multiply",
        }),
        content_type="application/json",
    )

    assert response.status_code == 200
    action = server.manager.get_resume_action(pause_id)
    assert action["action"] == "replace"
    assert action["function_name"] == "multiply"


def test_call_start_replaces_when_breakpoint_go_and_replacement_set(server) -> None:
    """If breakpoint doesn't pause and has replacement, server should replace."""
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    serializer = Serializer()
    target_payload = serializer.force_serialize_with_data({"x": 1})

    server.manager.add_breakpoint("add")
    server.manager.set_default_behavior("go")
    server.manager.set_breakpoint_replacement("add", "multiply")

    response = server.test_client().post(
        "/api/call/start",
        data=json.dumps({
            "method_name": "add",
            "target": {"cid": target_payload.cid, "data": target_payload.data_base64},
            "args": [],
            "kwargs": {},
            "call_site": {"timestamp": 123.0},
            "process_pid": 4242,
            "process_start_time": 123.456,
        }),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["action"] == "replace"
    assert data["function_name"] == "multiply"


def test_call_complete_pauses_when_after_breakpoint_set(server) -> None:
    """If after-breakpoint pauses, call completion should return poll action."""
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    serializer = Serializer()
    target_payload = serializer.force_serialize_with_data({"x": 1})
    result_payload = serializer.force_serialize_with_data(3)

    server.manager.add_breakpoint("add")
    server.manager.set_default_behavior("go")
    server.manager.set_after_breakpoint_behavior("add", "stop")

    response = server.test_client().post(
        "/api/call/start",
        data=json.dumps({
            "method_name": "add",
            "target": {"cid": target_payload.cid, "data": target_payload.data_base64},
            "args": [],
            "kwargs": {},
            "call_site": {"timestamp": 123.0},
            "process_pid": 4242,
            "process_start_time": 123.456,
        }),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    call_id = data["call_id"]

    response = server.test_client().post(
        "/api/call/complete",
        data=json.dumps({
            "call_id": call_id,
            "status": "success",
            "result_cid": result_payload.cid,
            "result_data": result_payload.data_base64,
        }),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["action"] == "poll"

    paused = server.manager.get_paused_executions()
    assert len(paused) == 1
    assert paused[0]["call_data"]["method_name"] == "add"
    assert paused[0]["call_data"]["pretty_result"] == "3"


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
    assert b"selectedReplacements" in response.data
    assert b"breakpoint-replacement-select" in response.data
    assert b"isBreakpointSelectActive" in response.data
    assert b"sortBreakpoints" in response.data


def test_report_com_error_endpoint(server) -> None:
    """Test POST /api/report-com-error and /api/com-errors."""
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    payload = {
        "summary": "timeout",
        "method": "POST",
        "path": "/api/call/start",
        "timestamp": 123.0,
        "exception_type": "Timeout",
        "exception_message": "request timed out",
    }

    response = server.test_client().post(
        "/api/report-com-error",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200

    errors = server.manager.get_com_errors()
    assert errors
    assert errors[-1]["summary"] == "timeout"

    response = server.test_client().get("/api/com-errors")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["errors"][0]["summary"] == "timeout"

    response = server.test_client().get("/com-errors")
    assert response.status_code == 200
    assert b"Communication Errors" in response.data


def test_objects_page_lists_refs_and_cids(server) -> None:
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    serializer = Serializer()
    target_payload = serializer.force_serialize_with_data({"target": True})
    arg_payload = serializer.force_serialize_with_data(["alpha"])

    process_pid = 8080
    process_start_time = 111.222
    process_key = f"{process_start_time:.6f}+{process_pid}"

    response = server.test_client().post(
        "/api/call/start",
        data=json.dumps({
            "method_name": "noop",
            "target_cid": "t1",
            "target": {
                "cid": target_payload.cid,
                "data": target_payload.data_base64,
                "client_ref": 1,
            },
            "args": [{
                "cid": arg_payload.cid,
                "data": arg_payload.data_base64,
                "client_ref": 99,
            }],
            "kwargs": {},
            "call_site": {"timestamp": 0.0},
            "process_pid": process_pid,
            "process_start_time": process_start_time,
        }),
        content_type="application/json",
    )
    assert response.status_code == 200

    response = server.test_client().get("/objects")
    assert response.status_code == 200
    body = response.data.decode()
    assert arg_payload.cid in body
    assert f"ref:{process_key}:99" in body


def test_object_pages_show_backrefs_and_snapshots(server) -> None:
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    serializer = Serializer()
    arg_payload = serializer.force_serialize_with_data(["alpha"])

    process_pid = 9090
    process_start_time = 222.333
    process_key = f"{process_start_time:.6f}+{process_pid}"

    response = server.test_client().post(
        "/api/call/start",
        data=json.dumps({
            "method_name": "noop",
            "target_cid": "t1",
            "target": {
                "cid": arg_payload.cid,
                "data": arg_payload.data_base64,
                "client_ref": 7,
            },
            "args": [{
                "cid": arg_payload.cid,
                "data": arg_payload.data_base64,
                "client_ref": 7,
            }],
            "kwargs": {},
            "call_site": {"timestamp": 0.0},
            "process_pid": process_pid,
            "process_start_time": process_start_time,
        }),
        content_type="application/json",
    )
    assert response.status_code == 200

    ref = f"ref:{process_key}:7"
    response = server.test_client().get(f"/object/{ref}")
    assert response.status_code == 200
    body = response.data.decode()
    assert arg_payload.cid in body

    response = server.test_client().get(f"/object/{arg_payload.cid}")
    assert response.status_code == 200
    body = response.data.decode()
    assert ref in body


def test_register_function_tracks_client_ref(server) -> None:
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    response = server.test_client().post(
        "/api/functions",
        data=json.dumps({
            "function_name": "asset_tool",
            "function_client_ref": 42,
        }),
        content_type="application/json",
    )
    assert response.status_code == 200

    response = server.test_client().get("/api/functions")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["function_metadata"]["asset_tool"]["client_ref"] == 42


def test_call_tree_links_registered_target_ref(server) -> None:
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    response = server.test_client().post(
        "/api/functions",
        data=json.dumps({
            "function_name": "demo_func",
            "function_client_ref": 17,
        }),
        content_type="application/json",
    )
    assert response.status_code == 200

    process_pid = 5555
    process_start_time = 333.444
    process_key = f"{process_start_time:.6f}+{process_pid}"

    response = server.test_client().post(
        "/api/call/event",
        data=json.dumps({
            "method_name": "with_debug.register",
            "status": "registered",
            "call_site": {"timestamp": 0.0},
            "process_pid": process_pid,
            "process_start_time": process_start_time,
            "pretty_result": {
                "event": "with_debug_registration",
                "function_name": "demo_func",
            },
        }),
        content_type="application/json",
    )
    assert response.status_code == 200

    response = server.test_client().get(f"/call-tree/{process_key}")
    assert response.status_code == 200
    body = response.data.decode()
    assert "registered_target_ref" in body
    assert f"ref:{process_key}:17" in body


def test_frame_endpoint_renders_source_for_paused_execution(server) -> None:
    """Test GET /frame/<pause_id>/<frame_index> endpoint."""
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    pause_id = server.manager.add_paused_execution({
        "method_name": "noop",
        "call_site": {
            "stack_trace": [
                {
                    "filename": __file__,
                    "lineno": 1,
                    "function": "test_frame_endpoint_renders_source_for_paused_execution",
                    "code_context": "def test_frame_endpoint_renders_source_for_paused_execution(server) -> None:",
                }
            ]
        },
    })

    response = server.test_client().get(f"/frame/{pause_id}/0")
    assert response.status_code == 200
    assert b"<html" in response.data.lower()
    assert b"test_breakpoint_server.py" in response.data


def test_frame_endpoint_returns_404_when_pause_missing(server) -> None:
    """Test /frame returns 404 when pause id is unknown."""
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    response = server.test_client().get("/frame/not-a-real-pause/0")
    assert response.status_code == 404


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
            "process_pid": 4242,
            "process_start_time": 123.456,
        }),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["action"] == "continue"


def test_call_tree_builds_from_outer_to_inner_stack_traces(server) -> None:
    """Call tree should nest nodes when stack traces are outer-to-inner ordered."""
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    process_key = "process-1"
    process_pid = 123
    process_start_time = 1000.0

    def frame(filename: str, lineno: int, function: str) -> dict[str, object]:
        return {"filename": filename, "lineno": lineno, "function": function}

    stack_root = [
        frame("app.py", 1, "<module>"),
        frame("app.py", 10, "main"),
    ]
    stack_child = stack_root + [frame("app.py", 20, "run_a")]
    stack_grandchild = stack_child + [frame("app.py", 30, "run_b")]

    def record(call_id: str, method_name: str, stack_trace: list[dict[str, object]], ts: float) -> dict[str, object]:
        return {
            "call_id": call_id,
            "method_name": method_name,
            "status": "success",
            "pretty_args": [],
            "pretty_kwargs": {},
            "signature": None,
            "call_site": {"timestamp": ts, "stack_trace": stack_trace},
            "process_pid": process_pid,
            "process_start_time": process_start_time,
            "process_key": process_key,
            "started_at": ts,
            "completed_at": ts + 0.05,
        }

    server.manager.record_call(record("call-a", "run_a", stack_root, 1.0))
    server.manager.record_call(record("call-b", "run_b", stack_child, 2.0))
    server.manager.record_call(record("call-c", "run_c", stack_grandchild, 3.0))

    response = server.test_client().get(f"/call-tree/{process_key}")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    match = re.search(r"const data = ({.*?});", html, re.S)
    assert match, "Expected call tree data to be embedded in HTML."
    payload = json.loads(match.group(1))

    assert payload["roots"] == ["call-a"]
    assert payload["children"]["call-a"] == ["call-b"]
    assert payload["children"]["call-b"] == ["call-c"]


def test_call_tree_renders_pretty_args_when_args_missing(server) -> None:
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    process_pid = 2468
    process_start_time = 2000.0
    process_key = f"{process_start_time:.6f}+{process_pid}"

    record = {
        "call_id": "call-1",
        "method_name": "with_debug.register",
        "status": "registered",
        "pretty_args": [
            {"__cideldill_placeholder__": True, "summary": "asset_tool", "client_ref": 17}
        ],
        "pretty_kwargs": {},
        "signature": None,
        "call_site": {"timestamp": 1.0, "stack_trace": []},
        "process_pid": process_pid,
        "process_start_time": process_start_time,
        "process_key": process_key,
        "started_at": 1.0,
        "completed_at": 1.0,
    }
    server.manager.record_call(record)

    response = server.test_client().get(f"/call-tree/{process_key}")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    match = re.search(r"const data = ({.*?});", html, re.S)
    assert match, "Expected call tree data to be embedded in HTML."
    payload = json.loads(match.group(1))
    assert payload["nodes"][0]["pretty_args"][0]["summary"] == "asset_tool"
    assert payload["nodes"][0]["args"] == []
    assert "argsSource = argsItems.length ? argsItems : prettyArgs" in html
    assert "kwargsSource = kwargsEntries.length ? kwargsEntries : Object.entries(prettyKwargs)" in html


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
