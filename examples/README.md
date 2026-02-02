# Examples

Simple examples demonstrating the `with_debug` API.

## Available Examples

- `with_debug_basic.py` — Basic synchronous usage.
- `with_debug_async.py` — Async method interception.
- `with_debug_builtins.py` — Built-in type wrapping.
- `sequence_demo.py` — Configurable sequence demo for testing breakpoints and remote configuration.
- `level0_calculator.py` — Calculator example for testing.

## Running Examples

### Basic Examples

```bash
python examples/with_debug_basic.py
python examples/with_debug_async.py
python examples/with_debug_builtins.py
```

### Sequence Demo with CLI Options

The `sequence_demo.py` example supports command-line arguments to customize behavior:

```bash
# Run with default settings (debug=OFF, iterations=10)
python examples/sequence_demo.py

# Enable debugging
python examples/sequence_demo.py --debug ON

# Run with custom iterations
python examples/sequence_demo.py --iterations 20

# Combine options with short flags
python examples/sequence_demo.py -d ON -i 5

# View help
python examples/sequence_demo.py --help
```

### Interactive Demo with Breakpoints (macOS)

For an interactive demonstration of breakpoint functionality:

```bash
# Start the demo with breakpoints and web UI
run/mac/sequence_demo_breakpoints

# Customize port and iterations
run/mac/sequence_demo_breakpoints --port 8080 --iterations 20

# Run without opening browser
run/mac/sequence_demo_breakpoints --no-browser
```

This script will:
1. Start the breakpoint server on the specified port
2. Set breakpoints on key functions (`whole_numbers`, `announce_say_default`, `delay_1s`)
3. Open your browser to the breakpoint UI
4. Run the sequence demo with debugging enabled

You can then examine, enable/disable, and toggle breakpoints through the web UI to see how execution pauses and resumes.
