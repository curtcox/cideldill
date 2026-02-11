"""MCP server implementation for CID el Dill breakpoint server."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from queue import Queue, Empty
import threading
from uuid import uuid4
from typing import Any, Callable, Iterable, Mapping, Iterator

from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from anyio import create_memory_object_stream, WouldBlock
from anyio.from_thread import BlockingPortal, start_blocking_portal
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    Resource,
    TextContent,
    Tool,
    JSONRPCMessage,
)
from mcp.shared.message import SessionMessage

from .breakpoint_manager import BreakpointManager
from .cid_store import CIDStore
from .mcp_notifications import MCPNotificationDispatcher
from .serialization import deserialize
from .serialization_common import DEFAULT_MAX_ATTRIBUTES, DEFAULT_MAX_DEPTH


class BreakpointMCPServer:
    """MCP server exposing breakpoint tools, resources, and prompts."""

    def __init__(
        self,
        manager: BreakpointManager,
        cid_store: CIDStore,
        *,
        repl_backend: object | None = None,
    ) -> None:
        self.manager = manager
        self.cid_store = cid_store
        self._repl_backend = repl_backend
        self._notification_loop: asyncio.AbstractEventLoop | None = None
        self._notifications = MCPNotificationDispatcher(manager)
        self.server = Server("cideldill-breakpoint-server")
        self._tools = self._build_tools()
        self._tool_handlers: dict[str, Callable[[dict[str, Any]], CallToolResult]] = {
            "breakpoint_list_breakpoints": self._tool_list_breakpoints,
            "breakpoint_add": self._tool_add_breakpoint,
            "breakpoint_remove": self._tool_remove_breakpoint,
            "breakpoint_set_behavior": self._tool_set_behavior,
            "breakpoint_set_after_behavior": self._tool_set_after_behavior,
            "breakpoint_set_replacement": self._tool_set_replacement,
            "breakpoint_get_default_behavior": self._tool_get_default_behavior,
            "breakpoint_set_default_behavior": self._tool_set_default_behavior,
            "breakpoint_list_paused": self._tool_list_paused,
            "breakpoint_continue": self._tool_continue,
            "breakpoint_list_functions": self._tool_list_functions,
            "breakpoint_get_call_records": self._tool_get_call_records,
            "breakpoint_repl_eval": self._tool_repl_eval,
            "breakpoint_inspect_object": self._tool_inspect_object,
        }

        self.server.list_tools()(self.list_tools)
        self.server.call_tool()(self.call_tool)
        self.server.list_resources()(self.list_resources)
        self.server.read_resource()(self.read_resource)
        self.server.list_prompts()(self.list_prompts)
        self.server.get_prompt()(self.get_prompt)
        self._notifications.add_sink(self._send_notification)
        self._sse_sessions: dict[str, _SseSession] = {}
        self._sse_lock = threading.Lock()

    async def list_tools(self) -> list[Tool]:
        return list(self._tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        handler = self._tool_handlers.get(name)
        if handler is None:
            return self._tool_result({"error": "unknown_tool", "tool": name})
        if not isinstance(arguments, dict):
            arguments = {}
        return handler(arguments)

    async def list_resources(self) -> list[Resource]:
        return [
            Resource(
                uri="breakpoint://status",
                name="Breakpoint Status",
                description="Summary of breakpoint server status.",
                mimeType="application/json",
            ),
            Resource(
                uri="breakpoint://breakpoints",
                name="Breakpoints",
                description="Active breakpoint configuration.",
                mimeType="application/json",
            ),
            Resource(
                uri="breakpoint://paused",
                name="Paused Executions",
                description="Currently paused executions.",
                mimeType="application/json",
            ),
            Resource(
                uri="breakpoint://call-history",
                name="Call History",
                description="Recent call records.",
                mimeType="application/json",
            ),
            Resource(
                uri="breakpoint://functions",
                name="Registered Functions",
                description="Registered functions and signatures.",
                mimeType="application/json",
            ),
        ]

    async def read_resource(self, uri: str) -> list[ReadResourceContents]:
        normalized = self._normalize_resource_uri(uri)
        if normalized == "breakpoint://status":
            payload = {
                "breakpoints": len(self.manager.get_breakpoints()),
                "paused": len(self.manager.get_paused_executions()),
                "total_calls": len(self.manager.get_call_records()),
            }
            return [self._resource_content(payload)]
        if normalized == "breakpoint://breakpoints":
            return [self._resource_content(self._list_breakpoints_payload())]
        if normalized == "breakpoint://paused":
            return [self._resource_content(self._list_paused_payload())]
        if normalized == "breakpoint://call-history":
            payload = self._call_history_payload(limit=50)
            return [self._resource_content(payload)]
        if normalized == "breakpoint://functions":
            payload = {
                "functions": self.manager.get_registered_functions(),
                "signatures": self.manager.get_function_signatures(),
                "metadata": self.manager.get_function_metadata(),
            }
            return [self._resource_content(payload)]
        raise ValueError("unknown resource")

    async def list_prompts(self) -> list[Prompt]:
        return [
            Prompt(
                name="debug-session-start",
                description="Provide context about the current debug session.",
                arguments=[],
            ),
            Prompt(
                name="inspect-paused-call",
                description="Inspect a specific paused execution.",
                arguments=[
                    PromptArgument(
                        name="pause_id",
                        description="ID of the paused execution",
                        required=True,
                    )
                ],
            ),
        ]

    async def get_prompt(self, name: str, arguments: dict[str, Any]) -> GetPromptResult:
        if name == "debug-session-start":
            payload = {
                "breakpoints": self._list_breakpoints_payload(),
                "functions": {
                    "functions": self.manager.get_registered_functions(),
                    "signatures": self.manager.get_function_signatures(),
                },
                "recent_calls": self._call_history_payload(limit=10),
                "paused": self._list_paused_payload(),
            }
            return GetPromptResult(
                messages=[
                    PromptMessage(
                        role="user",
                        content=self._json_content(payload),
                    )
                ]
            )
        if name == "inspect-paused-call":
            pause_id = arguments.get("pause_id")
            if not isinstance(pause_id, str):
                raise ValueError("missing pause_id")
            paused = self.manager.get_paused_execution(pause_id)
            if paused is None:
                raise ValueError("pause_not_found")
            call_data = paused.get("call_data", {}) if isinstance(paused, dict) else {}
            payload = {
                "pause_id": pause_id,
                "call_data": call_data,
                "repl_sessions": self.manager.get_repl_sessions_for_pause(pause_id),
            }
            return GetPromptResult(
                messages=[
                    PromptMessage(
                        role="user",
                        content=self._json_content(payload),
                    )
                ]
            )
        raise ValueError("unknown prompt")

    async def run_stdio(self) -> None:
        self._notification_loop = asyncio.get_running_loop()
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )

    def create_sse_app(self):
        raise RuntimeError("Use WSGI SSE routes via BreakpointServer.mount_mcp_sse")

    def start_sse_session(self, *, base_path: str = "/mcp") -> "_SseSession":
        portal_cm: AbstractContextManager[BlockingPortal] = start_blocking_portal()
        portal = portal_cm.__enter__()
        read_writer: object
        write_stream: object
        write_reader: object
        session_id = uuid4().hex
        queue: Queue[SessionMessage | None] = Queue()
        closed = threading.Event()

        async def run_session(task_status) -> None:
            nonlocal read_writer, write_stream, write_reader
            read_writer, read_stream = create_memory_object_stream[SessionMessage](100)
            write_stream, write_reader = create_memory_object_stream[SessionMessage](100)
            task_status.started((read_writer, write_stream, write_reader))

            async def forward_messages() -> None:
                async with write_reader:
                    async for message in write_reader:
                        queue.put(message)

            async with asyncio.TaskGroup() as tg:
                tg.create_task(
                    self.server.run(
                        read_stream,
                        write_stream,
                        self.server.create_initialization_options(),
                    )
                )
                tg.create_task(forward_messages())

        try:
            _, streams = portal.start_task(run_session)
            read_writer, write_stream, write_reader = streams
        except Exception:
            portal_cm.__exit__(None, None, None)
            raise

        session = _SseSession(
            session_id=session_id,
            read_writer=read_writer,
            write_stream=write_stream,
            write_reader=write_reader,
            queue=queue,
            closed=closed,
            portal=portal,
            portal_cm=portal_cm,
            base_path=base_path,
        )

        with self._sse_lock:
            self._sse_sessions[session_id] = session

        return session

    def handle_sse_message(self, session_id: str | None, body: bytes) -> tuple[str, int]:
        if not session_id:
            return ("session_id is required", 400)
        with self._sse_lock:
            session = self._sse_sessions.get(session_id)
        if session is None:
            return ("Could not find session", 404)
        try:
            message = JSONRPCMessage.model_validate_json(body)
        except Exception:
            return ("Could not parse message", 400)
        try:
            session.portal.call(session.read_writer.send_nowait, SessionMessage(message))
        except WouldBlock:
            # Backpressure: drop the message rather than hanging request thread.
            return ("Backpressure", 429)
        except Exception:
            return ("Failed to deliver message", 503)
        return ("Accepted", 202)

    def close_sse_session(self, session_id: str) -> None:
        with self._sse_lock:
            session = self._sse_sessions.pop(session_id, None)
        if session:
            session.close()

    def _send_notification(self, method: str, params: dict[str, object]) -> None:
        self._dispatch_notification(self.server, method, params)

    def _dispatch_notification(self, target: object, method: str, params: dict[str, object]) -> None:
        for name in ("send_notification", "notification", "notify"):
            sender = getattr(target, name, None)
            if not callable(sender):
                continue
            try:
                result = sender(method, params)
            except TypeError:
                try:
                    result = sender(method=method, params=params)
                except Exception:
                    continue
            except Exception:
                return
            self._schedule_notification(result)
            return

    def _schedule_notification(self, result: object) -> None:
        if not inspect.iscoroutine(result):
            return
        if self._notification_loop is not None:
            asyncio.run_coroutine_threadsafe(result, self._notification_loop)
            return
        try:
            asyncio.run(result)
        except RuntimeError:
            return

    def _tool_list_breakpoints(self, _args: dict[str, Any]) -> CallToolResult:
        return self._tool_result(self._list_breakpoints_payload())

    def _tool_add_breakpoint(self, args: dict[str, Any]) -> CallToolResult:
        function_name = self._require_str(args, "function_name")
        if isinstance(function_name, CallToolResult):
            return function_name
        behavior = args.get("behavior")

        self.manager.add_breakpoint(function_name)
        if behavior is not None:
            try:
                self.manager.set_breakpoint_behavior(function_name, str(behavior))
            except ValueError:
                return self._tool_result({"error": "invalid_behavior"})
        return self._tool_result({"status": "ok", "function_name": function_name})

    def _tool_remove_breakpoint(self, args: dict[str, Any]) -> CallToolResult:
        function_name = self._require_str(args, "function_name")
        if isinstance(function_name, CallToolResult):
            return function_name
        self.manager.remove_breakpoint(function_name)
        return self._tool_result({"status": "ok", "function_name": function_name})

    def _tool_set_behavior(self, args: dict[str, Any]) -> CallToolResult:
        function_name = self._require_str(args, "function_name")
        if isinstance(function_name, CallToolResult):
            return function_name
        behavior = self._require_str(args, "behavior")
        if isinstance(behavior, CallToolResult):
            return behavior
        try:
            self.manager.set_breakpoint_behavior(function_name, behavior)
        except KeyError:
            return self._tool_result({"error": "breakpoint_not_found"})
        except ValueError:
            return self._tool_result({"error": "invalid_behavior"})
        return self._tool_result(
            {"status": "ok", "function_name": function_name, "behavior": behavior}
        )

    def _tool_set_after_behavior(self, args: dict[str, Any]) -> CallToolResult:
        function_name = self._require_str(args, "function_name")
        if isinstance(function_name, CallToolResult):
            return function_name
        behavior = self._require_str(args, "behavior")
        if isinstance(behavior, CallToolResult):
            return behavior
        try:
            self.manager.set_after_breakpoint_behavior(function_name, behavior)
        except KeyError:
            return self._tool_result({"error": "breakpoint_not_found"})
        except ValueError:
            return self._tool_result({"error": "invalid_behavior"})
        return self._tool_result(
            {"status": "ok", "function_name": function_name, "behavior": behavior}
        )

    def _tool_set_replacement(self, args: dict[str, Any]) -> CallToolResult:
        function_name = self._require_str(args, "function_name")
        if isinstance(function_name, CallToolResult):
            return function_name
        replacement = self._require_str_allow_empty(args, "replacement_function")
        if isinstance(replacement, CallToolResult):
            return replacement
        if not self.manager.has_breakpoint(function_name):
            return self._tool_result({"error": "breakpoint_not_found"})
        if replacement:
            signatures = self.manager.get_function_signatures()
            expected = signatures.get(function_name)
            actual = signatures.get(replacement)
            if not expected or expected != actual:
                return self._tool_result({"error": "signature_mismatch"})
        try:
            self.manager.set_breakpoint_replacement(function_name, replacement)
        except KeyError:
            return self._tool_result({"error": "breakpoint_not_found"})
        return self._tool_result(
            {
                "status": "ok",
                "function_name": function_name,
                "replacement_function": replacement,
            }
        )

    def _tool_get_default_behavior(self, _args: dict[str, Any]) -> CallToolResult:
        return self._tool_result({"behavior": self.manager.get_default_behavior()})

    def _tool_set_default_behavior(self, args: dict[str, Any]) -> CallToolResult:
        behavior = self._require_str(args, "behavior")
        if isinstance(behavior, CallToolResult):
            return behavior
        if behavior == "continue":
            behavior = "go"
        try:
            self.manager.set_default_behavior(behavior)
        except ValueError:
            return self._tool_result({"error": "invalid_behavior"})
        return self._tool_result(
            {"status": "ok", "behavior": self.manager.get_default_behavior()}
        )

    def _tool_list_paused(self, _args: dict[str, Any]) -> CallToolResult:
        return self._tool_result(self._list_paused_payload())

    def _tool_continue(self, args: dict[str, Any]) -> CallToolResult:
        pause_id = self._require_str(args, "pause_id")
        if isinstance(pause_id, CallToolResult):
            return pause_id
        paused = self.manager.get_paused_execution(pause_id)
        if paused is None:
            if self.manager.get_resume_action(pause_id) is not None:
                return self._tool_result(
                    {"error": "pause_already_resumed", "pause_id": pause_id}
                )
            return self._tool_result({"error": "pause_not_found", "pause_id": pause_id})

        replacement_function = args.get("replacement_function")
        if replacement_function:
            action_dict: dict[str, Any] = {
                "action": "replace",
                "function_name": replacement_function,
            }
        else:
            action_dict = {"action": args.get("action", "continue")}

        for field in ("modified_args", "modified_kwargs", "fake_result"):
            if field in args:
                action_dict[field] = args[field]
        for field in ("exception_type", "exception_message"):
            if field in args:
                action_dict[field] = args[field]

        error = self._apply_preferred_format(action_dict)
        if error is not None:
            return error

        self.manager.resume_execution(pause_id, action_dict)
        return self._tool_result({"status": "ok", "pause_id": pause_id})

    def _tool_list_functions(self, _args: dict[str, Any]) -> CallToolResult:
        payload = {
            "functions": self.manager.get_registered_functions(),
            "signatures": self.manager.get_function_signatures(),
            "metadata": self.manager.get_function_metadata(),
        }
        return self._tool_result(payload)

    def _tool_get_call_records(self, args: dict[str, Any]) -> CallToolResult:
        limit = args.get("limit")
        function_name = args.get("function_name")
        return self._tool_result(
            self._call_history_payload(limit=limit, function_name=function_name)
        )

    def _tool_repl_eval(self, args: dict[str, Any]) -> CallToolResult:
        pause_id = self._require_str(args, "pause_id")
        if isinstance(pause_id, CallToolResult):
            return pause_id
        expr = args.get("expression")
        if not isinstance(expr, str) or not expr.strip():
            return self._tool_result({"error": "missing_expression"})
        paused = self.manager.get_paused_execution(pause_id)
        if paused is None:
            return self._tool_result({"error": "pause_not_found", "pause_id": pause_id})

        session_id = args.get("session_id")
        if session_id is None:
            try:
                session_id = self.manager.start_repl_session(pause_id)
            except KeyError as exc:
                return self._tool_result({"error": "invalid_pause", "message": str(exc)})
        elif not isinstance(session_id, str):
            return self._tool_result({"error": "invalid_session_id"})

        session = self.manager.get_repl_session(session_id)
        if session is None:
            return self._tool_result({"error": "session_not_found"})
        if session.get("closed_at") is not None:
            return self._tool_result({"error": "session_closed"})

        if self._repl_backend is None:
            return self._tool_result({"error": "repl_backend_unavailable"})
        queue_eval = getattr(self._repl_backend, "queue_repl_eval", None)
        wait_for_eval = getattr(self._repl_backend, "wait_for_repl_eval", None)
        if not callable(queue_eval) or not callable(wait_for_eval):
            return self._tool_result({"error": "repl_backend_unavailable"})

        eval_id = queue_eval(pause_id, session_id, expr)
        timeout_s = args.get("timeout_s", 30)
        if not isinstance(timeout_s, (int, float)):
            timeout_s = 30
        status, result = wait_for_eval(eval_id, float(timeout_s))
        if status == "timeout":
            return self._tool_result(
                {
                    "error": "eval_timeout",
                    "message": f"Debug client did not respond within {timeout_s}s",
                }
            )
        if status == "closed":
            return self._tool_result({"error": "session_closed"})
        if status != "ok" or result is None:
            return self._tool_result({"error": "eval_missing"})

        payload = dict(result)
        payload["session_id"] = session_id
        return self._tool_result(payload)

    def _tool_inspect_object(self, args: dict[str, Any]) -> CallToolResult:
        cid = self._require_str(args, "cid")
        if isinstance(cid, CallToolResult):
            return cid
        data = self.cid_store.get(cid)
        if data is None:
            return self._tool_result({"error": "cid_not_found", "cid": cid})

        json_value = self._try_json_value(data)
        if json_value is not None:
            value = json_value
        else:
            try:
                value = deserialize(data)
            except Exception as exc:  # noqa: BLE001
                return self._tool_result(
                    {
                        "cid": cid,
                        "type": "unknown",
                        "repr": f"<deserialization failed: {type(exc).__name__}>",
                        "attributes": {},
                        "error": "deserialization_failed",
                    }
                )

        payload = {
            "cid": cid,
            "type": type(value).__name__,
            "repr": self._safe_repr(value),
            "attributes": self._inspect_attributes(value),
        }
        return self._tool_result(payload)

    def _tool_result(self, payload: dict[str, Any]) -> CallToolResult:
        return CallToolResult(content=[self._json_content(payload)])

    def _json_content(self, payload: Any) -> TextContent:
        return TextContent(type="text", text=json.dumps(payload))

    def _resource_content(self, payload: Any) -> ReadResourceContents:
        return ReadResourceContents(
            content=json.dumps(payload),
            mime_type="application/json",
        )

    def _normalize_resource_uri(self, uri: object) -> str:
        text = str(uri)
        trimmed = text.split("?", 1)[0].split("#", 1)[0]
        return trimmed.rstrip("/")

    def _list_breakpoints_payload(self) -> dict[str, Any]:
        return {
            "breakpoints": self.manager.get_breakpoints(),
            "behaviors": self.manager.get_breakpoint_behaviors(),
            "after_behaviors": self.manager.get_after_breakpoint_behaviors(),
            "replacements": self.manager.get_breakpoint_replacements(),
        }

    def _list_paused_payload(self) -> dict[str, Any]:
        paused_payloads: list[dict[str, Any]] = []
        for item in self.manager.get_paused_executions():
            pause_id = item.get("id") if isinstance(item, dict) else None
            repl_sessions: list[str] = []
            if isinstance(pause_id, str):
                repl_sessions = self.manager.get_repl_sessions_for_pause(pause_id)
            payload = dict(item)
            payload["repl_sessions"] = repl_sessions
            paused_payloads.append(payload)
        return {"paused": paused_payloads}

    def _call_history_payload(
        self,
        *,
        limit: int | None = None,
        function_name: str | None = None,
    ) -> dict[str, Any]:
        if limit is None:
            limit = 100
        if not isinstance(limit, int) or limit < 1:
            return {"error": "invalid_limit"}
        records = self.manager.get_call_records()
        if isinstance(function_name, str):
            records = [
                record for record in records if record.get("method_name") == function_name
            ]
        total_count = len(records)
        truncated = total_count > limit
        records = records[:limit]
        return {
            "calls": records,
            "total_count": total_count,
            "truncated": truncated,
        }

    def _require_str(self, args: dict[str, Any], key: str) -> str | CallToolResult:
        value = args.get(key)
        if not isinstance(value, str) or not value.strip():
            return self._tool_result({"error": "missing_parameter", "parameter": key})
        return value

    def _require_str_allow_empty(self, args: dict[str, Any], key: str) -> str | CallToolResult:
        if key not in args:
            return self._tool_result({"error": "missing_parameter", "parameter": key})
        value = args.get(key)
        if not isinstance(value, str):
            return self._tool_result({"error": "missing_parameter", "parameter": key})
        return value

    def _apply_preferred_format(self, action_dict: dict[str, Any]) -> CallToolResult | None:
        try:
            if "modified_args" in action_dict:
                args = action_dict.get("modified_args")
                if isinstance(args, list):
                    action_dict["modified_args"] = [
                        item
                        if isinstance(item, dict) and "cid" in item
                        else self._encode_payload_item(item)
                        for item in args
                    ]
            if "modified_kwargs" in action_dict:
                kwargs = action_dict.get("modified_kwargs")
                if isinstance(kwargs, dict):
                    encoded_kwargs: dict[str, Any] = {}
                    for key, value in kwargs.items():
                        if isinstance(value, dict) and "cid" in value:
                            encoded_kwargs[key] = value
                        else:
                            encoded_kwargs[key] = self._encode_payload_item(value)
                    action_dict["modified_kwargs"] = encoded_kwargs
            if "fake_result" in action_dict and "fake_result_data" not in action_dict:
                encoded = self._encode_payload_item(action_dict.get("fake_result"))
                action_dict["fake_result_cid"] = encoded.get("cid")
                action_dict["fake_result_data"] = encoded.get("data")
                action_dict["fake_result_serialization_format"] = encoded.get(
                    "serialization_format"
                )
        except ValueError:
            return self._tool_result({"error": "invalid_json"})
        return None

    def _encode_payload_item(self, value: Any) -> dict[str, Any]:
        try:
            data = json.dumps(value)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("invalid_json") from exc
        cid = hashlib.sha512(data.encode("utf-8")).hexdigest()
        return {
            "cid": cid,
            "data": data,
            "serialization_format": "json",
        }

    def _try_json_value(self, data: bytes) -> object | None:
        try:
            return json.loads(data.decode("utf-8"))
        except Exception:
            return None

    def _safe_repr(self, value: object, limit: int = 500) -> str:
        try:
            text = repr(value)
        except Exception as exc:  # noqa: BLE001
            text = f"<unreprable: {type(exc).__name__}>"
        if len(text) > limit:
            return text[:limit] + "..."
        return text

    def _inspect_attributes(self, value: object) -> dict[str, Any]:
        if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
            try:
                return dict(getattr(value, "to_dict")())
            except Exception:
                return {}
        if isinstance(value, Mapping):
            return self._format_mapping(value, depth=0)
        if hasattr(value, "__dict__"):
            try:
                return self._format_mapping(vars(value), depth=0)
            except Exception:
                return {}
        return {}

    def _format_mapping(self, mapping: Mapping[str, Any], *, depth: int) -> dict[str, Any]:
        if depth >= DEFAULT_MAX_DEPTH:
            return {}
        formatted: dict[str, Any] = {}
        for idx, (key, val) in enumerate(mapping.items()):
            if idx >= DEFAULT_MAX_ATTRIBUTES:
                break
            formatted[str(key)] = self._format_value(val, depth=depth + 1)
        return formatted

    def _format_iterable(self, items: Iterable[Any], *, depth: int) -> list[Any]:
        if depth >= DEFAULT_MAX_DEPTH:
            return []
        formatted: list[Any] = []
        for idx, item in enumerate(items):
            if idx >= DEFAULT_MAX_ATTRIBUTES:
                break
            formatted.append(self._format_value(item, depth=depth + 1))
        return formatted

    def _format_value(self, value: Any, *, depth: int) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if depth >= DEFAULT_MAX_DEPTH:
            return self._safe_repr(value)
        if isinstance(value, Mapping):
            return self._format_mapping(value, depth=depth)
        if isinstance(value, (list, tuple, set, frozenset)):
            return self._format_iterable(list(value), depth=depth)
        return self._safe_repr(value)

    def _build_tools(self) -> list[Tool]:
        return [
            Tool(
                name="breakpoint_list_breakpoints",
                description="List all active breakpoints.",
                inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
            ),
            Tool(
                name="breakpoint_add",
                description="Add a breakpoint on a function.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "function_name": {"type": "string"},
                        "behavior": {"type": "string"},
                    },
                    "required": ["function_name"],
                    "additionalProperties": True,
                },
            ),
            Tool(
                name="breakpoint_remove",
                description="Remove a breakpoint.",
                inputSchema={
                    "type": "object",
                    "properties": {"function_name": {"type": "string"}},
                    "required": ["function_name"],
                    "additionalProperties": True,
                },
            ),
            Tool(
                name="breakpoint_set_behavior",
                description="Set before-execution behavior for a breakpoint.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "function_name": {"type": "string"},
                        "behavior": {"type": "string"},
                    },
                    "required": ["function_name", "behavior"],
                    "additionalProperties": True,
                },
            ),
            Tool(
                name="breakpoint_set_after_behavior",
                description="Set after-execution behavior for a breakpoint.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "function_name": {"type": "string"},
                        "behavior": {"type": "string"},
                    },
                    "required": ["function_name", "behavior"],
                    "additionalProperties": True,
                },
            ),
            Tool(
                name="breakpoint_set_replacement",
                description="Set a replacement function for a breakpoint.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "function_name": {"type": "string"},
                        "replacement_function": {"type": "string"},
                    },
                    "required": ["function_name", "replacement_function"],
                    "additionalProperties": True,
                },
            ),
            Tool(
                name="breakpoint_get_default_behavior",
                description="Get the default breakpoint behavior.",
                inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
            ),
            Tool(
                name="breakpoint_set_default_behavior",
                description="Set the default breakpoint behavior.",
                inputSchema={
                    "type": "object",
                    "properties": {"behavior": {"type": "string"}},
                    "required": ["behavior"],
                    "additionalProperties": True,
                },
            ),
            Tool(
                name="breakpoint_list_paused",
                description="List paused executions.",
                inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
            ),
            Tool(
                name="breakpoint_continue",
                description="Resume a paused execution.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pause_id": {"type": "string"},
                        "action": {"type": "string"},
                        "modified_args": {"type": "array"},
                        "modified_kwargs": {"type": "object"},
                        "fake_result": {},
                        "exception_type": {"type": "string"},
                        "exception_message": {"type": "string"},
                        "replacement_function": {"type": "string"},
                    },
                    "required": ["pause_id"],
                    "additionalProperties": True,
                },
            ),
            Tool(
                name="breakpoint_list_functions",
                description="List registered functions.",
                inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
            ),
            Tool(
                name="breakpoint_get_call_records",
                description="Get recorded call history.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "function_name": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1},
                    },
                    "additionalProperties": True,
                },
            ),
            Tool(
                name="breakpoint_repl_eval",
                description="Evaluate a Python expression in a paused execution.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pause_id": {"type": "string"},
                        "expression": {"type": "string"},
                        "session_id": {"type": "string"},
                        "timeout_s": {"type": "number"},
                    },
                    "required": ["pause_id", "expression"],
                    "additionalProperties": True,
                },
            ),
            Tool(
                name="breakpoint_inspect_object",
                description="Inspect a serialized object by CID.",
                inputSchema={
                    "type": "object",
                    "properties": {"cid": {"type": "string"}},
                    "required": ["cid"],
                    "additionalProperties": True,
                },
            ),
        ]


@dataclass
class _SseSession:
    session_id: str
    read_writer: object
    write_stream: object
    write_reader: object
    queue: Queue[SessionMessage | None]
    closed: threading.Event
    portal: BlockingPortal
    portal_cm: AbstractContextManager[BlockingPortal]
    base_path: str

    def endpoint_path(self) -> str:
        return f"{self.base_path.rstrip('/')}/messages?session_id={self.session_id}"

    def iter_events(self) -> Iterator[bytes]:
        yield f"event: endpoint\ndata: {self.endpoint_path()}\n\n".encode("utf-8")
        while True:
            if self.closed.is_set():
                break
            try:
                item = self.queue.get(timeout=15.0)
            except Empty:
                if self.closed.is_set():
                    break
                yield b": ping\n\n"
                continue
            if item is None:
                break
            data = item.message.model_dump_json(by_alias=True, exclude_none=True)
            yield f"event: message\ndata: {data}\n\n".encode("utf-8")

    def close(self) -> None:
        if self.closed.is_set():
            return
        self.closed.set()
        try:
            self.queue.put(None)
        except Exception:
            pass
        try:
            self.portal.call(self.read_writer.close)
        except Exception:
            pass
        try:
            self.portal.call(self.write_stream.close)
        except Exception:
            pass
        try:
            self.portal.call(self.write_reader.close)
        except Exception:
            pass
        try:
            self.portal_cm.__exit__(None, None, None)
        except Exception:
            pass
