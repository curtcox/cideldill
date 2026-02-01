"""Function interceptor module for CID el Dill.

This module provides functionality to wrap functions and record their
calls, arguments, and results to a CAS store.
"""

import functools
import inspect
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

    def wrap(self, func: Callable) -> Callable:
        """Wrap a function to intercept and record its calls.

        Args:
            func: The function to wrap.

        Returns:
            The wrapped function.
        """

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
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
                    function_name=func.__name__, args=args_dict, result=result
                )

                return result

            except Exception as e:
                # Record failed call with exception
                exception_info = {
                    "type": type(e).__name__,
                    "message": str(e),
                }
                self.store.record_call(
                    function_name=func.__name__, args=args_dict, exception=exception_info
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
