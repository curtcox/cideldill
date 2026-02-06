"""Unit tests for with_debug API."""

import functools
import importlib
import logging
import pytest
import requests
import threading
import types

pytest.importorskip("requests")

from cideldill_client.debug_proxy import AsyncDebugProxy, DebugProxy
from cideldill_client.with_debug import configure_debug, with_debug
with_debug_module = importlib.import_module("cideldill_client.with_debug")
import cideldill_client.serialization_common as serialization_common


class Sample:
    def add(self, x: int, y: int) -> int:
        return x + y


class AsyncCallable:
    async def __call__(self) -> str:
        return "ok"


class CallableObject:
    def __call__(self, value: int = 1) -> int:
        return value + 1


class AsyncCallableObject:
    async def __call__(self, value: int = 1) -> int:
        return value + 1


class SignatureBomb:
    @property
    def __signature__(self):
        raise RuntimeError("signature boom")

    def __call__(self, value: int = 1) -> int:
        return value


class UnpicklableCallable:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def __reduce_ex__(self, protocol):
        raise TypeError("Not picklable")

    def __call__(self, value: int = 1) -> int:
        return value


class UnpicklableInstance:
    def __reduce_ex__(self, protocol):
        raise TypeError("Not picklable")

    def add(self, x: int, y: int) -> int:
        return x + y


def _mock_server_ok(monkeypatch) -> None:
    def record_post(self, path, payload):
        return {"status": "ok"}

    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._post_json",
        record_post,
        raising=False,
    )


def test_with_debug_off_returns_info() -> None:
    info = with_debug("OFF")
    assert info.is_enabled() is False
    assert info.connection_status() == "disabled"


def test_with_debug_verbose_enables_debug(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    configure_debug(server_url="http://localhost:5000")

    info = with_debug("VERBOSE")
    assert info.is_enabled() is True
    with_debug("OFF")


def test_configure_debug_sets_suspended_breakpoint_log_interval(monkeypatch) -> None:
    captured: dict[str, float] = {}

    def fake_init(
        self,
        server_url: str,
        timeout_s: float = 30.0,
        retry_timeout_s: float = 60.0,
        retry_sleep_s: float = 0.25,
        suspended_breakpoints_log_interval_s: float = 60.0,
    ) -> None:
        del timeout_s, retry_timeout_s, retry_sleep_s
        self._server_url = server_url
        self._events_enabled = False
        captured["interval"] = suspended_breakpoints_log_interval_s

    def noop_check(self) -> None:
        return None

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.__init__", fake_init)
    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)

    configure_debug(
        server_url="http://localhost:5000",
        suspended_breakpoints_log_interval_s=12.5,
    )
    info = with_debug("ON")

    assert info.is_enabled() is True
    assert captured["interval"] == 12.5


def test_configure_debug_rejects_negative_suspended_breakpoint_log_interval() -> None:
    with pytest.raises(ValueError, match="suspended_breakpoints_log_interval_s"):
        configure_debug(
            server_url="http://localhost:5000",
            suspended_breakpoints_log_interval_s=-1.0,
        )


def test_with_debug_first_call_requires_control_string() -> None:
    with_debug_module._state.first_call_seen = False
    with pytest.raises(ValueError, match="with_debug must be called"):
        with_debug("maybe")


def test_with_debug_returns_original_when_off() -> None:
    """When debug is OFF, with_debug(obj) returns the original object unchanged (NOP)."""
    with_debug("OFF")

    target = Sample()
    result = with_debug(target)

    # Should return the exact same object (true NOP)
    assert result is target
    assert type(result) is Sample
    assert not isinstance(result, DebugProxy)


def test_with_debug_off_allows_any_object_including_strings() -> None:
    """When debug is OFF, any object (including non-command strings) is returned as-is."""
    with_debug("OFF")

    # With debug OFF, non-command strings are just returned as-is
    result = with_debug("maybe")
    assert result == "maybe"


