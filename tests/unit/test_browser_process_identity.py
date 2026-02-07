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


def test_call_start_stores_page_url(server) -> None:
    _start_server(server)
    server.manager.add_breakpoint("add")
    server.manager.set_default_behavior("stop")

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
            "process_pid": 0,
            "process_start_time": 123.456,
            "page_url": "https://example.com/app",
        }),
        content_type="application/json",
    )

    assert response.status_code == 200
    paused = server.manager.get_paused_executions()
    assert paused
    assert paused[0]["call_data"]["page_url"] == "https://example.com/app"


def test_call_event_stores_page_url(server) -> None:
    _start_server(server)

    response = server.test_client().post(
        "/api/call/event",
        data=json.dumps({
            "event_id": "evt-1",
            "method_name": "event",
            "process_pid": 0,
            "process_start_time": 123.456,
            "page_url": "https://example.com/event",
        }),
        content_type="application/json",
    )

    assert response.status_code == 200
    records = server.manager.get_call_records()
    assert records
    assert records[-1]["page_url"] == "https://example.com/event"
