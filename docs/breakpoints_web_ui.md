# Interactive Breakpoints in Web UI

This guide explains how to use the interactive breakpoint management features in the CID el Dill web UI.

## Overview

CID el Dill provides an interactive web interface for setting breakpoints, monitoring paused executions, and controlling program flow in real-time. This allows you to:

- **Set breakpoints** on specific functions via the web UI
- **Get notified** when execution hits a breakpoint
- **See paused executions** with their arguments and call context
- **Examine values** at each breakpoint before deciding how to proceed
- **Continue execution** with options to modify behavior

## Important Notes

- **Server Shutdown**: The Flask development server doesn't support clean programmatic shutdown. To stop the server, use Ctrl+C in the terminal. For production use, consider a proper WSGI server like Gunicorn.
- **Development Tool**: This is designed for development and debugging. Not recommended for production environments.
- **Thread Safety**: All components are thread-safe and can handle concurrent requests.

## Architecture

The interactive breakpoint system consists of three main components:

1. **BreakpointManager**: Manages breakpoint state and paused executions
2. **BreakpointServer**: Flask-based web server with REST API
3. **Interactive HTML UI**: JavaScript-powered interface for user interaction

## Quick Start

### 1. Start the Breakpoint Server

First, start the web server that handles breakpoint management:

```bash
python -m cideldill.breakpoint_server
```

Or specify a custom port:

```bash
python -m cideldill.breakpoint_server --port 8080
```

You should see:

```
============================================================
CID el Dill - Interactive Breakpoint Server
============================================================

Starting server on 0.0.0.0:5000

Web UI available at:
  http://localhost:5000/

API Endpoints:
  GET    /api/breakpoints        - List breakpoints
  POST   /api/breakpoints        - Add breakpoint
  DELETE /api/breakpoints/<name> - Remove breakpoint
  GET    /api/paused             - List paused executions
  POST   /api/paused/<id>/continue - Continue execution

Press Ctrl+C to stop the server
============================================================
```

### 2. Configure Your Application

In your Python code, integrate the breakpoint manager with the interceptor:

```python
from cideldill import CASStore, Interceptor, BreakpointManager
from cideldill.breakpoint_server import BreakpointServer
import threading

# Create store and manager
store = CASStore("my_app.db")
manager = BreakpointManager()
interceptor = Interceptor(store)

# Set up the pause handler to use the manager
def pause_handler(call_data):
    # Add to paused executions
    pause_id = manager.add_paused_execution(call_data)
    
    # Wait for user action (with timeout)
    action = manager.wait_for_resume_action(pause_id, timeout=300.0)
    
    # Default to continue if timeout
    if action is None:
        action = {"action": "continue"}
    
    return action

interceptor.set_pause_handler(pause_handler)

# Sync breakpoints from manager to interceptor
def sync_breakpoints():
    """Periodically sync breakpoints from web UI to interceptor."""
    import time
    while True:
        for func_name in manager.get_breakpoints():
            interceptor.set_breakpoint(func_name)
        time.sleep(1)

# Start background thread to sync breakpoints
sync_thread = threading.Thread(target=sync_breakpoints, daemon=True)
sync_thread.start()

# Wrap your functions
def calculate(x, y):
    return x + y

wrapped_calculate = interceptor.wrap(calculate)

# Use the wrapped function
result = wrapped_calculate(10, 20)
```

### 3. Generate and Open the Web UI

Generate the HTML viewer with your execution data:

```python
from cideldill.html_generator import generate_html_viewer

generate_html_viewer("my_app.db", "/path/to/output/viewer.html")
```

Then open `/path/to/output/breakpoints.html` in your web browser.

## Using the Web Interface

### Setting Breakpoints

1. Open the `breakpoints.html` page in your browser
2. You'll see a list of all functions that have been called
3. Click "➕ Set Breakpoint" on any function
4. The button will change to "❌ Remove Breakpoint" and show a "🔴 Active" indicator

### Viewing Paused Executions

When your code hits a breakpoint:

1. The execution will pause
2. The "Paused Executions" section will show:
   - Function name and time it was paused
   - All arguments passed to the function
   - Call stack information

### Continuing Execution

For each paused execution, you have two options:

1. **▶️ Continue**: Resume normal execution with the original arguments
2. **⏭️ Skip**: Skip the function call entirely

Click the appropriate button to control execution flow.

## Advanced Usage

### Modifying Arguments

You can modify arguments before continuing execution using the REST API directly:

```bash
curl -X POST http://localhost:5000/api/paused/<pause_id>/continue \
  -H "Content-Type: application/json" \
  -d '{
    "action": "continue",
    "modified_args": {
      "x": 100,
      "y": 200
    }
  }'
```

### Forcing Exceptions

You can force an exception to be raised:

```bash
curl -X POST http://localhost:5000/api/paused/<pause_id>/continue \
  -H "Content-Type: application/json" \
  -d '{
    "action": "raise",
    "exception": {
      "type": "ValueError",
      "message": "Forced error for testing"
    }
  }'
```

### Providing Fake Results

You can skip execution and provide a fake return value:

