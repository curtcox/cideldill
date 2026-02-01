# NAT Debugger — Master Plan

## Overview

A development debugger for NVIDIA Nemo Agent Toolkit (NAT) apps that provides inspection, breakpoints, and logging for tool calls and HTTP requests. Designed to be NAT-agnostic at its core so it can be reused with other agent frameworks.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                       Browser                           │
│                   (htmx + SSE)                          │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP/SSE
┌────────────────────────▼────────────────────────────────┐
│                   Debugger Core                         │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────┐   │
│  │  CAS Store  │  │  Call Log   │  │  Breakpoint    │   │
│  │  (SQLite +  │  │  (append-   │  │  Manager       │   │
│  │  cloudpickle)│  │  only CIDs) │  │                │   │
│  └─────────────┘  └─────────────┘  └────────────────┘   │
│                                                         │
│  Exposes: rpyc (for apps), HTTP/SSE (for UI)            │
└────────────────────────▲────────────────────────────────┘
                         │ rpyc
┌────────────────────────┴────────────────────────────────┐
│                      App Process                        │
│  ┌─────────────┐  ┌─────────────────────────────────┐   │
│  │ Interceptor │──│  Wrapped tools / HTTP calls     │   │
│  └─────────────┘  └─────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Process Boundaries

| Process | Role | Exposes |
|---------|------|---------|
| App | Runs interceptor, wrapped tools | — |
| Debugger core | CAS store, call log, breakpoint state | rpyc (for apps), HTTP/SSE (for UI) |
| Browser | Display + controls | — |

Minimal setup is two processes (app + debugger core).

## Components

### CAS Store
- SQLite single-file database
- cloudpickle with `persistent_id`/`persistent_load` for content-addressed serialization
- 512-bit (SHA-512) content identifiers
- Deduplication is automatic (same bytes → same CID → INSERT OR IGNORE)
- Objects immutable once written

### Call Log
- Append-only table of CID tuples
- Schema: `(timestamp, stack_trace_cid, function_cid, args_cid, kwargs_cid, result_cid, error_cid)`
- All fields are CIDs pointing into CAS store

### Interceptor
- Generic wrapper factory, no NAT dependency
- Hooks: `on_call`, `on_return`, `on_error`
- Sync and async variants needed
- Communicates with debugger core over rpyc

### Debugger Core (rpyc service)
- Receives events from interceptor
- Manages breakpoint state (pause/release/edit)
- Persists to CAS store and call log
- Also runs HTTP/SSE server for UI

### Web UI
- FastAPI + htmx + SSE
- Live event stream of calls
- Breakpoint controls
- CAS browser for inspecting recorded objects
- Purely a client of debugger core's HTTP API

### NAT Adapter (optional, separate module)
- Wraps NAT builder to return wrapped tools
- Imports generic interceptor
- Only code that depends on NAT

## Dependency Graph

| Component | Depends on |
|-----------|------------|
| CAS Store | stdlib, cloudpickle, sqlite3 |
| Call Log | CAS Store |
| Interceptor | Debugger protocol (abstract) |
| Debugger Core | CAS Store, Call Log, rpyc, FastAPI |
| Web UI | (just a browser hitting HTTP) |
| NAT Adapter | Interceptor, NAT |

## Progressive Demo Apps

For development, documentation, and demonstration:

| Level | App | Exercises |
|-------|-----|-----------|
| 0 | Calculator — `add(a, b)`, `mul(a, b)` | Basic interception, CAS storage of primitives |
| 1 | Calculator with history — functions take/return `State` object | Non-trivial objects, CID references across calls |
| 2 | File processor — `read`, `transform`, `write` | Larger payloads, unpicklable edge cases |
| 3 | Tool dispatcher — `{name: fn}` dict, `dispatch(name, args)` | Dynamic resolution, closer to NAT's builder pattern |
| 4 | Async tool dispatcher | Async interception, concurrent calls in flight |
| 5 | Mock agent loop — dispatcher + LLM-like "pick a tool" step | Multi-step call chains, breakpoint mid-workflow |
| 6 | Actual NAT app | Real integration |

Levels 0–3: single Python file each. Level 4–5: maybe two files. Level 6: mostly configuration.

## Implementation Phases

### Phase 1: CAS Store
- [ ] SQLite wrapper with `__setitem__`, `__getitem__`, `__contains__`
- [ ] CASPickler subclass of cloudpickle.CloudPickler with `persistent_id`
- [ ] CASUnpickler with `persistent_load`
- [ ] Memoize by `id(obj)` within single dump
- [ ] Fallback to `repr()` for unpicklable objects
- [ ] Unit tests with demo app level 0

