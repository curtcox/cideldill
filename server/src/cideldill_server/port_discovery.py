"""Port discovery utilities for avoiding port conflicts."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Optional


def find_free_port() -> int:
    """Find an available port by asking the OS.

    Returns:
        An available port number.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
    return port


def get_discovery_file_path() -> Path:
    """Get the path to the port discovery file.

    Returns:
        Path to ~/.cideldill/port
    """
    return Path.home() / ".cideldill" / "port"


def write_port_file(port: int, port_file: Optional[Path] = None) -> None:
    """Write the server port to the discovery file.

    Args:
        port: The port number to write.
        port_file: Optional custom path (default: ~/.cideldill/port).
    """
    if port_file is None:
        port_file = get_discovery_file_path()

    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text(str(port))


def read_port_file(port_file: Optional[Path] = None) -> Optional[int]:
    """Read the server port from the discovery file.

    Args:
        port_file: Optional custom path (default: ~/.cideldill/port).

    Returns:
        The port number, or None if file doesn't exist or is invalid.
    """
    if port_file is None:
        port_file = get_discovery_file_path()

    if not port_file.exists():
        return None

    try:
        port = int(port_file.read_text().strip())
    except (ValueError, OSError):
        return None

    if not (1 <= port <= 65535):
        return None

    return port
