from cideldill_client.custom_picklers import UnpicklablePlaceholder
from cideldill_client.debug_client import DebugClient


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