def test_with_debug_invalid_string_raises_when_on(monkeypatch) -> None:
    """Invalid command strings should raise ValueError when debug is ON."""
    def noop_check(self) -> None:
        return None

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    # With debug ON, non-command strings should raise
    with pytest.raises(ValueError, match="with_debug expects"):
        with_debug("maybe")


def test_with_debug_logs_breakpoint_label_on_register(monkeypatch, caplog) -> None:
    def noop_check(self) -> None:
        return None

    def post_ok(self, path, payload):
        return {"status": "ok"}

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._post_json",
        post_ok,
        raising=False,
    )
    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    def my_fn():
        return "ok"

    with caplog.at_level(logging.INFO, logger="cideldill_client.with_debug"):
        with_debug(("asset_tool", my_fn))

    assert any(
        "asset_tool" in record.message and "Registered breakpoint label" in record.message
        for record in caplog.records
    )


def test_with_debug_on_exits_with_help_when_unverified(monkeypatch, capsys) -> None:
    def raise_connection_error(*_args, **_kwargs) -> None:
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(
        "cideldill_client.debug_client.requests.get",
        raise_connection_error,
    )
    configure_debug(server_url="http://localhost:5000")

    with pytest.raises(SystemExit) as excinfo:
        with_debug("ON")

    assert excinfo.value.code == 1
    output = capsys.readouterr().err
    assert "Failed to contact breakpoint server" in output
    assert "Most likely causes" in output
    assert "Potential fixes" in output
    assert "connection refused" in output


def test_with_debug_wraps_object_when_on(monkeypatch) -> None:
    """When debug is ON, with_debug(obj) returns a DebugProxy."""
    def noop_check(self) -> None:
        return None

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    target = Sample()
    proxy = with_debug(target)
    assert isinstance(proxy, DebugProxy)
    assert proxy is not target
    assert proxy == proxy


def test_with_debug_off_does_not_contact_server(monkeypatch) -> None:
    """When debug is OFF, with_debug should not contact the server."""
    def fail_post(self, path, payload):
        raise AssertionError("Server contact should not occur when debug is OFF")

    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._post_json",
        fail_post,
        raising=False,
    )

    with_debug("OFF")
    target = Sample()
    result = with_debug(target)
    assert result is target


def test_with_debug_on_sends_registration_event(monkeypatch) -> None:
    """with_debug should confirm registration was sent to the server."""
    def noop_check(self) -> None:
        return None

    calls: list[str] = []

    def record_post(self, path, payload):
        calls.append(path)
        return {"status": "ok"}

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._post_json",
        record_post,
        raising=False,
    )
    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    def my_fn() -> int:
        return 1

    _wrapped = with_debug(my_fn)
    assert "/api/call/event" in calls


def test_with_debug_on_wraps_non_callable_sends_event(monkeypatch) -> None:
    """Non-callable registrations should also be confirmed to the server."""
    def noop_check(self) -> None:
        return None

    calls: list[str] = []

    def record_post(self, path, payload):
        calls.append(path)
        return {"status": "ok"}

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._post_json",
        record_post,
        raising=False,
    )
    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    target = Sample()
    _wrapped = with_debug(target)
    assert "/api/call/event" in calls


def test_with_debug_on_exits_if_registration_not_confirmed(monkeypatch) -> None:
    """with_debug should exit loudly if it cannot confirm server registration."""
    def noop_check(self) -> None:
        return None

    def fail_post(self, path, payload):
        raise SystemExit(1)

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._post_json",
        fail_post,
        raising=False,
    )
    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    target = Sample()
    with pytest.raises(SystemExit):
        with_debug(target)


def test_with_debug_registers_callable_for_breakpoints(monkeypatch) -> None:
    """Calling with_debug(callable) should register it for breakpoint UI/discovery."""

    def noop_check(self) -> None:
        return None

    register_calls: list[str] = []

    def record_register(self, function_name: str, signature: str | None = None, **_: object) -> None:
        register_calls.append(function_name)

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.register_function",
        record_register,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    def my_breakpoint_target() -> int:
        return 123

    _wrapped = with_debug(my_breakpoint_target)

    assert "my_breakpoint_target" in register_calls


