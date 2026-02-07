import json
import threading
import time

import pytest

from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer
from cideldill_server.serialization import Serializer


@pytest.fixture
def server():
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=0)
    yield server
    server.stop()


def _start_server(server):
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)


def test_call_start_returns_cid_mismatch_error(server) -> None:
    _start_server(server)
    serializer = Serializer()
    target_payload = serializer.force_serialize_with_data({"x": 1})

    response = server.test_client().post(
        "/api/call/start",
        data=json.dumps({
            "method_name": "add",
            "target": {"cid": "0" * 128, "data": target_payload.data_base64},
            "args": [],
            "kwargs": {},
            "call_site": {"timestamp": 123.0},
            "process_pid": 4242,
            "process_start_time": 123.456,
        }),
        content_type="application/json",
    )

    assert response.status_code == 400
    payload = json.loads(response.data)
    assert payload.get("error") == "cid_mismatch"
    assert payload.get("provided_cid") == "0" * 128
    assert payload.get("expected_cid")


def test_call_complete_returns_cid_mismatch_error(server) -> None:
    _start_server(server)
    serializer = Serializer()
    target_payload = serializer.force_serialize_with_data({"x": 1})
    result_payload = serializer.force_serialize_with_data(3)

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
    call_id = json.loads(response.data)["call_id"]

    response = server.test_client().post(
        "/api/call/complete",
        data=json.dumps({
            "call_id": call_id,
            "status": "success",
            "result_cid": "0" * 128,
            "result_data": result_payload.data_base64,
        }),
        content_type="application/json",
    )

    assert response.status_code == 400
    payload = json.loads(response.data)
    assert payload.get("error") == "cid_mismatch"
    assert payload.get("provided_cid") == "0" * 128
    assert payload.get("expected_cid")
