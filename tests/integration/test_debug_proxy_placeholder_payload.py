"""Integration test for placeholder payloads flowing through DebugProxy."""

from __future__ import annotations

import threading
import time

import pytest

from cideldill_client import configure_debug, with_debug
from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer


class ExplodingGetState:
    def __init__(self, value: int):
        self.value = value

    def __getstate__(self):
        raise TypeError("boom")

    def __setstate__(self, state):
        return None


@pytest.mark.integration
def test_debug_proxy_sends_placeholder_payloads():
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=5002)
    server_thread = threading.Thread(target=server.start, daemon=True)
    server_thread.start()
    time.sleep(0.5)

    try:
        configure_debug(server_url="http://localhost:5002")
        with_debug("ON")

        def echo(arg):
            return arg

        wrapped = with_debug(echo)
        result = wrapped(ExplodingGetState(10))
        assert isinstance(result, ExplodingGetState)

        records = manager.get_call_records()
        assert records, "Expected at least one call record"
        record = records[-1]
        call_data = record.get("call_data") or record
        pretty_args = call_data.get("pretty_args", [])
        pretty_result = call_data.get("pretty_result")

        assert pretty_args, "Expected pretty_args in call record"
        assert isinstance(pretty_args[0], dict)
        assert pretty_args[0].get("__cideldill_placeholder__") is True
        assert isinstance(pretty_result, dict)
        assert pretty_result.get("__cideldill_placeholder__") is True
    finally:
        with_debug("OFF")
        server.stop()
