"""Web server for interactive breakpoint management.

This module provides a Flask-based web server with REST API endpoints
for managing breakpoints and paused executions through a web UI.
"""

import base64
import hashlib
import uuid
import html
import json
import logging
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import quote

from flask import Flask, jsonify, render_template_string, request
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from werkzeug.serving import BaseWSGIServer, make_server

from .breakpoint_manager import BreakpointManager
from .cid_store import CIDStore
from .port_discovery import get_discovery_file_path, write_port_file
from .serialization import Serializer, deserialize

# Configure Flask's logging to suppress request spam by default
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING)


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
        .paused-meta {
            margin: -4px 0 10px;
            font-size: 0.85em;
            color: #6b5a2b;
            word-break: break-word;
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
        .function-choices {
            background-color: #f8f8f8;
            padding: 10px;
            border-radius: 4px;
            margin: 10px 0;
        }
        .function-choices label {
            display: flex;
            align-items: center;
            gap: 6px;
            margin: 4px 0;
            cursor: pointer;
        }
        .function-choices input {
            cursor: pointer;
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
        .btn-repl {
            background-color: #1565C0;
            color: white;
        }
        .btn-repl:hover {
            background-color: #0D47A1;
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
            align-items: center;
            gap: 12px;
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
        .breakpoint-name {
            font-weight: 600;
            color: #1976D2;
            text-decoration: none;
        }
        .breakpoint-name:hover {
            text-decoration: underline;
        }
        .breakpoint-options {
            margin-left: auto;
        }
        .state-btn {
            border: 2px solid transparent;
            background: white;
            cursor: pointer;
            padding: 6px 10px;
            border-radius: 999px;
            font-size: 16px;
            line-height: 1;
            width: 34px;
            height: 30px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }
        .state-btn.selected {
            border-color: #333;
        }
        .tabs {
            display: flex;
            gap: 8px;
            margin: 12px 0 16px;
            padding: 6px;
            background: #f8f8f8;
            border: 1px solid #ddd;
            border-radius: 10px;
        }
        .tab-btn {
            flex: 1;
            border: 1px solid transparent;
            background: transparent;
            cursor: pointer;
            padding: 10px 12px;
            border-radius: 8px;
            font-weight: 600;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        .tab-btn.active {
            background: white;
            border-color: #ddd;
        }
        .tab-count {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 24px;
            height: 22px;
            padding: 0 8px;
            border-radius: 999px;
            background: #eee;
            font-size: 0.85em;
            font-weight: 700;
        }
        .tab-panel {
            display: none;
        }
        .tab-panel.active {
            display: block;
        }
        .empty-state {
            color: #666;
            font-style: italic;
            padding: 20px;
            text-align: center;
        }
        .nav-links {
            display: flex;
            gap: 12px;
            margin: 10px 0 16px;
        }
        .nav-link {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 8px 12px;
            border-radius: 999px;
            border: 1px solid #d0d7de;
            background: white;
            color: #1976D2;
            font-weight: 600;
            text-decoration: none;
        }
        .nav-link:hover {
            border-color: #1976D2;
            text-decoration: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🛑 Interactive Breakpoints</h1>

        <div class="nav-links">
            <a class="nav-link" href="/objects">🧭 Objects</a>
            <a class="nav-link" href="/call-tree">🌲 Call Tree</a>
            <a class="nav-link" href="/com-errors">📡 Com Errors</a>
        </div>

        <div id="statusMessage" class="status-message"></div>

        <div class="tabs">
            <button id="tabBtnPaused" class="tab-btn active" type="button">
                ⏸️ Paused Executions <span id="pausedCount" class="tab-count">0</span>
            </button>
            <button id="tabBtnBreakpoints" class="tab-btn" type="button">
                🔴 Active Breakpoints <span id="breakpointsCount" class="tab-count">0</span>
            </button>
        </div>

        <div id="tabPaused" class="tab-panel active">
            <h2>⏸️ Paused Executions</h2>
            <div id="pausedExecutions">
                <div class="empty-state">No executions currently paused.</div>
            </div>
        </div>

        <div id="tabBreakpoints" class="tab-panel">
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
    </div>

    <script>
        const API_BASE = '/api';
        let updateInterval = null;
        let registeredFunctions = [];
        let functionSignatures = {};
        const selectedReplacements = {};
        let isBreakpointSelectActive = false;
        let activeTab = 'paused';

        function escapeHtml(text) {
            return String(text)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        function formatPretty(value) {
            if (value && typeof value === 'object' && value.__cideldill_placeholder__) {
                return value.summary || '<Unpicklable>';
            }
            return String(value);
        }

        function setActiveTab(tab) {
            activeTab = tab;
            const pausedPanel = document.getElementById('tabPaused');
            const breakpointsPanel = document.getElementById('tabBreakpoints');
            const pausedBtn = document.getElementById('tabBtnPaused');
            const breakpointsBtn = document.getElementById('tabBtnBreakpoints');
            const pausedActive = tab === 'paused';
            pausedPanel.classList.toggle('active', pausedActive);
            breakpointsPanel.classList.toggle('active', !pausedActive);
            pausedBtn.classList.toggle('active', pausedActive);
            breakpointsBtn.classList.toggle('active', !pausedActive);
        }

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

        async function setAfterBreakpointBehavior(functionName, behavior) {
            try {
                const encoded = encodeURIComponent(functionName);
                const response = await fetch(`${API_BASE}/breakpoints/${encoded}/after_behavior`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ behavior: behavior })
                });

                if (response.ok) {
                    const icon = behavior === 'stop' ? '🛑' : (behavior === 'yield' ? '⚠️' : '🟢');
                    showMessage(`${icon} Set after-breakpoint behavior: ${functionName}`, 'success');
                    loadBreakpoints();
                } else {
                    showMessage('Failed to set after-breakpoint behavior', 'error');
                }
            } catch (e) {
                console.error('Failed to set after-breakpoint behavior:', e);
                showMessage('Error setting after-breakpoint behavior', 'error');
            }
        }

        async function setBreakpointReplacement(functionName, replacement) {
            try {
                const previous = selectedReplacements[functionName];
                selectedReplacements[functionName] = replacement;
                const encoded = encodeURIComponent(functionName);
                const response = await fetch(`${API_BASE}/breakpoints/${encoded}/replacement`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ replacement_function: replacement })
                });

                if (response.ok) {
                    showMessage(`✅ Set replacement: ${functionName} → ${replacement}`, 'success');
                    loadBreakpoints();
                } else {
                    if (previous) {
                        selectedReplacements[functionName] = previous;
                    } else {
                        delete selectedReplacements[functionName];
                    }
                    showMessage('Failed to set replacement', 'error');
                }
            } catch (e) {
                console.error('Failed to set replacement:', e);
                delete selectedReplacements[functionName];
                showMessage('Error setting replacement', 'error');
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

                const bpCount = (data.breakpoints && data.breakpoints.length) ? data.breakpoints.length : 0;
                const bpCountEl = document.getElementById('breakpointsCount');
                if (bpCountEl) {
                    bpCountEl.textContent = bpCount;
                }

                const container = document.getElementById('breakpointsList');
                if (data.breakpoints && data.breakpoints.length > 0) {
                    const states = data.breakpoint_behaviors || {};
                    const afterStates = data.breakpoint_after_behaviors || {};
                    const replacements = data.breakpoint_replacements || {};
                    const sortBreakpoints = (items) => {
                        return [...items].sort((a, b) => {
                            const sigA = functionSignatures[a] || '';
                            const sigB = functionSignatures[b] || '';
                            if (sigA < sigB) return -1;
                            if (sigA > sigB) return 1;
                            return a.localeCompare(b);
                        });
                    };
                    container.innerHTML = '<div class="breakpoint-list">' +
                        sortBreakpoints(data.breakpoints).map(bp => {
                            const signature = functionSignatures[bp];
                            const alternates = [];
                            if (signature) {
                                registeredFunctions.forEach(fn => {
                                    if (fn !== bp && functionSignatures[fn] === signature) {
                                        alternates.push(fn);
                                    }
                                });
                            }
                            if (bp in replacements) {
                                selectedReplacements[bp] = replacements[bp];
                            }
                            const replacement = selectedReplacements[bp] || bp;
                            if (alternates.length > 0 && !(bp in selectedReplacements)) {
                                selectedReplacements[bp] = replacement;
                            }
                            const replacementSelect = alternates.length > 0
                                ? `<select class="breakpoint-replacement-select"
                                          onchange="setBreakpointReplacement('${bp}', this.value)">
                                        <option value="${escapeHtml(bp)}" ${replacement === bp ? 'selected' : ''}>
                                            ${escapeHtml(bp)}()
                                        </option>
                                        ${alternates.map(fn => `
                                            <option value="${escapeHtml(fn)}" ${replacement === fn ? 'selected' : ''}>
                                                ${escapeHtml(fn)}()
                                            </option>
                                        `).join('')}
                                   </select>`
                                : '';
                            return `
                                <div class="breakpoint-item ${states[bp] === 'go' ? 'go' : (states[bp] === 'yield' ? 'yield' : 'stop')}">
                                    <div class="state-toggle">
                                        <button class="state-btn ${states[bp] === 'stop' ? 'selected' : ''}"
                                                onclick="setBreakpointBehavior('${bp}', 'stop')"
                                                title="Before: Stop (pause)">
                                            🛑
                                        </button>
                                        <button class="state-btn ${states[bp] === 'yield' ? 'selected' : ''}"
                                                onclick="setBreakpointBehavior('${bp}', 'yield')"
                                                title="Before: Yield (inherit global default)">
                                            ⚠️
                                        </button>
                                        <button class="state-btn ${states[bp] === 'go' ? 'selected' : ''}"
                                                onclick="setBreakpointBehavior('${bp}', 'go')"
                                                title="Before: Go (don't pause)">
                                            🟢
                                        </button>
                                    </div>
                                    <a href="/breakpoint/${encodeURIComponent(bp)}/history" class="breakpoint-name">${escapeHtml(bp)}()</a>
                                    <div class="state-toggle">
                                        <button class="state-btn ${afterStates[bp] === 'stop' ? 'selected' : ''}"
                                                onclick="setAfterBreakpointBehavior('${bp}', 'stop')"
                                                title="After: Stop (pause)">
                                            🛑
                                        </button>
                                        <button class="state-btn ${afterStates[bp] === 'yield' ? 'selected' : ''}"
                                                onclick="setAfterBreakpointBehavior('${bp}', 'yield')"
                                                title="After: Yield (inherit global default)">
                                            ⚠️
                                        </button>
                                        <button class="state-btn ${afterStates[bp] === 'go' ? 'selected' : ''}"
                                                onclick="setAfterBreakpointBehavior('${bp}', 'go')"
                                                title="After: Go (don't pause)">
                                            🟢
                                        </button>
                                    </div>
                                    <div class="breakpoint-options">${replacementSelect}</div>
                                </div>
                            `;
                        }).join('') + '</div>';
                } else {
                    container.innerHTML = '<div class="empty-state">' +
                        'No breakpoints set.</div>';
                }
            } catch (e) {
                console.error('Failed to load breakpoints:', e);
            }
        }

        async function loadFunctions() {
            try {
                const response = await fetch(`${API_BASE}/functions`);
                const data = await response.json();
                registeredFunctions = data.functions || [];
                functionSignatures = data.function_signatures || {};
            } catch (e) {
                console.error('Failed to load functions:', e);
                registeredFunctions = [];
                functionSignatures = {};
            }
        }

        async function refresh() {
            await loadFunctions();
            if (!isBreakpointSelectActive) {
                await loadBreakpoints();
            }
            await loadPausedExecutions();
        }

        document.addEventListener('focusin', (event) => {
            const target = event.target;
            if (target && target.classList && target.classList.contains('breakpoint-replacement-select')) {
                isBreakpointSelectActive = true;
            }
        });

        document.addEventListener('focusout', (event) => {
            const target = event.target;
            if (target && target.classList && target.classList.contains('breakpoint-replacement-select')) {
                isBreakpointSelectActive = false;
            }
        });

        document.addEventListener('DOMContentLoaded', function() {
            const pausedBtn = document.getElementById('tabBtnPaused');
            const breakpointsBtn = document.getElementById('tabBtnBreakpoints');
            if (pausedBtn) {
                pausedBtn.addEventListener('click', () => setActiveTab('paused'));
            }
            if (breakpointsBtn) {
                breakpointsBtn.addEventListener('click', () => setActiveTab('breakpoints'));
            }
            setActiveTab(activeTab);
            // Load initial state
            loadBehavior();
            refresh();

            updateInterval = setInterval(() => {
                refresh();
            }, 1000);
        });

        // Load paused executions
        async function loadPausedExecutions() {
            try {
                const response = await fetch(`${API_BASE}/paused`);
                const data = await response.json();

                const pausedCount = (data.paused && data.paused.length) ? data.paused.length : 0;
                const pausedCountEl = document.getElementById('pausedCount');
                if (pausedCountEl) {
                    pausedCountEl.textContent = pausedCount;
                }

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
            const signature = callData.signature || null;
            const prettyResult = callData.pretty_result;
            const replSessions = Array.isArray(paused.repl_sessions) ? paused.repl_sessions : [];
            const pageUrl = callData.page_url;
            const processPid = callData.process_pid;
            const processLabel = (processPid === 0 && pageUrl) ? `JS ${pageUrl}` : `PID ${processPid}`;

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

            const renderResult = () => {
                if (prettyResult === null || prettyResult === undefined) {
                    return '';
                }
                return `<div class="call-data"><strong>Return Value:</strong>
${escapeHtml(formatPretty(prettyResult))}</div>`;
            };

            const renderReplSessions = () => {
                if (!replSessions.length) {
                    return '';
                }
                const links = replSessions.map(id => {
                    const href = `/repl/${encodeURIComponent(id)}`;
                    return `<a href="${href}" target="_blank" rel="noopener noreferrer" style="color:#1565c0;text-decoration:none;">${escapeHtml(id)}</a>`;
                }).join('<br>');
                return `<div class="call-data"><strong>REPL Sessions:</strong><div style="margin-top:6px;">${links}</div></div>`;
            };

            const renderFunctionChoices = () => {
                const candidates = [];
                const seen = new Set();
                const defaultName = displayName;
                if (defaultName && !seen.has(defaultName)) {
                    candidates.push(defaultName);
                    seen.add(defaultName);
                }
                if (signature) {
                    registeredFunctions.forEach((fn) => {
                        if (functionSignatures[fn] === signature && !seen.has(fn)) {
                            candidates.push(fn);
                            seen.add(fn);
                        }
                    });
                }
                if (candidates.length === 0) {
                    return '';
                }
                const radioName = `replacement-${paused.id}`;
                const saved = selectedReplacements[paused.id] || selectedReplacements[displayName];
                if (!selectedReplacements[paused.id] && selectedReplacements[displayName]) {
                    selectedReplacements[paused.id] = selectedReplacements[displayName];
                }
                const options = candidates.map(fn => `
                    <label>
                        <input type="radio" name="${radioName}" value="${escapeHtml(fn)}"
                               ${fn === (saved || defaultName) ? 'checked' : ''}
                               onchange="setReplacementSelection('${paused.id}', '${escapeHtml(fn)}')">
                        <span>${escapeHtml(fn)}()</span>
                    </label>
                `).join('');
                return `<div class="function-choices">
                    <div style="font-weight: 600; margin-bottom: 6px;">Execute:</div>
                    ${options}
                </div>`;
            };

            return `
                <div class="paused-card">
                    <div class="paused-header">
                        ⏸️ ${escapeHtml(displayName)}() - Paused at ${pausedAt}
                    </div>
                    <div class="paused-meta">${escapeHtml(processLabel || '')}</div>
                    ${renderArgs()}
                    ${renderStack()}
                    ${renderResult()}
                    ${renderReplSessions()}
                    ${renderFunctionChoices()}
                    <div class="actions">
                        <button class="btn btn-go" data-default-function="${escapeHtml(displayName)}"
                                onclick="continueExecution('${paused.id}', this.dataset.defaultFunction)">
                            🟢
                        </button>
                        <button class="btn btn-repl" onclick="openRepl('${paused.id}')">
                            REPL
                        </button>
                    </div>
                </div>
            `;
        }

        // Continue execution
        function selectedReplacement(pauseId) {
            return selectedReplacements[pauseId] || null;
        }

        function setReplacementSelection(pauseId, functionName) {
            selectedReplacements[pauseId] = functionName;
        }

        async function continueExecution(pauseId, defaultFunction) {
            try {
                const selected = selectedReplacement(pauseId)
                    || defaultFunction
                    || null;
                const payload = { action: 'continue' };
                if (selected && defaultFunction && selected !== defaultFunction) {
                    payload.replacement_function = selected;
                }
                const response = await fetch(`${API_BASE}/paused/${pauseId}/continue`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (response.ok) {
                    showMessage('Execution resumed', 'success');
                    loadPausedExecutions();
                }
            } catch (e) {
                showMessage('Failed to continue execution: ' + e.message, 'error');
            }
        }

        async function openRepl(pauseId) {
            try {
                const response = await fetch(`${API_BASE}/repl/start`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pause_id: pauseId })
                });
                if (!response.ok) {
                    const data = await response.json();
                    showMessage(`Failed to start REPL: ${data.error || response.status}`, 'error');
                    return;
                }
                const data = await response.json();
                if (data.session_id) {
                    window.location.href = `/repl/${encodeURIComponent(data.session_id)}`;
                }
            } catch (e) {
                showMessage('Failed to start REPL: ' + e.message, 'error');
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

    def __init__(
        self,
        manager: BreakpointManager,
        port: int = 5174,
        host: str = "0.0.0.0",
        debug_enabled: bool = False,
        db_path: str = ":memory:",
        port_file: Path | None = None,
        repl_eval_timeout_s: float = 30.0,
    ) -> None:
        """Initialize the server.

        Args:
            manager: BreakpointManager instance to use.
            port: Port number to listen on (0 for random available port).
        """
        self.manager = manager
        self.requested_port = port
        self.actual_port = port
        self.host = host
        self.app = Flask(__name__)
        self._running = False
        self._server: BaseWSGIServer | None = None
        self._cid_store = CIDStore(db_path)
        self._call_seq = 0
        self._call_seq_lock = threading.Lock()
        self._debug_enabled = debug_enabled
        self._repl_eval_timeout_s = float(repl_eval_timeout_s)
        self._repl_lock = threading.Lock()
        self._repl_eval_queues: dict[str, deque[dict[str, str]]] = {}
        self._repl_eval_waiters: dict[str, dict[str, object]] = {}
        self.port_file = port_file or get_discovery_file_path()
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Set up Flask routes."""

        @self.app.after_request
        def log_poll_requests(response):
            if not self._debug_enabled:
                return response
            if request.path.startswith("/api/poll/") and response.status_code == 200:
                timestamp = time.strftime("%d/%b/%Y %H:%M:%S", time.localtime())
                remote_addr = request.remote_addr or "-"
                protocol = request.environ.get("SERVER_PROTOCOL", "HTTP/1.1")
                log_line = (
                    f"{remote_addr} - - [{timestamp}] "
                    f"\"{request.method} {request.path} {protocol}\" "
                    f"{response.status_code} -"
                )
                print(log_line)
            return response

        @self.app.after_request
        def add_cors_headers(response):
            if request.path.startswith("/api/"):
                response.headers["Access-Control-Allow-Origin"] = "*"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type"
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            return response

        @self.app.route('/api/<path:_path>', methods=['OPTIONS'])
        def api_options(_path: str):
            return ("", 204)

        def next_call_id() -> str:
            with self._call_seq_lock:
                self._call_seq += 1
                seq = self._call_seq
            timestamp = f"{time.time():.6f}"
            return f"{timestamp}-{seq:03d}"

        def _error_payload(
            error: str,
            message: str,
            *,
            expected_cid: str | None = None,
            provided_cid: str | None = None,
        ) -> dict[str, object]:
            payload: dict[str, object] = {"error": error, "message": message}
            if expected_cid is not None:
                payload["expected_cid"] = expected_cid
            if provided_cid is not None:
                payload["provided_cid"] = provided_cid
            return payload

        def _resolve_serialization_format(
            item: dict[str, object], *, default: str = "dill"
        ) -> str:
            fmt = item.get("serialization_format", default) or default
            if fmt not in {"dill", "json"}:
                raise ValueError("invalid_serialization_format")
            return fmt

        def _decode_payload_bytes(item: dict[str, object]) -> tuple[bytes | None, str]:
            fmt = _resolve_serialization_format(item)
            if "data" not in item:
                return None, fmt
            raw = item.get("data")
            if fmt == "json":
                if not isinstance(raw, str):
                    raise ValueError("invalid_json")
                try:
                    json.loads(raw)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError("invalid_json") from exc
                return raw.encode("utf-8"), fmt
            if not isinstance(raw, str):
                raise ValueError("invalid_dill")
            try:
                return base64.b64decode(raw), fmt
            except Exception as exc:  # noqa: BLE001
                raise ValueError("invalid_dill") from exc

        def collect_missing_cids(items) -> list[str]:
            missing: list[str] = []
            iterable = items.values() if isinstance(items, dict) else items
            for item in iterable:
                if "cid" not in item:
                    continue
                if "data" not in item and not self._cid_store.exists(item["cid"]):
                    missing.append(item["cid"])
            return missing

        def store_payload(items) -> dict[str, object] | None:
            iterable = items.values() if isinstance(items, dict) else items
            for item in iterable:
                if "cid" not in item or "data" not in item:
                    continue
                cid = item.get("cid")
                if not isinstance(cid, str):
                    continue
                try:
                    data, _fmt = _decode_payload_bytes(item)
                except ValueError as exc:
                    if str(exc) == "invalid_serialization_format":
                        return _error_payload(
                            "invalid_serialization_format",
                            "serialization_format must be 'dill' or 'json'",
                        )
                    if str(exc) == "invalid_json":
                        return _error_payload("invalid_json", "Invalid JSON payload")
                    if str(exc) == "invalid_dill":
                        return _error_payload("invalid_dill", "Invalid dill payload")
                    return _error_payload("invalid_payload", "Invalid payload data")
                if data is None:
                    continue
                expected = hashlib.sha512(data).hexdigest()
                if expected != cid:
                    return _error_payload(
                        "cid_mismatch",
                        "Provided CID does not match SHA-512 hash of data",
                        expected_cid=expected,
                        provided_cid=cid,
                    )
                self._cid_store.store(cid, data)
            return None

        def _encode_payload_item(value: object, preferred_format: str) -> dict[str, object]:
            if preferred_format == "json":
                try:
                    data = json.dumps(value)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError("invalid_json") from exc
                cid = hashlib.sha512(data.encode("utf-8")).hexdigest()
                return {
                    "cid": cid,
                    "data": data,
                    "serialization_format": "json",
                }
            serializer = Serializer()
            serialized = serializer.force_serialize_with_data(value)
            return {
                "cid": serialized.cid,
                "data": serialized.data_base64,
                "serialization_format": "dill",
            }

        def _apply_preferred_format(
            action_dict: dict[str, object], preferred_format: str
        ) -> dict[str, object] | None:
            try:
                if "modified_args" in action_dict:
                    args = action_dict.get("modified_args")
                    if isinstance(args, list):
                        action_dict["modified_args"] = [
                            item
                            if isinstance(item, dict) and "cid" in item
                            else _encode_payload_item(item, preferred_format)
                            for item in args
                        ]
                if "modified_kwargs" in action_dict:
                    kwargs = action_dict.get("modified_kwargs")
                    if isinstance(kwargs, dict):
                        encoded_kwargs: dict[str, object] = {}
                        for key, value in kwargs.items():
                            if isinstance(value, dict) and "cid" in value:
                                encoded_kwargs[key] = value
                            else:
                                encoded_kwargs[key] = _encode_payload_item(value, preferred_format)
                        action_dict["modified_kwargs"] = encoded_kwargs
                if "fake_result" in action_dict and "fake_result_data" not in action_dict:
                    encoded = _encode_payload_item(action_dict.get("fake_result"), preferred_format)
                    action_dict["fake_result_cid"] = encoded.get("cid")
                    action_dict["fake_result_data"] = encoded.get("data")
                    action_dict["fake_result_serialization_format"] = encoded.get("serialization_format")
            except ValueError as exc:
                if str(exc) == "invalid_json":
                    return _error_payload("invalid_json", "Invalid JSON payload")
                return _error_payload("invalid_payload", "Invalid payload data")
            return None

        def _queue_repl_eval(pause_id: str, session_id: str, expr: str) -> str:
            eval_id = str(uuid.uuid4())
            with self._repl_lock:
                self._repl_eval_queues.setdefault(pause_id, deque()).append({
                    "eval_id": eval_id,
                    "session_id": session_id,
                    "expr": expr,
                })
                self._repl_eval_waiters[eval_id] = {
                    "event": threading.Event(),
                    "result": None,
                    "session_id": session_id,
                    "pause_id": pause_id,
                    "expr": expr,
                    "closed": False,
                }
            return eval_id

        def _pop_repl_eval(pause_id: str) -> dict[str, str] | None:
            with self._repl_lock:
                queue = self._repl_eval_queues.get(pause_id)
                if not queue:
                    return None
                return queue.popleft()

        def _mark_repl_waiters_closed(pause_id: str | None = None, session_id: str | None = None) -> None:
            with self._repl_lock:
                for waiter in self._repl_eval_waiters.values():
                    if pause_id and waiter.get("pause_id") != pause_id:
                        continue
                    if session_id and waiter.get("session_id") != session_id:
                        continue
                    waiter["closed"] = True
                    event = waiter.get("event")
                    if isinstance(event, threading.Event):
                        event.set()

        def _safe_repr(obj: object, limit: int = 500) -> str:
            try:
                text = repr(obj)
            except Exception as exc:  # noqa: BLE001
                text = f"<unreprable: {type(exc).__name__}>"
            if len(text) > limit:
                return text[:limit] + "..."
            return text

        def _is_placeholder(value: object) -> bool:
            return (
                hasattr(value, "pickle_error")
                and hasattr(value, "attributes")
                and hasattr(value, "failed_attributes")
                and hasattr(value, "type_name")
            )

        def _placeholder_summary(value: object) -> str:
            module = getattr(value, "module", "unknown")
            qualname = getattr(value, "qualname", getattr(value, "type_name", "Unknown"))
            object_name = getattr(value, "object_name", None)
            attrs = getattr(value, "attributes", {}) or {}
            failed = getattr(value, "failed_attributes", {}) or {}
            error = getattr(value, "pickle_error", "")
            name_prefix = f"{object_name} " if object_name else ""
            return (
                f"<Unpicklable {name_prefix}{module}.{qualname} "
                f"attrs={len(attrs)} failed={len(failed)} error={error}>"
            )

        def _is_json_scalar(value: object) -> bool:
            return value is None or isinstance(value, (str, int, float, bool))

        def _format_placeholder_value(
            value: object,
            *,
            depth: int,
            max_depth: int,
        ) -> object:
            if _is_placeholder(value):
                if depth < max_depth:
                    return _format_placeholder(value, depth=depth + 1, max_depth=max_depth)
                return _placeholder_summary(value)

            if _is_json_scalar(value):
                return value

            if depth > max_depth:
                return _safe_repr(value)

            if isinstance(value, dict):
                formatted_items: dict[str, object] = {}
                for idx, (item_key, item_value) in enumerate(value.items()):
                    if idx >= 50:
                        remaining = len(value) - 50
                        if remaining > 0:
                            formatted_items["__skipped__"] = f"{remaining} more items skipped"
                        break
                    key_text = item_key if isinstance(item_key, str) else _safe_repr(item_key)
                    formatted_items[str(key_text)] = _format_placeholder_value(
                        item_value,
                        depth=depth + 1,
                        max_depth=max_depth,
                    )
                return formatted_items

            if isinstance(value, (list, tuple)):
                sequence = list(value)
                formatted_list: list[object] = []
                for idx, item in enumerate(sequence):
                    if idx >= 50:
                        remaining = len(sequence) - 50
                        if remaining > 0:
                            formatted_list.append(f"<{remaining} more items skipped>")
                        break
                    formatted_list.append(
                        _format_placeholder_value(
                            item,
                            depth=depth + 1,
                            max_depth=max_depth,
                        )
                    )
                return formatted_list

            if isinstance(value, (set, frozenset)):
                formatted_set: list[object] = []
                ordered_items = sorted(value, key=lambda item: _safe_repr(item))
                for idx, item in enumerate(ordered_items):
                    if idx >= 50:
                        remaining = len(ordered_items) - 50
                        if remaining > 0:
                            formatted_set.append(f"<{remaining} more items skipped>")
                        break
                    formatted_set.append(
                        _format_placeholder_value(
                            item,
                            depth=depth + 1,
                            max_depth=max_depth,
                        )
                    )
                return {"__cideldill_set__": formatted_set}

            return _safe_repr(value)

        def _format_placeholder(value: object, depth: int = 0, max_depth: int = 2) -> dict[str, object]:
            attributes = getattr(value, "attributes", {}) or {}
            failed_attributes = getattr(value, "failed_attributes", {}) or {}

            formatted_attributes: dict[str, object] = {}
            for idx, (name, attr_value) in enumerate(attributes.items()):
                if idx >= 50:
                    remaining = len(attributes) - 50
                    if remaining > 0:
                        formatted_attributes["__skipped__"] = f"{remaining} more attributes skipped"
                    break
                formatted_attributes[name] = _format_placeholder_value(
                    attr_value,
                    depth=depth,
                    max_depth=max_depth,
                )

            return {
                "__cideldill_placeholder__": True,
                "summary": _placeholder_summary(value),
                "type_name": getattr(value, "type_name", "Unknown"),
                "module": getattr(value, "module", "unknown"),
                "qualname": getattr(value, "qualname", "Unknown"),
                "object_name": getattr(value, "object_name", None),
                "object_path": getattr(value, "object_path", None),
                "object_id": getattr(value, "object_id", "unknown"),
                "repr_text": getattr(value, "repr_text", ""),
                "str_text": getattr(value, "str_text", None),
                "pickle_error": getattr(value, "pickle_error", ""),
                "pickle_attempts": list(getattr(value, "pickle_attempts", []) or []),
                "attributes": formatted_attributes,
                "failed_attributes": {
                    key: _safe_repr(val) for key, val in failed_attributes.items()
                },
                "depth": getattr(value, "depth", 0),
                "capture_timestamp": getattr(value, "capture_timestamp", 0.0),
            }

        def _format_payload_value(item: dict[str, object]) -> object:
            cid = item.get("cid")
            if not isinstance(cid, str):
                return "<missing cid>"
            try:
                stored = self._cid_store.get(cid)
            except Exception:
                stored = None
            if stored is None:
                return f"<cid:{cid} missing>"
            serialization_format = item.get("serialization_format")
            if serialization_format == "json":
                try:
                    return json.loads(stored.decode("utf-8"))
                except Exception as exc:  # noqa: BLE001
                    return f"<unavailable: {type(exc).__name__}>"
            if serialization_format not in (None, "dill"):
                return f"<unavailable: invalid format {serialization_format}>"
            # If format isn't specified, attempt JSON as a best-effort fallback.
            if serialization_format is None:
                try:
                    return json.loads(stored.decode("utf-8"))
                except Exception:
                    pass
            try:
                value = deserialize(stored)
            except Exception as exc:  # noqa: BLE001
                return f"<unavailable: {type(exc).__name__}>"
            if _is_placeholder(value):
                return _format_placeholder(value)
            return _safe_repr(value)

        def _normalize_client_ref(value: object) -> int | str | None:
            if isinstance(value, (int, str)):
                return value
            return None

        def _record_payload_snapshots(
            *,
            process_key: str,
            call_id: str,
            method_name: str,
            target: dict[str, object] | None,
            args: list[object],
            kwargs: dict[str, object],
        ) -> None:
            timestamp = time.time()

            def record_item(
                item: dict[str, object],
                role: str,
                *,
                index: int | None = None,
                key: str | None = None,
            ) -> None:
                client_ref = _normalize_client_ref(item.get("client_ref"))
                if client_ref is None:
                    return
                snapshot = {
                    "timestamp": timestamp,
                    "call_id": call_id,
                    "method_name": method_name,
                    "role": role,
                    "cid": item.get("cid"),
                    "pretty": _format_payload_value(item),
                }
                if index is not None:
                    snapshot["index"] = index
                if key is not None:
                    snapshot["key"] = key
                self.manager.record_object_snapshot(process_key, client_ref, snapshot)

            if isinstance(target, dict):
                record_item(target, "target")
            for idx, item in enumerate(args):
                if isinstance(item, dict):
                    record_item(item, "arg", index=idx)
            for key, item in kwargs.items():
                if isinstance(item, dict):
                    record_item(item, "kwarg", key=key)

        def _record_completion_snapshot(
            *,
            process_key: str,
            call_id: str,
            method_name: str,
            role: str,
            client_ref: object,
            cid: str | None,
            serialization_format: str | None = None,
        ) -> None:
            normalized_ref = _normalize_client_ref(client_ref)
            if normalized_ref is None or cid is None:
                return
            item: dict[str, object] = {"cid": cid}
            if serialization_format:
                item["serialization_format"] = serialization_format
            snapshot = {
                "timestamp": time.time(),
                "call_id": call_id,
                "method_name": method_name,
                "role": role,
                "cid": cid,
                "pretty": _format_payload_value(item),
            }
            self.manager.record_object_snapshot(process_key, normalized_ref, snapshot)

        def _pretty_text(value: object) -> str:
            if isinstance(value, dict) and value.get("__cideldill_placeholder__"):
                summary = value.get("summary")
                if summary:
                    return str(summary)
                return "<Unpicklable>"
            return str(value)

        def _format_pretty_for_html(value: object) -> str:
            if isinstance(value, dict):
                return json.dumps(value, indent=2)
            return str(value)

        def _is_cid(value: object) -> bool:
            return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{128}", value) is not None

        def _object_ref(process_key: str | None, client_ref: int | str) -> str:
            if process_key:
                return f"ref:{process_key}:{client_ref}"
            return f"ref:{client_ref}"

        def _call_record_timestamp(record: dict[str, object]) -> float:
            call_site = record.get("call_site")
            if isinstance(call_site, dict):
                ts = call_site.get("timestamp")
                if ts is not None:
                    try:
                        return float(ts)
                    except Exception:
                        pass
            for key in ("started_at", "completed_at"):
                value = record.get(key)
                if value is not None:
                    try:
                        return float(value)
                    except Exception:
                        continue
            return 0.0

        def _call_tree_link(process_key: str, call_id: object) -> str:
            return (
                f"/call-tree/{quote(str(process_key), safe='')}"
                f"?selected={quote(str(call_id), safe='')}"
            )

        def _find_registration_call(function_name: str) -> tuple[str, str] | None:
            best: tuple[float, str, str] | None = None
            for record in self.manager.get_call_records():
                if record.get("method_name") != "with_debug.register":
                    continue
                pretty_result = record.get("pretty_result")
                if not isinstance(pretty_result, dict):
                    continue
                if pretty_result.get("function_name") != function_name:
                    continue
                process_key = record.get("process_key")
                call_id = record.get("call_id") or record.get("id")
                if not process_key or call_id is None:
                    continue
                ts = _call_record_timestamp(record)
                if best is None or ts < best[0]:
                    best = (ts, str(process_key), str(call_id))
            if best is None:
                return None
            return best[1], best[2]

        def _find_first_seen_call(histories: dict[str, list[dict[str, object]]]) -> tuple[str, str] | None:
            best: tuple[float, str, str] | None = None
            for process_key, history in histories.items():
                for snapshot in history:
                    call_id = snapshot.get("call_id")
                    if call_id is None:
                        continue
                    ts = snapshot.get("timestamp") or 0
                    try:
                        ts_value = float(ts)
                    except Exception:
                        ts_value = 0.0
                    if best is None or ts_value < best[0]:
                        best = (ts_value, str(process_key), str(call_id))
            if best is None:
                return None
            return best[1], best[2]

        def _normalize_stack_trace(call_site: object) -> list[dict[str, object]]:
            if not isinstance(call_site, dict):
                return []
            stack_trace = call_site.get("stack_trace") or []
            if not isinstance(stack_trace, list):
                return []
            return [
                frame for frame in stack_trace
                if isinstance(frame, dict)
            ]

        def _stack_signature(stack_trace: list[dict[str, object]]) -> tuple[tuple[object, object, object], ...]:
            signature: list[tuple[object, object, object]] = []
            for frame in stack_trace:
                signature.append(
                    (
                        frame.get("filename"),
                        frame.get("lineno"),
                        frame.get("function"),
                    )
                )
            return tuple(signature)

        def _format_ts(ts: float | int | None) -> str:
            if not ts:
                return "Unknown"
            try:
                return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
            except Exception:
                return "Unknown"

        def _process_key(process_pid: object, process_start_time: object) -> str | None:
            if process_pid is None or process_start_time is None:
                return None
            try:
                pid = int(process_pid)
                start = float(process_start_time)
            except (TypeError, ValueError):
                return None
            return f"{start:.6f}+{pid}"

        @self.app.route('/')
        def index():
            """Serve the main web UI."""
            return render_template_string(HTML_TEMPLATE)

        @self.app.route('/api/report-com-error', methods=['POST'])
        def report_com_error():
            """Record a communication error from a client."""
            data = request.get_json() or {}
            if "timestamp" not in data:
                data["timestamp"] = time.time()
            data["received_at"] = time.time()
            self.manager.add_com_error(data)
            return jsonify({"status": "ok"})

        @self.app.route('/api/com-errors', methods=['GET'])
        def list_com_errors():
            """Return recorded communication errors."""
            errors = self.manager.get_com_errors()
            return jsonify({"errors": errors})

        @self.app.route('/com-errors', methods=['GET'])
        def com_errors_page():
            """Serve a page to browse client/server communication errors."""
            errors = self.manager.get_com_errors()
            errors_sorted = sorted(
                errors,
                key=lambda item: float(
                    item.get("timestamp")
                    or item.get("received_at")
                    or 0
                ),
                reverse=True,
            )
            errors_json = json.dumps(errors_sorted)

            template = """
<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"UTF-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
    <title>CID el Dill - Communication Errors</title>
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
            border-bottom: 3px solid #d32f2f;
            padding-bottom: 10px;
        }
        .back-link {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            margin: 12px 0 20px;
            text-decoration: none;
            color: #1976D2;
            font-weight: 600;
        }
        .controls {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }
        .search {
            flex: 1;
            min-width: 240px;
            padding: 10px 12px;
            border-radius: 6px;
            border: 1px solid #ccc;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.08);
        }
        th, td {
            text-align: left;
            padding: 10px 12px;
            border-bottom: 1px solid #eee;
            vertical-align: top;
        }
        th {
            background: #fafafa;
            font-size: 0.9em;
            text-transform: uppercase;
            color: #666;
            letter-spacing: 0.04em;
        }
        tr:hover {
            background: #fef5f5;
        }
        .mono {
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }
        .pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 0.85em;
            background: #ffebee;
            color: #c62828;
            border: 1px solid #ffcdd2;
        }
        .empty-state {
            text-align: center;
            color: #666;
            padding: 20px;
            font-style: italic;
        }
        pre {
            margin: 0;
            white-space: pre-wrap;
            word-break: break-word;
            background: #f8f8f8;
            padding: 12px;
            border-radius: 6px;
            border: 1px solid #eee;
        }
        .detail {
            margin-top: 18px;
            background: white;
            padding: 16px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.08);
        }
    </style>
