# Dynamic Port Discovery Implementation Plan

## Overview

**Problem**: Port conflicts (especially port 5000 with macOS AirPlay) prevent server startup on machines where users lack admin rights to stop conflicting services.

**Solution**: Server auto-discovers an available port and writes it to a discovery file. Client reads from this file to connect automatically.

**Benefits**:
- Zero port conflicts
- No admin rights required
- Works with existing HTTP architecture
- Minimal code changes (~100 lines)
- No new dependencies

---

## Design Decisions

### Discovery File Location
- **Path**: `~/.cideldill/port`
- **Why home directory**: Works without admin, persists across sessions
- **Why subdirectory**: Allows future expansion (logs, config, etc.)

### Port Selection Strategy
1. Try requested port (default 5174)
2. If occupied, try OS-assigned port (bind to port 0)
3. Write actual port to discovery file
4. Server logs actual port to stdout

### Backwards Compatibility
- Environment variable `CIDELDILL_SERVER_URL` takes precedence
- Explicit port arguments still work
- Discovery file is fallback when neither is set

---

## Implementation Steps

### Phase 1: Server Changes (TDD)

#### 1.1 Write Tests First

**File**: `tests/unit/test_port_discovery.py`
````python
"""Tests for port discovery functionality."""

import tempfile
from pathlib import Path
import pytest
from cideldill_server.port_discovery import (
    find_free_port,
    write_port_file,
    read_port_file,
    get_discovery_file_path,
)


def test_find_free_port_returns_valid_port():
    """Test that find_free_port returns a port in valid range."""
    port = find_free_port()
    assert 1024 <= port <= 65535


def test_find_free_port_is_actually_free():
    """Test that the port returned is actually available."""
    import socket
    port = find_free_port()
    
    # Should be able to bind to it
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', port))
        # Success - port was free


def test_write_port_file_creates_directory():
    """Test that write_port_file creates parent directory if needed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "subdir" / "port"
        write_port_file(5174, port_file)
        
        assert port_file.exists()
        assert port_file.read_text() == "5174"


def test_write_port_file_overwrites_existing():
    """Test that write_port_file overwrites existing file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        
        write_port_file(5174, port_file)
        assert port_file.read_text() == "5174"
        
        write_port_file(5175, port_file)
        assert port_file.read_text() == "5175"


def test_read_port_file_returns_port():
    """Test that read_port_file returns the port number."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        port_file.write_text("5174")
        
        port = read_port_file(port_file)
        assert port == 5174


def test_read_port_file_returns_none_if_missing():
    """Test that read_port_file returns None if file doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "nonexistent"
        port = read_port_file(port_file)
        assert port is None


def test_read_port_file_returns_none_if_invalid():
    """Test that read_port_file returns None if file contains invalid data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        
        # Invalid port number
        port_file.write_text("not_a_number")
        assert read_port_file(port_file) is None
        
        # Out of range
        port_file.write_text("99999")
        assert read_port_file(port_file) is None


def test_get_discovery_file_path_returns_path_in_home():
    """Test that discovery file path is in user's home directory."""
    path = get_discovery_file_path()
    assert path.parent.name == ".cideldill"
    assert path.name == "port"
    assert str(Path.home()) in str(path)
````

**File**: `tests/unit/test_breakpoint_server_port_discovery.py`
````python
"""Tests for BreakpointServer port discovery integration."""

import tempfile
import threading
import time
from pathlib import Path
import pytest
import requests
from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer


def test_server_writes_port_to_discovery_file():
    """Test that server writes its port to the discovery file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        manager = BreakpointManager()
        server = BreakpointServer(manager, port=0, port_file=port_file)
        
        # Start in background
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.5)
        
        # Discovery file should exist and contain valid port
        assert port_file.exists()
        port = int(port_file.read_text())
        assert 1024 <= port <= 65535
        
        # Server should be accessible on that port
        response = requests.get(f"http://localhost:{port}/api/breakpoints", timeout=1)
        assert response.status_code == 200
        
        server.stop()


def test_server_uses_specified_port_if_available():
    """Test that server uses specified port if available."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        manager = BreakpointManager()
        server = BreakpointServer(manager, port=5174, port_file=port_file)
        
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        time.sleep(0.5)
        
        # Should use requested port
        assert port_file.read_text() == "5174"
        
        server.stop()


