# Google Notebooks MCP Gateway — Architectural Hardening & Implementation Plan v4.1

**Document Title:** Google Notebooks MCP Gateway — Architectural Hardening & Implementation Plan v4.1  
**Specification Version:** 4.1.0-STRICT  
**Status:** Approved for Implementation (Post Red-Team Audit Mitigation)  
**Parent Orchestrator:** Lead Systems Architect (Sub-Agent 1)  
**Synthesized By:** Sub-Agent 2 (Architect — Plan Synthesis)  
**Reference Notebook:** `"Google Notebooks MCP"` (`00000000-0000-0000-0000-000000000001`)  
**Hardware Profile:** Intel Core i3-N305 | 8 Threads (6-core pinned) | 6.4 GB RAM | Zero Swap | eMMC 5.1 Flash  

---

## Executive Summary & Red-Team Audit Synthesis

This document establishes the hardened, production-grade **Implementation Plan v4.1** for the Google Notebooks MCP Gateway. It formally ingests and resolves all 10 architectural vulnerabilities and edge failure modes identified during the Adversarial Red-Team Audit conducted by Sub-Agent 3 (Auditor).

### Audit Reconciliation Matrix (M-01 through M-10)

| Audit ID | Vulnerability Classification | Root Cause | Implemented v4.1 Architectural Mitigation |
| :--- | :--- | :--- | :--- |
| **M-01** | Session TOCTOU & Title Resolution Race | Unsynchronized async title resolution allows concurrent tools to bypass lock or read transitional state. | Added `self._session_mutex = asyncio.Lock()` in `BrokerDaemon`. Wrapped title resolution and lock acquisition. Queues concurrent calls or returns retryable `RESOLVING_SESSION` envelope. |
| **M-02** | IPC Framing Corruption on Scotty Streaming | Interleaving frames on single IPC socket from concurrent read/write tools during multi-part file chunking. | Added `self._companion_ipc_mutex = asyncio.Lock()`. Enforced exclusive socket ownership across all multi-part chunk dispatches. |
| **M-03** | Chromium MV3 300s Hard Kill Wall | MV3 background service workers are forcefully terminated by Chrome if any task runs $> 300\text{s}$. | Clamped single synchronous RPC operations to **240 seconds**. Streaming queries (`GenerateFreeFormStreamed`) emit native port chunks incrementally to continually reset event timers. |
| **M-04** | Silent Hang on Background Tab Discard | Chrome Memory Saver / low RAM discards background tab; promises hang until timeout. | Added proactive `chrome.tabs.update(tab.id, { autoDiscardable: false })`. Added reactive `chrome.tabs.onUpdated` listener for `changeInfo.discarded === true`, draining promises immediately with retryable `TAB_DISCARDED`. |
| **M-05** | Silent Upstream Schema Drift in `list_notes` | Guarding notes container with naive `if len(data[0]) > 17` returns empty `[]` when schema shifts. | Enforced loud failure canary: if `data` is malformed or lacks expected array signatures, return non-retryable `UPSTREAM_SCHEMA_DRIFT` error envelope. Never mask drift as empty notes. |
| **M-06** | Ungrounded Response Invariant Breach | Model responses with zero citations returned `ok: true`, violating `AGENTS.md` Rule XI.3. | Enforced strict rejection barrier: If citations list is empty (`len(citations) == 0`), fail closed with `ok: false` and `error.code: "UNGROUNDED_RESPONSE"`. |
| **M-07** | C-Level OS File Descriptor 2 Leakage | `sys.stderr = log_file` does not catch writes to native C file descriptor 2, corrupting native framing. | In `native_host.py`, execute `os.dup2(log_file.fileno(), 2)` at early boot before any library imports. Immediately pin `os.O_BINARY` on Windows stdio. |
| **M-08** | Non-Atomic SQLite Schema Migration | `CHECK` constraint expansion without atomic transaction crashes database under Chromebook `earlyoom`. | Wrapped migration in `PRAGMA user_version < 2` guard. Executed table swap strictly inside `PRAGMA foreign_keys = OFF; BEGIN IMMEDIATE TRANSACTION; ... PRAGMA user_version = 2; COMMIT; PRAGMA foreign_keys = ON;`. |
| **M-09** | Stream Consumption in Dynamic Interceptor | Attaching readers or reading `ReadableStream` bodies in fetch interceptors triggers `TypeError: Already read`. | Interceptor strictly inspects only string or `URLSearchParams` bodies (`bodyUsed` protected). Primary auth extraction remains isolated to `window.WIZ_global_data`. |
| **M-10** | Broad Pre-Query Readiness Blocking | Failed (`status=3`) or pending (`status=1`) non-targeted sources in notebook block querying healthy targeted sources. | Scoped pre-query readiness verification in `_handle_query_notebook` exclusively to `source_ids`. Untargeted unhealthy sources are ignored. |

