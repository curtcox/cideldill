"""Integration tests for breakpoint functionality.

These tests validate that breakpoints work correctly end-to-end.
"""

import time
from unittest.mock import patch, MagicMock
import pytest
import requests


def test_breakpoint_actually_pauses_execution():
    """Test that setting a breakpoint causes execution to pause."""
    # This test should fail initially - breakpoints aren't working
    from cideldill.breakpoint_manager import BreakpointManager
    from cideldill.breakpoint_server import BreakpointServer
    from cideldill import with_debug, configure_debug

    # Start server
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=5001)

    # Run server in a thread
    import threading
    server_thread = threading.Thread(target=lambda: server.start(), daemon=True)
    server_thread.start()
    time.sleep(1)  # Wait for server to start

    try:
        # Configure client to use the test server
        configure_debug(server_url="http://localhost:5001")

        # Set a breakpoint
        response = requests.post(
            "http://localhost:5001/api/breakpoints",
            json={"function_name": "test_function"},
            timeout=5
        )
        assert response.status_code == 200

        # Verify breakpoint is set
        response = requests.get("http://localhost:5001/api/breakpoints", timeout=5)
        assert response.status_code == 200
        assert "test_function" in response.json()["breakpoints"]

        # Enable debugging and wrap a function
        with_debug("ON")

        def test_function():
            return 42

        wrapped_func = with_debug(test_function)

        # Call should pause at breakpoint - check paused executions
        # We'll call it in a separate thread since it will block
        result_holder = []

        def call_function():
            result_holder.append(wrapped_func())

        call_thread = threading.Thread(target=call_function)
        call_thread.start()

        # Give it a moment to hit the breakpoint
        time.sleep(0.5)

        # Check that execution is paused
        response = requests.get("http://localhost:5001/api/paused", timeout=5)
        assert response.status_code == 200
        paused_list = response.json().get("paused", [])

        # This should now pass - breakpoint works!
        assert len(paused_list) > 0, "Execution should be paused at breakpoint"
        assert paused_list[0]["call_data"]["method_name"] == "test_function"

        # Resume execution
        pause_id = paused_list[0]["id"]
        response = requests.post(
            f"http://localhost:5001/api/paused/{pause_id}/continue",
            json={"action": "continue"},
            timeout=5
        )
        assert response.status_code == 200

        # Wait for thread to complete
        call_thread.join(timeout=5)

        # Verify result was returned
        assert len(result_holder) == 1
        assert result_holder[0] == 42

    finally:
        # Clean up
        with_debug("OFF")


def test_web_ui_has_toggle_breakpoint_functionality():
    """Test that the web UI HTML includes functionality to toggle breakpoints."""
    from cideldill.breakpoint_server import HTML_TEMPLATE

    # Check for add breakpoint functionality
    assert "add" in HTML_TEMPLATE.lower() or "new" in HTML_TEMPLATE.lower(), \
        "Web UI should have add breakpoint functionality"

    # Check for per-breakpoint stop/go toggle
    assert "setbreakpointbehavior" in HTML_TEMPLATE.lower(), \
        "Web UI should include per-breakpoint behavior toggle functionality"
    assert "🛑" in HTML_TEMPLATE and "⚠️" in HTML_TEMPLATE and "🟢" in HTML_TEMPLATE, \
        "Web UI should use stop/yield/go icons"

    # There should be no remove-breakpoint UI
    assert "removebreakpoint" not in HTML_TEMPLATE.lower(), \
        "Web UI should not expose breakpoint removal controls"

    # Check for input field to add new breakpoints
    assert "input" in HTML_TEMPLATE.lower() or "text" in HTML_TEMPLATE.lower(), \
        "Web UI should have input field to add breakpoints"


def test_breakpoint_manager_tracks_function_names():
    """Test that breakpoint manager correctly tracks function names."""
    from cideldill.breakpoint_manager import BreakpointManager

    manager = BreakpointManager()

    # Add breakpoints
    manager.add_breakpoint("function_one")
    manager.add_breakpoint("function_two")

    # Verify they're tracked
    breakpoints = manager.get_breakpoints()
    assert "function_one" in breakpoints
    assert "function_two" in breakpoints
    assert len(breakpoints) == 2

    # Remove one
    manager.remove_breakpoint("function_one")
    breakpoints = manager.get_breakpoints()
    assert "function_one" not in breakpoints
    assert "function_two" in breakpoints
    assert len(breakpoints) == 1


def test_with_debug_preserves_function_name():
    """Test that with_debug wrapper preserves the original function name."""
    from cideldill import with_debug

    def my_test_function():
        return "result"

    wrapped = with_debug(my_test_function)

    # The wrapped function should report the original name when called
    # This is crucial for breakpoint matching
    assert hasattr(wrapped, '__name__') or hasattr(wrapped, '_original_name'), \
        "Wrapped function should preserve original function name"

    # If it has __name__, it should match
    if hasattr(wrapped, '__name__'):
        assert wrapped.__name__ == "my_test_function", \
            f"Expected 'my_test_function' but got '{wrapped.__name__}'"


def test_server_matches_breakpoints_correctly():
    """Test that server correctly matches method names to breakpoints."""
    from cideldill.breakpoint_manager import BreakpointManager

    manager = BreakpointManager()
    manager.add_breakpoint("whole_numbers")
    manager.add_breakpoint("announce_say_default")

    # Simulate a call/start request
    method_name = "whole_numbers"

    # Check if it matches
    breakpoints = manager.get_breakpoints()
    should_pause = method_name in breakpoints

    assert should_pause, f"Method '{method_name}' should match breakpoint"

    # Test non-matching
    method_name = "other_function"
    should_pause = method_name in breakpoints
    assert not should_pause, f"Method '{method_name}' should not match breakpoint"
