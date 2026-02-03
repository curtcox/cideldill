"""Unit tests for DebugProxy replacement execution."""

from cideldill.debug_proxy import DebugProxy
from cideldill.function_registry import register_function, clear_registry


def test_execute_action_can_replace_function() -> None:
    """Replace action should execute the registered replacement function."""
    def add(x: int, y: int) -> int:
        return x + y

    def multiply(x: int, y: int) -> int:
        return x * y

    clear_registry()
    register_function(multiply)

    proxy = DebugProxy(add, client=object(), is_enabled=lambda: True)
    result = proxy._execute_action(
        {"action": "replace", "function_name": "multiply"},
        add,
        (2, 3),
        {},
    )

    assert result == 6
