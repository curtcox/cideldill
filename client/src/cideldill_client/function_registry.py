"""Function registry for breakpoint replacement."""

from __future__ import annotations

import inspect
import threading
from collections.abc import Callable


_lock = threading.Lock()
_functions: dict[str, Callable[..., object]] = {}
_signatures: dict[str, str] = {}


def compute_signature(func: Callable[..., object]) -> str:
    try:
        return str(inspect.signature(func))
    except Exception:  # noqa: BLE001 - signature can fail for many callables
        return ""


def register_function(
    func: Callable[..., object],
    name: str | None = None,
    signature: str | None = None,
) -> None:
    function_name = name or getattr(func, "__name__", None)
    if not function_name:
        return
    resolved_signature = signature if signature is not None else compute_signature(func)
    with _lock:
        _functions[function_name] = func
        if resolved_signature:
            _signatures[function_name] = resolved_signature
        else:
            _signatures.pop(function_name, None)


def get_function(name: str) -> Callable[..., object] | None:
    with _lock:
        return _functions.get(name)


def get_signature(name: str) -> str | None:
    with _lock:
        return _signatures.get(name)


def clear_registry() -> None:
    with _lock:
        _functions.clear()
        _signatures.clear()