def test_with_debug_registers_callable_even_when_target_is_proxy(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    register_calls: list[str] = []

    def record_register(self, function_name: str, signature: str | None = None, **_: object) -> None:
        register_calls.append(function_name)

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.register_function",
        record_register,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    def primes() -> int:
        return 2

    proxy = with_debug(primes)
    _proxy_again = with_debug(proxy)

    assert "primes" in register_calls


def test_with_debug_registers_alias_name_for_callable(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    register_calls: list[str] = []

    def record_register(self, function_name: str, signature: str | None = None, **_: object) -> None:
        register_calls.append(function_name)

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.register_function",
        record_register,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    def primes() -> int:
        return 2

    _wrapped = with_debug(("sequence_fn", primes))

    assert "sequence_fn" in register_calls


def test_with_debug_registers_callable_object_for_breakpoints(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    register_calls: list[str] = []

    def record_register(self, function_name: str, signature: str | None = None, **_: object) -> None:
        register_calls.append(function_name)

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.register_function",
        record_register,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    _wrapped = with_debug(CallableObject())

    assert "CallableObject.__call__" in register_calls


def test_with_debug_callable_object_uses_breakpoint_name(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    call_names: list[str] = []

    def record_call_start(
        self,
        method_name: str,
        target,
        target_cid: str,
        args,
        kwargs,
        call_site,
        signature: str | None = None,
        *,
        call_type: str = "proxy",
    ):
        call_names.append(method_name)
        return {"action": "continue", "call_id": "1"}

    def record_call_complete(self, *args, **kwargs):
        return None

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_start",
        record_call_start,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_complete",
        record_call_complete,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    proxy = with_debug(CallableObject())
    assert proxy(3) == 4
    assert call_names == ["CallableObject.__call__"]


def test_with_debug_alias_callable_object_registers_alias(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    register_calls: list[str] = []

    def record_register(self, function_name: str, signature: str | None = None, **_: object) -> None:
        register_calls.append(function_name)

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.register_function",
        record_register,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    _wrapped = with_debug(("aliased_callable", CallableObject()))

    assert "aliased_callable" in register_calls


def test_with_debug_alias_callable_object_uses_alias_on_call(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    call_names: list[str] = []

    def record_call_start(
        self,
        method_name: str,
        target,
        target_cid: str,
        args,
        kwargs,
        call_site,
        signature: str | None = None,
        *,
        call_type: str = "proxy",
    ):
        call_names.append(method_name)
        return {"action": "continue", "call_id": "1"}

    def record_call_complete(self, *args, **kwargs):
        return None

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_start",
        record_call_start,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_complete",
        record_call_complete,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    proxy = with_debug(("aliased_callable", CallableObject()))
    assert proxy(5) == 6
    assert call_names == ["aliased_callable"]


def test_with_debug_partial_callable_object_registers_callable_name(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    register_calls: list[str] = []

    def record_register(self, function_name: str, signature: str | None = None, **_: object) -> None:
        register_calls.append(function_name)

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.register_function",
        record_register,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    target = CallableObject()
    _wrapped = with_debug(functools.partial(target, 2))

    assert "CallableObject.__call__" in register_calls


def test_with_debug_partial_callable_object_uses_callable_name(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    call_names: list[str] = []

    def record_call_start(
        self,
        method_name: str,
        target,
        target_cid: str,
        args,
        kwargs,
        call_site,
        signature: str | None = None,
        *,
        call_type: str = "proxy",
    ):
        call_names.append(method_name)
        return {"action": "continue", "call_id": "1"}

    def record_call_complete(self, *args, **kwargs):
        return None

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_start",
        record_call_start,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_complete",
        record_call_complete,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    proxy = with_debug(functools.partial(CallableObject(), 3))
    assert proxy() == 4
    assert call_names == ["CallableObject.__call__"]


def test_with_debug_signature_failure_does_not_block_registration(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    register_calls: list[str] = []

    def record_register(self, function_name: str, signature: str | None = None, **_: object) -> None:
        register_calls.append(function_name)
        assert signature in (None, "")

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.register_function",
        record_register,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    _wrapped = with_debug(SignatureBomb())

    assert "SignatureBomb.__call__" in register_calls


def test_with_debug_unpicklable_callable_records_pickle_error(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    events: list[dict[str, object]] = []

    def post_ok(self, path, payload):
        events.append({"path": path, "payload": payload})
        return {"status": "ok"}

    def post_call_start(self, path, payload):
        events.append({"path": path, "payload": payload})
        return {"action": "continue", "call_id": "1"}

    def record_call_complete(self, *args, **kwargs):
        return None

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._post_json",
        post_ok,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._post_json_allowing_cid_errors",
        post_call_start,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_complete",
        record_call_complete,
        raising=False,
    )

    original_dumps = serialization_common.dill.dumps

    def failing_dumps(obj, *args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(obj, UnpicklableCallable):
            raise TypeError("forced pickle failure")
        return original_dumps(obj, *args, **kwargs)

    monkeypatch.setattr(serialization_common.dill, "dumps", failing_dumps)

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    proxy = with_debug(UnpicklableCallable())
    assert proxy(5) == 5

    method_names = [entry["payload"].get("method_name") for entry in events]
    assert "pickle_error" in method_names


def test_with_debug_callable_breakpointed_even_if_serialization_minimal(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    register_calls: list[str] = []
    call_names: list[str] = []

    def record_register(self, function_name: str, signature: str | None = None, **_: object) -> None:
        register_calls.append(function_name)

    def record_call_start(
        self,
        method_name: str,
        target,
        target_cid: str,
        args,
        kwargs,
        call_site,
        signature: str | None = None,
        *,
        call_type: str = "proxy",
    ):
        call_names.append(method_name)
        return {"action": "continue", "call_id": "1"}

    def record_call_complete(self, *args, **kwargs):
        return None

    def post_ok(self, path, payload):
        return {"status": "ok"}

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.register_function",
        record_register,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_start",
        record_call_start,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_complete",
        record_call_complete,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient._post_json",
        post_ok,
        raising=False,
    )

    original_dumps = serialization_common.dill.dumps
    placeholder_cls = serialization_common.UnpicklablePlaceholder

    def failing_dumps(obj, *args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(obj, (UnpicklableCallable, placeholder_cls)):
            raise TypeError("forced pickle failure")
        return original_dumps(obj, *args, **kwargs)

    monkeypatch.setattr(serialization_common.dill, "dumps", failing_dumps)

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    proxy = with_debug(UnpicklableCallable())
    assert proxy(7) == 7

    assert "UnpicklableCallable.__call__" in register_calls
    assert call_names == ["UnpicklableCallable.__call__"]


def test_with_debug_bound_method_of_unpicklable_instance(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    call_names: list[str] = []

    def record_call_start(
        self,
        method_name: str,
        target,
        target_cid: str,
        args,
        kwargs,
        call_site,
        signature: str | None = None,
        *,
        call_type: str = "proxy",
    ):
        call_names.append(method_name)
        return {"action": "continue", "call_id": "1"}

    def record_call_complete(self, *args, **kwargs):
        return None

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_start",
        record_call_start,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_complete",
        record_call_complete,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    obj = UnpicklableInstance()
    proxy = with_debug(obj.add)
    assert proxy(2, 3) == 5
    assert call_names == ["add"]


def test_with_debug_dynamic_function_registers(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    register_calls: list[str] = []

    def record_register(self, function_name: str, signature: str | None = None, **_: object) -> None:
        register_calls.append(function_name)

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.register_function",
        record_register,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    namespace: dict[str, object] = {}
    exec("def dyn_func(x):\n    return x + 1", namespace)
    dyn_func = namespace["dyn_func"]
    assert isinstance(dyn_func, types.FunctionType)

    _wrapped = with_debug(dyn_func)

    assert "dyn_func" in register_calls


def test_with_debug_lambda_with_unpicklable_capture(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    call_names: list[str] = []

    def record_call_start(
        self,
        method_name: str,
        target,
        target_cid: str,
        args,
        kwargs,
        call_site,
        signature: str | None = None,
        *,
        call_type: str = "proxy",
    ):
        call_names.append(method_name)
        return {"action": "continue", "call_id": "1"}

    def record_call_complete(self, *args, **kwargs):
        return None

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_start",
        record_call_start,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_complete",
        record_call_complete,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    lock = threading.Lock()
    fn = lambda: lock.locked()  # noqa: E731
    proxy = with_debug(fn)
    assert proxy() is False
    assert call_names == ["<lambda>"]


def test_with_debug_async_callable_object_uses_alias(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    call_names: list[str] = []

    def record_call_start(
        self,
        method_name: str,
        target,
        target_cid: str,
        args,
        kwargs,
        call_site,
        signature: str | None = None,
        *,
        call_type: str = "proxy",
    ):
        call_names.append(method_name)
        return {"action": "continue", "call_id": "1"}

    def record_call_complete(self, *args, **kwargs):
        return None

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_start",
        record_call_start,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_call_complete",
        record_call_complete,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    proxy = with_debug(("async_alias", AsyncCallableObject()))
    assert isinstance(proxy, AsyncDebugProxy)
    import asyncio
    assert asyncio.run(proxy(3)) == 4
    assert call_names == ["async_alias"]


def test_with_debug_breakpoint_unavailable_halts(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    events: list[dict[str, object]] = []

    def record_register(self, function_name: str, signature: str | None = None, **_: object) -> None:
        raise RuntimeError("registration failed")

    def record_event(
        self,
        *,
        method_name: str,
        status: str,
        call_site: dict[str, object],
        pretty_args=None,
        pretty_kwargs=None,
        signature: str | None = None,
        result=None,
        exception=None,
    ) -> None:
        events.append({
            "method_name": method_name,
            "status": status,
            "exception": exception,
        })

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.register_function",
        record_register,
        raising=False,
    )
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.record_event",
        record_event,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    with pytest.raises(SystemExit):
        with_debug(CallableObject())

    assert any(event["method_name"] == "breakpoint_unavailable" for event in events)


def test_with_debug_alias_callable_is_serializable(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    def record_register(self, function_name: str, signature: str | None = None, **_: object) -> None:
        return None

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    monkeypatch.setattr(
        "cideldill_client.debug_client.DebugClient.register_function",
        record_register,
        raising=False,
    )

    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    def primes() -> int:
        return 2

    aliased_proxy = with_debug(("sequence_fn", primes))
    assert aliased_proxy is not None


def test_with_debug_nop_preserves_identity_when_off() -> None:
    """obj = with_debug(obj) is a true NOP when debug is OFF."""
    with_debug("OFF")

    original = Sample()
    original_id = id(original)

    # This should be a no-op
    original = with_debug(original)

    # Identity should be preserved
    assert id(original) == original_id
    assert isinstance(original, Sample)
    assert not isinstance(original, DebugProxy)


def test_with_debug_nop_zero_overhead_when_off() -> None:
    """When debug is OFF, with_debug(obj) has zero overhead."""
    with_debug("OFF")

    # Test with various types
    obj1 = Sample()
    obj2 = [1, 2, 3]
    obj3 = {"key": "value"}

    # All should return original objects
    assert with_debug(obj1) is obj1
    assert with_debug(obj2) is obj2
    assert with_debug(obj3) is obj3


def test_with_debug_async_callable_uses_async_proxy(monkeypatch) -> None:
    def noop_check(self) -> None:
        return None

    monkeypatch.setattr("cideldill_client.debug_client.DebugClient.check_connection", noop_check)
    _mock_server_ok(monkeypatch)
    configure_debug(server_url="http://localhost:5000")
    with_debug("ON")

    proxy = with_debug(AsyncCallable())
    assert isinstance(proxy, AsyncDebugProxy)


def test_with_debug_async_callable_returns_original_when_off() -> None:
    """When debug is OFF, async callables are also returned unchanged."""
    with_debug("OFF")

    target = AsyncCallable()
    result = with_debug(target)

    assert result is target
    assert not isinstance(result, AsyncDebugProxy)
