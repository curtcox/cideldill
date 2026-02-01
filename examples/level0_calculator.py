"""Level 0 Calculator Example.

This example demonstrates basic function interception and content-addressable storage (CAS)
of primitives. It provides simple arithmetic operations that can be wrapped with interceptors
to record call args, return values, and exceptions.

Purpose:
    - Verify basic interception capabilities
    - Test CAS storage of primitive values
    - Record exceptions (division by zero)
    - Verify CIDs are stable (same args → same CID)
    - Verify primitives serialize/deserialize correctly

Functions:
    add: Add two integers
    mul: Multiply two integers
    div: Integer division (can raise ZeroDivisionError)
"""


def add(a: int, b: int) -> int:
    """Add two integers.

    Args:
        a: First integer
        b: Second integer

    Returns:
        The sum of a and b
    """
    return a + b


def mul(a: int, b: int) -> int:
    """Multiply two integers.

    Args:
        a: First integer
        b: Second integer

    Returns:
        The product of a and b
    """
    return a * b


def div(a: int, b: int) -> int:
    """Integer division of two integers.

    Args:
        a: Numerator
        b: Denominator

    Returns:
        The integer division result of a // b

    Raises:
        ZeroDivisionError: If b is zero
    """
    return a // b


if __name__ == "__main__":
    # Example usage demonstrating the calculator functions
    print("Level 0 Calculator Example")
    print("=" * 40)

    # Basic operations
    print(f"add(2, 3) = {add(2, 3)}")
    print(f"mul(4, 5) = {mul(4, 5)}")
    print(f"div(10, 2) = {div(10, 2)}")

    # Nested operations
    print(f"\nNested: mul(add(2, 3), 4) = {mul(add(2, 3), 4)}")

    # Exception case
    print("\nTesting division by zero:")
    try:
        result = div(1, 0)
        print(f"div(1, 0) = {result}")
    except ZeroDivisionError as e:
        print(f"div(1, 0) raised ZeroDivisionError: {e}")

    print("\n" + "=" * 40)
    print("All operations completed!")
