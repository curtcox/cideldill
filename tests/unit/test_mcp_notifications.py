"""Unit tests for MCP notification dispatch."""

from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.mcp_notifications import MCPNotificationDispatcher


def test_notification_on_breakpoint_hit() -> None:
    manager = BreakpointManager()
    dispatcher = MCPNotificationDispatcher(manager)
    events: list[tuple[str, dict[str, object]]] = []

    def sink(method: str, params: dict[str, object]) -> None:
        events.append((method, params))

    dispatcher.add_sink(sink)
    pause_id = manager.add_paused_execution(
        {"method_name": "process", "pause_reason": "breakpoint"}
    )

    assert events
    method, params = events[0]
    assert method == "notifications/breakpoint/execution_paused"
    assert params.get("pause_id") == pause_id


def test_notification_on_execution_resumed() -> None:
    manager = BreakpointManager()
    dispatcher = MCPNotificationDispatcher(manager)
    events: list[tuple[str, dict[str, object]]] = []

    dispatcher.add_sink(lambda method, params: events.append((method, params)))
    pause_id = manager.add_paused_execution({"method_name": "process"})
    manager.resume_execution(pause_id, {"action": "continue"})

    assert any(method.endswith("execution_resumed") for method, _ in events)


def test_notification_on_call_completed() -> None:
    manager = BreakpointManager()
    dispatcher = MCPNotificationDispatcher(manager)
    events: list[tuple[str, dict[str, object]]] = []

    dispatcher.add_sink(lambda method, params: events.append((method, params)))
    manager.record_call({"call_id": "1", "method_name": "process", "status": "success"})

    assert any(method.endswith("call_completed") for method, _ in events)


def test_notification_includes_pause_id() -> None:
    manager = BreakpointManager()
    dispatcher = MCPNotificationDispatcher(manager)
    events: list[dict[str, object]] = []

    dispatcher.add_sink(lambda _m, params: events.append(params))
    pause_id = manager.add_paused_execution({"method_name": "process"})

    assert events[0].get("pause_id") == pause_id


def test_notification_includes_method_name() -> None:
    manager = BreakpointManager()
    dispatcher = MCPNotificationDispatcher(manager)
    events: list[dict[str, object]] = []

    dispatcher.add_sink(lambda _m, params: events.append(params))
    manager.add_paused_execution({"method_name": "process"})

    assert events[0].get("method_name") == "process"


def test_notification_includes_pause_reason() -> None:
    manager = BreakpointManager()
    dispatcher = MCPNotificationDispatcher(manager)
    events: list[dict[str, object]] = []

    dispatcher.add_sink(lambda _m, params: events.append(params))
    manager.add_paused_execution({"method_name": "process", "pause_reason": "exception"})

    assert events[0].get("pause_reason") == "exception"


def test_notification_resumed_includes_action() -> None:
    manager = BreakpointManager()
    dispatcher = MCPNotificationDispatcher(manager)
    events: list[dict[str, object]] = []

    dispatcher.add_sink(lambda _m, params: events.append(params))
    pause_id = manager.add_paused_execution({"method_name": "process"})
    manager.resume_execution(pause_id, {"action": "skip"})

    resumed = [params for params in events if params.get("action") == "skip"]
    assert resumed


def test_notification_completed_includes_status() -> None:
    manager = BreakpointManager()
    dispatcher = MCPNotificationDispatcher(manager)
    events: list[dict[str, object]] = []

    dispatcher.add_sink(lambda _m, params: events.append(params))
    manager.record_call({"call_id": "1", "method_name": "process", "status": "success"})

    assert any(params.get("status") == "success" for params in events)


def test_no_notification_when_no_observers() -> None:
    manager = BreakpointManager()
    MCPNotificationDispatcher(manager)
    manager.add_paused_execution({"method_name": "process"})


def test_multiple_observers_all_notified() -> None:
    manager = BreakpointManager()
    dispatcher = MCPNotificationDispatcher(manager)
    calls = {"a": 0, "b": 0}

    def sink_a(_m: str, _p: dict[str, object]) -> None:
        calls["a"] += 1

    def sink_b(_m: str, _p: dict[str, object]) -> None:
        calls["b"] += 1

    dispatcher.add_sink(sink_a)
    dispatcher.add_sink(sink_b)
    manager.add_paused_execution({"method_name": "process"})

    assert calls["a"] == 1
    assert calls["b"] == 1


def test_observer_exception_does_not_crash_server() -> None:
    manager = BreakpointManager()
    dispatcher = MCPNotificationDispatcher(manager)
    calls: list[str] = []

    def bad_sink(_m: str, _p: dict[str, object]) -> None:
        raise RuntimeError("boom")

    def good_sink(method: str, _p: dict[str, object]) -> None:
        calls.append(method)

    dispatcher.add_sink(bad_sink)
    dispatcher.add_sink(good_sink)
    manager.add_paused_execution({"method_name": "process"})

    assert calls


def test_remove_observer() -> None:
    manager = BreakpointManager()
    dispatcher = MCPNotificationDispatcher(manager)
    calls: list[str] = []

    def sink(method: str, _p: dict[str, object]) -> None:
        calls.append(method)

    dispatcher.add_sink(sink)
    dispatcher.remove_sink(sink)
    manager.add_paused_execution({"method_name": "process"})

    assert calls == []
