"""Pytest fixtures for shared test state."""

from __future__ import annotations

import pytest

import importlib

import cideldill_client.function_registry as function_registry

with_debug_module = importlib.import_module("cideldill_client.with_debug")


@pytest.fixture(autouse=True)
def _reset_debug_state() -> None:
    """Reset global debug state between tests."""
    existing_client = with_debug_module._state.client
    if existing_client is not None:
        try:
            existing_client.close()
        except Exception:
            pass
    with_debug_module._state.server_url = None
    with_debug_module._state.enabled = False
    with_debug_module._state.client = None
    with_debug_module._state.first_call_seen = False
    with_debug_module._state.suspended_breakpoints_log_interval_s = None
    with_debug_module._state.deadlock_watchdog_timeout_s = None
    with_debug_module._state.deadlock_watchdog_log_interval_s = None
    function_registry.clear_registry()
    yield
    existing_client = with_debug_module._state.client
    if existing_client is not None:
        try:
            existing_client.close()
        except Exception:
            pass
    with_debug_module._state.server_url = None
    with_debug_module._state.enabled = False
    with_debug_module._state.client = None
    with_debug_module._state.first_call_seen = False
    with_debug_module._state.suspended_breakpoints_log_interval_s = None
    with_debug_module._state.deadlock_watchdog_timeout_s = None
    with_debug_module._state.deadlock_watchdog_log_interval_s = None
    function_registry.clear_registry()