---

## Phase 1: Lifecycle & Keep-Alive Hardening (Domain A)

### 1.1 Architectural Objectives
Eliminate all service worker idle evictions, OS pipe deadlocks, Chromium background tab discards, and 300-second execution kill walls while guaranteeing zero-leakage C-level descriptor redirection.

### 1.2 Target File Paths
- `src/mcp_gateway/host/native_host.py`
- `src/extension/service_worker.js`
- `src/extension/page-main.js`

### 1.3 Concrete Specifications & Code Implementations

#### 1.3.1 C-Level OS Descriptor Redirection & Windows Binary Mode (M-07)
In `src/mcp_gateway/host/native_host.py`, OS descriptor redirection must occur at line 1 before any standard library or runtime components initialize that could write warnings to stderr.

```python
#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# --- EARLY BOOT C-LEVEL REDIRECTION (M-07) ---
if sys.platform == "win32":
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

def early_c_stderr_redirection() -> None:
    """Redirects OS-level file descriptor 2 and Python sys.stderr to logfile."""
    try:
        log_dir = Path.home() / ".config" / "notebooklm-mcp-bridge"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(log_dir / "native_host_stderr.log", "a", encoding="utf-8", buffering=1)
        # Duplicate file descriptor into OS fd 2
        os.dup2(log_file.fileno(), 2)
        sys.stderr = log_file
    except Exception:
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, 2)
        except Exception:
            pass

early_c_stderr_redirection()
```

#### 1.3.2 Tab Discard Defense & Reactive Fail-Safe (M-04)
In `src/extension/service_worker.js`:
1. Proactive: Set `autoDiscardable: false` immediately upon tab creation.
2. Reactive: Monitor `chrome.tabs.onUpdated` for `changeInfo.discarded === true`.

```javascript
// Proactive Tab Creation
async function ensureNotebookTab() {
  for (const origin of NOTEBOOK_ORIGINS) {
    const tabs = await chrome.tabs.query({ url: origin + '/*' });
    if (tabs.length > 0) {
      // Ensure existing tab is protected from discard
      await chrome.tabs.update(tabs[0].id, { autoDiscardable: false });
      return tabs[0];
    }
  }

  const tab = await chrome.tabs.create({
    url: 'https://notebook.google.com/',
    active: false,
    pinned: true,
  });

  // M-04 Proactive Defense
  await chrome.tabs.update(tab.id, { autoDiscardable: false });

  provisionedTabId = tab.id;
  tabCreatedAt = Date.now();

  await waitForTabComplete(tab.id);
  await pollForWizData(tab.id);
  return tab;
}

// M-04 Reactive Fail-Safe
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.discarded === true && (tabId === provisionedTabId || pendingRequests.size > 0)) {
    console.warn(`[service_worker] Tab ${tabId} was discarded by Chrome. Draining pending requests.`);
    for (const [requestId, pending] of pendingRequests.entries()) {
      clearTimeout(pending.timeoutId);
      pending.reject({
        ok: false,
        error: {
          code: 'TAB_DISCARDED',
          message: 'Notebook tab was discarded by browser memory management. Please retry.',
          retryable: true,
        },
      });
    }
    pendingRequests.clear();
    if (tabId === provisionedTabId) {
      provisionedTabId = null;
      tabCreatedAt = 0;
    }
  }
});
```

