# Browser JavaScript Debug Support

## Goal

Provide browser-side `with_debug` and `debug_call` equivalents so that JavaScript
running in a web page can participate in the same breakpoint/inspection workflow
as the existing Python client. This is **additive** — the Python client is unchanged.

---

## Design Principles

1. **Reuse existing server endpoints** (`/api/call/start`, `/api/call/complete`,
   `/api/poll/<pause_id>`, `/api/functions`, `/api/breakpoints`, `/api/call/event`).
2. **Page URL replaces PID in the UI** — browsers have no OS process ID. The
   page's `window.location.href` is shown as the human-readable process
   identifier. Internally, the server still keys browser processes as
   `(process_pid=0, process_start_time=<timeOrigin>)` for uniqueness.
3. **JSON serialization** — browsers cannot produce dill pickles. A
   `serialization_format` field on every payload tells the server how to
   interpret `data` fields (`"dill"` for existing Python traffic, `"json"` for
   browser traffic).
4. **Server-served JavaScript** — the breakpoint server exposes an endpoint
   that returns the client library JS, so any page can include it with a single
   `<script>` tag.
5. **Minimal server changes** — the server already stores and renders JSON
   "pretty" snapshots; JSON-serialized payloads skip the dill decode step but
   still store raw JSON bytes in the CID store for deduplication.

---

## Architecture Overview

```
┌─────────────────────────────┐          ┌───────────────────────────┐
│   Browser Page              │          │   Breakpoint Server       │
│                             │          │                           │
│  <script src=               │  HTTP    │  /api/debug-client.js     │
│   "/api/debug-client.js"    │◄─────── │  (serves JS library)      │
│  ></script>                 │          │                           │
│                             │          │                           │
│  cideldill.withDebug("ON")  │          │                           │
│  cideldill.withDebug(obj)   │          │                           │
│  cideldill.withDebugSync()  │          │                           │
│  cideldill.debugCall()      │──POST──►│  /api/call/start          │
│  cideldill.debugCallSync()  │──POST──►│  /api/call/complete       │
│                             │◄──GET───│  /api/poll/<id>           │
│                             │──POST──►│  /api/functions            │
│                             │◄──GET───│  /api/poll-repl/<id>      │
│                             │──POST──►│  /api/call/repl-result    │
│  cideldill.registerReplacement()       │                           │
│    (client-side only)       │          │                           │
└─────────────────────────────┘          └───────────────────────────┘
```

---

## Component Design

### 1. JavaScript Client Library (`debug-client.js`)

Served by the breakpoint server at `GET /api/debug-client.js`.

#### 1.1 Global Namespace

The library exposes a single global object `cideldill` (attaches to
`window.cideldill`) with the public API. It also supports ES module export
so it can be loaded via:

```javascript
// Script tag (global via module)
<script type="module" src="http://localhost:5174/api/debug-client.js"></script>

// ES module import
import { withDebug, debugCall, debugCallSync } from 'http://localhost:5174/api/debug-client.js';
```

When served by the breakpoint server, the JS includes an injected
`SERVER_URL` constant set to the server's own origin. If the constant is
missing (e.g., the JS is bundled separately), the client falls back to
auto-detecting from the `<script src>`. `configure({serverUrl})` overrides
both.

#### 1.2 State Management

Mirrors the Python `_DebugState`:

```javascript
// Internal state (not exported)
let _enabled = false;
let _serverUrl = null;    // injected SERVER_URL or auto-detected from script src
let _pageUrl = null;      // window.location.href at enable time
let _pageLoadTime = null; // performance.timeOrigin or Date.now() at enable time
let _clientRefCounter = 0;
let _cidCache = new Map(); // cid -> true (sent to server)
let _registeredFunctions = new Set(); // function keys already registered
```

#### 1.3 Public API

| Function | Signature | Description |
|----------|-----------|-------------|
| `withDebug(command)` | `withDebug("ON" \| "OFF") → DebugInfo` | Enable/disable debugging |
| `withDebug(target)` | `withDebug(object) → Proxy \| object` | Wrap object (async methods) |
| `withDebug(aliasAndTarget)` | `withDebug(["alias", object]) → Proxy \| object` | Wrap with stable alias (async methods) |
| `withDebugSync(target)` | `withDebugSync(object) → Proxy \| object` | Wrap object (sync methods via XHR) |
| `debugCall(fn, ...args)` | `debugCall(fn, ...args) → Promise<result>` | Async inline breakpoint |
| `debugCall(alias, fn, ...args)` | `debugCall("name", fn, ...args) → Promise<result>` | Async inline breakpoint with alias |
| `debugCallSync(fn, ...args)` | `debugCallSync(fn, ...args) → result` | Synchronous inline breakpoint |
| `debugCallSync(alias, fn, ...args)` | `debugCallSync("name", fn, ...args) → result` | Synchronous inline breakpoint with alias |
| `configure(options)` | `configure({serverUrl, ...}) → void` | Set server URL if not auto-detected |
| `registerReplacement(name, fn)` | `registerReplacement(name, fn) → void` | Register a named JS function for `action: "replace"` (client-side only, does not POST to server) |

**Async vs. sync:** The browser client supports both modes:
- **Async (default):** `debugCall` and proxy methods return `Promise`. Uses
  `fetch` for server communication.
- **Synchronous:** `debugCallSync` and `withDebugSync` variants use
  synchronous `XMLHttpRequest` so callers that cannot be async can still
  participate. Note: synchronous XHR on the main thread is deprecated by
  browsers and will log console warnings, but it remains functional.

When debugging is OFF:
- `debugCall(fn, ...args)` returns `Promise.resolve(fn(...args))`
- `debugCallSync(fn, ...args)` returns `fn(...args)` directly (zero overhead)

