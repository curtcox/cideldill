"""Unit tests for debug_call and async_debug_call."""

from __future__ import annotations

import asyncio
import base64
import functools

import pytest

pytest.importorskip("dill")
pytest.importorskip("requests")

import dill

from cideldill_client.with_debug import (
    _debug_call_registered,
    _parse_debug_call_args,
    _state,
    configure_debug,
    debug_call,
    async_debug_call,
    with_debug,
)
from cideldill_client.debug_proxy import DebugProxy
from cideldill_client.function_registry import register_function as register_local_function


# ---------------------------------------------------------------------------
# Helpers: mock the server for ON-mode tests
# ---------------------------------------------------------------------------


def _enable_debug(monkeypatch, record_call_start_fn=None):
    """Turn debug ON with a mocked server.  Returns list of captured payloads."""
    captured: dict[str, list] = {"start": [], "complete": []}

    def noop_check(self):
        return None

    def mock_post(self, path, payload):
        return {"status": "ok"}

    def default_record_call_start(
        self, method_name, target, target_cid, args, kwargs,
        call_site, signature=None, *, call_type="proxy",
    ):
        captured["start"].append({
            "method_name": method_name,
            "args": args,
            "kwargs": kwargs,
            "call_type": call_type,
        })
        return {"action": "continue", "call_id": "test-001"}

    def mock_record_call_complete(self, *a, **kw):
        captured["complete"].append(kw or {"args": a})
        return None

    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.check_connection", noop_check
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._post_json", mock_post, raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_start",
        record_call_start_fn or default_record_call_start,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_complete",
        mock_record_call_complete,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")
    return captured


# ---------------------------------------------------------------------------
# _parse_debug_call_args
# ---------------------------------------------------------------------------


class TestParseDebugCallArgs:
    def test_callable_first_arg(self) -> None:
        def f():
            pass

        alias, func, call_args = _parse_debug_call_args(f, 1, 2)
        assert alias is None
        assert func is f
        assert call_args == (1, 2)

    def test_string_alias_first_arg(self) -> None:
        def f():
            pass

        alias, func, call_args = _parse_debug_call_args("step_3", f, 10)
        assert alias == "step_3"
        assert func is f
        assert call_args == (10,)

    def test_string_alias_no_callable_raises(self) -> None:
        with pytest.raises(TypeError, match="callable as second argument"):
            _parse_debug_call_args("step_3")

    def test_string_alias_non_callable_second_arg_raises(self) -> None:
        with pytest.raises(TypeError, match="callable as second argument"):
            _parse_debug_call_args("step_3", 42)

    def test_non_string_non_callable_raises(self) -> None:
        with pytest.raises(TypeError, match="callable or"):
            _parse_debug_call_args(42)

    def test_callable_no_extra_args(self) -> None:
        def f():
            pass

        alias, func, call_args = _parse_debug_call_args(f)
        assert alias is None
        assert func is f
        assert call_args == ()


# ---------------------------------------------------------------------------
# debug_call OFF mode
# ---------------------------------------------------------------------------


class TestDebugCallOff:
    def test_off_mode_calls_directly(self) -> None:
        def add(a, b):
            return a + b

        result = debug_call(add, 3, 4)
        assert result == 7

    def test_off_mode_with_alias_calls_directly(self) -> None:
        def add(a, b):
            return a + b

        result = debug_call("my_add", add, 3, 4)
        assert result == 7

    def test_off_mode_with_kwargs(self) -> None:
        def greet(name, greeting="hello"):
            return f"{greeting} {name}"

        result = debug_call(greet, "world", greeting="hi")
        assert result == "hi world"

    def test_off_mode_no_server_contact(self, monkeypatch) -> None:
        import requests

        def boom(*args, **kwargs):
            raise AssertionError("Should not contact server when OFF")

        monkeypatch.setattr(requests, "post", boom)
        monkeypatch.setattr(requests, "get", boom)

        result = debug_call(lambda x: x * 2, 5)
        assert result == 10


# ---------------------------------------------------------------------------
# async_debug_call OFF mode
# ---------------------------------------------------------------------------


