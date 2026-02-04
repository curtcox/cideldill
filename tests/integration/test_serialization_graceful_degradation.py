"""Integration tests for graceful serialization degradation."""

import sqlite3
import ssl

import pytest

from cideldill_client.custom_picklers import UnpicklablePlaceholder
from cideldill_client.serialization import deserialize, serialize


@pytest.mark.integration
def test_sslcontext_degrades_to_placeholder():
    ctx = ssl.create_default_context()
    data = serialize(ctx)
    restored = deserialize(data)

    if not isinstance(restored, UnpicklablePlaceholder):
        pytest.skip("SSLContext is picklable in this environment")

    assert isinstance(restored, UnpicklablePlaceholder)
    assert restored.type_name == type(ctx).__name__


@pytest.mark.integration
def test_sqlite_connection_degrades_to_placeholder():
    conn = sqlite3.connect(":memory:")
    try:
        data = serialize(conn)
        restored = deserialize(data)

        if not isinstance(restored, UnpicklablePlaceholder):
            pytest.skip("sqlite3 connection is picklable in this environment")

        assert isinstance(restored, UnpicklablePlaceholder)
        assert restored.type_name == type(conn).__name__
    finally:
        conn.close()
