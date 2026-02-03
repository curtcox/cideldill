"""Unit tests for BreakpointManager.

This test suite validates the breakpoint state management functionality.
"""

import pytest

from cideldill.breakpoint_manager import BreakpointManager


def test_can_create_breakpoint_manager() -> None:
    """Test that BreakpointManager can be instantiated."""
    manager = BreakpointManager()
    assert manager is not None


def test_can_add_breakpoint() -> None:
    """Test adding a breakpoint."""
    manager = BreakpointManager()
    manager.add_breakpoint("my_function")
    breakpoints = manager.get_breakpoints()
    assert "my_function" in breakpoints


def test_can_remove_breakpoint() -> None:
    """Test removing a breakpoint."""
    manager = BreakpointManager()
    manager.add_breakpoint("my_function")
    manager.remove_breakpoint("my_function")
    breakpoints = manager.get_breakpoints()
    assert "my_function" not in breakpoints


def test_can_clear_all_breakpoints() -> None:
    """Test clearing all breakpoints."""
    manager = BreakpointManager()
    manager.add_breakpoint("func1")
    manager.add_breakpoint("func2")
    manager.clear_breakpoints()
    breakpoints = manager.get_breakpoints()
    assert len(breakpoints) == 0


def test_can_track_paused_execution() -> None:
    """Test tracking a paused execution."""
    manager = BreakpointManager()
    call_data = {
        "function_name": "add",
        "args": {"a": 1, "b": 2},
        "timestamp": 123456.789
    }
    pause_id = manager.add_paused_execution(call_data)
    assert pause_id is not None
    assert len(manager.get_paused_executions()) == 1


def test_paused_execution_has_unique_id() -> None:
    """Test that each paused execution gets a unique ID."""
    manager = BreakpointManager()
    call_data1 = {"function_name": "add", "args": {"a": 1, "b": 2}}
    call_data2 = {"function_name": "mul", "args": {"a": 3, "b": 4}}

    id1 = manager.add_paused_execution(call_data1)
    id2 = manager.add_paused_execution(call_data2)

    assert id1 != id2


def test_can_get_paused_execution_by_id() -> None:
    """Test retrieving a specific paused execution."""
    manager = BreakpointManager()
    call_data = {"function_name": "add", "args": {"a": 1, "b": 2}}
    pause_id = manager.add_paused_execution(call_data)

    retrieved = manager.get_paused_execution(pause_id)
    assert retrieved is not None
    assert retrieved["call_data"]["function_name"] == "add"
    assert retrieved["call_data"]["args"] == {"a": 1, "b": 2}


def test_can_resume_paused_execution() -> None:
    """Test resuming a paused execution."""
    manager = BreakpointManager()
    call_data = {"function_name": "add", "args": {"a": 1, "b": 2}}
    pause_id = manager.add_paused_execution(call_data)

    # Resume with continue action
    action = {"action": "continue"}
    manager.resume_execution(pause_id, action)

    # Should no longer be in paused list
    assert len(manager.get_paused_executions()) == 0


def test_can_get_resume_action_for_paused_execution() -> None:
    """Test getting the resume action for a paused execution."""
    manager = BreakpointManager()
    call_data = {"function_name": "add", "args": {"a": 1, "b": 2}}
    pause_id = manager.add_paused_execution(call_data)

    # Set resume action
    action = {"action": "continue", "modified_args": {"a": 10, "b": 20}}
    manager.resume_execution(pause_id, action)

    # Get the action (before it's removed)
    retrieved_action = manager.get_resume_action(pause_id)
    assert retrieved_action == action


def test_pop_resume_action_removes_action() -> None:
    """Test pop_resume_action removes the stored action."""
    manager = BreakpointManager()
    pause_id = manager.add_paused_execution({"function_name": "add"})
    manager.resume_execution(pause_id, {"action": "continue"})

    action = manager.pop_resume_action(pause_id)
    assert action == {"action": "continue"}
    assert manager.get_resume_action(pause_id) is None


def test_paused_execution_includes_timestamp() -> None:
    """Test that paused execution includes timestamp."""
    manager = BreakpointManager()
    call_data = {"function_name": "add", "args": {"a": 1, "b": 2}}
    pause_id = manager.add_paused_execution(call_data)

    retrieved = manager.get_paused_execution(pause_id)
    assert "paused_at" in retrieved
    assert isinstance(retrieved["paused_at"], float)


def test_can_wait_for_resume_action() -> None:
    """Test that we can wait for a resume action with timeout."""
    manager = BreakpointManager()
    call_data = {"function_name": "add", "args": {"a": 1, "b": 2}}
    pause_id = manager.add_paused_execution(call_data)

    # Should timeout if no action provided
    action = manager.wait_for_resume_action(pause_id, timeout=0.1)
    assert action is None


