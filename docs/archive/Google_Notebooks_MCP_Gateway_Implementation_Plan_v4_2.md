# Google Notebooks MCP Gateway — Architectural Hardening & Implementation Plan v4.2

**Document Title:** Google Notebooks MCP Gateway — Architectural Hardening & Implementation Plan v4.2  
**Specification Version:** 4.2.0-STRICT  
**Status:** Approved for Implementation (Closed-Loop Grounded & Production Hardened)  
**Parent Orchestrator:** Lead Systems Architect (`d44c115c-a82c-4154-83d1-303f2d7e6078`)  
**Synthesized By:** Sub-Agent 2 (Architect — Plan Synthesis)  
**Reference Notebook:** `"Google Notebooks MCP"` (`00000000-0000-0000-0000-000000000001`)  
**Assigned Source ID:** `11111111-1111-1111-1111-111111111111`  
**Consultation Verdict:** `APPROVED WITH MINOR POLISH (PLAN v4.1 IS SOUND & SAFE)` & `CONFORMANCE VERDICT: ARCHITECTURALLY SOUND AND CONFORMANT`  
**Hardware Profile:** Intel Core i3-N305 | 8 Threads (6-core pinned `taskset -c 0-5`) | 6.4 GB RAM | Zero Swap | eMMC 5.1 Flash  

---

## Executive Summary & Closed-Loop Consultation Synthesis

This document establishes the production-grade **Implementation Plan v4.2** for the Google Notebooks MCP Gateway. It represents the hardened synthesis of:
1. **The 10 Core Red-Team Mitigations (M-01 through M-10)** established in v4.1, resolving session TOCTOU races, Scotty IPC framing interleaving, MV3 240s ceilings, background tab discards, loud schema drift canaries, ungrounded response rejection, C-level OS file descriptor leaks, atomic SQLite schema migrations, non-destructive fetch interception, and scoped pre-query readiness polling.
2. **The 4 Operational Polish Items (P-01 through P-04)** identified during the live closed-loop architectural consultation against the official `"Google Notebooks MCP"` knowledge base and formally requested by the Human Operator:
   - **P-01 (Phase 5): Mid-Stream Error Delta Emission** in `stream_decoder.py` and `broker.py` for abrupt network/transport severance.
   - **P-02 (Phase 4): Scotty Session URL Resumability Caching** in `chrome.storage.session` and offset querying via `X-Goog-Upload-Command: query`.
   - **P-03 (Phase 1): Pre-flight Account Identity Guard on Mutations** in `page-main.js` asserting `window.WIZ_global_data.oM1Kwf` prior to issuing any mutating `fetch()`.
   - **P-04 (Phase 3): Un-Hashed MCP Correlation ID Propagation** preserving `request_key` / `idempotency_key` as `_meta.mcp_correlation_id` across all logs, dispatches, and error envelopes.

### Audit & Operational Polish Reconciliation Ledger

