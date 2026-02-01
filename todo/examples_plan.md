# Example Apps Plan

Progressive demo apps for development, documentation, and demonstration of the debugger.

## Design Principles

- Each level should be a single file (or two for async)
- Each level exercises one or two new capabilities
- Examples should be realistic enough to be instructive, but minimal
- Same example can serve as: unit test fixture, documentation, demo
- No NAT dependency until level 6

---

## Level 0: Calculator

**Purpose**: Verify basic interception and CAS storage of primitives.

**Functions**:
```python
def add(a: int, b: int) -> int:
    return a + b

def mul(a: int, b: int) -> int:
    return a * b

def div(a: int, b: int) -> int:
    return a // b  # Can raise ZeroDivisionError
```

**Exercises**:
- Wrap functions with interceptor
- Record call args and return values
- Record an exception (div by zero)
- Verify CIDs are stable (same args → same CID)
- Verify primitives serialize/deserialize correctly

**Test scenarios**:
1. `add(2, 3)` → 5, inspect stored args and result
2. `mul(add(2, 3), 4)` → 20, nested calls recorded separately
3. `div(1, 0)` → error recorded

---

## Level 1: Calculator with State

**Purpose**: Non-trivial objects, CID references across calls.

**Data**:
```python
@dataclass
class CalcState:
    history: list[tuple[str, int]]  # (expression, result)
    last_result: int
```

**Functions**:
```python
def calc(state: CalcState, op: str, a: int, b: int) -> CalcState:
    """Returns new state with operation applied."""
    if op == "add":
        result = a + b
    elif op == "mul":
        result = a * b
    else:
        raise ValueError(f"Unknown op: {op}")
    
    return CalcState(
        history=state.history + [(f"{a} {op} {b}", result)],
        last_result=result
    )

def reset() -> CalcState:
    return CalcState(history=[], last_result=0)
```

**Exercises**:
- Dataclass serialization
- Same state object passed to multiple calls → deduplicated in CAS
- State grows over time → history list gets longer
- Inspect object graph in CAS browser

**Test scenarios**:
1. `reset()` → initial state
2. `calc(state, "add", 2, 3)` → new state with history
3. Chain of 5 operations, verify CAS deduplication of shared prefixes

**Open questions**:
- Will cloudpickle deduplicate the shared `history` prefix across states, or serialize full list each time? (Probably full list each time — dedup happens at object level, not structural sharing)

---

## Level 2: File Processor

**Purpose**: Larger payloads, unpicklable edge cases.

**Functions**:
```python
def read_file(path: str) -> bytes:
    with open(path, 'rb') as f:
        return f.read()

def transform(data: bytes, operation: str) -> bytes:
    if operation == "upper":
        return data.upper()
    elif operation == "reverse":
        return data[::-1]
    elif operation == "compress":
        import gzip
        return gzip.compress(data)
    else:
        raise ValueError(f"Unknown operation: {operation}")

def write_file(path: str, data: bytes) -> dict:
    with open(path, 'wb') as f:
        f.write(data)
    return {"path": path, "size": len(data)}
```

**Exercises**:
- Large-ish payloads (KB to MB)
- Verify CAS handles binary data correctly
- File handles themselves are not arguments, but paths are
- Result includes metadata dict

**Test scenarios**:
1. Read a 1KB file, transform, write
2. Read a 1MB file, verify CAS storage and retrieval
3. Read nonexistent file → error recorded

**Stretch — unpicklable edge case**:
```python
def read_file_lazy(path: str):
    """Returns a generator — cannot be pickled."""
    with open(path, 'rb') as f:
        for line in f:
            yield line
```

This tests the `repr()` fallback for unpicklable objects.

**Open questions**:
- Should we store file contents by CID and reference them, or is that overkill for a demo?
- For the lazy reader, what should the recorded "args" look like? Just `repr()`?

---

## Level 3: Tool Dispatcher

**Purpose**: Dynamic resolution, closer to NAT's builder pattern.