#### 1.3.3 MV3 240-Second Hard Execution Ceiling & Stream Reset (M-03)
In `src/extension/service_worker.js` and `page-main.js`:
- Hard cap on single synchronous commands: **240 seconds** (100% margin below the 300s MV3 process termination threshold).
- Incremental native chunking: For streaming responses, each chunk is forwarded immediately over `nativePort.postMessage({ type: 'stream_chunk', requestId, chunk })`, resetting Chrome's event-driven idle timer.

```javascript
// In service_worker.js sendCommandToPage
const MAX_RPC_TIMEOUT_MS = 240_000; // 240 seconds hard ceiling (M-03)

function sendCommandToPage(tabId, command) {
  return new Promise((resolve, reject) => {
    let timeoutMs = typeof command?.payload?.timeout_seconds === 'number'
      ? command.payload.timeout_seconds * 1000
      : (command?.command === 'query_stream' ? 240_000 : 30_000);

    if (timeoutMs > MAX_RPC_TIMEOUT_MS) {
      timeoutMs = MAX_RPC_TIMEOUT_MS;
    }

    const timeoutId = setTimeout(() => {
      pendingRequests.delete(command.requestId);
      reject({
        ok: false,
        error: {
          code: 'RPC_EXECUTION_TIMEOUT',
          message: `RPC operation exceeded maximum MV3 safety ceiling of 240s (${timeoutMs}ms).`,
          retryable: true,
        },
      });
    }, timeoutMs);

    pendingRequests.set(command.requestId, { resolve, reject, timeoutId });
    // ... dispatch to tab ...
  });
}
```

#### 1.3.4 Safe Fetch Interceptor — Zero Stream Consumption (M-09)
In `src/extension/page-main.js`, ensure that request inspection never accesses `request.body.getReader()` or consumes the body stream:

```javascript
// M-09: Safe Request Body Inspection
function inspectRequestBodySafely(body) {
  if (typeof body === 'string') {
    return body;
  }
  if (body instanceof URLSearchParams) {
    return body.toString();
  }
  // CRITICAL: NEVER touch ReadableStream or FormData streams to prevent bodyUsed = true
  return null;
}
```

### 1.4 Unit & Integration Test Specifications
- `tests/test_native_host_lifecycle.py`:
  - `test_early_c_level_stderr_redirection`: Verify file descriptor 2 matches logfile stat ino/dev.
  - `test_windows_binary_stdio_mode`: Mock `msvcrt.setmode` invocation asserting `os.O_BINARY`.
  - `test_tab_discard_event_drain`: Dispatch synthetic `chrome.tabs.onUpdated` with `changeInfo.discarded = true`; assert all pending futures resolve with `TAB_DISCARDED` error envelope.
  - `test_mv3_timeout_clamped_to_240s`: Pass `timeout_seconds: 600`; assert timer triggers rejection at $\le 240\text{s}$.

---

## Phase 2: Human-Centric Gating & Targeted RAG (Domain B)

### 2.1 Architectural Objectives
Safely allow human-readable `title` selection alongside `notebook_id`, eliminate TOCTOU race conditions via a dedicated session mutex, enable targeted RAG querying via `source_ids`, and strictly enforce the zero-citation ungrounded response rejection barrier.

### 2.2 Target File Paths
- `src/mcp_gateway/schemas/tools.py`
- `src/mcp_gateway/broker/broker.py`
- `src/mcp_gateway/broker/session.py`

### 2.3 Schemas (Pydantic v2 & JSON Schema)

