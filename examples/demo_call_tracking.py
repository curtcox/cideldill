#!/usr/bin/env python
"""Demo script to showcase new timestamp, callstack, and call site features.

This script demonstrates how the CID el Dill library now captures:
- Timestamps of each function call
- Call site information (file, line, code)
- Full call stack for debugging

Run this script, then open the generated HTML file to view the results.
"""

import tempfile
from pathlib import Path

from cideldill import CASStore, Interceptor
from cideldill.html_generator import generate_html_viewer


def fibonacci(n: int) -> int:
    """Calculate nth Fibonacci number (recursive)."""
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)


def factorial(n: int) -> int:
    """Calculate factorial of n."""
    if n <= 1:
        return 1
    return n * factorial(n - 1)


def main():
    """Demonstrate call tracking features."""
    # Use temp directory for output
    db_path = "/tmp/cideldill_demo.db"
    html_path = "/tmp/cideldill_demo.html"

    # Clean up previous files
    Path(db_path).unlink(missing_ok=True)
    Path(html_path).unlink(missing_ok=True)

    # Create store and interceptor
    store = CASStore(db_path)
    interceptor = Interceptor(store)

    # Wrap functions to track calls
    tracked_fib = interceptor.wrap(fibonacci)
    tracked_fact = interceptor.wrap(factorial)

    print("CID el Dill - Call Tracking Demo")
    print("=" * 50)

    # Make some calls
    print("\n1. Computing fibonacci(5)...")
    result = tracked_fib(5)
    print(f"   Result: {result}")

    print("\n2. Computing factorial(4)...")
    result = tracked_fact(4)
    print(f"   Result: {result}")

    # Close store and generate HTML
    store.close()

    print(f"\n3. Generating HTML report...")
    generate_html_viewer(
        db_path, html_path, title="CID el Dill - Call Tracking Demo"
    )

    print("\n" + "=" * 50)
    print("✓ Demo completed successfully!")
    print(f"\nGenerated files:")
    print(f"  Database: {db_path}")
    print(f"  HTML:     {html_path}")
    print(f"\nView the HTML file to see:")
    print("  • Timestamp for each call")
    print("  • Call site (file, line, code)")
    print("  • Full call stack for debugging")
    print("  • Function arguments and results")


if __name__ == "__main__":
    main()
