"""Integration tests for Level 0 Calculator with CAS storage.

This test suite verifies that the calculator example correctly stores
and retrieves all argument data to/from the database using the CAS store.
"""

import tempfile
from pathlib import Path
from typing import Generator

import pytest
from cideldill import CASStore, Interceptor
from examples.level0_calculator import add, div, mul


@pytest.fixture
def temp_db_path() -> Generator[str, None, None]:
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    yield db_path
    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def cas_store(temp_db_path):
    """Create a CAS store with temporary database."""
    store = CASStore(temp_db_path)
    yield store
    store.close()


@pytest.fixture
def interceptor(cas_store):
    """Create an interceptor with the test CAS store."""
    return Interceptor(cas_store)


def test_add_stores_and_retrieves_arguments(interceptor):
    """Test that add() function stores all argument data to database."""
    # Wrap the add function
    wrapped_add = interceptor.wrap(add)

    # Call the function
    result = wrapped_add(2, 3)

    # Verify result is correct
    assert result == 5

    # Verify data was stored
    records = interceptor.get_call_records()
    assert len(records) == 1

    # Verify stored data
    record = records[0]
    assert record["function_name"] == "add"
    assert record["args"] == {"a": 2, "b": 3}
    assert record["result"] == 5
    assert "exception" not in record


def test_mul_stores_and_retrieves_arguments(interceptor):
    """Test that mul() function stores all argument data to database."""
    wrapped_mul = interceptor.wrap(mul)

    result = wrapped_mul(4, 5)

    assert result == 20

    records = interceptor.get_call_records()
    assert len(records) == 1

    record = records[0]
    assert record["function_name"] == "mul"
    assert record["args"] == {"a": 4, "b": 5}
    assert record["result"] == 20


def test_div_stores_and_retrieves_arguments(interceptor):
    """Test that div() function stores all argument data to database."""
    wrapped_div = interceptor.wrap(div)

    result = wrapped_div(10, 2)

    assert result == 5

    records = interceptor.get_call_records()
    assert len(records) == 1

    record = records[0]
    assert record["function_name"] == "div"
    assert record["args"] == {"a": 10, "b": 2}
    assert record["result"] == 5


def test_div_by_zero_stores_exception(interceptor):
    """Test that div() by zero stores exception data to database."""
    wrapped_div = interceptor.wrap(div)

    # Call should still raise exception
    with pytest.raises(ZeroDivisionError):
        wrapped_div(1, 0)

    # Verify exception was stored
    records = interceptor.get_call_records()
    assert len(records) == 1

    record = records[0]
    assert record["function_name"] == "div"
    assert record["args"] == {"a": 1, "b": 0}
    assert "exception" in record
    assert record["exception"]["type"] == "ZeroDivisionError"
    assert "result" not in record


def test_multiple_calls_all_stored(interceptor):
    """Test that multiple function calls are all stored to database."""
    wrapped_add = interceptor.wrap(add)
    wrapped_mul = interceptor.wrap(mul)
    wrapped_div = interceptor.wrap(div)

    # Make several calls
    wrapped_add(2, 3)
    wrapped_mul(4, 5)
    wrapped_div(10, 2)
    wrapped_add(7, 8)

    # Verify all calls were stored
    records = interceptor.get_call_records()
    assert len(records) == 4

    # Verify each call
    assert records[0]["function_name"] == "add"
    assert records[0]["args"] == {"a": 2, "b": 3}
    assert records[0]["result"] == 5

    assert records[1]["function_name"] == "mul"
    assert records[1]["args"] == {"a": 4, "b": 5}
    assert records[1]["result"] == 20

    assert records[2]["function_name"] == "div"
    assert records[2]["args"] == {"a": 10, "b": 2}
    assert records[2]["result"] == 5

    assert records[3]["function_name"] == "add"
    assert records[3]["args"] == {"a": 7, "b": 8}
    assert records[3]["result"] == 15


def test_nested_calls_all_stored(interceptor):
    """Test that nested function calls are all stored separately."""
    wrapped_add = interceptor.wrap(add)
    wrapped_mul = interceptor.wrap(mul)

    # Nested call: mul(add(2, 3), 4)
    inner_result = wrapped_add(2, 3)
    outer_result = wrapped_mul(inner_result, 4)

    assert outer_result == 20

    # Verify both calls were stored
    records = interceptor.get_call_records()
    assert len(records) == 2

    # Inner call
    assert records[0]["function_name"] == "add"
    assert records[0]["args"] == {"a": 2, "b": 3}
    assert records[0]["result"] == 5

    # Outer call
    assert records[1]["function_name"] == "mul"
    assert records[1]["args"] == {"a": 5, "b": 4}
    assert records[1]["result"] == 20


def test_data_persists_across_store_instances(temp_db_path):
    """Test that data persists when store is closed and reopened."""
    # First store instance - write data
    store1 = CASStore(temp_db_path)
    interceptor1 = Interceptor(store1)
    wrapped_add = interceptor1.wrap(add)
    wrapped_add(2, 3)
    store1.close()

    # Second store instance - read data
    store2 = CASStore(temp_db_path)
    interceptor2 = Interceptor(store2)
    records = interceptor2.get_call_records()

    # Verify data persisted
    assert len(records) == 1
    assert records[0]["function_name"] == "add"
    assert records[0]["args"] == {"a": 2, "b": 3}
    assert records[0]["result"] == 5

    store2.close()


def test_same_args_produce_same_cid(cas_store):
    """Test that same arguments produce the same CID (content-addressable)."""
    # Store same data twice
    cid1 = cas_store.store({"a": 2, "b": 3})
    cid2 = cas_store.store({"a": 2, "b": 3})

    # CIDs should be identical
    assert cid1 == cid2

    # Data should be deduplicated (only one entry)
    data1 = cas_store.retrieve(cid1)
    data2 = cas_store.retrieve(cid2)
    assert data1 == data2
    assert data1 == {"a": 2, "b": 3}


def test_different_args_produce_different_cids(cas_store):
    """Test that different arguments produce different CIDs."""
    cid1 = cas_store.store({"a": 2, "b": 3})
    cid2 = cas_store.store({"a": 3, "b": 2})

    # CIDs should be different
    assert cid1 != cid2

    # Data should be retrievable and correct
    assert cas_store.retrieve(cid1) == {"a": 2, "b": 3}
    assert cas_store.retrieve(cid2) == {"a": 3, "b": 2}


def test_calculator_example_full_run(interceptor):
    """Test running the full calculator example scenario from level0_calculator.py."""
    # Wrap all functions
    wrapped_add = interceptor.wrap(add)
    wrapped_mul = interceptor.wrap(mul)
    wrapped_div = interceptor.wrap(div)

    # Run the example scenarios
    # Basic operations
    assert wrapped_add(2, 3) == 5
    assert wrapped_mul(4, 5) == 20
    assert wrapped_div(10, 2) == 5

    # Nested operation
    assert wrapped_mul(wrapped_add(2, 3), 4) == 20

    # Exception case
    with pytest.raises(ZeroDivisionError):
        wrapped_div(1, 0)

    # Verify all calls were stored
    records = interceptor.get_call_records()
    assert len(records) == 6  # 3 basic + 2 nested + 1 exception

    # Verify we can retrieve all data
    for record in records:
        assert "function_name" in record
        assert "args" in record
        # Either result or exception should be present
        assert "result" in record or "exception" in record