</head>
<body>
    <div class=\"container\">
        <h1>📡 Communication Errors</h1>
        <a href=\"/\" class=\"back-link\">← Back to Breakpoints</a>

        <div class=\"controls\">
            <input id=\"searchInput\" class=\"search\" type=\"text\" placeholder=\"Filter by summary, path, method, or exception...\" />
        </div>

        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Summary</th>
                    <th>Request</th>
                    <th>Status</th>
                    <th>Exception</th>
                </tr>
            </thead>
            <tbody id=\"errorsBody\"></tbody>
        </table>
        <div id=\"emptyState\" class=\"empty-state\" style=\"display:none;\">No communication errors recorded yet.</div>

        <div class=\"detail\">
            <h2>Details</h2>
            <pre id=\"detailPanel\">Select a row to see full details.</pre>
        </div>
    </div>

    <script>
        const errors = @@COM_ERRORS_JSON@@;
        const state = { filter: '' };

        function formatTs(ts) {
            if (!ts) return 'Unknown';
            try { return new Date(ts * 1000).toLocaleString(); } catch (e) { return 'Unknown'; }
        }

        function safeText(value) {
            if (value === null || value === undefined) return '';
            return String(value);
        }

        function render() {
            const tbody = document.getElementById('errorsBody');
            const emptyState = document.getElementById('emptyState');
            const filter = state.filter;
            const rows = errors.filter((item) => {
                const search = `${safeText(item.summary)} ${safeText(item.path)} ${safeText(item.method)} ${safeText(item.exception_type)} ${safeText(item.exception_message)}`.toLowerCase();
                return !filter || search.includes(filter);
            });

            if (!rows.length) {
                tbody.innerHTML = '';
                emptyState.style.display = 'block';
                return;
            }
            emptyState.style.display = 'none';

            tbody.innerHTML = rows.map((item, idx) => {
                const timeText = formatTs(item.timestamp || item.received_at);
                const summary = safeText(item.summary || item.message || 'Unknown');
                const method = safeText(item.method || '');
                const path = safeText(item.path || '');
                const status = item.status_code ? `HTTP ${item.status_code}` : 'Exception';
                const exception = safeText(item.exception_type || item.exception || '');
                return `
                    <tr data-index=\"${idx}\">
                        <td class=\"mono\">${timeText}</td>
                        <td>${summary}</td>
                        <td class=\"mono\">${method} ${path}</td>
                        <td><span class=\"pill\">${status}</span></td>
                        <td class=\"mono\">${exception}</td>
                    </tr>
                `;
            }).join('');

            document.querySelectorAll('#errorsBody tr').forEach((row) => {
                row.addEventListener('click', () => {
                    const idx = Number(row.getAttribute('data-index'));
                    const item = rows[idx];
                    document.getElementById('detailPanel').textContent = JSON.stringify(item, null, 2);
                });
            });
        }

        document.getElementById('searchInput').addEventListener('input', (event) => {
            state.filter = String(event.target.value || '').trim().toLowerCase();
            render();
        });

        render();
    </script>
