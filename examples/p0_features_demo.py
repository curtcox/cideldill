"""Example demonstrating all P0 real-time inspection features.

This example shows how to use:
1. Real-time observation (observers)
2. Call history filtering and searching
3. Export functionality
4. Breakpoints (pause/modify/skip)
"""

from cideldill import Interceptor


def calculate_total(items: list[dict], tax_rate: float = 0.1) -> float:
    """Calculate total price with tax."""
    subtotal = sum(item["price"] * item["quantity"] for item in items)
    return subtotal * (1 + tax_rate)


def apply_discount(amount: float, discount_percent: float) -> float:
    """Apply a discount to an amount."""
    return amount * (1 - discount_percent / 100)


def process_order(items: list[dict], discount: float = 0) -> dict:
    """Process an order with items and optional discount."""
    total = calculate_total(items)
    if discount > 0:
        total = apply_discount(total, discount)
    return {"total": total, "item_count": len(items)}


def main():
    """Demonstrate P0 features."""
    print("=" * 70)
    print("P0 Real-Time Inspection Features Demo")
    print("=" * 70)

    # Initialize interceptor
    interceptor = Interceptor()

    # =====================================================================
    # FEATURE 1: Real-time observation
    # =====================================================================
    print("\n1. REAL-TIME OBSERVATION")
    print("-" * 70)

    call_count = [0]  # Use list for closure modification

    def my_observer(event_type: str, call_data: dict):
        """Observer that prints events in real-time."""
        call_count[0] += 1
        if event_type == "call_start":
            print(f"  ⏱️  Starting: {call_data['function_name']}()")
            print(f"      Args: {call_data['args']}")
        elif event_type == "call_complete":
            print(f"  ✅ Completed: {call_data['function_name']}()")
            print(f"      Result: {call_data['result']}")
        elif event_type == "call_error":
            print(f"  ❌ Error in: {call_data['function_name']}()")
            print(f"      Exception: {call_data['exception']}")

    # Register observer
    interceptor.add_observer(my_observer)

    # Wrap functions
    wrapped_calculate = interceptor.wrap(calculate_total)
    wrapped_discount = interceptor.wrap(apply_discount)
    wrapped_process = interceptor.wrap(process_order)

    # Make some calls - observer will print them in real-time
    items = [
        {"name": "Widget", "price": 10.0, "quantity": 2},
        {"name": "Gadget", "price": 15.0, "quantity": 1},
    ]
    result = wrapped_process(items, discount=10)
    print(f"\n  Final result: {result}")

    # =====================================================================
    # FEATURE 2: Call history filtering and searching
    # =====================================================================
    print("\n\n2. CALL HISTORY FILTERING & SEARCHING")
    print("-" * 70)

    # Get all call records
    all_records = interceptor.get_call_records()
    print(f"  Total calls recorded: {len(all_records)}")

    # Filter by function name
    calc_calls = interceptor.filter_by_function("calculate_total")
    print(f"\n  Calls to 'calculate_total': {len(calc_calls)}")
    for record in calc_calls:
        print(f"    - Args: {record['args']}")
        print(f"      Result: {record['result']}")

    # Search by argument values
    print("\n  Searching for calls with discount...")
    discount_calls = interceptor.search_by_args({"discount": 10})
    for record in discount_calls:
        print(f"    - Function: {record['function_name']}")
        print(f"      Args: {record['args']}")

    # =====================================================================
    # FEATURE 3: Export functionality
    # =====================================================================
    print("\n\n3. EXPORT FUNCTIONALITY")
    print("-" * 70)

    # Export to JSON string
    json_export = interceptor.export_history(format="json")
    print(f"  Exported {len(json_export)} characters of JSON data")
    print(f"  First 200 chars: {json_export[:200]}...")

    # Could also export to file:
    # interceptor.export_history_to_file("call_history.json")

    # =====================================================================
    # FEATURE 4: Breakpoints - pause and inspect
    # =====================================================================
    print("\n\n4. BREAKPOINTS - PAUSE & INSPECT")
    print("-" * 70)

    paused_info = []

    def breakpoint_handler(call_data: dict) -> dict:
        """Handler that gets called when breakpoint is hit."""
        paused_info.append(call_data)
        print(f"  🔴 BREAKPOINT HIT: {call_data['function_name']}")
        print(f"      Args: {call_data['args']}")
        print(f"      Timestamp: {call_data['timestamp']:.3f}")
        # Continue normally
        return {"action": "continue"}

    # Set up breakpoint on calculate_total
    interceptor.set_pause_handler(breakpoint_handler)
    interceptor.set_breakpoint("calculate_total")

    print("\n  Calling function with breakpoint...")
    result = wrapped_calculate(items)
    print(f"  Result after breakpoint: {result}")

    # =====================================================================
    # FEATURE 5: Modify arguments at breakpoint
    # =====================================================================
    print("\n\n5. MODIFY ARGUMENTS AT BREAKPOINT")
    print("-" * 70)

    def modifying_handler(call_data: dict) -> dict:
        """Handler that modifies arguments."""
        print(f"  🔴 BREAKPOINT: {call_data['function_name']}")
        print(f"      Original args: {call_data['args']}")
        if call_data['function_name'] == 'apply_discount':
            # Change discount from 10% to 50%
            modified = {"amount": call_data['args']['amount'], "discount_percent": 50}
            print(f"      Modified args: {modified}")
            return {"action": "continue", "modified_args": modified}
        return {"action": "continue"}

    # Set up breakpoint with modification
    interceptor.clear_breakpoints()
    interceptor.set_pause_handler(modifying_handler)
    interceptor.set_breakpoint("apply_discount")

    print("\n  Applying 10% discount (will be changed to 50% at breakpoint)...")
    original_amount = 100.0
    result = wrapped_discount(original_amount, 10)  # Will become 50%
    print(f"  Result: ${result:.2f} (should be $50.00, not $90.00)")

    # =====================================================================
    # FEATURE 6: Skip call with fake result
    # =====================================================================
    print("\n\n6. SKIP CALL WITH FAKE RESULT")
    print("-" * 70)

    def skipping_handler(call_data: dict) -> dict:
        """Handler that skips the actual function call."""
        print(f"  🔴 BREAKPOINT: Skipping {call_data['function_name']}")
        # Return a fake result without calling the function
        return {"action": "skip", "fake_result": 42.0}

    interceptor.clear_breakpoints()
    interceptor.set_pause_handler(skipping_handler)
    interceptor.set_breakpoint("calculate_total")

    print("\n  Calling calculate_total (will be skipped)...")
    result = wrapped_calculate(items)
    print(f"  Got fake result: {result} (function was never actually called)")

    # =====================================================================
    # FEATURE 7: Pause on exceptions
    # =====================================================================
    print("\n\n7. PAUSE ON EXCEPTIONS")
    print("-" * 70)

    exception_info = []

    def exception_handler(call_data: dict) -> dict:
        """Handler called when exception occurs."""
        if "exception" in call_data:
            exception_info.append(call_data)
            print(f"  🔴 EXCEPTION BREAKPOINT: {call_data['function_name']}")
            print(f"      Exception: {call_data['exception']}")
        return {"action": "continue"}

    def failing_function(x: int) -> int:
        """Function that will raise an exception."""
        if x == 0:
            raise ValueError("Cannot be zero!")
        return 100 // x

    wrapped_failing = interceptor.wrap(failing_function)
    interceptor.clear_breakpoints()
    interceptor.set_pause_handler(exception_handler)
    interceptor.set_breakpoint_on_exception()

    print("\n  Calling function that will raise exception...")
    try:
        wrapped_failing(0)
    except ValueError as e:
        print(f"  Exception caught: {e}")
        print(f"  Breakpoint was triggered: {len(exception_info) > 0}")

    # =====================================================================
    # Summary
    # =====================================================================
    print("\n\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Total function calls: {len(interceptor.get_call_records())}")
    print(f"  Observer events received: {call_count[0]}")
    print(f"  Breakpoints hit: {len(paused_info)}")
    print(f"  Exceptions intercepted: {len(exception_info)}")
    print("\n✅ All P0 features demonstrated successfully!")

    # Cleanup
    interceptor.close()


if __name__ == "__main__":
    main()
