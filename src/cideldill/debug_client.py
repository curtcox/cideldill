"""HTTP client for communicating with the debug server."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

from .exceptions import (
    DebugCIDNotFoundError,
    DebugProtocolError,
    DebugServerError,
    DebugTimeoutError,
)
from .serialization import Serializer


class DebugClient:
    """HTTP client used by debug proxies."""

    def __init__(self, server_url: str, timeout_s: float = 5.0) -> None:
        self._server_url = server_url.rstrip("/")
        self._timeout_s = timeout_s
        self._serializer = Serializer()
        self._object_cache: OrderedDict[str, Any] = OrderedDict()
        self._object_cache_limit = 10_000

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
            raise DebugServerError("Debug server is unreachable") from exc
        if response.status_code >= 400:
            raise DebugServerError(
                f"Debug server error: {response.status_code} {response.text}"
            )

    def record_call_start(
        self,
        method_name: str,
        target: Any,
        target_cid: str,
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
        call_site: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload, cid_to_obj = self._build_call_payload(
            method_name, target, target_cid, args, kwargs, call_site
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
        result: Optional[Any] = None,
        exception: Optional[BaseException] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "call_id": call_id,
            "timestamp": time.time(),
            "status": status,
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
        if response.get("status") != "ok":
            raise DebugServerError("Debug server failed to acknowledge completion")

    def poll(self, action: Dict[str, Any]) -> Dict[str, Any]:
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
        raise DebugTimeoutError("Polling timed out")

    async def async_poll(self, action: Dict[str, Any]) -> Dict[str, Any]:
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
        raise DebugTimeoutError("Polling timed out")

    def deserialize_payload_item(self, item: Dict[str, Any]) -> Any:
        if "data" in item:
            return self._serializer.deserialize_base64(item["data"])
        if "cid" in item:
            cached = self._object_cache.get(item["cid"])
            if cached is None:
                raise DebugProtocolError("Missing data for CID in response")
            return cached
        raise DebugProtocolError("Malformed serialized item")

    def deserialize_payload_list(self, items: Iterable[Dict[str, Any]]) -> List[Any]:
        return [self.deserialize_payload_item(item) for item in items]

    def deserialize_payload_dict(self, items: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        return {key: self.deserialize_payload_item(value) for key, value in items.items()}

    def _build_call_payload(
        self,
        method_name: str,
        target: Any,
        target_cid: str,
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
        call_site: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        cid_to_obj: Dict[str, Any] = {}

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

        kwargs_payload: Dict[str, Any] = {}
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
        }
        return payload, cid_to_obj

    def _attach_missing_data(
        self, payload: Dict[str, Any], cid_to_obj: Dict[str, Any], missing: Iterable[str]
    ) -> Dict[str, Any]:
        missing_set = set(missing)

        def ensure_data(item: Dict[str, Any]) -> None:
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

    def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = requests.post(
                f"{self._server_url}{path}",
                json=payload,
                timeout=self._timeout_s,
            )
        except requests.RequestException as exc:
            raise DebugServerError("Debug server request failed") from exc
        if response.status_code >= 400:
            raise DebugServerError(
                f"Debug server error: {response.status_code} {response.text}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise DebugProtocolError("Malformed JSON response") from exc

    def _post_json_allowing_cid_errors(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = requests.post(
                f"{self._server_url}{path}",
                json=payload,
                timeout=self._timeout_s,
            )
        except requests.RequestException as exc:
            raise DebugServerError("Debug server request failed") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise DebugProtocolError("Malformed JSON response") from exc

        if response.status_code >= 400 and data.get("error") != "cid_not_found":
            raise DebugServerError(
                f"Debug server error: {response.status_code} {response.text}"
            )
        return data

    def _get_json(self, path: str) -> Dict[str, Any]:
        try:
            response = requests.get(
                f"{self._server_url}{path}",
                timeout=self._timeout_s,
            )
        except requests.RequestException as exc:
            raise DebugServerError("Debug server request failed") from exc
        if response.status_code >= 400:
            raise DebugServerError(
                f"Debug server error: {response.status_code} {response.text}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise DebugProtocolError("Malformed JSON response") from exc

    def _require_action(self, response: Dict[str, Any]) -> Dict[str, Any]:
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
