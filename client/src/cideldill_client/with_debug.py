"""Global debugging configuration and entry point."""

from __future__ import annotations

import functools
import inspect
import logging
import os
import threading
import time
from dataclasses import dataclass
from functools import wraps
from typing import Any
from urllib.parse import urlparse

from .debug_client import DebugClient
from .debug_info import DebugInfo
from .debug_proxy import (
    AsyncDebugProxy,
    DebugProxy,
    _build_stack_trace,
    execute_call_action,
    execute_call_action_async,
    wait_for_post_completion,
    wait_for_post_completion_async,
)
from .exceptions import DebugProtocolError, DebugServerError
from .function_registry import compute_signature
from .function_registry import register_function as register_local_function
from .port_discovery import read_port_from_discovery_file
from .serialization import compute_cid, set_serialization_error_reporter, set_verbose_serialization_warnings
from .server_failure import exit_with_breakpoint_unavailable, exit_with_server_failure


@dataclass
class _DebugState:
    enabled: bool = False
    server_url: str | None = None
    client: DebugClient | None = None
    first_call_seen: bool = False
    suspended_breakpoints_log_interval_s: float | None = None
    deadlock_watchdog_timeout_s: float | None = None
    deadlock_watchdog_log_interval_s: float | None = None


_state = _DebugState()
_state_lock = threading.Lock()
_debug_call_registered: set[tuple[str, int]] = set()
logger = logging.getLogger(__name__)
_MISSING = object()


def configure_debug(
    server_url: str | None = None,
    suspended_breakpoints_log_interval_s: float | None = None,
    deadlock_watchdog_timeout_s: float | None = None,
    deadlock_watchdog_log_interval_s: float | None = None,
) -> None:
    """Configure debug settings before enabling."""
    if server_url is not None:
        _validate_localhost(server_url)
    if (
        suspended_breakpoints_log_interval_s is not None
        and suspended_breakpoints_log_interval_s < 0
    ):
        raise ValueError("suspended_breakpoints_log_interval_s must be >= 0")
    if deadlock_watchdog_timeout_s is not None and deadlock_watchdog_timeout_s < 0:
        raise ValueError("deadlock_watchdog_timeout_s must be >= 0")
    if deadlock_watchdog_log_interval_s is not None and deadlock_watchdog_log_interval_s <= 0:
        raise ValueError("deadlock_watchdog_log_interval_s must be > 0")
    with _state_lock:
        _state.server_url = server_url
        if suspended_breakpoints_log_interval_s is not None:
            _state.suspended_breakpoints_log_interval_s = suspended_breakpoints_log_interval_s
        if deadlock_watchdog_timeout_s is not None:
            _state.deadlock_watchdog_timeout_s = deadlock_watchdog_timeout_s
        if deadlock_watchdog_log_interval_s is not None:
            _state.deadlock_watchdog_log_interval_s = deadlock_watchdog_log_interval_s


