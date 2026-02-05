# with_debug API Reference

`with_debug` is the single entry point for CID el Dill debugging.

## Enable Debugging

```python
from cideldill_client import with_debug

info = with_debug("ON")
```

- Enables debugging for the current process.
- Returns a `DebugInfo` object.
- Raises an exception if the server is unreachable.

## Disable Debugging

```python
from cideldill_client import with_debug

info = with_debug("OFF")
```

- Disables debugging globally.
- Returns a `DebugInfo` object.

## Wrap Objects

```python
from cideldill_client import with_debug

calculator = with_debug(Calculator())
calculator.add(1, 2)
```

- **When debug is ON**: Returns a proxy object that intercepts calls for debugging.
- **When debug is OFF**: Returns the original object unchanged (true NOP with zero overhead).

## Wrap Callables With Aliases

Callable objects and functions can be wrapped with a stable alias for breakpoint matching.

```python
from cideldill_client import with_debug

class Worker:
    def __call__(self, value: int) -> int:
        return value * 2

with_debug("ON")

task = Worker()
wrapped = with_debug(("run_task", task))
wrapped(3)
```

- The alias (`run_task`) is registered for breakpoints.
- Calls are reported under the alias name so server breakpoints can always stop the callable.

## Limitations and Failure Behavior

Some callables are executable when debug is OFF but cannot be reliably registered or
breakpointed with debug ON (for example: unstable names, failing `__signature__`,
or other runtime errors during registration).

When this happens:
- `with_debug` records a `breakpoint_unavailable` event on the server (if possible).
- The client halts with a detailed error message to avoid silently missing breakpoints.

If you see this error, try:
- Wrapping the callable with an explicit alias: `with_debug(("name", callable))`
- Ensuring the callable has a stable name and import path
- Removing custom `__signature__`/`__reduce__` implementations that raise

## Serialization Guarantee For Breakpoints

When debug is ON, callables wrapped with `with_debug` are always registered and
visible in the breakpoint server, even if the callable (or its internals) is highly
resistant to serialization.

CID el Dill falls back to minimal serialization payloads so breakpoint discovery
and call interception continue to work even when detailed object snapshots cannot
be captured.

## Handling Unpicklable Objects

CID el Dill automatically handles objects that can't be pickled using dill's default
mechanisms. This includes objects with metaclass registries, dynamically generated
classes, or complex internal state.

### Automatic Registration

```python
from cideldill_client import with_debug

with_debug("ON")

# Works even if NAT's OutputArgsSchema isn't normally picklable
from nat.utils.type_utils import OutputArgsSchema

schema = OutputArgsSchema(...)
wrapped_schema = with_debug(schema)  # Auto-registers custom pickler

result = wrapped_schema.validate(data)
```

### Manual Registration for Complex Cases

```python
from cideldill_client.custom_picklers import PickleRegistry

def custom_reducer(obj):
    state = {"field1": obj.field1, "field2": obj.field2}

    def reconstruct(state):
        obj = MyComplexClass.__new__(MyComplexClass)
        obj.field1 = state["field1"]
        obj.field2 = state["field2"]
        return obj

    return (reconstruct, (state,))

PickleRegistry.register(MyComplexClass, custom_reducer)
```

### Logging

```python
import logging

logging.basicConfig(level=logging.INFO)
```

You'll see messages like:

```
INFO: Auto-registered custom pickler for nat.utils.type_utils.OutputArgsSchema
```

## Configure Server URL

### Automatic Discovery (Recommended)

The client automatically discovers the server port:

```python
from cideldill_client import with_debug

# No configuration needed - uses port discovery
with_debug("ON")
```

Discovery priority:
1. Explicit `configure_debug(server_url=...)`
2. `CIDELDILL_SERVER_URL` environment variable
3. Port discovery file (`~/.cideldill/port`)
4. Default (`http://localhost:5174`)

### Manual Configuration

```python
from cideldill_client import configure_debug, with_debug

# Explicit configuration (overrides discovery)
configure_debug(server_url="http://localhost:5174")
with_debug("ON")
```

### Environment Variable

```bash
export CIDELDILL_SERVER_URL="http://localhost:8080"
python my_app.py
```

The server URL must be localhost-only.
