"""Minimal ASGI-to-WSGI adapter for mounting ASGI apps in WSGI servers."""

from __future__ import annotations

import asyncio
import threading
from http import HTTPStatus
from queue import Queue
from typing import Callable, Iterable


class AsgiToWsgi:
    """Adapt an ASGI application to a WSGI callable.

    This adapter is intentionally minimal and supports the HTTP subset needed
    for MCP SSE endpoints.
    """

    def __init__(self, app):
        self._app = app

    def __call__(self, environ, start_response):
        body = b""
        input_stream = environ.get("wsgi.input")
        content_length = environ.get("CONTENT_LENGTH")
        if input_stream is not None and content_length:
            try:
                length = int(content_length)
            except (TypeError, ValueError):
                length = 0
            if length > 0:
                body = input_stream.read(length)
        response_started = threading.Event()
        disconnect_event = threading.Event()
        response_status: dict[str, object] = {}
        response_headers: list[tuple[bytes, bytes]] = []
        body_queue: "Queue[bytes | None]" = Queue()
        error: dict[str, Exception] = {}
        disconnect_callback: list[Callable[[], None]] = []

        def _build_scope() -> dict[str, object]:
            path = environ.get("PATH_INFO", "")
            query = environ.get("QUERY_STRING", "")
            scheme = environ.get("wsgi.url_scheme", "http")
            server = (
                environ.get("SERVER_NAME", "localhost"),
                int(environ.get("SERVER_PORT", 80)),
            )
            client = (
                environ.get("REMOTE_ADDR", "127.0.0.1"),
                int(environ.get("REMOTE_PORT", 0)) if environ.get("REMOTE_PORT") else 0,
            )

            headers: list[tuple[bytes, bytes]] = []
            for key, value in environ.items():
                if key.startswith("HTTP_"):
                    header_name = key[5:].replace("_", "-").lower().encode("latin-1")
                    headers.append((header_name, str(value).encode("latin-1")))
            if "CONTENT_TYPE" in environ:
                headers.append((b"content-type", str(environ["CONTENT_TYPE"]).encode("latin-1")))
            if "CONTENT_LENGTH" in environ:
                headers.append((b"content-length", str(environ["CONTENT_LENGTH"]).encode("latin-1")))

            return {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": environ.get("SERVER_PROTOCOL", "HTTP/1.1").split("/")[-1],
                "method": environ.get("REQUEST_METHOD", "GET"),
                "scheme": scheme,
                "path": path,
                "raw_path": path.encode("utf-8"),
                "query_string": query.encode("utf-8"),
                "root_path": environ.get("SCRIPT_NAME", ""),
                "headers": headers,
                "server": server,
                "client": client,
            }

        async def _run_asgi() -> None:
            scope = _build_scope()
            body_sent = False
            loop = asyncio.get_running_loop()
            async_disconnect = asyncio.Event()

            def _signal_disconnect() -> None:
                if not async_disconnect.is_set():
                    async_disconnect.set()

            def _wake_disconnect() -> None:
                loop.call_soon_threadsafe(_signal_disconnect)

            disconnect_callback.append(_wake_disconnect)
            if disconnect_event.is_set():
                _signal_disconnect()

            async def receive():
                nonlocal body_sent
                if not body_sent:
                    body_sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                await async_disconnect.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                msg_type = message.get("type")
                if msg_type == "http.response.start":
                    response_status["status"] = message.get("status", 500)
                    response_headers.extend(message.get("headers", []))
                    response_started.set()
                elif msg_type == "http.response.body":
                    body_chunk = message.get("body", b"")
                    if body_chunk:
                        body_queue.put(body_chunk)
                    if not message.get("more_body", False):
                        body_queue.put(None)

            await self._app(scope, receive, send)

        def _thread_target():
            try:
                asyncio.run(_run_asgi())
            except Exception as exc:  # pragma: no cover - safety net
                error["exc"] = exc
                if not response_started.is_set():
                    response_status["status"] = 500
                    response_headers.extend([(b"content-type", b"text/plain")])
                    response_started.set()
                    body_queue.put(b"ASGI application error")
                    body_queue.put(None)

        thread = threading.Thread(target=_thread_target, daemon=True)
        thread.start()

        response_started.wait(timeout=5)
        status_code = int(response_status.get("status", 500))
        reason = HTTPStatus(status_code).phrase if status_code in HTTPStatus._value2member_map_ else ""
        status_line = f"{status_code} {reason}".strip()
        headers = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in response_headers]
        start_response(status_line, headers)

        def _iterable() -> Iterable[bytes]:
            try:
                while True:
                    chunk = body_queue.get()
                    if chunk is None:
                        break
                    yield chunk
            finally:
                disconnect_event.set()
                if disconnect_callback:
                    try:
                        disconnect_callback[0]()
                    except Exception:
                        pass
                thread.join(timeout=1)
                if "exc" in error:
                    raise error["exc"]

        return _iterable()
