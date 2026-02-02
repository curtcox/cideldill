"""Unit tests for DebugClient."""

from __future__ import annotations

import base64

import pytest

pytest.importorskip("dill")
pytest.importorskip("requests")

import dill

from cideldill.debug_client import DebugClient
from cideldill.serialization import Serializer


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


def test_record_call_start_resends_missing_cids(monkeypatch) -> None:
    serializer = Serializer()
    target = {"x": 1}
    target_serialized = serializer.force_serialize_with_data(target)

    responses = [
        _Response(
            400,
            {"error": "cid_not_found", "missing_cids": [target_serialized.cid]},
        ),
        _Response(200, {"call_id": "1-001", "action": "continue"}),
    ]

    def fake_post(url: str, json: dict, timeout: float) -> _Response:
        return responses.pop(0)

    monkeypatch.setattr("requests.post", fake_post)

    client = DebugClient("http://localhost:5000")
    action = client.record_call_start(
        method_name="noop",
        target=target,
        target_cid=target_serialized.cid,
        args=(),
        kwargs={},
        call_site={"timestamp": 0.0},
    )

    assert action["action"] == "continue"


def test_record_call_complete_serializes_result(monkeypatch) -> None:
    captured = {}

    def fake_post(url: str, json: dict, timeout: float) -> _Response:
        captured["payload"] = json
        return _Response(200, {"status": "ok"})

    monkeypatch.setattr("requests.post", fake_post)

    client = DebugClient("http://localhost:5000")
    client.record_call_complete(call_id="123", status="success", result={"a": 1})

    payload = captured["payload"]
    assert payload["call_id"] == "123"
    assert payload["status"] == "success"
    assert payload["result_cid"]
    assert base64.b64decode(payload["result_data"]) == dill.dumps({"a": 1}, protocol=4)
