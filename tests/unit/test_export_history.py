"""Unit tests for call history export functionality.

This test suite validates the export feature for offline analysis.
"""

import json
import tempfile
from pathlib import Path

import pytest

from cideldill import CASStore, Interceptor


def add(a: int, b: int) -> int:
    """Test function: add two numbers."""
    return a + b


def mul(a: int, b: int) -> int:
    """Test function: multiply two numbers."""
    return a * b


def test_export_history_to_json() -> None:
    """Test exporting call history to JSON format."""
    interceptor = Interceptor()
    wrapped_add = interceptor.wrap(add)
    wrapped_mul = interceptor.wrap(mul)

    wrapped_add(2, 3)
    wrapped_mul(4, 5)

    # Export to JSON string
    json_str = interceptor.export_history(format="json")
    
    # Parse and verify
    data = json.loads(json_str)
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["function_name"] == "add"
    assert data[1]["function_name"] == "mul"

    interceptor.close()


def test_export_history_to_file() -> None:
    """Test exporting call history to a JSON file."""
    interceptor = Interceptor()
    wrapped_add = interceptor.wrap(add)

    wrapped_add(10, 20)

    # Export to file using safer tempfile approach
    import tempfile
    import os

    fd, output_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)  # Close the file descriptor

    try:
        interceptor.export_history_to_file(output_path)

        # Read and verify
        with open(output_path) as f:
            data = json.load(f)

        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["function_name"] == "add"
        assert data[0]["args"] == {"a": 10, "b": 20}
        assert data[0]["result"] == 30
    finally:
        Path(output_path).unlink(missing_ok=True)

    interceptor.close()


def test_export_filtered_history() -> None:
    """Test exporting only filtered call history."""
    interceptor = Interceptor()
    wrapped_add = interceptor.wrap(add)
    wrapped_mul = interceptor.wrap(mul)

    wrapped_add(1, 2)
    wrapped_mul(3, 4)
    wrapped_add(5, 6)

    # Export only 'add' calls
    records = interceptor.filter_by_function("add")
    json_str = json.dumps(records)
    
    data = json.loads(json_str)
    assert len(data) == 2
    assert all(r["function_name"] == "add" for r in data)

    interceptor.close()


def test_export_empty_history() -> None:
    """Test exporting when no calls have been made."""
    interceptor = Interceptor()

    json_str = interceptor.export_history(format="json")
    
    data = json.loads(json_str)
    assert data == []

    interceptor.close()


def test_export_history_includes_exceptions() -> None:
    """Test that exported history includes exception information."""
    interceptor = Interceptor()
    
    def failing_func():
        raise ValueError("Test error")
    
    wrapped_fail = interceptor.wrap(failing_func)

    try:
        wrapped_fail()
    except ValueError:
        pass

    json_str = interceptor.export_history(format="json")
    data = json.loads(json_str)
    
    assert len(data) == 1
    assert "exception" in data[0]
    assert data[0]["exception"]["type"] == "ValueError"

    interceptor.close()


def test_export_history_from_cas_store() -> None:
    """Test exporting directly from CAS store."""
    store = CASStore()
    
    store.record_call("func1", {"x": 1}, result=10, timestamp=1.0)
    store.record_call("func2", {"y": 2}, result=20, timestamp=2.0)

    # Get all records
    records = store.get_all_call_records()
    json_str = json.dumps(records)
    
    data = json.loads(json_str)
    assert len(data) == 2

    store.close()
