# Java Debug Client Support

## Goal

Provide a Java client library for `with_debug` and `debug_call` functionality,
analogous to the existing Python client. The Java client communicates with the
same breakpoint server over the same HTTP/JSON API. This is **additive** — the
Python and JavaScript clients are unchanged.

---

## Design Principles

1. **Reuse existing server endpoints** — `/api/call/start`, `/api/call/complete`,
   `/api/poll/<pause_id>`, `/api/functions`, `/api/breakpoints`,
   `/api/call/event`. No new server-side endpoints required.
2. **JSON serialization format** — Java cannot produce dill pickles. All payloads
   use `serialization_format: "json"` and `preferred_format: "json"`. Objects are
   serialized to JSON via Jackson. The CID is `SHA-512(utf8_bytes(json_string))`.
3. **Separate source tree** — Java code lives under `java/` at the repo root,
   with its own Maven/Gradle build, independent of the Python packages.
4. **Mirror the Python client's public API** as closely as Java idioms allow.
5. **Thread-safe by default** — all shared state protected by concurrent data
   structures or explicit locks.

---

## Architecture Overview

```
┌────────────────────────────────────────┐          ┌───────────────────────────┐
│   Java Application                     │          │   Breakpoint Server       │
│                                        │          │   (existing, unchanged)   │
│  CidElDill.withDebug("ON")             │          │                           │
│  CidElDill.withDebug(obj)              │  HTTP    │                           │
│  CidElDill.debugCall(fn, args...)      │──POST──►│  /api/call/start          │
│  CidElDill.debugCall("alias", fn, ...) │──POST──►│  /api/call/complete       │
│                                        │◄──GET───│  /api/poll/<id>           │
│                                        │──POST──►│  /api/functions           │
│                                        │◄──GET───│  /api/breakpoints         │
│                                        │──POST──►│  /api/call/event          │
└────────────────────────────────────────┘          └───────────────────────────┘
```

---

## Source Tree Layout

```
java/
├── pom.xml                              (or build.gradle)
├── src/
│   ├── main/java/com/cideldill/client/
│   │   ├── CidElDill.java              — public entry point (withDebug, debugCall)
│   │   ├── DebugClient.java            — HTTP transport (call/start, call/complete, poll)
│   │   ├── DebugProxy.java             — dynamic proxy wrapping arbitrary interfaces
│   │   ├── Serializer.java             — JSON serialization + SHA-512 CID computation
│   │   ├── CidCache.java              — LRU CID cache (thread-safe)
│   │   ├── CallAction.java            — action enum + deserialization (continue/poll/modify/skip/replace/raise)
│   │   ├── DebugState.java            — global enabled/disabled state
│   │   ├── StackTraceCapture.java     — capture Java stack traces in server format
│   │   ├── ProcessIdentity.java       — PID + process start time
│   │   └── Exceptions.java            — DebugProtocolError, DebugConnectionError
│   └── test/java/com/cideldill/client/
│       ├── CidElDillTest.java         — withDebug / debugCall unit tests
│       ├── DebugClientTest.java       — HTTP transport tests (mocked server)
│       ├── DebugProxyTest.java        — proxy interception tests
│       ├── SerializerTest.java        — JSON serialization + CID tests
│       ├── CidCacheTest.java          — LRU cache tests
│       ├── CallActionTest.java        — action dispatch tests
│       ├── StackTraceCaptureTest.java — stack trace formatting tests
│       └── IntegrationTest.java       — end-to-end with real server
└── README.md
```

---

## Dependencies

| Dependency | Purpose | Version |
|-----------|---------|---------|
| Jackson (`jackson-databind`) | JSON serialization/deserialization | 2.17+ |
| `java.net.http.HttpClient` | HTTP transport (JDK 11+) | built-in |
| `java.security.MessageDigest` | SHA-512 CID computation | built-in |
| JUnit 5 | Testing | 5.10+ |
| WireMock | HTTP server mocking for tests | 3.x |
| (optional) SLF4J | Logging facade | 2.x |

**Minimum Java version: 11** (for `java.net.http.HttpClient`).

---

## Component Design

### 1. `CidElDill` — Public Entry Point

The main user-facing class, mirroring Python's `with_debug()` and `debug_call()`.

```java
public final class CidElDill {

    // --- Mode control ---
    public static DebugInfo withDebug(String mode);            // "ON", "OFF", "VERBOSE"
    public static DebugInfo withDebug(String mode, String serverUrl);

    // --- Object wrapping ---
    public static <T> T withDebug(T object, Class<T> iface);  // returns dynamic proxy
    public static <T> T withDebug(String alias, T object, Class<T> iface);

    // --- Inline breakpoints ---
    public static <R> R debugCall(Callable<R> func);
    public static <R> R debugCall(String alias, Callable<R> func);

    // For calls that need explicit argument capture:
    public static <R> R debugCall(String methodName, Object target,
                                   Object[] args, Callable<R> func);

    // --- Cleanup ---
    public static void reset();  // for testing
}
```

