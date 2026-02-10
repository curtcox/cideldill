"""Integration test for placeholder payloads flowing through DebugProxy."""

from __future__ import annotations

import json
import re
import threading
import time

import pytest
import requests

from cideldill_client import configure_debug, with_debug
from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer


class ExplodingGetState:
    def __init__(self, value: int):
        self.value = value

    def __getstate__(self):
        raise TypeError("boom")

    def __setstate__(self, state):
        return None


@pytest.mark.integration
def test_debug_proxy_sends_placeholder_payloads(monkeypatch, tmp_path):
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
    except PermissionError:
        pytest.skip("Socket bind not permitted in this environment")

    port_file = tmp_path / "port"
    monkeypatch.setenv("CIDELDILL_PORT_FILE", str(port_file))

    manager = BreakpointManager()
    server = BreakpointServer(manager, port=0)
    server_thread = threading.Thread(target=server.start, daemon=True)
    server_thread.start()
    server_start_deadline = time.monotonic() + 5.0
    port = 0
    while time.monotonic() < server_start_deadline:
        if server.is_running():
            port = server.get_port()
            if port:
                try:
                    resp = requests.get(f"http://localhost:{port}/api/breakpoints", timeout=1)
                    if resp.status_code == 200:
                        break
                except requests.RequestException:
                    pass
        time.sleep(0.05)
    else:
        pytest.fail("Breakpoint server did not start within 5 seconds")

    try:
        import importlib

        from cideldill_client.debug_client import DebugClient

        class LocalDebugClient(DebugClient):
            flask_client = server.test_client()

            def check_connection(self) -> None:
                return None

            def register_function(self, function_name, signature=None, **_):
                return None

            def _post_json(self, path, payload):
                response = self.flask_client.post(path, json=payload)
                return response.get_json()

            def _post_json_allowing_cid_errors(self, path, payload):
                response = self.flask_client.post(path, json=payload)
                return response.get_json()

            def _get_json(self, path):
                response = self.flask_client.get(path)
                return response.get_json()

        with_debug_module = importlib.import_module("cideldill_client.with_debug")
        monkeypatch.setattr(with_debug_module, "DebugClient", LocalDebugClient)

        configure_debug(server_url=f"http://localhost:{port}")
        with_debug("ON")

        def echo(arg):
            return arg

        wrapped = with_debug(echo)
        result_holder: dict[str, object] = {}
        error_holder: dict[str, BaseException] = {}

        def run_call() -> None:
            try:
                result_holder["result"] = wrapped(ExplodingGetState(10))
            except BaseException as exc:  # noqa: BLE001 - surface any failure
                error_holder["error"] = exc

        call_thread = threading.Thread(target=run_call, daemon=True)
        call_thread.start()
        call_thread.join(timeout=10.0)
        if call_thread.is_alive():
            pytest.fail("Debug proxy call did not finish within 10 seconds")
        if "error" in error_holder:
            raise error_holder["error"]
        result = result_holder.get("result")
        assert isinstance(result, ExplodingGetState)

        record_deadline = time.monotonic() + 10.0
        records = manager.get_call_records()
        while not records and time.monotonic() < record_deadline:
            time.sleep(0.05)
            records = manager.get_call_records()
        assert records, "Expected at least one call record within 10 seconds"
        record = records[-1]
        call_data = record.get("call_data") or record
        pretty_args = call_data.get("pretty_args", [])
        pretty_result = call_data.get("pretty_result")

        assert pretty_args, "Expected pretty_args in call record"
        assert isinstance(pretty_args[0], dict)
        assert pretty_args[0].get("__cideldill_placeholder__") is True
        assert pretty_args[0].get("object_name") == "ExplodingGetState"
        assert isinstance(pretty_result, dict)
        assert pretty_result.get("__cideldill_placeholder__") is True
    finally:
        with_debug("OFF")
        server.stop()
        monkeypatch.delenv("CIDELDILL_PORT_FILE", raising=False)


@pytest.mark.integration
def test_debug_proxy_exception_search_text_includes_exception_module(monkeypatch, tmp_path):
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
    except PermissionError:
        pytest.skip("Socket bind not permitted in this environment")

    port_file = tmp_path / "port"
    monkeypatch.setenv("CIDELDILL_PORT_FILE", str(port_file))

    manager = BreakpointManager()
    server = BreakpointServer(manager, port=0)
    server_thread = threading.Thread(target=server.start, daemon=True)
    server_thread.start()
    server_start_deadline = time.monotonic() + 5.0
    port = 0
    while time.monotonic() < server_start_deadline:
        if server.is_running():
            port = server.get_port()
            if port:
                try:
                    resp = requests.get(f"http://localhost:{port}/api/breakpoints", timeout=1)
                    if resp.status_code == 200:
                        break
                except requests.RequestException:
                    pass
        time.sleep(0.05)
    else:
        pytest.fail("Breakpoint server did not start within 5 seconds")

    try:
        import importlib

        from cideldill_client.debug_client import DebugClient

        class LocalDebugClient(DebugClient):
            flask_client = server.test_client()

            def check_connection(self) -> None:
                return None

            def register_function(self, function_name, signature=None, **_):
                return None

            def _post_json(self, path, payload):
                response = self.flask_client.post(path, json=payload)
                return response.get_json()

            def _post_json_allowing_cid_errors(self, path, payload):
                response = self.flask_client.post(path, json=payload)
                return response.get_json()

            def _get_json(self, path):
                response = self.flask_client.get(path)
                return response.get_json()

        with_debug_module = importlib.import_module("cideldill_client.with_debug")
        monkeypatch.setattr(with_debug_module, "DebugClient", LocalDebugClient)

        configure_debug(server_url=f"http://localhost:{port}")
        with_debug("ON")

        class OperationalError(Exception):
            __module__ = "psycopg2"

        def fail():
            raise OperationalError("database role does not exist")

        wrapped = with_debug(fail)
        with pytest.raises(OperationalError):
            wrapped()

        record_deadline = time.monotonic() + 10.0
        records = manager.get_call_records()
        while not records and time.monotonic() < record_deadline:
            time.sleep(0.05)
            records = manager.get_call_records()
        assert records, "Expected at least one call record within 10 seconds"

        record = records[-1]
        call_data = record.get("call_data") or record
        exception = call_data.get("exception")
        assert isinstance(exception, dict)
        assert exception.get("__cideldill_exception__") is True
        assert exception.get("module") == "psycopg2"
        assert exception.get("type_name") == "OperationalError"
        assert exception.get("message") == "database role does not exist"

        process_key = call_data.get("process_key")
        assert isinstance(process_key, str)

        response = server.test_client().get(f"/call-tree/{process_key}")
        assert response.status_code == 200
        html = response.data.decode("utf-8")
        match = re.search(r"const data = ({.*?});", html, re.S)
        assert match, "Expected call tree data to be embedded in HTML."
        payload = json.loads(match.group(1))
        node = payload["nodes"][-1]
        assert "psycopg2" in node["searchText"]
        assert "database role does not exist" in node["searchText"]
    finally:
        with_debug("OFF")
        server.stop()
        monkeypatch.delenv("CIDELDILL_PORT_FILE", raising=False)
