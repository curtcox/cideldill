"""Unit tests for DebugProxy."""

from __future__ import annotations

import pytest

pytest.importorskip("dill")

from cideldill.debug_proxy import DebugProxy


class _StubClient:
    def __init__(self, action: dict) -> None:
        self._action = action
        self.completed = []

    def record_call_start(self, **kwargs) -> dict:
        return self._action

    def record_call_complete(self, **kwargs) -> None:
        self.completed.append(kwargs)

    def poll(self, action: dict) -> dict:
        return action["resolved_action"]

    def deserialize_payload_list(self, items):
        return [item["value"] for item in items]

    def deserialize_payload_dict(self, items):
        return {key: value["value"] for key, value in items.items()}


class _Target:
    def add(self, x: int, y: int) -> int:
        return x + y

    def explode(self) -> None:
        raise ValueError("boom")


def test_debug_proxy_continue() -> None:
    client = _StubClient({"call_id": "1", "action": "continue"})
    proxy = DebugProxy(_Target(), client, lambda: True)

    assert proxy.add(1, 2) == 3
    assert client.completed[0]["status"] == "success"


def test_debug_proxy_modify_args() -> None:
    client = _StubClient({
        "call_id": "1",
        "action": "modify",
        "modified_args": [{"value": 5}, {"value": 6}],
        "modified_kwargs": {},
    })
    proxy = DebugProxy(_Target(), client, lambda: True)

    assert proxy.add(1, 2) == 11


def test_debug_proxy_skip() -> None:
    client = _StubClient({
        "call_id": "1",
        "action": "skip",
        "fake_result": 42,
    })
    proxy = DebugProxy(_Target(), client, lambda: True)

    assert proxy.add(1, 2) == 42


def test_debug_proxy_raise() -> None:
    client = _StubClient({
        "call_id": "1",
        "action": "raise",
        "exception_type": "ValueError",
        "exception_message": "forced",
    })
    proxy = DebugProxy(_Target(), client, lambda: True)

    with pytest.raises(ValueError, match="forced"):
        proxy.add(1, 2)


def test_debug_proxy_exception_reports_completion() -> None:
    client = _StubClient({"call_id": "1", "action": "continue"})
    proxy = DebugProxy(_Target(), client, lambda: True)

    with pytest.raises(ValueError, match="boom"):
        proxy.explode()
    assert client.completed[0]["status"] == "exception"
