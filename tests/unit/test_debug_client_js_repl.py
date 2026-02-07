import os
import subprocess
import tempfile

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


def test_js_repl_evaluates_expression_with_scope() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

const replCalls = [];
let pollReplCount = 0;

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    return { ok: true, json: async () => ({
      call_id: 'c1', action: 'poll', poll_url: '/api/poll/pause1', poll_interval_ms: 1
    }) };
  }
  if (url.endsWith('/api/poll-repl/pause1')) {
    pollReplCount += 1;
    if (pollReplCount === 1) {
      return { ok: true, json: async () => ({
        eval_id: 'e1', session_id: 's1', pause_id: 'pause1', expr: '$this.base + $args[0]'
      }) };
    }
    return { ok: true, json: async () => ({ eval_id: null }) };
  }
  if (url.endsWith('/api/call/repl-result')) {
    replCalls.push(JSON.parse(opts.body));
    return { ok: true, json: async () => ({ status: 'ok' }) };
  }
  if (url.endsWith('/api/poll/pause1')) {
    return { ok: true, json: async () => ({ status: 'ready', action: { action: 'continue' } }) };
  }
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
const target = { base: 2, add(x) { return this.base + x; } };
const wrapped = withDebug(['target', target]);
const result = await wrapped.add(1);
if (result !== 3) throw new Error('bad result');

if (replCalls.length !== 1) throw new Error('missing repl result');
const replPayload = replCalls[0];
if (replPayload.eval_id !== 'e1' || replPayload.session_id !== 's1' || replPayload.pause_id !== 'pause1') {
  throw new Error('repl payload missing ids');
}
if (replPayload.result_serialization_format !== 'json') throw new Error('repl result format');
if (replPayload.result_data !== '3') throw new Error('repl result data');
"""
    _run_node(js_source, script)


def test_js_repl_uses_eval() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    assert "eval(expr)" in js_source


def test_js_repl_handles_multiple_expressions() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

const replCalls = [];
let pollReplCount = 0;

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    return { ok: true, json: async () => ({
      call_id: 'c1', action: 'poll', poll_url: '/api/poll/pause2', poll_interval_ms: 1
    }) };
  }
  if (url.endsWith('/api/poll-repl/pause2')) {
    pollReplCount += 1;
    if (pollReplCount === 1) {
      return { ok: true, json: async () => ({
        eval_id: 'e1', session_id: 's1', pause_id: 'pause2', expr: '1 + 1'
      }) };
    }
    if (pollReplCount === 2) {
      return { ok: true, json: async () => ({
        eval_id: 'e2', session_id: 's1', pause_id: 'pause2', expr: '2 + 2'
      }) };
    }
    return { ok: true, json: async () => ({ eval_id: null }) };
  }
  if (url.endsWith('/api/call/repl-result')) {
    replCalls.push(JSON.parse(opts.body));
    return { ok: true, json: async () => ({ status: 'ok' }) };
  }
  if (url.endsWith('/api/poll/pause2')) {
    return { ok: true, json: async () => ({ status: 'ready', action: { action: 'continue' } }) };
  }
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
const result = await debugCall(function add(a, b) { return a + b; }, 1, 1);
if (result !== 2) throw new Error('bad result');
if (replCalls.length !== 2) throw new Error('expected two repl results');
"""
    _run_node(js_source, script)
