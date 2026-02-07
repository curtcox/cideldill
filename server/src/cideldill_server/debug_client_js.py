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
const _logOnlyProps = new Set(['valueOf', 'toString', 'toJSON']);
const _logOnlySymbols = new Set([
  Symbol.toPrimitive,
  Symbol.iterator,
  Symbol.asyncIterator,
  Symbol.hasInstance,
  Symbol.toStringTag,
]);

const _SHA512_K = [
  0x428a2f98d728ae22n, 0x7137449123ef65cdn, 0xb5c0fbcfec4d3b2fn, 0xe9b5dba58189dbbcn,
  0x3956c25bf348b538n, 0x59f111f1b605d019n, 0x923f82a4af194f9bn, 0xab1c5ed5da6d8118n,
  0xd807aa98a3030242n, 0x12835b0145706fben, 0x243185be4ee4b28cn, 0x550c7dc3d5ffb4e2n,
  0x72be5d74f27b896fn, 0x80deb1fe3b1696b1n, 0x9bdc06a725c71235n, 0xc19bf174cf692694n,
  0xe49b69c19ef14ad2n, 0xefbe4786384f25e3n, 0x0fc19dc68b8cd5b5n, 0x240ca1cc77ac9c65n,
  0x2de92c6f592b0275n, 0x4a7484aa6ea6e483n, 0x5cb0a9dcbd41fbd4n, 0x76f988da831153b5n,
  0x983e5152ee66dfabn, 0xa831c66d2db43210n, 0xb00327c898fb213fn, 0xbf597fc7beef0ee4n,
  0xc6e00bf33da88fc2n, 0xd5a79147930aa725n, 0x06ca6351e003826fn, 0x142929670a0e6e70n,
  0x27b70a8546d22ffcn, 0x2e1b21385c26c926n, 0x4d2c6dfc5ac42aedn, 0x53380d139d95b3dfn,
  0x650a73548baf63den, 0x766a0abb3c77b2a8n, 0x81c2c92e47edaee6n, 0x92722c851482353bn,
  0xa2bfe8a14cf10364n, 0xa81a664bbc423001n, 0xc24b8b70d0f89791n, 0xc76c51a30654be30n,
  0xd192e819d6ef5218n, 0xd69906245565a910n, 0xf40e35855771202an, 0x106aa07032bbd1b8n,
  0x19a4c116b8d2d0c8n, 0x1e376c085141ab53n, 0x2748774cdf8eeb99n, 0x34b0bcb5e19b48a8n,
  0x391c0cb3c5c95a63n, 0x4ed8aa4ae3418acbn, 0x5b9cca4f7763e373n, 0x682e6ff3d6b2b8a3n,
  0x748f82ee5defb2fcn, 0x78a5636f43172f60n, 0x84c87814a1f0ab72n, 0x8cc702081a6439ecn,
  0x90befffa23631e28n, 0xa4506cebde82bde9n, 0xbef9a3f7b2c67915n, 0xc67178f2e372532bn,
  0xca273eceea26619cn, 0xd186b8c721c0c207n, 0xeada7dd6cde0eb1en, 0xf57d4f7fee6ed178n,
  0x06f067aa72176fban, 0x0a637dc5a2c898a6n, 0x113f9804bef90daen, 0x1b710b35131c471bn,
  0x28db77f523047d84n, 0x32caab7b40c72493n, 0x3c9ebe0a15c9bebcn, 0x431d67c49c100d4cn,
  0x4cc5d4becb3e42b6n, 0x597f299cfc657e2an, 0x5fcb6fab3ad6faecn, 0x6c44198c4a475817n,
];

const _SHA512_H = [
  0x6a09e667f3bcc908n,
  0xbb67ae8584caa73bn,
  0x3c6ef372fe94f82bn,
  0xa54ff53a5f1d36f1n,
  0x510e527fade682d1n,
  0x9b05688c2b3e6c1fn,
  0x1f83d9abfb41bd6bn,
  0x5be0cd19137e2179n,
];

