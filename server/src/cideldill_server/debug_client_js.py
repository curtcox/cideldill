"""Server-served JavaScript debug client."""

from __future__ import annotations


def render_debug_client_js(server_url: str) -> str:
    safe_url = server_url.rstrip("/")
    return f"""
const SERVER_URL = {safe_url!r};
let _serverUrl = SERVER_URL;
let _enabled = false;
let _pageUrl = null;
let _pageLoadTime = null;
let _clientRefCounter = 0;
const _cidCache = new Set();
const _registeredFunctions = new WeakMap();
const _replacementRegistry = new Map();

function configure(options = {{}}) {{
  if (options.serverUrl) _serverUrl = options.serverUrl;
}}

function _nowSeconds() {{
  return Date.now() / 1000;
}}

function _resolvePageUrl() {{
  if (typeof window !== 'undefined' && window.location && window.location.href) {{
    return window.location.href;
  }}
  if (typeof location !== 'undefined' && location && location.href) {{
    return location.href;
  }}
  return null;
}}

function _resolveTimeOriginSeconds() {{
  if (typeof performance !== 'undefined' && performance && performance.timeOrigin) {{
    return performance.timeOrigin / 1000;
  }}
  return _nowSeconds();
}}

function _nextClientRef() {{
  _clientRefCounter += 1;
  return _clientRefCounter;
}}

function _resolveUrl(path) {{
  if (!path) return _serverUrl;
  if (path.startsWith('http://') || path.startsWith('https://')) return path;
  return `${{_serverUrl}}${{path}}`;
}}

function _sleep(ms) {{
  return new Promise((resolve) => setTimeout(resolve, ms));
}}

function _safeJson(value) {{
  const seen = new WeakSet();
  return JSON.stringify(value, (key, val) => {{
    if (typeof val === 'bigint') return val.toString();
    if (typeof val === 'function') return `[Function ${{val.name || 'anonymous'}}]`;
    if (typeof val === 'undefined') return null;
    if (typeof val === 'number') {{
      if (Number.isNaN(val)) return 'NaN';
      if (val === Infinity) return 'Infinity';
      if (val === -Infinity) return '-Infinity';
    }}
    if (val && typeof val === 'object') {{
      if (seen.has(val)) return '[Circular]';
      seen.add(val);
    }}
    return val;
  }});
}}

async function _sha512Hex(text) {{
  if (!globalThis.crypto || !globalThis.crypto.subtle) {{
    throw new Error('crypto.subtle unavailable');
  }}
  const encoder = new TextEncoder();
  const data = encoder.encode(text);
  const digest = await globalThis.crypto.subtle.digest('SHA-512', data);
  const bytes = Array.from(new Uint8Array(digest));
  return bytes.map((b) => b.toString(16).padStart(2, '0')).join('');
}}

async function _encodeJsonItem(value, {{ forceData = false }} = {{}}) {{
  const data = _safeJson(value);
  const cid = await _sha512Hex(data);
  const item = {{
    cid,
    data,
    serialization_format: 'json',
    client_ref: _nextClientRef(),
  }};
  if (!forceData && _cidCache.has(cid)) {{
    delete item.data;
  }} else {{
    _cidCache.add(cid);
  }}
  return item;
}}

function _decodeJsonItem(item) {{
  if (!item) return null;
  if (item.serialization_format && item.serialization_format !== 'json') return null;
  if (!('data' in item)) return null;
  try {{
    return JSON.parse(item.data);
  }} catch (err) {{
    return null;
  }}
}}

function _parseDebugCallArgs(nameOrFunc, args) {{
  if (typeof nameOrFunc === 'string') {{
    if (!args.length || typeof args[0] !== 'function') {{
      throw new TypeError('debugCall with alias requires a function');
    }}
    return [nameOrFunc, args[0], args.slice(1)];
  }}
  if (typeof nameOrFunc === 'function') {{
    return [null, nameOrFunc, args];
  }}
  throw new TypeError('debugCall expects a function or (alias, function, ...)');
}}

function _functionSignature(fn) {{
  try {{
    return fn.length;
  }} catch (err) {{
    return null;
  }}
}}

async function _registerFunctionIfNeeded(fn, name) {{
  let names = _registeredFunctions.get(fn);
  if (!names) {{
    names = new Set();
    _registeredFunctions.set(fn, names);
  }}
  if (names.has(name)) return;

  const signature = _functionSignature(fn);
  const functionData = {{ name, signature, source: String(fn) }};
  const functionItem = await _encodeJsonItem(functionData, {{ forceData: true }});
  const payload = {{
    function_name: name,
    signature,
    function_cid: functionItem.cid,
    function_data: functionItem.data,
    function_serialization_format: 'json',
  }};
  await _postJson('/api/functions', payload);
  names.add(name);
}}

async function _postJson(path, payload) {{
  const url = _resolveUrl(path);
  const response = await fetch(url, {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(payload),
  }});
  const data = await response.json();
  if (!response.ok) {{
    const message = data && data.message ? data.message : 'Server error';
    throw new Error(message);
  }}
  return data;
}}

async function _pollAction(action) {{
  let current = action;
  while (current && current.action === 'poll') {{
    const pollUrl = _resolveUrl(current.poll_url || current.pollUrl || current.pollURL);
    const pollResponse = await fetch(pollUrl, {{ method: 'GET' }});
    const pollData = await pollResponse.json();
    if (pollData.status === 'ready') {{
      current = pollData.action;
      break;
    }}
    const sleepMs = current.poll_interval_ms || 100;
    await _sleep(sleepMs);
  }}
  return current;
}}

async function _executeAction(action, fn, args, kwargs) {{
  let current = await _pollAction(action);
  if (!current || current.action === 'continue' || !current.action) {{
    return await fn(...args, ...(kwargs ? [kwargs] : []));
  }}
  if (current.action === 'modify') {{
    const modifiedArgs = (current.modified_args || []).map(_decodeJsonItem);
    const modifiedKwargs = current.modified_kwargs || {{}};
    return await fn(...modifiedArgs, ...(modifiedKwargs ? [modifiedKwargs] : []));
  }}
  if (current.action === 'skip') {{
    if (current.fake_result_data && current.fake_result_serialization_format === 'json') {{
      return JSON.parse(current.fake_result_data);
    }}
    if (current.fake_result_data && !current.fake_result_serialization_format) {{
      return JSON.parse(current.fake_result_data);
    }}
    if ('fake_result' in current) return current.fake_result;
    return null;
  }}
  if (current.action === 'replace') {{
    const replacement = _replacementRegistry.get(current.function_name);
    if (replacement && replacement.length === fn.length) {{
      return await replacement(...args);
    }}
    return await fn(...args);
  }}
  if (current.action === 'raise') {{
    const message = current.exception_message || 'Exception';
    throw new Error(message);
  }}
  throw new Error(`Unknown action: ${{current.action}}`);
}}

async function _sendCallComplete(callId, status, {{ result = null, error = null }} = {{}}) {{
  if (!callId) return null;
  const payload = {{
    call_id: callId,
    status,
  }};
  if (status === 'success') {{
    const resultItem = await _encodeJsonItem(result, {{ forceData: true }});
    payload.result_cid = resultItem.cid;
    payload.result_data = resultItem.data;
    payload.result_serialization_format = 'json';
  }} else if (status === 'exception') {{
    const errorPayload = {{
      name: error && error.name ? error.name : 'Error',
      message: error && error.message ? error.message : String(error),
    }};
    const errorItem = await _encodeJsonItem(errorPayload, {{ forceData: true }});
    payload.exception_cid = errorItem.cid;
    payload.exception_data = errorItem.data;
    payload.exception_serialization_format = 'json';
  }}
  return await _postJson('/api/call/complete', payload);
}}

function withDebug(commandOrTarget) {{
  if (commandOrTarget === 'ON') {{
    _enabled = true;
    _pageUrl = _resolvePageUrl();
    _pageLoadTime = _resolveTimeOriginSeconds();
    return {{ enabled: true, serverUrl: _serverUrl }};
  }}
  if (commandOrTarget === 'OFF') {{
    _enabled = false;
    return {{ enabled: false, serverUrl: _serverUrl }};
  }}
  if (Array.isArray(commandOrTarget) && commandOrTarget.length === 2) {{
    return _wrapObject(commandOrTarget[1], commandOrTarget[0]);
  }}
  if (commandOrTarget && typeof commandOrTarget === 'object') {{
    return _wrapObject(commandOrTarget, null);
  }}
  return commandOrTarget;
}}

function withDebugSync(commandOrTarget) {{
  return withDebug(commandOrTarget);
}}

function _wrapObject(target, alias) {{
  if (!target || typeof target !== 'object') return target;
  return new Proxy(target, {{
    get(obj, prop) {{
      const value = obj[prop];
      if (typeof value !== 'function') return value;
      return async function(...args) {{
        const bound = (...callArgs) => value.apply(obj, callArgs);
        const name = alias ? `${{alias}}.${{String(prop)}}` : String(prop);
        return await debugCall(name, bound, ...args);
      }};
    }}
  }});
}}

function registerReplacement(name, fn) {{
  _replacementRegistry.set(name, fn);
}}

async function debugCall(nameOrFunc, ...args) {{
  const [alias, fn, callArgs] = _parseDebugCallArgs(nameOrFunc, args);
  if (!_enabled) {{
    return await fn(...callArgs);
  }}

  if (_pageUrl === null) _pageUrl = _resolvePageUrl();
  if (_pageLoadTime === null) _pageLoadTime = _resolveTimeOriginSeconds();

  const methodName = alias || fn.name || 'anonymous';
  await _registerFunctionIfNeeded(fn, methodName);

  const targetItem = await _encodeJsonItem({{ name: methodName, length: fn.length }}, {{ forceData: true }});
  const argsItems = [];
  for (const value of callArgs) {{
    argsItems.push(await _encodeJsonItem(value));
  }}

  const payload = {{
    method_name: methodName,
    target: targetItem,
    args: argsItems,
    kwargs: {{}},
    call_site: {{
      timestamp: _nowSeconds(),
      page_url: _pageUrl,
      stack_trace: [],
    }},
    process_pid: 0,
    process_start_time: _pageLoadTime,
    page_url: _pageUrl,
    preferred_format: 'json',
  }};

  const action = await _postJson('/api/call/start', payload);
  const callId = action.call_id;
  if (!callId) throw new Error('Missing call_id');

  try {{
    const result = await _executeAction(action, fn, callArgs, {{}});
    const postAction = await _sendCallComplete(callId, 'success', {{ result }});
    if (postAction && postAction.action === 'poll') {{
      await _pollAction(postAction);
    }}
    return result;
  }} catch (err) {{
    try {{
      await _sendCallComplete(callId, 'exception', {{ error: err }});
    }} catch (innerErr) {{
      // swallow secondary failures
    }}
    throw err;
  }}
}}

function debugCallSync(fn, ...args) {{
  return fn(...args);
}}

const cideldill = {{
  withDebug,
  withDebugSync,
  debugCall,
  debugCallSync,
  configure,
  registerReplacement,
}};

if (typeof window !== 'undefined') {{
  window.cideldill = cideldill;
}}

export {{ withDebug, withDebugSync, debugCall, debugCallSync, configure, registerReplacement, cideldill }};
export default cideldill;
""".lstrip()