| Item ID | Domain | Classification | Root Cause / Rationale | Hardened Architectural Implementation |
| :--- | :--- | :--- | :--- | :--- |
| **M-01** | B | Session TOCTOU & Title Resolution Race | Unsynchronized async title resolution allows concurrent tools to bypass lock or read transitional state. | Added `self._session_mutex = asyncio.Lock()` in `BrokerDaemon`. Wrapped title resolution and lock acquisition. Queues concurrent calls or returns retryable `RESOLVING_SESSION` envelope. |
| **M-02** | D | IPC Framing Corruption on Scotty Streaming | Interleaving frames on single IPC socket from concurrent read/write tools during multi-part file chunking. | Added `self._companion_ipc_mutex = asyncio.Lock()`. Enforced exclusive socket ownership across all multi-part chunk dispatches. |
| **M-03** | A | Chromium MV3 300s Hard Kill Wall | MV3 background service workers are forcefully terminated by Chrome if any task runs $> 300\text{s}$. | Clamped single synchronous RPC operations to **240 seconds**. Streaming queries (`GenerateFreeFormStreamed`) emit native port chunks incrementally to continually reset event timers. |
| **M-04** | A | Silent Hang on Background Tab Discard | Chrome Memory Saver / low RAM discards background tab; promises hang until timeout. | Added proactive `chrome.tabs.update(tab.id, { autoDiscardable: false })`. Added reactive `chrome.tabs.onUpdated` listener for `changeInfo.discarded === true`, draining promises immediately with retryable `TAB_DISCARDED`. |
| **M-05** | C | Silent Upstream Schema Drift in `list_notes` | Guarding notes container with naive `if len(data[0]) > 17` returns empty `[]` when schema shifts. | Enforced loud failure canary: if `data` is malformed or lacks expected array signatures, return non-retryable `UPSTREAM_SCHEMA_DRIFT` error envelope. Never mask drift as empty notes. |
| **M-06** | B | Ungrounded Response Invariant Breach | Model responses with zero citations returned `ok: true`, violating `AGENTS.md` Rule XI.3. | Enforced strict rejection barrier: If citations list is empty (`len(citations) == 0`), fail closed with `ok: false` and `error.code: "UNGROUNDED_RESPONSE"`. |
| **M-07** | A | C-Level OS File Descriptor 2 Leakage | `sys.stderr = log_file` does not catch writes to native C file descriptor 2, corrupting native framing. | In `native_host.py`, execute `os.dup2(log_file.fileno(), 2)` at early boot before any library imports. Immediately pin `os.O_BINARY` on Windows stdio. |
| **M-08** | C | Non-Atomic SQLite Schema Migration | `CHECK` constraint expansion without atomic transaction crashes database under Chromebook `earlyoom`. | Wrapped migration in `PRAGMA user_version < 2` guard. Executed table swap strictly inside `PRAGMA foreign_keys = OFF; BEGIN IMMEDIATE TRANSACTION; ... PRAGMA user_version = 2; COMMIT; PRAGMA foreign_keys = ON;`. |
| **M-09** | A | Stream Consumption in Dynamic Interceptor | Attaching readers or reading `ReadableStream` bodies in fetch interceptors triggers `TypeError: Already read`. | Interceptor strictly inspects only string or `URLSearchParams` bodies (`bodyUsed` protected). Primary auth extraction remains isolated to `window.WIZ_global_data`. |
| **M-10** | B | Broad Pre-Query Readiness Blocking | Failed (`status=3`) or pending (`status=1`) non-targeted sources in notebook block querying healthy targeted sources. | Scoped pre-query readiness verification in `_handle_query_notebook` exclusively to `source_ids`. Untargeted unhealthy sources are ignored. |
| **P-01** | E | Mid-Stream Transport Severance Hang | Companion IPC or HTTP stream terminates mid-stream before Google end-of-stream delimiter, causing MCP client hangs. | Gateway immediately emits an explicit error delta frame (`{"type": "error_delta", "error": {"code": "STREAM_SEVERED", "message": "Stream severed unexpectedly by upstream transport.", "retryable": true}}`) before terminating stream. |
| **P-02** | D | Scotty Multi-Part Upload Replay Inefficiency | Socket disconnects during multi-megabyte file chunking forced full restart from byte 0, exhausting edge I/O. | Cache active upload session URL in `chrome.storage.session` keyed by `{notebook_id}:{source_id}`. On replay, query session via `X-Goog-Upload-Command: query` to fetch `X-Goog-Upload-Offset` and resume from server offset. |
| **P-03** | A | Multi-Account Identity Mutation Drift | Silent fallback to default account (`authuser=0`) or identity drift in shared Chrome profiles triggers unauthorized mutation. | In `page-main.js`, assert `window.WIZ_global_data.oM1Kwf` against `payload.expectedEmail` / `payload.expectedAccounts` before dispatching mutating RPCs (`add_source`, `create_note`, `delete_note`); fail closed with `PERMISSION_DENIED`. |
| **P-04** | C | Correlation ID vs Hash Ambiguity | Internal SHA256 hashes and W3C traceparents obscured original user-supplied correlation tokens in logs and errors. | Preserve client `request_key` / `idempotency_key` as un-hashed `_meta.mcp_correlation_id` across all log records, internal dispatch contexts, and output error envelopes. |

---

## Phase 1: Lifecycle, Keep-Alive & Account Identity Hardening (Domain A)

### 1.1 Architectural Objectives
Eliminate all service worker idle evictions, OS pipe deadlocks, Chromium background tab discards, and 300-second execution kill walls while guaranteeing zero-leakage C-level descriptor redirection and pre-flight account identity verification on mutating RPCs.

### 1.2 Target File Paths
- `src/mcp_gateway/host/native_host.py`
- `src/extension/service_worker.js`
- `src/extension/page-main.js`

### 1.3 Concrete Specifications & Code Implementations