#### 2.3.1 `select_notebook` Schema with Title Support
```python
# Pydantic v2 Closed Schema
class SelectNotebookInput(BaseModel):
    """Pydantic schema for select_notebook."""
    model_config = ConfigDict(extra="forbid")

    notebook_id: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def check_at_least_one_identifier(self) -> SelectNotebookInput:
        if not self.notebook_id and not self.title:
            raise ValueError("Must provide either 'notebook_id' or 'title'.")
        return self
```

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "notebook_id": {
      "type": "string",
      "minLength": 1
    },
    "title": {
      "type": "string",
      "minLength": 1
    }
  },
  "anyOf": [
    { "required": ["notebook_id"] },
    { "required": ["title"] }
  ]
}
```

#### 2.3.2 `query_notebook` Schema with `source_ids` Gating
```python
class QueryNotebookInput(BaseModel):
    """Pydantic schema for query_notebook."""
    model_config = ConfigDict(extra="forbid")

    notebook_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=2000)
    request_key: str = Field(min_length=1)
    source_ids: list[str] | None = None
    timeout_seconds: int = Field(default=240, ge=10, le=240)
```

### 2.4 Concrete Specifications & Mutex Synchronization

#### 2.4.1 Session Mutex & Title Resolution (M-01)
In `src/mcp_gateway/broker/broker.py`:
- Introduce `self._session_mutex = asyncio.Lock()`.
- Wrap title resolution and ADR-011 lock transitions inside `self._session_mutex`.

```python
class BrokerDaemon:
    def __init__(self, config: BrokerConfig | None = None) -> None:
        # ...
        self._session_mutex = asyncio.Lock()  # M-01 Mutex
        self._is_resolving_session = False

    async def _handle_select_notebook(self, command: dict[str, Any]) -> dict[str, Any]:
        """Resolves notebook by ID or title and establishes ADR-011 session lock."""
        # Check if already locked without lock contention
        if self._session_mutex.locked():
            return make_error(
                "RESOLVING_SESSION",
                "Session title resolution or lock acquisition is currently in progress. Please retry.",
                retryable=True,
            ).to_dict()

        async with self._session_mutex:
            nb_id = command.get("notebook_id")
            title = command.get("title")

            if not nb_id and title:
                # Title resolution loop
                list_res = await self._handle_list_notebooks({"page_size": 100})
                if not list_res.get("ok"):
                    return list_res

                matching = [
                    nb for nb in list_res.get("notebooks", [])
                    if nb.get("title", "").strip().lower() == title.strip().lower()
                ]

                if not matching:
                    return make_error(
                        NOT_FOUND,
                        f"No allowlisted notebook found matching title {title!r}.",
                        retryable=False,
                    ).to_dict()

                if len(matching) > 1:
                    matching_ids = [m["id"] for m in matching]
                    return make_error(
                        INVALID_ARGUMENT,
                        f"Ambiguous title {title!r} matched {len(matching)} notebooks ({matching_ids}). Please specify notebook_id.",
                        retryable=False,
                    ).to_dict()

                nb_id = matching[0]["id"]

            assert nb_id is not None
            self.reload_allowlist()
            assert self.allowlist is not None
            is_allowed = is_notebook_allowed(self.allowlist, str(nb_id))

            result = await self.session_lock.select_notebook(str(nb_id), is_allowed)
            return result
```

#### 2.4.2 Strict Grounding Verification Barrier (M-06)
In `_handle_query_notebook()`:
```python
# M-06: Strict Grounding Enforcement (AGENTS.md Rule XI.3)
if len(normalized_citations) == 0:
    self.journal.transition(request_key, MutationState.REJECTED)
    return make_error(
        "UNGROUNDED_RESPONSE",
        "Model query response contained zero citations. Ungrounded responses are strictly rejected per AGENTS.md Rule XI.3.",
        retryable=False,
    ).to_dict()
```

#### 2.4.3 Targeted Source Readiness Scoping (M-10)
In `_handle_query_notebook()`:
```python
# M-10: Pre-query readiness verification scoped strictly to targeted sources
target_source_ids = command.get("source_ids")
if target_source_ids:
    sources_res = await self._handle_list_sources({"notebook_id": nb_id})
    if sources_res.get("ok"):
        all_sources = {s["id"]: s for s in sources_res.get("sources", [])}
        for s_id in target_source_ids:
            if s_id not in all_sources:
                return make_error(
                    NOT_FOUND,
                    f"Targeted source {s_id!r} not found in notebook.",
                    retryable=False,
                ).to_dict()
            s_status = all_sources[s_id].get("status")
            if s_status != "READY":
                return make_error(
                    "SOURCE_NOT_READY",
                    f"Targeted source {s_id!r} is not READY (current status: {s_status}).",
                    retryable=True,
                ).to_dict()
