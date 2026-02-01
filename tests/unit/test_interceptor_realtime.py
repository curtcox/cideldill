"""Unit tests for real-time observation and breakpoint functionality.

This test suite validates the P0 real-time inspection and breakpoint features.
"""

import pytest

from cideldill import Interceptor


def add(a: int, b: int) -> int:
    """Test function: add two numbers."""
    return a + b


def mul(a: int, b: int) -> int:
    """Test function: multiply two numbers."""
    return a * b


def div(a: int, b: int) -> int:
    """Test function: divide two numbers."""
    return a // b


def test_real_time_observer_called_on_success() -> None:
    """Test that observer is called when function completes successfully."""
    interceptor = Interceptor()
    observations = []

    def observer(event_type, call_data):
        observations.append({"type": event_type, "data": call_data})

    interceptor.set_observer(observer)
    wrapped_add = interceptor.wrap(add)

    result = wrapped_add(2, 3)

    assert result == 5
    assert len(observations) == 2  # start and complete events
    assert observations[0]["type"] == "call_start"
    assert observations[0]["data"]["function_name"] == "add"
    assert observations[0]["data"]["args"] == {"a": 2, "b": 3}
    assert observations[1]["type"] == "call_complete"
    assert observations[1]["data"]["result"] == 5

    interceptor.close()


def test_real_time_observer_called_on_exception() -> None:
    """Test that observer is called when function raises exception."""
    interceptor = Interceptor()
    observations = []

    def observer(event_type, call_data):
        observations.append({"type": event_type, "data": call_data})

    interceptor.set_observer(observer)
    wrapped_div = interceptor.wrap(div)

    with pytest.raises(ZeroDivisionError):
        wrapped_div(1, 0)

    assert len(observations) == 2  # start and error events
    assert observations[0]["type"] == "call_start"
    assert observations[1]["type"] == "call_error"
    assert observations[1]["data"]["exception"]["type"] == "ZeroDivisionError"

    interceptor.close()


def test_multiple_observers() -> None:
    """Test that multiple observers can be registered."""
    interceptor = Interceptor()
    obs1_calls = []
    obs2_calls = []

    def observer1(event_type, call_data):
        obs1_calls.append(event_type)

    def observer2(event_type, call_data):
        obs2_calls.append(event_type)

    interceptor.add_observer(observer1)
    interceptor.add_observer(observer2)
    wrapped_add = interceptor.wrap(add)

    wrapped_add(2, 3)

    assert len(obs1_calls) == 2
    assert len(obs2_calls) == 2

    interceptor.close()


def test_remove_observer() -> None:
    """Test that observers can be removed."""
    interceptor = Interceptor()
    observations = []

    def observer(event_type, call_data):
        observations.append(event_type)

    interceptor.add_observer(observer)
    wrapped_add = interceptor.wrap(add)

    wrapped_add(1, 1)
    assert len(observations) == 2

    interceptor.remove_observer(observer)
    wrapped_add(2, 2)
    # Still 2, no new observations after removal
    assert len(observations) == 2

    interceptor.close()


def test_breakpoint_pauses_execution() -> None:
    """Test that setting a breakpoint pauses execution."""
    interceptor = Interceptor()
    paused_calls = []

    def on_pause(call_data):
        paused_calls.append(call_data)
        # Auto-release to continue
        return {"action": "continue"}

    interceptor.set_pause_handler(on_pause)
    interceptor.set_breakpoint("add")
    wrapped_add = interceptor.wrap(add)

    result = wrapped_add(2, 3)

    assert result == 5
    assert len(paused_calls) == 1
    assert paused_calls[0]["function_name"] == "add"
    assert paused_calls[0]["args"] == {"a": 2, "b": 3}

    interceptor.close()


def test_breakpoint_on_all_functions() -> None:
    """Test setting breakpoint on all functions."""
    interceptor = Interceptor()
    paused_calls = []

    def on_pause(call_data):
        paused_calls.append(call_data["function_name"])
        return {"action": "continue"}

    interceptor.set_pause_handler(on_pause)
    interceptor.set_breakpoint_on_all()
    
    wrapped_add = interceptor.wrap(add)
    wrapped_mul = interceptor.wrap(mul)

    wrapped_add(1, 2)
    wrapped_mul(3, 4)

    assert len(paused_calls) == 2
    assert "add" in paused_calls
    assert "mul" in paused_calls

    interceptor.close()