### Phase 2: Call Log
- [ ] Append-only table schema
- [ ] `record_call()` and `record_result()` methods
- [ ] Query by call_id, time range
- [ ] Unit tests with demo app level 1

### Phase 3: Interceptor (sync)
- [ ] Generic `wrap(fn, debugger)` function
- [ ] Abstract debugger protocol (on_call, on_return, on_error)
- [ ] Local (in-process) debugger for testing
- [ ] Unit tests with demo app level 2–3

### Phase 4: Debugger Core (rpyc)
- [ ] rpyc service implementing debugger protocol
- [ ] Breakpoint manager (set, clear, check, block-until-released)
- [ ] Integration tests with demo app level 3

### Phase 5: Web UI (read-only)
- [ ] FastAPI HTTP server in debugger core
- [ ] SSE endpoint for live events
- [ ] htmx page: live call stream
- [ ] CAS object browser (view by CID)
- [ ] Manual testing with demo app level 3

### Phase 6: Web UI (breakpoints)
- [ ] Breakpoint controls (set on function, pause all, release)
- [ ] View/edit paused call arguments
- [ ] Release with original or modified args
- [ ] Manual testing with demo app level 5

### Phase 7: Async Support
- [ ] Async interceptor variant
- [ ] Test with demo app level 4

### Phase 8: NAT Integration
- [ ] NAT adapter module
- [ ] Builder wrapper
- [ ] Test with demo app level 6

### Phase 9: HTTP Proxy (optional)
- [ ] Intercept outbound HTTP from app
- [ ] Same breakpoint/logging model
- [ ] Lower priority — only if needed for NAT backend calls

## Open Questions

1. **Object identity across calls**: Same logical value may produce different CIDs if object has mutable internal state (timestamps, random IDs). Problem to solve if/when it bites.

2. **Large objects**: Should there be a size threshold for CAS storage? Or always store everything?

3. **Retention policy**: CAS store grows forever. Add TTL/pruning later, or keep everything?

4. **Multiple apps**: Should debugger core handle multiple app connections simultaneously? Probably yes, but adds complexity to breakpoint management.

5. **Replay**: Recording is primary goal. Replay (re-execute calls with stored args) would be nice. Defer until inspection is solid?

6. **HTTP proxy placement**: If needed, does it run in app process or debugger core? Probably app process (intercept outbound before it leaves).

7. **Security**: rpyc is designed for trusted networks. Fine for local dev. Document this assumption.

8. **Serialization failures**: Current plan is fallback to `repr()`. Should we also store type info, traceback of the pickle failure, etc.?

## Technical Notes

### cloudpickle persistent_id pattern

```python
class CASPickler(cloudpickle.CloudPickler):
    def __init__(self, file, store, threshold=256):
        super().__init__(file)
        self.store = store
        self.threshold = threshold
        self._seen = {}
    
    def persistent_id(self, obj):
        if id(obj) in self._seen:
            return self._seen[id(obj)]
        
        try:
            data = cloudpickle.dumps(obj)
        except Exception:
            return None
        
        if len(data) < self.threshold:
            return None
        
        cid = hashlib.sha512(data).digest()
        self.store[cid] = data
        self._seen[id(obj)] = cid
        return cid
```

### SQLite CAS Store

```python
class CASStore:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS objects (cid BLOB PRIMARY KEY, data BLOB)"
        )
    
    def __setitem__(self, cid: bytes, data: bytes):
        self.conn.execute("INSERT OR IGNORE INTO objects VALUES (?, ?)", (cid, data))
        self.conn.commit()
    
    def __getitem__(self, cid: bytes) -> bytes:
        row = self.conn.execute("SELECT data FROM objects WHERE cid = ?", (cid,)).fetchone()
        if row is None:
            raise KeyError(cid)
        return row[0]
```

### Interceptor sketch

```python
def wrap(fn, debugger):
    def wrapped(*args, **kwargs):
        call_id = debugger.on_call(fn, args, kwargs)  # May block
        try:
            result = fn(*args, **kwargs)
            debugger.on_return(call_id, result)
            return result
        except Exception as e:
            debugger.on_error(call_id, e)
            raise
    return wrapped
```

## References

- [rpyc documentation](https://rpyc.readthedocs.io/)
- [cloudpickle](https://github.com/cloudpipe/cloudpickle)
- [GEF (uses rpyc for remote GDB control)](https://hugsy.github.io/gef/testing/)
- [vLLora breakpoint debugging](https://dev.to/mrunmaylangdb/pause-inspect-edit-debugging-llm-requests-in-vllora-26bg)
