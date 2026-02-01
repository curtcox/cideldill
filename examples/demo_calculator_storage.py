#!/usr/bin/env python
"""Demo script to show calculator example with database storage.

This script demonstrates how the calculator functions store
all argument data to the database and how it can be retrieved.
"""

import tempfile
from cideldill import CASStore, Interceptor
from examples.level0_calculator import add, div, mul


def main():
    # Create a temporary database
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    print("=" * 60)
    print("Calculator Example with Database Storage")
    print("=" * 60)
    print(f"\nDatabase: {db_path}\n")

    # Create store and interceptor
    store = CASStore(db_path)
    interceptor = Interceptor(store)

    # Wrap the calculator functions
    wrapped_add = interceptor.wrap(add)
    wrapped_mul = interceptor.wrap(mul)
    wrapped_div = interceptor.wrap(div)

    # Run calculator operations
    print("Running operations...")
    print(f"add(2, 3) = {wrapped_add(2, 3)}")
    print(f"mul(4, 5) = {wrapped_mul(4, 5)}")
    print(f"div(10, 2) = {wrapped_div(10, 2)}")
    print(f"\nNested: mul(add(2, 3), 4) = {wrapped_mul(wrapped_add(2, 3), 4)}")

    # Exception case
    print("\nTesting division by zero:")
    try:
        wrapped_div(1, 0)
    except ZeroDivisionError as e:
        print(f"div(1, 0) raised ZeroDivisionError: {e}")

    # Retrieve and display stored data
    print("\n" + "=" * 60)
    print("Stored Data in Database")
    print("=" * 60)

    records = interceptor.get_call_records()
    print(f"\nTotal calls recorded: {len(records)}\n")

    for i, record in enumerate(records, 1):
        print(f"Call #{i}:")
        print(f"  Function: {record['function_name']}")
        print(f"  Arguments: {record['args']}")
        if "result" in record:
            print(f"  Result: {record['result']}")
        if "exception" in record:
            print(f"  Exception: {record['exception']}")
        print()

    # Verify persistence by reopening the database
    print("=" * 60)
    print("Verifying Data Persistence")
    print("=" * 60)

    store.close()

    # Reopen with new store instance
    store2 = CASStore(db_path)
    interceptor2 = Interceptor(store2)
    records2 = interceptor2.get_call_records()

    print(f"\nReopened database: {db_path}")
    print(f"Retrieved {len(records2)} records after reopening")
    print("✓ All data persisted successfully!")

    store2.close()

    print("\n" + "=" * 60)
    print("Demo completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
