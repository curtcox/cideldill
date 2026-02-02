# CID el Dill

[![Build Report](https://github.com/curtcox/cideldill/actions/workflows/build-report.yml/badge.svg)](https://github.com/curtcox/cideldill/actions/workflows/build-report.yml)

CID el Dill is a Python library for debugging and inspecting applications through a request-response debugging API.

## Features

- **with_debug API**: Single entry point for enabling debugging and wrapping objects
- **Request-response control**: Server decides whether to continue, pause, skip, modify, or raise
- **Dill serialization + CID deduplication**: Efficient, content-addressed payloads
- **Breakpoint web UI**: Pause and resume calls through the debug server

## Installation

### Quick Start

To install CID el Dill with all dependencies:

```bash
./install_deps.sh
```

For development (includes testing and linting tools):

```bash
./install_deps.sh --dev
```

**Important**:
- The install script uses `python3 -m pip` by default. Make sure you run the doctor script and examples with the same Python version.
- On systems with externally-managed Python (e.g., Homebrew on macOS), the script will automatically use the `--user` flag to install to user site-packages.
- For best results, consider using a virtual environment (see below).

### Using a Virtual Environment (Recommended)

For a cleaner installation that doesn't affect your system Python, use a virtual environment:

```bash
# Create a virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate  # On Windows

# Install dependencies
./install_deps.sh --dev

# When done, deactivate
deactivate
```

### Verify Installation

After installation, verify everything is working correctly:

```bash
python3 doctor.py
```

## Usage

### Enable Debugging at Startup

```python
from cideldill import with_debug

info = with_debug("ON")
print(info.is_enabled())       # True
print(info.server_url())       # http://localhost:5000
print(info.connection_status())  # connected
```

### Wrap Objects for Debugging

```python
from cideldill import with_debug

calculator = Calculator()
calculator = with_debug(calculator)

result = calculator.add(1, 2)  # Intercepted if debug is ON
```

### Disable Debugging

```python
from cideldill import with_debug

info = with_debug("OFF")
print(info.is_enabled())  # False
```

### Configure the Debug Server URL

```python
from cideldill import configure_debug, with_debug

configure_debug(server_url="http://localhost:5000")
with_debug("ON")
```

### Start the Breakpoint Server

```bash
python -m cideldill --port 5000
```

Then open `http://localhost:5000/` to manage breakpoints and paused calls.

### Try the Interactive Demo

The `sequence_demo` example demonstrates breakpoint functionality with a simple repeating sequence:

```bash
# Quick start with breakpoints (macOS)
run/mac/sequence_demo_breakpoints

# Customize options
run/mac/sequence_demo_breakpoints --port 8080 --iterations 20 --no-browser

# Or run manually with CLI options
python examples/sequence_demo.py --debug ON --iterations 10
```

The `sequence_demo_breakpoints` script automatically:
- Starts the breakpoint server
- Sets breakpoints on key functions
- Opens the web UI in your browser
- Runs the demo with debugging enabled

## Documentation

- `docs/with_debug_api.md` for the full API reference
- `docs/breakpoints_web_ui.md` for breakpoint server usage

## License

MIT
