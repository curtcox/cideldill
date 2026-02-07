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


def test_js_call_start_with_empty_args() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

let callStart = null;

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    callStart = JSON.parse(opts.body);
    return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  }
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
const result = await debugCall(function noArgs() { return 42; });
if (result !== 42) throw new Error('bad result');
if (!callStart) throw new Error('missing call start');
if (!Array.isArray(callStart.args) || callStart.args.length !== 0) throw new Error('args not empty');
"""
    _run_node(js_source, script)


def test_js_call_start_with_large_payload() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

let callStart = null;
const bigValue = 'x'.repeat(10000);

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    callStart = JSON.parse(opts.body);
    return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  }
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
const result = await debugCall(function passthrough(obj) { return obj.payload.length; }, { payload: bigValue });
if (result !== 10000) throw new Error('bad result');
const argData = JSON.parse(callStart.args[0].data);
if (!argData || argData.payload.length !== 10000) throw new Error('payload truncated');
"""
    _run_node(js_source, script)


def test_js_call_start_with_deeply_nested_object() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

let callStart = null;

const deep = {};
let current = deep;
for (let i = 0; i < 60; i += 1) {
  current.child = {};
  current = current.child;
}

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    callStart = JSON.parse(opts.body);
    return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  }
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
const result = await debugCall(function depth(obj) { return obj ? 1 : 0; }, deep);
if (result !== 1) throw new Error('bad result');
if (!callStart || !callStart.args[0].data.includes('serialization_error')) {
  throw new Error('expected serialization placeholder');
}
"""
    _run_node(js_source, script)


def test_js_concurrent_calls_do_not_interfere() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

let callStartCount = 0;
const callCompleteIds = [];

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    callStartCount += 1;
    const callId = callStartCount === 1 ? 'c1' : 'c2';
    return { ok: true, json: async () => ({ call_id: callId, action: 'continue' }) };
  }
  if (url.endsWith('/api/call/complete')) {
    const payload = JSON.parse(opts.body);
    callCompleteIds.push(payload.call_id);
    return { ok: true, json: async () => ({ status: 'ok' }) };
  }
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
const [a, b] = await Promise.all([
  debugCall(function add(a, b) { return a + b; }, 1, 1),
  debugCall(function mul(a, b) { return a * b; }, 2, 3),
]);
if (a !== 2 || b !== 6) throw new Error('bad results');
if (callCompleteIds.sort().join(',') !== 'c1,c2') throw new Error('call ids mixed');
"""
    _run_node(js_source, script)


def test_js_rapid_enable_disable_cycle() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

let callStartCount = 0;

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    callStartCount += 1;
    return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  }
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
withDebug('OFF');
const direct = await debugCall(function add(a, b) { return a + b; }, 1, 2);
if (direct !== 3) throw new Error('bad direct');
if (callStartCount !== 0) throw new Error('call start should not run when off');

withDebug('ON');
const result = await debugCall(function add(a, b) { return a + b; }, 2, 3);
if (result !== 5) throw new Error('bad result');
if (callStartCount !== 1) throw new Error('call start not invoked');
"""
    _run_node(js_source, script)


def test_js_handles_server_500_response() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    return { ok: false, json: async () => ({ message: 'boom' }) };
  }
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
let caught = null;
try {
  await debugCall(function add(a, b) { return a + b; }, 1, 2);
} catch (err) {
  caught = err;
}
if (!caught) throw new Error('expected error');
if (!String(caught.message || caught).includes('boom')) throw new Error('wrong error');
"""
    _run_node(js_source, script)


def test_js_handles_network_timeout() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

globalThis.fetch = async (url, opts) => {
  throw new Error('timeout');
};

withDebug('ON');
let caught = null;
try {
  await debugCall(function add(a, b) { return a + b; }, 1, 2);
} catch (err) {
  caught = err;
}
if (!caught) throw new Error('expected error');
if (!String(caught.message || caught).includes('timeout')) throw new Error('wrong error');
"""
    _run_node(js_source, script)


def test_js_wrapping_null_or_undefined() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug } = mod;

const resultNull = withDebug(null);
if (resultNull !== null) throw new Error('null not preserved');

const resultUndefined = withDebug(undefined);
if (resultUndefined !== undefined) throw new Error('undefined not preserved');
"""
    _run_node(js_source, script)


def test_js_debug_call_with_async_function() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
const result = await debugCall(async function add(a, b) { return a + b; }, 3, 4);
if (result !== 7) throw new Error('bad result');
"""
    _run_node(js_source, script)


def test_js_debug_call_with_generator_function() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
function* gen() { yield 1; }
const result = await debugCall(gen);
if (!result || typeof result.next !== 'function') throw new Error('expected generator');
const step = result.next();
if (step.value !== 1) throw new Error('bad generator result');
"""
    _run_node(js_source, script)


