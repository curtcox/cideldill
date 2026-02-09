"""Unit tests for REPL API endpoints."""

import hashlib
import json
import threading
import time

import pytest

from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer


@pytest.fixture
def server():
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=0, repl_eval_timeout_s=1.0)
    yield server
    server.stop()


def _pause_call_data(pid: int = 5555) -> dict[str, object]:
    return {
        "method_name": "demo",
        "call_id": "call-1",
        "call_site": {"stack_trace": []},
        "process_pid": pid,
        "process_start_time": 10.0,
        "process_key": f"10.000000+{pid}",
    }


def test_post_repl_start_creates_session(server) -> None:
    pause_id = server.manager.add_paused_execution(_pause_call_data())

    response = server.test_client().post(
        "/api/repl/start",
        data=json.dumps({"pause_id": pause_id}),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = json.loads(response.data)
    assert "session_id" in payload


def test_poll_repl_returns_pending_eval_request(server) -> None:
    pause_id = server.manager.add_paused_execution(_pause_call_data())
    session_id = server.manager.start_repl_session(pause_id)

    eval_response = {}

    def _post_eval() -> None:
        nonlocal eval_response
        resp = server.test_client().post(
            f"/api/repl/{session_id}/eval",
            data=json.dumps({"expr": "1 + 1"}),
            content_type="application/json",
        )
        eval_response = {"status": resp.status_code, "data": json.loads(resp.data)}

    thread = threading.Thread(target=_post_eval)
    thread.start()
    time.sleep(0.1)

    poll = server.test_client().get(f"/api/poll-repl/{pause_id}")
    assert poll.status_code == 200
    poll_payload = json.loads(poll.data)
    assert poll_payload["eval_id"] is not None
    assert poll_payload["session_id"] == session_id
    assert poll_payload["expr"] == "1 + 1"

    result_payload = {
        "eval_id": poll_payload["eval_id"],
        "pause_id": pause_id,
        "session_id": session_id,
        "result": "2",
        "stdout": "",
        "error": None,
        "result_cid": None,
        "result_data": None,
    }
    result = server.test_client().post(
        "/api/call/repl-result",
        data=json.dumps(result_payload),
        content_type="application/json",
    )
    assert result.status_code == 200

    thread.join(timeout=1.0)
    assert eval_response["status"] == 200
    assert eval_response["data"]["output"] == "2"
    assert eval_response["data"]["is_error"] is False


def test_repl_result_accepts_json_payload(server) -> None:
    pause_id = server.manager.add_paused_execution(_pause_call_data())
    session_id = server.manager.start_repl_session(pause_id)

    eval_response = {}

    def _post_eval() -> None:
        nonlocal eval_response
        resp = server.test_client().post(
            f"/api/repl/{session_id}/eval",
            data=json.dumps({"expr": "1 + 1"}),
            content_type="application/json",
        )
        eval_response = {"status": resp.status_code, "data": json.loads(resp.data)}

    thread = threading.Thread(target=_post_eval)
    thread.start()
    time.sleep(0.1)

    poll = server.test_client().get(f"/api/poll-repl/{pause_id}")
    poll_payload = json.loads(poll.data)

    result_data = json.dumps(3)
    result_cid = hashlib.sha512(result_data.encode("utf-8")).hexdigest()
    result_payload = {
        "eval_id": poll_payload["eval_id"],
        "pause_id": pause_id,
        "session_id": session_id,
        "result_cid": result_cid,
        "result_data": result_data,
        "result_serialization_format": "json",
    }
    result = server.test_client().post(
        "/api/call/repl-result",
        data=json.dumps(result_payload),
        content_type="application/json",
    )
    assert result.status_code == 200

    thread.join(timeout=1.0)
    assert eval_response["status"] == 200
    assert eval_response["data"]["output"] == "3"
    assert eval_response["data"]["is_error"] is False


def test_poll_repl_returns_null_when_no_requests(server) -> None:
    pause_id = server.manager.add_paused_execution(_pause_call_data())

    response = server.test_client().get(f"/api/poll-repl/{pause_id}")
    assert response.status_code == 200
    payload = json.loads(response.data)
    assert payload["eval_id"] is None


def test_repl_eval_timeout_returns_504(server) -> None:
    pause_id = server.manager.add_paused_execution(_pause_call_data())
    session_id = server.manager.start_repl_session(pause_id)

    response = server.test_client().post(
        f"/api/repl/{session_id}/eval",
        data=json.dumps({"expr": "1 + 1"}),
        content_type="application/json",
    )

    assert response.status_code == 504


def test_poll_repl_response_includes_pause_id(server) -> None:
    """The poll-repl response must include pause_id so the JS client can
    include it when posting results to /api/call/repl-result."""
    pause_id = server.manager.add_paused_execution(_pause_call_data())
    session_id = server.manager.start_repl_session(pause_id)

    # Queue an eval request (in a background thread since it blocks)
    def _post_eval() -> None:
        server.test_client().post(
            f"/api/repl/{session_id}/eval",
            data=json.dumps({"expr": "x + 1"}),
            content_type="application/json",
        )

    thread = threading.Thread(target=_post_eval)
    thread.start()
    time.sleep(0.1)

    poll = server.test_client().get(f"/api/poll-repl/{pause_id}")
    assert poll.status_code == 200
    poll_payload = json.loads(poll.data)
    assert poll_payload["eval_id"] is not None
    assert poll_payload["pause_id"] == pause_id

    # Clean up: post a result so the eval thread unblocks
    server.test_client().post(
        "/api/call/repl-result",
        data=json.dumps({
            "eval_id": poll_payload["eval_id"],
            "pause_id": pause_id,
            "session_id": session_id,
            "result": "42",
        }),
        content_type="application/json",
    )
    thread.join(timeout=2.0)