class TestAsyncDebugCallOff:
    def test_off_mode_awaits_coroutine(self) -> None:
        async def double(x):
            return x * 2

        result = asyncio.run(async_debug_call(double, 5))
        assert result == 10

    def test_off_mode_handles_sync_callable(self) -> None:
        def triple(x):
            return x * 3

        result = asyncio.run(async_debug_call(triple, 4))
        assert result == 12

    def test_off_mode_with_alias(self) -> None:
        async def double(x):
            return x * 2

        result = asyncio.run(async_debug_call("my_double", double, 5))
        assert result == 10


# ---------------------------------------------------------------------------
# debug_call ON mode
# ---------------------------------------------------------------------------


class TestDebugCallOnContinue:
    def test_continue_calls_func(self, monkeypatch) -> None:
        captured = _enable_debug(monkeypatch)

        def add(a, b):
            return a + b

        result = debug_call(add, 3, 4)
        assert result == 7
        assert captured["start"][0]["call_type"] == "inline"
        assert captured["start"][0]["method_name"] == "add"

    def test_continue_with_alias(self, monkeypatch) -> None:
        captured = _enable_debug(monkeypatch)

        def add(a, b):
            return a + b

        result = debug_call("my_add", add, 3, 4)
        assert result == 7
        assert captured["start"][0]["method_name"] == "my_add"

    def test_continue_with_kwargs(self, monkeypatch) -> None:
        _enable_debug(monkeypatch)

        def greet(name, greeting="hello"):
            return f"{greeting} {name}"

        result = debug_call(greet, "world", greeting="hi")
        assert result == "hi world"


class TestDebugCallOnModify:
    def test_modify_changes_args(self, monkeypatch) -> None:
        serialized_10 = base64.b64encode(dill.dumps(10, protocol=4)).decode()

        def modify_record_call_start(
            self, method_name, target, target_cid, args, kwargs,
            call_site, signature=None, *, call_type="proxy",
        ):
            return {
                "action": "modify",
                "call_id": "test-001",
                "modified_args": [{"data": serialized_10}],
                "modified_kwargs": {},
            }

        _enable_debug(monkeypatch, modify_record_call_start)

        def double(x):
            return x * 2

        result = debug_call(double, 999)
        assert result == 20  # double(10), not double(999)


class TestDebugCallOnSkip:
    def test_skip_returns_fake_result(self, monkeypatch) -> None:
        def skip_record_call_start(
            self, method_name, target, target_cid, args, kwargs,
            call_site, signature=None, *, call_type="proxy",
        ):
            return {
                "action": "skip",
                "call_id": "test-001",
                "fake_result": 42,
            }

        _enable_debug(monkeypatch, skip_record_call_start)

        called = []

        def should_not_run(x):
            called.append(x)
            return x

        result = debug_call(should_not_run, 999)
        assert result == 42
        assert called == []  # func was never called


class TestDebugCallOnReplace:
    def test_replace_calls_replacement(self, monkeypatch) -> None:
        def replacement(x):
            return x * 100

        register_local_function(replacement, name="replacement")

        def replace_record_call_start(
            self, method_name, target, target_cid, args, kwargs,
            call_site, signature=None, *, call_type="proxy",
        ):
            return {
                "action": "replace",
                "call_id": "test-001",
                "function_name": "replacement",
            }

        _enable_debug(monkeypatch, replace_record_call_start)

        def original(x):
            return x + 1

        result = debug_call(original, 5)
        assert result == 500  # replacement(5)


class TestDebugCallOnRaise:
    def test_raise_raises_exception(self, monkeypatch) -> None:
        def raise_record_call_start(
            self, method_name, target, target_cid, args, kwargs,
            call_site, signature=None, *, call_type="proxy",
        ):
            return {
                "action": "raise",
                "call_id": "test-001",
                "exception_type": "ValueError",
                "exception_message": "test error",
            }

        _enable_debug(monkeypatch, raise_record_call_start)

        with pytest.raises(ValueError, match="test error"):
            debug_call(lambda x: x, 1)


