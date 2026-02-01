# Use Cases

User stories for the NAT debugger, organized by persona and goal.

---

## Personas

| Persona | Description |
|---------|-------------|
| **Agent Developer** | Building/debugging a NAT app or similar agent system |
| **Tool Author** | Writing tools that agents will call |
| **Ops/Support** | Investigating issues in deployed agents |
| **Researcher** | Studying agent behavior patterns |

---

## Inspection

### Observing calls in real-time

As an **agent developer**, I want to see tool calls as they happen, so that I can understand what my agent is doing without adding print statements everywhere.

As an **agent developer**, I want to see the full arguments passed to each tool, so that I can verify the agent is constructing calls correctly.

As an **agent developer**, I want to see the return value from each tool, so that I can verify tools are returning what the agent expects.

As an **agent developer**, I want to see exceptions raised by tools, so that I can understand why my agent's workflow failed.

As a **tool author**, I want to see exactly what arguments my tool receives, so that I can debug input handling issues.

### Inspecting complex objects

As an **agent developer**, I want to drill into nested objects in arguments and return values, so that I can inspect complex data structures without writing custom logging.

As an **agent developer**, I want to see the type and shape of objects (even if unpicklable), so that I can understand data flow even when full serialization fails.

As a **tool author**, I want to inspect the state object passed between calls, so that I can verify state transitions are correct.

### Reviewing history

As an **agent developer**, I want to see the sequence of all calls in a session, so that I can understand the full execution path.

As an **agent developer**, I want to filter call history by tool name, so that I can focus on specific tools when debugging.

As an **agent developer**, I want to search call history by argument values, so that I can find "the call where query was 'foo'".

As an **ops/support** person, I want to review what happened in a past session, so that I can investigate reported issues.

As a **researcher**, I want to export call history for analysis, so that I can study agent behavior patterns offline.

---

## Breakpoints

### Pausing execution

As an **agent developer**, I want to set a breakpoint on a specific tool, so that I can pause execution before that tool runs.

As an **agent developer**, I want to set a conditional breakpoint (e.g., "pause when query contains 'error'"), so that I can catch specific scenarios without pausing on every call.

As an **agent developer**, I want to pause all tool calls, so that I can step through execution one call at a time.

As an **agent developer**, I want to pause on exceptions, so that I can inspect state immediately when something goes wrong.

### Inspecting at breakpoint

As an **agent developer**, I want to see the full call context when paused (function, args, kwargs, caller), so that I can understand why this call is happening.

As an **agent developer**, I want to see the agent's accumulated state when paused, so that I can understand the context leading up to this call.

As an **agent developer**, I want to see other in-flight calls when paused (in async scenarios), so that I can understand concurrent behavior.

### Modifying at breakpoint

As an **agent developer**, I want to edit arguments before releasing a paused call, so that I can test "what if the agent had passed X instead".

As an **agent developer**, I want to skip a tool call and provide a fake return value, so that I can test downstream behavior without running the real tool.

As an **agent developer**, I want to force an exception on a paused call, so that I can test error handling paths.

### Resuming execution

As an **agent developer**, I want to release a single paused call, so that I can continue step-by-step.

As an **agent developer**, I want to release all paused calls, so that I can resume normal execution.

As an **agent developer**, I want to release and disable breakpoints, so that I can let the agent run to completion.

---

## Recording & Replay

### Recording

As an **agent developer**, I want all calls automatically recorded, so that I can review them later without remembering to enable logging.

As an **agent developer**, I want recordings to persist across debugger restarts, so that I don't lose history if I restart the debugger.

As an **agent developer**, I want recordings to be deduplicated, so that repeated calls with the same arguments don't waste storage.

As an **ops/support** person, I want to record production-like runs (without breakpoints), so that I can capture traces for later analysis.

### Replay

As an **agent developer**, I want to re-execute a recorded call with its original arguments, so that I can reproduce issues.

As an **agent developer**, I want to re-execute a recorded call with modified arguments, so that I can test fixes.

As a **tool author**, I want to replay calls to my tool from a recorded session, so that I can debug without running the full agent.

As a **researcher**, I want to replay a sequence of calls deterministically, so that I can study behavior variations.

---

## HTTP Interception (if implemented)

### Observing HTTP

As an **agent developer**, I want to see outbound HTTP requests from my agent, so that I can verify API calls are correct.

As an **agent developer**, I want to see HTTP responses received by my agent, so that I can understand what external services return.

As a **tool author**, I want to see the HTTP calls my tool makes, so that I can debug API integration issues.

### Modifying HTTP

As an **agent developer**, I want to intercept and modify outbound HTTP requests, so that I can test with altered payloads.

As an **agent developer**, I want to intercept and modify HTTP responses, so that I can simulate different API behaviors.

As an **agent developer**, I want to block specific HTTP calls, so that I can test offline/failure scenarios.

---

## Multi-session & Multi-app

### Multiple apps

As an **agent developer**, I want to debug multiple agent apps simultaneously, so that I can compare their behavior.

As an **agent developer**, I want to distinguish which app made which call, so that I can keep track when debugging multiple apps.

### Session management

As an **agent developer**, I want to label sessions (e.g., "testing new prompt"), so that I can organize my debugging history.

As an **agent developer**, I want to clear old sessions, so that I can manage storage.

As an **agent developer**, I want to compare two sessions side-by-side, so that I can see what changed between runs.

---

## Integration

### NAT-specific

As an **agent developer**, I want to enable debugging with a config flag, so that I can switch between debug and normal mode easily.

