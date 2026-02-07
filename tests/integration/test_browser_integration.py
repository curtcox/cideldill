"""Integration tests for browser debug client round trips."""

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


def _run_node(js_path: Path, script: str) -> None:
    env = dict(os.environ)
    env["DEBUG_JS"] = str(js_path)
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_browser_debug_call_roundtrip(tmp_path: Path) -> None:
    _skip_if_socket_unavailable()
    _skip_if_node_unavailable()

    server, thread, port = _start_server()
    base_url = f"http://localhost:{port}"
    try:
        resp = requests.post(
            f"{base_url}/api/breakpoints",
            json={"function_name": "add"},
            timeout=5,
        )
        assert resp.status_code == 200
        resp = requests.post(
            f"{base_url}/api/breakpoints/add/behavior",
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
globalThis.performance = { timeOrigin: 1234 };

withDebug('ON');
function add(a, b) { return a + b; }
const result = await debugCall(add, 1, 2);
if (result !== 3) throw new Error('bad result');
"""
        _run_node(js_path, script)

        history = requests.get(
            f"{base_url}/api/breakpoints/add/history",
            timeout=5,
        ).json()["history"]
        assert history, "expected history entry"
        call_data = history[0].get("call_data") or {}
        assert call_data.get("method_name") == "add"
        assert call_data.get("process_pid") == 0
    finally:
        server.stop()
        thread.join(timeout=2)