def test_server_falls_back_if_port_occupied():
    """Test that server falls back to free port if requested port is occupied."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        manager1 = BreakpointManager()
        manager2 = BreakpointManager()
        
        # Start first server on port 5174
        server1 = BreakpointServer(manager1, port=5174, port_file=port_file)
        thread1 = threading.Thread(target=server1.start, daemon=True)
        thread1.start()
        time.sleep(0.5)
        
        # Try to start second server on same port
        port_file2 = Path(tmpdir) / "port2"
        server2 = BreakpointServer(manager2, port=5174, port_file=port_file2)
        thread2 = threading.Thread(target=server2.start, daemon=True)
        thread2.start()
        time.sleep(0.5)
        
        # Second server should use different port
        port1 = int(port_file.read_text())
        port2 = int(port_file2.read_text())
        assert port1 == 5174
        assert port2 != 5174
        assert port2 > 1024
        
        server1.stop()
        server2.stop()
````

#### 1.2 Create Port Discovery Module

**File**: `server/src/cideldill_server/port_discovery.py`
````python
"""Port discovery utilities for avoiding port conflicts."""

import socket
from pathlib import Path
from typing import Optional


def find_free_port() -> int:
    """Find an available port by asking the OS.
    
    Returns:
        An available port number.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def get_discovery_file_path() -> Path:
    """Get the path to the port discovery file.
    
    Returns:
        Path to ~/.cideldill/port
    """
    return Path.home() / ".cideldill" / "port"


def write_port_file(port: int, port_file: Optional[Path] = None) -> None:
    """Write the server port to the discovery file.
    
    Args:
        port: The port number to write.
        port_file: Optional custom path (default: ~/.cideldill/port).
    """
    if port_file is None:
        port_file = get_discovery_file_path()
    
    # Create parent directory if needed
    port_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Write port number
    port_file.write_text(str(port))


def read_port_file(port_file: Optional[Path] = None) -> Optional[int]:
    """Read the server port from the discovery file.
    
    Args:
        port_file: Optional custom path (default: ~/.cideldill/port).
        
    Returns:
        The port number, or None if file doesn't exist or is invalid.
    """
    if port_file is None:
        port_file = get_discovery_file_path()
    
    if not port_file.exists():
        return None
    
    try:
        port = int(port_file.read_text().strip())
        # Validate port range
        if not (1 <= port <= 65535):
            return None
        return port
    except (ValueError, OSError):
        return None
````

#### 1.3 Update BreakpointServer

**File**: `server/src/cideldill_server/breakpoint_server.py`

Add to imports:
````python
from pathlib import Path
from .port_discovery import find_free_port, write_port_file, get_discovery_file_path
````

Modify `__init__`:
````python
def __init__(
    self,
    manager: BreakpointManager,
    port: int = 5174,
    host: str = "0.0.0.0",
    debug_enabled: bool = False,
    port_file: Optional[Path] = None,
) -> None:
    self.manager = manager
    self.requested_port = port
    self.actual_port = port
    self.host = host
    self.debug_enabled = debug_enabled
    self.port_file = port_file or get_discovery_file_path()
    # ... rest of __init__
````

Modify `start`:
````python
def start(self) -> None:
    """Start the Flask server with port discovery."""
    self._running = True
    
    # Try requested port first
    try:
        self.actual_port = self.requested_port
        self._try_start_server()
    except OSError as e:
        if "Address already in use" in str(e):
            # Fallback to OS-assigned port
            print(f"Port {self.requested_port} is occupied, finding free port...")
            self.actual_port = find_free_port()
            self._try_start_server()
        else:
            raise
    
    # Write port to discovery file
    try:
        write_port_file(self.actual_port, self.port_file)
        print(f"Port written to: {self.port_file}")
    except Exception as e:
        print(f"Warning: Could not write port file: {e}")
    
    # Log actual port
    print(f"Server running on http://{self.host}:{self.actual_port}")

