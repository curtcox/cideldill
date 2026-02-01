#!/usr/bin/env python3
"""Launch the breakpoint web server.

This script starts the Flask web server for interactive breakpoint management.
"""

import argparse
import sys

from cideldill import BreakpointManager
from cideldill.breakpoint_server import BreakpointServer


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Start the CID el Dill breakpoint web server"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port to listen on (default: 5000)"
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
    print(f"\nStarting server on {args.host}:{args.port}")
    print("\nWeb UI available at:")
    print(f"  http://localhost:{args.port}/")
    print("\nAPI Endpoints:")
    print("  GET    /api/breakpoints        - List breakpoints")
    print("  POST   /api/breakpoints        - Add breakpoint")
    print("  DELETE /api/breakpoints/<name> - Remove breakpoint")
    print("  GET    /api/paused             - List paused executions")
    print("  POST   /api/paused/<id>/continue - Continue execution")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 60)
    print()

    try:
        manager = BreakpointManager()
        server = BreakpointServer(manager, port=args.port)
        server.start()
    except KeyboardInterrupt:
        print("\n\nShutting down server...")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
