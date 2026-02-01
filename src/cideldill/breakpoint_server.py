"""Web server for interactive breakpoint management.

This module provides a Flask-based web server with REST API endpoints
for managing breakpoints and paused executions through a web UI.
"""

import logging

from flask import Flask, jsonify, request

from cideldill.breakpoint_manager import BreakpointManager

# Disable Flask's default logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)


class BreakpointServer:
    """Web server for breakpoint management.

    Provides REST API endpoints for:
    - Managing breakpoints (add, remove, list)
    - Viewing paused executions
    - Continuing/modifying paused executions

    Attributes:
        manager: The BreakpointManager instance.
        port: Port number for the server.
        app: Flask application instance.
    """

    def __init__(self, manager: BreakpointManager, port: int = 5000) -> None:
        """Initialize the server.

        Args:
            manager: BreakpointManager instance to use.
            port: Port number to listen on (0 for random available port).
        """
        self.manager = manager
        self.port = port
        self.app = Flask(__name__)
        self._running = False
        self._server = None
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Set up Flask routes."""

        @self.app.route('/api/breakpoints', methods=['GET'])
        def get_breakpoints():
            """Get list of all breakpoints."""
            return jsonify({
                "breakpoints": self.manager.get_breakpoints()
            })

        @self.app.route('/api/breakpoints', methods=['POST'])
        def add_breakpoint():
            """Add a new breakpoint."""
            data = request.get_json()
            function_name = data.get('function_name')
            if not function_name:
                return jsonify({"error": "function_name required"}), 400

            self.manager.add_breakpoint(function_name)
            return jsonify({"status": "ok", "function_name": function_name})

        @self.app.route('/api/breakpoints/<function_name>', methods=['DELETE'])
        def remove_breakpoint(function_name):
            """Remove a breakpoint."""
            self.manager.remove_breakpoint(function_name)
            return jsonify({"status": "ok", "function_name": function_name})

        @self.app.route('/api/paused', methods=['GET'])
        def get_paused():
            """Get all paused executions."""
            return jsonify({
                "paused": self.manager.get_paused_executions()
            })

        @self.app.route('/api/paused/<pause_id>/continue', methods=['POST'])
        def continue_execution(pause_id):
            """Continue a paused execution."""
            data = request.get_json()
            action = data.get('action', 'continue')

            action_dict = {"action": action}

            # Include additional fields if present
            if 'modified_args' in data:
                action_dict['modified_args'] = data['modified_args']
            if 'fake_result' in data:
                action_dict['fake_result'] = data['fake_result']
            if 'exception' in data:
                action_dict['exception'] = data['exception']

            self.manager.resume_execution(pause_id, action_dict)
            return jsonify({"status": "ok", "pause_id": pause_id})

    def start(self) -> None:
        """Start the server (blocking)."""
        self._running = True
        # Use threaded=True for better concurrency
        self.app.run(host='0.0.0.0', port=self.port, threaded=True, use_reloader=False)

    def stop(self) -> None:
        """Stop the server."""
        self._running = False
        # Flask doesn't have a clean shutdown method, so we just set the flag
        # In production, you'd use a proper WSGI server with shutdown support

    def is_running(self) -> bool:
        """Check if server is running.

        Returns:
            True if running, False otherwise.
        """
        return self._running

    def test_client(self):
        """Get a test client for testing.

        Returns:
            Flask test client.
        """
        return self.app.test_client()

    def get_port(self) -> int:
        """Get the actual port number the server is using.

        Returns:
            Port number.
        """
        return self.port
