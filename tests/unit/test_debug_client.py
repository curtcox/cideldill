"""Unit tests for DebugClient."""

from __future__ import annotations

import asyncio
import base64
import logging
from contextlib import contextmanager

import pytest

pytest.importorskip("dill")
pytest.importorskip("requests")

import dill

from cideldill_client.debug_client import DebugClient
from cideldill_client.serialization import Serializer, compute_cid


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_debug_client_initializes_and_closes_deadlock_watchdog(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeWatchdog:
        def __init__(self, timeout_s: float, log_interval_s: float = 60.0) -> None:
            captured["timeout"] = timeout_s
            captured["log_interval"] = log_interval_s
            captured["closed"] = False

        @contextmanager
        def track(self, label: str):
            captured.setdefault("labels", []).append(label)
            yield

        def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr("cideldill_client.debug_client.DeadlockWatchdog", _FakeWatchdog)

    client = DebugClient(
        "http://localhost:5000",
        deadlock_watchdog_timeout_s=2.5,
        deadlock_watchdog_log_interval_s=8.0,
    )
    client.close()

    assert captured["timeout"] == 2.5
    assert captured["log_interval"] == 8.0
    assert captured["closed"] is True


def test_debug_client_rejects_negative_deadlock_watchdog_timeout() -> None:
    with pytest.raises(ValueError, match="deadlock_watchdog_timeout_s"):
        DebugClient("http://localhost:5000", deadlock_watchdog_timeout_s=-1.0)


def test_debug_client_rejects_nonpositive_deadlock_watchdog_log_interval() -> None:
    with pytest.raises(ValueError, match="deadlock_watchdog_log_interval_s"):
        DebugClient(
            "http://localhost:5000",
            deadlock_watchdog_timeout_s=1.0,
            deadlock_watchdog_log_interval_s=0.0,
        )


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
        call_type="proxy",
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


def test_poll_logs_suspended_breakpoints_for_long_running_poll(monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING)
    clock = _FakeClock()

    def fake_get_json(self, path: str) -> dict:
        if path == "/api/poll/abc":
            return {"status": "waiting"}
        if path == "/api/poll-repl/abc":
            return {"eval_id": None}
        raise AssertionError(f"Unexpected path: {path}")

    def fake_get(url: str, timeout: float) -> _Response:
        if url.endswith("/api/paused"):
            return _Response(
                200,
                {
                    "paused": [
                        {
                            "id": "pause-1",
                            "paused_at": clock.time() - 12.0,
                            "call_data": {"method_name": "workflow:step_one"},
                        },
                    ],
                },
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._get_json",
        fake_get_json,
        raising=False,
    )
    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("cideldill_client.debug_client.time.time", clock.time)
    monkeypatch.setattr("cideldill_client.debug_client.time.sleep", clock.sleep)

    client = DebugClient(
        "http://localhost:5000",
        suspended_breakpoints_log_interval_s=0.15,
    )
    action = {
        "action": "poll",
        "poll_url": "/api/poll/abc",
        "poll_interval_ms": 100,
        "timeout_ms": 350,
    }

    result = client.poll(action)
    assert result == action
    assert "long-running suspended breakpoint poll" in caplog.text.lower()
    assert "workflow:step_one" in caplog.text


def test_poll_logs_all_visible_suspended_breakpoints(monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING)
    clock = _FakeClock()

    def fake_get_json(self, path: str) -> dict:
        if path == "/api/poll/abc":
            return {"status": "waiting"}
        if path == "/api/poll-repl/abc":
            return {"eval_id": None}
        raise AssertionError(f"Unexpected path: {path}")

    def fake_get(url: str, timeout: float) -> _Response:
        if url.endswith("/api/paused"):
            return _Response(
                200,
                {
                    "paused": [
                        {
                            "id": "pause-1",
                            "paused_at": clock.time() - 12.0,
                            "call_data": {"method_name": "workflow:step_one"},
                        },
                        {
                            "id": "pause-2",
                            "paused_at": clock.time() - 7.0,
                            "call_data": {"method_name": "workflow:step_two"},
                        },
                    ],
                },
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._get_json",
        fake_get_json,
        raising=False,
    )
    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("cideldill_client.debug_client.time.time", clock.time)
    monkeypatch.setattr("cideldill_client.debug_client.time.sleep", clock.sleep)

    client = DebugClient(
        "http://localhost:5000",
        suspended_breakpoints_log_interval_s=0.15,
    )
    action = {
        "action": "poll",
        "poll_url": "/api/poll/abc",
        "poll_interval_ms": 100,
        "timeout_ms": 350,
    }

    result = client.poll(action)
    assert result == action
    assert "suspended breakpoints on server (2)" in caplog.text.lower()
    assert "workflow:step_one" in caplog.text
    assert "workflow:step_two" in caplog.text


def test_poll_uses_function_name_when_method_name_missing(monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING)
    clock = _FakeClock()

    def fake_get_json(self, path: str) -> dict:
        if path == "/api/poll/abc":
            return {"status": "waiting"}
        if path == "/api/poll-repl/abc":
            return {"eval_id": None}
        raise AssertionError(f"Unexpected path: {path}")

    def fake_get(url: str, timeout: float) -> _Response:
        if url.endswith("/api/paused"):
            return _Response(
                200,
                {
                    "paused": [
                        {
                            "id": "pause-1",
                            "paused_at": clock.time() - 12.0,
                            "call_data": {"function_name": "workflow:legacy_step"},
                        },
                    ],
                },
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._get_json",
        fake_get_json,
        raising=False,
    )
    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("cideldill_client.debug_client.time.time", clock.time)
    monkeypatch.setattr("cideldill_client.debug_client.time.sleep", clock.sleep)

    client = DebugClient(
        "http://localhost:5000",
        suspended_breakpoints_log_interval_s=0.15,
    )
    action = {
        "action": "poll",
        "poll_url": "/api/poll/abc",
        "poll_interval_ms": 100,
        "timeout_ms": 350,
    }

    result = client.poll(action)
    assert result == action
    assert "workflow:legacy_step" in caplog.text


def test_poll_logs_when_no_suspended_breakpoints_are_visible(monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING)
    clock = _FakeClock()

    def fake_get_json(self, path: str) -> dict:
        if path == "/api/poll/abc":
            return {"status": "waiting"}
        if path == "/api/poll-repl/abc":
            return {"eval_id": None}
        raise AssertionError(f"Unexpected path: {path}")

    def fake_get(url: str, timeout: float) -> _Response:
        if url.endswith("/api/paused"):
            return _Response(200, {"paused": []})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._get_json",
        fake_get_json,
        raising=False,
    )
    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("cideldill_client.debug_client.time.time", clock.time)
    monkeypatch.setattr("cideldill_client.debug_client.time.sleep", clock.sleep)

    client = DebugClient(
        "http://localhost:5000",
        suspended_breakpoints_log_interval_s=0.15,
    )
    action = {
        "action": "poll",
        "poll_url": "/api/poll/abc",
        "poll_interval_ms": 100,
        "timeout_ms": 350,
    }

    result = client.poll(action)
    assert result == action
    assert "no suspended breakpoints are visible on the server" in caplog.text.lower()