```bash
curl -X POST http://localhost:5000/api/paused/<pause_id>/continue \
  -H "Content-Type: application/json" \
  -d '{
    "action": "skip",
    "fake_result": 999
  }'
```

## REST API Reference

### GET /api/breakpoints

List all active breakpoints.

**Response:**
```json
{
  "breakpoints": ["function1", "function2"]
}
```

### POST /api/breakpoints

Add a new breakpoint.

**Request:**
```json
{
  "function_name": "my_function"
}
```

**Response:**
```json
{
  "status": "ok",
  "function_name": "my_function"
}
```

### DELETE /api/breakpoints/<function_name>

Remove a breakpoint.

**Response:**
```json
{
  "status": "ok",
  "function_name": "my_function"
}
```

### GET /api/paused

List all currently paused executions.

**Response:**
```json
{
  "paused": [
    {
      "id": "uuid-string",
      "call_data": {
        "function_name": "calculate",
        "args": {"x": 10, "y": 20},
        "timestamp": 1234567890.123
      },
      "paused_at": 1234567890.456
    }
  ]
}
```

### POST /api/paused/<pause_id>/continue

Continue a paused execution.

**Request:**
```json
{
  "action": "continue"
}
```

**Response:**
```json
{
  "status": "ok",
  "pause_id": "uuid-string"
}
```

## Troubleshooting

### Server Not Connected

If the web UI shows "🔴 Not Connected":

1. Make sure the breakpoint server is running
2. Check that it's listening on the expected port (default: 5000)
3. Verify no firewall is blocking the connection
4. Check browser console for CORS or network errors

### Breakpoints Not Triggering

If breakpoints aren't pausing execution:

1. Verify the pause_handler is set on the interceptor
2. Ensure the sync_breakpoints loop is running
3. Check that the function is wrapped with interceptor.wrap()
4. Confirm the breakpoint is actually set (check "🔴 Active" indicator)

### Execution Stuck

If execution is stuck waiting at a breakpoint:

1. Check the "Paused Executions" section in the web UI
2. Click "Continue" or "Skip" to resume
3. If the UI is not responding, restart the breakpoint server
4. Consider using a shorter timeout in wait_for_resume_action()

## Best Practices

1. **Use Timeouts**: Always set reasonable timeouts in `wait_for_resume_action()` to prevent indefinite hangs
2. **Background Server**: Run the breakpoint server in a separate process or terminal
3. **Polling Interval**: The UI polls every second for updates - adjust if needed
4. **Thread Safety**: The BreakpointManager is thread-safe, but be careful with custom modifications
5. **Development Only**: Use interactive breakpoints primarily for development and debugging, not production

## Example: Complete Integration

Here's a complete example showing all the pieces together:

```python
#!/usr/bin/env python3
"""Example of interactive breakpoint usage."""

import threading
import time
from cideldill import CASStore, Interceptor, BreakpointManager

def main():
    # Setup
    store = CASStore("debug.db")
    manager = BreakpointManager()
    interceptor = Interceptor(store)
    
    # Configure pause handler
    def pause_handler(call_data):
        pause_id = manager.add_paused_execution(call_data)
        print(f"⏸️  Paused at {call_data['function_name']}()")
        print(f"    Check web UI: http://localhost:5000/")
        
        action = manager.wait_for_resume_action(pause_id, timeout=60.0)
        if action is None:
            print("    Timeout - continuing automatically")
            action = {"action": "continue"}
        else:
            print(f"    Action received: {action['action']}")
        
        return action
    
    interceptor.set_pause_handler(pause_handler)
    
    # Sync breakpoints
    def sync_breakpoints():
        while True:
            current_breakpoints = set(manager.get_breakpoints())
            interceptor_breakpoints = interceptor.get_breakpoints()

            # Add new breakpoints
            for bp in current_breakpoints - interceptor_breakpoints:
                interceptor.set_breakpoint(bp)

            # Remove deleted breakpoints
            for bp in interceptor_breakpoints - current_breakpoints:
                interceptor.remove_breakpoint(bp)

            time.sleep(1)
    
    sync_thread = threading.Thread(target=sync_breakpoints, daemon=True)
    sync_thread.start()
    
    # Your application code
    def add(a, b):
        return a + b
    
    def multiply(a, b):
        return a * b
    
    wrapped_add = interceptor.wrap(add)
    wrapped_multiply = interceptor.wrap(multiply)
    
    print("\n🚀 Application started!")
    print("📍 Set breakpoints via web UI: http://localhost:5000/")
    print("\n")
    
    # Run some operations
    for i in range(10):
        result1 = wrapped_add(i, i + 1)
        result2 = wrapped_multiply(i, 2)
        print(f"Iteration {i}: add={result1}, mul={result2}")
        time.sleep(2)
    
    store.close()

if __name__ == "__main__":
    main()
```

Save this as `breakpoint_demo.py`, start the server in one terminal, and run the demo in another.

## See Also

- [Interceptor API Reference](../README.md#interceptor)
- [P0 Implementation Summary](../P0_IMPLEMENTATION_SUMMARY.md)
- [Web UI Navigation Guide](../README.md#web-ui)
