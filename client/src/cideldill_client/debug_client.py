"""HTTP client for communicating with the debug server."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import traceback
import weakref
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any

import requests

from .exceptions import (
    DebugCIDNotFoundError,
    DebugProtocolError,
)
from .server_failure import exit_with_server_failure
from .serialization import Serializer, set_serialization_error_reporter

logger = logging.getLogger(__name__)

_PROCESS_IDENTITY_LOCK = threading.Lock()
_PROCESS_IDENTITY: dict[str, float | int | None] = {
    "pid": None,
    "start_time": None,
}


def _get_process_identity() -> tuple[int, float]:
    pid = os.getpid()
    with _PROCESS_IDENTITY_LOCK:
        cached_pid = _PROCESS_IDENTITY.get("pid")
        cached_start = _PROCESS_IDENTITY.get("start_time")
        if cached_pid == pid and isinstance(cached_start, float):
            return pid, cached_start
        start_time = time.time()
        _PROCESS_IDENTITY["pid"] = pid
        _PROCESS_IDENTITY["start_time"] = start_time
        return pid, start_time


class DebugClient:
    """HTTP client used by debug proxies."""

    def __init__(
        self,
        server_url: str,
        timeout_s: float = 30.0,
        retry_timeout_s: float = 60.0,
        retry_sleep_s: float = 0.25,
        suspended_breakpoints_log_interval_s: float = 60.0,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._timeout_s = timeout_s
        self._retry_timeout_s = retry_timeout_s
        self._retry_sleep_s = retry_sleep_s
        self._suspended_breakpoints_log_interval_s = max(0.0, suspended_breakpoints_log_interval_s)
        self._next_suspended_breakpoints_log_at: dict[str, float] = {}
        self._suspended_breakpoints_lock = threading.Lock()
        self._serializer = Serializer()
        self._object_cache: OrderedDict[str, Any] = OrderedDict()
        self._object_cache_limit = 10_000
        self._client_ref_counter = 0
        self._client_ref_lock = threading.Lock()
        self._client_ref_by_obj: weakref.WeakKeyDictionary[Any, int] = weakref.WeakKeyDictionary()
        self._client_ref_by_id: dict[int, int] = {}
        self._client_ref_objects: OrderedDict[int, Any] = OrderedDict()
        self._client_ref_cache_limit = 10_000
        self._process_pid, self._process_start_time = _get_process_identity()
        self._events_enabled = False
        set_serialization_error_reporter(self._report_serialization_error)

    @property
    def server_url(self) -> str:
        return self._server_url

    def enable_events(self) -> None:
        self._events_enabled = True

    def check_connection(self) -> None:
        """Verify that the server is reachable."""
        try:
            response = requests.get(
                f"{self._server_url}/api/breakpoints", timeout=self._timeout_s
            )
        except requests.RequestException as exc:
            self._report_com_error(
                "Debug server is unreachable",
                method="GET",
                path="/api/breakpoints",
                exception=exc,
            )
            exit_with_server_failure(
                "Debug server is unreachable",
                self._server_url,
                exc,
            )
        if response.status_code >= 400:
            self._report_com_error(
                "Debug server error",
                method="GET",
                path="/api/breakpoints",
                status_code=response.status_code,
                response_text=response.text,
            )
            exit_with_server_failure(
                f"Debug server error: {response.status_code} {response.text}",
                self._server_url,
            )


    def register_breakpoint(self, function_name: str, signature: str | None = None) -> None:
        payload: dict[str, Any] = {
            "function_name": function_name,
            "timestamp": time.time(),
        }
        if signature is not None:
            payload["signature"] = signature
        response = self._post_json("/api/breakpoints", payload)
        if response.get("status") != "ok":
            exit_with_server_failure(
                "Debug server failed to register breakpoint",
                self._server_url,
            )

    def register_function(
        self,
        function_name: str,
        signature: str | None = None,
        *,
        target: Any | None = None,
    ) -> None:
        self.register_breakpoint(function_name, signature=signature)
        payload: dict[str, Any] = {"function_name": function_name}
        if signature is not None:
            payload["signature"] = signature
        if target is not None:
            payload["function_client_ref"] = self._get_client_ref(target)
            serialized = self._serializer.force_serialize_with_data(target)
            if serialized.data_base64:
                try:
                    value = self._serializer.deserialize_base64(serialized.data_base64)
                except Exception:
                    value = None
                if value is not None and self._is_placeholder(value):
                    payload["function_cid"] = serialized.cid
                    payload["function_data"] = serialized.data_base64
        response = self._post_json("/api/functions", payload)
        if response.get("status") != "ok":
            exit_with_server_failure(
                "Debug server failed to register function",
                self._server_url,
            )

    @staticmethod
    def _is_placeholder(value: Any) -> bool:
        return (
            hasattr(value, "pickle_error")
            and hasattr(value, "attributes")
            and hasattr(value, "failed_attributes")
            and hasattr(value, "type_name")
        )

    def record_call_start(
        self,
        method_name: str,
        target: Any,
        target_cid: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        call_site: dict[str, Any],
        signature: str | None = None,
        *,
        call_type: str,
    ) -> dict[str, Any]:
        alias_name = getattr(target, "_cideldill_alias_name", None)
        effective_name = alias_name or method_name
        payload, cid_to_obj = self._build_call_payload(
            effective_name, target, target_cid, args, kwargs, call_site, signature,
            call_type=call_type,
        )
        response = self._post_json_allowing_cid_errors("/api/call/start", payload)
        if response.get("error") == "cid_not_found":
            missing = response.get("missing_cids", [])
            if not missing:
                raise DebugCIDNotFoundError("<unknown>")
            payload = self._attach_missing_data(payload, cid_to_obj, missing)
            response = self._post_json_allowing_cid_errors("/api/call/start", payload)
            if response.get("error") == "cid_not_found":
                raise DebugCIDNotFoundError(missing[0])
        return self._require_action(response)

    def record_call_complete(
        self,
        call_id: str,
        status: str,
        result: Any | None = None,
        exception: BaseException | None = None,
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {
            "call_id": call_id,
            "timestamp": time.time(),
            "status": status,
            "process_pid": self._process_pid,
            "process_start_time": self._process_start_time,
        }
        if status == "success":
            serialized = self._serializer.serialize(result)
            payload["result_cid"] = serialized.cid
            payload["result_client_ref"] = self._get_client_ref(result)
            if serialized.data_base64:
                payload["result_data"] = serialized.data_base64
        elif status == "exception" and exception is not None:
            payload["exception_type"] = type(exception).__name__
            payload["exception_message"] = str(exception)
            serialized = self._serializer.serialize(exception)
            payload["exception_cid"] = serialized.cid
            payload["exception_client_ref"] = self._get_client_ref(exception)
            if serialized.data_base64:
                payload["exception_data"] = serialized.data_base64
        else:
            raise DebugProtocolError("Invalid call completion payload")

        response = self._post_json("/api/call/complete", payload)
        if response.get("action"):
            return self._require_action(response)
        if response.get("status") != "ok":
            exit_with_server_failure(
                "Debug server failed to acknowledge completion",
                self._server_url,
            )
        return None

    def poll(self, action: dict[str, Any]) -> dict[str, Any]:
        poll_url = action.get("poll_url")
        interval_ms = action.get("poll_interval_ms", 100)
        timeout_ms = action.get("timeout_ms", 60_000)
        if not poll_url:
            raise DebugProtocolError("Missing poll_url for poll action")

        deadline = time.time() + (timeout_ms / 1000.0)
        while time.time() < deadline:
            response = self._get_json(poll_url)
            status = response.get("status")
            if status == "waiting":
                self._log_suspended_breakpoints_if_due(poll_url)
                time.sleep(interval_ms / 1000.0)
                continue
            if status == "ready":
                self._clear_suspended_breakpoint_timer(poll_url)
                return response.get("action", {})
            self._clear_suspended_breakpoint_timer(poll_url)
            raise DebugProtocolError("Malformed poll response")
        logger.info(
            "Debug server poll timed out after %sms (poll_url=%s). Continuing to wait...",
            timeout_ms,
            poll_url,
        )
        self._log_suspended_breakpoints_if_due(poll_url)
        return action

    async def async_poll(self, action: dict[str, Any]) -> dict[str, Any]:
        poll_url = action.get("poll_url")
        interval_ms = action.get("poll_interval_ms", 100)
        timeout_ms = action.get("timeout_ms", 60_000)
        if not poll_url:
            raise DebugProtocolError("Missing poll_url for poll action")

        deadline = time.time() + (timeout_ms / 1000.0)
        while time.time() < deadline:
            response = self._get_json(poll_url)
            status = response.get("status")
            if status == "waiting":
                self._log_suspended_breakpoints_if_due(poll_url)
                await asyncio.sleep(interval_ms / 1000.0)
                continue
            if status == "ready":
                self._clear_suspended_breakpoint_timer(poll_url)
                return response.get("action", {})
            self._clear_suspended_breakpoint_timer(poll_url)
            raise DebugProtocolError("Malformed poll response")
        logger.info(
            "Debug server poll timed out after %sms (poll_url=%s). Continuing to wait...",
            timeout_ms,
            poll_url,
        )
        self._log_suspended_breakpoints_if_due(poll_url)
        return action

    def deserialize_payload_item(self, item: dict[str, Any]) -> Any:
        if "data" in item:
            return self._serializer.deserialize_base64(item["data"])
        if "cid" in item:
            cached = self._object_cache.get(item["cid"])
            if cached is None:
                raise DebugProtocolError("Missing data for CID in response")
            return cached
        raise DebugProtocolError("Malformed serialized item")

    def deserialize_payload_list(self, items: Iterable[dict[str, Any]]) -> list[Any]:
        return [self.deserialize_payload_item(item) for item in items]

    def deserialize_payload_dict(self, items: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {key: self.deserialize_payload_item(value) for key, value in items.items()}

    def _build_call_payload(
        self,
        method_name: str,
        target: Any,
        target_cid: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        call_site: dict[str, Any],
        signature: str | None,
        *,
        call_type: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        cid_to_obj: dict[str, Any] = {}

        target_serialized = self._serializer.serialize(target)
        target_payload = {
            "cid": target_serialized.cid,
            "client_ref": self._get_client_ref(target),
        }
        if target_serialized.data_base64:
            target_payload["data"] = target_serialized.data_base64
        cid_to_obj[target_serialized.cid] = target
        self._remember_object(target_serialized.cid, target)

        args_payload = []
        for arg in args:
            serialized = self._serializer.serialize(arg)
            payload = {
                "cid": serialized.cid,
                "client_ref": self._get_client_ref(arg),
            }
            if serialized.data_base64:
                payload["data"] = serialized.data_base64
            args_payload.append(payload)
            cid_to_obj[serialized.cid] = arg
            self._remember_object(serialized.cid, arg)

        kwargs_payload: dict[str, Any] = {}
        for key, value in kwargs.items():
            serialized = self._serializer.serialize(value)
            payload = {
                "cid": serialized.cid,
                "client_ref": self._get_client_ref(value),
            }
            if serialized.data_base64:
                payload["data"] = serialized.data_base64
            kwargs_payload[key] = payload
            cid_to_obj[serialized.cid] = value
            self._remember_object(serialized.cid, value)

        payload = {
            "method_name": method_name,
            "target_cid": target_cid,
            "target": target_payload,
            "args": args_payload,
            "kwargs": kwargs_payload,
            "call_site": call_site,
            "call_type": call_type,
            "process_pid": self._process_pid,
            "process_start_time": self._process_start_time,
        }
        if signature is not None:
            payload["signature"] = signature
        return payload, cid_to_obj

    def _get_client_ref(self, obj: Any) -> int:
        try:
            with self._client_ref_lock:
                try:
                    existing = self._client_ref_by_obj.get(obj)
                except TypeError:
                    existing = None
                if existing is not None:
                    return existing
                obj_id = id(obj)
                existing = self._client_ref_by_id.get(obj_id)
                if existing is not None:
                    if obj_id in self._client_ref_objects:
                        self._client_ref_objects.move_to_end(obj_id)
                    return existing
                self._client_ref_counter += 1
                ref = self._client_ref_counter
                try:
                    self._client_ref_by_obj[obj] = ref
                    return ref
                except TypeError:
                    self._client_ref_by_id[obj_id] = ref
                    self._client_ref_objects[obj_id] = obj
                    if len(self._client_ref_objects) > self._client_ref_cache_limit:
                        oldest_id, _ = self._client_ref_objects.popitem(last=False)
                        self._client_ref_by_id.pop(oldest_id, None)
                    return ref
        except Exception:
            with self._client_ref_lock:
                self._client_ref_counter += 1
                return self._client_ref_counter

    def _attach_missing_data(
        self, payload: dict[str, Any], cid_to_obj: dict[str, Any], missing: Iterable[str]
    ) -> dict[str, Any]:
        missing_set = set(missing)

        def ensure_data(item: dict[str, Any]) -> None:
            cid = item.get("cid")
            if cid in missing_set and "data" not in item:
                obj = cid_to_obj.get(cid)
                if obj is None:
                    raise DebugCIDNotFoundError(cid)
                serialized = self._serializer.force_serialize_with_data(obj)
                item["data"] = serialized.data_base64

        target = payload.get("target")
        if isinstance(target, dict):
            ensure_data(target)

        for item in payload.get("args", []):
            ensure_data(item)

        for item in payload.get("kwargs", {}).values():
            ensure_data(item)

        return payload

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        deadline = time.time() + self._retry_timeout_s
        last_exc: BaseException | None = None
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            try:
                response = requests.post(
                    f"{self._server_url}{path}",
                    json=payload,
                    timeout=self._timeout_s,
                )
                break
            except requests.exceptions.Timeout as exc:
                last_exc = exc
                logger.warning(
                    "Debug server request timed out (attempt %s path=%s timeout_s=%.1f).",
                    attempt,
                    path,
                    self._timeout_s,
                )
                time.sleep(self._retry_sleep_s)
            except requests.RequestException as exc:
                self._report_com_error(
                    "Debug server request failed",
                    method="POST",
                    path=path,
                    payload=payload,
                    exception=exc,
                )
                exit_with_server_failure(
                    "Debug server request failed",
                    self._server_url,
                    exc,
                )
        else:
            self._report_com_error(
                "Debug server request failed",
                method="POST",
                path=path,
                payload=payload,
                exception=last_exc,
            )
            exit_with_server_failure(
                "Debug server request failed",
                self._server_url,
                last_exc,
            )

        if response.status_code >= 400:
            self._report_com_error(
                "Debug server error",
                method="POST",
                path=path,
                payload=payload,
                status_code=response.status_code,
                response_text=response.text,
            )
            exit_with_server_failure(
                f"Debug server error: {response.status_code} {response.text}",
                self._server_url,
            )
        try:
            return response.json()
        except ValueError as exc:
            self._report_com_error(
                "Malformed JSON response",
                method="POST",
                path=path,
                payload=payload,
                status_code=response.status_code,
                response_text=response.text,
                exception=exc,
            )
            raise DebugProtocolError("Malformed JSON response") from exc

    def _post_json_allowing_cid_errors(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        deadline = time.time() + self._retry_timeout_s
        last_exc: BaseException | None = None
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            try:
                response = requests.post(
                    f"{self._server_url}{path}",
                    json=payload,
                    timeout=self._timeout_s,
                )
                break
            except requests.exceptions.Timeout as exc:
                last_exc = exc
                logger.warning(
                    "Debug server request timed out (attempt %s path=%s timeout_s=%.1f).",
                    attempt,
                    path,
                    self._timeout_s,
                )
                time.sleep(self._retry_sleep_s)
            except requests.RequestException as exc:
                self._report_com_error(
                    "Debug server request failed",
                    method="POST",
                    path=path,
                    payload=payload,
                    exception=exc,
                )
                exit_with_server_failure(
                    "Debug server request failed",
                    self._server_url,
                    exc,
                )
        else:
            self._report_com_error(
                "Debug server request failed",
                method="POST",
                path=path,
                payload=payload,
                exception=last_exc,
            )
            exit_with_server_failure(
                "Debug server request failed",
                self._server_url,
                last_exc,
            )

        try:
            data = response.json()
        except ValueError as exc:
            self._report_com_error(
                "Malformed JSON response",
                method="POST",
                path=path,
                payload=payload,
                status_code=response.status_code,
                response_text=response.text,
                exception=exc,
            )
            raise DebugProtocolError("Malformed JSON response") from exc

        if response.status_code >= 400 and data.get("error") != "cid_not_found":
            self._report_com_error(
                "Debug server error",
                method="POST",
                path=path,
                payload=payload,
                status_code=response.status_code,
                response_text=response.text,
            )
            exit_with_server_failure(
                f"Debug server error: {response.status_code} {response.text}",
                self._server_url,
            )
        return data

    def record_event(
        self,
        *,
        method_name: str,
        status: str,
        call_site: dict[str, Any],
        pretty_args: list[Any] | None = None,
        pretty_kwargs: dict[str, Any] | None = None,
        signature: str | None = None,
        result: Any | None = None,
        exception: Any | None = None,
        result_cid: str | None = None,
        result_data: str | None = None,
        exception_cid: str | None = None,
        exception_data: str | None = None,
    ) -> None:
        if not self._events_enabled:
            return
        payload: dict[str, Any] = {
            "method_name": method_name,
            "status": status,
            "timestamp": time.time(),
            "call_site": call_site,
            "process_pid": self._process_pid,
            "process_start_time": self._process_start_time,
            "pretty_args": pretty_args or [],
            "pretty_kwargs": pretty_kwargs or {},
        }
        if signature is not None:
            payload["signature"] = signature
        if result is not None:
            payload["pretty_result"] = self._sanitize_for_json(result)
        if result_cid is not None and result_data is not None:
            payload["result_cid"] = result_cid
            payload["result_data"] = result_data
        if exception is not None:
            payload["exception"] = self._sanitize_for_json(exception)
        if exception_cid is not None and exception_data is not None:
            payload["exception_cid"] = exception_cid
            payload["exception_data"] = exception_data

        response = self._post_json("/api/call/event", payload)
        if response.get("status") != "ok":
            exit_with_server_failure(
                "Debug server failed to record debug event",
                self._server_url,
            )

    def _report_serialization_error(self, payload: dict[str, Any]) -> None:
        if not self._events_enabled:
            return
        info = dict(payload)
        placeholder_cid = info.pop("placeholder_cid", None)
        placeholder_data = info.pop("placeholder_data", None)
        call_site = info.pop("call_site", None) or {"timestamp": time.time(), "stack_trace": []}
        pretty_kwargs = {
            "object_type": info.get("object_type"),
            "object_id": info.get("object_id"),
        }
        self.record_event(
            method_name="pickle_error",
            status="serialization_error",
            call_site=call_site,
            pretty_kwargs=pretty_kwargs,
            exception=info,
            exception_cid=placeholder_cid,
            exception_data=placeholder_data,
        )

    def _get_json(self, path: str) -> dict[str, Any]:
        deadline = time.time() + self._retry_timeout_s
        last_exc: BaseException | None = None
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            try:
                response = requests.get(
                    f"{self._server_url}{path}",
                    timeout=self._timeout_s,
                )
                break
            except requests.exceptions.Timeout as exc:
                last_exc = exc
                logger.warning(
                    "Debug server request timed out (attempt %s path=%s timeout_s=%.1f).",
                    attempt,
                    path,
                    self._timeout_s,
                )
                time.sleep(self._retry_sleep_s)
            except requests.RequestException as exc:
                self._report_com_error(
                    "Debug server request failed",
                    method="GET",
                    path=path,
                    exception=exc,
                )
                exit_with_server_failure(
                    "Debug server request failed",
                    self._server_url,
                    exc,
                )
        else:
            self._report_com_error(
                "Debug server request failed",
                method="GET",
                path=path,
                exception=last_exc,
            )
            exit_with_server_failure(
                "Debug server request failed",
                self._server_url,
                last_exc,
            )
        if response.status_code >= 400:
            self._report_com_error(
                "Debug server error",
                method="GET",
                path=path,
                status_code=response.status_code,
                response_text=response.text,
            )
            exit_with_server_failure(
                f"Debug server error: {response.status_code} {response.text}",
                self._server_url,
            )
        try:
            return response.json()
        except ValueError as exc:
            self._report_com_error(
                "Malformed JSON response",
                method="GET",
                path=path,
                status_code=response.status_code,
                response_text=response.text,
                exception=exc,
            )
            raise DebugProtocolError("Malformed JSON response") from exc

    def _sanitize_for_json(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): self._sanitize_for_json(val) for key, val in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._sanitize_for_json(item) for item in value]
        return repr(value)

    def _truncate_text(self, text: str, limit: int = 4000) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + "..."

    def _report_com_error(
        self,
        summary: str,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        status_code: int | None = None,
        response_text: str | None = None,
        exception: BaseException | None = None,
    ) -> None:
        error_payload: dict[str, Any] = {
            "summary": summary,
            "timestamp": time.time(),
            "method": method,
            "path": path,
            "server_url": self._server_url,
            "process_pid": self._process_pid,
            "process_start_time": self._process_start_time,
        }
        if payload is not None:
            error_payload["payload"] = self._sanitize_for_json(payload)
        if status_code is not None:
            error_payload["status_code"] = status_code
        if response_text is not None:
            error_payload["response_text"] = self._truncate_text(str(response_text))
        if exception is not None:
            error_payload["exception_type"] = type(exception).__name__
            error_payload["exception_message"] = str(exception)
            error_payload["traceback"] = self._truncate_text(traceback.format_exc())

        try:
            requests.post(
                f"{self._server_url}/api/report-com-error",
                json=error_payload,
                timeout=min(5.0, self._timeout_s),
            )
        except requests.RequestException:
            return

    def _log_suspended_breakpoints_if_due(self, poll_url: str) -> None:
        interval_s = self._suspended_breakpoints_log_interval_s
        if interval_s <= 0.0:
            return

        now = time.time()
        with self._suspended_breakpoints_lock:
            next_log_at = self._next_suspended_breakpoints_log_at.get(poll_url)
            if next_log_at is None:
                self._next_suspended_breakpoints_log_at[poll_url] = now + interval_s
                return
            if now < next_log_at:
                return
            self._next_suspended_breakpoints_log_at[poll_url] = now + interval_s

        paused = self._get_paused_executions_for_logging()
        if paused is None:
            return
        if not paused:
            logger.warning(
                "Long-running suspended breakpoint poll (poll_url=%s). "
                "No suspended breakpoints are visible on the server.",
                poll_url,
            )
            return

        summaries = ", ".join(self._format_paused_execution_summary(item) for item in paused)
        logger.warning(
            "Long-running suspended breakpoint poll (poll_url=%s). "
            "Suspended breakpoints on server (%s): %s",
            poll_url,
            len(paused),
            summaries,
        )

    def _clear_suspended_breakpoint_timer(self, poll_url: str) -> None:
        with self._suspended_breakpoints_lock:
            self._next_suspended_breakpoints_log_at.pop(poll_url, None)

    def _get_paused_executions_for_logging(self) -> list[dict[str, Any]] | None:
        response = self._get_json_nonfatal("/api/paused")
        if response is None:
            return None
        paused = response.get("paused")
        if not isinstance(paused, list):
            logger.warning(
                "Unable to list suspended breakpoints: malformed /api/paused response (%r).",
                response,
            )
            return None
        return [item for item in paused if isinstance(item, dict)]

    def _get_json_nonfatal(self, path: str) -> dict[str, Any] | None:
        url = f"{self._server_url}{path}"
        try:
            response = requests.get(url, timeout=min(5.0, self._timeout_s))
        except requests.RequestException as exc:
            logger.warning(
                "Unable to list suspended breakpoints: GET %s failed (%s: %s).",
                path,
                type(exc).__name__,
                exc,
            )
            return None

        if response.status_code >= 400:
            logger.warning(
                "Unable to list suspended breakpoints: GET %s returned %s.",
                path,
                response.status_code,
            )
            return None
        try:
            payload = response.json()
        except ValueError:
            logger.warning(
                "Unable to list suspended breakpoints: GET %s returned malformed JSON.",
                path,
            )
            return None
        if not isinstance(payload, dict):
            logger.warning(
                "Unable to list suspended breakpoints: GET %s returned non-object payload.",
                path,
            )
            return None
        return payload

    def _format_paused_execution_summary(self, paused: dict[str, Any]) -> str:
        call_data = paused.get("call_data")
        method_name = "<unknown>"
        if isinstance(call_data, dict):
            method_name = str(
                call_data.get("method_name")
                or call_data.get("function_name")
                or "<unknown>"
            )
        elif paused.get("method_name") or paused.get("function_name"):
            method_name = str(paused.get("method_name") or paused.get("function_name"))
        pause_id = str(paused.get("id", "<unknown>"))
        paused_at = paused.get("paused_at")
        if isinstance(paused_at, (int, float)):
            age_s = max(0.0, time.time() - float(paused_at))
            return f"{method_name}[id={pause_id}, age={age_s:.1f}s]"
        return f"{method_name}[id={pause_id}]"

    def _require_action(self, response: dict[str, Any]) -> dict[str, Any]:
        if "action" not in response:
            raise DebugProtocolError("Missing action in response")
        return response

    def _remember_object(self, cid: str, obj: Any) -> None:
        if cid in self._object_cache:
            self._object_cache.move_to_end(cid)
        else:
            self._object_cache[cid] = obj
            if len(self._object_cache) > self._object_cache_limit:
                self._object_cache.popitem(last=False)