As an **agent developer**, I want debugging to capture NAT tool metadata (name, description, schema), so that I have richer context than just the function signature.

As an **agent developer**, I want to see which tools are registered with the builder, so that I can verify my configuration.

### Development workflow

As an **agent developer**, I want the debugger to start automatically when I run my app in dev mode, so that I don't have to remember to start it separately.

As an **agent developer**, I want hot-reload to work while debugging, so that I can iterate quickly without restarting everything.

As an **agent developer**, I want to connect my IDE to the debugger, so that I can set breakpoints from my editor (future).

---

## Non-goals (explicitly out of scope, at least initially)

As a user, I do **not** expect:

- Full Python debugger (step through lines of code) — this is tool-call level only
- Production monitoring/alerting — this is a dev tool
- Distributed tracing across services — single app focus
- Automatic issue detection — human-driven inspection
- GUI for building agents — debugging only, not authoring

---

## Priority Matrix

| Use Case Category | Priority | Status | Notes |
|-------------------|----------|--------|-------|
| Real-time inspection | **P0** | ✅ **COMPLETED** | Core value prop - implemented with observer pattern |
| Call history review | **P0** | ✅ **COMPLETED** | Core value prop - implemented with filtering, search, and export |
| Basic breakpoints (pause/release) | **P0** | ✅ **COMPLETED** | Core value prop - implemented with flexible pause handler |
| Argument editing at breakpoint | **P1** | ✅ **COMPLETED** | High value, moderate complexity - implemented in pause handler |
| Recording & persistence | **P1** | ✅ **COMPLETED** | Needed for post-hoc debugging - CAS store provides persistence |
| Conditional breakpoints | **P2** | ⏸️ **TODO** | Nice to have |
| Replay | **P2** | ⏸️ **TODO** | Nice to have |
| HTTP interception | **P2** | ⏸️ **TODO** | Only if NAT apps need it |
| Multi-app support | **P3** | ⏸️ **TODO** | Adds complexity |
| Session management | **P3** | ⏸️ **TODO** | Quality of life |
| IDE integration | **P3** | ⏸️ **TODO** | Future |

---

## Implementation Status

### ✅ Completed (P0 Features)

All P0 real-time inspection use cases have been successfully implemented with comprehensive tests.
See `done/use_cases.md` for detailed documentation of implemented features and API reference.

**Summary:**
- ✅ Real-time observation via observer callbacks
- ✅ Call history filtering by function name
- ✅ Call history search by argument values
- ✅ Export history for offline analysis
- ✅ Breakpoints on specific functions
- ✅ Pause all function calls
- ✅ Pause on exceptions
- ✅ Modify arguments at breakpoint
- ✅ Skip calls with fake return values
- ✅ Force exceptions at breakpoint
- ✅ Clear and manage breakpoints

**Test Coverage:**
- 26 new tests added for P0 features
- All existing tests continue to pass
- 98% code coverage for Interceptor module

---

## AI-as-User Support

Use cases where the debugger user is an AI agent rather than a human.

### Programmatic Access

As an **AI agent**, I want a structured API (not just a web UI), so that I can inspect and control the debugger programmatically.

As an **AI agent**, I want responses in machine-readable formats (JSON), so that I can parse and act on debugger state without scraping HTML.

As an **AI agent**, I want to set breakpoints via API calls, so that I can automate debugging workflows.

As an **AI agent**, I want to query call history with filters and pagination, so that I can efficiently search large execution traces.

### Automated Inspection

As an **AI agent**, I want to receive structured notifications when breakpoints are hit, so that I can respond without polling.

As an **AI agent**, I want to read and modify arguments at breakpoints programmatically, so that I can implement automated testing scenarios.

As an **AI agent**, I want to skip calls and inject return values via API, so that I can mock tool behavior during automated debugging.

As an **AI agent**, I want clear error codes and messages, so that I can handle failures gracefully without human interpretation.

### Batch Operations

As an **AI agent**, I want to set multiple breakpoints in a single API call, so that I can configure debugging efficiently.

As an **AI agent**, I want to export full session data in structured format, so that I can analyze execution traces offline.

As an **AI agent**, I want to replay sequences of calls programmatically, so that I can automate regression testing.

### Integration with AI Workflows

As an **AI agent**, I want to attach metadata to sessions and calls, so that I can correlate debugger data with my own reasoning traces.

As an **AI agent**, I want to subscribe to a stream of events (calls, breakpoints, exceptions), so that I can build reactive debugging workflows.

As an **AI agent**, I want to control multiple debugging sessions simultaneously, so that I can compare behavior across different runs or configurations.

---

## Design Decisions

Answers to key design questions.

1. **Conditional breakpoints**: Use Python `eval()` for conditional expressions. This provides full expressiveness for developers who already know Python.

2. **Replay fidelity**: Support multiple replay modes:
   - Stepping through past execution (read-only review)
   - Stepping through past execution with different arguments (modified replay)
   - Stepping through past execution with a code change (testing fixes)
   - Executing against the target system using a previously issued call (real replay with side effects)

3. **Recording overhead**: Use a simple boolean flag to enable/disable recording. This keeps the interface simple while allowing users to opt out if overhead is a concern.

4. **Multi-user**: Yes, support multiple browser sessions viewing the same app. This enables collaborative debugging and AI-human joint debugging scenarios.

5. **Permissions**: No confirmation required before modifying args at breakpoints. Trust the developer/agent to make appropriate modifications.
