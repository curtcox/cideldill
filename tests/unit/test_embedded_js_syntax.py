"""Validate embedded JavaScript in HTML pages parses cleanly."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time

import pytest

from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer


@pytest.fixture
def server() -> BreakpointServer:
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=0)
    yield server
    server.stop()


def _extract_scripts(html: str) -> list[str]:
    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.S | re.I)


def _assert_js_parses(source: str) -> None:
    if shutil.which("node") is None:
        pytest.fail("node is required to validate embedded JavaScript syntax")
    payload = json.dumps(source)
    proc = subprocess.run(
        ["node", "-e", f"new Function({payload});"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_embedded_js_is_valid(server: BreakpointServer) -> None:
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.2)

    process_pid = 1234
    process_start_time = 456.789
    process_key = f"{process_start_time:.6f}+{process_pid}"
    server.manager.record_call({
        "call_id": "call-1",
        "method_name": "noop",
        "status": "success",
        "pretty_args": [],
        "pretty_kwargs": {},
        "signature": None,
        "call_site": {"timestamp": 1.0, "stack_trace": []},
        "process_pid": process_pid,
        "process_start_time": process_start_time,
        "process_key": process_key,
        "started_at": 1.0,
        "completed_at": 1.1,
    })

    endpoints = [
        "/",
        "/com-errors",
        "/objects",
        "/breakpoint/noop/history",
        f"/call-tree/{process_key}",
    ]

    for path in endpoints:
        response = server.test_client().get(path)
        assert response.status_code == 200
        html = response.data.decode("utf-8")
        scripts = _extract_scripts(html)
        assert scripts, f"{path} did not include any script tags"
        for script in scripts:
            _assert_js_parses(script)