def with_debug(target: Any = _MISSING) -> Any:
    """Enable/disable debugging or wrap objects for debugging."""
    if target is _MISSING:
        target = os.environ.get("CIDELDILL", "OFF")

    alias_name: str | None = None

    if not _state.first_call_seen:
        if not isinstance(target, str) or target.strip().upper() not in {"ON", "OFF", "VERBOSE"}:
            raise ValueError(
                "with_debug must be called with 'ON', 'OFF', or 'VERBOSE' before any other use"
            )
        _state.first_call_seen = True

    if (
        isinstance(target, tuple)
        and len(target) == 2
        and isinstance(target[0], str)
    ):
        alias_name = target[0]
        target = target[1]

    # Check if it's a control command (ON/OFF)
    if isinstance(target, str):
        mode = target.strip().upper()
        if mode == "VERBOSE":
            set_verbose_serialization_warnings(True)
            return _set_debug_mode(True)
        if mode in {"ON", "OFF"}:
            set_verbose_serialization_warnings(False)
            return _set_debug_mode(mode == "ON")
        # If it's a string but not ON/OFF, it might be a typo - raise an error
        # unless we're in a debug-disabled state where we should just return it
        if not _is_debug_enabled():
            # When debug is OFF, any object (including non-command strings) is returned as-is
            return target
        # When debug is ON, reject invalid command strings as likely typos
        raise ValueError("with_debug expects 'ON', 'OFF', 'VERBOSE', or an object to wrap")

    # When debug is OFF, return the original object unchanged (true NOP)
    if not _is_debug_enabled():
        return target

    client = _state.client
    if client is None:
        client = _new_debug_client(_resolve_server_url())
        _state.client = client

    if isinstance(target, (DebugProxy, AsyncDebugProxy)):
        underlying = object.__getattribute__(target, "_target")
        if callable(underlying):
            proxy_alias = getattr(target, "_cideldill_alias_name", None)
            callable_name = _resolve_callable_name(underlying, proxy_alias)
            signature = compute_signature(underlying)
            _register_callable_or_halt(
                client,
                target=underlying,
                name=callable_name,
                signature=signature,
            )
            _record_registration(
                client,
                name=callable_name,
                signature=signature,
                alias_name=proxy_alias,
                target=underlying,
            )
        else:
            _record_registration(
                client,
                name=type(underlying).__qualname__,
                signature=None,
                alias_name=getattr(target, "_cideldill_alias_name", None),
                target=underlying,
            )
        return target

    if callable(target):
        callable_name = _resolve_callable_name(target, alias_name)
        signature = compute_signature(target)
        _register_callable_or_halt(
            client,
            target=target,
            name=callable_name,
            signature=signature,
        )
        _record_registration(
            client,
            name=callable_name,
            signature=signature,
            alias_name=alias_name,
            target=target,
        )

        if alias_name is not None and hasattr(target, "__name__"):
            original = target

            @wraps(target)
            def _aliased(*args: Any, **kwargs: Any) -> Any:
                return original(*args, **kwargs)

            _aliased.__name__ = alias_name
            setattr(_aliased, "_cideldill_alias_name", alias_name)
            target = _aliased
    elif alias_name is not None:
        _record_registration(
            client,
            name=alias_name,
            signature=None,
            alias_name=alias_name,
            target=target,
        )
    else:
        _record_registration(
            client,
            name=type(target).__qualname__,
            signature=None,
            alias_name=None,
            target=target,
        )

    proxy_class = AsyncDebugProxy if _is_coroutine_target(target) else DebugProxy
    proxy = proxy_class(target, client, _is_debug_enabled)
    if alias_name is not None:
        # Keep an alias on the proxy itself in case the target drops attributes.
        object.__setattr__(proxy, "_cideldill_alias_name", alias_name)
    elif callable(target):
        # Ensure callable objects without __name__ still have a breakpoint name.
        callable_name = _resolve_callable_name(target, None)
        if callable_name != getattr(target, "__name__", None):
            object.__setattr__(proxy, "_cideldill_alias_name", callable_name)
    return proxy


def _set_debug_mode(enabled: bool) -> DebugInfo:
    if not enabled:
        previous_client: DebugClient | None
        with _state_lock:
            previous_client = _state.client
            _state.enabled = False
            _state.client = None
        _close_client(previous_client)
        _debug_call_registered.clear()
        set_serialization_error_reporter(None)
        return DebugInfo(enabled=False, server=None, status="disabled")

    server_url = _resolve_server_url()
    client = _new_debug_client(server_url)
    try:
        client.check_connection()
    except DebugServerError as exc:
        previous_client = None
        with _state_lock:
            previous_client = _state.client
            _state.enabled = False
            _state.client = None
        _close_client(previous_client)
        _close_client(client)
        exit_with_server_failure(str(exc), server_url, exc)

    previous_client = None
    with _state_lock:
        client.enable_events()
        previous_client = _state.client
        _state.client = client
        _state.enabled = True
    if previous_client is not client:
        _close_client(previous_client)
    return DebugInfo(enabled=True, server=server_url, status="connected")


