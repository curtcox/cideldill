"""Web server for interactive breakpoint management.

This module provides a Flask-based web server with REST API endpoints
for managing breakpoints and paused executions through a web UI.
"""

import logging

from flask import Flask, jsonify, request, render_template_string

from cideldill.breakpoint_manager import BreakpointManager

# Configure Flask's logging to show startup info but not request spam
log = logging.getLogger('werkzeug')
log.setLevel(logging.INFO)


# HTML template for the web UI
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CID el Dill - Interactive Breakpoints</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        h1 {
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }
        h2 {
            color: #555;
            margin-top: 30px;
        }
        .info-box {
            background-color: #e3f2fd;
            border-left: 4px solid #2196F3;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 4px;
        }
        .status-message {
            padding: 10px;
            border-radius: 4px;
            margin-bottom: 15px;
            display: none;
        }
        .status-success {
            background-color: #d4edda;
            border: 1px solid #c3e6cb;
            color: #155724;
        }
        .status-error {
            background-color: #f8d7da;
            border: 1px solid #f5c6cb;
            color: #721c24;
        }
        .paused-card {
            background-color: #fff3cd;
            border: 2px solid #ff9800;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .paused-header {
            font-size: 1.1em;
            font-weight: bold;
            color: #f57c00;
            margin-bottom: 10px;
        }
        .call-data {
            background-color: #f8f8f8;
            padding: 10px;
            border-radius: 4px;
            margin: 10px 0;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            white-space: pre-wrap;
        }
        .actions {
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.9em;
            transition: all 0.2s;
        }
        .btn-continue {
            background-color: #2196F3;
            color: white;
        }
        .btn-continue:hover {
            background-color: #0b7dda;
        }
        .btn-skip {
            background-color: #ff9800;
            color: white;
        }
        .btn-skip:hover {
            background-color: #e68900;
        }
        .breakpoint-list {
            background-color: white;
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .breakpoint-item {
            padding: 10px;
            margin: 5px 0;
            background-color: #f8f8f8;
            border-left: 4px solid #f44336;
            border-radius: 4px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .btn-remove {
            background-color: #f44336;
            color: white;
            padding: 5px 12px;
            font-size: 0.85em;
        }
        .btn-remove:hover {
            background-color: #da190b;
        }
        .empty-state {
            color: #666;
            font-style: italic;
            padding: 20px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔴 Interactive Breakpoints</h1>

        <div id="statusMessage" class="status-message"></div>

        <div class="info-box">
            <strong>Welcome to the CID el Dill Breakpoint Manager!</strong>
            <p>This is the live breakpoint management interface. Use this to:</p>
            <ul>
                <li>View currently active breakpoints</li>
                <li>See paused executions in real-time</li>
                <li>Control execution flow (continue, skip)</li>
            </ul>
            <p><strong>Note:</strong> To set breakpoints on functions, use the Interceptor API in your Python code or generate a full HTML report with the breakpoints page.</p>
        </div>

        <h2>⏸️ Paused Executions</h2>
        <div id="pausedExecutions">
            <div class="empty-state">No executions currently paused.</div>
        </div>

        <h2>🔴 Active Breakpoints</h2>
        <div id="breakpointsList">
            <div class="empty-state">No breakpoints set.</div>
        </div>
    </div>

    <script>
        const API_BASE = '/api';
        let updateInterval = null;

        // Load active breakpoints
        async function loadBreakpoints() {
            try {
                const response = await fetch(`${API_BASE}/breakpoints`);
                const data = await response.json();
                
                const container = document.getElementById('breakpointsList');
                if (data.breakpoints && data.breakpoints.length > 0) {
                    container.innerHTML = '<div class="breakpoint-list">' + 
                        data.breakpoints.map(bp => `
                            <div class="breakpoint-item">
                                <span><strong>${bp}</strong>()</span>
                            </div>
                        `).join('') + '</div>';
                } else {
                    container.innerHTML = '<div class="empty-state">No breakpoints set.</div>';
                }
            } catch (e) {
                console.error('Failed to load breakpoints:', e);
            }
        }

        // Load paused executions
        async function loadPausedExecutions() {
            try {
                const response = await fetch(`${API_BASE}/paused`);
                const data = await response.json();
                
                const container = document.getElementById('pausedExecutions');
                if (data.paused && data.paused.length > 0) {
                    container.innerHTML = data.paused.map(p => createPausedCard(p)).join('');
                } else {
                    container.innerHTML = '<div class="empty-state">No executions currently paused.</div>';
                }
            } catch (e) {
                console.error('Failed to load paused executions:', e);
            }
        }

        // Create HTML for a paused execution
        function createPausedCard(paused) {
            const callData = paused.call_data;
            const pausedAt = new Date(paused.paused_at * 1000).toLocaleTimeString();
            
            return `
                <div class="paused-card">
                    <div class="paused-header">
                        ⏸️ ${callData.function_name}() - Paused at ${pausedAt}
                    </div>
                    <div class="call-data"><strong>Arguments:</strong>
${JSON.stringify(callData.args, null, 2)}</div>
                    <div class="actions">
                        <button class="btn btn-continue" onclick="continueExecution('${paused.id}', 'continue')">
                            ▶️ Continue
                        </button>
                        <button class="btn btn-skip" onclick="continueExecution('${paused.id}', 'skip')">
                            ⏭️ Skip
                        </button>
                    </div>
                </div>
            `;
        }

        // Continue execution
        async function continueExecution(pauseId, action) {
            try {
                const response = await fetch(`${API_BASE}/paused/${pauseId}/continue`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: action })
                });
                
                if (response.ok) {
                    showMessage('Execution resumed', 'success');
                    loadPausedExecutions();
                }
            } catch (e) {
                showMessage('Failed to continue execution: ' + e.message, 'error');
            }
        }

        // Show status message
        function showMessage(message, type) {
            const msgEl = document.getElementById('statusMessage');
            msgEl.textContent = message;
            msgEl.className = `status-message status-${type}`;
            msgEl.style.display = 'block';
            setTimeout(() => {
                msgEl.style.display = 'none';
            }, 3000);
        }

        // Start polling for updates
        function startPolling() {
            loadBreakpoints();
            loadPausedExecutions();
            updateInterval = setInterval(() => {
                loadBreakpoints();
                loadPausedExecutions();
            }, 1000);  // Poll every second
        }

        // Initialize on page load
        window.addEventListener('load', () => {
            startPolling();
        });

        // Clean up on page unload
        window.addEventListener('beforeunload', () => {
            if (updateInterval) {
                clearInterval(updateInterval);
            }
        });
    </script>
</body>
</html>
"""


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

        @self.app.route('/')
        def index():
            """Serve the main web UI."""
            return render_template_string(HTML_TEMPLATE)

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
