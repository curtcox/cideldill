# Integration Tests for Calculator Example

This directory contains integration tests that verify the calculator example correctly stores and retrieves all argument data to/from the database.

## What's Being Tested

The integration tests verify that:

1. **Function calls are intercepted**: When calculator functions (`add`, `mul`, `div`) are wrapped, their calls are captured
2. **Arguments are stored**: All function arguments are stored in the database with content-addressable identifiers (CIDs)
3. **Results are stored**: Return values are stored and associated with their function calls
4. **Exceptions are stored**: When functions raise exceptions (e.g., division by zero), the exception details are recorded
5. **Data is retrievable**: All stored data can be retrieved from the database by call ID
6. **Data persists**: Data remains in the database even after closing and reopening connections
7. **Content-addressable storage works**: Same data produces the same CID (deduplication)

## Test Files

- `test_calculator_integration.py`: Main integration test suite with 10 comprehensive tests

## Running the Tests

```bash
# Run just the integration tests
pytest tests/integration/

# Run with verbose output
pytest tests/integration/ -v

# Run with coverage
pytest tests/integration/ --cov=cideldill
```

## Architecture

The integration tests use:

- **CASStore**: SQLite-based content-addressable storage for function call data
- **Interceptor**: Wraps functions to capture calls, arguments, results, and exceptions
- **SQLite Database**: Persistent storage with two tables:
  - `cas_objects`: Stores content with CID keys
  - `call_records`: Links function calls to their arguments, results, and exceptions via CIDs

## Example Usage

See `examples/demo_calculator_storage.py` for a complete demonstration of how the calculator functions are wrapped and their data stored:

```bash
PYTHONPATH=. python examples/demo_calculator_storage.py
```

## Test Coverage

The integration tests achieve 100% code coverage of:
- `src/cideldill/cas_store.py`
- `src/cideldill/interceptor.py`

Combined with unit tests, the entire codebase has 100% test coverage.