def _record_registration(
    client: DebugClient,
    *,
    name: str,
    signature: str | None,
    alias_name: str | None,
    target: Any,
) -> None:
    if not hasattr(client, "record_event"):
        return
    call_site = {
        "timestamp": time.time(),
        "stack_trace": _build_stack_trace(skip=2),
    }
    result_payload = {
        "event": "with_debug_registration",
        "function_name": name,
        "signature": signature,
        "alias": alias_name,
        "target_type": f"{type(target).__module__}.{type(target).__qualname__}",
    }
    pretty_summary = alias_name or name
    pretty_arg: dict[str, Any] = {
        "__cideldill_placeholder__": True,
        "summary": pretty_summary,
    }
    try:
        pretty_arg["client_ref"] = client._get_client_ref(target)
    except Exception:
        pass
    client.record_event(
        method_name="with_debug.register",
        status="registered",
        call_site=call_site,
        result=result_payload,
        pretty_args=[pretty_arg],
    )


def _is_debug_enabled() -> bool:
    return _state.enabled


def _resolve_server_url() -> str:
    if _state.server_url:
        return _state.server_url
    env_url = os.getenv("CIDELDILL_SERVER_URL")
    if env_url:
        _validate_localhost(env_url)
        return env_url
    discovered_port = read_port_from_discovery_file()
    if discovered_port:
        return f"http://localhost:{discovered_port}"
    default_url = "http://localhost:5174"
    return default_url


def _resolve_suspended_breakpoint_log_interval_s() -> float:
    if _state.suspended_breakpoints_log_interval_s is not None:
        return max(0.0, _state.suspended_breakpoints_log_interval_s)

    env_value = os.getenv("CIDELDILL_SUSPENDED_BREAKPOINT_LOG_INTERVAL_S")
    if env_value is not None:
        try:
            interval = float(env_value)
            if interval < 0:
                raise ValueError
            return interval
        except ValueError:
            logger.warning(
                "Ignoring invalid CIDELDILL_SUSPENDED_BREAKPOINT_LOG_INTERVAL_S=%r; "
                "using default 60s",
                env_value,
            )
    return 60.0


def _resolve_deadlock_watchdog_timeout_s() -> float | None:
    if _state.deadlock_watchdog_timeout_s is not None:
        if _state.deadlock_watchdog_timeout_s <= 0:
            return None
        return _state.deadlock_watchdog_timeout_s

    env_value = os.getenv("CIDELDILL_DEADLOCK_WATCHDOG_TIMEOUT_S")
    if env_value is not None:
        try:
            timeout = float(env_value)
            if timeout < 0:
                raise ValueError
            if timeout == 0:
                return None
            return timeout
        except ValueError:
            logger.warning(
                "Ignoring invalid CIDELDILL_DEADLOCK_WATCHDOG_TIMEOUT_S=%r; "
                "watchdog disabled",
                env_value,
            )
    return None


def _resolve_deadlock_watchdog_log_interval_s() -> float:
    if _state.deadlock_watchdog_log_interval_s is not None:
        return _state.deadlock_watchdog_log_interval_s

    env_value = os.getenv("CIDELDILL_DEADLOCK_WATCHDOG_LOG_INTERVAL_S")
    if env_value is not None:
        try:
            interval = float(env_value)
            if interval <= 0:
                raise ValueError
            return interval
        except ValueError:
            logger.warning(
                "Ignoring invalid CIDELDILL_DEADLOCK_WATCHDOG_LOG_INTERVAL_S=%r; "
                "using default 60s",
                env_value,
            )
    return 60.0