def test_breakpoint_on_exceptions() -> None:
    """Test that breakpoint can be set to pause on exceptions."""
    interceptor = Interceptor()
    paused_calls = []

    def on_pause(call_data):
        paused_calls.append(call_data)
        return {"action": "continue"}

    interceptor.set_pause_handler(on_pause)
    interceptor.set_breakpoint_on_exception()
    wrapped_div = interceptor.wrap(div)
    wrapped_add = interceptor.wrap(add)

    # This should not pause
    wrapped_add(1, 2)

    # This should pause due to exception
    with pytest.raises(ZeroDivisionError):
        wrapped_div(1, 0)

    assert len(paused_calls) == 1
    assert paused_calls[0]["function_name"] == "div"
    assert "exception" in paused_calls[0]

    interceptor.close()


def test_remove_breakpoint() -> None:
    """Test that breakpoints can be removed."""
    interceptor = Interceptor()
    paused_calls = []

    def on_pause(call_data):
        paused_calls.append(call_data["function_name"])
        return {"action": "continue"}

    interceptor.set_pause_handler(on_pause)
    interceptor.set_breakpoint("add")
    wrapped_add = interceptor.wrap(add)

    # Should pause
    wrapped_add(1, 2)
    assert len(paused_calls) == 1

    # Remove breakpoint
    interceptor.remove_breakpoint("add")
    
    # Should not pause
    wrapped_add(3, 4)
    assert len(paused_calls) == 1  # Still 1

    interceptor.close()


def test_clear_all_breakpoints() -> None:
    """Test clearing all breakpoints."""
    interceptor = Interceptor()
    paused_calls = []

    def on_pause(call_data):
        paused_calls.append(call_data["function_name"])
        return {"action": "continue"}

    interceptor.set_pause_handler(on_pause)
    interceptor.set_breakpoint("add")
    interceptor.set_breakpoint("mul")
    
    wrapped_add = interceptor.wrap(add)
    wrapped_mul = interceptor.wrap(mul)

    wrapped_add(1, 2)
    wrapped_mul(3, 4)
    assert len(paused_calls) == 2

    # Clear all breakpoints
    interceptor.clear_breakpoints()

    # Should not pause
    wrapped_add(5, 6)
    wrapped_mul(7, 8)
    assert len(paused_calls) == 2  # Still 2

    interceptor.close()


def test_modify_args_at_breakpoint() -> None:
    """Test modifying arguments at breakpoint."""
    interceptor = Interceptor()

    def on_pause(call_data):
        # Modify args to change behavior
        return {
            "action": "continue",
            "modified_args": {"a": 10, "b": 20}  # Override original args
        }

    interceptor.set_pause_handler(on_pause)
    interceptor.set_breakpoint("add")
    wrapped_add = interceptor.wrap(add)

    # Original call with (2, 3), but should use (10, 20) instead
    result = wrapped_add(2, 3)

    assert result == 30  # 10 + 20, not 2 + 3

    interceptor.close()


def test_skip_call_with_fake_return() -> None:
    """Test skipping a call and providing a fake return value."""
    interceptor = Interceptor()

    def on_pause(call_data):
        # Skip the actual call and return fake value
        return {
            "action": "skip",
            "fake_result": 999
        }

    interceptor.set_pause_handler(on_pause)
    interceptor.set_breakpoint("add")
    wrapped_add = interceptor.wrap(add)

    result = wrapped_add(2, 3)

    # Should get fake result, not actual computation
    assert result == 999

    interceptor.close()


def test_force_exception_at_breakpoint() -> None:
    """Test forcing an exception at breakpoint."""
    interceptor = Interceptor()

    def on_pause(call_data):
        # Force an exception
        return {
            "action": "raise",
            "exception": ValueError("Forced error for testing")
        }

    interceptor.set_pause_handler(on_pause)
    interceptor.set_breakpoint("add")
    wrapped_add = interceptor.wrap(add)

    with pytest.raises(ValueError, match="Forced error for testing"):
        wrapped_add(2, 3)

    interceptor.close()
