"""Integration tests for breakpoint server DB selection."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import pytest

pytest.importorskip("requests")


def _read_port(port_file: Path) -> Optional[int]:
    try:
        return int(port_file.read_text())
    except (OSError, ValueError):
        return None


def _wait_for_port_file(port_file: Path, timeout: float = 10.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_file.exists():
            port = _read_port(port_file)
            if port is not None:
                return port
        time.sleep(0.2)
    raise AssertionError("Discovery file not created")


def _skip_if_socket_unavailable() -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
    except PermissionError:
        pytest.skip("Socket bind not permitted in this environment")


def _start_server(tmp_path: Path, extra_args: list[str]) -> tuple[subprocess.Popen, Path, dict[str, str]]:
    repo_root = Path(__file__).resolve().parents[2]
    server_script = repo_root / "run" / "mac" / "breakpoint_server"
    port_file = tmp_path / "port"

    env = os.environ.copy()
    env["CIDELDILL_PORT_FILE"] = str(port_file)
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [sys.executable, str(server_script), "--port", "0", *extra_args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    _wait_for_port_file(port_file)
    return proc, port_file, env


def _stop_server(proc: subprocess.Popen) -> tuple[str, str]:
    proc.terminate()
    try:
        return proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.communicate(timeout=5)


@pytest.mark.integration
def test_breakpoint_server_uses_default_disk_db(tmp_path: Path) -> None:
    _skip_if_socket_unavailable()
    repo_root = Path(__file__).resolve().parents[2]
    db_dir = repo_root / ".cideldill" / "breakpoint_dbs"
    before = set(db_dir.glob("*.sqlite3")) if db_dir.exists() else set()

    proc, port_file, _env = _start_server(tmp_path, [])

    try:
        deadline = time.time() + 5
        new_files: set[Path] = set()
        while time.time() < deadline:
            after = set(db_dir.glob("*.sqlite3")) if db_dir.exists() else set()
            new_files = after - before
            if new_files:
                break
            time.sleep(0.2)
        assert new_files, "Expected a new disk DB file to be created"
    finally:
        stdout, stderr = _stop_server(proc)
        if port_file.exists():
            port_file.unlink()

    db_path = sorted(new_files)[-1]
    assert db_path.exists()
    output = stdout + stderr
    assert "Database:" in output
    assert str(db_path) in output


@pytest.mark.integration
def test_breakpoint_server_respects_db_path(tmp_path: Path) -> None:
    _skip_if_socket_unavailable()
    db_path = tmp_path / "custom_breakpoints.sqlite3"

    proc, port_file, _env = _start_server(tmp_path, ["--db", str(db_path)])

    try:
        deadline = time.time() + 5
        while time.time() < deadline and not db_path.exists():
            time.sleep(0.2)
        assert db_path.exists()
    finally:
        stdout, stderr = _stop_server(proc)
        if port_file.exists():
            port_file.unlink()

    output = stdout + stderr
    assert "Database:" in output
    assert str(db_path) in output


@pytest.mark.integration
def test_breakpoint_server_supports_in_memory_db(tmp_path: Path) -> None:
    _skip_if_socket_unavailable()
    repo_root = Path(__file__).resolve().parents[2]
    db_dir = repo_root / ".cideldill" / "breakpoint_dbs"
    before = set(db_dir.glob("*.sqlite3")) if db_dir.exists() else set()

    proc, port_file, _env = _start_server(tmp_path, ["--db", ":memory:"])

    try:
        time.sleep(0.5)
    finally:
        stdout, stderr = _stop_server(proc)
        if port_file.exists():
            port_file.unlink()

    after = set(db_dir.glob("*.sqlite3")) if db_dir.exists() else set()
    assert after == before
    output = stdout + stderr
    assert "Database:" in output
    assert ":memory:" in output
