"""Notification dispatcher for MCP breakpoint events."""

from __future__ import annotations

import threading
from typing import Any, Callable

from .breakpoint_manager import BreakpointManager

NotificationSink = Callable[[str, dict[str, object]], None]


class MCPNotificationDispatcher:
    """Dispatch BreakpointManager events to MCP notification sinks."""

    def __init__(self, manager: BreakpointManager) -> None:
        self._manager = manager
        self._sinks: list[NotificationSink] = []
        self._lock = threading.Lock()
        self._manager.add_observer(self._handle_event)

    def add_sink(self, sink: NotificationSink) -> None:
        with self._lock:
            if sink not in self._sinks:
                self._sinks.append(sink)

    def remove_sink(self, sink: NotificationSink) -> None:
        with self._lock:
            try:
                self._sinks.remove(sink)
            except ValueError:
                return

    def _handle_event(self, event: str, payload: dict[str, object]) -> None:
        if event == "execution_paused":
            params = {
                "pause_id": payload.get("pause_id"),
                "method_name": payload.get("method_name"),
                "pause_reason": payload.get("pause_reason"),
                "paused_at": payload.get("paused_at"),
            }
            self._emit("notifications/breakpoint/execution_paused", params)
            return

        if event == "execution_resumed":
            params = {
                "pause_id": payload.get("pause_id"),
                "method_name": payload.get("method_name"),
                "action": payload.get("action"),
            }
            self._emit("notifications/breakpoint/execution_resumed", params)
            return

        if event == "call_completed":
            params = {
                "call_id": payload.get("call_id"),
                "method_name": payload.get("method_name"),
                "status": payload.get("status"),
            }
            self._emit("notifications/breakpoint/call_completed", params)

    def _emit(self, method: str, params: dict[str, object]) -> None:
        with self._lock:
            sinks = list(self._sinks)
        for sink in sinks:
            try:
                sink(method, params)
            except Exception:
                continue
