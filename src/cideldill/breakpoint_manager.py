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
        self._breakpoint_behaviors: dict[str, str] = {}
        self._registered_functions: set[str] = set()
        self._paused_executions: dict[str, dict[str, Any]] = {}
        self._resume_actions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        # Default behavior when a breakpoint is hit: "stop" or "go"
        self._default_behavior: str = "stop"

    def register_function(self, function_name: str) -> None:
        with self._lock:
            self._registered_functions.add(function_name)

    def get_registered_functions(self) -> list[str]:
        with self._lock:
            return sorted(self._registered_functions)

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
            self._breakpoint_behaviors.pop(function_name, None)

    def clear_breakpoints(self) -> None:
        """Clear all breakpoints."""
        with self._lock:
            self._breakpoints.clear()
            self._breakpoint_behaviors.clear()

    def get_breakpoints(self) -> list[str]:
        """Get list of all active breakpoints.

        Returns:
            List of function names with active breakpoints.
        """
        with self._lock:
            return list(self._breakpoints)

    def get_breakpoint_behavior(self, function_name: str) -> str:
        with self._lock:
            if function_name not in self._breakpoints:
                raise KeyError(function_name)
            return self._breakpoint_behaviors.get(function_name, "yield")

    def get_breakpoint_behaviors(self) -> dict[str, str]:
        with self._lock:
            return {
                name: self._breakpoint_behaviors.get(name, "yield")
                for name in self._breakpoints
            }

    def set_breakpoint_behavior(self, function_name: str, behavior: str) -> None:
        if behavior == "continue":
            behavior = "go"
        if behavior not in {"stop", "go", "yield"}:
            raise ValueError("Behavior must be 'stop', 'go', or 'yield'")
        with self._lock:
            if function_name not in self._breakpoints:
                raise KeyError(function_name)
            if behavior == "yield":
                self._breakpoint_behaviors.pop(function_name, None)
            else:
                self._breakpoint_behaviors[function_name] = behavior

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

    def pop_resume_action(self, pause_id: str) -> Optional[dict[str, Any]]:
        """Pop the resume action for a paused execution."""
        with self._lock:
            action = self._resume_actions.pop(pause_id, None)
        return action

    def wait_for_resume_action(
        self,
        pause_id: str,
        timeout: float = 30.0,
        poll_interval: float = 0.05,
    ) -> Optional[dict[str, Any]]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            action = self.pop_resume_action(pause_id)
            if action is not None:
                return action
            time.sleep(poll_interval)
        return None

    def set_default_behavior(self, behavior: str) -> None:
        """Set the default behavior when a breakpoint is hit.

        Args:
            behavior: Either "stop" (pause execution) or "go" (log only).
        """
        if behavior == "continue":
            behavior = "go"
        if behavior not in {"stop", "go"}:
            raise ValueError("Behavior must be 'stop' or 'go'")
        with self._lock:
            self._default_behavior = behavior

    def get_default_behavior(self) -> str:
        """Get the current default breakpoint behavior.

        Returns:
            "stop" or "go"
        """
        with self._lock:
            return self._default_behavior

    def should_pause_at_breakpoint(self, function_name: str) -> bool:
        """Check if execution should pause at a breakpoint.

        Args:
            function_name: Name of the function being called.

        Returns:
            True if execution should pause, False if it should continue.
        """
        with self._lock:
            # Check if there's a breakpoint set for this function
            has_breakpoint = function_name in self._breakpoints
            if not has_breakpoint:
                return False
            selected_behavior = self._breakpoint_behaviors.get(function_name, "yield")
            behavior = (
                self._default_behavior
                if selected_behavior == "yield"
                else selected_behavior
            )
            return behavior == "stop"

