import pytest

from cideldill_server.breakpoint_manager import BreakpointManager
from cideldill_server.breakpoint_server import BreakpointServer


@pytest.fixture
def server():
    manager = BreakpointManager()
    server = BreakpointServer(manager, port=0)
    yield server
    server.stop()


def test_cors_headers_on_api_routes(server) -> None:
    response = server.test_client().get("/api/breakpoints")
    assert response.status_code == 200
    assert response.headers.get("Access-Control-Allow-Origin") == "*"


def test_cors_preflight_options(server) -> None:
    response = server.test_client().open("/api/breakpoints", method="OPTIONS")
    assert response.status_code in (200, 204)
    assert response.headers.get("Access-Control-Allow-Origin") == "*"
    assert "OPTIONS" in (response.headers.get("Access-Control-Allow-Methods") or "")
