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

| Use Case Category | Priority | Notes |
|-------------------|----------|-------|
| Real-time inspection | **P0** | Core value prop |
| Call history review | **P0** | Core value prop |
| Basic breakpoints (pause/release) | **P0** | Core value prop |
| Argument editing at breakpoint | **P1** | High value, moderate complexity |
| Recording & persistence | **P1** | Needed for post-hoc debugging |
| Conditional breakpoints | **P2** | Nice to have |
| Replay | **P2** | Nice to have |
| HTTP interception | **P2** | Only if NAT apps need it |
| Multi-app support | **P3** | Adds complexity |
| Session management | **P3** | Quality of life |
| IDE integration | **P3** | Future |

---

## Open Questions

1. **Conditional breakpoints**: What expression language? Python eval? Simple predicates (tool name, arg contains)?

2. **Replay fidelity**: Should replay actually call the tool, or just show what *would* happen? Real replay has side effects.

3. **Recording overhead**: Is always-on recording acceptable, or should it be opt-in?

4. **Multi-user**: Should the debugger support multiple browser sessions viewing the same app? Probably not initially.

5. **Permissions**: Should breakpoints require confirmation before modifying args? Or trust the dev?
