"""Web server for interactive breakpoint management.

This module provides a Flask-based web server with REST API endpoints
for managing breakpoints and paused executions through a web UI.
"""

import base64
import html
import logging
import os
import threading
import time

from flask import Flask, jsonify, render_template_string, request
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

from cideldill.breakpoint_manager import BreakpointManager
from cideldill.cid_store import CIDStore
from cideldill.serialization import deserialize

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
        .btn-go {
            background-color: #2E7D32;
            color: white;
        }
        .btn-go:hover {
            background-color: #1B5E20;
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
            border-left: 4px solid transparent;
            border-radius: 4px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .breakpoint-item.stop {
            border-left-color: #f44336;
        }
        .breakpoint-item.go {
            border-left-color: #2E7D32;
        }
        .breakpoint-item.yield {
            border-left-color: #fbc02d;
        }
        .state-toggle {
            display: flex;
            gap: 8px;
            align-items: center;
        }
        .state-btn {
            border: 2px solid transparent;
            background: white;
            cursor: pointer;
            padding: 6px 10px;
            border-radius: 999px;
            font-size: 16px;
            line-height: 1;
        }
        .state-btn.selected {
            border-color: #333;
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
        <h1>🛑 Interactive Breakpoints</h1>

        <div id="statusMessage" class="status-message"></div>

        <h2>⏸️ Paused Executions</h2>
        <div id="pausedExecutions">
            <div class="empty-state">No executions currently paused.</div>
        </div>

        <h2>🔴 Active Breakpoints</h2>
        <div class="breakpoint-list">
            <div style="margin-bottom: 20px; padding: 15px; background-color: #fff3cd;
                        border: 1px solid #ffc107; border-radius: 8px;">
                <div style="margin-bottom: 10px;">
                    <strong>Default Breakpoint Behavior:</strong>
                </div>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <label style="display: flex; align-items: center; cursor: pointer;">
                        <input type="radio" name="behavior" value="stop"
                               id="behavior-stop" checked
                               onchange="setBehavior('stop')"
                               style="margin-right: 5px; cursor: pointer;">
                        <span>🛑 Stop at breakpoints</span>
                    </label>
                    <label style="display: flex; align-items: center; cursor: pointer;">
                        <input type="radio" name="behavior" value="go"
                               id="behavior-go"
                               onchange="setBehavior('go')"
                               style="margin-right: 5px; cursor: pointer;">
                        <span>🟢 Go (log only)</span>
                    </label>
                </div>
                <div style="margin-top: 10px; font-size: 0.9em; color: #856404;">
                    When "Stop" is selected, execution pauses at breakpoints.
                    When "Go" is selected, breakpoints are logged but don't pause.
                </div>
            </div>
        </div>
        <div id="breakpointsList">
            <div class="empty-state">No breakpoints set.</div>
        </div>
    </div>

    <script>
        const API_BASE = '/api';
        let updateInterval = null;

        // Set breakpoint behavior
        async function setBehavior(behavior) {
            try {
                const response = await fetch(`${API_BASE}/behavior`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ behavior: behavior })
                });

                if (response.ok) {
                    const icon = behavior === 'stop' ? '🛑' : '🟢';
                    const action = behavior === 'stop' ? 'stop at' : 'go through';
                    showMessage(`${icon} Will ${action} breakpoints`, 'success');
                } else {
                    showMessage('Failed to set behavior', 'error');
                }
            } catch (e) {
                console.error('Failed to set behavior:', e);
                showMessage('Error setting behavior', 'error');
            }
        }

        // Load current behavior setting
        async function loadBehavior() {
            try {
                const response = await fetch(`${API_BASE}/behavior`);
                const data = await response.json();

                const behavior = data.behavior || 'stop';
                document.getElementById(`behavior-${behavior}`).checked = true;
            } catch (e) {
                console.error('Failed to load behavior:', e);
            }
        }

        async function setBreakpointBehavior(functionName, behavior) {
            try {
                const encoded = encodeURIComponent(functionName);
                const response = await fetch(`${API_BASE}/breakpoints/${encoded}/behavior`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ behavior: behavior })
                });

                if (response.ok) {
                    const icon = behavior === 'stop' ? '🛑' : (behavior === 'yield' ? '⚠️' : '🟢');
                    showMessage(`${icon} Set breakpoint behavior: ${functionName}`, 'success');
                    loadBreakpoints();
                } else {
                    showMessage('Failed to set breakpoint behavior', 'error');
                }
            } catch (e) {
                console.error('Failed to set breakpoint behavior:', e);
                showMessage('Error setting breakpoint behavior', 'error');
            }
        }

        // Show a status message
        function showMessage(message, type) {
            const msgDiv = document.getElementById('statusMessage');
            msgDiv.textContent = message;
            msgDiv.style.display = 'block';
            const successColor = type === 'success';
            msgDiv.style.backgroundColor = successColor ? '#d4edda' : '#f8d7da';
            msgDiv.style.color = successColor ? '#155724' : '#721c24';
            msgDiv.style.border = `1px solid ${successColor ? '#c3e6cb' : '#f5c6cb'}`;
            msgDiv.style.padding = '10px';
            msgDiv.style.borderRadius = '4px';
            msgDiv.style.marginBottom = '20px';

            setTimeout(() => {
                msgDiv.style.display = 'none';
            }, 3000);
        }

        // Load active breakpoints
        async function loadBreakpoints() {
            try {
                const response = await fetch(`${API_BASE}/breakpoints`);
                const data = await response.json();

                const container = document.getElementById('breakpointsList');
                if (data.breakpoints && data.breakpoints.length > 0) {
                    const states = data.breakpoint_behaviors || {};
                    container.innerHTML = '<div class="breakpoint-list">' +
                        data.breakpoints.map(bp => `
                            <div class="breakpoint-item ${states[bp] === 'go' ? 'go' : (states[bp] === 'yield' ? 'yield' : 'stop')}">
                                <span><strong>${bp}</strong>()</span>
                                <div class="state-toggle">
                                    <button class="state-btn ${states[bp] === 'stop' ? 'selected' : ''}"
                                            onclick="setBreakpointBehavior('${bp}', 'stop')"
                                            title="Stop (pause)">
                                        🛑
                                    </button>
                                    <button class="state-btn ${states[bp] === 'yield' ? 'selected' : ''}"
                                            onclick="setBreakpointBehavior('${bp}', 'yield')"
                                            title="Yield (inherit global default)">
                                        ⚠️
                                    </button>
                                    <button class="state-btn ${states[bp] === 'go' ? 'selected' : ''}"
                                            onclick="setBreakpointBehavior('${bp}', 'go')"
                                            title="Go (don't pause)">
                                        🟢
                                    </button>
                                </div>
                            </div>
                        `).join('') + '</div>';
                } else {
                    container.innerHTML = '<div class="empty-state">' +
                        'No breakpoints set.</div>';
                }
            } catch (e) {
                console.error('Failed to load breakpoints:', e);
            }
        }

        document.addEventListener('DOMContentLoaded', function() {
            // Load initial state
            loadBehavior();
            loadBreakpoints();
            loadPausedExecutions();

            updateInterval = setInterval(() => {
                loadPausedExecutions();
                loadBreakpoints();
            }, 1000);
        });

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
            const displayName = callData.method_name || callData.function_name || 'unknown';
            const pausedAt = new Date(paused.paused_at * 1000).toLocaleTimeString();

            const prettyArgs = callData.pretty_args || [];
            const prettyKwargs = callData.pretty_kwargs || {};
            const stackTrace = (callData.call_site && callData.call_site.stack_trace) ? callData.call_site.stack_trace : [];

            const renderArgs = () => {
                const argsBlock = JSON.stringify({ args: prettyArgs, kwargs: prettyKwargs }, null, 2);
                return `<div class="call-data"><strong>Parameters:</strong>
${argsBlock}</div>`;
            };

            const renderStack = () => {
                if (!stackTrace || stackTrace.length === 0) {
                    return '';
                }

                const items = stackTrace.map((f, idx) => {
                    const file = f.filename || '';
                    const lineno = f.lineno || '';
                    const func = f.function || '';
                    const ctx = f.code_context || '';
                    const url = `/frame/${encodeURIComponent(paused.id)}/${encodeURIComponent(idx)}`;
                    const label = `${func} (${file}:${lineno})`;
                    const ctxHtml = ctx ? `<div style="margin-top: 4px; color: #444;"><code>${ctx}</code></div>` : '';
                    return `<li style="margin: 8px 0;">
  <a href="${url}" target="_blank" rel="noopener noreferrer" style="color: #1565c0; text-decoration: none;">${label}</a>
  ${ctxHtml}
  <div style="margin-top: 2px; font-size: 0.85em; color: #666;">Frame ${idx}</div>
</li>`;
                }).join('');

                return `<div class="call-data"><strong>Stack Trace:</strong>
<ol style="margin: 8px 0 0 18px; padding: 0;">${items}</ol>
</div>`;
            };

            return `
                <div class="paused-card">
                    <div class="paused-header">
                        ⏸️ ${displayName}() - Paused at ${pausedAt}
                    </div>
                    ${renderArgs()}
                    ${renderStack()}
                    <div class="actions">
                        <button class="btn btn-go" onclick="continueExecution('${paused.id}')">
                            🟢
                        </button>
                    </div>
                </div>
            `;
        }

        // Continue execution
        async function continueExecution(pauseId) {
            try {
                const response = await fetch(`${API_BASE}/paused/${pauseId}/continue`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'continue' })
                });

                if (response.ok) {
                    showMessage('Execution resumed', 'success');
                    loadPausedExecutions();
                }
            } catch (e) {
                showMessage('Failed to continue execution: ' + e.message, 'error');
            }
        }

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
        self._cid_store = CIDStore()
        self._call_seq = 0
        self._call_seq_lock = threading.Lock()
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Set up Flask routes."""

        def next_call_id() -> str:
            with self._call_seq_lock:
                self._call_seq += 1
                seq = self._call_seq
            timestamp = f"{time.time():.6f}"
            return f"{timestamp}-{seq:03d}"

        def collect_missing_cids(items) -> list[str]:
            missing: list[str] = []
            iterable = items.values() if isinstance(items, dict) else items
            for item in iterable:
                if "cid" not in item:
                    continue
                if "data" not in item and not self._cid_store.exists(item["cid"]):
                    missing.append(item["cid"])
            return missing

        def store_payload(items) -> None:
            iterable = items.values() if isinstance(items, dict) else items
            for item in iterable:
                if "cid" not in item or "data" not in item:
                    continue
                data = base64.b64decode(item["data"])
                self._cid_store.store(item["cid"], data)

        def _safe_repr(obj: object, limit: int = 500) -> str:
            try:
                text = repr(obj)
            except Exception as exc:  # noqa: BLE001
                text = f"<unreprable: {type(exc).__name__}>"
            if len(text) > limit:
                return text[:limit] + "..."
            return text

        def _format_payload_value(item: dict[str, object]) -> str:
            cid = item.get("cid")
            if not isinstance(cid, str):
                return "<missing cid>"
            try:
                stored = self._cid_store.get(cid)
            except Exception:
                stored = None
            if stored is None:
                return f"<cid:{cid} missing>"
            try:
                value = deserialize(stored)
            except Exception as exc:  # noqa: BLE001
                return f"<unavailable: {type(exc).__name__}>"
            return _safe_repr(value)

        @self.app.route('/')
        def index():
            """Serve the main web UI."""
            return render_template_string(HTML_TEMPLATE)

        @self.app.route('/frame/<pause_id>/<int:frame_index>', methods=['GET'])
        def frame_view(pause_id: str, frame_index: int):
            paused = self.manager.get_paused_execution(pause_id)
            if not paused:
                return jsonify({"error": "pause_not_found"}), 404

            call_data = paused.get("call_data", {})
            call_site = call_data.get("call_site") or {}
            stack_trace = call_site.get("stack_trace") or []
            if frame_index < 0 or frame_index >= len(stack_trace):
                return jsonify({"error": "frame_not_found"}), 404

            frame = stack_trace[frame_index]
            file_path = frame.get("filename") or ""
            line_no = frame.get("lineno") or 0
            try:
                line_no = int(line_no) if line_no else 0
            except ValueError:
                line_no = 0

            if not file_path:
                return jsonify({"error": "file_not_available"}), 404
            if not os.path.isfile(file_path):
                return jsonify({"error": "file_not_found"}), 404

            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                source = f.read()

            title = (
                f"{os.path.basename(file_path)}:{line_no}"
                if line_no
                else os.path.basename(file_path)
            )

            lexer = get_lexer_by_name("python", stripall=True)
            formatter = HtmlFormatter(
                linenos=True,
                cssclass="source",
                style="default",
                hl_lines=[line_no] if line_no else [],
                linenostart=1,
            )
            highlighted = highlight(source, lexer, formatter)
            css_styles = formatter.get_style_defs(".source")

            page = """<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='UTF-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1.0'>
  <title>{title}</title>
  <style>
    body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 16px; background: #f5f5f5; }}
    .header {{ margin-bottom: 12px; }}
    .file {{ font-weight: 600; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; }}
    .container {{ background: white; border: 1px solid #ddd; border-radius: 8px; padding: 12px; overflow-x: auto; }}
    .source {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; font-size: 0.95em; }}
    .source .hll {{ background-color: #fff3cd; display: block; }}
    .source pre {{ margin: 0; }}
    .source table {{ width: 100%; border-spacing: 0; }}
    .source td.linenos {{ user-select: none; color: #666; padding-right: 12px; }}
    .source td.code {{ width: 100%; }}
    {css_styles}
  </style>
</head>
<body>
  <div class='header'>
    <div class='file'>{file_path}</div>
  </div>
  <div class='container'>
    {body}
  </div>
</body>
</html>""".format(
                title=html.escape(title),
                file_path=html.escape(file_path),
                css_styles=css_styles,
                body=highlighted,
            )

            return page

        @self.app.route('/api/breakpoints', methods=['GET'])
        def get_breakpoints():
            """Get list of all breakpoints."""
            return jsonify({
                "breakpoints": self.manager.get_breakpoints(),
                "breakpoint_behaviors": self.manager.get_breakpoint_behaviors(),
            })

        @self.app.route('/api/functions', methods=['GET'])
        def get_functions():
            return jsonify({
                "functions": self.manager.get_registered_functions(),
            })

        @self.app.route('/api/functions', methods=['POST'])
        def register_function():
            data = request.get_json() or {}
            function_name = data.get('function_name')
            if not function_name:
                return jsonify({"error": "function_name required"}), 400
            self.manager.register_function(function_name)
            return jsonify({"status": "ok", "function_name": function_name})

        @self.app.route('/api/breakpoints', methods=['POST'])
        def add_breakpoint():
            """Add a new breakpoint."""
            data = request.get_json() or {}
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

        @self.app.route('/api/breakpoints/<function_name>/behavior', methods=['POST'])
        def set_breakpoint_behavior(function_name):
            """Set behavior for a single breakpoint."""
            data = request.get_json() or {}
            behavior = data.get('behavior')
            if behavior == 'continue':
                behavior = 'go'
            if behavior not in {'stop', 'go', 'yield'}:
                return jsonify({"error": "behavior must be 'stop', 'go', or 'yield'"}), 400
            try:
                self.manager.set_breakpoint_behavior(function_name, behavior)
            except KeyError:
                return jsonify({"error": "breakpoint_not_found"}), 404
            return jsonify({"status": "ok", "function_name": function_name, "behavior": behavior})

        @self.app.route('/api/behavior', methods=['GET'])
        def get_behavior():
            """Get the default breakpoint behavior."""
            return jsonify({
                "behavior": self.manager.get_default_behavior()
            })

        @self.app.route('/api/behavior', methods=['POST'])
        def set_behavior():
            """Set the default breakpoint behavior."""
            data = request.get_json() or {}
            behavior = data.get('behavior')
            if behavior == 'continue':
                behavior = 'go'
            if behavior not in {'stop', 'go'}:
                return jsonify({"error": "behavior must be 'stop' or 'go'"}), 400

            self.manager.set_default_behavior(behavior)
            return jsonify({"status": "ok", "behavior": behavior})

        @self.app.route('/api/call/start', methods=['POST'])
        def call_start():
            """Handle call start from debug client."""
            data = request.get_json() or {}
            method_name = data.get("method_name")
            target = data.get("target", {})
            args = data.get("args", [])
            kwargs = data.get("kwargs", {})

            missing = []
            missing.extend(collect_missing_cids([target] if target else []))
            missing.extend(collect_missing_cids(args))
            missing.extend(collect_missing_cids(kwargs))
            if missing:
                return jsonify({
                    "error": "cid_not_found",
                    "missing_cids": missing,
                    "message": "Resend with full data",
                }), 400

            store_payload([target] if target else [])
            store_payload(args)
            store_payload(kwargs)

            call_id = next_call_id()
            action = {"call_id": call_id, "action": "continue"}

            # Check if we should pause at this breakpoint
            if self.manager.should_pause_at_breakpoint(method_name):
                pretty_args = [
                    _format_payload_value(item)
                    for item in args
                    if isinstance(item, dict)
                ]
                pretty_kwargs = {
                    key: _format_payload_value(value)
                    for key, value in kwargs.items()
                    if isinstance(value, dict)
                }
                pause_id = self.manager.add_paused_execution({
                    "method_name": method_name,
                    "args": args,
                    "kwargs": kwargs,
                    "pretty_args": pretty_args,
                    "pretty_kwargs": pretty_kwargs,
                    "call_site": data.get("call_site"),
                })
                action = {
                    "call_id": call_id,
                    "action": "poll",
                    "poll_interval_ms": 100,
                    "poll_url": f"/api/poll/{pause_id}",
                    "timeout_ms": 60_000,
                }

            return jsonify(action)

        @self.app.route('/api/poll/<pause_id>', methods=['GET'])
        def poll(pause_id):
            """Poll for resume actions."""
            action = self.manager.pop_resume_action(pause_id)
            if action is None:
                return jsonify({"status": "waiting"})
            return jsonify({"status": "ready", "action": action})

        @self.app.route('/api/call/complete', methods=['POST'])
        def call_complete():
            """Handle call completion from debug client."""
            data = request.get_json() or {}
            result_data = data.get("result_data")
            result_cid = data.get("result_cid")
            exception_data = data.get("exception_data")
            exception_cid = data.get("exception_cid")

            if result_data and result_cid:
                self._cid_store.store(result_cid, base64.b64decode(result_data))
            if exception_data and exception_cid:
                self._cid_store.store(exception_cid, base64.b64decode(exception_data))

            return jsonify({"status": "ok"})

        @self.app.route('/api/paused', methods=['GET'])
        def get_paused():
            """Get all paused executions."""
            return jsonify({
                "paused": self.manager.get_paused_executions()
            })

        @self.app.route('/api/paused/<pause_id>/continue', methods=['POST'])
        def continue_execution(pause_id):
            """Continue a paused execution."""
            data = request.get_json() or {}
            action = data.get('action', 'continue')

            if action == 'skip':
                return jsonify({"error": "skip_not_supported"}), 400

            action_dict = {"action": action}

            # Include additional fields if present
            if 'modified_args' in data:
                action_dict['modified_args'] = data['modified_args']
            if 'modified_kwargs' in data:
                action_dict['modified_kwargs'] = data['modified_kwargs']
            if 'fake_result' in data:
                action_dict['fake_result'] = data['fake_result']
            if 'fake_result_data' in data:
                action_dict['fake_result_data'] = data['fake_result_data']
            if 'exception' in data:
                action_dict['exception'] = data['exception']
            if 'exception_type' in data:
                action_dict['exception_type'] = data['exception_type']
            if 'exception_message' in data:
                action_dict['exception_message'] = data['exception_message']

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
