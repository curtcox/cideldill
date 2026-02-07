import pytest

from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer


@pytest.fixture
def server():
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=0)
    yield server
    server.stop()


def test_debug_client_js_endpoint(server) -> None:
    response = server.test_client().get("/api/debug-client.js")
    assert response.status_code == 200
    content_type = response.headers.get("Content-Type") or ""
    assert "application/javascript" in content_type

    body = response.data.decode("utf-8")
    assert "const SERVER_URL" in body
    assert "window.cideldill" in body
    assert "export" in body