**Log-only mode:** The async proxy (`withDebug`) intercepts method calls
via a `Proxy` `get` handler. Certain property accesses are invoked by the
JavaScript runtime itself and **must** return synchronous values — the proxy
cannot return a Promise for these. The proxy detects these cases by property
name and falls back to **log-only mode**: the call is recorded on the server
(fire-and-forget POST to `/api/call/start` + `/api/call/complete`) but is
never paused at breakpoints.

**Log-only triggers (common list; may vary by engine):**
- `Symbol.toPrimitive`, `Symbol.iterator`, `Symbol.asyncIterator`
- `valueOf`, `toString`, `toJSON`
- `[Symbol.hasInstance]`, `[Symbol.toStringTag]`

For all other method calls, the async proxy returns a `Promise` and full
breakpoint interception applies. There is no explicit opt-in for log-only
mode — it is always automatic based on the property name.

#### 1.4 Serialization

The JavaScript client serializes objects to JSON. Since arbitrary JS objects
cannot always be JSON-serialized, the client uses a structured-clone-safe
approach:

1. **Try** `JSON.stringify(obj)` with a replacer that handles cycles and
   non-serializable values.
2. **On failure**, produce a placeholder object analogous to
   `UnpicklablePlaceholder`:
   ```json
   {
     "type_name": "HTMLElement",
     "repr_text": "<div id=\"main\">...</div>",
     "attributes": {"id": "main", "className": "container"},
     "failed_attributes": {"parentNode": "circular reference"},
     "serialization_error": "Converting circular structure to JSON",
     "serialization_format": "json"
   }
   ```
3. **CID** is computed as SHA-512 of the canonical JSON string. All CIDs in
   the system (both Python dill payloads and browser JSON payloads) use
   SHA-512. The server always validates CIDs against the data it receives.

   **Async path (`debugCall`):** Uses `crypto.subtle.digest("SHA-512", ...)`
   (Web Crypto API, returns a Promise).

   **Sync path (`debugCallSync`):** `crypto.subtle.digest` is async and
   cannot be used synchronously. The sync path uses a bundled pure-JavaScript
   SHA-512 implementation (e.g., a minimal self-contained function included
   in `debug-client.js`). This is slower than Web Crypto but necessary for
   synchronous CID computation.

#### 1.5 Process Identity

Instead of a real OS PID, the browser client sends:

| Field | Value | Purpose |
|-------|-------|---------|
| `process_pid` | `0` | Sentinel indicating browser client |
| `process_start_time` | `performance.timeOrigin / 1000` | Page load epoch (seconds) |
| `page_url` | `window.location.href` | Human-readable process identifier |

The server's `_process_key` function already accepts any integer PID and float
timestamp, so `0 + <timeOrigin>` produces a unique key per page load. The
`page_url` field is additional metadata for display purposes (shown in the UI
instead of a PID).

#### 1.6 Call Site Information

Python sends a stack trace. JavaScript sends:

```json
{
  "timestamp": 1707349261.123,
  "page_url": "https://example.com/app",
  "stack_trace": [
    {
      "filename": "https://example.com/app.js",
      "lineno": 42,
      "function": "handleClick",
      "code_context": null
    }
  ]
}
```

The stack trace is parsed from `new Error().stack`. The format varies across
browsers but the library normalizes it to the same shape the Python client
uses.

#### 1.7 Proxy Wrapping (`withDebug(object)`)

Uses JavaScript `Proxy` to intercept method calls, analogous to Python's
`DebugProxy`:

```javascript
// Conceptual sketch
function wrapObject(target, alias) {
  return new Proxy(target, {
    get(obj, prop) {
      const value = obj[prop];
      if (typeof value !== "function") return value;
      return async function(...args) {
        // ... call start / poll / execute / call complete ...
      };
    }
  });
}
```

**Important:** `withDebug(object)` wraps methods as **async** — callers must
`await` them. For code that cannot tolerate this, use `withDebugSync(object)`
which intercepts synchronously via `XMLHttpRequest`. In cases where neither
async nor sync interception can preserve the call semantics, the proxy falls
back to **log-only mode**: calls are recorded on the server for the call
tree but never paused at breakpoints.

#### 1.8 REPL Support

The browser client implements REPL support using `eval()` in the page context.
Everything runs on localhost, so the security implications of `eval()` are
acceptable for this development tool.

During a paused execution, the browser client polls `GET /api/poll-repl/<pause_id>`
for REPL evaluation requests. When one arrives, the client:

1. Receives the expression string from the server.
2. Evaluates it via `eval()` in a scope that has access to the function's
   arguments and the `this` binding of the paused call.
3. Serializes the result as JSON and POSTs it to `/api/call/repl-result`.

**Scope construction:** The REPL scope exposes only:
- `$args` — array of the intercepted function's arguments
- `$this` — the `this` binding of the paused call
- Named parameters — extracted from `Function.toString()` where possible

Closure variables (values captured from outer scopes) are **not** exposed
in v1. This avoids the complexity of source parsing.

**Error handling:** If `eval()` throws, the error is captured and sent back
to the server as an error result, just like the Python REPL.

#### 1.9 Replacement Function Registry (Client-Side)

The browser client maintains a **local** registry of named JavaScript
functions that can serve as replacements when the server returns
`action: "replace"`. This is distinct from the Python client's
`register_function`, which POSTs to the server — the JS replacement
registry is purely client-side.

```javascript
const _replacementRegistry = new Map(); // name -> function

cideldill.registerReplacement = function(name, fn) {
  _replacementRegistry.set(name, fn);
};
```