#### 1.3.1 C-Level OS Descriptor Redirection & Windows Binary Mode (M-07)
In `src/mcp_gateway/host/native_host.py`, OS descriptor redirection must occur at line 1 before any standard library or runtime components initialize that could write diagnostic prints or C runtime warnings to standard error.

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
1. **Proactive:** Explicitly mark notebook tabs as `autoDiscardable: false` immediately upon creation or detection.
2. **Reactive:** Listen to `chrome.tabs.onUpdated` for `changeInfo.discarded === true`, draining pending promises immediately with retryable `TAB_DISCARDED` failure envelopes.

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
- Incremental native chunking: For streaming responses, each chunk forwarded over `nativePort.postMessage({ type: 'stream_chunk', requestId, chunk })` continually resets Chrome's event-driven idle timer.

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

#### 1.3.5 Pre-Flight Account Identity Guard on Mutations (P-03 / v4.2 Polish)
In `src/extension/page-main.js`, prior to dispatching ANY mutating RPC (`add_source`, `create_note`, `delete_note`, or Scotty upload), assert the active page-resident account identity against the caller's expected account allowlist. If mismatched or unauthenticated, fail closed immediately before issuing the fetch.

```javascript
// --- P-03: PRE-FLIGHT ACCOUNT IDENTITY GUARD ON MUTATIONS ---
const MUTATING_COMMANDS = new Set([
  'add_source',
  'create_note',
  'delete_note',
  'scotty_upload',
  'scotty_chunk',
]);

const MUTATING_RPC_IDS = new Set([
  'izAoDd', // Ingest text / url / drive source
  'CYK0Xb', // Create user note
  'tGMBJ',  // Delete user note
  'o4cbdc', // Register Scotty file upload
]);

/**
 * Validates active Google account identity before initiating mutations.
 * Prevents unauthorized writes to incorrect accounts in multi-account Chrome profiles.
 *
 * @param {string} command
 * @param {object} payload
 * @returns {{ok: true} | {ok: false, error: object}}
 */
function verifyAccountIdentityPreflight(command, payload) {
  const isMutating =
    MUTATING_COMMANDS.has(command) ||
    (command === 'batchexecute' && MUTATING_RPC_IDS.has(payload?.rpcId));

  if (!isMutating) {
    return { ok: true };
  }

  const wiz = window.WIZ_global_data ?? {};
  const activeEmail = (typeof wiz.oM1Kwf === 'string' ? wiz.oM1Kwf : '').trim().toLowerCase();

  // If no account is logged in, fail immediately
  if (!activeEmail) {
    return {
      ok: false,
      error: {
        code: 'AUTH_REQUIRED',
        message: 'No active Google account identity detected in window.WIZ_global_data.oM1Kwf.',
        retryable: false,
      },
    };
  }

  // 1. Verify specific expected email
  if (payload?.expectedEmail) {
    const expected = String(payload.expectedEmail).trim().toLowerCase();
    if (activeEmail !== expected) {
      return {
        ok: false,
        error: {
          code: 'PERMISSION_DENIED',
          message: `Active Google account (${activeEmail}) does not match expectedEmail (${expected}).`,
          retryable: false,
        },
      };
    }
  }

  // 2. Verify account against allowed list
  if (Array.isArray(payload?.expectedAccounts) && payload.expectedAccounts.length > 0) {
    const allowed = new Set(payload.expectedAccounts.map((a) => String(a).trim().toLowerCase()));
    if (!allowed.has(activeEmail)) {
      return {
        ok: false,
        error: {
          code: 'PERMISSION_DENIED',
          message: `Active Google account (${activeEmail}) does not match allowlist.`,
          retryable: false,
        },
      };
    }
  }

  return { ok: true };
}
```

### 1.4 Unit & Integration Test Specifications
- `tests/test_native_host_lifecycle.py`:
  - `test_early_c_level_stderr_redirection`: Verify file descriptor 2 matches logfile stat ino/dev.
  - `test_windows_binary_stdio_mode`: Mock `msvcrt.setmode` invocation asserting `os.O_BINARY`.
  - `test_tab_discard_event_drain`: Dispatch synthetic `chrome.tabs.onUpdated` with `changeInfo.discarded = true`; assert all pending futures resolve with `TAB_DISCARDED` error envelope.
  - `test_mv3_timeout_clamped_to_240s`: Pass `timeout_seconds: 600`; assert timer triggers rejection at $\le 240\text{s}$.
  - `test_preflight_account_identity_mismatch_blocks_mutation`: Dispatch `create_note` with mismatched `expectedEmail`; verify immediate `PERMISSION_DENIED` rejection without network dispatch.
  - `test_preflight_account_identity_unauthenticated_blocks_mutation`: Clear `window.WIZ_global_data.oM1Kwf`; verify immediate `AUTH_REQUIRED`.

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

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["notebook_id", "question", "request_key"],
  "properties": {
    "notebook_id": { "type": "string", "minLength": 1 },
    "question": { "type": "string", "minLength": 1, "maxLength": 2000 },
    "request_key": { "type": "string", "minLength": 1 },
    "source_ids": {
      "type": "array",
      "items": { "type": "string" }
    },
    "timeout_seconds": {
      "type": "integer",
      "minimum": 10,
      "maximum": 240,
      "default": 240
    }
  }
}
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