def _new_debug_client(server_url: str) -> DebugClient:
    kwargs: dict[str, Any] = {
        "suspended_breakpoints_log_interval_s": _resolve_suspended_breakpoint_log_interval_s(),
    }
    timeout = _resolve_deadlock_watchdog_timeout_s()
    if timeout is not None:
        kwargs["deadlock_watchdog_timeout_s"] = timeout
        kwargs["deadlock_watchdog_log_interval_s"] = _resolve_deadlock_watchdog_log_interval_s()
    return DebugClient(server_url, **kwargs)


def _close_client(client: DebugClient | None) -> None:
    if client is None:
        return
    try:
        client.close()
    except Exception:
        logger.debug("Failed to close debug client cleanly", exc_info=True)


def _validate_localhost(server_url: str) -> None:
    hostname = urlparse(server_url).hostname
    if hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise DebugServerError("Debug server URL must be localhost-only")


def _is_coroutine_target(target: Any) -> bool:
    if inspect.iscoroutine(target) or inspect.iscoroutinefunction(target):
        return True
    if isinstance(target, functools.partial):
        if inspect.iscoroutinefunction(target.func):
            return True
        if callable(target.func) and inspect.iscoroutinefunction(getattr(target.func, "__call__", None)):
            return True
    if callable(target) and inspect.iscoroutinefunction(target.__call__):
        return True
    return False


def _resolve_callable_name(target: Any, alias_name: str | None) -> str:
    if alias_name:
        return alias_name
    if isinstance(target, functools.partial):
        return _resolve_callable_name(target.func, None)
    target_name = getattr(target, "__name__", None)
    if target_name:
        return target_name
    return f"{type(target).__qualname__}.__call__"


def _register_callable_or_halt(
    client: DebugClient,
    *,
    target: Any,
    name: str,
    signature: str | None,
) -> None:
    try:
        client.register_function(name, signature=signature, target=target)
        logger.info("Registered breakpoint label: %s", name)
        register_local_function(target, name=name, signature=signature)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - must halt when breakpointing fails
        _record_breakpoint_unavailable(
            client,
            name=name,
            target=target,
            error=exc,
        )
        exit_with_breakpoint_unavailable(
            name=name,
            target=target,
            server_url=client.server_url,
            error=exc,
        )


def _record_breakpoint_unavailable(
    client: DebugClient,
    *,
    name: str,
    target: Any,
    error: BaseException,
) -> None:
    if not hasattr(client, "record_event"):
        return
    call_site = {
        "timestamp": time.time(),
        "stack_trace": _build_stack_trace(skip=2),
    }
    result_payload = {
        "event": "breakpoint_unavailable",
        "function_name": name,
        "target_type": f"{type(target).__module__}.{type(target).__qualname__}",
        "error": f"{type(error).__name__}: {error}",
    }
    try:
        client.record_event(
            method_name="breakpoint_unavailable",
            status="failed",
            call_site=call_site,
            result=result_payload,
            exception=result_payload,
        )
    except Exception:
        return


# ---------------------------------------------------------------------------
# debug_call — inline breakpoints
# ---------------------------------------------------------------------------


def _parse_debug_call_args(
    __name_or_func: Any, *args: Any
) -> tuple[str | None, Any, tuple[Any, ...]]:
    if isinstance(__name_or_func, str):
        alias = __name_or_func
        if not args or not callable(args[0]):
            raise TypeError("debug_call with alias requires a callable as second argument")
        func = args[0]
        call_args = args[1:]
    elif callable(__name_or_func):
        alias = None
        func = __name_or_func
        call_args = args
    else:
        raise TypeError("debug_call expects a callable or (alias_str, callable, ...)")
    return alias, func, call_args


