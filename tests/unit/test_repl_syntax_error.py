"""Unit test for REPL syntax errors."""

import inspect

from cideldill_client.debug_client import DebugClient


def _frame_with_locals() -> inspect.FrameInfo | None:
    x = 1
    return inspect.currentframe()


def test_syntax_error_returns_error_payload() -> None:
    client = DebugClient("http://localhost")
    frame = _frame_with_locals()

    payload = client._evaluate_repl_expression("session-err", "def:", frame)

    assert payload["error"] is not None
    assert payload["error"].startswith("SyntaxError:")