## Phase 3: First-Class Note Management, State Journaling & Correlation Propagation (Domain C)

### 3.1 Architectural Objectives
Promote Notes to first-class citizens in the MCP tool catalog, implement loud failure canaries for the `rLM1Ne` note container, execute an atomic, crash-resilient SQLite migration under `PRAGMA user_version`, and preserve un-hashed client correlation IDs across logs and envelopes.

### 3.2 Target File Paths
- `src/mcp_gateway/storage/journal.py`
- `src/mcp_gateway/storage/schema.sql`
- `src/mcp_gateway/broker/broker.py`
- `src/mcp_gateway/schemas/tools.py`
- `src/mcp_gateway/schemas/error.py`

### 3.3 Schemas (Pydantic v2 & JSON Schema)

#### 3.3.1 Note Tool Schemas (`create_note`, `list_notes`, `delete_note`)
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

#### 3.4.3 Un-Hashed MCP Correlation ID Propagation (P-04 / v4.2 Polish)
In `src/mcp_gateway/schemas/error.py` and `broker.py`:
- In addition to W3C `traceparent`, preserve and forward the client-provided `request_key` / `idempotency_key` as `_meta.mcp_correlation_id` across error envelopes and log records.
- Eliminates confusion between internal cryptographic HMAC hashes/SHA256 payload digests and user-supplied correlation strings.

```python
# In src/mcp_gateway/schemas/error.py
@dataclass(frozen=True)
class ErrorDetail:
    code: str
    message: str
    retryable: bool
    errorCategory: ErrorCategory | None = None
    isRetryable: bool | None = None
    mcp_correlation_id: str | None = None  # P-04 Polish Item

    def __post_init__(self) -> None:
        if self.errorCategory is None:
            object.__setattr__(self, "errorCategory", categorize_error(self.code))
        if self.isRetryable is None:
            object.__setattr__(self, "isRetryable", self.retryable)

@dataclass(frozen=True)
class FailureEnvelope:
    error: ErrorDetail
    ok: Literal[False] = False
    _meta: dict[str, Any] = field(default_factory=dict)  # Metadata carrier

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Ensure _meta is top-level and explicitly exposed
        if self.error.mcp_correlation_id and "mcp_correlation_id" not in data["_meta"]:
            data["_meta"]["mcp_correlation_id"] = self.error.mcp_correlation_id
        return data

def make_error(
    code: str,
    message: str,
    retryable: bool = False,
    mcp_correlation_id: str | None = None,
    traceparent: str | None = None,
) -> FailureEnvelope:
    """Constructs a standardized FailureEnvelope with un-hashed correlation propagation."""
    meta: dict[str, Any] = {}
    if mcp_correlation_id:
        meta["mcp_correlation_id"] = mcp_correlation_id
    if traceparent:
        meta["traceparent"] = traceparent

    return FailureEnvelope(
        error=ErrorDetail(
            code=code,
            message=message,
            retryable=retryable,
            mcp_correlation_id=mcp_correlation_id,
        ),
        _meta=meta,
    )
```

In `src/mcp_gateway/broker/broker.py`:
Extract `correlation_id = command.get("request_key") or command.get("idempotency_key")` at dispatch start, attach to structured log lines, and thread through into every `make_error()` invocation and successful response envelope under `_meta.mcp_correlation_id`.

### 3.5 Unit & Integration Test Specifications
- `tests/test_notes_and_migration.py`:
  - `test_sqlite_user_version_migration`: Start with version 1 database; run initialization; assert `PRAGMA user_version == 2` and new CHECK constraint active.
  - `test_create_note_journal_state_machine`: Verify `create_note` passes `prepared -> sent -> confirmed`.
  - `test_list_notes_loud_canary_failure`: Mock `rLM1Ne` with `len(data[0]) == 10`; assert `UPSTREAM_SCHEMA_DRIFT` error returned.
  - `test_delete_note_idempotency`: Repeat delete with identical `idempotency_key`; verify rejection of duplicate or confirmation of cached state.
  - `test_correlation_id_propagation_in_error_envelopes`: Pass `request_key: "consultation-query-001"`; inject error; verify output contains `_meta.mcp_correlation_id: "consultation-query-001"` un-hashed.