**Structure**:
```python
class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Callable] = {}
    
    def register(self, name: str, fn: Callable):
        self._tools[name] = fn
    
    def get(self, name: str) -> Callable:
        return self._tools[name]
    
    def dispatch(self, name: str, *args, **kwargs):
        fn = self.get(name)
        return fn(*args, **kwargs)

# Tools
def search(query: str) -> list[str]:
    """Fake search returning dummy results."""
    return [f"Result 1 for '{query}'", f"Result 2 for '{query}'"]

def calculate(expression: str) -> float:
    """Eval a simple math expression."""
    return eval(expression)  # Yes, unsafe. It's a demo.

def echo(message: str) -> str:
    return message

# Setup
registry = ToolRegistry()
registry.register("search", search)
registry.register("calculate", calculate)
registry.register("echo", echo)
```

**Exercises**:
- Wrap at `dispatch()` level vs wrapping individual tools
- Record which tool was selected
- `get()` returns a callable — does that serialize?
- Dynamic tool set (tools can be added at runtime)

**Interception strategies to explore**:

1. **Wrap dispatch only**:
   - Records: `dispatch("search", "cats")` → `["Result 1...", ...]`
   - Simple, but loses tool identity in call log

2. **Wrap each tool at registration**:
   - Records: `search("cats")` → `["Result 1...", ...]`
   - More granular

3. **Both**:
   - Records dispatch and underlying tool call
   - Most visibility, but noisy

**Test scenarios**:
1. `dispatch("search", "cats")` → results
2. `dispatch("calculate", "2 + 3")` → 5
3. `dispatch("unknown", ...)` → KeyError
4. Register new tool at runtime, dispatch to it

**Open questions**:
- Which interception strategy should be the default?
- Should `ToolRegistry` itself be a debugger-aware class, or should wrapping be external?

---

## Level 4: Async Tool Dispatcher

**Purpose**: Async interception, concurrent calls in flight.

**Structure**:
```python
class AsyncToolRegistry:
    def __init__(self):
        self._tools: dict[str, Callable] = {}
    
    def register(self, name: str, fn: Callable):
        self._tools[name] = fn
    
    async def dispatch(self, name: str, *args, **kwargs):
        fn = self._tools[name]
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        else:
            return fn(*args, **kwargs)

# Async tools
async def async_search(query: str) -> list[str]:
    await asyncio.sleep(0.1)  # Simulate network
    return [f"Result for '{query}'"]

async def async_fetch(url: str) -> str:
    await asyncio.sleep(0.2)  # Simulate network
    return f"<html>Content of {url}</html>"

# Sync tool (should still work)
def sync_echo(message: str) -> str:
    return message
```

**Exercises**:
- Async wrapper (`async def wrapped(...)`)
- Multiple concurrent calls (`asyncio.gather`)
- Mix of sync and async tools
- Breakpoints must not block event loop (use `asyncio.Event` not `threading.Event`)

**Test scenarios**:
1. Single async call
2. `gather(dispatch("search", "a"), dispatch("search", "b"))` — concurrent
3. Breakpoint on one call, other continues
4. Sync tool through async dispatch

**Open questions**:
- Should async interceptor use a thread pool for rpyc calls, or is rpyc async-compatible?
- How does breakpoint "pause" work in async? Await an `asyncio.Event`?

---

## Level 5: Mock Agent Loop

**Purpose**: Multi-step call chains, breakpoint mid-workflow.

**Structure**:
```python
@dataclass
class AgentState:
    messages: list[dict]
    tool_results: list[dict]
    step: int

def mock_llm_decide(state: AgentState, available_tools: list[str]) -> dict:
    """
    Fake LLM that picks tools based on simple rules.
    Returns: {"action": "tool", "tool": "search", "args": {"query": "..."}}
            or {"action": "respond", "response": "..."}
    """
    if state.step == 0:
        return {"action": "tool", "tool": "search", "args": {"query": "example"}}
    elif state.step == 1:
        return {"action": "tool", "tool": "calculate", "args": {"expression": "1+1"}}
    else:
        return {"action": "respond", "response": "Done!"}

def agent_loop(registry: ToolRegistry, max_steps: int = 5) -> str:
    state = AgentState(messages=[], tool_results=[], step=0)
    
    while state.step < max_steps:
        decision = mock_llm_decide(state, list(registry._tools.keys()))
        
        if decision["action"] == "respond":
            return decision["response"]
        
        tool_name = decision["tool"]
        tool_args = decision["args"]
        
        result = registry.dispatch(tool_name, **tool_args)
        
        state = AgentState(
            messages=state.messages,
            tool_results=state.tool_results + [{"tool": tool_name, "result": result}],
            step=state.step + 1
        )
    
    return "Max steps reached"
```

