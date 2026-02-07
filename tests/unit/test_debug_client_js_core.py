import os
import subprocess
import tempfile

import pytest

from cideldill_server.debug_client_js import render_debug_client_js


def _run_node(js_source: str, script: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        js_path = os.path.join(tmpdir, "debug-client.mjs")
        with open(js_path, "w", encoding="utf-8") as handle:
            handle.write(js_source)

        env = dict(os.environ)
        env["DEBUG_JS"] = js_path
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr or proc.stdout


def test_js_debug_call_sends_call_start_and_complete() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

const calls = [];
globalThis.fetch = async (url, opts) => {
  calls.push({ url, opts });
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
const result = await debugCall(function add(a, b) { return a + b; }, 2, 3);
if (result !== 5) throw new Error('bad result');

const callStart = JSON.parse(calls.find(c => c.url.endsWith('/api/call/start')).opts.body);
if (callStart.preferred_format !== 'json') throw new Error('preferred_format');
if (callStart.process_pid !== 0) throw new Error('process_pid');
if (!callStart.page_url) throw new Error('page_url');
if (!callStart.target || callStart.target.serialization_format !== 'json') throw new Error('target fmt');
if (!Array.isArray(callStart.args) || callStart.args[0].serialization_format !== 'json') throw new Error('args fmt');

const callComplete = JSON.parse(calls.find(c => c.url.endsWith('/api/call/complete')).opts.body);
if (callComplete.result_serialization_format !== 'json') throw new Error('result fmt');
"""
    _run_node(js_source, script)


def test_js_registers_function_once() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

const calls = [];
globalThis.fetch = async (url, opts) => {
  calls.push({ url, opts });
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
function add(a, b) { return a + b; }
await debugCall(add, 1, 2);
await debugCall(add, 2, 3);

const functionCalls = calls.filter(c => c.url.endsWith('/api/functions'));
if (functionCalls.length !== 1) throw new Error('function registration not cached');
"""
    _run_node(js_source, script)


def test_js_modify_action_uses_modified_args() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

const calls = [];
let callStartCount = 0;

globalThis.fetch = async (url, opts) => {
  calls.push({ url, opts });
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    callStartCount += 1;
    return { ok: true, json: async () => ({
      call_id: 'c1',
      action: 'modify',
      modified_args: [
        { cid: 'a', data: '10', serialization_format: 'json' },
        { cid: 'b', data: '5', serialization_format: 'json' }
      ],
      modified_kwargs: {}
    }) };
  }
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
const result = await debugCall(function sub(a, b) { return a - b; }, 1, 2);
if (result !== 5) throw new Error('modify did not apply');
"""
    _run_node(js_source, script)


def test_js_replace_action_calls_replacement() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall, registerReplacement } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

const calls = [];

globalThis.fetch = async (url, opts) => {
  calls.push({ url, opts });
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) return { ok: true, json: async () => ({
    call_id: 'c1', action: 'replace', function_name: 'alt'
  }) };
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
registerReplacement('alt', (a, b) => a * b);
const result = await debugCall(function add(a, b) { return a + b; }, 2, 3);
if (result !== 6) throw new Error('replace failed');
"""
    _run_node(js_source, script)


def test_js_poll_action_is_handled() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

const calls = [];
let pollCount = 0;

globalThis.fetch = async (url, opts) => {
  calls.push({ url, opts });
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) return { ok: true, json: async () => ({
    call_id: 'c1', action: 'poll', poll_url: '/api/poll/abc', poll_interval_ms: 1
  }) };
  if (url.endsWith('/api/poll/abc')) {
    pollCount += 1;
    return { ok: true, json: async () => ({ status: 'ready', action: { action: 'continue' } }) };
  }
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
const result = await debugCall(function add(a, b) { return a + b; }, 1, 1);
if (result !== 2) throw new Error('poll did not continue');
if (pollCount < 1) throw new Error('poll not called');
"""
    _run_node(js_source, script)
