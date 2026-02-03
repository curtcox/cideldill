#!/usr/bin/env python3
"""Launch the breakpoint web server.

This script starts the Flask web server for interactive breakpoint management.
"""

import argparse
import sys

from .breakpoint_manager import BreakpointManager
from .breakpoint_server import BreakpointServer


def main():
    """Main entry point."""
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

    args = parser.parse_args()

    print("=" * 60)
    print("CID el Dill - Interactive Breakpoint Server")
    print("=" * 60)
    print(f"\nStarting server on {args.host}:{args.port}...")
    print("\nNote: If port is occupied, a free port will be auto-selected.")
    print("      Port will be written to: ~/.cideldill/port")
    print("\nWeb UI available at:")
    print("  Check server output for the actual port.")
    print("\nAPI Endpoints:")
    print("  GET    /api/breakpoints           - List breakpoints")
    print("  POST   /api/breakpoints           - Add breakpoint")
    print("  DELETE /api/breakpoints/<name>    - Remove breakpoint")
    print("  POST   /api/call/start            - Start a debug call")
    print("  GET    /api/poll/<id>             - Poll for resume action")
    print("  POST   /api/call/complete         - Complete a debug call")
    print("  GET    /api/paused                - List paused executions")
    print("  POST   /api/paused/<id>/continue  - Continue execution")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 60)

    try:
        manager = BreakpointManager()
        server = BreakpointServer(manager, port=args.port, host=args.host)
        print("\n✓ Server is starting...\n")
        server.start()
    except KeyboardInterrupt:
        print("\n\n✓ Server stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Error starting server: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
