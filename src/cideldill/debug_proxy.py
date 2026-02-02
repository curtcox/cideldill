"""Debug proxy implementations."""

from __future__ import annotations

import builtins
import inspect
import time
from typing import Any, Callable, Dict, Tuple

from .debug_client import DebugClient
from .exceptions import DebugProtocolError
from .serialization import compute_cid


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
            )

            call_id = action.get("call_id")
            if not call_id:
                raise DebugProtocolError("Missing call_id in response")

            try:
                result = self._execute_action(action, method, args, kwargs)
            except Exception as exc:  # noqa: BLE001 - re-raise after reporting
                self._client.record_call_complete(
                    call_id=call_id,
                    status="exception",
                    exception=exc,
                )
                raise

            self._client.record_call_complete(
                call_id=call_id,
                status="success",
                result=result,
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
            )

            call_id = action.get("call_id")
            if not call_id:
                raise DebugProtocolError("Missing call_id in response")

            try:
                result = await self._execute_action_async(action, method, args, kwargs)
            except Exception as exc:  # noqa: BLE001 - re-raise after reporting
                self._client.record_call_complete(
                    call_id=call_id,
                    status="exception",
                    exception=exc,
                )
                raise

            self._client.record_call_complete(
                call_id=call_id,
                status="success",
                result=result,
            )
            return result

        return wrapper

    def _execute_action(
        self,
        action: Dict[str, Any],
        method: Callable[..., Any],
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
    ) -> Any:
        if action.get("action") == "poll":
            action = self._client.poll(action)

        action_type = action.get("action")
        if action_type == "continue":
            return method(*args, **kwargs)
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
        action: Dict[str, Any],
        method: Callable[..., Any],
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
    ) -> Any:
        if action.get("action") == "poll":
            action = await self._client.async_poll(action)

        action_type = action.get("action")
        if action_type == "continue":
            return await method(*args, **kwargs)
        if action_type == "modify":
            new_args, new_kwargs = self._deserialize_modified(action)
            return await method(*new_args, **new_kwargs)
        if action_type == "skip":
            return self._deserialize_fake_result(action)
        if action_type == "raise":
            raise self._deserialize_exception(action)
        raise DebugProtocolError(f"Unknown action: {action_type}")

    def _deserialize_modified(self, action: Dict[str, Any]) -> Tuple[Tuple[Any, ...], Dict[str, Any]]:
        modified_args = action.get("modified_args", [])
        modified_kwargs = action.get("modified_kwargs", {})
        args = tuple(self._client.deserialize_payload_list(modified_args))
        kwargs = self._client.deserialize_payload_dict(modified_kwargs)
        return args, kwargs

    def _deserialize_fake_result(self, action: Dict[str, Any]) -> Any:
        if "fake_result_data" in action:
            return self._client.deserialize_payload_item({"data": action["fake_result_data"]})
        if "fake_result" in action:
            return action["fake_result"]
        if "fake_result_cid" in action:
            return self._client.deserialize_payload_item({"cid": action["fake_result_cid"]})
        return None

    def _deserialize_exception(self, action: Dict[str, Any]) -> Exception:
        exc_type = action.get("exception_type", "Exception")
        message = action.get("exception_message", "")
        exc_class = getattr(builtins, exc_type, Exception)
        return exc_class(message)

    def _intercept_dunder(self, name: str, *args: Any) -> Any:
        attr = getattr(self._target, name)
        if callable(attr):
            if self._is_enabled():
                return self._wrap_method(attr, name)(*args)
            return attr(*args)
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


class AsyncDebugProxy(DebugProxy):
    """Alias for a debug proxy with async-compatible methods."""
