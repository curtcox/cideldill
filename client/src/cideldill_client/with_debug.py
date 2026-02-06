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
from .debug_proxy import AsyncDebugProxy, DebugProxy, _build_stack_trace
from .exceptions import DebugServerError
from .function_registry import compute_signature
from .function_registry import register_function as register_local_function
from .port_discovery import read_port_from_discovery_file
from .server_failure import exit_with_breakpoint_unavailable, exit_with_server_failure
from .serialization import set_serialization_error_reporter, set_verbose_serialization_warnings


@dataclass
class _DebugState:
    enabled: bool = False
    server_url: str | None = None
    client: DebugClient | None = None
    first_call_seen: bool = False
    suspended_breakpoints_log_interval_s: float | None = None


_state = _DebugState()
_state_lock = threading.Lock()
logger = logging.getLogger(__name__)


def configure_debug(
    server_url: str | None = None,
    suspended_breakpoints_log_interval_s: float | None = None,
) -> None:
    """Configure debug settings before enabling."""
    if server_url is not None:
        _validate_localhost(server_url)
    if (
        suspended_breakpoints_log_interval_s is not None
        and suspended_breakpoints_log_interval_s < 0
    ):
        raise ValueError("suspended_breakpoints_log_interval_s must be >= 0")
    with _state_lock:
        _state.server_url = server_url
        if suspended_breakpoints_log_interval_s is not None:
            _state.suspended_breakpoints_log_interval_s = suspended_breakpoints_log_interval_s


def with_debug(target: Any) -> Any:
    """Enable/disable debugging or wrap objects for debugging."""
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
        client = DebugClient(
            _resolve_server_url(),
            suspended_breakpoints_log_interval_s=_resolve_suspended_breakpoint_log_interval_s(),
        )
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
        with _state_lock:
            _state.enabled = False
            _state.client = None
        set_serialization_error_reporter(None)
        return DebugInfo(enabled=False, server=None, status="disabled")

    server_url = _resolve_server_url()
    client = DebugClient(
        server_url,
        suspended_breakpoints_log_interval_s=_resolve_suspended_breakpoint_log_interval_s(),
    )
    try:
        client.check_connection()
    except DebugServerError as exc:
        with _state_lock:
            _state.enabled = False
            _state.client = None
        exit_with_server_failure(str(exc), server_url, exc)

    with _state_lock:
        client.enable_events()
        _state.client = client
        _state.enabled = True
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