def test_async_poll_logs_when_no_suspended_breakpoints_are_visible(monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING)
    clock = _FakeClock()

    def fake_get_json(self, path: str) -> dict:
        if path == "/api/poll/abc":
            return {"status": "waiting"}
        if path == "/api/poll-repl/abc":
            return {"eval_id": None}
        raise AssertionError(f"Unexpected path: {path}")

    def fake_get(url: str, timeout: float) -> _Response:
        if url.endswith("/api/paused"):
            return _Response(200, {"paused": []})
        raise AssertionError(f"Unexpected URL: {url}")

    async def fake_sleep(seconds: float) -> None:
        clock.sleep(seconds)

    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._get_json",
        fake_get_json,
        raising=False,
    )
    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("cideldill_client.debug_client.time.time", clock.time)
    monkeypatch.setattr("cideldill_client.debug_client.asyncio.sleep", fake_sleep)

    client = DebugClient(
        "http://localhost:5000",
        suspended_breakpoints_log_interval_s=0.15,
    )
    action = {
        "action": "poll",
        "poll_url": "/api/poll/abc",
        "poll_interval_ms": 100,
        "timeout_ms": 350,
    }

    result = asyncio.run(client.async_poll(action))
    assert result == action
    assert "no suspended breakpoints are visible on the server" in caplog.text.lower()


def test_record_call_start_includes_stable_client_refs(monkeypatch) -> None:
    captured: list[dict] = []

    def fake_post(self, path: str, payload: dict) -> dict:
        captured.append(payload)
        return {"call_id": "1-001", "action": "continue"}

    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._post_json_allowing_cid_errors",
        fake_post,
    )

    client = DebugClient("http://localhost:5000")
    target = {"x": 1}
    mutable = ["alpha"]
    target_cid = compute_cid(target)

    client.record_call_start(
        method_name="noop",
        target=target,
        target_cid=target_cid,
        args=(mutable,),
        kwargs={"same": mutable},
        call_site={"timestamp": 0.0},
        call_type="proxy",
    )

    mutable.append("beta")
    client.record_call_start(
        method_name="noop",
        target=target,
        target_cid=target_cid,
        args=(mutable,),
        kwargs={"same": mutable},
        call_site={"timestamp": 1.0},
        call_type="proxy",
    )

    payload1, payload2 = captured
    ref1 = payload1["args"][0]["client_ref"]
    ref2 = payload2["args"][0]["client_ref"]

    assert ref1 == ref2
    assert payload1["kwargs"]["same"]["client_ref"] == ref1
    assert payload2["kwargs"]["same"]["client_ref"] == ref2
    assert payload1["target"]["client_ref"] != ref1


def test_record_call_start_includes_call_type_in_payload(monkeypatch) -> None:
    captured: list[dict] = []

    def fake_post(self, path: str, payload: dict) -> dict:
        captured.append(payload)
        return {"call_id": "1-001", "action": "continue"}

    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._post_json_allowing_cid_errors",
        fake_post,
    )

    client = DebugClient("http://localhost:5000")
    target = {"x": 1}
    target_cid = compute_cid(target)

    client.record_call_start(
        method_name="noop",
        target=target,
        target_cid=target_cid,
        args=(),
        kwargs={},
        call_site={"timestamp": 0.0},
        call_type="proxy",
    )

    assert captured[0]["call_type"] == "proxy"

    client.record_call_start(
        method_name="noop",
        target=target,
        target_cid=target_cid,
        args=(),
        kwargs={},
        call_site={"timestamp": 0.0},
        call_type="inline",
    )

    assert captured[1]["call_type"] == "inline"


def test_record_call_start_requires_call_type() -> None:
    client = DebugClient("http://localhost:5000")
    with pytest.raises(TypeError):
        client.record_call_start(
            method_name="noop",
            target={},
            target_cid="abc",
            args=(),
            kwargs={},
            call_site={"timestamp": 0.0},
        )