```

### 2.5 Unit & Integration Test Specifications
- `tests/test_session_title_gating.py`:
  - `test_select_notebook_by_title_success`: Provide title `"Google Notebooks MCP"`, verify resolution to `b61be5ed-...`.
  - `test_select_notebook_ambiguous_title_error`: Mock list returning 2 notebooks with title `"Research"`; verify rejection with `INVALID_ARGUMENT`.
  - `test_session_mutex_toctou_prevention`: Fire concurrent `select_notebook` and `list_sources`; assert `RESOLVING_SESSION` or serialized execution.
  - `test_ungrounded_response_rejection`: Query mock returning empty citations; verify `UNGROUNDED_RESPONSE` and journal status `rejected`.
  - `test_targeted_source_readiness_isolation`: Notebook has Source A (`READY`) and Source B (`ERROR`). Target only Source A; verify query succeeds.

---

## Phase 3: First-Class Note Management & SQLite State Journaling (Domain C)

### 3.1 Architectural Objectives
Promote Notes to first-class citizens in the MCP tool catalog, implement loud failure canaries for the `rLM1Ne` note container, and execute an atomic, crash-resilient SQLite migration under `PRAGMA user_version`.

### 3.2 Target File Paths
- `src/mcp_gateway/storage/journal.py`
- `src/mcp_gateway/storage/schema.sql`
- `src/mcp_gateway/broker/broker.py`
- `src/mcp_gateway/schemas/tools.py`

### 3.3 Schemas (Pydantic v2 & JSON Schema)

#### 3.3.1 `create_note`, `list_notes`, `delete_note` Schemas
```python
class CreateNoteInput(BaseModel):
    """Pydantic schema for create_note."""
    model_config = ConfigDict(extra="forbid")

    notebook_id: str = Field(min_length=1)
    title: str = Field(default="Untitled Note", min_length=1, max_length=255)
    content: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)

class ListNotesInput(BaseModel):
    """Pydantic schema for list_notes."""
    model_config = ConfigDict(extra="forbid")

    notebook_id: str = Field(min_length=1)
    page_size: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None

class DeleteNoteInput(BaseModel):
    """Pydantic schema for delete_note."""
    model_config = ConfigDict(extra="forbid")

    notebook_id: str = Field(min_length=1)
    note_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