**Key differences from Python:**
- Java requires explicit interface types for dynamic proxies (`Class<T> iface`).
- `debugCall` uses `Callable<R>` since Java lacks Python's `*args, **kwargs`.
  For rich argument capture, an overload accepts `(methodName, target, args, func)`.
- No async variant initially. Java's `CompletableFuture` variant can be added
  later if needed.

### 2. `DebugClient` — HTTP Transport

Handles all communication with the breakpoint server.

```java
public class DebugClient {

    public DebugClient(String serverUrl);
    public DebugClient(String serverUrl, int timeoutSeconds, int retryTimeoutSeconds);

    // Connection check
    public boolean checkConnection();

    // Function registration
    public void registerFunction(String functionName, String signature,
                                  Object target);

    // Call lifecycle
    public Map<String, Object> recordCallStart(
        String methodName, Object target, String targetCid,
        Object[] args, Map<String, Object> kwargs,
        Map<String, Object> callSite, String signature,
        String callType);

    public Map<String, Object> recordCallComplete(
        String callId, String status,
        Object result, Exception exception);

    // Polling
    public Map<String, Object> poll(Map<String, Object> action);

    // Deserialization helpers
    public Object deserializePayloadItem(Map<String, Object> payload);
    public List<Object> deserializePayloadList(List<Map<String, Object>> payloads);
    public Map<String, Object> deserializePayloadDict(
        Map<String, Map<String, Object>> payloads);
}
```

**All requests include:**
- `preferred_format: "json"`
- `serialization_format: "json"` on every payload item
- `process_pid` — from `ProcessHandle.current().pid()`
- `process_start_time` — captured once at client init via `ProcessHandle.current().info().startInstant()`

### 3. `DebugProxy` — Dynamic Proxy

Uses `java.lang.reflect.Proxy` to intercept method calls on interfaces.

```java
public class DebugProxy implements InvocationHandler {

    public static <T> T create(T target, Class<T> iface,
                                String alias, DebugClient client);

    @Override
    public Object invoke(Object proxy, Method method, Object[] args);
}
```

**Limitations vs. Python:**
- Java dynamic proxies only work with **interfaces**, not concrete classes.
  For concrete classes, users can either:
  - Extract an interface.
  - Use `debugCall()` for individual method calls.
  - (Future) Use ByteBuddy for class-based proxies.