def test_multiple_paused_executions() -> None:
    """Test managing multiple paused executions simultaneously."""
    manager = BreakpointManager()

    id1 = manager.add_paused_execution({"function_name": "add"})
    id2 = manager.add_paused_execution({"function_name": "mul"})
    id3 = manager.add_paused_execution({"function_name": "div"})

    paused = manager.get_paused_executions()
    assert len(paused) == 3

    # Resume one
    manager.resume_execution(id2, {"action": "continue"})

    paused = manager.get_paused_executions()
    assert len(paused) == 2
    assert id2 not in [p["id"] for p in paused]


def test_register_function_tracks_signature() -> None:
    """Registering a function should track its signature for UI matching."""
    manager = BreakpointManager()
    manager.register_function("add", signature="(x: int, y: int) -> int")

    assert "add" in manager.get_registered_functions()
    assert manager.get_function_signatures()["add"] == "(x: int, y: int) -> int"


def test_breakpoint_replacement_tracks_selection() -> None:
    """Selecting a replacement should be tracked per breakpoint."""
    manager = BreakpointManager()
    manager.add_breakpoint("add")
    manager.set_breakpoint_replacement("add", "multiply")

    assert manager.get_breakpoint_replacement("add") == "multiply"


def test_after_breakpoints_can_pause_execution() -> None:
    """After-breakpoint behaviors should control post-call pauses."""
    manager = BreakpointManager()
    manager.add_breakpoint("add")
    manager.set_default_behavior("go")
    manager.set_after_breakpoint_behavior("add", "stop")

    assert manager.should_pause_after_breakpoint("add") is True

    manager.set_after_breakpoint_behavior("add", "go")
    assert manager.should_pause_after_breakpoint("add") is False


def test_can_record_execution_history() -> None:
    """Test that execution history can be recorded."""
    manager = BreakpointManager()
    manager.record_execution("add", {"method_name": "add", "args": [1, 2]})

    history = manager.get_execution_history("add")
    assert len(history) == 1
    assert history[0]["function_name"] == "add"
    assert history[0]["call_data"]["args"] == [1, 2]
    assert "completed_at" in history[0]


def test_execution_history_ordered_by_time() -> None:
    """Test that execution history is returned most recent first."""
    import time

    manager = BreakpointManager()
    manager.record_execution("add", {"call_id": 1}, completed_at=100.0)
    time.sleep(0.01)
    manager.record_execution("add", {"call_id": 2}, completed_at=200.0)
    time.sleep(0.01)
    manager.record_execution("add", {"call_id": 3}, completed_at=150.0)

    history = manager.get_execution_history("add")
    assert len(history) == 3
    # Should be ordered by completed_at descending
    assert history[0]["call_data"]["call_id"] == 2  # 200.0
    assert history[1]["call_data"]["call_id"] == 3  # 150.0
    assert history[2]["call_data"]["call_id"] == 1  # 100.0


def test_execution_history_with_limit() -> None:
    """Test that execution history can be limited."""
    manager = BreakpointManager()
    for i in range(10):
        manager.record_execution("add", {"call_id": i}, completed_at=float(i))

    history = manager.get_execution_history("add", limit=3)
    assert len(history) == 3
    # Most recent first
    assert history[0]["call_data"]["call_id"] == 9
    assert history[1]["call_data"]["call_id"] == 8
    assert history[2]["call_data"]["call_id"] == 7


def test_execution_history_empty_for_unknown_function() -> None:
    """Test that execution history is empty for functions without history."""
    manager = BreakpointManager()
    history = manager.get_execution_history("unknown_func")
    assert history == []


def test_pop_call_cleans_up_associated_pause() -> None:
    """Test that pop_call cleans up associated pause and resume data."""
    manager = BreakpointManager()

    # Register a call and create a pause
    call_data = {"method_name": "add", "args": [1, 2]}
    manager.register_call("call-123", call_data)

    pause_id = manager.add_paused_execution(call_data)
    manager.associate_pause_with_call("call-123", pause_id)

    # Resume the execution (stores the action)
    manager.resume_execution(pause_id, {"action": "continue"})

    # Verify the resume action is available
    assert manager.get_resume_action(pause_id) == {"action": "continue"}

    # Pop the call - should clean up the resume action too
    popped = manager.pop_call("call-123")
    assert popped is not None

    # Resume action should now be cleaned up
    assert manager.get_resume_action(pause_id) is None


def test_get_resume_action_is_idempotent() -> None:
    """Test that get_resume_action can be called multiple times."""
    manager = BreakpointManager()

    call_data = {"method_name": "add", "args": [1, 2]}
    pause_id = manager.add_paused_execution(call_data)
    manager.resume_execution(pause_id, {"action": "continue"})

    # get_resume_action should return the same value on repeated calls
    action1 = manager.get_resume_action(pause_id)
    action2 = manager.get_resume_action(pause_id)
    action3 = manager.get_resume_action(pause_id)

    assert action1 == {"action": "continue"}
    assert action2 == {"action": "continue"}
    assert action3 == {"action": "continue"}