**Exercises**:
- Multiple calls in a logical sequence
- Agent state evolves across steps
- Breakpoint mid-loop (pause before step 2, inspect state, continue)
- Edit args at breakpoint and observe different path

**Test scenarios**:
1. Run to completion, verify all calls logged in order
2. Set breakpoint on "calculate", pause, inspect accumulated state
3. At breakpoint, modify `expression` arg from "1+1" to "2*3", continue
4. Breakpoint on mock_llm_decide, observe decision-making

**Open questions**:
- Should `mock_llm_decide` be a wrapped tool, or is it "infrastructure"?
- How should the UI visualize a multi-step workflow? Timeline? Tree?

---

## Level 6: NAT App

**Purpose**: Real integration with NVIDIA Nemo Agent Toolkit.

**Structure**: TBD based on actual NAT app, but roughly:

```python
# nat_adapter.py
from debugger import wrap, connect_debugger

def wrap_builder(builder, debugger):
    """
    Returns a modified builder where get_tool() returns wrapped tools.
    """
    original_get_tool = builder.get_tool
    
    def wrapped_get_tool(name):
        tool = original_get_tool(name)
        return wrap(tool, debugger)
    
    builder.get_tool = wrapped_get_tool
    return builder

# Usage in dev config
if DEV_MODE:
    debugger = connect_debugger("localhost", 18861)
    builder = wrap_builder(builder, debugger)
```

**Exercises**:
- Real tool metadata (NAT tools have rich metadata)
- Real async patterns (NAT is likely async)
- Integration with NAT config system
- HTTP backend calls (if proxy layer is implemented)

**Test scenarios**:
- TBD based on specific NAT app

**Open questions**:
- What does NAT's builder interface actually look like?
- Are NAT tools sync or async?
- What metadata is available on tools (name, description, schema)?
- How does NAT handle tool errors?

---

## File Organization

```
examples/
├── level0_calculator.py
├── level1_stateful_calculator.py
├── level2_file_processor.py
├── level3_tool_dispatcher.py
├── level4_async_dispatcher.py
├── level5_mock_agent.py
└── level6_nat_app/
    ├── app.py
    ├── dev_config.yaml
    └── prod_config.yaml
```

Each file should be:
1. Runnable standalone (`if __name__ == "__main__"`)
2. Importable as a module for tests
3. Documented with docstrings explaining what it demonstrates

---

## Suggested Development Order

| Phase | Build | Test with |
|-------|-------|-----------|
| 1 | CAS Store | Level 0 |
| 2 | Call Log | Level 1 |
| 3 | Sync Interceptor | Level 2, 3 |
| 4 | rpyc Debugger Core | Level 3 |
| 5 | Web UI (read-only) | Level 3 |
| 6 | Web UI (breakpoints) | Level 5 |
| 7 | Async Interceptor | Level 4 |
| 8 | NAT Adapter | Level 6 |

---

## Open Questions (Cross-cutting)

1. **Call graph vs flat log**: Should we track parent-child relationships between calls (e.g., `mul(add(...), ...)` or `agent_loop` → `dispatch` → `search`)?

2. **Tool identity**: When dispatch wraps tools, how do we record "this is the search tool" vs "this is some function"?

3. **Timing**: Should we record wall-clock time, or just sequence? Both?

4. **Deterministic replay**: If we want replay, mock_llm_decide and async sleeps need to be deterministic. Seed RNG? Record/replay sleep durations?

5. **Error taxonomy**: Should we distinguish between:
   - Tool raised an exception
   - Tool returned an error value
   - Dispatch failed (unknown tool)
   - Serialization failed

6. **Metadata capture**: Beyond args/result, what else?
   - Function name, module, qualname
   - Docstring
   - Type hints
   - Source location (file:line)
