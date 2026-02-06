# CID el Dill

[![Build Report](https://github.com/curtcox/cideldill/actions/workflows/build-report.yml/badge.svg)](https://github.com/curtcox/cideldill/actions/workflows/build-report.yml)

CID el Dill is a Python library for debugging and inspecting applications through a request-response debugging API.

## Features

- **with_debug API**: Single entry point for enabling debugging and wrapping objects
- **Request-response control**: Server decides whether to continue, pause, skip, modify, or raise
- **Dill serialization + CID deduplication**: Efficient, content-addressed payloads
- **Automatic unpicklable object handling**: Works with complex objects from third-party libraries
- **Breakpoint web UI**: Pause and resume calls through the debug server

## Client and Server Packages

CID el Dill is split into two independent code bases:

- **cideldill-client**: the client-side debugging helpers (minimal deps: `dill`, `requests`)
- **cideldill-server**: the breakpoint server and web UI (minimal deps: `dill`, `flask`, `pygments`)

## Installation

### Quick Start

To install both the client and server with all dependencies:

```bash
./install_deps.sh
```

To install just one package:

```bash
pip install cideldill-client
pip install cideldill-server
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
from cideldill_client import with_debug

info = with_debug("ON")
print(info.is_enabled())       # True
print(info.server_url())       # http://localhost:5174
print(info.connection_status())  # connected
```

### Wrap Objects for Debugging

```python
from cideldill_client import with_debug

calculator = Calculator()
calculator = with_debug(calculator)

result = calculator.add(1, 2)  # Intercepted if debug is ON
```

### Disable Debugging

```python
from cideldill_client import with_debug

info = with_debug("OFF")
print(info.is_enabled())  # False
```

### Configure the Debug Server URL

```python
from cideldill_client import configure_debug, with_debug

configure_debug(server_url="http://localhost:5174")
with_debug("ON")
```

To enable deadlock diagnostics, add:

```python
configure_debug(
    server_url="http://localhost:5174",
    deadlock_watchdog_timeout_s=30.0,
    deadlock_watchdog_log_interval_s=60.0,
)
```

### Start the Breakpoint Server

```bash
python -m cideldill_server --port 5174
```

The server will automatically find a free port if 5174 is occupied. The actual port
is written to `~/.cideldill/port` for client auto-discovery. Then open the web UI at
the port shown in the server output (for example `http://localhost:5174/`).

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