</body>
</html>
            """

            return render_template_string(
                template.replace("@@COM_ERRORS_JSON@@", errors_json)
            )

        @self.app.route('/objects', methods=['GET'])
        def objects_page():
            """Browse object references and stored CIDs."""
            rows: list[dict[str, object]] = []

            object_histories = self.manager.get_all_object_histories()
            for (process_key, client_ref), history in object_histories.items():
                if not history:
                    continue
                def snapshot_ts(item: dict[str, object]) -> float:
                    try:
                        return float(item.get("timestamp") or 0)
                    except Exception:
                        return 0.0
                latest = max(history, key=snapshot_ts)
                rows.append({
                    "kind": "object",
                    "ref": _object_ref(process_key, client_ref),
                    "process_key": process_key,
                    "client_ref": client_ref,
                    "cid": latest.get("cid"),
                    "role": latest.get("role"),
                    "method_name": latest.get("method_name"),
                    "call_id": latest.get("call_id"),
                    "last_seen": latest.get("timestamp"),
                    "summary": _pretty_text(latest.get("pretty")),
                })

            refs_seen = {row.get("ref") for row in rows if row.get("ref")}
            for function_name, meta in self.manager.get_function_metadata().items():
                client_ref = meta.get("client_ref")
                if client_ref is None:
                    continue
                process_key = meta.get("last_process_key")
                ref_value = _object_ref(process_key, client_ref)
                if ref_value in refs_seen:
                    continue
                rows.append({
                    "kind": "function",
                    "ref": ref_value,
                    "process_key": process_key,
                    "client_ref": client_ref,
                    "role": "registered",
                    "method_name": function_name,
                    "call_id": None,
                    "last_seen": meta.get("registered_at"),
                    "summary": meta.get("summary")
                    or meta.get("object_name")
                    or meta.get("object_path")
                    or "",
                })
                refs_seen.add(ref_value)

            for entry in self._cid_store.list_entries():
                rows.append({
                    "kind": "cid",
                    "cid": entry.get("cid"),
                    "created_at": entry.get("created_at"),
                    "size_bytes": entry.get("size_bytes"),
                    "last_seen": entry.get("created_at"),
                })

            data_json = json.dumps(rows)

            template = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
  <title>Objects</title>
  <style>
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
    .container { max-width: 1300px; margin: 0 auto; }
    h1 { color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }
    .back-link { display: inline-block; margin-bottom: 20px; color: #1976D2; text-decoration: none; }
    .back-link:hover { text-decoration: underline; }
    .toolbar { display: flex; gap: 12px; align-items: center; margin: 14px 0 16px; flex-wrap: wrap; }
    .search-input { flex: 1; min-width: 280px; padding: 10px 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 0.95em; background: white; }
    .summary { color: #666; font-size: 0.9em; white-space: nowrap; }
    table { width: 100%; border-collapse: collapse; background: white; border: 1px solid #ddd; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.06); }
    thead th { text-align: left; background: #fafafa; border-bottom: 1px solid #eee; padding: 12px 10px; font-size: 0.9em; color: #444; user-select: none; cursor: pointer; white-space: nowrap; }
    thead th.sort-active { color: #111; }
    tbody td { padding: 10px; border-bottom: 1px solid #f0f0f0; vertical-align: top; font-size: 0.92em; color: #222; }
    tbody tr:hover { background: #f7fbff; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.92em; white-space: pre-wrap; word-break: break-word; }
    .row-link { color: #1976D2; text-decoration: none; font-weight: 600; }
    .row-link:hover { text-decoration: underline; }
    .empty-state { text-align: center; padding: 40px; color: #666; font-style: italic; }
  </style>
</head>
<body>
  <div class=\"container\">
    <a href=\"/\" class=\"back-link\">← Back to Breakpoints</a>
    <h1>Objects</h1>
    <div class=\"toolbar\">
      <input id=\"searchInput\" class=\"search-input\" type=\"text\" placeholder=\"Filter by ref, CID, method, role, or summary...\" />
      <div id=\"summary\" class=\"summary\"></div>
    </div>
    <div id=\"tableWrapper\"></div>
  </div>

  <script>
    const rows = @@DATA_JSON@@;
    const state = { filter: '', sortKey: 'last_seen', sortDir: 'desc' };

    function formatTs(ts) {
      if (!ts) return 'Unknown';
      try { return new Date(ts * 1000).toLocaleString(); } catch (e) { return 'Unknown'; }
    }

    function formatBytes(bytes) {
      if (!bytes && bytes !== 0) return '';
      const units = ['B', 'KB', 'MB', 'GB'];
      let idx = 0;
      let value = Number(bytes);
      while (value >= 1024 && idx < units.length - 1) {
        value /= 1024;
        idx += 1;
      }
      return `${value.toFixed(value >= 10 || idx === 0 ? 0 : 1)} ${units[idx]}`;
    }

    function getCellValue(row, key) {
      if (key === 'id') return row.ref || row.cid || '';
      if (key === 'last_seen') return row.last_seen || row.created_at || 0;
      if (key === 'size_bytes') return row.size_bytes || 0;
      return row[key] || '';
    }

    function sortRows(items) {
      const key = state.sortKey;
      const dir = state.sortDir === 'asc' ? 1 : -1;
      return [...items].sort((a, b) => {
        const av = getCellValue(a, key);
        const bv = getCellValue(b, key);
        if (typeof av === 'number' && typeof bv === 'number') {
          return (av - bv) * dir;
        }
        return String(av).localeCompare(String(bv)) * dir;
      });
    }

    function matchesFilter(row, filter) {
      if (!filter) return true;
      const haystack = JSON.stringify(row).toLowerCase();
      return haystack.includes(filter);
    }

    function render() {
      const filter = state.filter;
      const filtered = rows.filter((row) => matchesFilter(row, filter));
      const sorted = sortRows(filtered);
      const summary = document.getElementById('summary');
      summary.textContent = `${sorted.length} of ${rows.length} rows`;

      if (!sorted.length) {
        document.getElementById('tableWrapper').innerHTML =
          '<div class=\"empty-state\">No objects or CIDs recorded yet.</div>';
        return;
      }

      const header = `
        <table>
          <thead>
            <tr>
              <th data-key=\"kind\">Type</th>
              <th data-key=\"id\">Ref / CID</th>
              <th data-key=\"process_key\">Process</th>
              <th data-key=\"client_ref\">Client Ref</th>
              <th data-key=\"role\">Role</th>
              <th data-key=\"method_name\">Method</th>
              <th data-key=\"call_id\">Call</th>
              <th data-key=\"last_seen\">Last Seen</th>
              <th data-key=\"size_bytes\">Size</th>
              <th data-key=\"summary\">Summary</th>
            </tr>
          </thead>
          <tbody>
            ${sorted.map((row) => {
              const id = row.ref || row.cid || '';
              const href = id ? `/object/${encodeURIComponent(id)}` : '';
              const link = href ? `<a class=\"row-link\" href=\"${href}\">${id}</a>` : '';
              return `
                <tr>
                  <td>${row.kind || ''}</td>
                  <td class=\"mono\">${link || ''}</td>
                  <td class=\"mono\">${row.process_key || ''}</td>
                  <td class=\"mono\">${row.client_ref ?? ''}</td>
                  <td>${row.role || ''}</td>
                  <td class=\"mono\">${row.method_name || ''}</td>
                  <td class=\"mono\">${row.call_id || ''}</td>
                  <td class=\"mono\">${formatTs(row.last_seen || row.created_at)}</td>
                  <td class=\"mono\">${formatBytes(row.size_bytes)}</td>
                  <td>${row.summary || ''}</td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      `;

      document.getElementById('tableWrapper').innerHTML = header;
      document.querySelectorAll('th[data-key]').forEach((th) => {
        const key = th.getAttribute('data-key');
        th.classList.toggle('sort-active', key === state.sortKey);
        th.addEventListener('click', () => {
          if (state.sortKey === key) {
            state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
          } else {
            state.sortKey = key;
            state.sortDir = 'asc';
          }
          render();
        });
      });
    }

    document.getElementById('searchInput').addEventListener('input', (event) => {
      state.filter = String(event.target.value || '').trim().toLowerCase();
      render();
    });

    render();
  </script>
</body>
</html>"""

            return template.replace("@@DATA_JSON@@", data_json)

        @self.app.route('/object/<path:object_ref>', methods=['GET'])
        def object_page(object_ref: str):
            """Show object details for a CID or client ref."""
            def parse_ref(value: str) -> tuple[str | None, int | str]:
                ref_value = value
                if ref_value.startswith("ref:"):
                    ref_value = ref_value[4:]
                if ":" in ref_value:
                    process_part, client_part = ref_value.split(":", 1)
                else:
                    process_part, client_part = None, ref_value
                if client_part.isdigit():
                    client_ref_value: int | str = int(client_part)
                else:
                    client_ref_value = client_part
                return process_part, client_ref_value

            if _is_cid(object_ref):
                meta = self._cid_store.get_meta(object_ref)
                data = self._cid_store.get(object_ref)
                if meta is None or data is None:
                    return (
                        "<h1>Object not found.</h1><p>Unknown CID.</p>"
                    ), 404

                decoded: object | None = None
                decode_error: str | None = None
                try:
                    decoded = deserialize(data)
                except Exception as exc:  # noqa: BLE001
                    decode_error = f"{type(exc).__name__}: {exc}"

                if decode_error:
                    rendered = f"<unavailable: {decode_error}>"
                elif _is_placeholder(decoded):
                    rendered = json.dumps(_format_placeholder(decoded), indent=2)
                elif isinstance(decoded, (dict, list)):
                    rendered = json.dumps(decoded, indent=2)
                else:
                    rendered = _safe_repr(decoded)

                backrefs: list[dict[str, object]] = []
                for (process_key, client_ref), history in self.manager.get_all_object_histories().items():
                    for snapshot in history:
                        if snapshot.get("cid") == object_ref:
                            backrefs.append({
                                "process_key": process_key,
                                "client_ref": client_ref,
                                "role": snapshot.get("role"),
                                "method_name": snapshot.get("method_name"),
                                "call_id": snapshot.get("call_id"),
                                "timestamp": snapshot.get("timestamp"),
                            })
                backrefs.sort(key=lambda item: float(item.get("timestamp") or 0), reverse=True)

                backref_rows = "".join(
                    "<tr>"
                    f"<td class='mono'>{html.escape(_format_ts(item.get('timestamp')))}</td>"
                    f"<td class='mono'>{html.escape(str(item.get('process_key') or ''))}</td>"
                    f"<td class='mono'>{html.escape(str(item.get('client_ref') or ''))}</td>"
                    f"<td>{html.escape(str(item.get('role') or ''))}</td>"
                    f"<td class='mono'>{html.escape(str(item.get('method_name') or ''))}</td>"
                    f"<td class='mono'>{html.escape(str(item.get('call_id') or ''))}</td>"
                    f"<td><a class='row-link' href='/object/{quote(_object_ref(item.get('process_key'), item.get('client_ref')), safe='')}'>"
                    f"{html.escape(_object_ref(item.get('process_key'), item.get('client_ref')))}</a></td>"
                    "</tr>"
                    for item in backrefs
                )
                backref_table = (
                    "<table>"
                    "<thead><tr>"
                    "<th>Timestamp</th>"
                    "<th>Process</th>"
                    "<th>Client Ref</th>"
                    "<th>Role</th>"
                    "<th>Method</th>"
                    "<th>Call</th>"
                    "<th></th>"
                    "</tr></thead>"
                    "<tbody>"
                    + backref_rows
                    + "</tbody></table>"
                ) if backrefs else "<div class='empty-state'>No references recorded for this CID.</div>"

                template = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
  <title>Object {cid}</title>
  <style>
    body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
    .back-link {{ display: inline-block; margin-bottom: 20px; color: #1976D2; text-decoration: none; }}
    .back-link:hover {{ text-decoration: underline; }}
    .panel {{ background: white; border: 1px solid #ddd; border-radius: 10px; padding: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.06); margin-bottom: 16px; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; white-space: pre-wrap; word-break: break-word; }}
    pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #ddd; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.06); }}
    thead th {{ text-align: left; background: #fafafa; border-bottom: 1px solid #eee; padding: 12px 10px; font-size: 0.9em; color: #444; }}
    tbody td {{ padding: 10px; border-bottom: 1px solid #f0f0f0; vertical-align: top; font-size: 0.92em; color: #222; }}
    tbody tr:hover {{ background: #f7fbff; }}
    .row-link {{ color: #1976D2; text-decoration: none; font-weight: 600; }}
    .row-link:hover {{ text-decoration: underline; }}
    .empty-state {{ text-align: center; padding: 20px; color: #666; font-style: italic; }}
  </style>
</head>
<body>
  <div class=\"container\">
    <a href=\"/objects\" class=\"back-link\">← Back to Objects</a>
    <h1>Object CID</h1>
    <div class=\"panel\">
      <div class=\"mono\">{cid}</div>
      <div class=\"mono\">Size: {size_bytes} bytes</div>
      <div class=\"mono\">Stored: {stored_at}</div>
    </div>
    <div class=\"panel\">
      <h2>Decoded</h2>
      <pre class=\"mono\">{decoded}</pre>
    </div>
    <div class=\"panel\">
      <h2>Referenced By</h2>
      {backrefs}
    </div>
  </div>
</body>
</html>""".format(
                    cid=html.escape(object_ref),
                    size_bytes=html.escape(str(meta.get("size_bytes") or 0)),
                    stored_at=html.escape(_format_ts(meta.get("created_at"))),
                    decoded=html.escape(rendered),
                    backrefs=backref_table,
                )
                return template

            process_key, client_ref = parse_ref(object_ref)
            histories: dict[str, list[dict[str, object]]] = {}
            if process_key:
                histories[process_key] = self.manager.get_object_history(process_key, client_ref)
            else:
                histories = self.manager.get_object_histories_by_ref(client_ref)

            function_matches: list[tuple[str, dict[str, object]]] = []
            for name, meta in self.manager.get_function_metadata().items():
                if meta.get("client_ref") == client_ref:
                    function_matches.append((name, meta))

            first_seen_link = ""
            first_seen = _find_first_seen_call(histories)
            if first_seen:
                first_process, first_call_id = first_seen
                link = _call_tree_link(first_process, first_call_id)
                first_seen_link = (
                    "<div class='panel'>"
                    "<h2>First Seen</h2>"
                    f"<a class='row-link' href='{link}'>View first reference in call tree</a>"
                    "</div>"
                )

            snapshot_sections: list[str] = []
            for proc, history in histories.items():
                if not history:
                    continue
                row_lines: list[str] = []
                for item in history:
                    link = ""
                    if item.get("cid"):
                        link = (
                            "<a class='row-link' href='/object/"
                            f"{quote(str(item.get('cid')), safe='')}'>View</a>"
                        )
                    row_lines.append(
                        "<tr>"
                        f"<td class='mono'>{html.escape(_format_ts(item.get('timestamp')))}</td>"
                        f"<td>{html.escape(str(item.get('role') or ''))}</td>"
                        f"<td class='mono'>{html.escape(str(item.get('method_name') or ''))}</td>"
                        f"<td class='mono'>{html.escape(str(item.get('call_id') or ''))}</td>"
                        f"<td class='mono'>{html.escape(str(item.get('cid') or ''))}</td>"
                        f"<td>{html.escape(_pretty_text(item.get('pretty')))}</td>"
                        f"<td>{link}</td>"
                        "</tr>"
                    )
                rows_html = "".join(row_lines)
                snapshot_sections.append(
                    "<div class='panel'>"
                    f"<h2>Snapshots ({html.escape(str(proc))})</h2>"
                    "<table>"
                    "<thead><tr>"
                    "<th>Timestamp</th>"
                    "<th>Role</th>"
                    "<th>Method</th>"
                    "<th>Call</th>"
                    "<th>CID</th>"
                    "<th>Summary</th>"
                    "<th></th>"
                    "</tr></thead>"
                    "<tbody>"
                    + rows_html
                    + "</tbody></table>"
                    "</div>"
                )

            functions_html = ""
            if function_matches:
                rows = "".join(
                    "<tr>"
                    f"<td class='mono'>{html.escape(name)}</td>"
                    f"<td>{html.escape(str(meta.get('summary') or meta.get('object_name') or meta.get('object_path') or ''))}</td>"
                    f"<td class='mono'>{html.escape(str(meta.get('last_process_key') or ''))}</td>"
                    "</tr>"
                    for name, meta in function_matches
                )
                functions_html = (
                    "<div class='panel'>"
                    "<h2>Registered Functions</h2>"
                    "<table>"
                    "<thead><tr>"
                    "<th>Function</th>"
                    "<th>Summary</th>"
                    "<th>Last Process</th>"
                    "</tr></thead>"
                    "<tbody>"
                    + rows
                    + "</tbody></table>"
                    "</div>"
                )

            if not snapshot_sections and not functions_html:
                snapshot_sections = ["<div class='panel'><div class='empty-state'>No snapshots recorded for this ref.</div></div>"]

            template = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
  <title>Object {ref}</title>
  <style>
    body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
    .back-link {{ display: inline-block; margin-bottom: 20px; color: #1976D2; text-decoration: none; }}
    .back-link:hover {{ text-decoration: underline; }}
    .panel {{ background: white; border: 1px solid #ddd; border-radius: 10px; padding: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.06); margin-bottom: 16px; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; white-space: pre-wrap; word-break: break-word; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #ddd; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.06); }}
    thead th {{ text-align: left; background: #fafafa; border-bottom: 1px solid #eee; padding: 12px 10px; font-size: 0.9em; color: #444; }}
    tbody td {{ padding: 10px; border-bottom: 1px solid #f0f0f0; vertical-align: top; font-size: 0.92em; color: #222; }}
    tbody tr:hover {{ background: #f7fbff; }}
    .row-link {{ color: #1976D2; text-decoration: none; font-weight: 600; }}
    .row-link:hover {{ text-decoration: underline; }}
    .empty-state {{ text-align: center; padding: 20px; color: #666; font-style: italic; }}
  </style>
</head>
<body>
  <div class=\"container\">
    <a href=\"/objects\" class=\"back-link\">← Back to Objects</a>
    <h1>Object Ref</h1>
    <div class=\"panel\">
      <div class=\"mono\">{ref}</div>
    </div>
    {first_seen}
    {functions}
    {snapshots}
  </div>
</body>
</html>""".format(
                ref=html.escape(object_ref),
                first_seen=first_seen_link,
                functions=functions_html,
                snapshots="".join(snapshot_sections),
            )
            return template

        @self.app.route('/repls', methods=['GET'])
        def repls_page():
            template = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>REPL Sessions</title>
  <style>
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
    .container { max-width: 1200px; margin: 0 auto; }
    h1 { color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }
    .back-link { display: inline-block; margin-bottom: 20px; color: #1976D2; text-decoration: none; }
    .back-link:hover { text-decoration: underline; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
    .toolbar input, .toolbar select { padding: 8px; border-radius: 6px; border: 1px solid #ccc; }
    table { width: 100%; border-collapse: collapse; background: white; border: 1px solid #ddd; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.06); }
    thead th { text-align: left; background: #fafafa; border-bottom: 1px solid #eee; padding: 12px 10px; font-size: 0.9em; color: #444; }
    tbody td { padding: 10px; border-bottom: 1px solid #f0f0f0; vertical-align: top; font-size: 0.92em; color: #222; }
    tbody tr:hover { background: #f7fbff; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    .row-link { color: #1976D2; text-decoration: none; font-weight: 600; }
    .row-link:hover { text-decoration: underline; }
    .badge { padding: 2px 6px; border-radius: 6px; font-size: 0.75em; font-weight: 700; }
    .badge-active { background: #e8f5e9; color: #2E7D32; }
    .badge-closed { background: #ffebee; color: #C62828; }
    .empty-state { text-align: center; padding: 20px; color: #666; font-style: italic; }
  </style>
</head>
<body>
  <div class="container">
    <a href="/" class="back-link">← Back to Breakpoints</a>
    <h1>REPL Sessions</h1>
    <div class="toolbar">
      <input id="searchInput" type="text" placeholder="Search sessions..." />
      <select id="statusFilter">
        <option value="">All</option>
        <option value="active">Active</option>
        <option value="closed">Closed</option>
      </select>
      <input id="fromInput" type="text" placeholder="From timestamp" />
      <input id="toInput" type="text" placeholder="To timestamp" />
      <button id="applyFilters">Apply</button>
    </div>
    <div id="sessionsTable"></div>
  </div>
  <script>
    async function loadSessions() {
      const params = new URLSearchParams();
      const search = document.getElementById('searchInput').value.trim();
      const status = document.getElementById('statusFilter').value;
      const from = document.getElementById('fromInput').value.trim();
      const to = document.getElementById('toInput').value.trim();
      if (search) params.set('search', search);
      if (status) params.set('status', status);
      if (from) params.set('from', from);
      if (to) params.set('to', to);
      const response = await fetch(`/api/repl/sessions?${params.toString()}`);
      const data = await response.json();
      const sessions = data.sessions || [];
      const container = document.getElementById('sessionsTable');
      if (!sessions.length) {
        container.innerHTML = '<div class="empty-state">No REPL sessions found.</div>';
        return;
      }
      const rows = sessions.map(session => {
        const status = session.closed_at ? 'Closed' : 'Active';
        const badgeClass = session.closed_at ? 'badge-closed' : 'badge-active';
        const started = session.started_at ? new Date(session.started_at * 1000).toLocaleString() : '—';
        const closed = session.closed_at ? new Date(session.closed_at * 1000).toLocaleString() : '—';
        const transcriptCount = Array.isArray(session.transcript) ? session.transcript.length : 0;
        const callstackLink = session.pause_id ? `<a class="row-link" href="/callstack/${encodeURIComponent(session.pause_id)}">Call stack</a>` : '—';
        return `
          <tr>
            <td class="mono"><a class="row-link" href="/repl/${encodeURIComponent(session.session_id)}">${session.session_id}</a></td>
            <td>${session.function_name || '—'}</td>
            <td><span class="badge ${badgeClass}">${status}</span></td>
            <td class="mono">${started}</td>
            <td class="mono">${closed}</td>
            <td class="mono">${transcriptCount}</td>
            <td>${callstackLink}</td>
          </tr>
        `;
      }).join('');
      container.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Session ID</th>
              <th>Function</th>
              <th>Status</th>
              <th>Started</th>
              <th>Closed</th>
              <th>Entries</th>
              <th></th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    }

    document.getElementById('applyFilters').addEventListener('click', loadSessions);
    window.addEventListener('load', loadSessions);
  </script>
</body>
</html>"""
            return template

        @self.app.route('/repl/<session_id>', methods=['GET'])
        def repl_page(session_id: str):
            template = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>REPL Session</title>
  <style>
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
    .container { max-width: 1000px; margin: 0 auto; }
    h1 { color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }
    .back-link { display: inline-block; margin-bottom: 20px; color: #1976D2; text-decoration: none; }
    .back-link:hover { text-decoration: underline; }
    .panel { background: white; border: 1px solid #ddd; border-radius: 10px; padding: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.06); margin-bottom: 16px; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; white-space: pre-wrap; word-break: break-word; }
    .entry { border-bottom: 1px solid #eee; padding: 8px 0; }
    .entry:last-child { border-bottom: none; }
    .input { color: #1565C0; }
    .output { color: #222; }
    .error { color: #C62828; }
    textarea { width: 100%; min-height: 100px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; padding: 10px; border-radius: 8px; border: 1px solid #ccc; }
    button { padding: 8px 14px; border: none; border-radius: 6px; background: #1565C0; color: white; cursor: pointer; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
  </style>
</head>
<body>
  <div class="container">
    <a href="/repls" class="back-link">← Back to REPL Sessions</a>
    <h1>REPL Session</h1>
    <div style="margin-bottom: 10px;"><a class="row-link" href="/repl-help">REPL Help</a></div>
    <div id="meta" class="panel"></div>
    <div id="transcript" class="panel"></div>
    <div id="inputPanel" class="panel">
      <textarea id="exprInput" placeholder="Enter Python expression..."></textarea>
      <div style="margin-top:10px;">
        <button id="submitBtn">Run</button>
      </div>
    </div>
  </div>
  <script>
    const sessionId = @@SESSION_ID_JSON@@;
    let sessionClosed = false;

    function renderMeta(session) {
      const started = session.started_at ? new Date(session.started_at * 1000).toLocaleString() : '—';
      const closed = session.closed_at ? new Date(session.closed_at * 1000).toLocaleString() : '—';
      const status = session.closed_at ? 'Closed' : 'Active';
      const callstackLink = session.pause_id ? `<a href="/callstack/${encodeURIComponent(session.pause_id)}">Call stack</a>` : '';
      const callTreeLink = session.process_key ? `<a href="/call-tree/${encodeURIComponent(session.process_key)}">Call tree</a>` : '';
      const prettyArgs = Array.isArray(session.pretty_args) ? session.pretty_args : [];
      const prettyKwargs = session.pretty_kwargs || {};
      const params = [];
      prettyArgs.forEach((value, idx) => {
        params.push(`[${idx}] ${JSON.stringify(value)}`);
      });
      Object.entries(prettyKwargs).forEach(([key, value]) => {
        params.push(`${key}=${JSON.stringify(value)}`);
      });
      const paramsHtml = params.length
        ? `<div><strong>Parameters:</strong><div class="mono" style="margin-top:6px;">${params.join('<br>')}</div></div>`
        : '<div><strong>Parameters:</strong> —</div>';
      document.getElementById('meta').innerHTML = `
        <div><strong>Session:</strong> <span class="mono">${session.session_id}</span></div>
        <div><strong>Function:</strong> ${session.function_name || '—'}</div>
        <div><strong>Status:</strong> ${status}</div>
        <div><strong>Started:</strong> ${started}</div>
        <div><strong>Closed:</strong> ${closed}</div>
        ${paramsHtml}
        <div style="margin-top:8px;">${callstackLink} ${callTreeLink}</div>
      `;
    }

    function renderTranscript(entries) {
      const container = document.getElementById('transcript');
      if (!entries.length) {
        container.innerHTML = '<div class="mono">No transcript entries yet.</div>';
        return;
      }
      container.innerHTML = entries.map(entry => {
        const output = entry.is_error ? `<div class="mono error">${entry.output || ''}</div>` : `
          ${entry.stdout ? `<div class="mono output">${entry.stdout}</div>` : ''}
          ${entry.output ? `<div class="mono output">>>> ${entry.output}</div>` : ''}
        `;
        const cidLink = entry.result_cid ? `<div><a href="/object/${encodeURIComponent(entry.result_cid)}">result cid</a></div>` : '';
        return `
          <div class="entry">
            <div class="mono input">>>> ${entry.input}</div>
            ${output}
            ${cidLink}
          </div>
        `;
      }).join('');
      container.scrollTop = container.scrollHeight;
    }

    async function loadSession() {
      const response = await fetch(`/api/repl/${encodeURIComponent(sessionId)}`);
      if (!response.ok) {
        document.getElementById('meta').innerHTML = '<div class="mono">Session not found.</div>';
        document.getElementById('inputPanel').style.display = 'none';
        return;
      }
      const data = await response.json();
      const session = data.session;
      sessionClosed = Boolean(session.closed_at);
      renderMeta(session);
      renderTranscript(session.transcript || []);
      document.getElementById('submitBtn').disabled = sessionClosed;
      if (sessionClosed) {
        document.getElementById('exprInput').disabled = true;
      }
    }

    async function submitExpr() {
      const input = document.getElementById('exprInput');
      const expr = input.value.trim();
      if (!expr || sessionClosed) return;
      document.getElementById('submitBtn').disabled = true;
      const response = await fetch(`/api/repl/${encodeURIComponent(sessionId)}/eval`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expr })
      });
      document.getElementById('submitBtn').disabled = false;
      if (response.status === 409) {
        sessionClosed = true;
        document.getElementById('submitBtn').disabled = true;
        document.getElementById('exprInput').disabled = true;
        const container = document.getElementById('transcript');
        const entry = document.createElement('div');
        entry.className = 'entry';
        entry.innerHTML = `
          <div class="mono input">>>> ${expr}</div>
          <div class="mono error">Breakpoint resumed — command not executed.</div>
        `;
        container.appendChild(entry);
        container.scrollTop = container.scrollHeight;
        input.value = '';
        return;
      }
      input.value = '';
      await loadSession();
    }

    document.getElementById('submitBtn').addEventListener('click', submitExpr);
    setInterval(loadSession, 2000);
    loadSession();
  </script>
</body>
</html>"""
            return template.replace("@@SESSION_ID_JSON@@", json.dumps(session_id))

        @self.app.route('/repl-help', methods=['GET'])
        def repl_help_page():
            template = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>REPL Help</title>
  <style>
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
    .container { max-width: 900px; margin: 0 auto; }
    h1 { color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }
    .back-link { display: inline-block; margin-bottom: 20px; color: #1976D2; text-decoration: none; }
    .back-link:hover { text-decoration: underline; }
    .panel { background: white; border: 1px solid #ddd; border-radius: 10px; padding: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.06); margin-bottom: 16px; }
    pre { background: #f8f8f8; padding: 12px; border-radius: 8px; overflow-x: auto; }
  </style>
</head>
<body>
  <div class="container">
    <a href="/repls" class="back-link">← Back to REPL Sessions</a>
    <h1>REPL Help</h1>
    <div class="panel">
      <h2>Examples</h2>
      <pre>x + 1\nprint(x)\nmy_list.append(42)\nimport math\nmath.sqrt(9)\n\ndef foo(a):\n    return a * 2\n\nfoo(3)</pre>
      <p>Multi-line input: use Shift+Enter in the text area to add new lines, then click Run.</p>
    </div>
  </div>
</body>
</html>"""
            return template

        @self.app.route('/call-tree', methods=['GET'])
        def call_tree_index():
            """List processes with recorded calls."""
            records = self.manager.get_call_records()
            summaries: dict[str, dict[str, object]] = {}
            for record in records:
                process_key = record["process_key"]
                process_pid = record["process_pid"]
                process_start_time = record["process_start_time"]
                page_url = record.get("page_url")
                started_at = record.get("started_at") or 0
                completed_at = record.get("completed_at") or started_at

                summary = summaries.get(process_key)
                if summary is None:
                    summary = {
                        "process_key": process_key,
                        "process_pid": process_pid,
                        "process_start_time": process_start_time,
                        "page_url": page_url,
                        "call_count": 0,
                        "first_call": started_at,
                        "last_call": completed_at,
                    }
                    summaries[process_key] = summary
                elif page_url and not summary.get("page_url"):
                    summary["page_url"] = page_url

                summary["call_count"] = int(summary.get("call_count", 0)) + 1
                summary["first_call"] = min(
                    float(summary.get("first_call", started_at) or started_at),
                    float(started_at or 0),
                )
                summary["last_call"] = max(
                    float(summary.get("last_call", completed_at) or completed_at),
                    float(completed_at or 0),
                )

            processes = sorted(
                summaries.values(),
                key=lambda item: float(item.get("process_start_time") or 0),
            )

            rows: list[str] = []
            for item in processes:
                process_key = str(item.get("process_key"))
                pid = item.get("process_pid", "unknown")
                page_url = item.get("page_url")
                start_time = item.get("process_start_time")
                start_text = _format_ts(start_time)
                first_call = _format_ts(item.get("first_call"))
                last_call = _format_ts(item.get("last_call"))
                call_count = item.get("call_count", 0)
                link = f"/call-tree/{quote(process_key, safe='')}"
                process_label = str(pid)
                if pid == 0 and page_url:
                    process_label = f"JS {page_url}"
                rows.append(
                    "<tr>"
                    f"<td class='mono'>{html.escape(start_text)}</td>"
                    f"<td class='mono'>{html.escape(process_label)}</td>"
                    f"<td class='mono'>{call_count}</td>"
                    f"<td class='mono'>{html.escape(first_call)}</td>"
                    f"<td class='mono'>{html.escape(last_call)}</td>"
                    f"<td><a class='row-link' href='{link}'>View call tree</a></td>"
                    "</tr>"
                )

            empty_state = "<div class='empty-state'>No processes recorded yet.</div>"
            table_html = (
                "<table>"
                "<thead><tr>"
                "<th>Process Start</th>"
                "<th>Process</th>"
                "<th>Calls</th>"
                "<th>First Call</th>"
                "<th>Last Call</th>"
                "<th></th>"
                "</tr></thead>"
                "<tbody>"
                + "".join(rows)
                + "</tbody></table>"
            ) if rows else empty_state

            template = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Call Trees</title>
  <style>
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
    .container { max-width: 1200px; margin: 0 auto; }
    h1 { color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }
    .back-link { display: inline-block; margin-bottom: 20px; color: #1976D2; text-decoration: none; }
    .back-link:hover { text-decoration: underline; }
    table { width: 100%; border-collapse: collapse; background: white; border: 1px solid #ddd; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.06); }
    thead th { text-align: left; background: #fafafa; border-bottom: 1px solid #eee; padding: 12px 10px; font-size: 0.9em; color: #444; }
    tbody td { padding: 10px; border-bottom: 1px solid #f0f0f0; vertical-align: top; font-size: 0.92em; color: #222; }
    tbody tr:hover { background: #f7fbff; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.92em; white-space: pre-wrap; word-break: break-word; }
    .row-link { color: #1976D2; text-decoration: none; font-weight: 600; }
    .row-link:hover { text-decoration: underline; }
    .empty-state { text-align: center; padding: 40px; color: #666; font-style: italic; }
  </style>
</head>
<body>
  <div class="container">
    <a href="/" class="back-link">← Back to Breakpoints</a>
    <h1>Call Trees</h1>
    <p>Recorded processes ordered by start time.</p>
    @@TABLE_HTML@@
  </div>
</body>
</html>"""

            return template.replace("@@TABLE_HTML@@", table_html)

        @self.app.route('/call-tree/<process_key>', methods=['GET'])
        def call_tree_detail(process_key: str):
            """Show call tree for a specific process."""
            records = [
                record for record in self.manager.get_call_records()
                if record.get("process_key") == process_key
            ]
            if not records:
                return (
                    "<h1>Call tree not found.</h1>"
                    "<p>No calls recorded for this process.</p>"
                ), 404

            nodes: list[dict[str, object]] = []
            stack_signatures: dict[str, tuple[tuple[object, object, object], ...]] = {}
            function_metadata = self.manager.get_function_metadata()

            for idx, record in enumerate(records):
                call_id = record.get("call_id") or f"call-{idx}"
                call_site = record.get("call_site") or {}
                stack_trace = _normalize_stack_trace(call_site)
                started_at = call_site.get("timestamp") or record.get("started_at") or 0
                completed_at = record.get("completed_at") or started_at or 0
                duration = None
                if started_at and completed_at:
                    try:
                        duration = max(0.0, float(completed_at) - float(started_at))
                    except Exception:
                        duration = None

                node = {
                    "id": str(call_id),
                    "method_name": record.get("method_name"),
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "duration": duration,
                    "status": record.get("status"),
                    "process_key": record.get("process_key"),
                    "target": record.get("target"),
                    "pretty_target": record.get("pretty_target"),
                    "args": record.get("args", []),
                    "kwargs": record.get("kwargs", {}),
                    "pretty_args": record.get("pretty_args", []),
                    "pretty_kwargs": record.get("pretty_kwargs", {}),
                    "pretty_result": record.get("pretty_result"),
                    "exception": record.get("exception"),
                    "result_cid": record.get("result_cid"),
                    "result_client_ref": record.get("result_client_ref"),
                    "exception_cid": record.get("exception_cid"),
                    "exception_client_ref": record.get("exception_client_ref"),
                    "signature": record.get("signature"),
                    "call_site": call_site,
                    "stack_trace": stack_trace,
                    "repl_sessions": record.get("repl_sessions", []) or [],
                }
                if record.get("method_name") == "with_debug.register":
                    pretty_result = record.get("pretty_result")
                    if isinstance(pretty_result, dict):
                        function_name = pretty_result.get("function_name")
                        if function_name in function_metadata:
                            meta = function_metadata.get(function_name, {})
                            client_ref = meta.get("client_ref")
                            if client_ref is not None:
                                node["registered_target_ref"] = _object_ref(
                                    record.get("process_key"), client_ref
                                )
                nodes.append(node)
                stack_signatures[str(call_id)] = _stack_signature(stack_trace)

            nodes_by_id = {node["id"]: node for node in nodes}  # type: ignore[index]
            def _compute_parent_by_id(match_fn) -> dict[str, str | None]:
                parent_by_id: dict[str, str | None] = {node["id"]: None for node in nodes}  # type: ignore[index]
                for node in nodes:
                    node_id = node["id"]  # type: ignore[index]
                    signature = stack_signatures.get(node_id, ())
                    if not signature:
                        continue
                    parent_id = None
                    parent_len = -1
                    for other in nodes:
                        other_id = other["id"]  # type: ignore[index]
                        if other_id == node_id:
                            continue
                        other_sig = stack_signatures.get(other_id, ())
                        if not other_sig:
                            continue
                        if len(other_sig) >= len(signature):
                            continue
                        if match_fn(signature, other_sig) and len(other_sig) > parent_len:
                            parent_id = other_id
                            parent_len = len(other_sig)
                    parent_by_id[node_id] = parent_id
                return parent_by_id

            def _count_parents(parent_by_id: dict[str, str | None]) -> int:
                return sum(1 for parent_id in parent_by_id.values() if parent_id)

            parent_by_suffix = _compute_parent_by_id(
                lambda signature, other_sig: signature[-len(other_sig):] == other_sig
            )
            parent_by_prefix = _compute_parent_by_id(
                lambda signature, other_sig: signature[:len(other_sig)] == other_sig
            )
            parent_by_id = (
                parent_by_prefix
                if _count_parents(parent_by_prefix) > _count_parents(parent_by_suffix)
                else parent_by_suffix
            )

            children_by_id: dict[str, list[str]] = {node["id"]: [] for node in nodes}  # type: ignore[index]
            for child_id, parent_id in parent_by_id.items():
                if parent_id:
                    children_by_id.setdefault(parent_id, []).append(child_id)

            def _node_time(node_id: str) -> float:
                node = nodes_by_id.get(node_id)
                if not node:
                    return 0
                started = node.get("started_at") or 0
                completed = node.get("completed_at") or 0
                try:
                    return float(started) or float(completed) or 0
                except Exception:
                    return 0

            for key, children in children_by_id.items():
                children.sort(key=_node_time)

            roots = [node_id for node_id, parent_id in parent_by_id.items() if parent_id is None]
            roots.sort(key=_node_time)

            timeline = [node["id"] for node in sorted(nodes, key=lambda n: _node_time(n["id"]))]  # type: ignore[index]

            process_info = {
                "process_key": process_key,
                "process_pid": records[0].get("process_pid"),
                "process_start_time": records[0].get("process_start_time"),
                "page_url": records[0].get("page_url"),
                "call_count": len(records),
            }

            data = {
                "process": process_info,
                "nodes": nodes,
                "children": children_by_id,
                "roots": roots,
                "timeline": timeline,
                "parent_by_id": parent_by_id,
            }

            template = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Call Tree</title>
  <style>
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
    .container { max-width: 1400px; margin: 0 auto; }
    h1 { color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }
    .back-link { display: inline-block; margin-bottom: 20px; color: #1976D2; text-decoration: none; }
    .back-link:hover { text-decoration: underline; }
    .toolbar { display: flex; align-items: center; gap: 12px; margin: 12px 0 20px; flex-wrap: wrap; }
    .timeline-btn { border: 1px solid #ccc; background: white; border-radius: 8px; padding: 6px 10px; cursor: pointer; font-weight: 600; }
    .timeline-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    .timeline { flex: 1; min-width: 240px; }
    .timeline-info { font-size: 0.9em; color: #555; }
    .layout { display: grid; grid-template-columns: minmax(260px, 1.1fr) minmax(320px, 1.5fr); gap: 16px; }
    .panel { background: white; border: 1px solid #ddd; border-radius: 10px; padding: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.06); }
    .panel h2 { margin-top: 0; font-size: 1.05em; color: #333; }
    .tree-node { margin: 6px 0; }
    .tree-row { display: flex; align-items: center; gap: 8px; padding: 4px 6px; border-radius: 6px; }
    .tree-row.selected { background: #e3f2fd; }
    .tree-row:hover { background: #f5f9ff; }
    .tree-toggle { border: none; background: transparent; cursor: pointer; font-size: 14px; width: 18px; }
    .tree-toggle.empty { visibility: hidden; }
    .tree-label { font-weight: 600; color: #1976D2; cursor: pointer; background: none; border: none; padding: 0; }
    .tree-time { margin-left: auto; font-size: 0.85em; color: #666; }
    .repl-badge { background: #e3f2fd; color: #1565C0; font-size: 0.75em; padding: 2px 6px; border-radius: 999px; font-weight: 700; }
    .tree-children { margin-left: 18px; border-left: 1px dashed #e0e0e0; padding-left: 10px; }
    .tree-collapsed > .tree-children { display: none; }
    .detail-item { margin: 10px 0; }
    .detail-label { font-weight: 700; color: #444; margin-bottom: 4px; }
    .detail-value { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; white-space: pre-wrap; word-break: break-word; color: #222; background: #f8f8f8; padding: 8px; border-radius: 8px; }
    .payload-row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 8px; }
    .payload-key { font-weight: 700; color: #333; min-width: 80px; }
    .payload-value { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; background: #f8f8f8; padding: 6px 8px; border-radius: 6px; white-space: pre-wrap; word-break: break-word; }
    .object-links { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 4px; }
    .object-link { color: #1976D2; text-decoration: none; font-weight: 600; }
    .object-link:hover { text-decoration: underline; }
    .stack-frame { padding: 6px 8px; border-radius: 6px; margin-bottom: 6px; background: #f9fafb; border: 1px solid #eee; }
    .stack-frame-link { color: #1976D2; text-decoration: none; font-weight: 600; }
    .stack-frame-link:hover { text-decoration: underline; }
    .empty-state { text-align: center; padding: 40px; color: #666; font-style: italic; }
    @media (max-width: 900px) {
      .layout { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="container">
    <a href="/call-tree" class="back-link">← Back to Call Trees</a>
    <h1>Call Tree</h1>
    <div class="toolbar">
      <button id="prevNode" class="timeline-btn" type="button">←</button>
      <input id="timeline" class="timeline" type="range" min="0" max="0" value="0" step="1">
      <button id="nextNode" class="timeline-btn" type="button">→</button>
      <div id="timelineInfo" class="timeline-info"></div>
    </div>
    <div class="layout">
      <div class="panel">
        <h2>Call Navigation</h2>
        <div id="tree" class="tree"></div>
      </div>
      <div class="panel">
        <h2>Selected Call Details</h2>
        <div id="details"></div>
      </div>
    </div>
  </div>

  <script>
    const data = @@DATA_JSON@@;
    const nodesById = new Map();
    const childrenById = data.children || {};
    const roots = data.roots || [];
    const timeline = data.timeline || [];
    const parentById = data.parent_by_id || {};
    const timelineIndexById = new Map();
    const nodeRowById = new Map();
    const nodeContainerById = new Map();

    data.nodes.forEach((node) => { nodesById.set(node.id, node); });
    timeline.forEach((id, idx) => timelineIndexById.set(id, idx));

    const params = new URLSearchParams(window.location.search);
    const selectedParam = params.get('selected');
    const fallbackSelected = timeline[0] || roots[0] || null;
    const initialSelected = selectedParam && nodesById.has(selectedParam) ? selectedParam : fallbackSelected;
    const state = { selectedId: initialSelected, collapsed: new Set() };

    function formatTs(ts) {
      if (!ts) return 'Unknown';
      try { return new Date(ts * 1000).toLocaleString(); } catch (e) { return 'Unknown'; }
    }

    function formatDuration(seconds) {
      if (seconds === null || seconds === undefined) return 'Unknown';
      return `${seconds.toFixed(3)}s`;
    }

    function formatPretty(value) {
      if (value && typeof value === 'object' && value.__cideldill_placeholder__) {
        return value.summary || '<Unpicklable>';
      }
      if (value && typeof value === 'object') {
        try { return JSON.stringify(value, null, 2); } catch (e) { return '[object]'; }
      }
      return String(value);
    }

    function escapeHtml(text) {
      return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function renderPretty(value) {
      return escapeHtml(formatPretty(value));
    }

    function renderObjectLinks(item, processKey) {
      if (!item || typeof item !== 'object') return '';
      const links = [];
      if (item.cid) {
        links.push(`<a class="object-link" href="/object/${encodeURIComponent(item.cid)}">cid</a>`);
      }
      if (item.client_ref !== undefined && item.client_ref !== null && processKey) {
        const ref = `ref:${processKey}:${item.client_ref}`;
        links.push(`<a class="object-link" href="/object/${encodeURIComponent(ref)}">ref ${item.client_ref}</a>`);
      }
      if (!links.length) return '';
      return `<div class="object-links">${links.join(' ')}</div>`;
    }

    function updateTimelineControls() {
      const slider = document.getElementById('timeline');
      slider.max = Math.max(0, timeline.length - 1);
      const idx = timelineIndexById.get(state.selectedId) || 0;
      slider.value = String(idx);
      const hasTimeline = timeline.length > 0;
      slider.disabled = !hasTimeline;
      document.getElementById('prevNode').disabled = !hasTimeline || idx <= 0;
      document.getElementById('nextNode').disabled = !hasTimeline || idx >= timeline.length - 1;

      const node = nodesById.get(state.selectedId);
      const info = document.getElementById('timelineInfo');
      if (!node) {
        info.textContent = '';
        return;
      }
      info.textContent = `${formatTs(node.started_at)} → ${formatTs(node.completed_at)}`;
    }

    function isAncestor(ancestorId, nodeId) {
      let current = parentById[nodeId];
      while (current) {
        if (current === ancestorId) return true;
        current = parentById[current];
      }
      return false;
    }

    function expandAncestors(nodeId) {
      let current = parentById[nodeId];
      while (current) {
        state.collapsed.delete(current);
        current = parentById[current];
      }
    }

    function setSelected(nodeId, opts = {}) {
      if (!nodeId) return;
      state.selectedId = nodeId;
      expandAncestors(nodeId);
      updateTreeSelection();
      updateDetails();
      updateTimelineControls();
      if (!opts.skipScroll) {
        const row = nodeRowById.get(nodeId);
        if (row) row.scrollIntoView({ block: 'nearest' });
      }
    }

    function updateTreeSelection() {
      nodeRowById.forEach((row, id) => {
        row.classList.toggle('selected', id === state.selectedId);
      });
      nodeContainerById.forEach((container, id) => {
        const isCollapsed = state.collapsed.has(id);
        container.parentElement.classList.toggle('tree-collapsed', isCollapsed);
      });
    }

    function updateDetails() {
      const node = nodesById.get(state.selectedId);
      const details = document.getElementById('details');
      if (!node) {
        details.innerHTML = '<div class="empty-state">No call selected.</div>';
        return;
      }
      const processKey = node.process_key || '';
      const stackTrace = node.stack_trace || [];
      const stackHtml = stackTrace.length
        ? stackTrace.map((frame, idx) => {
            const label = `${frame.function || 'unknown'} (${frame.filename || 'unknown'}:${frame.lineno || '?'})`;
            const labelHtml = escapeHtml(label);
            const frameUrl = processKey && node.id
              ? `/frame/call/${encodeURIComponent(processKey)}/${encodeURIComponent(node.id)}/${encodeURIComponent(idx)}`
              : '';
            const labelBlock = frameUrl
              ? `<a class="stack-frame-link" href="${frameUrl}">${labelHtml}</a>`
              : labelHtml;
            const codeBlock = frame.code_context ? `<div>${escapeHtml(frame.code_context)}</div>` : '';
            return `
              <div class="stack-frame">
                <div>${labelBlock}</div>
                ${codeBlock}
              </div>
            `;
          }).join('')
        : '<div class="empty-state">No stack trace recorded.</div>';

      const replSessions = Array.isArray(node.repl_sessions) ? node.repl_sessions : [];
      const replHtml = replSessions.length
        ? `
          <div class="detail-item">
            <div class="detail-label">REPL Sessions</div>
            <div class="detail-value">
              ${replSessions.map(id => `<a class="object-link" href="/repl/${encodeURIComponent(id)}">${escapeHtml(id)}</a>`).join('<br>')}
            </div>
          </div>
        `
        : '';

      const targetHtml = node.target ? `
        <div class="detail-item">
          <div class="detail-label">Target</div>
          <div class="payload-value">${renderPretty(node.pretty_target)}</div>
          ${renderObjectLinks(node.target, processKey)}
        </div>
      ` : '';

      const argsItems = Array.isArray(node.args) ? node.args : [];
      const prettyArgs = Array.isArray(node.pretty_args) ? node.pretty_args : [];
      const argsSource = argsItems.length ? argsItems : prettyArgs;
      const argsHtml = argsSource.length
        ? argsSource.map((item, idx) => {
            const pretty = idx < prettyArgs.length ? prettyArgs[idx] : item;
            return `
              <div class="payload-row">
                <div class="payload-key">[${idx}]</div>
                <div class="payload-value">${renderPretty(pretty)}</div>
                ${renderObjectLinks(item, processKey)}
              </div>
            `;
          }).join('')
        : '<div class="empty-state">No arguments recorded.</div>';

      const kwargsEntries = Object.entries(node.kwargs || {});
      const prettyKwargs = node.pretty_kwargs || {};
      const kwargsSource = kwargsEntries.length ? kwargsEntries : Object.entries(prettyKwargs);
      const kwargsHtml = kwargsSource.length
        ? kwargsSource.map(([key, item]) => {
            const pretty = Object.prototype.hasOwnProperty.call(prettyKwargs, key)
              ? prettyKwargs[key]
              : item;
            return `
              <div class="payload-row">
                <div class="payload-key">${escapeHtml(key)}</div>
                <div class="payload-value">${renderPretty(pretty)}</div>
                ${renderObjectLinks(item, processKey)}
              </div>
            `;
          }).join('')
        : '<div class="empty-state">No keyword arguments recorded.</div>';

      let resultLinks = '';
      if (node.result_cid) {
        resultLinks += `<a class="object-link" href="/object/${encodeURIComponent(node.result_cid)}">cid</a>`;
      }
      if (node.result_client_ref !== undefined && node.result_client_ref !== null && processKey) {
        const ref = `ref:${processKey}:${node.result_client_ref}`;
        resultLinks += ` <a class="object-link" href="/object/${encodeURIComponent(ref)}">ref ${node.result_client_ref}</a>`;
      }
      if (resultLinks) {
        resultLinks = `<div class="object-links">${resultLinks}</div>`;
      }

      let exceptionLinks = '';
      if (node.exception_cid) {
        exceptionLinks += `<a class="object-link" href="/object/${encodeURIComponent(node.exception_cid)}">cid</a>`;
      }
      if (node.exception_client_ref !== undefined && node.exception_client_ref !== null && processKey) {
        const ref = `ref:${processKey}:${node.exception_client_ref}`;
        exceptionLinks += ` <a class="object-link" href="/object/${encodeURIComponent(ref)}">ref ${node.exception_client_ref}</a>`;
      }
      if (exceptionLinks) {
        exceptionLinks = `<div class="object-links">${exceptionLinks}</div>`;
      }

      const registeredTargetHtml = node.registered_target_ref ? `
        <div class="detail-item">
          <div class="detail-label">Registered Target</div>
          <div class="detail-value">
            <a class="object-link" href="/object/${encodeURIComponent(node.registered_target_ref)}">
              ${escapeHtml(node.registered_target_ref)}
            </a>
          </div>
        </div>
      ` : '';

      details.innerHTML = `
        <div class="detail-item">
          <div class="detail-label">Call</div>
          <div class="detail-value">${escapeHtml(node.method_name || 'unknown')}()</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Status</div>
          <div class="detail-value">${escapeHtml(node.status || 'unknown')}</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Started</div>
          <div class="detail-value">${escapeHtml(formatTs(node.started_at))}</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Completed</div>
          <div class="detail-value">${escapeHtml(formatTs(node.completed_at))}</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Duration</div>
          <div class="detail-value">${escapeHtml(formatDuration(node.duration))}</div>
        </div>
        ${replHtml}
        ${registeredTargetHtml}
        ${targetHtml}
        <div class="detail-item">
          <div class="detail-label">Arguments</div>
          ${argsHtml}
        </div>
        <div class="detail-item">
          <div class="detail-label">Keyword Arguments</div>
          ${kwargsHtml}
        </div>
        ${node.pretty_result !== undefined && node.pretty_result !== null ? `
          <div class="detail-item">
            <div class="detail-label">Result</div>
            <div class="detail-value">${renderPretty(node.pretty_result)}</div>
            ${resultLinks}
          </div>
        ` : ''}
        ${node.exception ? `
          <div class="detail-item">
            <div class="detail-label">Exception</div>
            <div class="detail-value">${renderPretty(node.exception)}</div>
            ${exceptionLinks}
          </div>
        ` : ''}
        <div class="detail-item">
          <div class="detail-label">Stack Trace</div>
          ${stackHtml}
        </div>
      `;
    }

    function renderNode(id) {
      const node = nodesById.get(id);
      const children = childrenById[id] || [];
      const wrapper = document.createElement('div');
      wrapper.className = 'tree-node';

      const row = document.createElement('div');
      row.className = 'tree-row';
      row.dataset.id = id;

      const toggle = document.createElement('button');
      toggle.className = 'tree-toggle' + (children.length ? '' : ' empty');
      toggle.textContent = children.length ? '▾' : '';
      toggle.addEventListener('click', (event) => {
        event.stopPropagation();
        if (!children.length) return;
        if (isAncestor(id, state.selectedId)) return;
        if (state.collapsed.has(id)) {
          state.collapsed.delete(id);
        } else {
          state.collapsed.add(id);
        }
        updateTreeSelection();
      });

      const label = document.createElement('button');
      label.className = 'tree-label';
      label.textContent = node ? `${node.method_name || 'unknown'}()` : id;
      label.addEventListener('click', () => setSelected(id));

      let replBadge = null;
      if (node && Array.isArray(node.repl_sessions) && node.repl_sessions.length) {
        replBadge = document.createElement('span');
        replBadge.className = 'repl-badge';
        replBadge.textContent = 'REPL';
      }

      const time = document.createElement('div');
      time.className = 'tree-time';
      time.textContent = node ? formatTs(node.started_at) : '';

      row.appendChild(toggle);
      row.appendChild(label);
      if (replBadge) {
        row.appendChild(replBadge);
      }
      row.appendChild(time);

      const childrenContainer = document.createElement('div');
      childrenContainer.className = 'tree-children';
      children.forEach((childId) => {
        childrenContainer.appendChild(renderNode(childId));
      });

      wrapper.appendChild(row);
      wrapper.appendChild(childrenContainer);

      nodeRowById.set(id, row);
      nodeContainerById.set(id, childrenContainer);
      return wrapper;
    }

    function renderTree() {
      const tree = document.getElementById('tree');
      tree.innerHTML = '';
      if (!roots.length) {
        tree.innerHTML = '<div class="empty-state">No calls recorded.</div>';
        return;
      }
      roots.forEach((id) => {
        tree.appendChild(renderNode(id));
      });
      updateTreeSelection();
    }

    document.addEventListener('DOMContentLoaded', () => {
      renderTree();
      updateTimelineControls();
      updateDetails();

      const slider = document.getElementById('timeline');
      slider.addEventListener('input', () => {
        const idx = Number(slider.value);
        const id = timeline[idx];
        if (id) setSelected(id, { skipScroll: true });
      });

      document.getElementById('prevNode').addEventListener('click', () => {
        const idx = timelineIndexById.get(state.selectedId) || 0;
        if (idx > 0) setSelected(timeline[idx - 1]);
      });

      document.getElementById('nextNode').addEventListener('click', () => {
        const idx = timelineIndexById.get(state.selectedId) || 0;
        if (idx < timeline.length - 1) setSelected(timeline[idx + 1]);
      });
    });
  </script>
</body>
</html>"""

            return template.replace("@@DATA_JSON@@", json.dumps(data))

        def _render_frame_page(file_path: str, line_no: int):
            if not file_path:
                return jsonify({"error": "file_not_available"}), 404
            if not os.path.isfile(file_path):
                return jsonify({"error": "file_not_found"}), 404

            try:
                line_no = int(line_no) if line_no else 0
            except ValueError:
                line_no = 0

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

        @self.app.route('/callstack/<pause_id>', methods=['GET'])
        def callstack_view(pause_id: str):
            paused = self.manager.get_paused_execution(pause_id)
            if not paused:
                return "<h1>Paused execution not found.</h1>", 404

            call_data = paused.get("call_data", {})
            function_name = (
                call_data.get("method_name")
                or call_data.get("function_name")
                or "unknown"
            )
            call_site = call_data.get("call_site") or {}
            stack_trace = _normalize_stack_trace(call_site)
            process_key = call_data.get("process_key")
            call_id = call_data.get("call_id")
            call_tree_link = ""
            if process_key and call_id:
                call_tree_link = _call_tree_link(str(process_key), str(call_id))

            repl_sessions = self.manager.get_repl_sessions_for_pause(pause_id)
            repl_links = "".join(
                f"<li><a class='row-link' href='/repl/{html.escape(sid)}'>{html.escape(sid)}</a></li>"
                for sid in repl_sessions
            )
            repl_block = (
                "<div class='panel'><h3>REPL Sessions</h3><ul>" + repl_links + "</ul></div>"
                if repl_links
                else ""
            )

            frames_html = ""
            for idx, frame in enumerate(stack_trace):
                filename = html.escape(str(frame.get("filename") or ""))
                lineno = html.escape(str(frame.get("lineno") or ""))
                func = html.escape(str(frame.get("function") or ""))
                ctx = html.escape(str(frame.get("code_context") or ""))
                frame_url = f"/frame/{html.escape(pause_id)}/{idx}"
                frames_html += (
                    "<div class='frame'>"
                    f"<div class='frame-title'><a class='row-link' href='{frame_url}'>"
                    f"{func} ({filename}:{lineno})</a></div>"
                    f"<div class='frame-code'>{ctx}</div>"
                    "</div>"
                )

            call_tree_block = (
                f"<a class='row-link' href='{call_tree_link}'>View Call Tree</a>"
                if call_tree_link
                else ""
            )

            template = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Call Stack</title>
  <style>
    body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }}
    .container {{ max-width: 1000px; margin: 0 auto; }}
    h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
    .back-link {{ display: inline-block; margin-bottom: 20px; color: #1976D2; text-decoration: none; }}
    .back-link:hover {{ text-decoration: underline; }}
    .panel {{ background: white; border: 1px solid #ddd; border-radius: 10px; padding: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.06); margin-bottom: 16px; }}
    .frame {{ padding: 12px; border-bottom: 1px solid #eee; }}
    .frame:last-child {{ border-bottom: none; }}
    .frame-title {{ font-weight: 600; margin-bottom: 4px; }}
    .frame-code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; color: #444; }}
    .row-link {{ color: #1976D2; text-decoration: none; }}
    .row-link:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="container">
    <a href="/" class="back-link">← Back to Breakpoints</a>
    <h1>Call Stack for {html.escape(str(function_name))}</h1>
    <div class="panel">
      {call_tree_block}
    </div>
    {repl_block}
    <div class="panel">
      {frames_html or "<div class='empty-state'>No stack frames recorded.</div>"}
    </div>
  </div>
</body>
</html>"""
            return template

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
            return _render_frame_page(file_path, line_no)

        @self.app.route('/frame/call/<process_key>/<call_id>/<int:frame_index>', methods=['GET'])
        def frame_view_for_call(process_key: str, call_id: str, frame_index: int):
            call_record = None
            for record in self.manager.get_call_records():
                if str(record.get("process_key")) != process_key:
                    continue
                record_id = record.get("call_id") or record.get("id")
                if str(record_id) == call_id:
                    call_record = record
                    break
            if not call_record:
                return jsonify({"error": "call_not_found"}), 404

            call_site = call_record.get("call_site") or {}
            stack_trace = _normalize_stack_trace(call_site)
            if frame_index < 0 or frame_index >= len(stack_trace):
                return jsonify({"error": "frame_not_found"}), 404

            frame = stack_trace[frame_index]
            file_path = frame.get("filename") or ""
            line_no = frame.get("lineno") or 0
            return _render_frame_page(file_path, line_no)

        @self.app.route('/breakpoint/<function_name>/history', methods=['GET'])
        def breakpoint_history_page(function_name: str):
            """Serve the breakpoint execution history page."""
            history = self.manager.get_execution_history(function_name)
            registration_link = ""
            registration = _find_registration_call(function_name)
            if registration:
                process_key, call_id = registration
                link = _call_tree_link(process_key, call_id)
                registration_link = (
                    "<div class='toolbar'>"
                    f"<a class='row-link' href='{link}'>View registration in call tree</a>"
                    "</div>"
                )

            template = """<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='UTF-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1.0'>
  <title>Execution History: @@FUNCTION_NAME@@()</title>
  <style>
    body {{
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        margin: 0;
        padding: 20px;
        background-color: #f5f5f5;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    h1 {{
        color: #333;
        border-bottom: 3px solid #4CAF50;
        padding-bottom: 10px;
    }}
    .back-link {{
        display: inline-block;
        margin-bottom: 20px;
        color: #1976D2;
        text-decoration: none;
    }}
    .back-link:hover {{ text-decoration: underline; }}
    .toolbar {{
        display: flex;
        gap: 12px;
        align-items: center;
        margin: 14px 0 16px;
        flex-wrap: wrap;
    }}
    .search-input {{
        flex: 1;
        min-width: 280px;
        padding: 10px 12px;
        border: 1px solid #ddd;
        border-radius: 8px;
        font-size: 0.95em;
        background: white;
    }}
    .summary {{
        color: #666;
        font-size: 0.9em;
        white-space: nowrap;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        background: white;
        border: 1px solid #ddd;
        border-radius: 10px;
        overflow: hidden;
        box-shadow: 0 2px 4px rgba(0,0,0,0.06);
    }}
    thead th {{
        text-align: left;
        background: #fafafa;
        border-bottom: 1px solid #eee;
        padding: 12px 10px;
        font-size: 0.9em;
        color: #444;
        user-select: none;
        cursor: pointer;
        white-space: nowrap;
    }}
    thead th.sort-active {{
        color: #111;
    }}
    tbody td {{
        padding: 10px;
        border-bottom: 1px solid #f0f0f0;
        vertical-align: top;
        font-size: 0.92em;
        color: #222;
    }}
    tbody tr:hover {{
        background: #f7fbff;
    }}
    .mono {{
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 0.92em;
        white-space: pre-wrap;
        word-break: break-word;
    }}
    .status-pill {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 3px 8px;
        border-radius: 999px;
        font-weight: 700;
        font-size: 0.85em;
        white-space: nowrap;
    }}
    .status-pill.success {{
        background-color: #d4edda;
        color: #155724;
    }}
    .status-pill.error {{
        background-color: #f8d7da;
        color: #721c24;
    }}
    .row-link {{
        color: #1976D2;
        text-decoration: none;
    }}
    .row-link:hover {{
        text-decoration: underline;
    }}
    .empty-state {{
        text-align: center;
        padding: 40px;
        color: #666;
        font-style: italic;
    }}
  </style>
</head>
<body>
  <div class='container'>
    <a href="/" class="back-link">← Back to Breakpoints</a>
    <h1>Execution History: @@FUNCTION_NAME@@()</h1>
    @@REGISTRATION_LINK@@

    <div class="toolbar">
        <input id="searchInput" class="search-input" type="search" placeholder="Filter rows (time, call, result, status)" autocomplete="off" />
        <div id="summary" class="summary"></div>
    </div>

    <table id="historyTable">
        <thead>
            <tr>
                <th data-key="time">Time</th>
                <th data-key="call">Call</th>
                <th data-key="result">Result</th>
                <th data-key="status">Success/Failure</th>
            </tr>
        </thead>
        <tbody id="historyBody"></tbody>
    </table>

    <div id="emptyState" class="empty-state" style="display:none;">No executions recorded yet.</div>
  </div>

  <script>
    const functionName = @@FUNCTION_NAME_JSON@@;
    const history = @@HISTORY_JSON@@;

    const state = {{
      sortKey: 'time',
      sortDir: 'desc',
      filter: ''
    }};

    function escapeHtml(text) {{
      return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }}

    function formatPretty(value) {{
      if (value && typeof value === 'object' && value.__cideldill_placeholder__) {{
        return value.summary || '<Unpicklable>';
      }}
      return String(value);
    }}

    function recordToRowData(record) {{
      const callData = record.call_data || {{}};
      const completedAt = record.completed_at || 0;
      const timeText = completedAt ? new Date(completedAt * 1000).toLocaleString() : 'Unknown';

      const prettyArgs = callData.pretty_args || [];
      const prettyKwargs = callData.pretty_kwargs || {{}};
      const argParts = [];
      try {{
        for (const a of prettyArgs) {{
          argParts.push(formatPretty(a));
        }}
        for (const [k, v] of Object.entries(prettyKwargs)) {{
          argParts.push(`${{k}}=${{formatPretty(v)}}`);
        }}
      }} catch (e) {{
      }}
      const callText = `${{functionName}}(${{argParts.join(', ')}})`;

      const status = String(callData.status || 'unknown');
      const ok = status === 'success';
      const statusText = ok ? 'success' : status;
      const statusIcon = ok ? '✓' : '✗';

      let resultText = '';
      if (callData.exception) {{
        resultText = formatPretty(callData.exception);
      }} else if (callData.pretty_result !== null && callData.pretty_result !== undefined) {{
        resultText = formatPretty(callData.pretty_result);
      }}

      const id = String(record.id || '');
      const detailUrl = `/breakpoint/${{encodeURIComponent(functionName)}}/history/${{encodeURIComponent(id)}}`;

      return {{
        id,
        detailUrl,
        completedAt,
        timeText,
        callText,
        resultText,
        statusText,
        statusIcon,
        ok,
        searchText: `${{timeText}} ${{callText}} ${{resultText}} ${{statusText}}`.toLowerCase(),
      }};
    }}

    function compare(a, b) {{
      const dir = state.sortDir === 'asc' ? 1 : -1;
      const key = state.sortKey;
      if (key === 'time') {{
        return (a.completedAt - b.completedAt) * dir;
      }}
      if (key === 'status') {{
        const av = a.ok ? 1 : 0;
        const bv = b.ok ? 1 : 0;
        if (av !== bv) return (av - bv) * dir;
        return (a.completedAt - b.completedAt) * dir;
      }}
      const av = String(a[key + 'Text'] || a[key] || '').toLowerCase();
      const bv = String(b[key + 'Text'] || b[key] || '').toLowerCase();
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return (a.completedAt - b.completedAt) * dir;
    }}

    function updateHeaderIndicators() {{
      const headers = document.querySelectorAll('thead th');
      headers.forEach((h) => {{
        const isActive = h.dataset.key === state.sortKey;
        h.classList.toggle('sort-active', isActive);
        const base = h.textContent.replace(/\\s*[▲▼]$/, '');
        if (!isActive) {{
          h.textContent = base;
          return;
        }}
        const arrow = state.sortDir === 'asc' ? ' ▲' : ' ▼';
        h.textContent = base + arrow;
      }});
    }}

    function render() {{
      const body = document.getElementById('historyBody');
      const empty = document.getElementById('emptyState');
      const table = document.getElementById('historyTable');
      const summary = document.getElementById('summary');

      if (history.length === 0) {{
        table.style.display = 'none';
        empty.style.display = 'block';
        summary.textContent = '';
        return;
      }}

      const rows = history.map(recordToRowData)
        .filter((r) => !state.filter || r.searchText.includes(state.filter));

      rows.sort(compare);

      table.style.display = 'table';
      empty.style.display = rows.length === 0 ? 'block' : 'none';
      summary.textContent = `${{rows.length}} of ${{history.length}}`;

      body.innerHTML = rows.map((r) => `
        <tr>
          <td class="mono">${{escapeHtml(r.timeText)}}</td>
          <td class="mono"><a class="row-link" href="${{r.detailUrl}}">${{escapeHtml(r.callText)}}</a></td>
          <td class="mono">${{escapeHtml(r.resultText)}}</td>
          <td><span class="status-pill ${{r.ok ? 'success' : 'error'}}">${{r.statusIcon}} ${{escapeHtml(r.statusText)}}</span></td>
        </tr>
      `).join('');
    }

    document.addEventListener('DOMContentLoaded', () => {{
      const search = document.getElementById('searchInput');
      search.addEventListener('input', () => {{
        state.filter = String(search.value || '').trim().toLowerCase();
        render();
      }});

      const headers = document.querySelectorAll('thead th');
      headers.forEach((h) => {{
        h.addEventListener('click', () => {{
          const key = h.dataset.key;
          if (!key) return;
          if (state.sortKey === key) {{
            state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
          }} else {{
            state.sortKey = key;
            state.sortDir = key === 'time' ? 'desc' : 'asc';
          }}
          updateHeaderIndicators();
          render();
        }});
      }});

      updateHeaderIndicators();
      render();
    }});
  </script>
</body>

</html>"""
            # This template previously relied on str.format(), so it contains doubled
            # braces ({{ / }}) to escape literal braces in CSS/JS. Since we no longer
            # use str.format(), normalize them back to single braces before injecting
            # any dynamic data.
            page = template.replace("{{", "{").replace("}}", "}")
            page = (
                page.replace("@@FUNCTION_NAME@@", html.escape(function_name))
                .replace("@@FUNCTION_NAME_JSON@@", json.dumps(function_name))
                .replace("@@HISTORY_JSON@@", json.dumps(history))
                .replace("@@REGISTRATION_LINK@@", registration_link)
            )

            return page

        @self.app.route('/breakpoint/<function_name>/history/<record_id>', methods=['GET'])
        def breakpoint_execution_detail_page(function_name: str, record_id: str):
            record = self.manager.get_execution_record(function_name, record_id)
            if not record:
                return jsonify({"error": "record_not_found"}), 404

            call_data = record.get("call_data", {})
            completed_at = record.get("completed_at", 0)
            status = call_data.get("status", "unknown")
            pretty_args = call_data.get("pretty_args", [])
            pretty_kwargs = call_data.get("pretty_kwargs", {})
            pretty_result = call_data.get("pretty_result")
            exception = call_data.get("exception")
            signature = call_data.get("signature")
            call_site = call_data.get("call_site") or {}
            started_at = call_site.get("timestamp", 0)

            stack_trace = (call_site.get("stack_trace") or []) if isinstance(call_site, dict) else []

            from datetime import datetime

            started_at_text = (
                datetime.fromtimestamp(float(started_at)).strftime("%Y-%m-%d %H:%M:%S")
                if started_at
                else "Unknown"
            )
            completed_at_text = (
                datetime.fromtimestamp(float(completed_at)).strftime("%Y-%m-%d %H:%M:%S")
                if completed_at
                else "Unknown"
            )

            args_block = json.dumps({"args": pretty_args, "kwargs": pretty_kwargs}, indent=2)

            parts: list[str] = []
            try:
                parts.extend([_pretty_text(a) for a in pretty_args])
                parts.extend([f"{k}={_pretty_text(v)}" for k, v in pretty_kwargs.items()])
            except Exception:
                pass
            call_str = f"{function_name}({', '.join(parts)})"

            frame_index = request.args.get("frame", default=0, type=int)
            if frame_index < 0:
                frame_index = 0
            if stack_trace and frame_index >= len(stack_trace):
                frame_index = 0

            highlighted_source = ""
            source_title = "Source not available"
            css_styles = ""
            if stack_trace:
                frame = stack_trace[frame_index]
                file_path = frame.get("filename") or ""
                line_no = frame.get("lineno") or 0
                try:
                    line_no = int(line_no) if line_no else 0
                except ValueError:
                    line_no = 0

                if file_path and os.path.isfile(file_path):
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        source = f.read()
                    source_title = (
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
                    highlighted_source = highlight(source, lexer, formatter)
                    css_styles = formatter.get_style_defs(".source")
                else:
                    source_title = file_path or source_title

            status_ok = status == "success"
            status_class = "success" if status_ok else "error"
            status_icon = "✓" if status_ok else "✗"

            stack_html = ""
            if stack_trace:
                items = []
                for idx, fr in enumerate(stack_trace):
                    file_path = fr.get("filename") or ""
                    lineno = fr.get("lineno") or ""
                    func = fr.get("function") or ""
                    ctx = fr.get("code_context") or ""
                    file_label = os.path.basename(file_path) if file_path else ""
                    label = f"{func} ({file_label}:{lineno})" if file_label else f"{func}"
                    url = (
                        "/breakpoint/"
                        + quote(function_name, safe="")
                        + "/history/"
                        + quote(record_id, safe="")
                        + f"?frame={idx}"
                    )
                    ctx_html = (
                        f"<div style='margin-top:4px;color:#444;'><code>{html.escape(str(ctx))}</code></div>"
                        if ctx
                        else ""
                    )
                    active = "font-weight:700;" if idx == frame_index else ""
                    items.append(
                        "<li style='margin:8px 0;'>"
                        f"<a href='{html.escape(url)}' style='color:#1565c0;text-decoration:none;{active}'>"
                        f"{html.escape(label)}"
                        "</a>"
                        f"{ctx_html}"
                        f"<div style='margin-top:2px;font-size:0.85em;color:#666;'>Frame {idx}</div>"
                        "</li>"
                    )
                stack_html = "<ol style='margin: 8px 0 0 18px; padding: 0;'>" + "".join(items) + "</ol>"
            else:
                stack_html = "<div style='color:#666;font-style:italic;'>No call stack recorded.</div>"

            history_url = "/breakpoint/" + quote(function_name, safe="") + "/history"

            template = """<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='UTF-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1.0'>
  <title>Execution Detail: @@FUNCTION_NAME@@()</title>
  <style>
    body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
    h2 {{ color: #444; margin-top: 26px; }}
    .back-link {{ display: inline-block; margin-bottom: 18px; color: #1976D2; text-decoration: none; }}
    .back-link:hover {{ text-decoration: underline; }}
    .card {{ background: white; border: 1px solid #ddd; border-radius: 10px; padding: 14px 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.06); }}
    .meta {{ display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }}
    .pill {{ display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px; font-weight: 700; font-size: 0.85em; }}
    .pill.success {{ background: #d4edda; color: #155724; }}
    .pill.error {{ background: #f8d7da; color: #721c24; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
    pre {{ margin: 0; }}
    .card pre {{ white-space: pre-wrap; word-break: break-word; }}
    .grid {{ display: grid; grid-template-columns: 1fr; gap: 14px; }}
    .source-container {{ background: white; border: 1px solid #ddd; border-radius: 10px; padding: 12px; overflow-x: auto; }}
    .source {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; font-size: 0.95em; }}
    .source .hll {{ background-color: #fff3cd; display: block; }}
    .source pre {{ margin: 0; white-space: pre; word-break: normal; }}
    .source table {{ width: 100%; border-spacing: 0; }}
    .source td.linenos {{ user-select: none; color: #666; padding-right: 12px; min-width: 5ch; text-align: right; white-space: nowrap; }}
    .source td.linenos pre {{ white-space: pre; }}
    .source td.code {{ width: 100%; }}
    @@CSS_STYLES@@
  </style>
</head>
<body>
  <div class='container'>
    <a href="@@HISTORY_URL@@" class="back-link">← Back to History</a>
    <h1>Execution Detail: @@FUNCTION_NAME@@()</h1>

    <div class="card">
      <div class="meta">
        <div><strong>Started:</strong> <span class="mono">@@STARTED_AT@@</span></div>
        <div><strong>Completed:</strong> <span class="mono">@@COMPLETED_AT@@</span></div>
        <div class="pill @@STATUS_CLASS@@">@@STATUS_ICON@@ @@STATUS@@</div>
        <div><strong>Record:</strong> <span class="mono">@@RECORD_ID@@</span></div>
      </div>
      <div style="margin-top:10px;">
        <strong>Call:</strong>
        <div class="mono" style="margin-top:4px;">@@CALL_STR@@</div>
        @@SIGNATURE_BLOCK@@
      </div>
    </div>

    <div class="grid" style="margin-top:14px;">
      <div class="card">
        <h2 style="margin-top:0;">Parameters</h2>
        <pre class="mono">@@ARGS_BLOCK@@</pre>
      </div>

      <div class="card">
        <h2 style="margin-top:0;">Return Value / Exception</h2>
        <div><strong>Return:</strong></div>
        <pre class="mono">@@PRETTY_RESULT@@</pre>
        <div style="margin-top:10px;"><strong>Exception:</strong></div>
        <pre class="mono">@@EXCEPTION@@</pre>
      </div>

      <div class="card">
        <h2 style="margin-top:0;">Call Stack</h2>
        @@STACK_HTML@@
      </div>

      <div class="card">
        <h2 style="margin-top:0;">Python Source</h2>
        <div style="color:#666; margin-bottom:8px;" class="mono">@@SOURCE_TITLE@@</div>
        <div class="source-container">@@HIGHLIGHTED_SOURCE@@</div>
      </div>
    </div>
  </div>
</body>
</html>"""

            signature_block = (
                f"<div style='margin-top:6px;'><strong>Signature:</strong> <span class='mono'>{html.escape(str(signature))}</span></div>"
                if signature
                else ""
            )

            page = template.replace("{{", "{").replace("}}", "}")
            page = (
                page.replace("@@FUNCTION_NAME@@", html.escape(function_name))
                .replace("@@HISTORY_URL@@", html.escape(history_url))
                .replace("@@STARTED_AT@@", html.escape(started_at_text))
                .replace("@@COMPLETED_AT@@", html.escape(completed_at_text))
                .replace("@@STATUS_CLASS@@", status_class)
                .replace("@@STATUS_ICON@@", status_icon)
                .replace("@@STATUS@@", html.escape(str(status)))
                .replace("@@RECORD_ID@@", html.escape(record_id))
                .replace("@@CALL_STR@@", html.escape(call_str))
                .replace("@@SIGNATURE_BLOCK@@", signature_block)
                .replace("@@ARGS_BLOCK@@", html.escape(args_block))
                .replace(
                    "@@PRETTY_RESULT@@",
                    html.escape(
                        _format_pretty_for_html(pretty_result) if pretty_result is not None else ""
                    ),
                )
                .replace(
                    "@@EXCEPTION@@",
                    html.escape(
                        _format_pretty_for_html(exception) if exception is not None else ""
                    ),
                )
                .replace("@@STACK_HTML@@", stack_html)
                .replace("@@SOURCE_TITLE@@", html.escape(source_title))
                .replace("@@HIGHLIGHTED_SOURCE@@", highlighted_source or "")
                .replace("@@CSS_STYLES@@", css_styles)
            )

            return page

        @self.app.route('/api/breakpoints', methods=['GET'])
        def get_breakpoints():
            """Get list of all breakpoints."""
            return jsonify({
                "breakpoints": self.manager.get_breakpoints(),
                "breakpoint_behaviors": self.manager.get_breakpoint_behaviors(),
                "breakpoint_after_behaviors": self.manager.get_after_breakpoint_behaviors(),
                "breakpoint_replacements": self.manager.get_breakpoint_replacements(),
            })

        @self.app.route('/api/functions', methods=['GET'])
        def get_functions():
            return jsonify({
                "functions": self.manager.get_registered_functions(),
                "function_signatures": self.manager.get_function_signatures(),
                "function_metadata": self.manager.get_function_metadata(),
            })

        @self.app.route('/api/functions', methods=['POST'])
        def register_function():
            data = request.get_json() or {}
            function_name = data.get('function_name')
            signature = data.get('signature')
            function_cid = data.get('function_cid')
            function_data = data.get('function_data')
            function_format = data.get("function_serialization_format", "dill")
            function_client_ref = data.get('function_client_ref')
            metadata: dict[str, Any] | None = None
            if not function_name:
                return jsonify({"error": "function_name required"}), 400
            if function_cid and function_data:
                try:
                    error = store_payload([{
                        "cid": function_cid,
                        "data": function_data,
                        "serialization_format": function_format,
                    }])
                    if error:
                        return jsonify(error), 400
                    try:
                        decoded = self._cid_store.get(function_cid)
                        if decoded is not None:
                            if function_format == "json":
                                try:
                                    value = json.loads(decoded.decode("utf-8"))
                                except Exception:
                                    value = decoded.decode("utf-8", errors="replace")
                            else:
                                value = deserialize(decoded)
                            if _is_placeholder(value):
                                metadata = _format_placeholder(value)
                            else:
                                metadata = {
                                    "summary": _safe_repr(value),
                                    "object_name": getattr(value, "object_name", None),
                                    "object_path": getattr(value, "object_path", None),
                                }
                    except Exception:
                        metadata = None
                except Exception:
                    metadata = None
            if metadata is None and isinstance(data.get("function_metadata"), dict):
                metadata = data.get("function_metadata")
            normalized_ref = _normalize_client_ref(function_client_ref)
            if normalized_ref is not None:
                metadata = dict(metadata or {})
                metadata.setdefault("client_ref", normalized_ref)
                metadata.setdefault("registered_at", time.time())
            self.manager.register_function(function_name, signature=signature, metadata=metadata)
            return jsonify({
                "status": "ok",
                "function_name": function_name,
                "signature": signature,
            })

        @self.app.route('/api/breakpoints', methods=['POST'])
        def add_breakpoint():
            """Add a new breakpoint."""
            data = request.get_json() or {}
            function_name = data.get('function_name')
            signature = data.get('signature')
            behavior = data.get('behavior')
            if not function_name:
                return jsonify({"error": "function_name required"}), 400

            self.manager.add_breakpoint(function_name)
            if behavior in {"stop", "go", "yield"}:
                try:
                    self.manager.set_breakpoint_behavior(function_name, behavior)
                except ValueError:
                    return jsonify({"error": "behavior must be 'stop', 'go', or 'yield'"}), 400
            self.manager.register_function(function_name, signature=signature)
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

        @self.app.route('/api/breakpoints/<function_name>/after_behavior', methods=['POST'])
        def set_after_breakpoint_behavior(function_name):
            """Set after-breakpoint behavior for a single breakpoint."""
            data = request.get_json() or {}
            behavior = data.get('behavior')
            if behavior == 'continue':
                behavior = 'go'
            if behavior not in {'stop', 'go', 'yield'}:
                return jsonify({"error": "behavior must be 'stop', 'go', or 'yield'"}), 400
            try:
                self.manager.set_after_breakpoint_behavior(function_name, behavior)
            except KeyError:
                return jsonify({"error": "breakpoint_not_found"}), 404
            return jsonify({
                "status": "ok",
                "function_name": function_name,
                "behavior": behavior,
            })

        @self.app.route('/api/breakpoints/<function_name>/replacement', methods=['POST'])
        def set_breakpoint_replacement(function_name):
            """Set replacement for a single breakpoint."""
            data = request.get_json() or {}
            replacement = data.get('replacement_function')
            signatures = self.manager.get_function_signatures()
            if replacement and replacement != function_name:
                expected = signatures.get(function_name)
                actual = signatures.get(replacement)
                if not expected or expected != actual:
                    return jsonify({"error": "signature_mismatch"}), 400
            try:
                self.manager.set_breakpoint_replacement(function_name, replacement)
            except KeyError:
                return jsonify({"error": "breakpoint_not_found"}), 404
            return jsonify({
                "status": "ok",
                "function_name": function_name,
                "replacement_function": replacement,
            })

        @self.app.route('/api/breakpoints/<function_name>/history', methods=['GET'])
        def get_breakpoint_history(function_name):
            """Get execution history for a specific breakpoint."""
            limit = request.args.get('limit', type=int)
            history = self.manager.get_execution_history(function_name, limit=limit)
            return jsonify({
                "function_name": function_name,
                "history": history,
            })

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

        @self.app.route('/api/repl/start', methods=['POST'])
        def repl_start():
            data = request.get_json() or {}
            pause_id = data.get("pause_id")
            if not pause_id:
                return jsonify({"error": "missing_pause_id"}), 400
            paused = self.manager.get_paused_execution(pause_id)
            if paused is None:
                if self.manager.get_resume_action(pause_id) is not None:
                    return jsonify({"error": "pause_resumed"}), 409
                return jsonify({"error": "pause_not_found"}), 404
            try:
                session_id = self.manager.start_repl_session(pause_id)
            except KeyError as exc:
                return jsonify({"error": "invalid_pause", "message": str(exc)}), 400
            return jsonify({"session_id": session_id})

        @self.app.route('/api/repl/sessions', methods=['GET'])
        def repl_sessions():
            search = request.args.get("search")
            status = request.args.get("status")
            from_ts = request.args.get("from")
            to_ts = request.args.get("to")
            try:
                from_value = float(from_ts) if from_ts is not None else None
                to_value = float(to_ts) if to_ts is not None else None
            except ValueError:
                return jsonify({"error": "invalid_timestamp"}), 400
            try:
                sessions = self.manager.list_repl_sessions(
                    search=search,
                    status=status,
                    from_ts=from_value,
                    to_ts=to_value,
                )
            except ValueError as exc:
                return jsonify({"error": "invalid_status", "message": str(exc)}), 400
            return jsonify({"sessions": sessions})

        @self.app.route('/api/repl/<session_id>', methods=['GET'])
        def repl_session_detail(session_id: str):
            session = self.manager.get_repl_session(session_id)
            if session is None:
                return jsonify({"error": "session_not_found"}), 404
            return jsonify({"session": session})

        @self.app.route('/api/repl/<session_id>/eval', methods=['POST'])
        def repl_eval(session_id: str):
            data = request.get_json() or {}
            expr = data.get("expr")
            if not isinstance(expr, str) or not expr.strip():
                return jsonify({"error": "missing_expr"}), 400
            session = self.manager.get_repl_session(session_id)
            if session is None:
                return jsonify({"error": "session_not_found"}), 404
            if session.get("closed_at") is not None:
                return jsonify({"error": "session_closed"}), 409
            pause_id = session.get("pause_id")
            if not isinstance(pause_id, str):
                return jsonify({"error": "invalid_pause"}), 400

            eval_id = _queue_repl_eval(pause_id, session_id, expr)
            waiter = self._repl_eval_waiters.get(eval_id)
            if waiter is None:
                return jsonify({"error": "eval_missing"}), 500
            event = waiter.get("event")
            if not isinstance(event, threading.Event):
                return jsonify({"error": "eval_missing"}), 500

            if not event.wait(timeout=self._repl_eval_timeout_s):
                with self._repl_lock:
                    self._repl_eval_waiters.pop(eval_id, None)
                return jsonify({"error": "eval_timeout"}), 504

            with self._repl_lock:
                waiter = self._repl_eval_waiters.pop(eval_id, None)
            if waiter is None:
                return jsonify({"error": "eval_missing"}), 500
            if waiter.get("closed"):
                return jsonify({"error": "session_closed"}), 409
            result = waiter.get("result") or {}
            return jsonify(result)

        @self.app.route('/api/repl/<session_id>/close', methods=['POST'])
        def repl_close(session_id: str):
            try:
                self.manager.close_repl_session(session_id)
            except KeyError:
                return jsonify({"error": "session_not_found"}), 404
            _mark_repl_waiters_closed(session_id=session_id)
            return jsonify({"status": "ok"})

        @self.app.route('/api/poll-repl/<pause_id>', methods=['GET'])
        def poll_repl(pause_id: str):
            request_data = _pop_repl_eval(pause_id)
            if request_data is None:
                return jsonify({"eval_id": None})
            return jsonify(request_data)

        @self.app.route('/api/call/repl-result', methods=['POST'])
        def repl_result():
            data = request.get_json() or {}
            eval_id = data.get("eval_id")
            session_id = data.get("session_id")
            pause_id = data.get("pause_id")
            if not eval_id or not session_id or not pause_id:
                return jsonify({"error": "missing_fields"}), 400

            session = self.manager.get_repl_session(session_id)
            if session is None:
                return jsonify({"error": "session_not_found"}), 404
            if session.get("closed_at") is not None:
                return jsonify({"error": "session_closed"}), 409

            waiter = self._repl_eval_waiters.get(eval_id)
            if waiter is None:
                return jsonify({"error": "eval_not_found"}), 404

            result_cid = data.get("result_cid")
            result_data = data.get("result_data")
            if result_cid and result_data:
                self._cid_store.store(result_cid, base64.b64decode(result_data))

            error = data.get("error")
            stdout = data.get("stdout") or ""
            result_value = data.get("result") or ""
            if error:
                output = str(error)
                is_error = True
            else:
                output = str(result_value)
                is_error = False

            input_expr = waiter.get("expr") if isinstance(waiter, dict) else ""
            try:
                self.manager.append_repl_transcript(
                    session_id,
                    str(input_expr or ""),
                    output,
                    str(stdout),
                    is_error,
                    result_cid=result_cid,
                )
            except RuntimeError:
                return jsonify({"error": "session_closed"}), 409

            with self._repl_lock:
                waiter["result"] = {
                    "output": output,
                    "stdout": stdout,
                    "is_error": is_error,
                    "result_cid": result_cid,
                }
                event = waiter.get("event")
                if isinstance(event, threading.Event):
                    event.set()

            return jsonify({"status": "ok"})

        @self.app.route('/api/call/start', methods=['POST'])
        def call_start():
            """Handle call start from debug client."""
            data = request.get_json() or {}
            method_name = data.get("method_name")
            target = data.get("target", {})
            args = data.get("args", [])
            kwargs = data.get("kwargs", {})
            process_pid = data.get("process_pid")
            process_start_time = data.get("process_start_time")
            process_key = _process_key(process_pid, process_start_time)
            if process_key is None:
                return jsonify({
                    "error": "missing_process_identity",
                    "message": "process_pid and process_start_time are required",
                }), 400

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

            error = store_payload([target] if target else [])
            if error:
                return jsonify(error), 400
            error = store_payload(args)
            if error:
                return jsonify(error), 400
            error = store_payload(kwargs)
            if error:
                return jsonify(error), 400

            call_id = next_call_id()
            preferred_format = data.get("preferred_format", "dill")
            if preferred_format not in {"dill", "json"}:
                return jsonify({
                    "error": "invalid_preferred_format",
                    "message": "preferred_format must be 'dill' or 'json'",
                }), 400
            _record_payload_snapshots(
                process_key=process_key,
                call_id=call_id,
                method_name=method_name,
                target=target if isinstance(target, dict) else None,
                args=args,
                kwargs=kwargs,
            )
            action = {"call_id": call_id, "action": "continue"}

            # Check if we should pause at this breakpoint
            pretty_target = (
                _format_payload_value(target)
                if isinstance(target, dict)
                else None
            )
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
            page_url = data.get("page_url")
            call_data = {
                "method_name": method_name,
                "target": target if isinstance(target, dict) else None,
                "pretty_target": pretty_target,
                "args": args,
                "kwargs": kwargs,
                "pretty_args": pretty_args,
                "pretty_kwargs": pretty_kwargs,
                "signature": data.get("signature"),
                "call_site": data.get("call_site"),
                "page_url": page_url,
                "preferred_format": preferred_format,
                "process_pid": int(process_pid),
                "process_start_time": float(process_start_time),
                "process_key": process_key,
            }
            call_data["call_id"] = call_id
            self.manager.register_call(call_id, call_data)
            if self.manager.should_pause_at_breakpoint(method_name):
                pause_id = self.manager.add_paused_execution(call_data)
                # Store the pause_id with the call for cleanup later
                self.manager.associate_pause_with_call(call_id, pause_id)
                action = {
                    "call_id": call_id,
                    "action": "poll",
                    "poll_interval_ms": 100,
                    "poll_url": f"/api/poll/{pause_id}",
                    "timeout_ms": 60_000,
                }
            else:
                replacement = self.manager.get_breakpoint_replacement(method_name)
                if replacement and self.manager.has_breakpoint(method_name):
                    action = {
                        "call_id": call_id,
                        "action": "replace",
                        "function_name": replacement,
                    }

            return jsonify(action)

        @self.app.route('/api/poll/<pause_id>', methods=['GET'])
        def poll(pause_id):
            """Poll for resume actions.

            Uses get (peek) instead of pop to be idempotent - if the network
            fails after the server responds, the client can retry and still
            get the same resume action. The action is cleaned up when the
            call completes.
            """
            action = self.manager.get_resume_action(pause_id)
            if action is None:
                return jsonify({"status": "waiting"})
            return jsonify({"status": "ready", "action": action})

        @self.app.route('/api/call/complete', methods=['POST'])
        def call_complete():
            """Handle call completion from debug client."""
            data = request.get_json() or {}
            call_id = data.get("call_id")
            status = data.get("status")
            result_data = data.get("result_data")
            result_cid = data.get("result_cid")
            result_format = data.get("result_serialization_format", "dill")
            exception_data = data.get("exception_data")
            exception_cid = data.get("exception_cid")
            exception_format = data.get("exception_serialization_format", "dill")
            result_client_ref = data.get("result_client_ref")
            exception_client_ref = data.get("exception_client_ref")
            completed_at = data.get("timestamp") or time.time()

            if result_data and result_cid:
                error = store_payload([{
                    "cid": result_cid,
                    "data": result_data,
                    "serialization_format": result_format,
                }])
                if error:
                    return jsonify(error), 400
            if exception_data and exception_cid:
                error = store_payload([{
                    "cid": exception_cid,
                    "data": exception_data,
                    "serialization_format": exception_format,
                }])
                if error:
                    return jsonify(error), 400

            call_data = self.manager.pop_call(call_id) if call_id else None
            method_name = ""
            process_key = None
            if call_data:
                call_data.setdefault("call_id", call_id)
                method_name = call_data.get("method_name", "")
                process_key = _process_key(
                    call_data.get("process_pid"),
                    call_data.get("process_start_time"),
                )
            if process_key is None:
                process_key = _process_key(data.get("process_pid"), data.get("process_start_time"))

            if process_key and call_id:
                _record_completion_snapshot(
                    process_key=process_key,
                    call_id=call_id,
                    method_name=method_name,
                    role="result",
                    client_ref=result_client_ref,
                    cid=result_cid,
                    serialization_format=result_format,
                )
                _record_completion_snapshot(
                    process_key=process_key,
                    call_id=call_id,
                    method_name=method_name,
                    role="exception",
                    client_ref=exception_client_ref,
                    cid=exception_cid,
                    serialization_format=exception_format,
                )

            # Record execution history for breakpoints
            if call_data:
                method_name = call_data.get("method_name", "")
                pretty_result = None
                if result_cid:
                    pretty_result = _format_payload_value({
                        "cid": result_cid,
                        "serialization_format": result_format,
                    })
                pretty_exception = None
                if exception_cid:
                    pretty_exception = _format_payload_value({
                        "cid": exception_cid,
                        "serialization_format": exception_format,
                    })

                call_record = dict(call_data)
                call_record["call_id"] = call_id
                call_record["status"] = status
                call_record["completed_at"] = completed_at
                call_record["pretty_result"] = pretty_result
                if result_cid:
                    call_record["result_cid"] = result_cid
                if result_client_ref is not None:
                    call_record["result_client_ref"] = result_client_ref
                if pretty_exception is not None:
                    call_record["exception"] = pretty_exception
                if exception_cid:
                    call_record["exception_cid"] = exception_cid
                if exception_client_ref is not None:
                    call_record["exception_client_ref"] = exception_client_ref
                call_site = call_data.get("call_site") or {}
                call_record["started_at"] = call_site.get("timestamp")
                self.manager.record_call(call_record)

                if self.manager.has_breakpoint(method_name):
                    history_data = dict(call_data)
                    history_data["status"] = status
                    history_data["pretty_result"] = pretty_result
                    if pretty_exception is not None:
                        history_data["exception"] = pretty_exception
                    self.manager.record_execution(method_name, history_data, completed_at=completed_at)

            if (
                status == "success"
                and call_data
                and self.manager.should_pause_after_breakpoint(call_data.get("method_name", ""))
            ):
                pretty_result = None
                if result_cid:
                    pretty_result = _format_payload_value({
                        "cid": result_cid,
                        "serialization_format": result_format,
                    })
                call_data = dict(call_data)
                call_data["pretty_result"] = pretty_result
                pause_id = self.manager.add_paused_execution(call_data)
                return jsonify({
                    "action": "poll",
                    "poll_interval_ms": 100,
                    "poll_url": f"/api/poll/{pause_id}",
                    "timeout_ms": 60_000,
                })

            return jsonify({"status": "ok"})

        @self.app.route('/api/call/event', methods=['POST'])
        def call_event():
            """Record an event for call tree views (non-call diagnostics)."""
            data = request.get_json() or {}
            process_pid = data.get("process_pid")
            process_start_time = data.get("process_start_time")
            process_key = _process_key(process_pid, process_start_time)
            if process_key is None:
                return jsonify({
                    "error": "missing_process_identity",
                    "message": "process_pid and process_start_time are required",
                }), 400

            result_data = data.get("result_data")
            result_cid = data.get("result_cid")
            result_format = data.get("result_serialization_format", "dill")
            exception_data = data.get("exception_data")
            exception_cid = data.get("exception_cid")
            exception_format = data.get("exception_serialization_format", "dill")

            if result_data and result_cid:
                error = store_payload([{
                    "cid": result_cid,
                    "data": result_data,
                    "serialization_format": result_format,
                }])
                if error:
                    return jsonify(error), 400
            if exception_data and exception_cid:
                error = store_payload([{
                    "cid": exception_cid,
                    "data": exception_data,
                    "serialization_format": exception_format,
                }])
                if error:
                    return jsonify(error), 400

            timestamp = data.get("timestamp") or time.time()
            call_site = data.get("call_site") or {}

            pretty_result = None
            if result_cid:
                pretty_result = _format_payload_value({
                    "cid": result_cid,
                    "serialization_format": result_format,
                })
            elif "pretty_result" in data:
                pretty_result = data.get("pretty_result")

            pretty_exception = None
            if exception_cid:
                pretty_exception = _format_payload_value({
                    "cid": exception_cid,
                    "serialization_format": exception_format,
                })
            elif "exception" in data:
                pretty_exception = data.get("exception")

            if (
                data.get("method_name") == "with_debug.register"
                and isinstance(pretty_result, dict)
                and pretty_result.get("function_name")
            ):
                self.manager.update_function_metadata(
                    str(pretty_result.get("function_name")),
                    {"last_process_key": process_key},
                )

            call_record = {
                "call_id": data.get("event_id") or data.get("call_id") or str(uuid.uuid4()),
                "method_name": data.get("method_name") or data.get("event_type") or "event",
                "status": data.get("status") or data.get("event_type") or "event",
                "pretty_args": data.get("pretty_args", []),
                "pretty_kwargs": data.get("pretty_kwargs", {}),
                "signature": data.get("signature"),
                "call_site": call_site,
                "page_url": data.get("page_url"),
                "process_pid": int(process_pid),
                "process_start_time": float(process_start_time),
                "process_key": process_key,
                "started_at": timestamp,
                "completed_at": timestamp,
            }
            if result_cid:
                call_record["result_cid"] = result_cid
            if exception_cid:
                call_record["exception_cid"] = exception_cid
            if pretty_result is not None:
                call_record["pretty_result"] = pretty_result
            if pretty_exception is not None:
                call_record["exception"] = pretty_exception

            self.manager.record_call(call_record)
            return jsonify({"status": "ok"})

        @self.app.route('/api/paused', methods=['GET'])
        def get_paused():
            """Get all paused executions."""
            paused = []
            for item in self.manager.get_paused_executions():
                pause_id = item.get("id")
                repl_sessions = []
                if isinstance(pause_id, str):
                    repl_sessions = self.manager.get_repl_sessions_for_pause(pause_id)
                payload = dict(item)
                payload["repl_sessions"] = repl_sessions
                paused.append(payload)
            return jsonify({
                "paused": paused
            })

        @self.app.route('/api/paused/<pause_id>/continue', methods=['POST'])
        def continue_execution(pause_id):
            """Continue a paused execution."""
            data = request.get_json() or {}
            action = data.get('action', 'continue')
            replacement_function = data.get('replacement_function')
            paused = self.manager.get_paused_execution(pause_id) or {}
            call_data = paused.get("call_data") if isinstance(paused, dict) else {}
            preferred_format = "dill"
            if isinstance(call_data, dict):
                preferred_format = call_data.get("preferred_format", "dill")

            if replacement_function:
                action_dict = {
                    "action": "replace",
                    "function_name": replacement_function,
                }
            else:
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

            if preferred_format not in {"dill", "json"}:
                preferred_format = "dill"
            error = _apply_preferred_format(action_dict, preferred_format)
            if error:
                return jsonify(error), 400

            self.manager.resume_execution(pause_id, action_dict)
            _mark_repl_waiters_closed(pause_id=pause_id)
            return jsonify({"status": "ok", "pause_id": pause_id})

    def start(self) -> None:
        """Start the server (blocking)."""
        self._running = True
        self._server = self._create_server()
        self.actual_port = self._server.server_port
        self._write_port_file()
        print(f"Server running on http://{self.host}:{self.actual_port}")
        try:
            self._server.serve_forever()
        finally:
            self._running = False

    def stop(self) -> None:
        """Stop the server."""
        self._running = False
        if self._server is not None:
            self._server.shutdown()
        try:
            self._cid_store.close()
        except Exception:
            return

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
        return self.actual_port

    def _create_server(self) -> BaseWSGIServer:
        try:
            return make_server(self.host, self.requested_port, self.app, threaded=True)
        except SystemExit:
            print(
                f"Port {self.requested_port} is occupied, finding free port...",
            )
            return make_server(self.host, 0, self.app, threaded=True)
        except OSError as exc:
            if not _is_address_in_use(exc):
                raise
            print(
                f"Port {self.requested_port} is occupied, finding free port...",
            )
            return make_server(self.host, 0, self.app, threaded=True)

    def _write_port_file(self) -> None:
        try:
            write_port_file(self.actual_port, self.port_file)
            print(f"Port written to: {self.port_file}")
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: Could not write port file: {exc}")


def _is_address_in_use(exc: OSError) -> bool:
    if exc.errno in {98, 48}:  # Linux and macOS
        return True
    return "Address already in use" in str(exc)
