#!/usr/bin/env python3
"""Demo script to generate and show web UI navigation features."""

import tempfile
from pathlib import Path

from cideldill import CASStore, Interceptor
from cideldill.html_generator import generate_html_viewer


def sample_add(a: int, b: int) -> int:
    """Simple addition function."""
    return a + b


def sample_multiply(a: int, b: int) -> int:
    """Simple multiplication function."""
    return a * b


def sample_divide(a: int, b: int) -> float:
    """Simple division function."""
    return a / b


def main():
    """Run demo and generate HTML."""
    print("=" * 60)
    print("CID el Dill Web UI Demo")
    print("=" * 60)
    
    # Create temporary database
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    print(f"\nDatabase: {db_path}")
    
    # Create store and interceptor
    store = CASStore(db_path)
    interceptor = Interceptor(store)
    
    # Wrap functions
    wrapped_add = interceptor.wrap(sample_add)
    wrapped_multiply = interceptor.wrap(sample_multiply)
    wrapped_divide = interceptor.wrap(sample_divide)
    
    # Execute some operations
    print("\nExecuting function calls...")
    wrapped_add(2, 3)
    wrapped_multiply(4, 5)
    wrapped_add(10, 20)
    wrapped_multiply(3, 7)
    wrapped_divide(10, 2)
    
    # Nested call
    result = wrapped_add(wrapped_multiply(2, 3), 4)
    print(f"Result of nested call: {result}")
    
    # Exception case
    print("\nTesting division by zero...")
    try:
        wrapped_divide(1, 0)
    except ZeroDivisionError:
        print("Caught ZeroDivisionError as expected")
    
    store.close()
    
    # Generate HTML
    output_dir = Path("/tmp/cideldill_demo")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "viewer.html"
    
    print(f"\nGenerating HTML files...")
    generate_html_viewer(db_path, str(output_path), title="CID el Dill Demo")
    
    print(f"\nHTML files generated in: {output_dir}")
    print("\nGenerated pages:")
    for html_file in sorted(output_dir.glob("*.html")):
        size = html_file.stat().st_size
        print(f"  - {html_file.name} ({size:,} bytes)")
    
    print("\n" + "=" * 60)
    print("To view the web UI, open these files in a browser:")
    print("=" * 60)
    print(f"\nHome Page:       file://{output_dir}/index.html")
    print(f"Timeline:        file://{output_dir}/timeline.html")
    print(f"Source Files:    file://{output_dir}/sources.html")
    print(f"Call Stacks:     file://{output_dir}/callstacks.html")
    print(f"Breakpoints:     file://{output_dir}/breakpoints.html")
    print(f"Main Viewer:     file://{output_dir}/viewer.html")
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
