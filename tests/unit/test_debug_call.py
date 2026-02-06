"""Unit tests for debug_call and async_debug_call."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("dill")
pytest.importorskip("requests")

from cideldill_client.with_debug import (
    _parse_debug_call_args,
    debug_call,
    async_debug_call,
)


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
