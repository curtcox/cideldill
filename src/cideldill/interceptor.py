"""Function interceptor module for CID el Dill.

This module provides functionality to wrap functions and record their
calls, arguments, and results to a CAS store.
"""

import functools
import inspect
import time
from typing import Any, Callable, Optional

from cideldill.cas_store import CASStore


class Interceptor:
    """Function call interceptor with CAS storage.

    This class wraps functions to record their calls, arguments, return values,
    and exceptions to a CAS store. It also supports real-time observation and
    breakpoints for debugging.

    Attributes:
        store: The CAS store for persisting call data.
    """

    def __init__(self, store: Optional[CASStore] = None) -> None:
        """Initialize the Interceptor.

        Args:
            store: CAS store instance. If None, creates an in-memory store.
        """
        self.store = store if store is not None else CASStore()
        self._observers: list[Callable[[str, dict[str, Any]], None]] = []
        self._pause_handler: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None
        self._breakpoints: set[str] = set()
        self._break_on_all = False
        self._break_on_exception = False

    def _extract_call_site(self, frame: inspect.FrameInfo) -> dict[str, Any]:
        """Extract call site information from a frame.

        Args:
            frame: Frame information from inspect.

        Returns:
            Dictionary with call site information.
        """
        return {
            "filename": frame.filename,
            "lineno": frame.lineno,
            "function": frame.function,
            "code_context": frame.code_context[0].strip() if frame.code_context else None,
        }

    def wrap(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap a function to intercept and record its calls.

        Args:
            func: The function to wrap.

        Returns:
            The wrapped function.
        """

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Capture timestamp
            timestamp = time.time()

            # Get the call stack and call site
            # Stack frame layout:
            #   [0]: this wrapper function
            #   [1]: the function that called the wrapped function (call site)
            #   [2+]: frames above the call site
            stack = inspect.stack()
            # Extract call site from frame [1]
            call_site = self._extract_call_site(stack[1]) if len(stack) > 1 else None
            # Extract full callstack starting from frame [1] (caller and above)
            callstack = []
            for frame in stack[1:]:  # Skip wrapper frame [0]
                callstack.append({
                    "filename": frame.filename,
                    "lineno": frame.lineno,
                    "function": frame.function,
                    "code_context": frame.code_context[0].strip() if frame.code_context else None,
                })

            # Get function signature to bind arguments properly
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            # Create args dictionary
            args_dict = dict(bound_args.arguments)

            # Notify observers of call start
            call_data = {
                "function_name": func.__name__,
                "args": args_dict,
                "timestamp": timestamp,
                "callstack": callstack,
                "call_site": call_site,
            }
            self._notify_observers("call_start", call_data)

            # Check for breakpoint before execution
            should_break_before_call = (
                self._break_on_all
                or func.__name__ in self._breakpoints
            )

            modified_args_dict = None  # Track if args were modified

            if should_break_before_call and self._pause_handler:
                pause_response = self._pause_handler(call_data)
                action = pause_response.get("action", "continue")

                if action == "skip":
                    # Skip execution and return fake result
                    fake_result = pause_response.get("fake_result")
                    self._notify_observers("call_complete", {
                        **call_data,
                        "result": fake_result,
                        "skipped": True,
                    })
                    return fake_result
                elif action == "raise":
                    # Force an exception
                    exception = pause_response.get("exception")
                    if exception:
                        raise exception
                elif action == "continue":
                    # Check if args were modified
                    if "modified_args" in pause_response:
                        modified_args_dict = pause_response["modified_args"]

            try:
                # Call the original function with original or modified args
                if modified_args_dict is not None:
                    # Apply modified args using function signature
                    bound_modified = sig.bind(**modified_args_dict)
                    bound_modified.apply_defaults()
                    result = func(*bound_modified.args, **bound_modified.kwargs)
                    # Update args_dict for recording
                    args_dict = modified_args_dict
                else:
                    result = func(*args, **kwargs)

                # Record successful call
                self.store.record_call(
                    function_name=func.__name__,
                    args=args_dict,
                    result=result,
                    timestamp=timestamp,
                    callstack=callstack,
                    call_site=call_site,
                )

                # Notify observers of successful completion
                self._notify_observers("call_complete", {
                    **call_data,
                    "result": result,
                })

                return result

            except Exception as e:
                # Record failed call with exception
                exception_info = {
                    "type": type(e).__name__,
                    "message": str(e),
                }

                # Check for breakpoint on exception
                if self._break_on_exception and self._pause_handler:
                    exception_call_data = {
                        **call_data,
                        "exception": exception_info,
                    }
                    pause_response = self._pause_handler(exception_call_data)
                    # After handling, continue with normal exception flow

                self.store.record_call(
                    function_name=func.__name__,
                    args=args_dict,
                    exception=exception_info,
                    timestamp=timestamp,
                    callstack=callstack,
                    call_site=call_site,
                )

                # Notify observers of error
                self._notify_observers("call_error", {
                    **call_data,
                    "exception": exception_info,
                })

                raise

        return wrapper

    def get_call_records(self) -> list[dict[str, Any]]:
        """Get all recorded function calls.

        Returns:
            List of all call records from the store.
        """
        return self.store.get_all_call_records()

    def filter_by_function(self, function_name: str) -> list[dict[str, Any]]:
        """Filter call records by function name.

        Args:
            function_name: The name of the function to filter by.

        Returns:
            List of call records matching the function name.
        """
        return self.store.filter_by_function(function_name)

    def search_by_args(self, search_args: dict[str, Any]) -> list[dict[str, Any]]:
        """Search call records by argument values.

        Args:
            search_args: Dictionary of argument key-value pairs to search for.

        Returns:
            List of call records where args contain all search_args pairs.
        """
        return self.store.search_by_args(search_args)

    def _notify_observers(self, event_type: str, call_data: dict[str, Any]) -> None:
        """Notify all registered observers of an event.

        Args:
            event_type: Type of event (e.g., "call_start", "call_complete", "call_error").
            call_data: Data about the function call.
        """
        for observer in self._observers:
            observer(event_type, call_data)

    def set_observer(self, observer: Callable[[str, dict[str, Any]], None]) -> None:
        """Set a single observer (replaces all existing observers).

        Args:
            observer: Callback function that receives event_type and call_data.
        """
        self._observers = [observer]

    def add_observer(self, observer: Callable[[str, dict[str, Any]], None]) -> None:
        """Add an observer to receive real-time events.

        Args:
            observer: Callback function that receives event_type and call_data.
        """
        if observer not in self._observers:
            self._observers.append(observer)

    def remove_observer(self, observer: Callable[[str, dict[str, Any]], None]) -> None:
        """Remove an observer.

        Args:
            observer: The observer callback to remove.
        """
        if observer in self._observers:
            self._observers.remove(observer)

    def set_pause_handler(
        self, handler: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> None:
        """Set the handler for breakpoint pauses.

        Args:
            handler: Callback that receives call_data and returns action dict.
                    Action dict can contain:
                    - "action": "continue" (default), "skip", or "raise"
                    - "modified_args": dict (when action is "continue")
                    - "fake_result": any (when action is "skip")
                    - "exception": Exception (when action is "raise")
        """
        self._pause_handler = handler

    def set_breakpoint(self, function_name: str) -> None:
        """Set a breakpoint on a specific function.

        Args:
            function_name: Name of the function to break on.
        """
        self._breakpoints.add(function_name)

    def remove_breakpoint(self, function_name: str) -> None:
        """Remove a breakpoint from a specific function.

        Args:
            function_name: Name of the function to remove breakpoint from.
        """
        self._breakpoints.discard(function_name)

    def set_breakpoint_on_all(self) -> None:
        """Set breakpoint to pause on all function calls."""
        self._break_on_all = True

    def set_breakpoint_on_exception(self) -> None:
        """Set breakpoint to pause when exceptions occur."""
        self._break_on_exception = True

    def clear_breakpoints(self) -> None:
        """Clear all breakpoints and pause settings."""
        self._breakpoints.clear()
        self._break_on_all = False
        self._break_on_exception = False

    def export_history(self, format: str = "json") -> str:
        """Export call history for offline analysis.

        Args:
            format: Export format. Currently only "json" is supported.

        Returns:
            Exported data as a string in the specified format.

        Raises:
            ValueError: If format is not supported.
        """
        if format != "json":
            raise ValueError(f"Unsupported export format: {format}")

        import json
        records = self.get_call_records()
        return json.dumps(records, indent=2)

    def export_history_to_file(self, file_path: str, format: str = "json") -> None:
        """Export call history to a file.

        Args:
            file_path: Path to the output file.
            format: Export format. Currently only "json" is supported.
        """
        data = self.export_history(format=format)
        with open(file_path, "w") as f:
            f.write(data)

    def close(self) -> None:
        """Close the underlying store."""
        self.store.close()
