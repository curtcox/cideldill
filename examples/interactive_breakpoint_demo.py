#!/usr/bin/env python3
"""Interactive breakpoint demo.

This demo shows how to use interactive breakpoints with the web UI.
Start the breakpoint server first:
    python -m cideldill.breakpoint_server

Then run this demo:
    python examples/interactive_breakpoint_demo.py
"""

import tempfile
import threading
import time
from pathlib import Path

from cideldill import CASStore, Interceptor, BreakpointManager
from cideldill.html_generator import generate_html_viewer


def sync_breakpoints(manager, interceptor):
    """Sync breakpoints from manager to interceptor."""
    print("🔄 Breakpoint sync thread started")
    while True:
        try:
            current_breakpoints = set(manager.get_breakpoints())
            interceptor_breakpoints = interceptor.get_breakpoints()

            # Add new breakpoints
            for bp in current_breakpoints - interceptor_breakpoints:
                interceptor.set_breakpoint(bp)
                print(f"✅ Breakpoint set on {bp}()")

            # Remove deleted breakpoints
            for bp in interceptor_breakpoints - current_breakpoints:
                interceptor.remove_breakpoint(bp)
                print(f"❌ Breakpoint removed from {bp}()")

            time.sleep(0.5)
        except Exception as e:
            print(f"Error in sync: {e}")


def main():
    """Run the demo."""
    print("=" * 60)
    print("CID el Dill - Interactive Breakpoint Demo")
    print("=" * 60)
    
    # Create temporary database
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    print(f"\n📁 Database: {db_path}")
    
    # Setup components
    store = CASStore(db_path)
    manager = BreakpointManager()
    interceptor = Interceptor(store)
    
    # Configure pause handler
    def pause_handler(call_data):
        """Handle paused execution."""
        pause_id = manager.add_paused_execution(call_data)
        func_name = call_data.get('function_name', 'unknown')
        args = call_data.get('args', {})
        
        print(f"\n⏸️  PAUSED at {func_name}() with args: {args}")
        print(f"   Pause ID: {pause_id}")
        print(f"   🌐 View in web UI: http://localhost:5000/")
        print(f"   Waiting for user action (60s timeout)...")
        
        # Wait for action from web UI
        action = manager.wait_for_resume_action(pause_id, timeout=60.0)
        
        if action is None:
            print(f"   ⏱️  Timeout - continuing automatically")
            action = {"action": "continue"}
        else:
            action_type = action.get('action', 'continue')
            print(f"   ✅ Action received: {action_type}")
            if action_type == "skip":
                print(f"   ⏭️  Skipping execution")
            elif action_type == "continue" and "modified_args" in action:
                print(f"   🔧 Modified args: {action['modified_args']}")
        
        return action
    
    interceptor.set_pause_handler(pause_handler)
    
    # Start breakpoint sync thread
    sync_thread = threading.Thread(
        target=sync_breakpoints,
        args=(manager, interceptor),
        daemon=True
    )
    sync_thread.start()
    
    # Define some functions to debug
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b
    
    def multiply(a: int, b: int) -> int:
        """Multiply two numbers."""
        return a * b
    
    def calculate_area(width: int, height: int) -> int:
        """Calculate rectangle area."""
        return multiply(width, height)
    
    # Wrap functions
    wrapped_add = interceptor.wrap(add)
    wrapped_multiply = interceptor.wrap(multiply)
    wrapped_calculate_area = interceptor.wrap(calculate_area)
    
    print("\n🚀 Application started!")
    print("\n📍 Instructions:")
    print("   1. Open http://localhost:5000/ in your browser")
    print("   2. Navigate to the Breakpoints page")
    print("   3. Set breakpoints on functions (add, multiply, calculate_area)")
    print("   4. Watch this terminal for pause notifications")
    print("   5. Use the web UI to continue/skip execution")
    print("\n⏰ Demo will run for 60 seconds...\n")
    
    start_time = time.time()
    iteration = 0
    
    # Run demo loop
    while time.time() - start_time < 60:
        iteration += 1
        print(f"\n--- Iteration {iteration} ---")
        
        try:
            # Execute some operations
            result1 = wrapped_add(iteration, iteration + 1)
            print(f"✓ add({iteration}, {iteration + 1}) = {result1}")
            
            time.sleep(1)
            
            result2 = wrapped_multiply(iteration, 2)
            print(f"✓ multiply({iteration}, 2) = {result2}")
            
            time.sleep(1)
            
            if iteration % 3 == 0:
                result3 = wrapped_calculate_area(iteration, iteration)
                print(f"✓ calculate_area({iteration}, {iteration}) = {result3}")
            
            time.sleep(2)
            
        except KeyboardInterrupt:
            print("\n\n⏹️  Demo interrupted by user")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
    
    print("\n\n🏁 Demo complete!")
    
    # Generate HTML viewer
    output_dir = Path("/tmp/cideldill_breakpoint_demo")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "viewer.html"
    
    print(f"\n📄 Generating HTML viewer...")
    store.close()
    generate_html_viewer(db_path, str(output_path), title="Breakpoint Demo")
    
    print(f"\n✅ HTML viewer generated at: {output_dir}")
    print(f"   Open: file://{output_dir}/breakpoints.html")
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