- `equals`, `hashCode`, `toString` are forwarded to the real object without
  server interaction (matching Python's behavior for dunder methods).

### 4. `Serializer` — JSON + CID

```java
public class Serializer {

    // Serialize an object to JSON and compute CID
    public SerializedObject serialize(Object value);

    // Force serialize with data (always include bytes, ignore cache)
    public SerializedObject forceSerializeWithData(Object value);

    // Compute CID from JSON string
    public static String computeCid(String jsonString);

    // Build a payload item for the API
    public Map<String, Object> buildPayloadItem(Object value);
}

public record SerializedObject(
    String cid,            // 128-char hex SHA-512
    String data,           // JSON string
    String format          // always "json"
) {}
```

**CID computation:**
```
cid = sha512(json_string.getBytes(StandardCharsets.UTF_8)).toHexString()
```

The JSON string must be produced by Jackson with deterministic settings:
- `MapperFeature.SORT_PROPERTIES_ALPHABETICALLY` enabled
- `SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS` enabled
- No pretty-printing (compact output)

This ensures the same logical value always produces the same CID.

**Serializable types:**
- Java primitives and their wrappers (`int`, `Integer`, `long`, `double`, etc.)
- `String`
- `null`
- `List`, `Set`, `Map` (including nested)
- Arrays
- JavaBeans / POJOs with public getters
- Records
- Objects implementing a `toDebugJson()` convention (custom hook)

**Non-serializable fallback:**
- Objects that Jackson cannot serialize produce a placeholder:
  ```json
  {
    "__unserializable__": true,
    "type": "com.example.Foo",
    "toString": "Foo@1a2b3c",
    "fields": {"fieldA": "...", "fieldB": "..."}
  }
  ```
- Best-effort field extraction via reflection (public fields and getters).

### 5. `CidCache` — Thread-Safe LRU Cache

```java
public class CidCache {
    public CidCache(int maxSize);          // default 10_000
    public boolean contains(String cid);
    public void markSent(String cid);
    public void clear();
}
```

Internally uses `LinkedHashMap` with `removeEldestEntry` under
`ReentrantReadWriteLock`, or `ConcurrentHashMap` with LRU eviction.

### 6. `CallAction` — Action Dispatch

Mirrors Python's `execute_call_action`:

```java
public class CallAction {

    public enum ActionType {
        CONTINUE, POLL, MODIFY, SKIP, REPLACE, RAISE
    }

    public static Object execute(
        Map<String, Object> action,
        DebugClient client,
        Callable<Object> func,
        Object[] args,
        Map<String, Object> kwargs
    );
}
```

**Action behaviors (matching Python exactly):**

| Action | Behavior |
|--------|----------|
| `continue` | Execute `func` with original args, return result |
| `poll` | Long-poll `GET /api/poll/<pause_id>` until ready, then execute returned action |
| `modify` | Deserialize `modified_args` / `modified_kwargs` from server, call func with new args |
| `skip` | Deserialize `fake_result` from server, return without calling func |
| `replace` | Look up replacement function by name, call it with original args |
| `raise` | Deserialize exception type + message, throw as `RuntimeException` (or mapped type) |

### 7. `StackTraceCapture` — Call Site Capture

```java
public class StackTraceCapture {

    public static List<Map<String, Object>> capture(int skip);
}
```

Produces a list matching the Python format:
```json
[
  {
    "filename": "Calculator.java",
    "lineno": 42,
    "function": "add",
    "code_context": null
  }
]
```

Note: `code_context` is `null` for Java (source not available at runtime).
The stack frames come from `Thread.currentThread().getStackTrace()`.

### 8. `ProcessIdentity`

```java
public record ProcessIdentity(long pid, double startTime) {

    public static ProcessIdentity current();
}
```

---

## Wire Protocol Details

### Serialization Format Specifier

Every payload item sent by the Java client includes `serialization_format: "json"`.
The `preferred_format: "json"` field is set on `/api/call/start` requests.

**Request payload item structure (Java client):**
```json
{
  "cid": "128-char-hex-sha512",
  "data": "{\"key\": \"value\"}",
  "client_ref": 1,
  "serialization_format": "json"
}
```

When the CID has already been sent (present in CidCache):
```json
{
  "cid": "128-char-hex-sha512",
  "client_ref": 1,
  "serialization_format": "json"
}
```

### `/api/functions` — Register Function

**Request:**
```json
{
  "function_name": "add",
  "signature": "(int, int) -> int",
  "function_client_ref": 1,
  "function_cid": "abc123...",
  "function_data": "{\"class\": \"Calculator\", \"method\": \"add\"}",
  "function_serialization_format": "json"
}
```

### `/api/call/start` — Begin Call

**Request:**
```json
{
  "method_name": "add",
  "target": {
    "cid": "xyz...",
    "client_ref": 1,
    "data": "{...}",
    "serialization_format": "json"
  },
  "target_cid": "xyz...",
  "args": [
    {"cid": "a1...", "client_ref": 2, "data": "5", "serialization_format": "json"},
    {"cid": "b1...", "client_ref": 3, "data": "3", "serialization_format": "json"}
  ],
  "kwargs": {},
  "call_site": {
    "timestamp": 1707374400.123,
    "stack_trace": [
      {"filename": "Main.java", "lineno": 42, "function": "main", "code_context": null}
    ]
  },
  "signature": "(int, int) -> int",
  "call_type": "inline",
  "process_pid": 12345,
  "process_start_time": 1707374398.0,
  "preferred_format": "json"
}
```

**Response (continue):**
```json
{"call_id": "call-001", "action": "continue"}
```

**Response (pause):**
```json
{
  "call_id": "call-001",
  "action": "poll",
  "poll_url": "/api/poll/pause-001",
  "poll_interval_ms": 100,
  "timeout_ms": 60000
}
```

**Response (CID not found):**
```json
{
  "error": "cid_not_found",
  "missing_cids": ["abc123...", "def456..."]
}
```

### `/api/call/complete` — Report Result

**Success:**
```json
{
  "call_id": "call-001",
  "timestamp": 1707374401.0,
  "status": "success",
  "result_cid": "res...",
  "result_client_ref": 4,
  "result_data": "{\"result\": 8}",
  "result_serialization_format": "json",
  "process_pid": 12345,
  "process_start_time": 1707374398.0
}
```

**Exception:**
```json
{
  "call_id": "call-001",
  "timestamp": 1707374401.0,
  "status": "exception",
  "exception_type": "ArithmeticException",
  "exception_message": "/ by zero",
  "exception_cid": "exc...",
  "exception_client_ref": 5,
  "exception_data": "{\"type\": \"ArithmeticException\", \"message\": \"/ by zero\"}",
  "exception_serialization_format": "json",
  "process_pid": 12345,
  "process_start_time": 1707374398.0
}
```

### `/api/poll/<pause_id>` — Long Poll

**Waiting:**
```json
{"status": "waiting"}
```

**Ready with action:**
```json
{
  "status": "ready",
  "action": {
    "action": "continue",
    "call_id": "call-001"
  }
}
```

### Server Response Actions with Data

When the server sends a `modify` action, the response includes serialized data.
The `serialization_format` field on each item tells the Java client how to
decode:

```json
{
  "action": "modify",
  "call_id": "call-001",
  "modified_args": [
    {"cid": "...", "data": "10", "serialization_format": "json"},
    {"cid": "...", "data": "20", "serialization_format": "json"}
  ],
  "modified_kwargs": {}
}
```

For `skip`:
```json
{
  "action": "skip",
  "call_id": "call-001",
  "fake_result_cid": "...",
  "fake_result_data": "42",
  "fake_result_serialization_format": "json"
}
```

For `raise`:
```json
{
  "action": "raise",
  "exception_type": "IllegalArgumentException",
  "exception_message": "value out of range"
}
```

**Important:** When the Java client requested `preferred_format: "json"`, the
server encodes all response payloads (modified_args, fake_result, etc.) using
JSON format. The Java client must check the `serialization_format` field on each
item: if it is `"dill"`, the client cannot decode it and should throw a
`DebugProtocolError`.

---

## CID Not Found Recovery

When the server responds with `{"error": "cid_not_found", "missing_cids": [...]}`:

1. The client evicts the missing CIDs from CidCache.
2. The client rebuilds the request with `data` included for the missing CIDs.
3. The client retries the request (up to 2 retries).

This matches the Python client behavior exactly.

---

## Exception Mapping

When the server sends a `raise` action:

| Server `exception_type` | Java Exception |
|-------------------------|---------------|
| `ValueError` | `IllegalArgumentException` |
| `TypeError` | `IllegalArgumentException` |
| `RuntimeError` | `RuntimeException` |
| `KeyError` | `NoSuchElementException` |
| `IndexError` | `IndexOutOfBoundsException` |
| `AttributeError` | `NoSuchFieldException` wrapped in `RuntimeException` |
| `IOError` / `OSError` | `IOException` wrapped in `UncheckedIOException` |
| (anything else) | `RuntimeException` with message including original type |

---

## Implementation Phases

### Phase 1: Core Serialization
- [ ] `Serializer` — JSON serialization with deterministic output
- [ ] `SerializedObject` record
- [ ] SHA-512 CID computation
- [ ] `CidCache` — thread-safe LRU
- [ ] Unserializable object placeholder fallback

### Phase 2: HTTP Transport
- [ ] `DebugClient` — HTTP client using `java.net.http.HttpClient`
- [ ] `checkConnection()` via `GET /api/breakpoints`
- [ ] `registerFunction()` via `POST /api/functions`
- [ ] `recordCallStart()` via `POST /api/call/start`
- [ ] `recordCallComplete()` via `POST /api/call/complete`
- [ ] `poll()` via `GET /api/poll/<pause_id>`
- [ ] CID not found recovery (retry with data)
- [ ] `ProcessIdentity` for PID / start time
- [ ] `StackTraceCapture` for call site info

### Phase 3: Action Dispatch
- [ ] `CallAction.execute()` — dispatch on action type
- [ ] `continue` — call func, return result
- [ ] `poll` — long-poll loop, then dispatch
- [ ] `modify` — deserialize new args from JSON, call func
- [ ] `skip` — deserialize fake result, return without calling
- [ ] `replace` — look up replacement, call it
- [ ] `raise` — map exception type, throw

### Phase 4: Public API
- [ ] `CidElDill.withDebug("ON"/"OFF"/"VERBOSE")`
- [ ] `CidElDill.withDebug(obj, Interface.class)` — dynamic proxy
- [ ] `CidElDill.debugCall(callable)` — inline breakpoint
- [ ] `CidElDill.debugCall("alias", callable)` — with alias
- [ ] `CidElDill.debugCall(methodName, target, args, callable)` — full capture
- [ ] `DebugProxy` — `InvocationHandler` implementation
- [ ] `DebugState` — global ON/OFF state management
- [ ] Environment variable support (`CIDELDILL` env var parsing)

### Phase 5: Integration Testing
- [ ] End-to-end tests with a real breakpoint server instance
- [ ] Cross-language test: Java client + Python server + browser UI
- [ ] Verify CID deduplication works across Java and Python clients

---

## Full Test List

Tests are organized by component and listed in TDD execution order. Each test
describes a single behavior. Where there is ambiguity, the test name is the
specification.

### Serializer Tests (`SerializerTest.java`)

#### CID Computation
1. `computeCid_emptyString_returnsExpectedSha512` — `sha512("".getBytes(UTF_8))` matches known hash
2. `computeCid_helloWorld_returnsExpectedSha512` — verify against Python `hashlib.sha512(b"hello world").hexdigest()`
3. `computeCid_unicodeString_handlesUtf8Encoding` — `"日本語"` produces correct CID
4. `computeCid_returnValue_is128CharHexString` — length is always 128, all hex chars

#### JSON Serialization
5. `serialize_null_producesJsonNull` — `null` → `"null"`
6. `serialize_integer_producesJsonNumber` — `42` → `"42"`
7. `serialize_long_producesJsonNumber` — `Long.MAX_VALUE` → correct JSON number
8. `serialize_double_producesJsonNumber` — `3.14` → `"3.14"`
9. `serialize_doubleNaN_producesPlaceholder` — `NaN` is not valid JSON; fallback
10. `serialize_doubleInfinity_producesPlaceholder` — `Infinity` is not valid JSON; fallback
11. `serialize_boolean_producesJsonBoolean` — `true` → `"true"`
12. `serialize_string_producesQuotedJson` — `"hello"` → `"\"hello\""`
13. `serialize_stringWithSpecialChars_escapesCorrectly` — newlines, quotes, backslashes
14. `serialize_emptyList_producesEmptyArray` — `[]` → `"[]"`
15. `serialize_listOfIntegers_producesJsonArray` — `[1, 2, 3]` → `"[1,2,3]"`
16. `serialize_nestedList_producesNestedArray` — `[[1], [2]]`
17. `serialize_emptyMap_producesEmptyObject` — `{}` → `"{}"`
18. `serialize_mapWithStringKeys_producesJsonObject` — `{"a": 1}` → `"{\"a\":1}"`
19. `serialize_mapKeysAreSorted_forDeterministicCid` — `{"b":2, "a":1}` → `{"a":1,"b":2}`
20. `serialize_nestedMap_producesNestedObject` — maps of maps
21. `serialize_mixedCollection_serializesCorrectly` — list of maps, maps of lists
22. `serialize_javaArray_serializesAsJsonArray` — `int[]`, `String[]`
23. `serialize_set_serializesAsSortedArray` — sets must be sorted for deterministic CID
24. `serialize_pojo_serializesPublicGetters` — `class Foo { int getX(); }` → `{"x": 1}`
25. `serialize_record_serializesFields` — Java 16+ records
26. `serialize_enum_serializesAsString` — `Color.RED` → `"RED"`

#### Deterministic Output
27. `serialize_sameObject_producesSameCidEveryTime` — repeated calls return same CID
28. `serialize_equalObjects_produceSameCid` — two `new ArrayList<>(List.of(1,2,3))` produce same CID
29. `serialize_mapInsertionOrder_doesNotAffectCid` — `{a:1, b:2}` vs `{b:2, a:1}` same CID

#### Unserializable Fallback
30. `serialize_unserializableObject_producesPlaceholder` — e.g., `Thread.currentThread()`
31. `serialize_unserializablePlaceholder_containsTypeName` — includes fully-qualified class name
32. `serialize_unserializablePlaceholder_containsToString` — includes `toString()` output
33. `serialize_unserializablePlaceholder_containsPublicFields` — best-effort field extraction
34. `serialize_objectWithCircularRef_producesPlaceholder` — `A.child = B; B.parent = A`

#### Payload Item Building
35. `buildPayloadItem_includesCidDataAndFormat` — all three fields present
36. `buildPayloadItem_formatIsAlwaysJson` — `serialization_format` == `"json"`
37. `buildPayloadItem_cidMatchesManualComputation` — CID matches `computeCid(json)`

#### forceSerializeWithData
38. `forceSerializeWithData_alwaysIncludesData` — even if CID is in cache
39. `forceSerializeWithData_sameAsSerialized_cidMatches` — CID identical to serialize()

### CidCache Tests (`CidCacheTest.java`)

40. `newCache_containsReturnsFalse` — empty cache has no CIDs
41. `markSent_thenContains_returnsTrue` — basic insert + lookup
42. `markSent_sameCidTwice_noDuplicate` — idempotent
43. `cache_evictsOldestWhenFull` — insert maxSize+1, first entry evicted
44. `cache_accessRefreshesEntry` — LRU: accessing an entry moves it to end
45. `cache_clear_removesAllEntries` — `clear()` empties the cache
46. `cache_threadSafety_concurrentInserts` — 100 threads inserting concurrently, no exception
47. `cache_threadSafety_concurrentContainsAndInsert` — read + write concurrently

### DebugClient Tests (`DebugClientTest.java`)

#### Connection
48. `checkConnection_serverReachable_returnsTrue` — mock server returns 200 on `/api/breakpoints`
49. `checkConnection_serverUnreachable_returnsFalse` — connection refused
50. `checkConnection_serverReturns500_returnsFalse` — server error

#### Function Registration
51. `registerFunction_sendsCorrectPayload` — verify JSON body to `/api/functions`
52. `registerFunction_includesSerializationFormat` — `function_serialization_format: "json"`
53. `registerFunction_serverReturnsOk_noException` — 200 response
54. `registerFunction_serverReturnsError_throwsException` — non-200 response

#### Call Start
55. `recordCallStart_sendsAllRequiredFields` — method_name, target, args, kwargs, call_site, etc.
56. `recordCallStart_includesPreferredFormatJson` — `preferred_format: "json"`
57. `recordCallStart_includesSerializationFormatOnEachItem` — target, each arg, each kwarg
58. `recordCallStart_includesProcessPidAndStartTime` — `process_pid`, `process_start_time`
59. `recordCallStart_includesCallType` — `call_type` field
60. `recordCallStart_omitsDataForCachedCids` — CID in cache → no `data` field
61. `recordCallStart_includesDataForNewCids` — CID not in cache → `data` field present
62. `recordCallStart_continueAction_returnsCallId` — parse `{"action": "continue", "call_id": "..."}`
63. `recordCallStart_pollAction_returnsPollUrl` — parse `{"action": "poll", "poll_url": "..."}`
64. `recordCallStart_emptyArgs_sendsEmptyArray` — `args: []`
65. `recordCallStart_emptyKwargs_sendsEmptyObject` — `kwargs: {}`
66. `recordCallStart_nullSignature_omitsField` — signature is optional

#### CID Not Found Recovery
67. `recordCallStart_cidNotFound_retriesWithData` — evict + resend with `data`
68. `recordCallStart_cidNotFound_evictsMissingFromCache` — cache no longer contains evicted CIDs
69. `recordCallStart_cidNotFound_maxRetries_throwsError` — after 2 retries, gives up
70. `recordCallStart_cidNotFound_singleMissing_retriesOnlyThatCid` — only the missing CID gets data

#### Call Complete
71. `recordCallComplete_success_sendsResultPayload` — verify JSON body
72. `recordCallComplete_success_includesResultSerializationFormat` — `result_serialization_format: "json"`
73. `recordCallComplete_exception_sendsExceptionPayload` — exception_type + exception_message
74. `recordCallComplete_exception_includesExceptionSerializationFormat` — `exception_serialization_format: "json"`
75. `recordCallComplete_exception_includesExceptionCidAndData` — serialized exception
76. `recordCallComplete_serverReturnsAction_returnsAction` — post-completion action

#### Polling
77. `poll_waiting_pollsAgain` — `{"status": "waiting"}` → poll again
78. `poll_ready_returnsAction` — `{"status": "ready", "action": {...}}` → return action
79. `poll_respectsPollIntervalMs` — waits at least `poll_interval_ms` between polls
80. `poll_respectsTimeoutMs` — gives up after `timeout_ms`
81. `poll_serverError_throwsException` — non-200 during poll
82. `poll_networkError_retriesBeforeFailing` — transient failure → retry

#### Deserialization
83. `deserializePayloadItem_jsonFormat_returnsObject` — `{"data": "42", "serialization_format": "json"}`
84. `deserializePayloadItem_dillFormat_throwsError` — Java cannot decode dill
85. `deserializePayloadItem_noFormat_assumesDill_throwsError` — default is dill, Java can't decode
86. `deserializePayloadItem_missingData_lookupByCid_throwsError` — no local CID store
87. `deserializePayloadList_multipleItems_returnsAll` — list of items
88. `deserializePayloadDict_mapOfItems_returnsMap` — keyed items

### CallAction Tests (`CallActionTest.java`)

89. `execute_continueAction_callsFunc` — func is called, result returned
90. `execute_continueAction_passesOriginalArgs` — args not modified
91. `execute_pollAction_pollsThenExecutes` — polls until ready, then dispatches
92. `execute_modifyAction_deserializesNewArgs` — new args from server used
93. `execute_modifyAction_callsFuncWithNewArgs` — func called with modified args
94. `execute_modifyAction_emptyModifiedKwargs_ok` — kwargs can be empty
95. `execute_skipAction_doesNotCallFunc` — func is never invoked
96. `execute_skipAction_returnsFakeResult` — fake_result deserialized and returned
97. `execute_skipAction_fakeResultData_deserialized` — `fake_result_data` field decoded
98. `execute_skipAction_fakeResultCid_deserialized` — `fake_result_cid` field decoded
99. `execute_skipAction_noFakeResult_returnsNull` — missing fake_result → null
100. `execute_replaceAction_callsReplacementFunction` — registered replacement invoked
101. `execute_replaceAction_missingFunctionName_throwsProtocolError` — validation
102. `execute_replaceAction_unknownFunction_throwsProtocolError` — not registered
103. `execute_raiseAction_throwsMappedException` — e.g., `ValueError` → `IllegalArgumentException`
104. `execute_raiseAction_includesMessage` — exception message preserved
105. `execute_raiseAction_unknownType_throwsRuntimeException` — fallback
106. `execute_unknownAction_throwsProtocolError` — unrecognized action type
107. `execute_nestedPoll_pollReturnsPoll_pollsAgain` — poll → poll → continue
108. `execute_modifyAction_jsonSerializationFormat_works` — verify JSON decode
109. `execute_modifyAction_dillSerializationFormat_throwsError` — Java can't decode dill from server

### DebugProxy Tests (`DebugProxyTest.java`)

110. `proxy_methodCall_interceptedByClient` — verify recordCallStart called
111. `proxy_methodCall_returnValue_passedThrough` — result forwarded to caller
112. `proxy_methodCall_exception_propagated` — exception from func reaches caller
113. `proxy_methodCall_capturesStackTrace` — call_site includes Java stack
114. `proxy_methodCall_sendsCorrectMethodName` — method name matches
115. `proxy_methodCall_sendsTargetObject` — target serialized correctly
116. `proxy_methodCall_sendsArgs` — arguments serialized correctly
117. `proxy_equals_notIntercepted` — `equals()` forwarded directly
118. `proxy_hashCode_notIntercepted` — `hashCode()` forwarded directly
119. `proxy_toString_notIntercepted` — `toString()` forwarded directly
120. `proxy_multipleMethodCalls_eachIntercepted` — every call goes through server
121. `proxy_withAlias_registersWithAlias` — alias used in function registration
122. `proxy_callComplete_reportsSuccess` — recordCallComplete called on success
123. `proxy_callComplete_reportsException` — recordCallComplete called on exception
124. `proxy_continueAction_executesNormally` — server says continue, method runs
125. `proxy_skipAction_returnsServerResult` — server says skip, fake result returned
126. `proxy_modifyAction_callsWithNewArgs` — server modifies args
127. `proxy_raiseAction_throwsException` — server says raise

### CidElDill (Entry Point) Tests (`CidElDillTest.java`)

#### Mode Control
128. `withDebug_ON_enablesDebugging` — state becomes enabled
129. `withDebug_OFF_disablesDebugging` — state becomes disabled
130. `withDebug_VERBOSE_enablesDebugging` — verbose mode enabled
131. `withDebug_invalidMode_throwsException` — `"MAYBE"` → error
132. `withDebug_ON_checksServerConnection` — connection validated on enable
133. `withDebug_ON_serverUnreachable_throwsException` — fail-closed
134. `withDebug_ON_thenOFF_disablesDebugging` — toggle works
135. `withDebug_mustCallModeFirst_beforeWrapping` — calling withDebug(obj) before ON/OFF → error

#### Object Wrapping
136. `withDebug_object_debugOff_returnsOriginal` — NOP when disabled
137. `withDebug_object_debugOn_returnsProxy` — proxy when enabled
138. `withDebug_object_proxyImplementsInterface` — instanceof check passes
139. `withDebug_objectWithAlias_registersAlias` — alias passed to server
140. `withDebug_objectWithAlias_debugOff_returnsOriginal` — alias ignored when off

#### debugCall
141. `debugCall_debugOff_callsFuncDirectly` — no server contact
142. `debugCall_debugOff_returnsResult` — result from func
143. `debugCall_debugOn_contactsServer` — recordCallStart called
144. `debugCall_debugOn_reportsResult` — recordCallComplete called
145. `debugCall_withAlias_usesAliasAsMethodName` — alias in method_name
146. `debugCall_funcThrowsException_reportedException` — exception reported
147. `debugCall_funcThrowsException_propagatesToCaller` — exception re-thrown
148. `debugCall_withExplicitArgs_capturesArgs` — args sent to server
149. `debugCall_withExplicitTarget_capturesTarget` — target serialized
150. `debugCall_nestedDebugCall_bothIntercepted` — inner and outer both talk to server

#### Environment Variable
151. `env_CIDELDILL_ON_enablesDebugging` — `CIDELDILL=ON` auto-enables
152. `env_CIDELDILL_OFF_disablesDebugging` — `CIDELDILL=OFF`
153. `env_CIDELDILL_ONWithUrl_setsServerUrl` — `CIDELDILL="ON http://localhost:5174"`
154. `env_CIDELDILL_empty_noEffect` — empty string ignored
155. `env_CIDELDILL_invalidMode_throwsError` — `CIDELDILL="MAYBE"` → error

#### Reset
156. `reset_clearsState` — all state cleared
157. `reset_disablesDebugging` — debug off after reset
158. `reset_clearsCidCache` — CID cache emptied

### StackTraceCapture Tests (`StackTraceCaptureTest.java`)

159. `capture_returnsNonEmptyList` — at least one frame
160. `capture_firstFrame_isCallerMethod` — skip parameter works
161. `capture_frame_containsFilename` — `.java` file
162. `capture_frame_containsLineNumber` — positive integer
163. `capture_frame_containsFunctionName` — method name
164. `capture_frame_codeContextIsNull` — Java doesn't have source at runtime
165. `capture_syntheticFrames_filtered` — lambda$$, access$, etc. excluded

### ProcessIdentity Tests (`ProcessIdentityTest.java`)

166. `current_pidIsPositive` — `pid > 0`
167. `current_startTimeIsPositive` — `startTime > 0`
168. `current_pidMatchesRuntimePid` — matches `ProcessHandle.current().pid()`
169. `current_calledTwice_returnsSameValues` — cached / stable

### Exception Mapping Tests

170. `mapException_ValueError_returnsIllegalArgument` — `ValueError` → `IllegalArgumentException`
171. `mapException_TypeError_returnsIllegalArgument` — `TypeError` → `IllegalArgumentException`
172. `mapException_RuntimeError_returnsRuntimeException` — `RuntimeError` → `RuntimeException`
173. `mapException_KeyError_returnsNoSuchElement` — `KeyError` → `NoSuchElementException`
174. `mapException_unknownType_returnsRuntimeException` — `CustomError` → `RuntimeException`
175. `mapException_preservesMessage` — exception message kept
176. `mapException_emptyMessage_ok` — empty string allowed

### Integration Tests (`IntegrationTest.java`)

These require a running breakpoint server (started in test setup).

177. `integration_registerFunction_visibleInBreakpoints` — register, then GET /api/breakpoints shows it
178. `integration_callStart_continue_callComplete` — full happy path
179. `integration_callStart_pause_poll_continue` — breakpoint pauses, user continues via UI
180. `integration_cidDeduplication_secondCallOmitsData` — second call same object, no data
181. `integration_cidNotFound_recovers` — force cache evict, server requests resend
182. `integration_callStart_skip_returnsFakeResult` — breakpoint skips with fake result
183. `integration_callStart_modify_callsWithNewArgs` — breakpoint modifies args
184. `integration_callStart_raise_throwsException` — breakpoint injects exception
185. `integration_proxyWrapper_interceptsAllCalls` — wrap interface, multiple calls
186. `integration_debugCall_inlinePauseAndContinue` — debugCall with breakpoint
187. `integration_mixedClients_javaAndPython_sameServer` — both clients, same server instance
188. `integration_jsonSerializationFormat_displayedInUi` — server can render Java payloads
189. `integration_largePayload_serializesCorrectly` — large Map/List, verify CID
190. `integration_concurrentCalls_noDeadlock` — multiple threads calling simultaneously
191. `integration_serverRestart_clientReconnects` — server goes away and comes back
192. `integration_callComplete_postAction_handlesPoll` — post-completion poll

---

## Open Questions

1. **Dynamic proxy limitation**: Java's `java.lang.reflect.Proxy` only works for
   interfaces. Should we also support concrete class proxying via ByteBuddy or
   CGLIB? This adds a heavy dependency. Alternatively, document that users must
   either use `debugCall()` for concrete classes or extract an interface.

2. **Deterministic JSON for CID**: Jackson's output order depends on
   configuration. Should the plan mandate a specific ObjectMapper configuration
   (sorted keys, no pretty-print), or should we define a canonical JSON
   normalization step before hashing?

3. **Java Records vs. POJOs**: Should the serializer treat Java records specially
   (accessing components by name) vs. generic POJO getter introspection? Records
   are cleaner but require Java 16+.

4. **Async support**: Should we provide a `CompletableFuture`-based async API
   from the start, or defer it? The Python client has `async_debug_call`. Java
   applications commonly use threads rather than coroutines, so sync-with-threads
   may suffice initially.

5. **Replacement function registry**: The Python client has `get_function()` /
   `register_function()` for the `replace` action. How should Java handle this?
   A static registry `CidElDill.registerReplacement(String name, Callable fn)`?
   Or is replacement only useful for Python/JS where functions are first-class?

6. **`code_context` in stack traces**: Python captures the actual source line.
   Java cannot do this at runtime. Should we attempt to read `.java` source files
   from a configured source path, or always send `null`?

7. **CID compatibility with Python JSON**: If a Python client sends
   `preferred_format: "json"` and a Java client sends `preferred_format: "json"`
   for the same logical value, will the CIDs match? This depends on both
   producing identical JSON strings. Should we define a canonical form, or accept
   that CIDs are per-client and deduplication only works within a single client
   language?

8. **Build tool**: Maven or Gradle? Maven is more common in enterprise; Gradle is
   more flexible. Which should be the default?

9. **Minimum Java version**: The plan says Java 11 for `HttpClient`. Should we
   target Java 17 instead (current LTS, enables records, sealed classes, etc.)?

10. **Exception serialization**: When reporting exceptions via `/api/call/complete`,
    should the Java client include the full Java stack trace in the serialized
    exception data, or just type + message (matching Python)?

11. **Server-side rendering of Java objects**: The server uses dill to unpickle
    and render Python objects in the web UI. For JSON-serialized Java objects, the
    server will display raw JSON. Is this acceptable, or should the server have
    special formatting for Java object placeholders (e.g., showing class names)?

12. **Thread-local state vs. global state**: Python uses global `_state` with a
    lock. Java could use `ThreadLocal` for per-thread debug state or global state
    with synchronized access. Which model should we follow? (Global matches
    Python; ThreadLocal may be more natural for Java server apps.)
