"""Global debugging configuration and entry point."""

from __future__ import annotations

import inspect
import os
import threading
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import Any, Optional

from .debug_client import DebugClient
from .debug_info import DebugInfo
from .debug_proxy import AsyncDebugProxy, DebugProxy
from .exceptions import DebugServerError


@dataclass
class _DebugState:
    enabled: bool = False
    server_url: Optional[str] = None
    client: Optional[DebugClient] = None


_state = _DebugState()
_state_lock = threading.Lock()


def configure_debug(server_url: Optional[str] = None) -> None:
    """Configure debug settings before enabling."""
    if server_url is not None:
        _validate_localhost(server_url)
    with _state_lock:
        _state.server_url = server_url


def with_debug(target: Any) -> Any:
    """Enable/disable debugging or wrap objects for debugging."""
    # Check if it's a control command (ON/OFF)
    if isinstance(target, str):
        mode = target.strip().upper()
        if mode in {"ON", "OFF"}:
            return _set_debug_mode(mode == "ON")
        # If it's a string but not ON/OFF, it might be a typo - raise an error
        # unless we're in a debug-disabled state where we should just return it
        if not _is_debug_enabled():
            # When debug is OFF, any object (including non-command strings) is returned as-is
            return target
        # When debug is ON, reject invalid command strings as likely typos
        raise ValueError("with_debug expects 'ON', 'OFF', or an object to wrap")

    # When debug is OFF, return the original object unchanged (true NOP)
    if not _is_debug_enabled():
        return target

    if isinstance(target, (DebugProxy, AsyncDebugProxy)):
        return target

    client = _state.client
    if client is None:
        client = DebugClient(_resolve_server_url())
        _state.client = client

    proxy_class = AsyncDebugProxy if _is_coroutine_target(target) else DebugProxy
    return proxy_class(target, client, _is_debug_enabled)


def _set_debug_mode(enabled: bool) -> DebugInfo:
    if not enabled:
        with _state_lock:
            _state.enabled = False
            _state.client = None
        return DebugInfo(enabled=False, server=None, status="disabled")

    server_url = _resolve_server_url()
    client = DebugClient(server_url)
    try:
        client.check_connection()
    except DebugServerError:
        with _state_lock:
            _state.enabled = False
            _state.client = None
        return DebugInfo(enabled=False, server=None, status="disabled")

    with _state_lock:
        _state.client = client
        _state.enabled = True
    return DebugInfo(enabled=True, server=server_url, status="connected")


def _is_debug_enabled() -> bool:
    return _state.enabled


def _resolve_server_url() -> str:
    if _state.server_url:
        return _state.server_url
    env_url = os.getenv("CIDELDILL_SERVER_URL")
    if env_url:
        _validate_localhost(env_url)
        return env_url
    default_url = "http://localhost:5000"
    return default_url


def _validate_localhost(server_url: str) -> None:
    hostname = urlparse(server_url).hostname
    if hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise DebugServerError("Debug server URL must be localhost-only")


def _is_coroutine_target(target: Any) -> bool:
    if inspect.iscoroutine(target) or inspect.iscoroutinefunction(target):
        return True
    if hasattr(target, "__call__") and inspect.iscoroutinefunction(target.__call__):
        return True
    return False