class TestDebugCallOnPoll:
    def test_poll_then_continue(self, monkeypatch) -> None:
        poll_count = [0]

        def poll_record_call_start(
            self, method_name, target, target_cid, args, kwargs,
            call_site, signature=None, *, call_type="proxy",
        ):
            return {
                "action": "poll",
                "call_id": "test-001",
                "poll_url": "/api/poll/abc",
                "poll_interval_ms": 1,
                "timeout_ms": 5000,
            }

        def mock_poll(self, action):
            poll_count[0] += 1
            return {"action": "continue", "call_id": "test-001"}

        _enable_debug(monkeypatch, poll_record_call_start)
        monkeypatch.setattr(
            "cideldill_client.debug_client.DebugClient.poll",
            mock_poll,
            raising=False,
        )

        result = debug_call(lambda x: x + 1, 10)
        assert result == 11
        assert poll_count[0] == 1


# ---------------------------------------------------------------------------
# async_debug_call ON mode
# ---------------------------------------------------------------------------


class TestAsyncDebugCallOn:
    def test_continue_awaits_coroutine(self, monkeypatch) -> None:
        _enable_debug(monkeypatch)

        async def double(x):
            return x * 2

        result = asyncio.run(async_debug_call(double, 5))
        assert result == 10

    def test_skip_returns_fake(self, monkeypatch) -> None:
        def skip_fn(
            self, method_name, target, target_cid, args, kwargs,
            call_site, signature=None, *, call_type="proxy",
        ):
            return {"action": "skip", "call_id": "test-001", "fake_result": 99}

        _enable_debug(monkeypatch, skip_fn)

        async def should_not_run(x):
            raise AssertionError("should not be called")

        result = asyncio.run(async_debug_call(should_not_run, 1))
        assert result == 99


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestDebugCallEdgeCases:
    def test_proxy_unwrap(self, monkeypatch) -> None:
        """debug_call on a DebugProxy unwraps to avoid double-interception."""
        captured = _enable_debug(monkeypatch)

        def add(a, b):
            return a + b

        proxy = with_debug(add)
        assert isinstance(proxy, DebugProxy)

        result = debug_call(proxy, 2, 3)
        assert result == 5
        # The call_start should have been made for the unwrapped function
        assert captured["start"][0]["method_name"] == "add"

    def test_registration_on_first_encounter(self, monkeypatch) -> None:
        """debug_call registers on first call, not on subsequent calls."""
        register_calls: list[str] = []
        original_register = None

        def tracking_register(self, function_name, signature=None, **kw):
            register_calls.append(function_name)
            return original_register(self, function_name, signature=signature, **kw)

        _enable_debug(monkeypatch)
        # Capture original and patch
        from cideldill_client.debug_client import DebugClient
        original_register = DebugClient.register_function
        monkeypatch.setattr(
            "cideldill_client.debug_client.DebugClient.register_function",
            tracking_register,
            raising=False,
        )

        def my_func(x):
            return x

        for _ in range(5):
            debug_call(my_func, 1)

        assert register_calls.count("my_func") == 1

    def test_registration_cleared_on_off(self, monkeypatch) -> None:
        """with_debug('OFF') clears _debug_call_registered."""
        _enable_debug(monkeypatch)

        def f(x):
            return x

        debug_call(f, 1)
        assert len(_debug_call_registered) > 0

        with_debug("OFF")
        assert len(_debug_call_registered) == 0

    def test_call_type_is_inline(self, monkeypatch) -> None:
        """debug_call sends call_type='inline' in the payload."""
        captured = _enable_debug(monkeypatch)

        debug_call(lambda x: x, 1)
        assert captured["start"][0]["call_type"] == "inline"

    def test_functools_partial_name(self, monkeypatch) -> None:
        """debug_call resolves functools.partial names correctly."""
        captured = _enable_debug(monkeypatch)

        def add(a, b):
            return a + b

        add_five = functools.partial(add, 5)
        result = debug_call(add_five, 3)
        assert result == 8
        assert captured["start"][0]["method_name"] == "add"
