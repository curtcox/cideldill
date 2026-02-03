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

## Configure Server URL

```python
from cideldill_client import configure_debug, with_debug

configure_debug(server_url="http://localhost:5000")
with_debug("ON")
```

The server URL must be localhost-only.
