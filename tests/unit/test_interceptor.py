"""Unit tests for Interceptor module.

This test suite validates the function interception functionality.
"""

import pytest

from cideldill import CASStore, Interceptor


def add(a: int, b: int) -> int:
    """Test function: add two numbers."""
    return a + b


def div(a: int, b: int) -> int:
    """Test function: divide two numbers."""
    return a // b


def test_interceptor_initialization_default() -> None:
    """Test interceptor can be initialized with default store."""
    interceptor = Interceptor()
    assert interceptor.store is not None
    assert isinstance(interceptor.store, CASStore)
    interceptor.close()


def test_interceptor_initialization_with_store() -> None:
    """Test interceptor can be initialized with provided store."""
    store = CASStore()
    interceptor = Interceptor(store)
    assert interceptor.store is store
    interceptor.close()


def test_wrap_function_returns_callable() -> None:
    """Test that wrapping a function returns a callable."""
    interceptor = Interceptor()
    wrapped = interceptor.wrap(add)
    assert callable(wrapped)
    interceptor.close()


def test_wrapped_function_preserves_behavior() -> None:
    """Test that wrapped function preserves original behavior."""
    interceptor = Interceptor()
    wrapped_add = interceptor.wrap(add)

    result = wrapped_add(2, 3)
    assert result == 5

    interceptor.close()


def test_wrapped_function_records_call() -> None:
    """Test that wrapped function records the call."""
    interceptor = Interceptor()
    wrapped_add = interceptor.wrap(add)

    wrapped_add(2, 3)

    records = interceptor.get_call_records()
    assert len(records) == 1
    assert records[0]["function_name"] == "add"
    assert records[0]["args"] == {"a": 2, "b": 3}
    assert records[0]["result"] == 5

    interceptor.close()


def test_wrapped_function_records_exception() -> None:
    """Test that wrapped function records exceptions."""
    interceptor = Interceptor()
    wrapped_div = interceptor.wrap(div)

    with pytest.raises(ZeroDivisionError):
        wrapped_div(1, 0)

    records = interceptor.get_call_records()
    assert len(records) == 1
    assert records[0]["function_name"] == "div"
    assert records[0]["args"] == {"a": 1, "b": 0}
    assert "exception" in records[0]
    assert records[0]["exception"]["type"] == "ZeroDivisionError"

    interceptor.close()


def test_multiple_wrapped_functions() -> None:
    """Test wrapping multiple functions."""
    interceptor = Interceptor()
    wrapped_add = interceptor.wrap(add)
    wrapped_div = interceptor.wrap(div)

    wrapped_add(5, 3)
    wrapped_div(10, 2)

    records = interceptor.get_call_records()
    assert len(records) == 2
    assert records[0]["function_name"] == "add"
    assert records[1]["function_name"] == "div"

    interceptor.close()


def test_get_call_records_empty() -> None:
    """Test getting call records when none exist."""
    interceptor = Interceptor()
    records = interceptor.get_call_records()
    assert records == []
    interceptor.close()


def test_wrapped_function_with_kwargs() -> None:
    """Test wrapped function with keyword arguments."""
    interceptor = Interceptor()
    wrapped_add = interceptor.wrap(add)

    result = wrapped_add(a=10, b=20)
    assert result == 30

    records = interceptor.get_call_records()
    assert len(records) == 1
    assert records[0]["args"] == {"a": 10, "b": 20}
    assert records[0]["result"] == 30

    interceptor.close()


def test_wrapped_function_with_mixed_args() -> None:
    """Test wrapped function with mixed positional and keyword arguments."""
    interceptor = Interceptor()
    wrapped_add = interceptor.wrap(add)

    result = wrapped_add(5, b=7)
    assert result == 12

    records = interceptor.get_call_records()
    assert len(records) == 1
    assert records[0]["args"] == {"a": 5, "b": 7}
    assert records[0]["result"] == 12

    interceptor.close()


def test_wrapped_function_records_timestamp() -> None:
    """Test that wrapped function records the timestamp."""
    import time

    interceptor = Interceptor()
    wrapped_add = interceptor.wrap(add)

    before = time.time()
    wrapped_add(2, 3)
    after = time.time()

    records = interceptor.get_call_records()
    assert len(records) == 1
    assert "timestamp" in records[0]
    # Timestamp should be between before and after
    assert before <= records[0]["timestamp"] <= after

    interceptor.close()


def test_wrapped_function_records_callstack() -> None:
    """Test that wrapped function records the callstack."""
    interceptor = Interceptor()
    wrapped_add = interceptor.wrap(add)

    wrapped_add(2, 3)

    records = interceptor.get_call_records()
    assert len(records) == 1
    assert "callstack" in records[0]
    assert isinstance(records[0]["callstack"], list)
    assert len(records[0]["callstack"]) > 0
    # Callstack should contain frame information
    first_frame = records[0]["callstack"][0]
    assert "filename" in first_frame
    assert "lineno" in first_frame
    assert "function" in first_frame

    interceptor.close()


def test_wrapped_function_records_call_site() -> None:
    """Test that wrapped function records the source code call site."""
    interceptor = Interceptor()
    wrapped_add = interceptor.wrap(add)

    wrapped_add(2, 3)

    records = interceptor.get_call_records()
    assert len(records) == 1
    assert "call_site" in records[0]
    call_site = records[0]["call_site"]
    assert "filename" in call_site
    assert "lineno" in call_site
    assert "code_context" in call_site
    # Should show the line where wrapped_add was called
    assert isinstance(call_site["lineno"], int)
    assert call_site["lineno"] > 0

    interceptor.close()
