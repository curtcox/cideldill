"""Server-served JavaScript debug client."""

from __future__ import annotations


def render_debug_client_js(server_url: str) -> str:
    safe_url = server_url.rstrip("/")
    return f"""
const SERVER_URL = {safe_url!r};
let _serverUrl = SERVER_URL;
let _enabled = false;

function configure(options = {{}}) {{
  if (options.serverUrl) _serverUrl = options.serverUrl;
}}

function withDebug(commandOrTarget) {{
  if (commandOrTarget === "ON") {{
    _enabled = true;
    return {{ enabled: true, serverUrl: _serverUrl }};
  }}
  if (commandOrTarget === "OFF") {{
    _enabled = false;
    return {{ enabled: false, serverUrl: _serverUrl }};
  }}
  return commandOrTarget;
}}

function withDebugSync(commandOrTarget) {{
  return withDebug(commandOrTarget);
}}

function debugCall(fn, ...args) {{
  if (!_enabled) return Promise.resolve(fn(...args));
  return Promise.resolve(fn(...args));
}}

function debugCallSync(fn, ...args) {{
  return fn(...args);
}}

const cideldill = {{ withDebug, withDebugSync, debugCall, debugCallSync, configure }};

if (typeof window !== "undefined") {{
  window.cideldill = cideldill;
}}

export {{ withDebug, withDebugSync, debugCall, debugCallSync, configure, cideldill }};
export default cideldill;
""".lstrip()
