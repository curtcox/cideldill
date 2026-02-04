"""Helpers for fatal breakpoint server failures."""

from __future__ import annotations

import sys
from typing import NoReturn


def exit_with_server_failure(
    summary: str,
    server_url: str | None,
    error: BaseException | None = None,
) -> NoReturn:
    """Print a detailed failure report and exit immediately."""
    lines = [
        "CID el Dill: Failed to contact breakpoint server.",
        "",
        "Details:",
        f"- Summary: {summary}",
    ]
    if server_url:
        lines.append(f"- Server URL: {server_url}")
    if error is not None:
        lines.append(f"- Exception: {type(error).__name__}: {error}")

    lines.extend(
        [
            "",
            "Most likely causes:",
            "1. The breakpoint server is not running.",
            "2. The server is running on a different port or URL.",
            "3. The server is not reachable from this environment (container/remote).",
            "",
            "Potential fixes:",
            "1. Start the breakpoint server and retry.",
            "2. Set CIDELDILL_SERVER_URL to the correct URL.",
            "3. Ensure the port is exposed and firewall rules allow access.",
            "",
            "Exiting now.",
        ]
    )

    print("\n".join(lines), file=sys.stderr)
    sys.stderr.flush()
    raise SystemExit(1)