**Note:** The name `registerReplacement` (not `registerFunction`) is used
to avoid confusion with the Python client's `register_function` which has
different semantics (posts to the server's `/api/functions` endpoint).

When the server returns `action: "replace"` with `function_name: "myAlt"`,
the browser client:

1. Looks up `"myAlt"` in `_replacementRegistry`.
2. **Validates the signature:** checks that the replacement's `Function.length`
   matches the original function's parameter count. On mismatch, logs a
   warning and falls back to calling the original function.
3. If found and compatible, calls the replacement with the original arguments.
4. If not found, falls back to calling the original function and logs a warning.

---

### 2. Server Changes

#### 2.1 New Endpoint: `GET /api/debug-client.js`

Returns the JavaScript client library with `Content-Type: application/javascript`.
The server URL is injected into the script as a constant so the client
auto-discovers its server.

#### 2.2 Serialization Format Specifier

Every payload that currently carries `data` (base64-encoded dill) gains an
optional `serialization_format` field:

| Value | Meaning |
|-------|---------|
| `"dill"` | (default, backward compatible) base64-encoded dill pickle |
| `"json"` | JSON-encoded value (the `data` field is a JSON string, not base64) |

**Affected payloads:**

- `/api/call/start` — `target.data`, `args[*].data`, `kwargs.*.data`
  (format field on each nested item: `target.serialization_format`, etc.)
- `/api/call/complete` — `result_data`, `exception_data`
  (format field at top level: `result_serialization_format`,
  `exception_serialization_format` since these are not nested items)
- `/api/functions` — `function_data`
  (format field at top level: `function_serialization_format`)
- `/api/call/event` — `result_data`, `exception_data`
  (format field at top level: `result_serialization_format`,
  `exception_serialization_format`)

When `serialization_format` is `"json"`:
- The `data` field contains a JSON string (not base64).
- The `cid` field is the SHA-512 hex digest of the UTF-8 encoded JSON string.
- The CID store stores the raw UTF-8 bytes of the JSON string.
- Deserialization uses `json.loads()` instead of `dill.loads(base64.b64decode(...))`.

**CID migration:** All CIDs across the system move from SHA-256 to SHA-512.
This affects both the Python client (dill payloads) and the new browser client
(JSON payloads). The server always validates that the provided CID matches the
SHA-512 hash of the received data, rejecting mismatches with a 400 error.

#### 2.3 Process Key with Page URL

The server currently builds `process_key = f"{start:.6f}+{pid}"`. Browser
payloads include an additional `page_url` field. The server stores `page_url`
alongside the process key as metadata for display in the web UI (call tree,
paused executions, etc.) without changing the key format.

#### 2.4 Pretty-Printing JSON Payloads

The server's `_format_payload_value` function currently deserializes dill
objects for display. For JSON payloads, it can display the JSON directly
since it is already human-readable. The function checks `serialization_format`
and branches accordingly:

- `"dill"` → existing path (dill.loads + pygments Python highlighting)
- `"json"` → json.loads + pygments JSON highlighting

#### 2.5 CID Deduplication and Validation

The same CID cache logic applies: if a CID is already in the CID store, the
client can omit the `data` field. The server returns `cid_not_found` if it
needs the data resent.

**Server-side CID validation:** The server always validates CIDs. When `data`
is present, the server computes `SHA-512(data_bytes)` and compares it to the
provided `cid`. On mismatch, the server returns a 400 error:
```json
{
  "error": "cid_mismatch",
  "message": "Provided CID does not match SHA-512 hash of data",
  "expected_cid": "<computed>",
  "provided_cid": "<from_request>"
}
```
This applies to both `"dill"` and `"json"` format payloads.

#### 2.6 Client-Declared Preferred Format

When the server needs to send data back to the client (e.g., modified args
for `action: "modify"`, or fake results for `action: "skip"`), it needs to
know what serialization format the client can consume. The client declares
this in every `/api/call/start` request:

```json
{
  "preferred_format": "json",
  ...
}
```

| Value | Meaning |
|-------|---------|
| `"dill"` | (default) Send modified args/results as base64 dill |
| `"json"` | Send modified args/results as JSON |

The server stores `preferred_format` with the call data so that when a
breakpoint is resumed with modifications, the response is encoded in the
format the client understands.

#### 2.7 CORS Headers

The breakpoint server must add CORS headers so that pages on different origins
can call the API. The `/api/debug-client.js` endpoint also needs CORS for
cross-origin `<script>` loading (or use `crossorigin` attribute).

A simple approach: add `Access-Control-Allow-Origin: *` to all `/api/*`
responses and handle `OPTIONS` preflight requests. This is acceptable because
the breakpoint server is a development tool running locally.

---

### 3. Web UI Changes (Server-Side)

#### UI: Client Type Indicator

Paused executions and call tree entries from browser clients show a browser
icon (or "JS" label) next to the page URL instead of a PID.

#### UI: JSON Value Display

When the server detects a JSON-serialized payload, the object browser and
call detail views render JSON with syntax highlighting instead of attempting
Python repr formatting.

---

## Serialization Format Specifier — Detailed Placement

The `serialization_format` field appears at the **payload item level** for
requests that contain multiple data items (e.g., `/api/call/start`). For
endpoints where the payload only includes a single result/exception blob
(`call/complete` and `call/event`), the format is specified with the
top-level `result_serialization_format` / `exception_serialization_format`
fields for clarity.

```json
{
  "method_name": "fetchData",
  "target": {
    "cid": "abc123...",
    "client_ref": 1,
    "data": "{\"type\": \"APIClient\", \"baseUrl\": \"https://api.example.com\"}",
    "serialization_format": "json"
  },
  "args": [
    {
      "cid": "def456...",
      "client_ref": 2,
      "data": "{\"endpoint\": \"/users\"}",
      "serialization_format": "json"
    }
  ],
  "kwargs": {},
  "page_url": "https://example.com/app",
  "process_pid": 0,
  "process_start_time": 1707349261.123
}
```

When `serialization_format` is absent, the server assumes `"dill"` (backward
compatible).

---

## Test Plan

Tests are organized by component. Each test name follows the project's
`test_*.py` naming convention. Tests use TDD (red-green-refactor) per
CLAUDE.md.

### T1. Server: Serialization Format Handling

These test the server's ability to accept and store JSON-serialized payloads.

| # | Test | What It Verifies |
|---|------|-------------------|
| 1 | `test_call_start_accepts_json_serialization_format` | `/api/call/start` accepts `serialization_format: "json"` in payload items and returns a `call_id` |
| 2 | `test_call_start_defaults_to_dill_when_format_absent` | Existing payloads without `serialization_format` still work (backward compat) |
| 3 | `test_call_start_stores_json_data_in_cid_store` | JSON data is stored in CID store with CID = SHA-512 of UTF-8 JSON |
| 4 | `test_call_start_cid_dedup_works_for_json` | Second request with same CID and no `data` succeeds (server has it cached) |
| 5 | `test_call_start_returns_cid_not_found_for_missing_json_data` | Request with JSON CID but no data and CID not in store → 400 with `cid_not_found` |
| 6 | `test_call_complete_accepts_json_result_data` | `/api/call/complete` stores JSON result with `serialization_format: "json"` |
| 7 | `test_call_complete_accepts_json_exception_data` | `/api/call/complete` stores JSON exception data |
| 8 | `test_call_event_accepts_json_serialization_format` | `/api/call/event` handles JSON payloads |
| 9 | `test_register_function_accepts_json_format` | `/api/functions` POST accepts JSON-serialized function metadata |
| 10 | `test_mixed_format_in_single_request` | A `/api/call/start` where `target` is JSON format but an arg is dill format (or vice versa) is handled correctly |
| 11 | `test_json_cid_matches_sha512_of_utf8_json_string` | Server validates that provided CID matches SHA-512 of the JSON data bytes |
| 12 | `test_invalid_serialization_format_rejected` | `serialization_format: "xml"` → 400 error |

### T2. Server: Process Identity with Page URL

| # | Test | What It Verifies |
|---|------|-------------------|
| 13 | `test_process_key_with_pid_zero_and_page_url` | `process_pid=0` + `process_start_time` produces a valid process key |
| 14 | `test_page_url_stored_in_call_data` | `page_url` from request body is stored in call data and accessible via `/api/paused` |
| 15 | `test_call_tree_groups_by_page_url` | Call tree view groups browser calls by page URL |
| 16 | `test_page_url_displayed_in_paused_execution` | Paused execution card shows page URL when present |
| 17 | `test_different_page_loads_get_different_process_keys` | Two requests with `pid=0` but different `process_start_time` get different keys |
| 18 | `test_same_page_reload_gets_new_process_key` | Same URL with different `process_start_time` (reload) creates a new process key |

### T3. Server: CORS Support

| # | Test | What It Verifies |
|---|------|-------------------|
| 19 | `test_api_responses_include_cors_headers` | All `/api/*` responses have `Access-Control-Allow-Origin: *` |
| 20 | `test_options_preflight_returns_200` | `OPTIONS` request to any `/api/*` endpoint returns 200 with correct CORS headers |
| 21 | `test_cors_allows_content_type_json` | Preflight response includes `Access-Control-Allow-Headers: Content-Type` |
| 22 | `test_debug_client_js_has_cors_headers` | `/api/debug-client.js` response includes CORS headers |

### T4. Server: JavaScript Client Endpoint

| # | Test | What It Verifies |
|---|------|-------------------|
| 23 | `test_debug_client_js_endpoint_exists` | `GET /api/debug-client.js` returns 200 |
| 24 | `test_debug_client_js_content_type` | Response has `Content-Type: application/javascript` |
| 25 | `test_debug_client_js_contains_server_url` | Returned JS contains the server's own URL so client auto-discovers |
| 26 | `test_debug_client_js_defines_cideldill_namespace` | Returned JS defines `cideldill` global (parseable, no syntax errors) |
| 27 | `test_debug_client_js_is_cacheable` | Response includes appropriate cache headers (ETag or Cache-Control) |

### T5. Server: Pretty-Print JSON Payloads

| # | Test | What It Verifies |
|---|------|-------------------|
| 28 | `test_format_payload_value_for_json_data` | `_format_payload_value` returns readable dict for JSON-serialized items |
| 29 | `test_format_payload_value_for_dill_data_unchanged` | Existing dill path still works identically |
| 30 | `test_breakpoint_history_shows_json_args` | `/api/breakpoints/<name>/history` renders JSON args readably |
| 31 | `test_object_browser_renders_json_objects` | `/objects` page displays JSON-serialized objects with JSON highlighting |

### T6. JavaScript Client: Core API

These tests run in a simulated browser environment (e.g., jsdom or by testing
the JS against a live test server from Python using subprocess + a headless
browser, or by unit-testing the JS functions directly).

| # | Test | What It Verifies |
|---|------|-------------------|
| 32 | `test_js_with_debug_on_returns_debug_info` | `cideldill.withDebug("ON")` returns object with `isEnabled()` true |
| 33 | `test_js_with_debug_off_returns_debug_info` | `cideldill.withDebug("OFF")` returns object with `isEnabled()` false |
| 34 | `test_js_with_debug_off_is_noop_for_wrapping` | `cideldill.withDebug(obj)` when OFF returns the original object |
| 35 | `test_js_with_debug_on_wraps_object_in_proxy` | `cideldill.withDebug(obj)` when ON returns a Proxy |
| 36 | `test_js_proxy_intercepts_method_calls` | Calling a method on a wrapped object sends POST to `/api/call/start` |
| 37 | `test_js_proxy_non_function_properties_not_intercepted` | Reading a data property on a wrapped object does not trigger a call |
| 38 | `test_js_debug_call_sends_call_start` | `cideldill.debugCall(fn, arg)` POSTs to `/api/call/start` |
| 39 | `test_js_debug_call_with_alias` | `cideldill.debugCall("myAlias", fn, arg)` uses alias as `method_name` |
| 40 | `test_js_debug_call_when_off_calls_directly` | When debug OFF, `cideldill.debugCall(fn, arg)` calls `fn(arg)` directly |
| 41 | `test_js_debug_call_returns_function_result` | Result of the original function is returned through the promise |
| 42 | `test_js_debug_call_propagates_exceptions` | If `fn` throws, the promise rejects with the same error |
| 43 | `test_js_configure_sets_server_url` | `cideldill.configure({serverUrl: "..."})` overrides auto-detection |

### T7. JavaScript Client: Serialization

| # | Test | What It Verifies |
|---|------|-------------------|
| 44 | `test_js_serializes_primitives_as_json` | Numbers, strings, booleans, null serialize correctly |
| 45 | `test_js_serializes_plain_objects` | `{a: 1, b: "two"}` produces valid JSON with correct CID |
| 46 | `test_js_serializes_arrays` | `[1, 2, 3]` serializes correctly |
| 47 | `test_js_serializes_nested_objects` | Deep nesting works |
| 48 | `test_js_handles_circular_references` | Object with cycle produces placeholder instead of throwing |
| 49 | `test_js_handles_dom_elements` | DOM node produces a placeholder with type_name and attributes |
| 50 | `test_js_handles_functions_in_objects` | Functions in object values produce placeholder entries |
| 51 | `test_js_handles_undefined_values` | `undefined` is serialized as `null` or omitted, not dropped silently |
| 52 | `test_js_handles_symbol_keys` | Symbol-keyed properties are skipped gracefully |
| 53 | `test_js_handles_bigint` | BigInt values produce string representation |
| 54 | `test_js_cid_computation_matches_server` | CID computed in JS (SHA-512 of JSON UTF-8) matches what server computes for same JSON string |
| 55 | `test_js_cid_cache_deduplication` | Second serialization of same object omits data (cache hit) |
| 56 | `test_js_placeholder_structure_matches_server_expectation` | JS placeholder objects have the fields the server expects |
| 57 | `test_js_sync_sha512_matches_async_sha512` | Pure-JS sync SHA-512 produces same hex as `crypto.subtle.digest` for same input |

### T8. JavaScript Client: Process Identity

| # | Test | What It Verifies |
|---|------|-------------------|
| 58 | `test_js_sends_pid_zero` | All payloads have `process_pid: 0` |
| 59 | `test_js_sends_page_load_time` | `process_start_time` is set from `performance.timeOrigin` |
| 60 | `test_js_sends_page_url` | All payloads include `page_url` field |
| 61 | `test_js_page_url_reflects_current_location` | `page_url` matches `window.location.href` |

### T9. JavaScript Client: Call Stack Parsing

| # | Test | What It Verifies |
|---|------|-------------------|
| 62 | `test_js_parses_chrome_stack_trace` | Chrome-format stack traces are parsed into `{filename, lineno, function}` |
| 63 | `test_js_parses_firefox_stack_trace` | Firefox-format stack traces are parsed |
| 64 | `test_js_parses_safari_stack_trace` | Safari-format stack traces are parsed |
| 65 | `test_js_stack_trace_with_anonymous_functions` | Anonymous functions get a sensible placeholder name |
| 66 | `test_js_stack_trace_with_eval` | `eval()` frames are handled without crashing |

### T10. JavaScript Client: Polling

| # | Test | What It Verifies |
|---|------|-------------------|
| 67 | `test_js_polls_when_action_is_poll` | Client enters poll loop when server returns `action: "poll"` |
| 68 | `test_js_stops_polling_when_ready` | Poll loop exits when server returns `status: "ready"` |
| 69 | `test_js_respects_poll_interval` | Polls at the interval specified by server |
| 70 | `test_js_times_out_after_timeout_ms` | After `timeout_ms`, client stops polling and continues |
| 71 | `test_js_handles_poll_network_error` | Network error during poll does not crash; retries or times out |

### T11. JavaScript Client: Action Handling

| # | Test | What It Verifies |
|---|------|-------------------|
| 72 | `test_js_action_continue_executes_normally` | `action: "continue"` → function runs, result returned |
| 73 | `test_js_action_modify_uses_modified_args` | `action: "modify"` → function called with modified args from server |
| 74 | `test_js_action_skip_returns_fake_result` | `action: "skip"` → function not called, fake result returned |
| 75 | `test_js_action_raise_throws_exception` | `action: "raise"` → promise rejects with specified error |
| 76 | `test_js_action_replace_calls_replacement` | `action: "replace"` → looks up registered replacement and calls it |
| 77 | `test_js_sends_call_complete_after_success` | After function returns, POST to `/api/call/complete` with `status: "success"` |
| 78 | `test_js_sends_call_complete_after_exception` | After function throws, POST to `/api/call/complete` with `status: "exception"` |
| 79 | `test_js_handles_after_breakpoint_poll` | If call_complete returns `action: "poll"`, client polls again |

### T12. JavaScript Client: Function Registration

| # | Test | What It Verifies |
|---|------|-------------------|
| 80 | `test_js_registers_function_on_first_call` | First intercepted call POSTs to `/api/functions` |
| 81 | `test_js_does_not_re_register_same_function` | Second call to same function skips registration |
| 82 | `test_js_registration_includes_function_name` | Registration payload has `function_name` |
| 83 | `test_js_registration_includes_signature_if_available` | If function has `.length` or `.toString()`, signature is included |

### T13. JavaScript Client: Proxy Behavior

| # | Test | What It Verifies |
|---|------|-------------------|
| 84 | `test_js_proxy_preserves_this_binding` | Method called on proxy has correct `this` |
| 85 | `test_js_proxy_handles_constructor_calls` | `new Proxy(...)` doesn't break if target is a class |
| 86 | `test_js_proxy_toString_is_log_only` | `proxy.toString()` triggers log-only mode, returns sync result |
| 87 | `test_js_proxy_property_access_not_async` | Non-function property reads are synchronous |
| 88 | `test_js_proxy_handles_symbol_methods` | `Symbol.iterator`, `Symbol.toPrimitive` are forwarded via log-only |
| 89 | `test_js_proxy_wrapping_with_alias` | `withDebug(["myName", obj])` uses "myName" as function prefix |

### T14. Integration: Browser Client ↔ Server Round Trip

These tests start a real server and exercise the JS client against it.
They can use a headless browser (Playwright/Puppeteer) or simulate the
JS client's HTTP calls from Python.

| # | Test | What It Verifies |
|---|------|-------------------|
| 90 | `test_browser_client_registers_and_calls_through_server` | Full round trip: enable → wrap → call → server sees call |
| 91 | `test_browser_client_pauses_at_breakpoint` | Set breakpoint → browser call pauses → appears in `/api/paused` |
| 92 | `test_browser_client_resumes_after_continue` | Paused browser call resumes when continued from UI/API |
| 93 | `test_browser_client_modify_args` | Server modifies args → browser client receives and uses modified args |
| 94 | `test_browser_client_skip_returns_fake_result` | Server sets skip → browser client receives fake result |
| 95 | `test_browser_client_and_python_client_coexist` | Both a Python and browser client connect; both appear in call tree with correct identifiers |
| 96 | `test_browser_call_tree_shows_page_url` | Call tree page displays page URL for browser-originated calls |
| 97 | `test_browser_breakpoint_history_shows_json_values` | History view renders JSON-serialized args readably |
| 98 | `test_browser_client_handles_server_restart` | If server restarts, browser client re-enables cleanly |
| 99 | `test_browser_client_handles_server_unreachable` | Calls proceed (or fail gracefully) when server is down |
| 100 | `test_multiple_browser_tabs_get_unique_process_keys` | Two page loads with different load times → different process keys |
| 101 | `test_debug_client_js_served_from_running_server` | `GET /api/debug-client.js` from a running server returns valid JS |

### T15. Edge Cases and Error Handling

| # | Test | What It Verifies |
|---|------|-------------------|
| 102 | `test_js_call_start_with_empty_args` | `debugCall(fn)` with no args works |
| 103 | `test_js_call_start_with_large_payload` | Very large JSON object is handled (not truncated silently) |
| 104 | `test_js_call_start_with_deeply_nested_object` | 50+ levels of nesting produce placeholder, not stack overflow |
| 105 | `test_js_concurrent_calls_do_not_interfere` | Two simultaneous `debugCall` invocations maintain separate call IDs |
| 106 | `test_js_rapid_enable_disable_cycle` | ON → OFF → ON rapidly does not leave stale state |
| 107 | `test_server_rejects_json_data_with_dill_format` | `serialization_format: "dill"` with non-base64 data → appropriate error |
| 108 | `test_server_rejects_invalid_json_in_json_format` | `serialization_format: "json"` with unparseable data → appropriate error |
| 109 | `test_js_handles_server_500_response` | Server error during call/start → call proceeds (or rejects) gracefully |
| 110 | `test_js_handles_network_timeout` | fetch timeout → call proceeds (or rejects) gracefully |
| 111 | `test_js_wrapping_null_or_undefined` | `withDebug(null)` returns null, `withDebug(undefined)` returns undefined |
| 112 | `test_js_debug_call_with_async_function` | `debugCall(asyncFn, arg)` correctly awaits the async function |
| 113 | `test_js_debug_call_with_generator_function` | `debugCall(generatorFn)` handles or rejects gracefully |
| 114 | `test_js_proxy_method_returning_promise` | If proxied method returns Promise, it is properly awaited and result reported |
| 115 | `test_json_serialization_of_date_objects` | `Date` objects serialize to ISO string |
| 116 | `test_json_serialization_of_regexp` | `RegExp` objects serialize to string representation |
| 117 | `test_json_serialization_of_error_objects` | `Error` objects serialize with message and stack |
| 118 | `test_json_serialization_of_map_and_set` | `Map` and `Set` serialize to array-of-entries / array |
| 119 | `test_json_serialization_of_typed_arrays` | `Uint8Array` etc. serialize to regular arrays |
| 120 | `test_json_serialization_of_nan_and_infinity` | `NaN`, `Infinity`, `-Infinity` serialize to string markers |

---

## Resolved Decisions

These were originally open questions. All have been resolved:

| # | Question | Decision |
|---|----------|----------|
| 1 | Proxy wrapping vs. debugCall-only | Ship both. Only fall back to log-only mode when sync/async nature cannot be preserved. |
| 2 | How `action: "replace"` works in browser | Replacement is a JS function registered earlier by the page via `cideldill.registerReplacement(name, fn)`. |
| 3 | ES module support | Yes. The library supports both `<script>` tag and `import` from ES modules. |
| 4 | CORS policy | `Access-Control-Allow-Origin: *` on all `/api/*` endpoints. Acceptable for a local dev tool. |
| 5 | Browser REPL | Implement it. Uses `eval()` in page context. Everything runs on localhost; security is not a concern. |
| 6 | `action: "modify"` format | Client declares `preferred_format` in every `/api/call/start` request. Server responds in that format. |
| 7 | Headless browser testing | Deferred to later. Initial tests simulate the JS client's HTTP calls from Python and use Node.js for JS unit tests. |
| 8 | Synchronous mode | Supported. `debugCallSync` and `withDebugSync` use synchronous `XMLHttpRequest`. |
| 9 | Script tag URL | Hardcoded. Docs recommend `<script type="module" src="http://localhost:5174/api/debug-client.js"></script>`. Server injects its own URL into the served JS. |
| 10 | CID algorithm and validation | All CIDs (both Python and JS) use **SHA-512**. Server always validates CID against received data; mismatches return 400. |
| 11 | REPL scope depth | v1 exposes only `$args`, `$this`, and named parameters. No closure variable extraction. |
| 12 | Log-only mode activation | Always implicit. The client automatically falls back to log-only when sync/async semantics cannot be preserved. No explicit opt-in API. |
| 13 | SHA-512 migration rollout | Single release. No backward compatibility period — there is no installed base to worry about. Just switch from SHA-256 to SHA-512 everywhere. |
| 14 | `debugCallSync` polling sleep | Deferred. Address when the implementation is working. |
| 15 | Replacement function signature validation | Validate. The browser client checks that the replacement's `Function.length` matches the original's parameter count before calling. Mismatch logs a warning and falls back to the original function. |
| 16 | `withDebugSync` proxy blocking | Acceptable for all callers. No per-method opt-out needed. |

---

## Additional Tests (from resolved decisions)

The following tests cover the new features introduced by the resolved decisions.
They continue the numbering from the original 120 tests.

### T16. SHA-512 CID Migration

| # | Test | What It Verifies |
|---|------|-------------------|
| 121 | `test_python_client_uses_sha512_for_cid` | Python serializer computes CID using SHA-512 |
| 122 | `test_server_validates_cid_against_sha512_hash` | Server rejects payload where CID does not match SHA-512 of data |
| 123 | `test_server_returns_cid_mismatch_error` | Server returns `{"error": "cid_mismatch", ...}` with both CIDs on mismatch |
| 124 | `test_cid_validation_applies_to_dill_format` | CID validation applies to `serialization_format: "dill"` payloads too |
| 125 | `test_cid_validation_applies_to_json_format` | CID validation applies to `serialization_format: "json"` payloads |
| 126 | `test_cid_validation_on_call_complete` | `/api/call/complete` validates result_cid and exception_cid |
| 127 | `test_cid_validation_on_call_event` | `/api/call/event` validates CIDs |
| 128 | `test_js_computes_sha512_cid` | JavaScript client uses `crypto.subtle.digest("SHA-512", ...)` for CID |
| 129 | `test_python_and_js_sha512_agree_on_same_json_bytes` | Python `hashlib.sha512` and JS `crypto.subtle.digest` produce same hex for same UTF-8 input |

### T17. Server: Preferred Format

| # | Test | What It Verifies |
|---|------|-------------------|
| 130 | `test_call_start_stores_preferred_format` | `preferred_format` from request is stored with call data |
| 131 | `test_modify_action_uses_json_for_json_client` | When `preferred_format: "json"`, modified args in resume action are JSON |
| 132 | `test_modify_action_uses_dill_for_dill_client` | When `preferred_format: "dill"` (or absent), modified args are dill |
| 133 | `test_skip_action_uses_preferred_format` | `action: "skip"` returns fake result in client's preferred format |
| 134 | `test_preferred_format_defaults_to_dill` | Missing `preferred_format` defaults to `"dill"` |

### T18. JavaScript Client: Synchronous Mode

| # | Test | What It Verifies |
|---|------|-------------------|
| 135 | `test_js_debug_call_sync_returns_result_directly` | `debugCallSync(fn, arg)` returns the result, not a Promise |
| 136 | `test_js_debug_call_sync_sends_call_start` | Sync mode POSTs to `/api/call/start` via XHR |
| 137 | `test_js_debug_call_sync_polls_synchronously` | Sync polling uses synchronous XHR at poll interval |
| 138 | `test_js_debug_call_sync_when_off` | When OFF, `debugCallSync(fn, arg)` returns `fn(arg)` directly |
| 139 | `test_js_debug_call_sync_propagates_exceptions` | Sync mode throws on function error (not a rejected Promise) |
| 140 | `test_js_debug_call_sync_with_alias` | `debugCallSync("name", fn, arg)` uses alias as method_name |
| 141 | `test_js_with_debug_sync_wraps_methods_synchronously` | `withDebugSync(obj)` proxy methods return values, not Promises |
| 142 | `test_js_with_debug_sync_polls_at_breakpoint` | Sync proxy enters synchronous poll loop when paused at breakpoint |

### T19. JavaScript Client: REPL Support

| # | Test | What It Verifies |
|---|------|-------------------|
| 143 | `test_js_polls_for_repl_requests_during_pause` | While paused, client checks `/api/poll-repl/<pause_id>` |
| 144 | `test_js_evaluates_repl_expression_via_eval` | REPL request expression is evaluated with `eval()` |
| 145 | `test_js_repl_has_access_to_function_args` | REPL scope includes the intercepted function's arguments |
| 146 | `test_js_repl_has_access_to_this_binding` | REPL scope includes `$this` for the call's `this` context |
| 147 | `test_js_repl_has_dollar_args_array` | REPL scope has `$args` array as a fallback for unnamed params |
| 148 | `test_js_repl_posts_result_to_server` | REPL result is POSTed to `/api/call/repl-result` |
| 149 | `test_js_repl_handles_eval_error` | If `eval()` throws, error is sent back as error result |
| 150 | `test_js_repl_handles_undefined_result` | `eval()` returning `undefined` is serialized as `null` |
| 151 | `test_js_repl_multiple_expressions` | Multiple REPL requests during a single pause are handled sequentially |

### T20. JavaScript Client: Replacement Function Registry

| # | Test | What It Verifies |
|---|------|-------------------|
| 152 | `test_js_register_replacement_stores_in_registry` | `cideldill.registerReplacement("name", fn)` stores the function |
| 153 | `test_js_replace_action_calls_registered_function` | `action: "replace"` with `function_name: "myAlt"` calls the registered fn |
| 154 | `test_js_replace_action_fallback_when_not_registered` | Unregistered replacement falls back to original + warning |
| 155 | `test_js_replace_action_passes_original_args` | Replacement function receives the original arguments |
| 156 | `test_js_replace_action_result_sent_to_call_complete` | Replacement function's result is sent in `/api/call/complete` |
| 157 | `test_js_replace_action_validates_signature_match` | Replacement with matching `Function.length` proceeds normally |
| 158 | `test_js_replace_action_rejects_signature_mismatch` | Replacement with different `Function.length` falls back to original + warning |

### T21. JavaScript Client: Log-Only Mode

| # | Test | What It Verifies |
|---|------|-------------------|
| 159 | `test_js_log_only_mode_records_call_on_server` | Log-only call sends `/api/call/start` and `/api/call/complete` |
| 160 | `test_js_log_only_mode_does_not_pause` | Log-only call ignores `action: "poll"` and proceeds |
| 161 | `test_js_log_only_valueOf_triggers_log_only` | `valueOf` on async proxy triggers log-only mode, returns sync |
| 162 | `test_js_log_only_toString_triggers_log_only` | `toString` on async proxy triggers log-only mode, returns sync |
| 163 | `test_js_log_only_toPrimitive_triggers_log_only` | `Symbol.toPrimitive` on async proxy triggers log-only mode |
| 164 | `test_js_log_only_toJSON_triggers_log_only` | `toJSON` on async proxy triggers log-only mode, returns sync |
| 165 | `test_js_log_only_mode_records_result` | Call result is sent to server even in log-only mode |

### T22. Integration: REPL Round Trip

| # | Test | What It Verifies |
|---|------|-------------------|
| 166 | `test_browser_repl_eval_roundtrip` | Server sends REPL expr → browser evals → server receives result |
| 167 | `test_browser_repl_access_call_args` | REPL expression can read the paused call's arguments |
| 168 | `test_browser_repl_error_displayed_in_server` | `eval()` error is shown in server REPL UI |

### T23. Integration: Sync Mode Round Trip

| # | Test | What It Verifies |
|---|------|-------------------|
| 169 | `test_sync_browser_client_pauses_at_breakpoint` | `debugCallSync` pauses; call appears in `/api/paused` |
| 170 | `test_sync_browser_client_resumes` | Paused sync call resumes when continued via API |
| 171 | `test_sync_browser_client_modify_args` | Sync client receives and uses modified args from server |

---

## Open Questions

None. All questions have been resolved. See the Resolved Decisions table above.

---

## Implementation Phases

### Phase 0: SHA-512 Migration (Done)
- Update Python `serialization_common.py` to use SHA-512 for `compute_cid`
- Update Python `Serializer.serialize` and `verify_cid` to use SHA-512
- Add server-side CID validation on all endpoints that receive data
- No backward compatibility period — clean switch from SHA-256 to SHA-512
- Tests: #121–#129

### Phase 1: Server-Side JSON Format Support (Done)
- Add `serialization_format` handling to `/api/call/start`, `/api/call/complete`,
  `/api/call/event`, `/api/functions`
- Add `preferred_format` handling to call data
- Update CID store to handle JSON data storage
- Update `_format_payload_value` to pretty-print JSON payloads
- Tests: #1–#12, #28–#31, #130–#134

### Phase 2: Server Process Identity + CORS (Done)
- Store and display `page_url` field
- Add CORS headers to all `/api/*` endpoints
- Handle OPTIONS preflight
- Tests: #13–#22

### Phase 3: JavaScript Client Endpoint (Done)
- Create `/api/debug-client.js` endpoint with ES module + global support
- Build the JS client library with `withDebug`, `debugCall`, `configure`
- Tests: #23–#27

### Phase 4: JavaScript Client Core (Async)
- Implement JSON serialization with SHA-512 CID
- Implement call protocol (call/start, poll, call/complete)
- Implement function registration and replacement registry
- Implement proxy wrapping
- Tests: #32–#89, #152–#158

### Phase 5: JavaScript Client Sync Mode
- Implement `debugCallSync` and `withDebugSync` with synchronous XHR
- Implement log-only fallback mode
- Tests: #135–#142, #159–#165

### Phase 6: JavaScript Client REPL
- Implement REPL polling during pause
- Implement `eval()` scope construction with `$args`, `$this`, named params
- Implement REPL result posting
- Tests: #143–#151

### Phase 7: Integration Testing
- End-to-end tests with real server and simulated browser client
- REPL and sync mode round trips
- Tests: #90–#101, #166–#171

### Phase 8: Edge Cases and Hardening
- Handle all error and edge case scenarios
- Tests: #102–#120

---

## Files to Create/Modify

### New Files
- `server/src/cideldill_server/debug_client_js.py` — JS client library content
  (or inline in breakpoint_server.py alongside HTML_TEMPLATE)
- `tests/unit/test_browser_serialization_format.py` — server-side JSON format tests
- `tests/unit/test_browser_cors.py` — CORS tests
- `tests/unit/test_browser_process_identity.py` — page URL / PID=0 tests
- `tests/unit/test_debug_client_js_endpoint.py` — JS endpoint tests
- `tests/unit/test_sha512_migration.py` — SHA-512 CID tests
- `tests/unit/test_cid_validation.py` — server-side CID validation tests
- `tests/unit/test_preferred_format.py` — preferred_format handling tests
- `tests/unit/test_browser_sync_mode.py` — synchronous JS client tests
- `tests/unit/test_browser_repl.py` — browser REPL tests
- `tests/unit/test_browser_replacement_registry.py` — replacement function tests
- `tests/unit/test_browser_log_only.py` — log-only mode tests
- `tests/integration/test_browser_integration.py` — full round-trip tests
- `tests/integration/test_browser_repl_integration.py` — REPL round-trip tests
- `tests/integration/test_browser_sync_integration.py` — sync mode round-trip tests

### Modified Files
- `client/src/cideldill_client/serialization_common.py` — SHA-512 migration
- `server/src/cideldill_server/serialization_common.py` — SHA-512 migration
- `server/src/cideldill_server/breakpoint_server.py` — CORS, new endpoint,
  JSON format handling, CID validation, preferred_format in call/start,
  call/complete, call/event, functions
- `server/src/cideldill_server/serialization.py` (if exists) or the
  relevant server deserialization path — JSON branch
- Web UI HTML template — client type indicator, JSON rendering
