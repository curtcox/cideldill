"""Unit tests for Inspector class."""

import pytest
from cideldill.inspector import Inspector


def test_inspector_initialization() -> None:
    """Test Inspector initialization."""
    inspector = Inspector()
    assert inspector.host == "localhost"
    assert inspector.port == 8080


def test_inspector_custom_host_port() -> None:
    """Test Inspector with custom host and port."""
    inspector = Inspector("example.com", 9000)
    assert inspector.host == "example.com"
    assert inspector.port == 9000


def test_connect() -> None:
    """Test connecting to remote agent."""
    inspector = Inspector()
    result = inspector.connect()
    assert result is True
    assert inspector.is_connected() is True


def test_disconnect() -> None:
    """Test disconnecting from remote agent."""
    inspector = Inspector()
    inspector.connect()
    inspector.disconnect()
    assert inspector.is_connected() is False


def test_send_data_when_connected() -> None:
    """Test sending data when connected."""
    inspector = Inspector()
    inspector.connect()
    data = {"test": "value"}
    response = inspector.send_data(data)
    assert response is not None
    assert response["status"] == "received"


def test_send_data_when_not_connected() -> None:
    """Test sending data when not connected."""
    inspector = Inspector()
    response = inspector.send_data({"test": "value"})
    assert response is None
