import pytest

pytest.importorskip("dill")
pytest.importorskip("requests")

from cideldill_client.custom_picklers import UnpicklablePlaceholder
from cideldill_client.debug_client import DebugClient
from cideldill_client.serialization import set_serialization_error_reporter


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class ExplodingState:
    def __getstate__(self):
        raise TypeError("no state for you")


class UnpicklableContainer:
    def __init__(self):
        self.ok = 123
        self.bad = ExplodingState()

    def __getstate__(self):
        raise TypeError("container boom")


def test_debug_client_payload_includes_placeholder_for_unpicklable_arg():
    client = DebugClient("http://example.test")
    target = object()
    payload, _ = client._build_call_payload(  # noqa: SLF001 - test internal payload shape
        method_name="do_thing",
        target=target,
        target_cid="cid",
        args=(UnpicklableContainer(),),
        kwargs={},
        call_site={"timestamp": 0.0, "target_cid": "cid", "stack_trace": []},
        signature=None,
    )

    arg_payload = payload["args"][0]
    assert "data" in arg_payload
    restored = client.deserialize_payload_item(arg_payload)
    assert isinstance(restored, UnpicklablePlaceholder)


def test_serialization_error_event_sends_placeholder(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    def fake_post(url: str, json: dict, timeout: float) -> _Response:
        captured["payload"] = json
        return _Response(200, {"status": "ok"})

    monkeypatch.setattr("requests.post", fake_post)

    client = DebugClient("http://example.test")
    client.enable_events()
    try:
        client._serializer.serialize(UnpicklableContainer())
    finally:
        set_serialization_error_reporter(None)
        client._events_enabled = False

    payload = captured["payload"]
    assert payload["method_name"] == "pickle_error"
    assert payload["exception_cid"]
    assert payload["exception_data"]
    assert payload["exception"]["object_name"] == "UnpicklableContainer"
    restored = client._serializer.deserialize_base64(payload["exception_data"])
    assert isinstance(restored, UnpicklablePlaceholder)
