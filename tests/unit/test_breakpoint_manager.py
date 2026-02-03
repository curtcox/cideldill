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