```

```json
{
  "create_note": {
    "type": "object",
    "additionalProperties": false,
    "required": ["notebook_id", "content", "idempotency_key"],
    "properties": {
      "notebook_id": { "type": "string", "minLength": 1 },
      "title": { "type": "string", "maxLength": 255 },
      "content": { "type": "string", "minLength": 1 },
      "idempotency_key": { "type": "string", "minLength": 1 }
    }
  },
  "list_notes": {
    "type": "object",
    "additionalProperties": false,
    "required": ["notebook_id"],
    "properties": {
      "notebook_id": { "type": "string", "minLength": 1 },
      "page_size": { "type": "integer", "minimum": 1, "maximum": 100, "default": 20 },
      "cursor": { "type": "string" }
    }
  },
  "delete_note": {
    "type": "object",
    "additionalProperties": false,
    "required": ["notebook_id", "note_id", "idempotency_key"],
    "properties": {
      "notebook_id": { "type": "string", "minLength": 1 },
      "note_id": { "type": "string", "minLength": 1 },
      "idempotency_key": { "type": "string", "minLength": 1 }
    }
  }
}
```

### 3.4 Concrete Specifications & Database Migration

#### 3.4.1 Atomic SQLite Schema Migration with Version Pragma (M-08)
In `src/mcp_gateway/storage/journal.py`:
```python
def _run_migrations(conn: sqlite3.Connection) -> None:
    """Executes atomic schema migrations guarded by PRAGMA user_version."""
    cursor = conn.execute("PRAGMA user_version;")
    current_version = cursor.fetchone()[0]

    if current_version < 2:
        # Atomic table recreation for expanded CHECK constraints
        migration_sql = """
        PRAGMA foreign_keys = OFF;
        BEGIN IMMEDIATE TRANSACTION;

        CREATE TABLE IF NOT EXISTS mutation_journal_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_key TEXT NOT NULL UNIQUE,
            notebook_id TEXT NOT NULL,
            operation_type TEXT NOT NULL CHECK(operation_type IN ('add_source', 'query_notebook', 'create_note', 'delete_note')),
            payload_hash TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'prepared' CHECK(state IN ('prepared', 'sent', 'confirmed', 'rejected', 'unknown')),
            assigned_source_id TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );

        INSERT INTO mutation_journal_v2 (
            id, request_key, notebook_id, operation_type, payload_hash, state, assigned_source_id, created_at, updated_at
        )
        SELECT id, request_key, notebook_id, operation_type, payload_hash, state, assigned_source_id, created_at, updated_at
        FROM mutation_journal;

        DROP TABLE mutation_journal;
        ALTER TABLE mutation_journal_v2 RENAME TO mutation_journal;

        CREATE UNIQUE INDEX IF NOT EXISTS idx_mutation_journal_request_key ON mutation_journal(request_key);
        PRAGMA user_version = 2;
        COMMIT;
        PRAGMA foreign_keys = ON;
        """
        conn.executescript(migration_sql)
```

#### 3.4.2 Loud Schema Canary in `_handle_list_notes` (M-05)
In `src/mcp_gateway/broker/broker.py`:
```python
async def _handle_list_notes(self, command: dict[str, Any]) -> dict[str, Any]:
    nb_id = str(command["notebook_id"])
    rpc_payload = make_get_metadata_payload(nb_id)
    res = await self.send_to_companion("batchexecute", {"rpcId": "rLM1Ne", "paramsJson": rpc_payload, "notebookId": nb_id})
    if not res.get("ok"):
        return res

    body = str(res.get("body", ""))
    decoder = BatchexecuteStreamDecoder()
    records = decoder.feed(body.encode("utf-8"))

    found_container = False
    raw_notes: list[Any] = []

    for record in records:
        if record.get("rpc_id") == "rLM1Ne":
            data = record.get("data")
            if not isinstance(data, list) or len(data) == 0 or not isinstance(data[0], list):
                # M-05: Fail loud on invalid top-level envelope
                return make_error(
                    "UPSTREAM_SCHEMA_DRIFT",
                    f"Invalid rLM1Ne response envelope structure: {type(data)}",
                    retryable=False,
                ).to_dict()

            container = data[0]
            found_container = True

            # Loud Canary: Verify index 17 existence and signature
            if len(container) <= 17:
                return make_error(
                    "UPSTREAM_SCHEMA_DRIFT",
                    f"rLM1Ne container length is {len(container)} (expected > 17 for notes array). Upstream schema shifted.",
                    retryable=False,
                ).to_dict()

            notes_array = container[17]
            if not isinstance(notes_array, list):
                return make_error(
                    "UPSTREAM_SCHEMA_DRIFT",
                    f"rLM1Ne container[17] is not an array (type: {type(notes_array)}). Upstream schema shifted.",
                    retryable=False,
                ).to_dict()

            raw_notes = notes_array
            break

    if not found_container:
        return make_error(
            "UPSTREAM_SCHEMA_DRIFT",
            "rLM1Ne record missing from response stream.",
            retryable=False,
        ).to_dict()

    notes: list[dict[str, Any]] = []
    for n in raw_notes:
        if isinstance(n, list) and len(n) > 4:
            note_id = str(n[0][0]) if (isinstance(n[0], list) and n[0]) else str(n[0])
            note_title = str(n[4]) if n[4] is not None else ""
            note_content = str(n[1]) if len(n) > 1 and n[1] is not None else ""
            notes.append({"id": note_id, "title": note_title, "content": note_content})

    return {"ok": True, "notes": notes}
