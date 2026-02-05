"""Test to reproduce breakpoint stopping issue in sequence_demo."""

import os
import sys
import threading
import time
from pathlib import Path

import pytest
import requests

from cideldill_client import configure_debug, with_debug
from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer


def _skip_if_socket_unavailable() -> None:
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
    except PermissionError:
        pytest.skip("Socket bind not permitted in this environment")


def test_sequence_demo_actually_stops_at_breakpoints(tmp_path: Path, monkeypatch):
    """Test that running sequence_demo with breakpoints actually pauses execution.

    This simulates what the sequence_demo_breakpoints script does and verifies
    that execution stops at breakpoints.
    """
    _skip_if_socket_unavailable()
    port_file = tmp_path / "port"
    monkeypatch.setenv("CIDELDILL_PORT_FILE", str(port_file))

    # Start server
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=5002)

    server_thread = threading.Thread(target=lambda: server.start(), daemon=True)
    server_thread.start()
    server_start_deadline = time.monotonic() + 5.0
    port = 0
    while time.monotonic() < server_start_deadline:
        if port_file.exists():
            try:
                port = int(port_file.read_text().strip())
            except ValueError:
                port = 0
        if port:
            try:
                resp = requests.get(
                    f"http://localhost:{port}/api/breakpoints",
                    timeout=1,
                )
                if resp.status_code == 200:
                    break
            except requests.RequestException:
                pass
        time.sleep(0.05)
    else:
        pytest.fail("Breakpoint server did not start within 5 seconds")

    try:
        # Set breakpoints like the script does
        for func_name in ["whole_numbers", "announce_say_default", "delay_1s"]:
            response = requests.post(
                f"http://localhost:{port}/api/breakpoints",
                json={"function_name": func_name},
                timeout=5
            )
            assert response.status_code == 200

        # Verify breakpoints are set
        response = requests.get(f"http://localhost:{port}/api/breakpoints", timeout=5)
        breakpoints = response.json()["breakpoints"]
        assert "whole_numbers" in breakpoints

        # Now run a simulated sequence demo
        monkeypatch.setenv("CIDELDILL_SERVER_URL", f"http://localhost:{port}")
        configure_debug(server_url=f"http://localhost:{port}")
        with_debug("ON")

        # Import the functions from sequence_demo
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "examples"))
        from sequence_demo import whole_numbers, announce_print, delay_01s

        # Wrap them
        wrapped_whole = with_debug(whole_numbers)
        wrapped_announce = with_debug(announce_print)
        wrapped_delay = with_debug(delay_01s)

        # Call in a thread since it should block
        execution_started = threading.Event()
        execution_completed = threading.Event()

        def run_sequence():
            execution_started.set()
            value = 0
            for _ in range(2):
                value = wrapped_whole(value)
                wrapped_announce(value)
                wrapped_delay()
            execution_completed.set()

        thread = threading.Thread(target=run_sequence, daemon=True)
        thread.start()

        # Wait for execution to start
        execution_started.wait(timeout=2)
        time.sleep(0.5)  # Give it time to hit breakpoint

        # Check if there are paused executions
        response = requests.get(f"http://localhost:{port}/api/paused", timeout=5)
        paused = response.json().get("paused", [])

        # This should have paused executions if breakpoints are working
        assert len(paused) > 0, f"Expected paused executions but got: {paused}"

        # The paused execution should be for whole_numbers
        assert paused[0]["call_data"]["method_name"] == "whole_numbers"

        # Resume execution
        pause_id = paused[0]["id"]
        requests.post(
            f"http://localhost:{port}/api/paused/{pause_id}/continue",
            json={"action": "continue"},
            timeout=5
        )

        # Wait for thread to complete
        thread.join(timeout=5)

    finally:
        with_debug("OFF")
        monkeypatch.delenv("CIDELDILL_PORT_FILE", raising=False)
        monkeypatch.delenv("CIDELDILL_SERVER_URL", raising=False)


def test_breakpoint_behavior_defaults():
    """Test that breakpoints have a default behavior setting."""
    manager = BreakpointManager()

    # Check default behavior
    assert manager.get_default_behavior() == "stop"

    # Test setting behavior
    manager.set_default_behavior("go")
    assert manager.get_default_behavior() == "go"

    manager.set_default_behavior("stop")
    assert manager.get_default_behavior() == "stop"

    # Test invalid behavior
    with pytest.raises(ValueError):
        manager.set_default_behavior("invalid")


def test_behavior_affects_pausing():
    """Test that the behavior setting affects whether execution pauses."""
    manager = BreakpointManager()
    manager.add_breakpoint("test_function")

    # With "stop" behavior, should pause
    manager.set_default_behavior("stop")
    assert manager.should_pause_at_breakpoint("test_function") is True

    # With "continue" behavior, should not pause
    manager.set_default_behavior("go")
    assert manager.should_pause_at_breakpoint("test_function") is False

    # Without breakpoint, should never pause
    assert manager.should_pause_at_breakpoint("other_function") is False


def test_behavior_api_endpoints(tmp_path: Path, monkeypatch):
    """Test the behavior API endpoints."""
    _skip_if_socket_unavailable()
    port_file = tmp_path / "port"
    monkeypatch.setenv("CIDELDILL_PORT_FILE", str(port_file))

    manager = BreakpointManager()
    server = BreakpointServer(manager, port=5003)

    server_thread = threading.Thread(target=lambda: server.start(), daemon=True)
    server_thread.start()
    server_start_deadline = time.monotonic() + 5.0
    port = 0
    while time.monotonic() < server_start_deadline:
        if port_file.exists():
            try:
                port = int(port_file.read_text().strip())
            except ValueError:
                port = 0
        if port:
            try:
                resp = requests.get(f"http://localhost:{port}/api/behavior", timeout=1)
                if resp.status_code == 200:
                    break
            except requests.RequestException:
                pass
        time.sleep(0.05)
    else:
        pytest.fail("Breakpoint server did not start within 5 seconds")

    try:
        # Get default behavior
        response = requests.get(f"http://localhost:{port}/api/behavior", timeout=5)
        assert response.status_code == 200
        assert response.json()["behavior"] == "stop"

        # Set to go
        response = requests.post(
            f"http://localhost:{port}/api/behavior",
            json={"behavior": "go"},
            timeout=5,
        )
        assert response.status_code == 200
        assert response.json()["behavior"] == "go"

        # Verify it was set
        response = requests.get(f"http://localhost:{port}/api/behavior", timeout=5)
        assert response.json()["behavior"] == "go"

        # Try invalid behavior
        response = requests.post(
            f"http://localhost:{port}/api/behavior",
            json={"behavior": "invalid"},
            timeout=5
        )
        assert response.status_code == 400

    finally:
        monkeypatch.delenv("CIDELDILL_PORT_FILE", raising=False)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
