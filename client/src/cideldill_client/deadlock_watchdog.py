"""Deadlock watchdog utilities."""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _TrackedOperation:
    label: str
    started_at: float


class DeadlockWatchdog:
    """Log thread stack dumps when tracked operations stall."""

    def __init__(self, timeout_s: float, log_interval_s: float = 60.0) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        if log_interval_s <= 0:
            raise ValueError("log_interval_s must be > 0")
        self._timeout_s = float(timeout_s)
        self._log_interval_s = float(log_interval_s)
        self._lock = threading.Lock()
        self._operations: dict[int, _TrackedOperation] = {}
        self._next_operation_id = 0
        self._last_dump_at = 0.0
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="cideldill-deadlock-watchdog",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=0.5)

    def track_start(self, label: str) -> int:
        with self._lock:
            self._next_operation_id += 1
            operation_id = self._next_operation_id
            self._operations[operation_id] = _TrackedOperation(
                label=label,
                started_at=time.time(),
            )
            return operation_id

    def track_end(self, operation_id: int) -> None:
        with self._lock:
            self._operations.pop(operation_id, None)

    @contextmanager
    def track(self, label: str) -> Iterator[None]:
        operation_id = self.track_start(label)
        try:
            yield
        finally:
            self.track_end(operation_id)

    def _run(self) -> None:
        check_interval_s = min(1.0, max(0.1, self._timeout_s / 4.0))
        while not self._stop_event.wait(check_interval_s):
            stalled = self._get_stalled_snapshot()
            if stalled is None:
                continue
            oldest, operation_count, age_s = stalled
            now = time.time()
            if now - self._last_dump_at < self._log_interval_s:
                continue
            self._last_dump_at = now
            logger.warning(
                "Potential deadlock detected in cideldill client: operation=%s age=%.1fs "
                "active_operations=%s timeout=%.1fs\n%s",
                oldest.label,
                age_s,
                operation_count,
                self._timeout_s,
                self._collect_thread_dump(),
            )

    def _get_stalled_snapshot(self) -> tuple[_TrackedOperation, int, float] | None:
        now = time.time()
        with self._lock:
            if not self._operations:
                return None
            oldest = min(self._operations.values(), key=lambda op: op.started_at)
            age_s = max(0.0, now - oldest.started_at)
            if age_s < self._timeout_s:
                return None
            return oldest, len(self._operations), age_s

    def _collect_thread_dump(self) -> str:
        frames = sys._current_frames()
        threads_by_id = {thread.ident: thread for thread in threading.enumerate()}
        lines: list[str] = []
        watchdog_thread_id = self._thread.ident
        for thread_id in sorted(frames):
            if watchdog_thread_id is not None and thread_id == watchdog_thread_id:
                continue
            frame = frames[thread_id]
            thread = threads_by_id.get(thread_id)
            thread_name = thread.name if thread is not None else "<unknown>"
            daemon_flag = bool(getattr(thread, "daemon", False))
            lines.append(f"Thread {thread_name} (id={thread_id}, daemon={daemon_flag})")
            lines.extend(traceback.format_stack(frame))
            lines.append("")
        return "\n".join(lines).strip()
