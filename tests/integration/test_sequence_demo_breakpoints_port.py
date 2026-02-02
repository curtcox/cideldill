import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import pytest
import requests


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_http_200(url: str, timeout_s: float = 10.0) -> None:
    deadline = time.time() + timeout_s
    last_exc: Optional[BaseException] = None
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=1)
            if resp.status_code == 200:
                return
        except requests.RequestException as exc:
            last_exc = exc
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for server: {url}. Last error: {last_exc}")


def _wait_for_paused(port: int, timeout_s: float = 10.0) -> dict:
    url = f"http://localhost:{port}/api/paused"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = requests.get(url, timeout=1)
        resp.raise_for_status()
        paused = resp.json().get("paused", [])
        if paused:
            return paused[0]
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for a paused execution")


def _drain_pauses_until_exit(proc: subprocess.Popen[str], port: int, timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return

        resp = requests.get(f"http://localhost:{port}/api/paused", timeout=1)
        resp.raise_for_status()
        paused = resp.json().get("paused", [])
        if not paused:
            time.sleep(0.1)
            continue

        for pause in paused:
            pause_id = pause["id"]
            cont = requests.post(
                f"http://localhost:{port}/api/paused/{pause_id}/continue",
                json={"action": "continue"},
                timeout=2,
            )
            cont.raise_for_status()
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for demo process to exit")


@pytest.mark.integration
def test_sequence_demo_breakpoints_custom_port_honors_breakpoints() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    runner = repo_root / "run" / "mac" / "sequence_demo_breakpoints"

    port = _find_free_port()

    proc = subprocess.Popen(
        [
            sys.executable,
            str(runner),
            "--port",
            str(port),
            "--iterations",
            "1",
            "--no-browser",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_for_http_200(f"http://localhost:{port}/api/breakpoints", timeout_s=10)

        # Ensure at least one breakpoint is actually hit (this is the regression signal).
        _wait_for_paused(port, timeout_s=15)
        _drain_pauses_until_exit(proc, port, timeout_s=30)
        assert proc.returncode == 0

    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.mark.integration
def test_sequence_demo_direct_env_custom_port_honors_breakpoints() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    server_script = repo_root / "run" / "mac" / "breakpoint_server"
    demo_script = repo_root / "examples" / "sequence_demo.py"

    port = _find_free_port()

    server_proc = subprocess.Popen(
        [sys.executable, str(server_script), "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_for_http_200(f"http://localhost:{port}/api/breakpoints", timeout_s=10)

        resp = requests.post(
            f"http://localhost:{port}/api/breakpoints",
            json={"function_name": "delay_1s"},
            timeout=2,
        )
        resp.raise_for_status()

        demo_env = os.environ.copy()
        demo_env["CIDELDILL_SERVER_URL"] = f"http://localhost:{port}"

        demo_proc = subprocess.Popen(
            [
                sys.executable,
                str(demo_script),
                "--debug",
                "ON",
                "--iterations",
                "1",
            ],
            env=demo_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            _wait_for_paused(port, timeout_s=15)
            _drain_pauses_until_exit(demo_proc, port, timeout_s=30)
            assert demo_proc.returncode == 0
        finally:
            if demo_proc.poll() is None:
                demo_proc.terminate()
                try:
                    demo_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    demo_proc.kill()

    finally:
        if server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_proc.kill()
