"""Unit tests for DebugClient."""

from __future__ import annotations

import asyncio
import base64
import logging

import pytest

pytest.importorskip("dill")
pytest.importorskip("requests")

import dill

from cideldill_client.debug_client import DebugClient
from cideldill_client.serialization import Serializer


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


def test_poll_timeout_returns_poll_action(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)

    def fake_get(url: str, timeout: float) -> _Response:  # pragma: no cover
        raise AssertionError("Should not be called when timeout_ms=0")

    monkeypatch.setattr("requests.get", fake_get)

    client = DebugClient("http://localhost:5000")
    action = {
        "action": "poll",
        "poll_url": "/api/poll/abc",
        "poll_interval_ms": 1,
        "timeout_ms": 0,
    }
    result = client.poll(action)
    assert result == action
    assert "poll timed out" in caplog.text.lower()


def test_async_poll_timeout_returns_poll_action(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)

    def fake_get(url: str, timeout: float) -> _Response:  # pragma: no cover
        raise AssertionError("Should not be called when timeout_ms=0")

    monkeypatch.setattr("requests.get", fake_get)

    client = DebugClient("http://localhost:5000")
    action = {
        "action": "poll",
        "poll_url": "/api/poll/abc",
        "poll_interval_ms": 1,
        "timeout_ms": 0,
    }

    result = asyncio.run(client.async_poll(action))
    assert result == action
    assert "poll timed out" in caplog.text.lower()
