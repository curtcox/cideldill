"""Unit tests for CAS Store filtering and search functionality.

This test suite validates the filtering and search features for call history.
"""

import pytest

from cideldill_server.cas_store import CASStore


def test_filter_by_function_returns_matching_calls() -> None:
    """Test filtering call records by function name."""
    store = CASStore()
    
    # Record calls to different functions
    store.record_call("add", {"a": 1, "b": 2}, result=3, timestamp=1.0)
    store.record_call("mul", {"a": 3, "b": 4}, result=12, timestamp=2.0)
    store.record_call("add", {"a": 5, "b": 6}, result=11, timestamp=3.0)
    store.record_call("div", {"a": 10, "b": 2}, result=5, timestamp=4.0)
    
    # Filter for 'add' calls
    add_records = store.filter_by_function("add")
    
    assert len(add_records) == 2
    assert add_records[0]["function_name"] == "add"
    assert add_records[0]["args"] == {"a": 1, "b": 2}
    assert add_records[1]["function_name"] == "add"
    assert add_records[1]["args"] == {"a": 5, "b": 6}
    
    store.close()


def test_filter_by_function_returns_empty_for_no_matches() -> None:
    """Test filtering returns empty list when no matches."""
    store = CASStore()
    
    store.record_call("add", {"a": 1, "b": 2}, result=3, timestamp=1.0)
    store.record_call("mul", {"a": 3, "b": 4}, result=12, timestamp=2.0)
    
    # Filter for function that doesn't exist
    records = store.filter_by_function("nonexistent")
    
    assert records == []
    
    store.close()


def test_search_by_args_finds_matching_calls() -> None:
    """Test searching call records by argument values."""
    store = CASStore()
    
    # Record calls with different arguments
    store.record_call("add", {"a": 1, "b": 2}, result=3, timestamp=1.0)
    store.record_call("add", {"a": 5, "b": 2}, result=7, timestamp=2.0)
    store.record_call("mul", {"a": 3, "b": 2}, result=6, timestamp=3.0)
    store.record_call("add", {"x": 2, "y": 3}, result=5, timestamp=4.0)
    
    # Search for calls with {"b": 2} in args
    records = store.search_by_args({"b": 2})
    
    assert len(records) == 3
    assert all(record["args"].get("b") == 2 for record in records)
    
    store.close()


def test_search_by_args_partial_match() -> None:
    """Test searching with partial argument match."""
    store = CASStore()
    
    store.record_call("func1", {"a": 1, "b": 2, "c": 3}, result=6, timestamp=1.0)
    store.record_call("func2", {"a": 1, "x": 5}, result=6, timestamp=2.0)
    store.record_call("func3", {"a": 2, "b": 2}, result=4, timestamp=3.0)
    
    # Search for calls with {"a": 1} - should match first two
    records = store.search_by_args({"a": 1})
    
    assert len(records) == 2
    assert records[0]["function_name"] == "func1"
    assert records[1]["function_name"] == "func2"
    
    store.close()


def test_search_by_args_multiple_criteria() -> None:
    """Test searching with multiple argument criteria."""
    store = CASStore()
    
    store.record_call("func1", {"a": 1, "b": 2}, result=3, timestamp=1.0)
    store.record_call("func2", {"a": 1, "b": 3}, result=4, timestamp=2.0)
    store.record_call("func3", {"a": 2, "b": 2}, result=4, timestamp=3.0)
    
    # Search for calls with both {"a": 1, "b": 2}
    records = store.search_by_args({"a": 1, "b": 2})
    
    assert len(records) == 1
    assert records[0]["function_name"] == "func1"
    
    store.close()


def test_search_by_args_returns_empty_for_no_matches() -> None:
    """Test search returns empty list when no matches."""
    store = CASStore()
    
    store.record_call("add", {"a": 1, "b": 2}, result=3, timestamp=1.0)
    store.record_call("mul", {"a": 3, "b": 4}, result=12, timestamp=2.0)
    
    # Search for args that don't exist
    records = store.search_by_args({"x": 99})
    
    assert records == []
    
    store.close()


def test_search_by_args_with_nested_values() -> None:
    """Test searching with nested argument values."""
    store = CASStore()
    
    store.record_call("func1", {"config": {"mode": "debug"}}, result=1, timestamp=1.0)
    store.record_call("func2", {"config": {"mode": "prod"}}, result=2, timestamp=2.0)
    store.record_call("func3", {"other": "value"}, result=3, timestamp=3.0)
    
    # Search for calls with nested config
    records = store.search_by_args({"config": {"mode": "debug"}})
    
    assert len(records) == 1
    assert records[0]["function_name"] == "func1"
    
    store.close()


def test_filter_by_function_preserves_order() -> None:
    """Test that filtering preserves chronological order."""
    store = CASStore()
    
    store.record_call("add", {"a": 1, "b": 1}, result=2, timestamp=1.0)
    store.record_call("add", {"a": 2, "b": 2}, result=4, timestamp=2.0)
    store.record_call("add", {"a": 3, "b": 3}, result=6, timestamp=3.0)
    
    records = store.filter_by_function("add")
    
    assert len(records) == 3
    assert records[0]["args"] == {"a": 1, "b": 1}
    assert records[1]["args"] == {"a": 2, "b": 2}
    assert records[2]["args"] == {"a": 3, "b": 3}
    
    store.close()