const _MASK_64 = (1n << 64n) - 1n;

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
  const seen = new WeakMap();
  const maxDepth = 50;
  const placeholder = (val, reason) => {{
    let typeName = 'Object';
    try {{
      typeName = val && val.constructor ? val.constructor.name : 'Object';
    }} catch (err) {{
      typeName = 'Object';
    }}
    return {{
      __cideldill_placeholder__: true,
      type_name: typeName,
      repr_text: String(val),
      serialization_error: reason,
      serialization_format: 'json',
    }};
  }};
  return JSON.stringify(value, function (key, val) {{
    if (typeof val === 'bigint') return val.toString();
    if (typeof val === 'function') return `[Function ${{val.name || 'anonymous'}}]`;
    if (typeof val === 'undefined') return null;
    if (typeof val === 'number') {{
      if (Number.isNaN(val)) return 'NaN';
      if (val === Infinity) return 'Infinity';
      if (val === -Infinity) return '-Infinity';
    }}
    if (val instanceof Date) {{
      return val.toISOString();
    }}
    if (val instanceof RegExp) {{
      return val.toString();
    }}
    if (val instanceof Error) {{
      return {{
        name: val.name || 'Error',
        message: val.message || String(val),
        stack: val.stack || null,
      }};
    }}
    if (val instanceof Map) {{
      return Array.from(val.entries());
    }}
    if (val instanceof Set) {{
      return Array.from(val.values());
    }}
    if (ArrayBuffer.isView(val)) {{
      return Array.from(val);
    }}
    if (val instanceof ArrayBuffer) {{
      return Array.from(new Uint8Array(val));
    }}
    if (val && typeof val === 'object') {{
      const parentDepth = seen.get(this) || 0;
      const depth = parentDepth + 1;
      if (depth > maxDepth) {{
        return placeholder(val, `Max depth ${{maxDepth}} exceeded`);
      }}
      if (seen.has(val)) return '[Circular]';
      seen.set(val, depth);
    }}
    return val;
  }});
}}

function _rotr(x, n) {{
  return ((x >> n) | (x << (64n - n))) & _MASK_64;
}}

function _shr(x, n) {{
  return x >> n;
}}

function _ch(x, y, z) {{
  return (x & y) ^ (~x & z);
}}

function _maj(x, y, z) {{
  return (x & y) ^ (x & z) ^ (y & z);
}}

function _sigma0(x) {{
  return _rotr(x, 28n) ^ _rotr(x, 34n) ^ _rotr(x, 39n);
}}

function _sigma1(x) {{
  return _rotr(x, 14n) ^ _rotr(x, 18n) ^ _rotr(x, 41n);
}}

function _gamma0(x) {{
  return _rotr(x, 1n) ^ _rotr(x, 8n) ^ _shr(x, 7n);
}}

function _gamma1(x) {{
  return _rotr(x, 19n) ^ _rotr(x, 61n) ^ _shr(x, 6n);
}}

