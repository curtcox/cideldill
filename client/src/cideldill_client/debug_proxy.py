"""Debug proxy implementations."""

from __future__ import annotations

import builtins
import inspect
import logging
import time
from typing import Any, Callable

from .debug_client import DebugClient
from .exceptions import DebugProtocolError, DebugServerError
from .function_registry import compute_signature, get_function
from .serialization import compute_cid

logger = logging.getLogger(__name__)


def _build_stack_trace(skip: int = 2) -> list[dict[str, Any]]:
    stack = inspect.stack()
    frames = stack[skip:]
    trace: list[dict[str, Any]] = []
    for frame in frames:
        trace.append({
            "filename": frame.filename,
            "lineno": frame.lineno,
            "function": frame.function,
            "code_context": frame.code_context[0].strip() if frame.code_context else None,
        })
    return trace


class DebugProxy:
    """Transparent proxy that intercepts calls for debugging."""

    def __init__(
        self,
        target: Any,
        client: DebugClient,
        is_enabled: Callable[[], bool],
    ) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_is_enabled", is_enabled)
        object.__setattr__(self, "_cid", compute_cid(target))

    @property
    def cid(self) -> str:
        return object.__getattribute__(self, "_cid")

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._target, name)
        if callable(attr):
            if inspect.iscoroutinefunction(attr):
                return self._wrap_async_method(attr, name)
            return self._wrap_method(attr, name)
        return attr

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._target, name, value)

    def _wrap_method(self, method: Callable[..., Any], name: str) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not self._is_enabled():
                return method(*args, **kwargs)

            call_site = {
                "timestamp": time.time(),
                "target_cid": self._cid,
                "stack_trace": _build_stack_trace(skip=3),
            }

            action = self._client.record_call_start(
                method_name=name,
                target=self._target,
                target_cid=self._cid,
                args=args,
                kwargs=kwargs,
                call_site=call_site,
                signature=compute_signature(method),
            )

            call_id = action.get("call_id")
            if not call_id:
                raise DebugProtocolError("Missing call_id in response")

            try:
                result = self._execute_action(action, method, args, kwargs)
            except Exception as exc:  # noqa: BLE001 - re-raise after reporting
                try:
                    self._client.record_call_complete(
                        call_id=call_id,
                        status="exception",
                        exception=exc,
                    )
                except DebugServerError:
                    logger.exception(
                        "Failed to report call completion to debug server "
                        "(call_id=%s status=exception)",
                        call_id,
                    )
                raise

            try:
                post_action = self._client.record_call_complete(
                    call_id=call_id,
                    status="success",
                    result=result,
                )
                if post_action:
                    self._wait_for_post_completion(post_action)
            except DebugServerError:
                logger.exception(
                    "Failed to report call completion to debug server "
                    "(call_id=%s status=success)",
                    call_id,
                )
            return result

        return wrapper

    def _wrap_async_method(self, method: Callable[..., Any], name: str) -> Callable[..., Any]:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not self._is_enabled():
                return await method(*args, **kwargs)

            call_site = {
                "timestamp": time.time(),
                "target_cid": self._cid,
                "stack_trace": _build_stack_trace(skip=3),
            }

            action = self._client.record_call_start(
                method_name=name,
                target=self._target,
                target_cid=self._cid,
                args=args,
                kwargs=kwargs,
                call_site=call_site,
                signature=compute_signature(method),
            )

            call_id = action.get("call_id")
            if not call_id:
                raise DebugProtocolError("Missing call_id in response")

            try:
                result = await self._execute_action_async(action, method, args, kwargs)
            except Exception as exc:  # noqa: BLE001 - re-raise after reporting
                try:
                    self._client.record_call_complete(
                        call_id=call_id,
                        status="exception",
                        exception=exc,
                    )
                except DebugServerError:
                    logger.exception(
                        "Failed to report call completion to debug server (call_id=%s status=exception)",
                        call_id,
                    )
                raise

            try:
                post_action = self._client.record_call_complete(
                    call_id=call_id,
                    status="success",
                    result=result,
                )
                if post_action:
                    await self._wait_for_post_completion_async(post_action)
            except DebugServerError:
                logger.exception(
                    "Failed to report call completion to debug server (call_id=%s status=success)",
                    call_id,
                )
            return result

        return wrapper

    def _execute_action(
        self,
        action: dict[str, Any],
        method: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        while action.get("action") == "poll":
            action = self._client.poll(action)

        action_type = action.get("action")
        if action_type == "continue":
            return method(*args, **kwargs)
        if action_type == "replace":
            function_name = action.get("function_name")
            if not function_name:
                raise DebugProtocolError("Missing function_name for replace action")
            replacement = get_function(function_name)
            if replacement is None:
                raise DebugProtocolError(f"Unknown replacement function: {function_name}")
            return replacement(*args, **kwargs)
        if action_type == "modify":
            new_args, new_kwargs = self._deserialize_modified(action)
            return method(*new_args, **new_kwargs)
        if action_type == "skip":
            return self._deserialize_fake_result(action)
        if action_type == "raise":
            raise self._deserialize_exception(action)
        raise DebugProtocolError(f"Unknown action: {action_type}")

    async def _execute_action_async(
        self,
        action: dict[str, Any],
        method: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        while action.get("action") == "poll":
            action = await self._client.async_poll(action)

        action_type = action.get("action")
        if action_type == "continue":
            return await method(*args, **kwargs)
        if action_type == "replace":
            function_name = action.get("function_name")
            if not function_name:
                raise DebugProtocolError("Missing function_name for replace action")
            replacement = get_function(function_name)
            if replacement is None:
                raise DebugProtocolError(f"Unknown replacement function: {function_name}")
            result = replacement(*args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        if action_type == "modify":
            new_args, new_kwargs = self._deserialize_modified(action)
            return await method(*new_args, **new_kwargs)
        if action_type == "skip":
            return self._deserialize_fake_result(action)
        if action_type == "raise":
            raise self._deserialize_exception(action)
        raise DebugProtocolError(f"Unknown action: {action_type}")

    def _deserialize_modified(
        self, action: dict[str, Any]
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        modified_args = action.get("modified_args", [])
        modified_kwargs = action.get("modified_kwargs", {})
        args = tuple(self._client.deserialize_payload_list(modified_args))
        kwargs = self._client.deserialize_payload_dict(modified_kwargs)
        return args, kwargs

    def _deserialize_fake_result(self, action: dict[str, Any]) -> Any:
        if "fake_result_data" in action:
            return self._client.deserialize_payload_item({"data": action["fake_result_data"]})
        if "fake_result" in action:
            return action["fake_result"]
        if "fake_result_cid" in action:
            return self._client.deserialize_payload_item({"cid": action["fake_result_cid"]})
        return None

    def _deserialize_exception(self, action: dict[str, Any]) -> Exception:
        exc_type = action.get("exception_type", "Exception")
        message = action.get("exception_message", "")
        exc_class = getattr(builtins, exc_type, Exception)
        return exc_class(message)

    def _intercept_dunder(self, name: str, *args: Any, **kwargs: Any) -> Any:
        attr = getattr(self._target, name)
        if callable(attr):
            if self._is_enabled():
                return self._wrap_method(attr, name)(*args, **kwargs)
            return attr(*args, **kwargs)
        return attr

    def __str__(self) -> str:
        return self._intercept_dunder("__str__")

    def __repr__(self) -> str:
        return self._intercept_dunder("__repr__")

    def __iter__(self) -> Any:
        return self._intercept_dunder("__iter__")

    def __len__(self) -> int:
        return self._intercept_dunder("__len__")

    def __getitem__(self, key: Any) -> Any:
        return self._intercept_dunder("__getitem__", key)

    def __setitem__(self, key: Any, value: Any) -> None:
        return self._intercept_dunder("__setitem__", key, value)

    def __delitem__(self, key: Any) -> None:
        return self._intercept_dunder("__delitem__", key)

    def __contains__(self, item: Any) -> bool:
        return self._intercept_dunder("__contains__", item)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        # For wrapped functions, use the actual function name for breakpoint matching
        # instead of "__call__"
        if callable(self._target) and hasattr(self._target, '__name__'):
            alias_name = getattr(self, "_cideldill_alias_name", None)
            if not alias_name:
                alias_name = getattr(self._target, "_cideldill_alias_name", None)
            method_name = alias_name or self._target.__name__
            # Call the target function directly with the correct name for breakpoint matching
            if self._is_enabled():
                return self._wrap_method(self._target, method_name)(*args, **kwargs)
            return self._target(*args, **kwargs)
        return self._intercept_dunder("__call__", *args, **kwargs)

    def __enter__(self) -> Any:
        return self._intercept_dunder("__enter__")

    def __exit__(self, exc_type, exc, tb) -> Any:
        return self._intercept_dunder("__exit__", exc_type, exc, tb)

    def __add__(self, other: Any) -> Any:
        return self._intercept_dunder("__add__", other)

    def __radd__(self, other: Any) -> Any:
        return self._intercept_dunder("__radd__", other)

    def __sub__(self, other: Any) -> Any:
        return self._intercept_dunder("__sub__", other)

    def __rsub__(self, other: Any) -> Any:
        return self._intercept_dunder("__rsub__", other)

    def __mul__(self, other: Any) -> Any:
        return self._intercept_dunder("__mul__", other)

    def __rmul__(self, other: Any) -> Any:
        return self._intercept_dunder("__rmul__", other)

    def __truediv__(self, other: Any) -> Any:
        return self._intercept_dunder("__truediv__", other)

    def __rtruediv__(self, other: Any) -> Any:
        return self._intercept_dunder("__rtruediv__", other)

    def __floordiv__(self, other: Any) -> Any:
        return self._intercept_dunder("__floordiv__", other)

    def __rfloordiv__(self, other: Any) -> Any:
        return self._intercept_dunder("__rfloordiv__", other)

    def __mod__(self, other: Any) -> Any:
        return self._intercept_dunder("__mod__", other)

    def __rmod__(self, other: Any) -> Any:
        return self._intercept_dunder("__rmod__", other)

    def __pow__(self, other: Any) -> Any:
        return self._intercept_dunder("__pow__", other)

    def __rpow__(self, other: Any) -> Any:
        return self._intercept_dunder("__rpow__", other)

    def __neg__(self) -> Any:
        return self._intercept_dunder("__neg__")

    def __pos__(self) -> Any:
        return self._intercept_dunder("__pos__")

    def __bool__(self) -> bool:
        return self._intercept_dunder("__bool__")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DebugProxy):
            return False
        return self._target == other._target

    def __hash__(self) -> int:
        return hash(self._target)

    def _wait_for_post_completion(self, action: dict[str, Any]) -> None:
        while action.get("action") == "poll":
            action = self._client.poll(action)
        action_type = action.get("action")
        if action_type not in (None, "continue"):
            raise DebugProtocolError(f"Unsupported post-completion action: {action_type}")

    async def _wait_for_post_completion_async(self, action: dict[str, Any]) -> None:
        while action.get("action") == "poll":
            action = await self._client.async_poll(action)
        action_type = action.get("action")
        if action_type not in (None, "continue"):
            raise DebugProtocolError(f"Unsupported post-completion action: {action_type}")


class AsyncDebugProxy(DebugProxy):
    """Alias for a debug proxy with async-compatible methods."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        attr = getattr(self._target, "__call__", None)
        if attr is not None and inspect.iscoroutinefunction(attr):
            return self._wrap_async_method(attr, "__call__")(*args, **kwargs)
        return self._intercept_dunder("__call__", *args, **kwargs)
