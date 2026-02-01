"""Breakpoint state manager for web UI integration.

This module provides centralized management of breakpoints and paused executions
for interactive debugging through a web UI.
"""

import threading
import time
import uuid
from typing import Any, Optional


class BreakpointManager:
    """Manages breakpoint state and paused executions.

    This class provides thread-safe management of:
    - Active breakpoints (function names to break on)
    - Currently paused executions (waiting for user action)
    - Resume actions (how to continue each paused execution)

    Attributes:
        _breakpoints: Set of function names with active breakpoints.
        _paused_executions: Dict mapping pause IDs to execution data.
        _resume_actions: Dict mapping pause IDs to resume actions.
        _lock: Thread lock for synchronization.
    """

    def __init__(self) -> None:
        """Initialize the BreakpointManager."""
        self._breakpoints: set[str] = set()
        self._paused_executions: dict[str, dict[str, Any]] = {}
        self._resume_actions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def add_breakpoint(self, function_name: str) -> None:
        """Add a breakpoint on a function.

        Args:
            function_name: Name of the function to break on.
        """
        with self._lock:
            self._breakpoints.add(function_name)

    def remove_breakpoint(self, function_name: str) -> None:
        """Remove a breakpoint from a function.

        Args:
            function_name: Name of the function to remove breakpoint from.
        """
        with self._lock:
            self._breakpoints.discard(function_name)

    def clear_breakpoints(self) -> None:
        """Clear all breakpoints."""
        with self._lock:
            self._breakpoints.clear()

    def get_breakpoints(self) -> list[str]:
        """Get list of all active breakpoints.

        Returns:
            List of function names with active breakpoints.
        """
        with self._lock:
            return list(self._breakpoints)

    def add_paused_execution(self, call_data: dict[str, Any]) -> str:
        """Add a new paused execution.

        Args:
            call_data: Data about the function call (function_name, args, etc.).

        Returns:
            Unique ID for this paused execution.
        """
        pause_id = str(uuid.uuid4())
        paused_at = time.time()

        with self._lock:
            self._paused_executions[pause_id] = {
                "id": pause_id,
                "call_data": call_data,
                "paused_at": paused_at
            }

        return pause_id

    def get_paused_execution(self, pause_id: str) -> Optional[dict[str, Any]]:
        """Get data for a specific paused execution.

        Args:
            pause_id: ID of the paused execution.

        Returns:
            Paused execution data, or None if not found.
        """
        with self._lock:
            return self._paused_executions.get(pause_id)

    def get_paused_executions(self) -> list[dict[str, Any]]:
        """Get all currently paused executions.

        Returns:
            List of paused execution data.
        """
        with self._lock:
            return list(self._paused_executions.values())

    def resume_execution(self, pause_id: str, action: dict[str, Any]) -> None:
        """Resume a paused execution with the given action.

        Args:
            pause_id: ID of the paused execution.
            action: Action dict (e.g., {"action": "continue"}).
        """
        with self._lock:
            # Store the action
            self._resume_actions[pause_id] = action
            # Remove from paused list
            self._paused_executions.pop(pause_id, None)

    def get_resume_action(self, pause_id: str) -> Optional[dict[str, Any]]:
        """Get the resume action for a paused execution.

        Args:
            pause_id: ID of the paused execution.

        Returns:
            Resume action dict, or None if not found.
        """
        with self._lock:
            return self._resume_actions.get(pause_id)

    def wait_for_resume_action(
        self, pause_id: str, timeout: float = 60.0
    ) -> Optional[dict[str, Any]]:
        """Wait for a resume action to be provided.

        This blocks until either:
        - A resume action is provided via resume_execution()
        - The timeout expires

        Args:
            pause_id: ID of the paused execution.
            timeout: Maximum time to wait in seconds.

        Returns:
            Resume action dict, or None if timeout.
        """
        start_time = time.time()
        poll_interval = 0.05  # 50ms

        while time.time() - start_time < timeout:
            action = self.get_resume_action(pause_id)
            if action is not None:
                # Clean up the action after retrieving it
                with self._lock:
                    self._resume_actions.pop(pause_id, None)
                return action
            time.sleep(poll_interval)

        return None