def test_js_proxy_method_returning_promise() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

let callComplete = null;

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  if (url.endsWith('/api/call/complete')) {
    callComplete = JSON.parse(opts.body);
    return { ok: true, json: async () => ({ status: 'ok' }) };
  }
  throw new Error('unexpected url ' + url);
};

const target = {
  async add(a, b) { return a + b; }
};

withDebug('ON');
const proxy = withDebug(['target', target]);
const result = await proxy.add(5, 6);
if (result !== 11) throw new Error('bad result');
if (!callComplete || callComplete.result_data !== '11') throw new Error('call complete missing result');
"""
    _run_node(js_source, script)


def test_json_serialization_of_date_objects() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

let callStart = null;
const date = new Date('2024-01-02T03:04:05.000Z');

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    callStart = JSON.parse(opts.body);
    return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  }
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
await debugCall(function passthrough(value) { return value; }, date);
const parsed = JSON.parse(callStart.args[0].data);
if (parsed !== '2024-01-02T03:04:05.000Z') throw new Error('date not iso');
"""
    _run_node(js_source, script)


def test_json_serialization_of_regexp() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

let callStart = null;
const regex = /abc/i;

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    callStart = JSON.parse(opts.body);
    return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  }
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
await debugCall(function passthrough(value) { return value; }, regex);
const parsed = JSON.parse(callStart.args[0].data);
if (parsed !== '/abc/i') throw new Error('regex not stringified');
"""
    _run_node(js_source, script)


def test_json_serialization_of_error_objects() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

let callStart = null;
const err = new Error('boom');

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    callStart = JSON.parse(opts.body);
    return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  }
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
await debugCall(function passthrough(value) { return value; }, err);
const parsed = JSON.parse(callStart.args[0].data);
if (!parsed || parsed.message !== 'boom') throw new Error('error not serialized');
"""
    _run_node(js_source, script)


def test_json_serialization_of_map_and_set() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

let callStart = null;
const map = new Map([['a', 1], ['b', 2]]);
const set = new Set([1, 2]);

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    callStart = JSON.parse(opts.body);
    return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  }
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
await debugCall(function passthrough(a, b) { return [a, b]; }, map, set);
const parsedMap = JSON.parse(callStart.args[0].data);
const parsedSet = JSON.parse(callStart.args[1].data);
if (!Array.isArray(parsedMap) || parsedMap.length !== 2) throw new Error('map not serialized');
if (!Array.isArray(parsedSet) || parsedSet.length !== 2) throw new Error('set not serialized');
"""
    _run_node(js_source, script)


def test_json_serialization_of_typed_arrays() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

let callStart = null;
const arr = new Uint8Array([1, 2, 3]);

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    callStart = JSON.parse(opts.body);
    return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  }
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
await debugCall(function passthrough(value) { return value; }, arr);
const parsed = JSON.parse(callStart.args[0].data);
if (!Array.isArray(parsed) || parsed.join(',') !== '1,2,3') throw new Error('typed array not serialized');
"""
    _run_node(js_source, script)


def test_json_serialization_of_nan_and_infinity() -> None:
    js_source = render_debug_client_js("http://localhost:5174")
    script = r"""
import { pathToFileURL } from 'node:url';

const mod = await import(pathToFileURL(process.env.DEBUG_JS).href);
const { withDebug, debugCall } = mod;

globalThis.window = { location: { href: 'https://example.com/app' } };
globalThis.performance = { timeOrigin: 1234 };

let callStart = null;
const payload = { a: NaN, b: Infinity, c: -Infinity };

globalThis.fetch = async (url, opts) => {
  if (url.endsWith('/api/functions')) return { ok: true, json: async () => ({ status: 'ok' }) };
  if (url.endsWith('/api/call/start')) {
    callStart = JSON.parse(opts.body);
    return { ok: true, json: async () => ({ call_id: 'c1', action: 'continue' }) };
  }
  if (url.endsWith('/api/call/complete')) return { ok: true, json: async () => ({ status: 'ok' }) };
  throw new Error('unexpected url ' + url);
};

withDebug('ON');
await debugCall(function passthrough(value) { return value; }, payload);
const parsed = JSON.parse(callStart.args[0].data);
if (parsed.a !== 'NaN' || parsed.b !== 'Infinity' || parsed.c !== '-Infinity') throw new Error('nan/inf not serialized');
"""
    _run_node(js_source, script)
