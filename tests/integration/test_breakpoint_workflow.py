"""Integration test for interactive breakpoint workflow.

This test validates the complete workflow of using breakpoints with the web UI.
"""

import tempfile
import threading
import time

import pytest

from cideldill import CASStore, Interceptor, BreakpointManager


def test_complete_breakpoint_workflow():
    """Test the complete workflow: set breakpoint, pause, examine, continue."""
    # Setup
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    store = CASStore(db_path)
    manager = BreakpointManager()
    interceptor = Interceptor(store)

    # Track what happens
    events = []

    # Configure pause handler to use manager
    def pause_handler(call_data):
        events.append(("paused", call_data["function_name"]))
        pause_id = manager.add_paused_execution(call_data)

        # Simulate web UI providing action after 0.1s
        def provide_action():
            time.sleep(0.1)
            manager.resume_execution(pause_id, {"action": "continue"})

        action_thread = threading.Thread(target=provide_action, daemon=True)
        action_thread.start()

        # Wait for action
        action = manager.wait_for_resume_action(pause_id, timeout=1.0)
        events.append(("resumed", call_data["function_name"]))
        return action if action else {"action": "continue"}

    interceptor.set_pause_handler(pause_handler)

    # Test function
    def add(a: int, b: int) -> int:
        return a + b

    wrapped_add = interceptor.wrap(add)

    # Step 1: Set breakpoint via manager (simulating web UI action)
    manager.add_breakpoint("add")
    assert "add" in manager.get_breakpoints()

    # Step 2: Sync to interceptor (as would happen in sync thread)
    for bp in manager.get_breakpoints():
        interceptor.set_breakpoint(bp)

    assert "add" in interceptor.get_breakpoints()

    # Step 3: Execute function - should pause
    result = wrapped_add(2, 3)

    # Verify workflow
    assert result == 5  # Function completed
    assert ("paused", "add") in events
    assert ("resumed", "add") in events
    assert len(manager.get_paused_executions()) == 0  # Nothing still paused

    # Step 4: Remove breakpoint
    manager.remove_breakpoint("add")
    interceptor.remove_breakpoint("add")

    # Step 5: Execute again - should not pause
    events.clear()
    result = wrapped_add(10, 20)

    assert result == 30
    assert ("paused", "add") not in events  # Did not pause

    # Cleanup
    store.close()


def test_multiple_paused_executions():
    """Test handling multiple simultaneous paused executions."""
    manager = BreakpointManager()
    interceptor = Interceptor()

    paused_ids = []

    def pause_handler(call_data):
        pause_id = manager.add_paused_execution(call_data)
        paused_ids.append(pause_id)

        # Immediately mark as resumed
        manager.resume_execution(pause_id, {"action": "continue"})

        return {"action": "continue"}

    interceptor.set_pause_handler(pause_handler)
    interceptor.set_breakpoint("func1")
    interceptor.set_breakpoint("func2")

    def func1():
        return "result1"

    def func2():
        return "result2"

    wrapped_func1 = interceptor.wrap(func1)
    wrapped_func2 = interceptor.wrap(func2)

    # Execute both - they pause but continue immediately
    result1 = wrapped_func1()
    result2 = wrapped_func2()

    assert result1 == "result1"
    assert result2 == "result2"
    assert len(paused_ids) == 2  # Both paused
    assert len(manager.get_paused_executions()) == 0  # But already resumed

    interceptor.close()


def test_breakpoint_sync_mechanism():
    """Test that breakpoints can be synced from manager to interceptor."""
    manager = BreakpointManager()
    interceptor = Interceptor()

    # Initially empty
    assert len(manager.get_breakpoints()) == 0
    assert len(interceptor.get_breakpoints()) == 0

    # Add via manager (simulating web UI)
    manager.add_breakpoint("func1")
    manager.add_breakpoint("func2")

    # Sync to interceptor
    for bp in manager.get_breakpoints():
        interceptor.set_breakpoint(bp)

    assert interceptor.get_breakpoints() == {"func1", "func2"}

    # Remove from manager
    manager.remove_breakpoint("func1")

    # Sync removal
    manager_bps = set(manager.get_breakpoints())
    for bp in interceptor.get_breakpoints() - manager_bps:
        interceptor.remove_breakpoint(bp)

    assert interceptor.get_breakpoints() == {"func2"}

    interceptor.close()
