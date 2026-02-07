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


def test_js_debug_call_sync_returns_result_and_posts() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCallSync } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

const requests = [];
const responses = new Map();
responses.set('/api/functions', { status: 'ok' });
responses.set('/api/call/start', { call_id: 'c1', action: 'continue' });
responses.set('/api/call/complete', { status: 'ok' });

class FakeXHR {
  open(method, url, async=false) {
    this.method = method;
    this.url = url;
    this.async = async;
  }
  setRequestHeader(key, value) {
    this.header = { key, value };
  }
  send(body) {
    requests.push({ url: this.url, body });
    const path = this.url.replace('http://localhost:5174', '');
    const payload = responses.get(path) || {};
    this.status = 200;
    this.responseText = JSON.stringify(payload);
  }
}

globalThis.XMLHttpRequest = FakeXHR;

withDebug('ON');
const result = debugCallSync(function add(a, b) { return a + b; }, 2, 3);
if (result !== 5) throw new Error('sync result');

const callStart = requests.find(r => r.url.endsWith('/api/call/start'));
const callComplete = requests.find(r => r.url.endsWith('/api/call/complete'));
if (!callStart || !callComplete) throw new Error('missing xhr calls');
"""
    _run_node(js_source, script)


def test_js_debug_call_sync_polls() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCallSync } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

const requests = [];
let pollCount = 0;

class FakeXHR {
  open(method, url, async=false) {
    this.method = method;
    this.url = url;
    this.async = async;
  }
  setRequestHeader() {}
  send(body) {
    requests.push({ url: this.url, body });
    const path = this.url.replace('http://localhost:5174', '');
    if (path === '/api/call/start') {
      this.status = 200;
      this.responseText = JSON.stringify({ call_id: 'c1', action: 'poll', poll_url: '/api/poll/abc', poll_interval_ms: 1 });
      return;
    }
    if (path === '/api/poll/abc') {
      pollCount += 1;
      this.status = 200;
      this.responseText = JSON.stringify({ status: 'ready', action: { action: 'continue' } });
      return;
    }
    if (path === '/api/call/complete') {
      this.status = 200;
      this.responseText = JSON.stringify({ status: 'ok' });
      return;
    }
    if (path === '/api/functions') {
      this.status = 200;
      this.responseText = JSON.stringify({ status: 'ok' });
      return;
    }
    this.status = 200;
    this.responseText = JSON.stringify({});
  }
}

globalThis.XMLHttpRequest = FakeXHR;

withDebug('ON');
const result = debugCallSync(function add(a, b) { return a + b; }, 1, 1);
if (result !== 2) throw new Error('sync poll result');
if (pollCount < 1) throw new Error('poll not called');
"""
    _run_node(js_source, script)


def test_js_log_only_toString_records_call() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug } = mod;

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
const obj = { toString() { return 'obj'; } };
const proxy = withDebug(obj);
const result = proxy.toString();
if (result !== 'obj') throw new Error('log-only return');

// allow fetch microtasks to run
await new Promise((resolve) => setTimeout(resolve, 0));

const callStart = calls.find(c => c.url.endsWith('/api/call/start'));
const callComplete = calls.find(c => c.url.endsWith('/api/call/complete'));
if (!callStart || !callComplete) throw new Error('log-only did not record');
"""
    _run_node(js_source, script)
