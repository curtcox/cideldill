"""Tests for exception reporting in DebugClient.record_call_complete.

Verifies that exception payloads include:
1. Fully-qualified exception type (e.g. "json.decoder.JSONDecodeError", not just "JSONDecodeError")
2. Formatted traceback string
3. Builtin exceptions omit the "builtins." prefix
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("dill")
pytest.importorskip("requests")

from cideldill_client.debug_client import DebugClient


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_exception_payload(monkeypatch, exception):
    """Call record_call_complete with the given exception, return the payload."""
    captured: dict = {}

    def fake_post(url: str, json: dict, timeout: float) -> _Response:
        captured["payload"] = json
        return _Response(200, {"status": "ok"})

    monkeypatch.setattr("requests.post", fake_post)

    client = DebugClient("http://localhost:5000")
    client.record_call_complete(
        call_id="exc-001", status="exception", exception=exception
    )
    return captured["payload"]


# ---------------------------------------------------------------------------
# Tests for fully-qualified exception type
# ---------------------------------------------------------------------------


class TestExceptionTypeFullyQualified:
    """exception_type should include the module for non-builtin exceptions."""

    def test_stdlib_exception_includes_module(self, monkeypatch) -> None:
        """json.decoder.JSONDecodeError should appear fully qualified."""
        try:
            json.loads("not json")
        except json.JSONDecodeError as exc:
            payload = _capture_exception_payload(monkeypatch, exc)

        assert payload["exception_type"] == "json.decoder.JSONDecodeError"

    def test_builtin_exception_omits_builtins_prefix(self, monkeypatch) -> None:
        """ValueError should remain 'ValueError', not 'builtins.ValueError'."""
        exc = ValueError("bad value")
        payload = _capture_exception_payload(monkeypatch, exc)

        assert payload["exception_type"] == "ValueError"

    def test_custom_exception_includes_module(self, monkeypatch) -> None:
        """A custom exception class should include its module path."""

        class CustomError(Exception):
            pass

        exc = CustomError("oops")
        payload = _capture_exception_payload(monkeypatch, exc)

        # The module will be the test module; the key point is it's NOT just "CustomError"
        assert "CustomError" in payload["exception_type"]
        assert payload["exception_type"] != "CustomError"  # must have module prefix


# ---------------------------------------------------------------------------
# Tests for traceback inclusion
# ---------------------------------------------------------------------------


class TestExceptionTraceback:
    """exception_traceback should be present and contain useful information."""

    def test_traceback_field_is_present(self, monkeypatch) -> None:
        """The payload must include an 'exception_traceback' key."""
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            payload = _capture_exception_payload(monkeypatch, exc)

        assert "exception_traceback" in payload

    def test_traceback_contains_exception_type_and_message(self, monkeypatch) -> None:
        """The traceback string should mention the exception type and message."""
        try:
            raise ValueError("some detail")
        except ValueError as exc:
            payload = _capture_exception_payload(monkeypatch, exc)

        tb = payload["exception_traceback"]
        assert "ValueError" in tb
        assert "some detail" in tb

    def test_traceback_contains_source_location(self, monkeypatch) -> None:
        """The traceback should reference this test file."""
        try:
            raise TypeError("type issue")
        except TypeError as exc:
            payload = _capture_exception_payload(monkeypatch, exc)

        tb = payload["exception_traceback"]
        assert "test_exception_reporting" in tb

    def test_traceback_for_stdlib_exception_includes_module(self, monkeypatch) -> None:
        """A stdlib exception's traceback should mention the module path."""
        try:
            json.loads("not json")
        except json.JSONDecodeError as exc:
            payload = _capture_exception_payload(monkeypatch, exc)

        tb = payload["exception_traceback"]
        assert "JSONDecodeError" in tb

    def test_exception_without_traceback_still_has_field(self, monkeypatch) -> None:
        """An exception constructed without raising still gets a traceback field."""
        exc = RuntimeError("no raise")
        payload = _capture_exception_payload(monkeypatch, exc)

        # Should still have the field, even if the traceback is minimal
        assert "exception_traceback" in payload
        assert "RuntimeError" in payload["exception_traceback"]
