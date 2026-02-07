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
        self._function_metadata: dict[str, dict[str, Any]] = {}
        self._paused_executions: dict[str, dict[str, Any]] = {}
        self._resume_actions: dict[str, dict[str, Any]] = {}
        self._call_data: dict[str, dict[str, Any]] = {}
        self._call_to_pause: dict[str, str] = {}  # Maps call_id -> pause_id
        self._execution_history: dict[str, list[dict[str, Any]]] = {}
        self._call_records: list[dict[str, Any]] = []
        self._com_errors: list[dict[str, Any]] = []
        self._object_history: dict[tuple[str, int | str], list[dict[str, Any]]] = {}
        self._repl_sessions: dict[str, dict[str, Any]] = {}
        self._repl_sessions_by_pause: dict[str, list[str]] = {}
        self._repl_sessions_by_call: dict[str, list[str]] = {}
        self._com_error_limit = 500
        self._lock = threading.Lock()
        # Default behavior when a breakpoint is hit: "stop" or "go"
        self._default_behavior: str = "stop"

    def register_function(
        self,
        function_name: str,
        signature: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._registered_functions.add(function_name)
            if signature:
                self._function_signatures[function_name] = signature
            else:
                self._function_signatures.pop(function_name, None)
            if metadata is not None:
                self._function_metadata[function_name] = dict(metadata)

    def get_registered_functions(self) -> list[str]:
        with self._lock:
            return sorted(self._registered_functions)

    def get_function_signatures(self) -> dict[str, str]:
        with self._lock:
            return dict(self._function_signatures)

    def get_function_metadata(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._function_metadata)

    def update_function_metadata(self, function_name: str, updates: dict[str, Any]) -> None:
        with self._lock:
            current = dict(self._function_metadata.get(function_name, {}))
            current.update(updates)
            self._function_metadata[function_name] = current

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
            self._close_repl_sessions_for_pause(pause_id)

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

    def record_object_snapshot(
        self,
        process_key: str,
        client_ref: int | str,
        snapshot: dict[str, Any],
    ) -> None:
        key = (process_key, client_ref)
        with self._lock:
            history = self._object_history.setdefault(key, [])
            history.append(dict(snapshot))

    def get_object_history(self, process_key: str, client_ref: int | str) -> list[dict[str, Any]]:
        key = (process_key, client_ref)
        with self._lock:
            return list(self._object_history.get(key, []))

    def get_all_object_histories(self) -> dict[tuple[str, int | str], list[dict[str, Any]]]:
        with self._lock:
            return {
                key: list(history)
                for key, history in self._object_history.items()
            }

    def get_object_histories_by_ref(self, client_ref: int | str) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            return {
                process_key: list(history)
                for (process_key, ref), history in self._object_history.items()
                if ref == client_ref
            }

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
            if selected_behavior == "yield":
                return False
            return selected_behavior == "stop"

    def register_call(self, call_id: str, call_data: dict[str, Any]) -> None:
        """Register call data for later lookup during call completion."""
        with self._lock:
            self._call_data[call_id] = dict(call_data)

    def associate_pause_with_call(self, call_id: str, pause_id: str) -> None:
        """Associate a pause_id with a call_id for cleanup purposes."""
        with self._lock:
            self._call_to_pause[call_id] = pause_id

    def pop_call(self, call_id: str) -> Optional[dict[str, Any]]:
        """Pop call data for the given call_id and clean up associated resources."""
        with self._lock:
            # Clean up any associated pause/resume data
            pause_id = self._call_to_pause.pop(call_id, None)
            if pause_id:
                self._resume_actions.pop(pause_id, None)
                self._paused_executions.pop(pause_id, None)
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
        record_id = str(uuid.uuid4())
        record = {
            "id": record_id,
            "function_name": function_name,
            "call_data": call_data,
            "completed_at": completed_at,
        }
        with self._lock:
            if function_name not in self._execution_history:
                self._execution_history[function_name] = []
            self._execution_history[function_name].append(record)

    def record_call(self, call_record: dict[str, Any]) -> None:
        """Record a completed call for call tree views."""
        with self._lock:
            call_id = call_record.get("call_id")
            if call_id:
                call_record.setdefault(
                    "repl_sessions",
                    list(self._repl_sessions_by_call.get(call_id, [])),
                )
            self._call_records.append(call_record)

    def get_call_records(self) -> list[dict[str, Any]]:
        """Get all recorded calls."""
        with self._lock:
            return [dict(record) for record in self._call_records]

    def add_com_error(self, com_error: dict[str, Any]) -> None:
        """Record a client/server communication error.

        Args:
            com_error: Communication error payload.
        """
        with self._lock:
            self._com_errors.append(dict(com_error))
            if len(self._com_errors) > self._com_error_limit:
                overflow = len(self._com_errors) - self._com_error_limit
                if overflow > 0:
                    del self._com_errors[:overflow]

    def get_com_errors(self) -> list[dict[str, Any]]:
        """Get recorded communication errors (most recent last)."""
        with self._lock:
            return [dict(record) for record in self._com_errors]

    def get_execution_record(
        self, function_name: str, record_id: str
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            history = self._execution_history.get(function_name, [])
            for record in history:
                if "id" not in record:
                    record["id"] = str(uuid.uuid4())
                if record.get("id") == record_id:
                    return dict(record)
        return None

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
            for record in history:
                if "id" not in record:
                    record["id"] = str(uuid.uuid4())
            # Sort by completed_at descending (most recent first)
            sorted_history = sorted(
                history, key=lambda r: r.get("completed_at", 0), reverse=True
            )
            if limit is not None:
                return sorted_history[:limit]
            return sorted_history

    def start_repl_session(self, pause_id: str, *, now: float | None = None) -> str:
        """Start a REPL session for a paused execution."""
        with self._lock:
            paused = self._paused_executions.get(pause_id)
            if paused is None:
                raise KeyError(pause_id)

            call_data = paused.get("call_data", {}) if isinstance(paused, dict) else {}
            pid = call_data.get("process_pid")
            if pid is None:
                raise KeyError("process_pid")

            started_at = float(time.time() if now is None else now)
            session_id = self._unique_repl_session_id(int(pid), started_at)

            session = {
                "session_id": session_id,
                "pause_id": pause_id,
                "pid": int(pid),
                "started_at": started_at,
                "closed_at": None,
                "function_name": call_data.get("method_name") or call_data.get("function_name"),
                "call_id": call_data.get("call_id"),
                "process_key": call_data.get("process_key"),
                "args": call_data.get("args"),
                "kwargs": call_data.get("kwargs"),
                "pretty_args": call_data.get("pretty_args"),
                "pretty_kwargs": call_data.get("pretty_kwargs"),
                "signature": call_data.get("signature"),
                "transcript": [],
            }
            self._repl_sessions[session_id] = session
            self._repl_sessions_by_pause.setdefault(pause_id, []).append(session_id)
            call_id = session.get("call_id")
            if isinstance(call_id, str):
                self._repl_sessions_by_call.setdefault(call_id, []).append(session_id)
                for record in self._call_records:
                    if record.get("call_id") == call_id:
                        repl_sessions = record.setdefault("repl_sessions", [])
                        if session_id not in repl_sessions:
                            repl_sessions.append(session_id)
            return session_id

    def _unique_repl_session_id(self, pid: int, started_at: float) -> str:
        session_id = f"{pid}-{started_at:.6f}"
        while session_id in self._repl_sessions:
            started_at += 0.001
            session_id = f"{pid}-{started_at:.6f}"
        return session_id

    def get_repl_session(self, session_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            session = self._repl_sessions.get(session_id)
            if session is None:
                return None
            return dict(session)

    def list_repl_sessions(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
    ) -> list[dict[str, Any]]:
        if status not in {None, "active", "closed"}:
            raise ValueError("status must be active, closed, or None")
        search_text = (search or "").lower().strip()
        with self._lock:
            sessions = list(self._repl_sessions.values())

        def _match(session: dict[str, Any]) -> bool:
            if status == "active" and session.get("closed_at") is not None:
                return False
            if status == "closed" and session.get("closed_at") is None:
                return False
            started_at = session.get("started_at")
            if from_ts is not None and isinstance(started_at, (int, float)):
                if float(started_at) < float(from_ts):
                    return False
            if to_ts is not None and isinstance(started_at, (int, float)):
                if float(started_at) > float(to_ts):
                    return False
            if not search_text:
                return True
            function_name = str(session.get("function_name") or "").lower()
            if search_text in function_name:
                return True
            for entry in session.get("transcript", []):
                input_text = str(entry.get("input") or "").lower()
                output_text = str(entry.get("output") or "").lower()
                stdout_text = str(entry.get("stdout") or "").lower()
                if (
                    search_text in input_text
                    or search_text in output_text
                    or search_text in stdout_text
                ):
                    return True
            return False

        filtered = [dict(session) for session in sessions if _match(session)]
        filtered.sort(key=lambda item: float(item.get("started_at") or 0), reverse=True)
        return filtered

    def append_repl_transcript(
        self,
        session_id: str,
        input_text: str,
        output: str,
        stdout: str,
        is_error: bool,
        *,
        result_cid: str | None = None,
    ) -> int:
        with self._lock:
            session = self._repl_sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            if session.get("closed_at") is not None:
                raise RuntimeError("session closed")
            transcript = session.setdefault("transcript", [])
            index = len(transcript)
            transcript.append({
                "index": index,
                "input": input_text,
                "output": output,
                "stdout": stdout,
                "is_error": bool(is_error),
                "result_cid": result_cid,
                "timestamp": time.time(),
            })
            return index

    def close_repl_session(self, session_id: str) -> None:
        with self._lock:
            session = self._repl_sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            if session.get("closed_at") is None:
                session["closed_at"] = time.time()

    def _close_repl_sessions_for_pause(self, pause_id: str) -> None:
        session_ids = self._repl_sessions_by_pause.get(pause_id, [])
        for session_id in session_ids:
            session = self._repl_sessions.get(session_id)
            if session and session.get("closed_at") is None:
                session["closed_at"] = time.time()

    def get_repl_sessions_for_pause(self, pause_id: str) -> list[str]:
        with self._lock:
            return list(self._repl_sessions_by_pause.get(pause_id, []))

    def get_repl_sessions_for_call(self, call_id: str) -> list[str]:
        with self._lock:
            return list(self._repl_sessions_by_call.get(call_id, []))