---

## Phase 4: Edge Memory Governance, Segmented Scotty Streaming & Session Resumability (Domain D)

### 4.1 Architectural Objectives
Enforce strict physical memory protection on the 6.4 GB Chromebook development node, introduce socket-level exclusivity for large file uploads, stream Scotty binary data in bounded 512 KiB segments without frame interleaving, and cache Scotty upload session URLs in `chrome.storage.session` to support offset querying and resumability.

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

#### 4.3.2 Scotty Session URL Resumability Caching & Offset Querying (P-02 / v4.2 Polish)
In `src/extension/service_worker.js` and `page-main.js`:
- In `page-main.js` and `service_worker.js`: Cache active Scotty upload session URLs in `chrome.storage.session` under the deterministic key `scotty_session_${notebook_id}_${source_id}`.
- If a multi-part upload disconnects or replays, query the session URL using `X-Goog-Upload-Command: query` to fetch the current server-acknowledged `X-Goog-Upload-Offset`.
- Resume byte streaming from the server-reported byte offset instead of restarting from byte 0.
- Evict the cached key upon successful upload finalization or terminal failure.

```javascript
// --- P-02: SCOTTY SESSION URL RESUMABILITY CACHING ---
function getSessionStorageKey(notebookId, sourceId) {
  return `scotty_session_${notebookId}_${sourceId}`;
}

/**
 * Queries active Scotty upload session to retrieve server-confirmed byte offset.
 *
 * @param {string} sessionUrl
 * @returns {Promise<{status: string, offset: number}>}
 */
async function queryScottySessionOffset(sessionUrl) {
  const response = await fetch(sessionUrl, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'X-Goog-Upload-Command': 'query',
    },
  });

  const uploadStatus =
    response.headers.get('X-Goog-Upload-Status') ||
    response.headers.get('x-goog-upload-status') ||
    'active';

  const offsetHeader =
    response.headers.get('X-Goog-Upload-Offset') ||
    response.headers.get('x-goog-upload-offset') ||
    '0';

  const offset = parseInt(offsetHeader, 10);
  return { status: uploadStatus, offset: Number.isNaN(offset) ? 0 : offset };
}

/**
 * Hardened Scotty Upload Handler with Session URL Caching & Resumability.
 */
async function executeResumableScottyUpload(sourceId, filename, notebookId, fileBytes, authuser) {
  const sessionKey = getSessionStorageKey(notebookId, sourceId);
  let sessionUrl = null;
  let startOffset = 0;

  // 1. Check for cached session URL in chrome.storage.session
  try {
    const cached = await chrome.storage.session.get(sessionKey);
    if (cached && cached[sessionKey]) {
      sessionUrl = cached[sessionKey];
      // Query server for acknowledged offset
      try {
        const queryRes = await queryScottySessionOffset(sessionUrl);
        if (queryRes.status === 'final') {
          // Already finalized on server
          await chrome.storage.session.remove(sessionKey);
          return { ok: true, sourceId };
        }
        startOffset = queryRes.offset;
        console.log(`[scotty] Resuming upload for ${sourceId} from server offset: ${startOffset}`);
      } catch (err) {
        // Cached session expired or invalid, invalidate and start fresh
        console.warn(`[scotty] Cached session query failed, creating fresh session.`, err);
        sessionUrl = null;
        startOffset = 0;
        await chrome.storage.session.remove(sessionKey);
      }
    }
  } catch (err) {
    console.warn('[scotty] chrome.storage.session read error:', err);
  }

  // 2. If no valid session URL, initiate upload intent
  if (!sessionUrl) {
    const uploadInitUrl =
      'https://notebook.google.com/upload/_/LabsTailwindUi/feeds/upload/create_session/interactive/media/?authuser=' +
      encodeURIComponent(String(authuser));

    const initResponse = await fetch(uploadInitUrl, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'X-Goog-Upload-Command': 'start',
        'X-Goog-Upload-Header-Content-Length': String(fileBytes.byteLength),
        'X-Goog-Upload-Header-Content-Type': 'application/octet-stream',
        'X-Goog-Upload-Protocol': 'resumable',
        'X-Same-Domain': '1',
        'X-Goog-Authuser': String(authuser),
      },
      body: JSON.stringify({
        PROJECT_ID: notebookId,
        SOURCE_NAME: filename,
        SOURCE_ID: sourceId,
        sourceId,
        notebookId,
        filename,
      }),
    });

    sessionUrl =
      initResponse.headers.get('x-goog-upload-url') ||
      initResponse.headers.get('X-Goog-Upload-URL');

    if (!sessionUrl) {
      return {
        ok: false,
        error: {
          code: 'UPLOAD_INIT_ERROR',
          message: 'No upload session URL returned by Scotty.',
          retryable: true,
        },
      };
    }

    // Persist session URL for resumption across transient disconnects
    try {
      await chrome.storage.session.set({ [sessionKey]: sessionUrl });
    } catch (e) {
      console.warn('[scotty] Failed to cache session URL:', e);
    }
  }

  // 3. Stream remaining bytes starting from confirmed offset
  try {
    const payloadBytes = startOffset > 0 ? fileBytes.slice(startOffset) : fileBytes;

    await fetch(sessionUrl, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/octet-stream',
        'X-Goog-Upload-Command': 'upload, finalize',
        'X-Goog-Upload-Offset': String(startOffset),
      },
      body: payloadBytes,
    });

    // Cleanup session cache upon confirmed completion
    try {
      await chrome.storage.session.remove(sessionKey);
    } catch (_) {}

    return { ok: true, sourceId };
  } catch (err) {
    return {
      ok: false,
      error: {
        code: 'UPLOAD_STREAM_ERROR',
        message: err instanceof Error ? err.message : 'Upload stream failed.',
        retryable: true,
      },
    };
  }
}
```