def debug_call(__name_or_func: Any, *args: Any, **kwargs: Any) -> Any:
    """One-shot inline breakpoint.

    When debug is OFF: ``f(*args, **kwargs)`` — immediate call, zero server contact.
    When debug is ON: full round-trip to server with inspection/modification support.
    """
    alias, func, call_args = _parse_debug_call_args(__name_or_func, *args)

    if not _is_debug_enabled():
        return func(*call_args, **kwargs)

    # Unwrap existing proxies
    if isinstance(func, (DebugProxy, AsyncDebugProxy)):
        func = object.__getattribute__(func, "_target")

    client = _state.client
    if client is None:
        client = _new_debug_client(_resolve_server_url())
        _state.client = client

    method_name = alias or _resolve_callable_name(func, None)
    signature = compute_signature(func)
    target_cid = compute_cid(func)

    # Register on first encounter
    reg_key = (method_name, id(func))
    if reg_key not in _debug_call_registered:
        _register_callable_or_halt(
            client, target=func, name=method_name, signature=signature,
        )
        _record_registration(
            client, name=method_name, signature=signature,
            alias_name=alias, target=func,
        )
        _debug_call_registered.add(reg_key)

    call_site = {
        "timestamp": time.time(),
        "target_cid": target_cid,
        "stack_trace": _build_stack_trace(skip=2),
    }

    action = client.record_call_start(
        method_name=method_name,
        target=func,
        target_cid=target_cid,
        args=call_args,
        kwargs=kwargs,
        call_site=call_site,
        signature=signature,
        call_type="inline",
    )

    call_id = action.get("call_id")
    if not call_id:
        raise DebugProtocolError("Missing call_id in response")

    try:
        result = execute_call_action(action, client, func, call_args, kwargs)
    except Exception as exc:
        try:
            client.record_call_complete(
                call_id=call_id, status="exception", exception=exc,
            )
        except DebugServerError:
            logger.exception("Failed to report exception for debug_call (call_id=%s)", call_id)
        raise

    try:
        post_action = client.record_call_complete(
            call_id=call_id, status="success", result=result,
        )
        if post_action:
            wait_for_post_completion(post_action, client)
    except DebugServerError:
        logger.exception("Failed to report completion for debug_call (call_id=%s)", call_id)

    return result


async def async_debug_call(__name_or_func: Any, *args: Any, **kwargs: Any) -> Any:
    """Async variant of debug_call."""
    alias, func, call_args = _parse_debug_call_args(__name_or_func, *args)

    if not _is_debug_enabled():
        result = func(*call_args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    # Unwrap existing proxies
    if isinstance(func, (DebugProxy, AsyncDebugProxy)):
        func = object.__getattribute__(func, "_target")

    client = _state.client
    if client is None:
        client = _new_debug_client(_resolve_server_url())
        _state.client = client

    method_name = alias or _resolve_callable_name(func, None)
    signature = compute_signature(func)
    target_cid = compute_cid(func)

    # Register on first encounter
    reg_key = (method_name, id(func))
    if reg_key not in _debug_call_registered:
        _register_callable_or_halt(
            client, target=func, name=method_name, signature=signature,
        )
        _record_registration(
            client, name=method_name, signature=signature,
            alias_name=alias, target=func,
        )
        _debug_call_registered.add(reg_key)

    call_site = {
        "timestamp": time.time(),
        "target_cid": target_cid,
        "stack_trace": _build_stack_trace(skip=2),
    }

    action = client.record_call_start(
        method_name=method_name,
        target=func,
        target_cid=target_cid,
        args=call_args,
        kwargs=kwargs,
        call_site=call_site,
        signature=signature,
        call_type="inline",
    )

    call_id = action.get("call_id")
    if not call_id:
        raise DebugProtocolError("Missing call_id in response")

    try:
        result = await execute_call_action_async(action, client, func, call_args, kwargs)
    except Exception as exc:
        try:
            client.record_call_complete(
                call_id=call_id, status="exception", exception=exc,
            )
        except DebugServerError:
            logger.exception("Failed to report exception for async_debug_call (call_id=%s)", call_id)
        raise

    try:
        post_action = client.record_call_complete(
            call_id=call_id, status="success", result=result,
        )
        if post_action:
            await wait_for_post_completion_async(post_action, client)
    except DebugServerError:
        logger.exception("Failed to report completion for async_debug_call (call_id=%s)", call_id)

    return result