def _try_start_server(self) -> None:
    """Attempt to start the Flask server on actual_port."""
    self.app.run(
        host=self.host,
        port=self.actual_port,
        debug=False,
        use_reloader=False,
    )
````

Add getter:
````python
def get_port(self) -> int:
    """Get the actual port the server is running on.
    
    Returns:
        The actual port number.
    """
    return self.actual_port
````

---

### Phase 2: Client Changes (TDD)

#### 2.1 Write Tests First

**File**: `tests/unit/test_client_port_discovery.py`
````python
"""Tests for client port discovery."""

import tempfile
from pathlib import Path
import pytest
from cideldill_client.with_debug import _resolve_server_url
from cideldill_client import configure_debug


def test_resolve_server_url_uses_env_variable_first(monkeypatch):
    """Test that CIDELDILL_SERVER_URL takes precedence."""
    monkeypatch.setenv("CIDELDILL_SERVER_URL", "http://localhost:8080")
    
    url = _resolve_server_url()
    assert url == "http://localhost:8080"


def test_resolve_server_url_reads_discovery_file(monkeypatch):
    """Test that server URL is read from discovery file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        port_file.write_text("5175")
        
        monkeypatch.delenv("CIDELDILL_SERVER_URL", raising=False)
        monkeypatch.setattr(
            "cideldill_client.with_debug.get_discovery_file_path",
            lambda: port_file
        )
        
        url = _resolve_server_url()
        assert url == "http://localhost:5175"


def test_resolve_server_url_falls_back_to_default(monkeypatch):
    """Test that default URL is used if no env or discovery file."""
    monkeypatch.delenv("CIDELDILL_SERVER_URL", raising=False)
    monkeypatch.setattr(
        "cideldill_client.with_debug.get_discovery_file_path",
        lambda: Path("/nonexistent/port")
    )
    
    url = _resolve_server_url()
    assert url == "http://localhost:5174"


def test_resolve_server_url_ignores_invalid_discovery_file(monkeypatch):
    """Test that invalid discovery file is ignored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        port_file.write_text("invalid")
        
        monkeypatch.delenv("CIDELDILL_SERVER_URL", raising=False)
        monkeypatch.setattr(
            "cideldill_client.with_debug.get_discovery_file_path",
            lambda: port_file
        )
        
        url = _resolve_server_url()
        assert url == "http://localhost:5174"  # Falls back to default


