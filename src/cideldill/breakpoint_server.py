"""Web server for interactive breakpoint management.

This module provides a Flask-based web server with REST API endpoints
for managing breakpoints and paused executions through a web UI.
"""

import base64
import html
import json
import logging
import os
import threading
import time
from urllib.parse import quote

from flask import Flask, jsonify, render_template_string, request
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

from cideldill.breakpoint_manager import BreakpointManager
from cideldill.cid_store import CIDStore
from cideldill.serialization import deserialize

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
    </style>
</head>
<body>
    <div class="container">
        <h1>🛑 Interactive Breakpoints</h1>

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
${prettyResult}</div>`;
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
                    ${renderArgs()}
                    ${renderStack()}
                    ${renderResult()}
                    ${renderFunctionChoices()}
                    <div class="actions">
                        <button class="btn btn-go" data-default-function="${escapeHtml(displayName)}"
                                onclick="continueExecution('${paused.id}', this.dataset.defaultFunction)">
                            🟢
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
        port: int = 5000,
        debug_enabled: bool = False,
    ) -> None:
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
        self._debug_enabled = debug_enabled
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

        @self.app.route('/breakpoint/<function_name>/history', methods=['GET'])
        def breakpoint_history_page(function_name: str):
            """Serve the breakpoint execution history page."""
            history = self.manager.get_execution_history(function_name)

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

    function recordToRowData(record) {{
      const callData = record.call_data || {{}};
      const completedAt = record.completed_at || 0;
      const timeText = completedAt ? new Date(completedAt * 1000).toLocaleString() : 'Unknown';

      const prettyArgs = callData.pretty_args || [];
      const prettyKwargs = callData.pretty_kwargs || {{}};
      const argParts = [];
      try {{
        for (const a of prettyArgs) {{
          argParts.push(String(a));
        }}
        for (const [k, v] of Object.entries(prettyKwargs)) {{
          argParts.push(`${{k}}=${{v}}`);
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
        resultText = String(callData.exception);
      }} else if (callData.pretty_result !== null && callData.pretty_result !== undefined) {{
        resultText = String(callData.pretty_result);
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
                parts.extend([str(a) for a in pretty_args])
                parts.extend([f"{k}={v}" for k, v in pretty_kwargs.items()])
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
                    html.escape(str(pretty_result) if pretty_result is not None else ""),
                )
                .replace(
                    "@@EXCEPTION@@",
                    html.escape(str(exception) if exception is not None else ""),
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
            })

        @self.app.route('/api/functions', methods=['POST'])
        def register_function():
            data = request.get_json() or {}
            function_name = data.get('function_name')
            signature = data.get('signature')
            if not function_name:
                return jsonify({"error": "function_name required"}), 400
            self.manager.register_function(function_name, signature=signature)
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
            if not function_name:
                return jsonify({"error": "function_name required"}), 400

            self.manager.add_breakpoint(function_name)
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
            call_data = {
                "method_name": method_name,
                "args": args,
                "kwargs": kwargs,
                "pretty_args": pretty_args,
                "pretty_kwargs": pretty_kwargs,
                "signature": data.get("signature"),
                "call_site": data.get("call_site"),
            }
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
            exception_data = data.get("exception_data")
            exception_cid = data.get("exception_cid")

            if result_data and result_cid:
                self._cid_store.store(result_cid, base64.b64decode(result_data))
            if exception_data and exception_cid:
                self._cid_store.store(exception_cid, base64.b64decode(exception_data))

            call_data = self.manager.pop_call(call_id) if call_id else None

            # Record execution history for breakpoints
            if call_data:
                method_name = call_data.get("method_name", "")
                if self.manager.has_breakpoint(method_name):
                    pretty_result = None
                    if result_cid:
                        pretty_result = _format_payload_value({"cid": result_cid})
                    history_data = dict(call_data)
                    history_data["status"] = status
                    history_data["pretty_result"] = pretty_result
                    if exception_cid:
                        history_data["exception"] = _format_payload_value(
                            {"cid": exception_cid}
                        )
                    self.manager.record_execution(method_name, history_data)

            if (
                status == "success"
                and call_data
                and self.manager.should_pause_after_breakpoint(call_data.get("method_name", ""))
            ):
                pretty_result = None
                if result_cid:
                    pretty_result = _format_payload_value({"cid": result_cid})
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
            replacement_function = data.get('replacement_function')

            if action == 'skip':
                return jsonify({"error": "skip_not_supported"}), 400

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
