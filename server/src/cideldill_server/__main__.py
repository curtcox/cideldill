#!/usr/bin/env python3
"""Launch the breakpoint web server.

This script starts the Flask web server for interactive breakpoint management.
"""

import argparse
import asyncio
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

from .breakpoint_manager import BreakpointManager
from .breakpoint_server import BreakpointServer


def parse_args():
    parser = argparse.ArgumentParser(
        description="Start the CID el Dill breakpoint web server"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5174,
        help="Port to listen on (default: 5174)"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)"
    )

    db_group = parser.add_mutually_exclusive_group()
    db_group.add_argument(
        "--db",
        default=None,
        help=(
            "SQLite database file for payload storage. Defaults to an auto-created "
            "disk DB under .cideldill/breakpoint_dbs. Use ':memory:' for in-memory."
        ),
    )
    db_group.add_argument(
        "--memory",
        action="store_true",
        help="Use an in-memory SQLite database (equivalent to --db :memory:).",
    )

    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Enable MCP stdio transport alongside the HTTP server.",
    )
    parser.add_argument(
        "--mcp-sse",
        action="store_true",
        help="Enable MCP SSE transport at /mcp/sse.",
    )

    return parser.parse_args()


def resolve_db_path(args) -> str:
    if args.memory:
        return ":memory:"
    if args.db:
        if args.db == ":memory:":
            return ":memory:"
        db_path = Path(args.db).expanduser()
        if not db_path.is_absolute():
            db_path = (Path.cwd() / db_path).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return str(db_path)

    db_dir = Path.cwd() / ".cideldill" / "breakpoint_dbs"
    db_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    db_path = db_dir / f"breakpoints-{timestamp}.sqlite3"
    return str(db_path)

def _print_banner(args, db_path: str, *, out) -> None:
    print("=" * 60, file=out)
    print("CID el Dill - Interactive Breakpoint Server", file=out)
    print("=" * 60, file=out)
    print(f"\nStarting server on {args.host}:{args.port}...", file=out)
    print("\nNote: If port is occupied, a free port will be auto-selected.", file=out)
    print("      Port will be written to: ~/.cideldill/port", file=out)
    print("\nWeb UI available at:", file=out)
    print("  Check server output for the actual port.", file=out)
    print("\nAPI Endpoints:", file=out)
    print("  GET    /api/breakpoints           - List breakpoints", file=out)
    print("  POST   /api/breakpoints           - Add breakpoint", file=out)
    print("  DELETE /api/breakpoints/<name>    - Remove breakpoint", file=out)
    print("  POST   /api/call/start            - Start a debug call", file=out)
    print("  GET    /api/poll/<id>             - Poll for resume action", file=out)
    print("  POST   /api/call/complete         - Complete a debug call", file=out)
    print("  GET    /api/paused                - List paused executions", file=out)
    print("  POST   /api/paused/<id>/continue  - Continue execution", file=out)
    print(f"\nDatabase: {db_path}", file=out)
    print("\nPress Ctrl+C to stop the server", file=out)
    print("=" * 60, file=out)


def _configure_mcp_logging() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    logging.getLogger("werkzeug").setLevel(logging.INFO)


def main():
    """Main entry point."""
    args = parse_args()
    db_path = resolve_db_path(args)

    use_mcp = bool(args.mcp or args.mcp_sse)
    if args.mcp:
        _configure_mcp_logging()
    out = sys.stderr if args.mcp else sys.stdout
    _print_banner(args, db_path, out=out)

    try:
        manager = BreakpointManager()
        server = BreakpointServer(
            manager,
            port=args.port,
            host=args.host,
            db_path=db_path,
            log_stream=out,
        )

        if use_mcp:
            try:
                from .mcp_server import BreakpointMCPServer
            except Exception as exc:  # pragma: no cover - mcp optional
                print(f"✗ MCP not available: {exc}", file=sys.stderr)
                sys.exit(1)

            mcp_server = BreakpointMCPServer(
                manager,
                server.cid_store,
                repl_backend=server,
            )
            if args.mcp_sse:
                try:
                    server.mount_mcp_sse(mcp_server)
                except Exception as exc:  # pragma: no cover - optional transport
                    print(f"✗ Failed to mount MCP SSE: {exc}", file=sys.stderr)
                    sys.exit(1)

            if args.mcp:
                flask_thread = threading.Thread(target=server.start, daemon=False)
                flask_thread.start()
                asyncio.run(mcp_server.run_stdio())
                flask_thread.join()
                return

        print("\n✓ Server is starting...\n", file=out)
        server.start()
    except KeyboardInterrupt:
        print("\n\n✓ Server stopped by user", file=out)
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Error starting server: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
