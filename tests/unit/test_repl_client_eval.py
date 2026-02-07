"""Unit tests for REPL evaluation in DebugClient."""

import inspect

from cideldill_client.debug_client import DebugClient


def _frame_with_locals() -> inspect.FrameInfo | None:
    x = 10
    y = 32
    return inspect.currentframe()


def test_eval_expression_uses_frame_locals() -> None:
    client = DebugClient("http://localhost")
    frame = _frame_with_locals()

    payload = client._evaluate_repl_expression("session-1", "x + y", frame)

    assert payload["result"] == "42"
    assert payload["error"] is None


def test_exec_assignment_persists_in_session_namespace() -> None:
    client = DebugClient("http://localhost")
    frame = _frame_with_locals()

    payload1 = client._evaluate_repl_expression("session-2", "z = x + 5", frame)
    payload2 = client._evaluate_repl_expression("session-2", "z", frame)

    assert payload1["error"] is None
    assert payload2["result"] == "15"


def test_incomplete_input_returns_error() -> None:
    client = DebugClient("http://localhost")
    frame = _frame_with_locals()

    payload = client._evaluate_repl_expression("session-3", "def foo():", frame)

    assert payload["error"] == "SyntaxError: incomplete input"
