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
    and exceptions to a CAS store.

    Attributes:
        store: The CAS store for persisting call data.
    """

    def __init__(self, store: Optional[CASStore] = None) -> None:
        """Initialize the Interceptor.

        Args:
            store: CAS store instance. If None, creates an in-memory store.
        """
        self.store = store if store is not None else CASStore()

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

            try:
                # Call the original function
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

                return result

            except Exception as e:
                # Record failed call with exception
                exception_info = {
                    "type": type(e).__name__,
                    "message": str(e),
                }
                self.store.record_call(
                    function_name=func.__name__,
                    args=args_dict,
                    exception=exception_info,
                    timestamp=timestamp,
                    callstack=callstack,
                    call_site=call_site,
                )
                raise

        return wrapper

    def get_call_records(self) -> list[dict[str, Any]]:
        """Get all recorded function calls.

        Returns:
            List of all call records from the store.
        """
        return self.store.get_all_call_records()

    def close(self) -> None:
        """Close the underlying store."""
        self.store.close()
