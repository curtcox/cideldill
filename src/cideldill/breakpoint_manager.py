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
        self._after_breakpoint_behaviors: dict[str, str] = {}
        self._breakpoint_replacements: dict[str, str] = {}
        self._registered_functions: set[str] = set()
        self._function_signatures: dict[str, str] = {}
        self._paused_executions: dict[str, dict[str, Any]] = {}
        self._resume_actions: dict[str, dict[str, Any]] = {}
        self._call_data: dict[str, dict[str, Any]] = {}
        self._execution_history: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()
        # Default behavior when a breakpoint is hit: "stop" or "go"
        self._default_behavior: str = "stop"

    def register_function(self, function_name: str, signature: str | None = None) -> None:
        with self._lock:
            self._registered_functions.add(function_name)
            if signature:
                self._function_signatures[function_name] = signature
            else:
                self._function_signatures.pop(function_name, None)

    def get_registered_functions(self) -> list[str]:
        with self._lock:
            return sorted(self._registered_functions)

    def get_function_signatures(self) -> dict[str, str]:
        with self._lock:
            return dict(self._function_signatures)

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
            self._after_breakpoint_behaviors.pop(function_name, None)
            self._breakpoint_replacements.pop(function_name, None)

    def clear_breakpoints(self) -> None:
        """Clear all breakpoints."""
        with self._lock:
            self._breakpoints.clear()
            self._breakpoint_behaviors.clear()
            self._after_breakpoint_behaviors.clear()
            self._breakpoint_replacements.clear()

    def get_breakpoints(self) -> list[str]:
        """Get list of all active breakpoints.

        Returns:
            List of function names with active breakpoints.
        """
        with self._lock:
            return list(self._breakpoints)

    def has_breakpoint(self, function_name: str) -> bool:
        with self._lock:
            return function_name in self._breakpoints

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

    def get_after_breakpoint_behavior(self, function_name: str) -> str:
        with self._lock:
            if function_name not in self._breakpoints:
                raise KeyError(function_name)
            return self._after_breakpoint_behaviors.get(function_name, "yield")

    def get_after_breakpoint_behaviors(self) -> dict[str, str]:
        with self._lock:
            return {
                name: self._after_breakpoint_behaviors.get(name, "yield")
                for name in self._breakpoints
            }

    def get_breakpoint_replacements(self) -> dict[str, str]:
        with self._lock:
            return dict(self._breakpoint_replacements)

    def get_breakpoint_replacement(self, function_name: str) -> str | None:
        with self._lock:
            return self._breakpoint_replacements.get(function_name)

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

    def set_after_breakpoint_behavior(self, function_name: str, behavior: str) -> None:
        if behavior == "continue":
            behavior = "go"
        if behavior not in {"stop", "go", "yield"}:
            raise ValueError("Behavior must be 'stop', 'go', or 'yield'")
        with self._lock:
            if function_name not in self._breakpoints:
                raise KeyError(function_name)
            if behavior == "yield":
                self._after_breakpoint_behaviors.pop(function_name, None)
            else:
                self._after_breakpoint_behaviors[function_name] = behavior

    def set_breakpoint_replacement(self, function_name: str, replacement: str | None) -> None:
        with self._lock:
            if function_name not in self._breakpoints:
                raise KeyError(function_name)
            if not replacement or replacement == function_name:
                self._breakpoint_replacements.pop(function_name, None)
            else:
                self._breakpoint_replacements[function_name] = replacement

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

    def should_pause_after_breakpoint(self, function_name: str) -> bool:
        """Check if execution should pause after a breakpoint."""
        with self._lock:
            if function_name not in self._breakpoints:
                return False
            selected_behavior = self._after_breakpoint_behaviors.get(function_name, "yield")
            behavior = (
                self._default_behavior
                if selected_behavior == "yield"
                else selected_behavior
            )
            return behavior == "stop"

    def register_call(self, call_id: str, call_data: dict[str, Any]) -> None:
        """Register call data for later lookup during call completion."""
        with self._lock:
            self._call_data[call_id] = dict(call_data)

    def pop_call(self, call_id: str) -> Optional[dict[str, Any]]:
        """Pop call data for the given call_id."""
        with self._lock:
            return self._call_data.pop(call_id, None)

    def record_execution(
        self, function_name: str, call_data: dict[str, Any], completed_at: float | None = None
    ) -> None:
        """Record a completed execution for a breakpoint.

        Args:
            function_name: Name of the function that was executed.
            call_data: Data about the function call.
            completed_at: Timestamp when the call completed (defaults to now).
        """
        if completed_at is None:
            completed_at = time.time()
        record = {
            "function_name": function_name,
            "call_data": call_data,
            "completed_at": completed_at,
        }
        with self._lock:
            if function_name not in self._execution_history:
                self._execution_history[function_name] = []
            self._execution_history[function_name].append(record)

    def get_execution_history(
        self, function_name: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Get execution history for a specific breakpoint.

        Args:
            function_name: Name of the function.
            limit: Optional limit on number of records to return.

        Returns:
            List of execution records, most recent first.
        """
        with self._lock:
            history = self._execution_history.get(function_name, [])
            # Sort by completed_at descending (most recent first)
            sorted_history = sorted(
                history, key=lambda r: r.get("completed_at", 0), reverse=True
            )
            if limit is not None:
                return sorted_history[:limit]
            return sorted_history