#### 4.3.3 Host Execution Caps & Memory Interlocks
In `src/mcp_gateway/cli.py`:
- Enforce `NODE_OPTIONS="--max-old-space-size=1024 --max-semi-space-size=128"`.
- Pin process affinity to cores 0–5 (`taskset -c 0-5`).
- Enforce 320 MB untouchable RAM safety buffer check before launching multi-part chunk uploads.

### 4.4 Unit & Integration Test Specifications
- `tests/test_scotty_chunking.py`:
  - `test_companion_ipc_mutex_interleaving_prevention`: Run 3 concurrent `get_notebook_metadata` calls while a 4-chunk Scotty stream is running; assert socket writes do not interleave.
  - `test_scotty_512k_chunk_slicing`: Provide a 1.5 MiB payload; assert exactly 3 chunks generated and acknowledged.
  - `test_scotty_session_url_caching_and_resumption`: Simulate disconnection after 512 KiB; query session URL asserting `X-Goog-Upload-Offset: 524288`; verify second attempt resumes from byte 524288 without re-uploading chunk 1.
  - `test_memory_interlock_threshold`: Mock available RAM below 320 MB; verify upload aborts with `RESOURCE_EXHAUSTED`.

---

## Phase 5: Protocol Auto-Healing, Resilient Decoders & Mid-Stream Error Delta Emission (Domain E)

### 5.1 Architectural Objectives
Build resilient decoders capable of handling upstream format variations, escaped characters, and chunk splits while maintaining continuous broker-companion health monitoring via automated heartbeats and emitting explicit mid-stream error delta frames upon transport severance.

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
    _meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "errorCategory": self.errorCategory,
                "details": self.details,
            },
            "_meta": self._meta,
        }
```

#### 5.3.3 Mid-Stream Error Delta Emission (P-01 / v4.2 Polish)
In `src/mcp_gateway/engine/stream_decoder.py` and `broker.py`:
- If the companion IPC connection or HTTP stream terminates abruptly mid-stream before receiving the Google end-of-stream delimiter, the gateway must emit an explicit error delta frame before closing the stream:
  `{"type": "error_delta", "error": {"code": "STREAM_SEVERED", "message": "Stream severed unexpectedly by upstream transport.", "retryable": true}}`
- Prevents downstream MCP clients from hanging indefinitely until global timeout.

```python
# In src/mcp_gateway/engine/stream_decoder.py
class GenerateFreeFormStreamParser:
    """Incremental line parser for GenerateFreeFormStreamed event chunks."""

    def __init__(self) -> None:
        self._line_buffer: str = ""
        self._last_cumulative_text: str = ""
        self._is_terminated_cleanly: bool = False

    def feed(self, chunk: bytes) -> list[dict[str, Any]]:
        self._line_buffer += chunk.decode("utf-8", errors="replace")
        results: list[dict[str, Any]] = []

        while "\n" in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            parsed = self._classify(record)
            if parsed is not None:
                if parsed.get("type") == "done":
                    self._is_terminated_cleanly = True
                results.append(parsed)

        return results

    def finalize(self) -> list[dict[str, Any]]:
        """Invoked on stream closure to detect abrupt mid-stream severance (P-01)."""
        if not self._is_terminated_cleanly:
            # Stream ended without receiving Google's clean done delimiter
            return [
                {
                    "type": "error_delta",
                    "error": {
                        "code": "STREAM_SEVERED",
                        "message": "Stream severed unexpectedly by upstream transport.",
                        "retryable": True,
                    },
                }
            ]
        return []
