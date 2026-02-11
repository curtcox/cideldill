"""End-to-end MCP integration tests."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import socket
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _run(coro):
    return asyncio.run(coro)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _pythonpath() -> str:
    root = _repo_root()
    parts = [str(root / "server" / "src"), str(root / "client" / "src")]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        parts.append(existing)
    return os.pathsep.join(parts)


def _server_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = _pythonpath()
    env["CIDELDILL_PORT_FILE"] = str(tmp_path / "port")
    return env


async def _with_stdio_session(args: list[str], env: dict[str, str]):
    params = StdioServerParameters(command=sys.executable, args=args, env=env)
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return session


@pytest.mark.integration
def test_mcp_stdio_initialize(tmp_path: Path) -> None:
    async def _exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "cideldill_server", "--mcp", "--memory", "--port", "0"],
            env=_server_env(tmp_path),
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

    _run(_exercise())


@pytest.mark.integration
def test_mcp_add_and_list_breakpoints(tmp_path: Path) -> None:
    async def _exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "cideldill_server", "--mcp", "--memory", "--port", "0"],
            env=_server_env(tmp_path),
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                add_result = await session.call_tool(
                    "breakpoint_add", {"function_name": "process"}
                )
                payload = json.loads(add_result.content[0].text)
                assert payload["status"] == "ok"

                list_result = await session.call_tool("breakpoint_list_breakpoints", {})
                payload = json.loads(list_result.content[0].text)
                assert "process" in payload["breakpoints"]

    _run(_exercise())


@pytest.mark.integration
def test_mcp_resource_read(tmp_path: Path) -> None:
    async def _exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "cideldill_server", "--mcp", "--memory", "--port", "0"],
            env=_server_env(tmp_path),
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                resource = await session.read_resource("breakpoint://status")
                payload = json.loads(resource.contents[0].text)
                assert "breakpoints" in payload

    _run(_exercise())


@pytest.mark.integration
def test_mcp_prompt_get(tmp_path: Path) -> None:
    async def _exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "cideldill_server", "--mcp", "--memory", "--port", "0"],
            env=_server_env(tmp_path),
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                prompt = await session.get_prompt("debug-session-start", {})
                assert prompt.messages

    _run(_exercise())


def _start_sse_server(tmp_path: Path):
    env = _server_env(tmp_path)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "cideldill_server",
            "--mcp-sse",
            "--memory",
            "--port",
            "0",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    port_file = Path(env["CIDELDILL_PORT_FILE"])
    deadline = time.time() + 10
    while time.time() < deadline:
        if port_file.exists():
            port_text = port_file.read_text().strip()
            if port_text.isdigit():
                return proc, int(port_text)
        time.sleep(0.05)
    proc.terminate()
    raise RuntimeError("SSE server did not start")


def _can_bind_local_port() -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.close()
        return True
    except PermissionError:
        return False


@pytest.mark.integration
def test_mcp_sse_initialize(tmp_path: Path) -> None:
    try:
        from mcp.client.sse import sse_client
    except Exception:
        pytest.skip("mcp sse client not available")
    if not _can_bind_local_port():
        pytest.skip("socket binding not permitted in this environment")

    proc, port = _start_sse_server(tmp_path)
    url = f"http://127.0.0.1:{port}/mcp/sse"

    async def _exercise():
        async with sse_client(url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

    try:
        _run(_exercise())
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
