"""Integration tests for browser REPL round trips."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
import requests

from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer
from cideldill_server.debug_client_js import render_debug_client_js


def _skip_if_socket_unavailable() -> None:
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
    except PermissionError:
        pytest.skip("Socket bind not permitted in this environment")


def _skip_if_node_unavailable() -> None:
    if not shutil.which("node"):
        pytest.skip("node is not available")


def _start_server() -> tuple[BreakpointServer, threading.Thread, int]:
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=0)
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()

    deadline = time.monotonic() + 5.0
    port = 0
    while time.monotonic() < deadline:
        if server.is_running():
            port = server.get_port()
            if port:
                try:
                    response = requests.get(
                        f"http://localhost:{port}/api/breakpoints",
                        timeout=1,
                    )
                    if response.status_code == 200:
                        break
                except requests.RequestException:
                    pass
        time.sleep(0.05)
    else:
        pytest.fail("Breakpoint server did not start within 5 seconds")

    return server, thread, port


def _write_debug_client(tmp_path: Path, server_url: str) -> Path:
    js_path = tmp_path / "debug-client.mjs"
    js_path.write_text(render_debug_client_js(server_url), encoding="utf-8")
    return js_path


def _run_node_process(js_path: Path, script: str) -> subprocess.Popen:
    env = dict(os.environ)
    env["DEBUG_JS"] = str(js_path)
    return subprocess.Popen(
        ["node", "--input-type=module", "-e", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def _wait_for_pause(base_url: str, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = requests.get(f"{base_url}/api/paused", timeout=1)
        paused = response.json().get("paused", [])
        if paused:
            pause_id = paused[0].get("id")
            if pause_id:
                return pause_id
        time.sleep(0.05)
    pytest.fail("Timed out waiting for paused execution")


def test_browser_repl_eval_roundtrip(tmp_path: Path) -> None:
    _skip_if_socket_unavailable()
    _skip_if_node_unavailable()

    server, thread, port = _start_server()
    base_url = f"http://localhost:{port}"
    proc = None
    try:
        resp = requests.post(
            f"{base_url}/api/breakpoints",
            json={"function_name": "add"},
            timeout=5,
        )
        assert resp.status_code == 200
        resp = requests.post(
            f"{base_url}/api/breakpoints/add/after_behavior",
            json={"behavior": "go"},
            timeout=5,
        )
        assert resp.status_code == 200

        js_path = _write_debug_client(tmp_path, base_url)
        script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234, markResourceTiming: () => {} };

withDebug('ON');
function add(a, b) { return a + b; }
const result = await debugCall(add, 1, 2);
if (result !== 3) throw new Error('bad result');
"""
        proc = _run_node_process(js_path, script)

        pause_id = _wait_for_pause(base_url)
        session = requests.post(
            f"{base_url}/api/repl/start",
            json={"pause_id": pause_id},
            timeout=5,
        )
        assert session.status_code == 200
        session_id = session.json()["session_id"]

        eval_response = requests.post(
            f"{base_url}/api/repl/{session_id}/eval",
            json={"expr": "a + b"},
            timeout=10,
        )
        assert eval_response.status_code == 200
        payload = eval_response.json()
        assert payload["output"] == "3"
        assert payload["is_error"] is False

        resp = requests.post(
            f"{base_url}/api/paused/{pause_id}/continue",
            json={"action": "continue"},
            timeout=5,
        )
        assert resp.status_code == 200

        stdout, stderr = proc.communicate(timeout=10)
        assert proc.returncode == 0, stderr or stdout
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
        server.stop()
        thread.join(timeout=2)
