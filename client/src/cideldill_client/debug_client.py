"""HTTP client for communicating with the debug server."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any

import requests

from .exceptions import (
    DebugCIDNotFoundError,
    DebugProtocolError,
)
from .server_failure import exit_with_server_failure
from .serialization import Serializer

logger = logging.getLogger(__name__)


class DebugClient:
    """HTTP client used by debug proxies."""

    def __init__(
        self,
        server_url: str,
        timeout_s: float = 30.0,
        retry_timeout_s: float = 60.0,
        retry_sleep_s: float = 0.25,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._timeout_s = timeout_s
        self._retry_timeout_s = retry_timeout_s
        self._retry_sleep_s = retry_sleep_s
        self._serializer = Serializer()
        self._object_cache: OrderedDict[str, Any] = OrderedDict()
        self._object_cache_limit = 10_000
        self._process_pid = os.getpid()
        self._process_start_time = time.time()

    @property
    def server_url(self) -> str:
        return self._server_url

    def check_connection(self) -> None:
        """Verify that the server is reachable."""
        try:
            response = requests.get(
                f"{self._server_url}/api/breakpoints", timeout=self._timeout_s
            )
        except requests.RequestException as exc:
            exit_with_server_failure(
                "Debug server is unreachable",
                self._server_url,
                exc,
            )
        if response.status_code >= 400:
            exit_with_server_failure(
                f"Debug server error: {response.status_code} {response.text}",
                self._server_url,
            )


    def register_breakpoint(self, function_name: str, signature: str | None = None) -> None:
        payload: dict[str, Any] = {
            "function_name": function_name,
            "behavior": "go",
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

    def register_function(self, function_name: str, signature: str | None = None) -> None:
        self.register_breakpoint(function_name, signature=signature)
        payload: dict[str, Any] = {"function_name": function_name}
        if signature is not None:
            payload["signature"] = signature
        response = self._post_json("/api/functions", payload)
        if response.get("status") != "ok":
            exit_with_server_failure(
                "Debug server failed to register function",
                self._server_url,
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
    ) -> dict[str, Any]:
        payload, cid_to_obj = self._build_call_payload(
            method_name, target, target_cid, args, kwargs, call_site, signature
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
            if serialized.data_base64:
                payload["result_data"] = serialized.data_base64
        elif status == "exception" and exception is not None:
            payload["exception_type"] = type(exception).__name__
            payload["exception_message"] = str(exception)
            serialized = self._serializer.serialize(exception)
            payload["exception_cid"] = serialized.cid
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
                time.sleep(interval_ms / 1000.0)
                continue
            if status == "ready":
                return response.get("action", {})
            raise DebugProtocolError("Malformed poll response")
        logger.info(
            "Debug server poll timed out after %sms (poll_url=%s). Continuing to wait...",
            timeout_ms,
            poll_url,
        )
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
                await asyncio.sleep(interval_ms / 1000.0)
                continue
            if status == "ready":
                return response.get("action", {})
            raise DebugProtocolError("Malformed poll response")
        logger.info(
            "Debug server poll timed out after %sms (poll_url=%s). Continuing to wait...",
            timeout_ms,
            poll_url,
        )
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
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        cid_to_obj: dict[str, Any] = {}

        target_serialized = self._serializer.serialize(target)
        target_payload = {"cid": target_serialized.cid}
        if target_serialized.data_base64:
            target_payload["data"] = target_serialized.data_base64
        cid_to_obj[target_serialized.cid] = target
        self._remember_object(target_serialized.cid, target)

        args_payload = []
        for arg in args:
            serialized = self._serializer.serialize(arg)
            payload = {"cid": serialized.cid}
            if serialized.data_base64:
                payload["data"] = serialized.data_base64
            args_payload.append(payload)
            cid_to_obj[serialized.cid] = arg
            self._remember_object(serialized.cid, arg)

        kwargs_payload: dict[str, Any] = {}
        for key, value in kwargs.items():
            serialized = self._serializer.serialize(value)
            payload = {"cid": serialized.cid}
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
            "process_pid": self._process_pid,
            "process_start_time": self._process_start_time,
        }
        if signature is not None:
            payload["signature"] = signature
        return payload, cid_to_obj

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
                exit_with_server_failure(
                    "Debug server request failed",
                    self._server_url,
                    exc,
                )
        else:
            exit_with_server_failure(
                "Debug server request failed",
                self._server_url,
                last_exc,
            )

        if response.status_code >= 400:
            exit_with_server_failure(
                f"Debug server error: {response.status_code} {response.text}",
                self._server_url,
            )
        try:
            return response.json()
        except ValueError as exc:
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
                exit_with_server_failure(
                    "Debug server request failed",
                    self._server_url,
                    exc,
                )
        else:
            exit_with_server_failure(
                "Debug server request failed",
                self._server_url,
                last_exc,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise DebugProtocolError("Malformed JSON response") from exc

        if response.status_code >= 400 and data.get("error") != "cid_not_found":
            exit_with_server_failure(
                f"Debug server error: {response.status_code} {response.text}",
                self._server_url,
            )
        return data

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
                exit_with_server_failure(
                    "Debug server request failed",
                    self._server_url,
                    exc,
                )
        else:
            exit_with_server_failure(
                "Debug server request failed",
                self._server_url,
                last_exc,
            )
        if response.status_code >= 400:
            exit_with_server_failure(
                f"Debug server error: {response.status_code} {response.text}",
                self._server_url,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise DebugProtocolError("Malformed JSON response") from exc

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