function _sha512HexSync(message) {{
  const encoder = new TextEncoder();
  const bytes = Array.from(encoder.encode(message));
  const bitLen = BigInt(bytes.length) * 8n;

  bytes.push(0x80);
  while ((bytes.length % 128) !== 112) {{
    bytes.push(0);
  }}

  const lenHi = bitLen >> 64n;
  const lenLo = bitLen & _MASK_64;
  for (let i = 7; i >= 0; i--) {{
    bytes.push(Number((lenHi >> (BigInt(i) * 8n)) & 0xffn));
  }}
  for (let i = 7; i >= 0; i--) {{
    bytes.push(Number((lenLo >> (BigInt(i) * 8n)) & 0xffn));
  }}

  let h = _SHA512_H.slice();
  for (let offset = 0; offset < bytes.length; offset += 128) {{
    const w = new Array(80).fill(0n);
    for (let i = 0; i < 16; i++) {{
      let word = 0n;
      for (let j = 0; j < 8; j++) {{
        word = (word << 8n) | BigInt(bytes[offset + i * 8 + j]);
      }}
      w[i] = word;
    }}
    for (let i = 16; i < 80; i++) {{
      w[i] = (_gamma1(w[i - 2]) + w[i - 7] + _gamma0(w[i - 15]) + w[i - 16]) & _MASK_64;
    }}

    let a = h[0];
    let b = h[1];
    let c = h[2];
    let d = h[3];
    let e = h[4];
    let f = h[5];
    let g = h[6];
    let hh = h[7];

    for (let i = 0; i < 80; i++) {{
      const t1 = (hh + _sigma1(e) + _ch(e, f, g) + _SHA512_K[i] + w[i]) & _MASK_64;
      const t2 = (_sigma0(a) + _maj(a, b, c)) & _MASK_64;
      hh = g;
      g = f;
      f = e;
      e = (d + t1) & _MASK_64;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) & _MASK_64;
    }}

    h = [
      (h[0] + a) & _MASK_64,
      (h[1] + b) & _MASK_64,
      (h[2] + c) & _MASK_64,
      (h[3] + d) & _MASK_64,
      (h[4] + e) & _MASK_64,
      (h[5] + f) & _MASK_64,
      (h[6] + g) & _MASK_64,
      (h[7] + hh) & _MASK_64,
    ];
  }}

  return h.map((x) => x.toString(16).padStart(16, '0')).join('');
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

function _encodeJsonItemSync(value, {{ forceData = false }} = {{}}) {{
  const data = _safeJson(value);
  const cid = _sha512HexSync(data);
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

function _extractParamNames(fn) {{
  if (typeof fn !== 'function') return {{ names: [], restIndex: null }};
  const src = String(fn);
  let params = '';
  const funcMatch = src.match(/^[\\s\\(]*function[^\\(]*\\(([^)]*)\\)/);
  if (funcMatch) {{
    params = funcMatch[1];
  }} else {{
    const arrowParen = src.match(/^\\s*(?:async\\s*)?\\(([^)]*)\\)\\s*=>/);
    if (arrowParen) {{
      params = arrowParen[1];
    }} else {{
      const arrowSingle = src.match(/^\\s*(?:async\\s*)?([A-Za-z_$][A-Za-z0-9_$]*)\\s*=>/);
      if (arrowSingle) {{
        params = arrowSingle[1];
      }}
    }}
  }}
  if (!params) return {{ names: [], restIndex: null }};
  const parts = params.split(',');
  const names = [];
  let restIndex = null;
  for (let i = 0; i < parts.length; i += 1) {{
    let part = parts[i].trim();
    if (!part) continue;
    if (part.startsWith('...')) {{
      part = part.slice(3).trim();
      if (!part) continue;
      if (restIndex === null) restIndex = names.length;
    }}
    if (part.includes('=')) {{
      part = part.split('=')[0].trim();
    }}
    if (part.startsWith('{{') || part.startsWith('[')) continue;
    if (!/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(part)) continue;
    if (part === '$args' || part === '$this' || part === 'expr') continue;
    names.push(part);
    if (restIndex !== null) break;
  }}
  return {{ names, restIndex }};
}}

function _buildReplContext(fn, args, thisArg) {{
  const resolvedArgs = Array.isArray(args) ? args : [];
  const info = _extractParamNames(fn);
  const names = info.names || [];
  const restIndex = info.restIndex;
  const paramValues = [];
  for (let i = 0; i < names.length; i += 1) {{
    if (restIndex !== null && i === restIndex) {{
      paramValues.push(resolvedArgs.slice(i));
      break;
    }}
    paramValues.push(resolvedArgs[i]);
  }}
  return {{
    args: resolvedArgs,
    thisArg,
    paramNames: names,
    paramValues,
  }};
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

function _registerFunctionIfNeededSync(fn, name) {{
  let names = _registeredFunctions.get(fn);
  if (!names) {{
    names = new Set();
    _registeredFunctions.set(fn, names);
  }}
  if (names.has(name)) return;

  const signature = _functionSignature(fn);
  const functionData = {{ name, signature, source: String(fn) }};
  const functionItem = _encodeJsonItemSync(functionData, {{ forceData: true }});
  const payload = {{
    function_name: name,
    signature,
    function_cid: functionItem.cid,
    function_data: functionItem.data,
    function_serialization_format: 'json',
  }};
  _xhrJson('/api/functions', payload);
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

function _xhrJson(path, payload) {{
  const url = _resolveUrl(path);
  const xhr = new XMLHttpRequest();
  xhr.open('POST', url, false);
  if (xhr.setRequestHeader) {{
    xhr.setRequestHeader('Content-Type', 'application/json');
  }}
  xhr.send(JSON.stringify(payload));
  const text = xhr.responseText || '{{}}';
  return JSON.parse(text);
}}

function _xhrGetJson(path) {{
  const url = _resolveUrl(path);
  const xhr = new XMLHttpRequest();
  xhr.open('GET', url, false);
  xhr.send(null);
  const text = xhr.responseText || '{{}}';
  return JSON.parse(text);
}}

function _extractPauseId(pollUrl) {{
  if (!pollUrl) return null;
  const parts = String(pollUrl).split('/');
  return parts[parts.length - 1] || null;
}}

function _evaluateRepl(expr, context) {{
  const args = context && Array.isArray(context.args) ? context.args : [];
  const thisArg = context ? context.thisArg : null;
  const paramNames = context && Array.isArray(context.paramNames) ? context.paramNames : [];
  const paramValues = context && Array.isArray(context.paramValues) ? context.paramValues : [];
  const safeNames = [];
  const safeValues = [];
  for (let i = 0; i < paramNames.length; i += 1) {{
    const name = paramNames[i];
    if (!name || name === '$args' || name === '$this' || name === 'expr') continue;
    if (!/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name)) continue;
    safeNames.push(name);
    safeValues.push(paramValues[i]);
  }}
  let fn;
  try {{
    fn = new Function('$args', '$this', 'expr', ...safeNames, 'return eval(expr);');
  }} catch (err) {{
    fn = new Function('$args', '$this', 'expr', 'return eval(expr);');
    return fn(args, thisArg, String(expr || ''));
  }}
  return fn(args, thisArg, String(expr || ''), ...safeValues);
}}

async function _pollRepl(pauseId, context) {{
  if (!pauseId) return;
  const url = _resolveUrl(`/api/poll-repl/${{pauseId}}`);
  while (true) {{
    const response = await fetch(url, {{ method: 'GET' }});
    const data = await response.json();
    if (!data || !data.eval_id) return;

    let result = null;
    let error = null;
    try {{
      result = _evaluateRepl(data.expr || '', context);
      if (result === undefined) result = null;
    }} catch (err) {{
      error = {{
        name: err && err.name ? err.name : 'Error',
        message: err && err.message ? err.message : String(err),
      }};
    }}

    const payload = {{
      eval_id: data.eval_id,
      session_id: data.session_id,
      pause_id: data.pause_id,
    }};

    if (error) {{
      payload.error = error;
    }} else {{
      const resultItem = await _encodeJsonItem(result, {{ forceData: true }});
      payload.result_cid = resultItem.cid;
      payload.result_data = resultItem.data;
      payload.result_serialization_format = 'json';
    }}

    await _postJson('/api/call/repl-result', payload);
  }}
}}

async function _pollAction(action, replContext) {{
  let current = action;
  while (current && current.action === 'poll') {{
    const pauseId = _extractPauseId(current.poll_url || current.pollUrl || current.pollURL);
    await _pollRepl(pauseId, replContext);
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

function _pollActionSync(action) {{
  let current = action;
  while (current && current.action === 'poll') {{
    const pollData = _xhrGetJson(current.poll_url || current.pollUrl || current.pollURL);
    if (pollData.status === 'ready') {{
      current = pollData.action;
      break;
    }}
  }}
  return current;
}}

async function _executeAction(action, fn, args, kwargs, replContext) {{
  let current = await _pollAction(action, replContext);
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

function _executeActionSync(action, fn, args, kwargs) {{
  let current = _pollActionSync(action);
  if (!current || current.action === 'continue' || !current.action) {{
    return fn(...args, ...(kwargs ? [kwargs] : []));
  }}
  if (current.action === 'modify') {{
    const modifiedArgs = (current.modified_args || []).map(_decodeJsonItem);
    const modifiedKwargs = current.modified_kwargs || {{}};
    return fn(...modifiedArgs, ...(modifiedKwargs ? [modifiedKwargs] : []));
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
      return replacement(...args);
    }}
    return fn(...args);
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

function _sendCallCompleteSync(callId, status, {{ result = null, error = null }} = {{}}) {{
  if (!callId) return null;
  const payload = {{
    call_id: callId,
    status,
  }};
  if (status === 'success') {{
    const resultItem = _encodeJsonItemSync(result, {{ forceData: true }});
    payload.result_cid = resultItem.cid;
    payload.result_data = resultItem.data;
    payload.result_serialization_format = 'json';
  }} else if (status === 'exception') {{
    const errorPayload = {{
      name: error && error.name ? error.name : 'Error',
      message: error && error.message ? error.message : String(error),
    }};
    const errorItem = _encodeJsonItemSync(errorPayload, {{ forceData: true }});
    payload.exception_cid = errorItem.cid;
    payload.exception_data = errorItem.data;
    payload.exception_serialization_format = 'json';
  }}
  return _xhrJson('/api/call/complete', payload);
}}

function _fireAndForget(promise) {{
  if (promise && typeof promise.catch === 'function') {{
    promise.catch(() => {{}});
  }}
}}

function _logOnlyCall(methodName, fn, args) {{
  if (!_enabled) return fn(...args);
  const result = fn(...args);
  const targetItem = _encodeJsonItemSync({{ name: methodName, length: fn.length }}, {{ forceData: true }});
  const argsItems = args.map((value) => _encodeJsonItemSync(value));
  const payload = {{
    method_name: methodName,
    target: targetItem,
    args: argsItems,
    kwargs: {{}},
    call_site: {{ timestamp: _nowSeconds(), page_url: _pageUrl, stack_trace: [] }},
    process_pid: 0,
    process_start_time: _pageLoadTime,
    page_url: _pageUrl,
    preferred_format: 'json',
  }};
  _fireAndForget((async () => {{
    const action = await _postJson('/api/call/start', payload);
    const callId = action.call_id;
    if (callId) {{
      const resultItem = _encodeJsonItemSync(result, {{ forceData: true }});
      await _postJson('/api/call/complete', {{
        call_id: callId,
        status: 'success',
        result_cid: resultItem.cid,
        result_data: resultItem.data,
        result_serialization_format: 'json',
      }});
    }}
  }})());
  return result;
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
  if (commandOrTarget === 'ON' || commandOrTarget === 'OFF') {{
    return withDebug(commandOrTarget);
  }}
  if (Array.isArray(commandOrTarget) && commandOrTarget.length === 2) {{
    return _wrapObjectSync(commandOrTarget[1], commandOrTarget[0]);
  }}
  if (commandOrTarget && typeof commandOrTarget === 'object') {{
    return _wrapObjectSync(commandOrTarget, null);
  }}
  return commandOrTarget;
}}

function _wrapObject(target, alias) {{
  if (!target || typeof target !== 'object') return target;
  return new Proxy(target, {{
    get(obj, prop) {{
      const value = obj[prop];
      if (typeof value !== 'function') return value;
      if (_logOnlyProps.has(prop) || _logOnlySymbols.has(prop)) {{
        return function(...args) {{
          const bound = (...callArgs) => value.apply(obj, callArgs);
          const name = alias ? `${{alias}}.${{String(prop)}}` : String(prop);
          return _logOnlyCall(name, bound, args);
        }};
      }}
      return async function(...args) {{
        const bound = (...callArgs) => value.apply(obj, callArgs);
        const name = alias ? `${{alias}}.${{String(prop)}}` : String(prop);
        return await _debugCallInternal(name, bound, args, obj, value);
      }};
    }}
  }});
}}

function _wrapObjectSync(target, alias) {{
  if (!target || typeof target !== 'object') return target;
  return new Proxy(target, {{
    get(obj, prop) {{
      const value = obj[prop];
      if (typeof value !== 'function') return value;
      return function(...args) {{
        const bound = (...callArgs) => value.apply(obj, callArgs);
        const name = alias ? `${{alias}}.${{String(prop)}}` : String(prop);
        return debugCallSync(name, bound, ...args);
      }};
    }}
  }});
}}

function registerReplacement(name, fn) {{
  _replacementRegistry.set(name, fn);
}}

async function _debugCallInternal(alias, fn, callArgs, thisArg, paramSource = null) {{
  if (!_enabled) {{
    return await fn(...callArgs);
  }}

  if (_pageUrl === null) _pageUrl = _resolvePageUrl();
  if (_pageLoadTime === null) _pageLoadTime = _resolveTimeOriginSeconds();

  const methodName = alias || fn.name || 'anonymous';
  const sourceFn = paramSource || fn;
  await _registerFunctionIfNeeded(sourceFn, methodName);

  const targetItem = await _encodeJsonItem(
    {{ name: methodName, length: sourceFn.length }},
    {{ forceData: true }}
  );
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

  const replContext = _buildReplContext(sourceFn, callArgs, thisArg);
  const action = await _postJson('/api/call/start', payload);
  const callId = action.call_id;
  if (!callId) throw new Error('Missing call_id');

  try {{
    const result = await _executeAction(action, fn, callArgs, {{}}, replContext);
    const postAction = await _sendCallComplete(callId, 'success', {{ result }});
    if (postAction && postAction.action === 'poll') {{
      await _pollAction(postAction, replContext);
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

async function debugCall(nameOrFunc, ...args) {{
  const [alias, fn, callArgs] = _parseDebugCallArgs(nameOrFunc, args);
  return await _debugCallInternal(alias, fn, callArgs, null);
}}

function debugCallSync(nameOrFunc, ...args) {{
  const [alias, fn, callArgs] = _parseDebugCallArgs(nameOrFunc, args);
  if (!_enabled) {{
    return fn(...callArgs);
  }}

  if (_pageUrl === null) _pageUrl = _resolvePageUrl();
  if (_pageLoadTime === null) _pageLoadTime = _resolveTimeOriginSeconds();

  const methodName = alias || fn.name || 'anonymous';
  _registerFunctionIfNeededSync(fn, methodName);

  const targetItem = _encodeJsonItemSync({{ name: methodName, length: fn.length }}, {{ forceData: true }});
  const argsItems = [];
  for (const value of callArgs) {{
    argsItems.push(_encodeJsonItemSync(value));
  }}

  const payload = {{
    method_name: methodName,
    target: targetItem,
    args: argsItems,
    kwargs: {{}},
    call_site: {{ timestamp: _nowSeconds(), page_url: _pageUrl, stack_trace: [] }},
    process_pid: 0,
    process_start_time: _pageLoadTime,
    page_url: _pageUrl,
    preferred_format: 'json',
  }};

  const action = _xhrJson('/api/call/start', payload);
  const callId = action.call_id;
  if (!callId) throw new Error('Missing call_id');

  try {{
    const result = _executeActionSync(action, fn, callArgs, {{}});
    const postAction = _sendCallCompleteSync(callId, 'success', {{ result }});
    if (postAction && postAction.action === 'poll') {{
      _pollActionSync(postAction);
    }}
    return result;
  }} catch (err) {{
    try {{
      _sendCallCompleteSync(callId, 'exception', {{ error: err }});
    }} catch (innerErr) {{
      // swallow secondary failures
    }}
    throw err;
  }}
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