```

### 3.5 Unit & Integration Test Specifications
- `tests/test_notes_and_migration.py`:
  - `test_sqlite_user_version_migration`: Start with version 1 database; run initialization; assert `PRAGMA user_version == 2` and new CHECK constraint active.
  - `test_create_note_journal_state_machine`: Verify `create_note` passes `prepared -> sent -> confirmed`.
  - `test_list_notes_loud_canary_failure`: Mock `rLM1Ne` with `len(data[0]) == 10`; assert `UPSTREAM_SCHEMA_DRIFT` error returned.
  - `test_delete_note_idempotency`: Repeat delete with identical `idempotency_key`; verify rejection of duplicate or confirmation of cached state.

---

## Phase 4: Edge Memory Governance & Segmented Scotty Chunk Streaming (Domain D)

### 4.1 Architectural Objectives
Enforce strict physical memory protection on the 6.4 GB Chromebook development node, introduce socket-level exclusivity for large file uploads, and stream Scotty binary data in bounded 512 KiB segments without frame interleaving.

### 4.2 Target File Paths
- `src/mcp_gateway/broker/broker.py`
- `src/mcp_gateway/host/native_host.py`
- `src/extension/service_worker.js`
- `src/extension/page-main.js`

### 4.3 Concrete Specifications & Mutex Synchronization

#### 4.3.1 IPC Socket Exclusivity & Scotty Chunk Mutex (M-02)
In `src/mcp_gateway/broker/broker.py`:
- Introduce `self._companion_ipc_mutex = asyncio.Lock()`.
- Guard `_active_companion_writer` with `self._companion_ipc_mutex` during multi-part file chunk transmission.

```python
class BrokerDaemon:
    def __init__(self, config: BrokerConfig | None = None) -> None:
        # ...
        self._companion_ipc_mutex = asyncio.Lock()  # M-02 Mutex

    async def send_to_companion_exclusive(
        self,
        command: str,
        payload: dict[str, Any],
        timeout_seconds: float = 60.0,
    ) -> dict[str, Any]:
        """Sends command to companion holding socket lock for entire duration."""
        async with self._companion_ipc_mutex:
            return await self.send_to_companion(command, payload, timeout_seconds)

    async def _stream_scotty_chunks(
        self,
        source_id: str,
        filename: str,
        notebook_id: str,
        file_bytes: bytes,
    ) -> dict[str, Any]:
        """Streams multi-part file chunks holding companion IPC lock exclusively."""
        chunk_size = 512 * 1024  # 512 KiB bounded chunk
        total_chunks = math.ceil(len(file_bytes) / chunk_size)

        async with self._companion_ipc_mutex:  # M-02 Invariant: Lock socket for ALL chunks
            for idx in range(total_chunks):
                start = idx * chunk_size
                end = min(start + chunk_size, len(file_bytes))
                chunk_b64 = base64.b64encode(file_bytes[start:end]).decode("ascii")

                msg = {
                    "sourceId": source_id,
                    "filename": filename,
                    "notebookId": notebook_id,
                    "chunkIndex": idx,
                    "totalChunks": total_chunks,
                    "isLastChunk": (idx == total_chunks - 1),
                    "chunkData": chunk_b64,
                }
                res = await self.send_to_companion("scotty_chunk", msg, timeout_seconds=120.0)
                if not res.get("ok"):
                    return res

            return {"ok": True, "source_id": source_id}