def test_configured_server_url_takes_precedence(monkeypatch):
    """Test that configure_debug() takes precedence over discovery file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        port_file = Path(tmpdir) / "port"
        port_file.write_text("5175")
        
        monkeypatch.setattr(
            "cideldill_client.with_debug.get_discovery_file_path",
            lambda: port_file
        )
        
        configure_debug(server_url="http://localhost:9999")
        url = _resolve_server_url()
        assert url == "http://localhost:9999"
````

#### 2.2 Add Port Discovery to Client

**File**: `client/src/cideldill_client/port_discovery.py`
````python
"""Port discovery utilities for client."""

from pathlib import Path
from typing import Optional


def get_discovery_file_path() -> Path:
    """Get the path to the port discovery file.
    
    Returns:
        Path to ~/.cideldill/port
    """
    return Path.home() / ".cideldill" / "port"


def read_port_from_discovery_file() -> Optional[int]:
    """Read the server port from the discovery file.
    
    Returns:
        The port number, or None if file doesn't exist or is invalid.
    """
    port_file = get_discovery_file_path()
    
    if not port_file.exists():
        return None
    
    try:
        port = int(port_file.read_text().strip())
        # Validate port range
        if not (1 <= port <= 65535):
            return None
        return port
    except (ValueError, OSError):
        return None
````

#### 2.3 Update with_debug.py

**File**: `client/src/cideldill_client/with_debug.py`

Add to imports:
````python
from .port_discovery import read_port_from_discovery_file
````

Update `_resolve_server_url`:
````python
def _resolve_server_url() -> str:
    """Resolve the debug server URL with fallback priority:
    
    1. Explicit configuration via configure_debug()
    2. CIDELDILL_SERVER_URL environment variable
    3. Port discovery file (~/.cideldill/port)
    4. Default (http://localhost:5174)
    """
    # Priority 1: Explicit configuration
    if _state.server_url:
        return _state.server_url
    
    # Priority 2: Environment variable
    env_url = os.getenv("CIDELDILL_SERVER_URL")
    if env_url:
        _validate_localhost(env_url)
        return env_url
    
    # Priority 3: Discovery file
    discovered_port = read_port_from_discovery_file()
    if discovered_port:
        return f"http://localhost:{discovered_port}"
    
    # Priority 4: Default
    return "http://localhost:5174"
````

---

### Phase 3: Script Updates

#### 3.1 Update breakpoint_server Script

**File**: `run/mac/breakpoint_server`

Update the main function to show discovered port:
````python
def main():
    """Main entry point for the script."""
    args = parse_args()

    print("=" * 60)
    print("CID el Dill - Interactive Breakpoint Server")
    print("=" * 60)
    
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=args.port, debug_enabled=args.debug)
    
    print(f"\nStarting server (requested port: {args.port})...")
    print("\nNote: If port is occupied, a free port will be auto-selected.")
    print("      Port will be written to: ~/.cideldill/port")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 60)

    try:
        server.start()
        # Server will print actual port when it starts
    except KeyboardInterrupt:
        print("\n\n✓ Server stopped by user")
        return 0
    except Exception as e:
        print(f"\n✗ Error starting server: {e}", file=sys.stderr)
        return 1

    return 0
````

#### 3.2 Update sequence_demo_breakpoints Script

**File**: `run/mac/sequence_demo_breakpoints`

Update to read actual port from discovery file:
````python
def wait_for_server(port, max_attempts=30, delay=0.5):
    """Wait for the server to be ready.
    
    Args:
        port: Initial port number to try
        max_attempts: Maximum number of attempts
        delay: Delay between attempts in seconds

    Returns:
        Actual port number if server is ready, None otherwise
    """
    from pathlib import Path
    from cideldill_server.port_discovery import read_port_file
    
    port_file = Path.home() / ".cideldill" / "port"
    
    for _ in range(max_attempts):
        # Read actual port from discovery file
        actual_port = read_port_file(port_file)
        if actual_port:
            url = f"http://localhost:{actual_port}/api/breakpoints"
            try:
                response = requests.get(url, timeout=1)
                if response.status_code == 200:
                    return actual_port
            except requests.exceptions.RequestException:
                pass
        time.sleep(delay)
    return None


def main():
    """Main entry point."""
    args = parse_args()

    # ... existing setup code ...

    print(f"Starting breakpoint server (requested port {args.port})...")
    server_process = subprocess.Popen(
        [sys.executable, str(server_script), "--port", str(args.port)],
    )

    # Wait and get actual port
    print("Waiting for server to be ready...")
    actual_port = wait_for_server(args.port)
    if not actual_port:
        print("✗ Error: Server failed to start")
        server_process.terminate()
        return 1

    print(f"✓ Server is ready on port {actual_port}")
    
    # Use actual port for all subsequent connections
    ui_url = f"http://localhost:{actual_port}/"
    
    # ... rest of script uses actual_port ...
````

---

### Phase 4: Documentation Updates

#### 4.1 Update README.md

**File**: `README.md`

Update "Start the Breakpoint Server" section:
````markdown
### Start the Breakpoint Server
```bash
python -m cideldill_server --port 5174
```

The server will automatically find a free port if 5174 is occupied. The actual port is written to `~/.cideldill/port` for client auto-discovery.

Then open the web UI (check server output for actual port):
```bash
# Server will display: "Server running on http://0.0.0.0:5174"
open http://localhost:5174/
```
````

#### 4.2 Update breakpoints_web_ui.md

**File**: `docs/breakpoints_web_ui.md`

Add Port Discovery section:
````markdown
## Port Discovery

The server automatically handles port conflicts:

1. **Default behavior**: Attempts to use port 5174
2. **Conflict resolution**: If occupied, automatically selects a free port
3. **Discovery file**: Writes actual port to `~/.cideldill/port`
4. **Client auto-discovery**: Clients read the port from the discovery file

### Manual Port Selection
```bash
# Request specific port
python -m cideldill_server --port 8080

# Server will use 8080 if available, otherwise fallback to auto-assigned port
```

### Environment Variables

For explicit control, use the environment variable:
```bash
export CIDELDILL_SERVER_URL="http://localhost:8080"
```

Priority order:
1. `configure_debug(server_url=...)`
2. `CIDELDILL_SERVER_URL` environment variable
3. Port discovery file (`~/.cideldill/port`)
4. Default (`http://localhost:5174`)
````

#### 4.3 Update with_debug_api.md

**File**: `docs/with_debug_api.md`

Update "Configure Server URL" section:
````markdown
## Configure Server URL

### Automatic Discovery (Recommended)

The client automatically discovers the server port:
```python
from cideldill_client import with_debug

# No configuration needed - uses port discovery
with_debug("ON")
```

Discovery priority:
1. Explicit `configure_debug(server_url=...)`
2. `CIDELDILL_SERVER_URL` environment variable
3. Port discovery file (`~/.cideldill/port`)
4. Default (`http://localhost:5174`)

### Manual Configuration
```python
from cideldill_client import configure_debug, with_debug

# Explicit configuration (overrides discovery)
configure_debug(server_url="http://localhost:8080")
with_debug("ON")
```

### Environment Variable
```bash
export CIDELDILL_SERVER_URL="http://localhost:8080"
python my_app.py
```

The server URL must be localhost-only for security.
````

---

### Phase 5: Integration Tests

**File**: `tests/integration/test_port_discovery_integration.py`
````python
"""Integration tests for port discovery workflow."""

import subprocess
import sys
import time
from pathlib import Path
import pytest
import requests


def test_server_client_discovery_workflow():
    """Test complete workflow: server starts, client discovers port."""
    repo_root = Path(__file__).resolve().parents[2]
    server_script = repo_root / "run" / "mac" / "breakpoint_server"
    
    # Clean up discovery file
    port_file = Path.home() / ".cideldill" / "port"
    if port_file.exists():
        port_file.unlink()
    
    # Start server on default port
    server_proc = subprocess.Popen(
        [sys.executable, str(server_script), "--port", "5174"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    
    try:
        # Wait for discovery file
        max_wait = 10
        for _ in range(max_wait):
            if port_file.exists():
                break
            time.sleep(0.5)
        
        assert port_file.exists(), "Discovery file not created"
        
        # Read port
        actual_port = int(port_file.read_text())
        assert 1024 <= actual_port <= 65535
        
        # Test client can connect
        from cideldill_client.with_debug import _resolve_server_url
        url = _resolve_server_url()
        assert f"localhost:{actual_port}" in url
        
        # Verify server responds
        response = requests.get(f"http://localhost:{actual_port}/api/breakpoints")
        assert response.status_code == 200
        
    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()


def test_server_handles_port_conflict():
    """Test that server recovers from port conflict."""
    repo_root = Path(__file__).resolve().parents[2]
    server_script = repo_root / "run" / "mac" / "breakpoint_server"
    
    # Start first server on 5174
    server1 = subprocess.Popen(
        [sys.executable, str(server_script), "--port", "5174"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    
    time.sleep(1)  # Let it bind
    
    try:
        # Start second server on same port - should fallback
        server2 = subprocess.Popen(
            [sys.executable, str(server_script), "--port", "5174"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        
        time.sleep(1)
        
        try:
            # Both should be running on different ports
            port_file = Path.home() / ".cideldill" / "port"
            assert port_file.exists()
            
            # At least one server should be accessible
            # (port file shows last-started server)
            port = int(port_file.read_text())
            response = requests.get(f"http://localhost:{port}/api/breakpoints")
            assert response.status_code == 200
            
        finally:
            server2.terminate()
            try:
                server2.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server2.kill()
    finally:
        server1.terminate()
        try:
            server1.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server1.kill()


@pytest.mark.integration
def test_sequence_demo_uses_discovered_port():
    """Test that sequence_demo_breakpoints works with port discovery."""
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "run" / "mac" / "sequence_demo_breakpoints"
    
    proc = subprocess.Popen(
        [
            sys.executable,
            str(script),
            "--iterations", "1",
            "--no-browser",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    
    try:
        # Should complete successfully
        stdout, stderr = proc.communicate(timeout=30)
        assert proc.returncode == 0, f"Script failed: {stderr}"
        
        # Should mention port discovery
        output = stdout + stderr
        assert "port" in output.lower()
        
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
````

---

## Testing Checklist

### Unit Tests
- [ ] `test_find_free_port_returns_valid_port`
- [ ] `test_find_free_port_is_actually_free`
- [ ] `test_write_port_file_creates_directory`
- [ ] `test_write_port_file_overwrites_existing`
- [ ] `test_read_port_file_returns_port`
- [ ] `test_read_port_file_returns_none_if_missing`
- [ ] `test_read_port_file_returns_none_if_invalid`
- [ ] `test_get_discovery_file_path_returns_path_in_home`
- [ ] `test_server_writes_port_to_discovery_file`
- [ ] `test_server_uses_specified_port_if_available`
- [ ] `test_server_falls_back_if_port_occupied`
- [ ] `test_resolve_server_url_uses_env_variable_first`
- [ ] `test_resolve_server_url_reads_discovery_file`
- [ ] `test_resolve_server_url_falls_back_to_default`
- [ ] `test_resolve_server_url_ignores_invalid_discovery_file`
- [ ] `test_configured_server_url_takes_precedence`

### Integration Tests
- [ ] `test_server_client_discovery_workflow`
- [ ] `test_server_handles_port_conflict`
- [ ] `test_sequence_demo_uses_discovered_port`

### Manual Tests
- [ ] Start server on default port - check discovery file created
- [ ] Start server on occupied port - verify fallback
- [ ] Start two servers simultaneously - both work on different ports
- [ ] Run sequence_demo_breakpoints - verify auto-discovery
- [ ] Set CIDELDILL_SERVER_URL - verify it overrides discovery
- [ ] Delete discovery file - verify fallback to default

---

## Edge Cases to Handle

1. **Stale discovery file**: File exists but server is down
   - Solution: Client should handle connection errors gracefully
   
2. **Concurrent server starts**: Multiple servers started simultaneously
   - Solution: Each gets unique port, discovery file shows last one
   
3. **Permission errors**: Can't write to ~/.cideldill/
   - Solution: Log warning, continue without discovery file
   
4. **Discovery file corruption**: File contains garbage
   - Solution: Fallback to default port, log warning

5. **Port exhaustion**: No ports available
   - Solution: Fail with clear error message

---

## Backwards Compatibility

### What Stays the Same
- Default port is still 5174
- `--port` argument still works
- `CIDELDILL_SERVER_URL` environment variable still works
- `configure_debug(server_url=...)` still works

### What Changes
- Discovery file is now created automatically
- Port conflicts no longer prevent startup
- Clients auto-discover port without configuration

### Migration Path
No migration needed - all existing code continues to work.

---

## Success Criteria

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Server starts successfully on occupied ports
- [ ] Discovery file is created and readable
- [ ] Client connects via discovery without configuration
- [ ] Environment variable still overrides discovery
- [ ] Documentation updated
- [ ] No breaking changes to existing API

---

## Estimated Effort

- **Phase 1 (Server)**: 2 hours
- **Phase 2 (Client)**: 1 hour
- **Phase 3 (Scripts)**: 1 hour
- **Phase 4 (Docs)**: 30 minutes
- **Phase 5 (Integration)**: 1 hour
- **Testing & Polish**: 1 hour

**Total**: ~6.5 hours

---

## Notes

- Follow TDD: Write tests first, then implementation
- Commit after each phase
- Update CHANGELOG.md when complete
- Consider adding `.cideldill/` to `.gitignore` examples in docs