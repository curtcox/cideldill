"""Unit tests for CAS Store module.

This test suite validates the content-addressable storage functionality.
"""

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from cideldill_server.cas_store import CASStore


@pytest.fixture
def temp_db_path() -> Generator[str, None, None]:
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    yield db_path
    # Cleanup
    Path(db_path).unlink(missing_ok=True)


def test_cas_store_initialization_memory() -> None:
    """Test CAS store can be initialized with in-memory database."""
    store = CASStore()
    assert store.db_path == ":memory:"
    store.close()


def test_cas_store_initialization_file(temp_db_path: str) -> None:
    """Test CAS store can be initialized with file database."""
    store = CASStore(temp_db_path)
    assert store.db_path == temp_db_path
    store.close()


def test_store_and_retrieve_data() -> None:
    """Test storing and retrieving data."""
    store = CASStore()

    data = {"key": "value", "number": 42}
    cid = store.store(data)

    retrieved = store.retrieve(cid)
    assert retrieved == data

    store.close()


def test_store_returns_same_cid_for_same_data() -> None:
    """Test that storing same data returns same CID."""
    store = CASStore()

    data = {"a": 1, "b": 2}
    cid1 = store.store(data)
    cid2 = store.store(data)

    assert cid1 == cid2

    store.close()


def test_store_returns_different_cid_for_different_data() -> None:
    """Test that storing different data returns different CIDs."""
    store = CASStore()

    cid1 = store.store({"a": 1})
    cid2 = store.store({"a": 2})

    assert cid1 != cid2

    store.close()


def test_retrieve_nonexistent_cid() -> None:
    """Test retrieving a nonexistent CID returns None."""
    store = CASStore()

    result = store.retrieve("nonexistent_cid")
    assert result is None

    store.close()


def test_record_call_with_result() -> None:
    """Test recording a function call with result."""
    store = CASStore()

    call_id = store.record_call(
        function_name="test_function", args={"x": 1, "y": 2}, result=3
    )

    assert isinstance(call_id, int)
    assert call_id > 0

    store.close()


def test_record_call_with_exception() -> None:
    """Test recording a function call with exception."""
    store = CASStore()

    call_id = store.record_call(
        function_name="test_function",
        args={"x": 1},
        exception={"type": "ValueError", "message": "test error"},
    )

    assert isinstance(call_id, int)
    assert call_id > 0

    store.close()


def test_get_call_record() -> None:
    """Test retrieving a call record."""
    store = CASStore()

    call_id = store.record_call(
        function_name="add", args={"a": 2, "b": 3}, result=5
    )

    record = store.get_call_record(call_id)
    assert record is not None
    assert record["id"] == call_id
    assert record["function_name"] == "add"
    assert record["args"] == {"a": 2, "b": 3}
    assert record["result"] == 5
    assert "exception" not in record

    store.close()


def test_get_call_record_with_exception() -> None:
    """Test retrieving a call record with exception."""
    store = CASStore()

    exception_info = {"type": "ZeroDivisionError", "message": "division by zero"}
    call_id = store.record_call(
        function_name="div", args={"a": 1, "b": 0}, exception=exception_info
    )

    record = store.get_call_record(call_id)
    assert record is not None
    assert record["function_name"] == "div"
    assert record["args"] == {"a": 1, "b": 0}
    assert record["exception"] == exception_info
    assert "result" not in record

    store.close()


def test_get_nonexistent_call_record() -> None:
    """Test retrieving a nonexistent call record returns None."""
    store = CASStore()

    record = store.get_call_record(999)
    assert record is None

    store.close()


def test_get_all_call_records() -> None:
    """Test retrieving all call records."""
    store = CASStore()

    # Record multiple calls
    store.record_call("func1", {"x": 1}, result=2)
    store.record_call("func2", {"y": 3}, result=4)
    store.record_call("func3", {"z": 5}, exception={"type": "Error", "message": "err"})

    records = store.get_all_call_records()
    assert len(records) == 3
    assert records[0]["function_name"] == "func1"
    assert records[1]["function_name"] == "func2"
    assert records[2]["function_name"] == "func3"

    store.close()


def test_data_persists_across_connections(temp_db_path: str) -> None:
    """Test that data persists when store is closed and reopened."""
    # First connection
    store1 = CASStore(temp_db_path)
    data = {"test": "data"}
    cid = store1.store(data)
    call_id = store1.record_call("test_func", {"arg": "value"}, result="output")
    store1.close()

    # Second connection
    store2 = CASStore(temp_db_path)
    retrieved_data = store2.retrieve(cid)
    assert retrieved_data == data

    record = store2.get_call_record(call_id)
    assert record is not None
    assert record["function_name"] == "test_func"

    store2.close()