```

In `src/mcp_gateway/broker/broker.py`:
When consuming streaming deltas from the companion over IPC:
```python
# In _handle_query_notebook streaming loop
try:
    while not stream_finished:
        chunk = await self._read_next_stream_chunk(stream_id, timeout=30.0)
        if chunk is None:  # Connection closed unexpectedly
            break
        events = stream_parser.feed(chunk)
        for ev in events:
            yield ev
            if ev.get("type") == "done":
                stream_finished = True
except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError, asyncio.TimeoutError):
    pass  # Transport dropped

# P-01 Polish: Emit error delta if stream did not finish cleanly
final_events = stream_parser.finalize()
for ev in final_events:
    yield ev
```

### 5.4 Unit & Integration Test Specifications
- `tests/test_protocol_healing.py`:
  - `test_heartbeat_ping_pong_recovery`: Simulate dropped port; assert auto-reconnect restores bridge within 2 seconds.
  - `test_batchexecute_surrogate_pair_decoder`: Test stream containing astral plane Unicode code units across chunk boundary; assert clean string assembly.
  - `test_mid_stream_severance_emits_error_delta`: Feed partial streaming chunk with initial text; abruptly trigger stream close without `done` sentinel; assert parser emits `type: "error_delta"` with `code: "STREAM_SEVERED"` and `retryable: True`.

---

## Phase 6: Documentation Restructuring & Inverted Hierarchy (Domain F)

### 6.1 Architectural Objectives
Restructure repository documentation into an inverted hierarchy where `AGENTS.md` and `docs/architecture.md` serve as immutable invariant foundations, backed by domain learnings and progress records.

### 6.2 Documentation Hierarchy Mapping
```
├── AGENTS.md                                     [System Directives & Architectural Invariants]
├── docs/
│   ├── architecture.md                           [Pillar Blueprints & Cross-Platform Topologies]
│   ├── Google_Notebooks_MCP_Gateway_Implementation_Plan_v4_2.md [THIS PLAN: Execution Blueprint]
│   ├── NotebookLM_Closed_Loop_Consultation_Verification_Report_v4_1.md [Consultation Ledger]
│   ├── learnings-and-reasoning.md                [Empirical Learnings & Root-Cause Analyses]
│   ├── progress-tracker.md                       [Historical Ledger & Phase Completion Tracking]
│   └── client-configuration.md                   [IDE & Host Setup Guide]
```

---

## Comprehensive Test Matrix & Verification Checklist

### Consolidated Test Suite Matrix

| Test Suite File | Test Case Name | Target Requirement / Invariant | Expected Behavior |
| :--- | :--- | :--- | :--- |
| `tests/test_native_host_lifecycle.py` | `test_early_c_level_stderr_redirection` | M-07 (Early OS Descriptors) | OS fd 2 points to log file; no native C warnings reach stdout. |
| `tests/test_native_host_lifecycle.py` | `test_windows_binary_stdio_mode` | M-07 (Windows Mode) | `msvcrt.setmode` invoked on fd 0 and 1 with `os.O_BINARY`. |
| `tests/test_native_host_lifecycle.py` | `test_tab_discard_event_drain` | M-04 (Tab Discard) | Synthetic discard resolves pending promises with `TAB_DISCARDED`. |
| `tests/test_native_host_lifecycle.py` | `test_mv3_timeout_clamped_to_240s` | M-03 (MV3 Ceiling) | Long timeouts capped to 240,000ms. |
| `tests/test_native_host_lifecycle.py` | `test_preflight_account_identity_mismatch` | **P-03 (Identity Guard)** | Mutation rejected immediately with `PERMISSION_DENIED` on email mismatch. |
| `tests/test_native_host_lifecycle.py` | `test_preflight_account_identity_unauthenticated`| **P-03 (Identity Guard)** | Mutation rejected immediately with `AUTH_REQUIRED` if `oM1Kwf` empty. |
| `tests/test_session_title_gating.py` | `test_select_notebook_by_title_success` | M-01 (Title Resolution) | Unique title resolves to valid UUID; session locks. |
| `tests/test_session_title_gating.py` | `test_select_notebook_ambiguous_title_error` | M-01 (Title Collision) | Duplicate title fails closed with `INVALID_ARGUMENT`. |
| `tests/test_session_title_gating.py` | `test_session_mutex_toctou_prevention` | M-01 (Session Mutex) | Concurrent calls serialized or return `RESOLVING_SESSION`. |
| `tests/test_session_title_gating.py` | `test_ungrounded_response_rejection` | M-06 (Grounding Barrier) | Responses with 0 citations rejected with `UNGROUNDED_RESPONSE`. |
| `tests/test_session_title_gating.py` | `test_targeted_source_readiness_isolation` | M-10 (Readiness Scoping)| Healthy targeted source queries succeed despite unhealthy untargeted sources. |
| `tests/test_notes_and_migration.py` | `test_sqlite_user_version_migration` | M-08 (Atomic Migration) | `PRAGMA user_version` upgrades to 2; CHECK constraints expand cleanly. |
| `tests/test_notes_and_migration.py` | `test_create_note_journal_state_machine`| M-08 (Note Journal) | Note mutation executes `prepared -> sent -> confirmed`. |
| `tests/test_notes_and_migration.py` | `test_list_notes_loud_canary_failure` | M-05 (Schema Drift) | Truncated `rLM1Ne` array triggers loud `UPSTREAM_SCHEMA_DRIFT`. |
| `tests/test_notes_and_migration.py` | `test_correlation_id_propagation` | **P-04 (Correlation ID)**| `request_key` preserved un-hashed in `_meta.mcp_correlation_id`. |
| `tests/test_scotty_chunking.py` | `test_companion_ipc_mutex_exclusivity` | M-02 (IPC Mutex) | Multi-part chunks do not interleave with metadata queries. |
| `tests/test_scotty_chunking.py` | `test_scotty_512k_chunk_slicing` | M-02 (Chunk Bounding) | Large files sliced into exact $\le 512\text{ KiB}$ payloads. |
| `tests/test_scotty_chunking.py` | `test_scotty_session_url_caching_and_resumption`| **P-02 (Scotty Resume)** | `chrome.storage.session` queried with `query`; resumes from byte offset. |
| `tests/test_scotty_chunking.py` | `test_memory_interlock_threshold` | Memory Guard | Aborts file upload if available system RAM $< 320\text{ MB}$. |
| `tests/test_protocol_healing.py` | `test_heartbeat_ping_pong_recovery` | Keep-Alive | 15s ping drops trigger reconnect within 2 seconds. |
| `tests/test_protocol_healing.py` | `test_mid_stream_severance_emits_error_delta` | **P-01 (Error Delta)** | Mid-stream transport drop emits `STREAM_SEVERED` error delta frame. |

---

## 6-Gate Production Verification & Safety Guardrail Checklist

Prior to final implementation deployment, the execution must satisfy all 6 safety gates sequentially:

1. **Gate 1: Static Typing & Allocator Linting**:
   ```bash
   taskset -c 0-5 mypy --strict src/ tests/
   ```
   *Requirement:* 0 errors across 100% of Python files.
2. **Gate 2: Unit Regression Suite**:
   ```bash
   taskset -c 0-5 pytest -v tests/
   ```
   *Requirement:* All unit tests pass sequentially without threadpool contention.
3. **Gate 3: Closed Schema Fuzzing**:
   *Requirement:* Execute schema fuzzing against all 9 tool definitions with extraneous keys; assert immediate `INVALID_ARGUMENT`.
4. **Gate 4: Security Canary Assertions**:
   *Requirement:* Verify zero cookies, `ya29` tokens, or `SNlM0e` CSRF secrets appear in SQLite journal, broker logs, or Native Messaging framing.
5. **Gate 5: GitNexus Knowledge Graph Synchronization**:
   ```bash
   node .gitnexus/run.cjs detect-changes --scope all --repo .
   ```
   *Requirement:* Clean blast-radius check verifying structural alignment.
6. **Gate 6: Live In-Situ Grounded Consultation**:
   *Requirement:* Ingestion and consultation in `"Google Notebooks MCP"` notebook confirms grounded conformance.
