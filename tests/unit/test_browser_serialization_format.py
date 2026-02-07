import json
import threading
import time
import hashlib

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


def _json_data_and_cid(value):
    data = json.dumps(value)
    cid = hashlib.sha512(data.encode("utf-8")).hexdigest()
    return data, cid


def _start_server(server):
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)


def test_call_start_accepts_json_serialization_format(server) -> None:
    _start_server(server)
    data, cid = _json_data_and_cid({"x": 1})

    response = server.test_client().post(
        "/api/call/start",
        data=json.dumps({
            "method_name": "add",
            "target": {
                "cid": cid,
                "data": data,
                "serialization_format": "json",
            },
            "args": [],
            "kwargs": {},
            "call_site": {"timestamp": 123.0},
            "process_pid": 4242,
            "process_start_time": 123.456,
        }),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert server._cid_store.get(cid) == data.encode("utf-8")


def test_call_start_defaults_to_dill_when_format_absent(server) -> None:
    _start_server(server)
    serializer = Serializer()
    target_payload = serializer.force_serialize_with_data({"x": 1})

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


def test_call_start_cid_dedup_works_for_json(server) -> None:
    _start_server(server)
    data, cid = _json_data_and_cid({"x": 2})

    response = server.test_client().post(
        "/api/call/start",
        data=json.dumps({
            "method_name": "add",
            "target": {"cid": cid, "data": data, "serialization_format": "json"},
            "args": [],
            "kwargs": {},
            "call_site": {"timestamp": 123.0},
            "process_pid": 4242,
            "process_start_time": 123.456,
        }),
        content_type="application/json",
    )
    assert response.status_code == 200

    response = server.test_client().post(
        "/api/call/start",
        data=json.dumps({
            "method_name": "add",
            "target": {"cid": cid, "serialization_format": "json"},
            "args": [],
            "kwargs": {},
            "call_site": {"timestamp": 124.0},
            "process_pid": 4242,
            "process_start_time": 123.456,
        }),
        content_type="application/json",
    )
    assert response.status_code == 200


def test_call_start_returns_cid_not_found_for_missing_json_data(server) -> None:
    _start_server(server)
    _, cid = _json_data_and_cid({"x": 3})

    response = server.test_client().post(
        "/api/call/start",
        data=json.dumps({
            "method_name": "add",
            "target": {"cid": cid, "serialization_format": "json"},
            "args": [],
            "kwargs": {},
            "call_site": {"timestamp": 125.0},
            "process_pid": 4242,
            "process_start_time": 123.456,
        }),
        content_type="application/json",
    )

    assert response.status_code == 400
    payload = json.loads(response.data)
    assert payload.get("error") == "cid_not_found"


def test_call_complete_accepts_json_result_data(server) -> None:
    _start_server(server)
    serializer = Serializer()
    target_payload = serializer.force_serialize_with_data({"x": 1})
    result_data, result_cid = _json_data_and_cid({"answer": 3})

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
            "result_cid": result_cid,
            "result_data": result_data,
            "result_serialization_format": "json",
        }),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert server._cid_store.get(result_cid) == result_data.encode("utf-8")


def test_call_complete_accepts_json_exception_data(server) -> None:
    _start_server(server)
    serializer = Serializer()
    target_payload = serializer.force_serialize_with_data({"x": 1})
    exc_data, exc_cid = _json_data_and_cid({"error": "boom"})

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
            "status": "exception",
            "exception_cid": exc_cid,
            "exception_data": exc_data,
            "exception_serialization_format": "json",
        }),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert server._cid_store.get(exc_cid) == exc_data.encode("utf-8")


def test_call_event_accepts_json_serialization(server) -> None:
    _start_server(server)
    result_data, result_cid = _json_data_and_cid({"event": "ok"})

    response = server.test_client().post(
        "/api/call/event",
        data=json.dumps({
            "event_id": "evt-1",
            "method_name": "event",
            "process_pid": 4242,
            "process_start_time": 123.456,
            "result_cid": result_cid,
            "result_data": result_data,
            "result_serialization_format": "json",
        }),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert server._cid_store.get(result_cid) == result_data.encode("utf-8")


def test_functions_endpoint_accepts_json_serialization(server) -> None:
    _start_server(server)
    function_data, function_cid = _json_data_and_cid({"name": "myFn"})

    response = server.test_client().post(
        "/api/functions",
        data=json.dumps({
            "function_name": "myFn",
            "function_cid": function_cid,
            "function_data": function_data,
            "function_serialization_format": "json",
        }),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert server._cid_store.get(function_cid) == function_data.encode("utf-8")
