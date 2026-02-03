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
