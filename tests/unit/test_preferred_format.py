import base64
import json
import threading
import time
import hashlib

import pytest

from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer
from cideldill_server.serialization import Serializer, deserialize


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


def _pause_id_from_poll_url(poll_url: str) -> str:
    return poll_url.rsplit("/", 1)[-1]


def _start_paused_call(server, *, preferred_format=None):
    _start_server(server)
    server.manager.add_breakpoint("add")
    server.manager.set_default_behavior("stop")

    serializer = Serializer()
    target_payload = serializer.force_serialize_with_data({"x": 1})
    payload = {
        "method_name": "add",
        "target": {"cid": target_payload.cid, "data": target_payload.data_base64},
        "args": [],
        "kwargs": {},
        "call_site": {"timestamp": 123.0},
        "process_pid": 4242,
        "process_start_time": 123.456,
    }
    if preferred_format is not None:
        payload["preferred_format"] = preferred_format

    response = server.test_client().post(
        "/api/call/start",
        data=json.dumps(payload),
        content_type="application/json",
    )
    data = json.loads(response.data)
    pause_id = _pause_id_from_poll_url(data["poll_url"])
    return pause_id


def test_call_start_stores_preferred_format(server) -> None:
    pause_id = _start_paused_call(server, preferred_format="json")
    paused = server.manager.get_paused_execution(pause_id)
    assert paused is not None
    assert paused["call_data"]["preferred_format"] == "json"


def test_modify_action_uses_json_preferred_format(server) -> None:
    pause_id = _start_paused_call(server, preferred_format="json")

    response = server.test_client().post(
        f"/api/paused/{pause_id}/continue",
        data=json.dumps({
            "action": "modify",
            "modified_args": [1, {"x": 2}],
        }),
        content_type="application/json",
    )
    assert response.status_code == 200

    poll = server.test_client().get(f"/api/poll/{pause_id}")
    payload = json.loads(poll.data)
    action = payload["action"]

    assert action["action"] == "modify"
    args = action["modified_args"]
    assert args[0]["serialization_format"] == "json"
    assert args[1]["serialization_format"] == "json"
    assert json.loads(args[0]["data"]) == 1
    assert json.loads(args[1]["data"]) == {"x": 2}

    expected_cid = hashlib.sha512(args[0]["data"].encode("utf-8")).hexdigest()
    assert args[0]["cid"] == expected_cid


def test_modify_action_defaults_to_dill(server) -> None:
    pause_id = _start_paused_call(server)

    response = server.test_client().post(
        f"/api/paused/{pause_id}/continue",
        data=json.dumps({
            "action": "modify",
            "modified_args": ["hello"],
        }),
        content_type="application/json",
    )
    assert response.status_code == 200

    poll = server.test_client().get(f"/api/poll/{pause_id}")
    payload = json.loads(poll.data)
    action = payload["action"]

    item = action["modified_args"][0]
    assert item["serialization_format"] == "dill"
    decoded = base64.b64decode(item["data"])
    assert deserialize(decoded) == "hello"


def test_skip_action_uses_preferred_format(server) -> None:
    pause_id = _start_paused_call(server, preferred_format="json")

    response = server.test_client().post(
        f"/api/paused/{pause_id}/continue",
        data=json.dumps({
            "action": "skip",
            "fake_result": {"ok": True},
        }),
        content_type="application/json",
    )
    assert response.status_code == 200

    poll = server.test_client().get(f"/api/poll/{pause_id}")
    payload = json.loads(poll.data)
    action = payload["action"]

    assert action["action"] == "skip"
    assert action["fake_result_serialization_format"] == "json"
    assert json.loads(action["fake_result_data"]) == {"ok": True}
