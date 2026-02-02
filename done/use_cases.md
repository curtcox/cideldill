# Implemented Use Cases

This document tracks implemented use cases for the `with_debug` API.

## Debugging Entry Point

✅ **Enable debugging at startup**

- **Implementation**: `with_debug("ON")`
- **Behavior**: Enables debugging globally and returns `DebugInfo`.

✅ **Disable debugging at startup**

- **Implementation**: `with_debug("OFF")`
- **Behavior**: Disables debugging globally and returns `DebugInfo`.

✅ **Wrap objects for debugging**

- **Implementation**: `with_debug(obj)` returns a proxy.
- **Behavior**: Proxy intercepts calls when debug is enabled.

## Request-Response Debugging

✅ **Pause on breakpoints**

- **Implementation**: `/api/call/start` responds with `action="poll"` for breakpointed methods.
- **Behavior**: Client polls `/api/poll/<id>` until resume action is ready.

✅ **Resume with action**

- **Implementation**: `/api/paused/<id>/continue` stores the action.
- **Behavior**: Client receives `continue`, `skip`, `raise`, or `modify`.

## Completion Reporting

✅ **Call completion notifications**

- **Implementation**: `/api/call/complete` stores results or exceptions.
