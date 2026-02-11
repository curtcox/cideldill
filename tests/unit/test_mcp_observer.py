"""Unit tests for BreakpointManager observer interface."""

import threading

from cideldill_server.breakpoint_manager import BreakpointManager


def test_add_observer() -> None:
    manager = BreakpointManager()

    def observer(event: str, payload: dict[str, object]) -> None:
        return None

    manager.add_observer(observer)


def test_remove_observer() -> None:
    manager = BreakpointManager()
    calls: list[str] = []

    def observer(event: str, payload: dict[str, object]) -> None:
        calls.append(event)

    manager.add_observer(observer)
    manager.remove_observer(observer)
    manager.add_paused_execution({"method_name": "process"})

    assert calls == []


def test_remove_observer_not_registered() -> None:
    manager = BreakpointManager()

    def observer(event: str, payload: dict[str, object]) -> None:
        return None

    manager.remove_observer(observer)


def test_observer_called_on_add_paused_execution() -> None:
    manager = BreakpointManager()
    events: list[tuple[str, dict[str, object]]] = []

    def observer(event: str, payload: dict[str, object]) -> None:
        events.append((event, payload))

    manager.add_observer(observer)
    pause_id = manager.add_paused_execution({"method_name": "process"})

    assert events
    event_name, payload = events[0]
    assert event_name == "execution_paused"
    assert payload.get("pause_id") == pause_id
    assert payload.get("method_name") == "process"


def test_observer_called_on_resume_execution() -> None:
    manager = BreakpointManager()
    events: list[tuple[str, dict[str, object]]] = []

    def observer(event: str, payload: dict[str, object]) -> None:
        events.append((event, payload))

    manager.add_observer(observer)
    pause_id = manager.add_paused_execution({"method_name": "process"})
    manager.resume_execution(pause_id, {"action": "continue"})

    assert any(event == "execution_resumed" for event, _ in events)
    resumed = [payload for event, payload in events if event == "execution_resumed"][0]
    assert resumed.get("pause_id") == pause_id
    assert resumed.get("action") == "continue"


def test_observer_called_on_record_call() -> None:
    manager = BreakpointManager()
    events: list[tuple[str, dict[str, object]]] = []

    def observer(event: str, payload: dict[str, object]) -> None:
        events.append((event, payload))

    manager.add_observer(observer)
    manager.record_call({"call_id": "1", "method_name": "process", "status": "success"})

    assert any(event == "call_completed" for event, _ in events)
    completed = [payload for event, payload in events if event == "call_completed"][0]
    assert completed.get("call_id") == "1"
    assert completed.get("method_name") == "process"
    assert completed.get("status") == "success"


def test_observer_can_read_manager_without_deadlock() -> None:
    manager = BreakpointManager()
    done = threading.Event()

    def observer(event: str, payload: dict[str, object]) -> None:
        manager.get_paused_executions()
        done.set()

    manager.add_observer(observer)
    manager.add_paused_execution({"method_name": "process"})

    assert done.wait(1)