```

#### 4.3.2 Host Execution Caps & Memory Interlocks
In `src/mcp_gateway/cli.py`:
- Enforce `NODE_OPTIONS="--max-old-space-size=1024 --max-semi-space-size=128"`.
- Set `taskset -c 0-5` on launched child processes.
- Enforce 320 MB untouchable RAM safety buffer check before launching multi-part chunk uploads.

### 4.4 Unit & Integration Test Specifications
- `tests/test_scotty_chunking.py`:
  - `test_companion_ipc_mutex_interleaving_prevention`: Run 3 concurrent `get_notebook_metadata` calls while a 4-chunk Scotty stream is running; assert socket writes do not interleave.
  - `test_scotty_512k_chunk_slicing`: Provide a 1.5 MiB payload; assert exactly 3 chunks generated and acknowledged.
  - `test_memory_interlock_threshold`: Mock available RAM below 320 MB; verify upload aborts with `RESOURCE_EXHAUSTED`.

---

## Phase 5: Protocol Auto-Healing & Resilient Decoders (Domain E)

### 5.1 Architectural Objectives
Build resilient decoders capable of handling upstream format variations, escaped characters, and chunk splits while maintaining continuous broker-companion health monitoring via automated heartbeats.

### 5.2 Target File Paths
- `src/mcp_gateway/engine/stream_decoder.py`
- `src/mcp_gateway/broker/broker.py`
- `src/extension/service_worker.js`

### 5.3 Concrete Specifications & Error Envelopes

#### 5.3.1 15-Second Automated Heartbeat
- The broker daemon schedules a background `asyncio` task sending `{ "command": "ping", "requestId": "..." }` every 15 seconds.
- If no `pong` is received within 5 seconds, the broker drops `_active_companion_writer` and triggers auto-reconnect.
- The service worker handles `ping` by responding `{ "ok": true, "type": "pong" }`, refreshing Chrome's port event loop.

#### 5.3.2 Standardized Failure Envelopes (MCP 2026-07-28 Compliant)
```python
@dataclass
class FailureEnvelope:
    code: str
    message: str
    retryable: bool
    errorCategory: str  # 'transient' | 'validation' | 'permission' | 'business'
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "errorCategory": self.errorCategory,
                "details": self.details,
            }
        }
```

### 5.4 Unit & Integration Test Specifications
- `tests/test_protocol_healing.py`:
  - `test_heartbeat_ping_pong_recovery`: Simulate dropped port; assert auto-reconnect restores bridge within 2 seconds.
  - `test_batchexecute_surrogate_pair_decoder`: Test stream containing astral plane Unicode code units across chunk boundary; assert clean string assembly.

---

## Phase 6: Documentation Restructuring & Inverted Hierarchy (Domain F)

### 6.1 Architectural Objectives
Restructure repository documentation into an inverted hierarchy where `AGENTS.md` and `docs/architecture.md` serve as immutable invariant foundations, backed by domain learnings and progress records.

### 6.2 Documentation Hierarchy Mapping
```
├── AGENTS.md                                     [System Directives & Architectural Invariants]
├── docs/
│   ├── architecture.md                           [Pillar Blueprints & Cross-Platform Topologies]
│   ├── Google_Notebooks_MCP_Gateway_Implementation_Plan_v4_1.md [THIS PLAN: Execution Blueprint]
│   ├── learnings-and-reasoning.md                [Empirical Learnings & Root-Cause Analyses]
│   ├── progress-tracker.md                       [Historical Ledger & Phase Completion Tracking]
│   └── client-configuration.md                   [IDE & Host Setup Guide]
```

---

## Complete Verification & Safety Guardrail Checklist

Prior to production sign-off, the implementation must pass this 6-gate verification sequence:

1. **Gate 1: Static Typing & Linting**:
   `taskset -c 0-5 mypy --strict src/ tests/` (0 errors across 100% of files).
2. **Gate 2: Unit Regression Suite**:
   `taskset -c 0-5 pytest -v tests/` (All existing and new tests pass).
3. **Gate 3: Closed Schema Fuzzing**:
   Execute schema fuzzing against all tools with extra attributes; assert immediate `INVALID_ARGUMENT`.
4. **Gate 4: Security Canary Assertions**:
   Verify zero cookies/tokens in SQLite journal, broker logs, or Native Messaging frames.
5. **Gate 5: GitNexus Knowledge Graph Sync**:
   `node .gitnexus/run.cjs detect-changes --scope all --repo .` (Clean blast-radius check).
6. **Gate 6: Live In-Situ Self-Consultation**:
   Upload `Implementation Plan v4.1` to `"Google Notebooks MCP"` notebook and verify grounded approval via `query_notebook`.
