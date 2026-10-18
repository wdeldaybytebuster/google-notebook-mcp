# Google Notebook MCP Gateway — Master Architecture & Systems Specification

**Document Version:** 4.2.0-STRICT  
**System Status:** Closed-Loop Grounded, Verified & Production Hardened  
**Primary Governance:** [`AGENTS.md`](../AGENTS.md) | [`docs/archive/learnings-and-reasoning.md`](archive/learnings-and-reasoning.md) | [`docs/archive/progress-tracker.md`](archive/progress-tracker.md)

---

## 1. Master Architecture Blueprint (Page 1)

The **Google Notebook MCP Gateway** establishes a resilient, zero-credential-export bridge connecting autonomous AI coding agents (Claude Code, Cursor, Cline, Windsurf, Antigravity) to private Google Gemini Notebook (`notebook.google.com`) knowledge bases.

```
+---------------------------------------------------------------------------------------------------+
|                                   AI CODING AGENTS (MCP CLIENTS)                                   |
|                        Claude Code  *  Cursor  *  Cline  *  Windsurf  *  Antigravity               |
|                                    [Transport: stdio JSON-RPC 2.0]                                |
+-------------------------------------------------+-------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                            LOCAL POLICY & SESSION BROKER DAEMON (broker.py)                       |
|  * Process Facade: stdio JSON-RPC 2.0 engine (protocol-only on stdout; diagnostic logging stderr) |
|  * Closed 9-Tool Schema Surface (extra="forbid", additionalProperties: false)                     |
|  * ADR-011 Session Lock FSM: DISCOVERY_ONLY -> ACTIVE_DISPATCH (select_notebook gating)            |
|  * Session TOCTOU Mutex (_session_mutex) [M-01] & Scotty IPC Mutex (_companion_ipc_mutex) [M-02]  |
|  * Mandatory Allowlist Enforcement (~/.config/notebooklm-mcp-bridge/allowlist.json)               |
|  * Mutation Journal: prepared -> sent -> confirmed / rejected / unknown (SQLite WAL) [M-08, ADR-5]|
|  * Coordinate Normalizer: Translates Google V8 UTF-16 code units to Python Unicode spans [ADR-004] |
|  * Host Governance: taskset -c 0-5, UV_THREADPOOL_SIZE=3, NODE_OPTIONS ceiling, 320MB reserve     |
+-------------------------------------------------+-------------------------------------------------+
                                                  |
                    [Local IPC: Unix Domain Socket / Named Pipe (Big-Endian 32-bit '>I')]
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                  DEDICATED NATIVE MESSAGING HOST                                  |
|  * Standalone Native OS Process (Decouples 32-bit Binary Framing from MCP Stdio) [ADR-002]        |
|  * Early C-Level OS Descriptor 2 Redirection (os.dup2(log_file.fileno(), 2)) [M-07]               |
|  * Windows stdio Binary Mode Pinning (msvcrt.setmode(..., os.O_BINARY)) [M-07, ADR-009]           |
|  * 15-Second Bidirectional PING/PONG Keepalive Heartbeat Engine                                   |
|  * Protocol Relaying: Chrome Native 32-bit Native '=I' <-> Broker IPC 32-bit Big-Endian '>I'      |
|  * Chunk Segmentation: Enforces <1 MiB Native Limit via <=512 KiB Slices [M-02]                  |
+-------------------------------------------------+-------------------------------------------------+
                                                  |
                  [Chrome Native Messaging API: 32-bit Native-Endian Binary Frames]
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                              BROWSER COMPANION (MANIFEST V3 EXTENSION)                            |
|  * Execution Target: Injected page-main.js running in MAIN world on notebook.google.com          |
|  * MV3 240-Second Hard Execution Ceiling & Stream Timer Reset [M-03, ADR-014]                     |
|  * Tab Discard Defense: autoDiscardable: false & TAB_DISCARDED Reactive Promise Drain [M-04]       |
|  * Scotty Session URL Caching in chrome.storage.session & Query Resumption [P-02, ADR-013]        |
|  * Lifecycle Management: Cold-start background tab provisioning & globalThis.ensureNativePort      |
+---------------------------------+---------------------------------+-------------------------------+
                                  |                                 |
                 [batchexecute Form POST RPC]      [Server-Streaming gRPC-Web POST]
                                  |                                 |
                                  v                                 v
+---------------------------------------------------+ +---------------------------------------------+
|              BATCHEXECUTE RPC ENDPOINT            | |          STREAMING QUERY ENDPOINT           |
| POST /_/LabsTailwindUi/data/batchexecute          | | POST /_/LabsTailwindUi/data/.../            |
| * Envelope: f.req=[[[RPC_ID, JSON_STR, null, gen]]| |      GenerateFreeFormStreamed               |
| * Strips )]}' Anti-XSSI Prefix                    | | * Server-Streaming gRPC-Web Frames          |
| * Methods: wXbhsf, rLM1Ne, izAoDd, CYK0Xb, tGMBJ  | | * Strict Citation Grounding Barrier [M-06]  |
| * Scotty Intent: o4cbdc (returns sourceId)        | | * Mid-Stream Error Delta Emission [P-01]    |
+---------------------------------+-----------------+ +---------------------------------------------+
                                  |
                        [Scotty Intent o4cbdc]
                                  v
+---------------------------------------------------+
|               SCOTTY RESUMABLE UPLOAD             |
| POST /upload/_/LabsTailwindUi/... (start)         |
| * Session URL retained in browser storage [P-02]  |
| * Raw Bytes Streamed to x-goog-upload-url (<=512K)|
| * Query resume via X-Goog-Upload-Command: query   |
+---------------------------------------------------+
```

### 1.1 Complete End-to-End System Topology (Mermaid)

```mermaid
flowchart TD
    subgraph Clients ["AI Coding Agents (MCP Clients)"]
        IDE["Claude Code / Cursor / Windsurf / Antigravity"]
    end

    subgraph Broker ["Local Policy & Session Broker (broker.py)"]
        MCPFacade["MCP Stdio Facade<br/>(JSON-RPC 2.0 newline-delimited)"]
        Catalog["Closed 9-Tool Catalog<br/>(extra='forbid', additionalProperties: false)"]
        FSM["ADR-011 Session Lock FSM<br/>(DISCOVERY_ONLY → ACTIVE_DISPATCH)"]
        SessMutex["Session TOCTOU Mutex<br/>(_session_mutex) [M-01]"]
        IPCScottyMutex["Scotty IPC Mutex<br/>(_companion_ipc_mutex) [M-02]"]
        Journal["Mutation Journal (SQLite WAL)<br/>(prepared → sent → confirmed / unknown) [M-08, ADR-005]"]
        CoordTrans["Citation Normalizer<br/>(UTF-16 → Unicode Code Points) [ADR-004]"]
        Scrubber["Secret Scrubber<br/>(Zero Credential Export)"]
    end

    subgraph NativeHost ["Dedicated Native Messaging Host (native_host.py)"]
        NHMain["Standalone Host (Standard Library Only)"]
        OSRedir["C-Level fd 2 Redirection [M-07]<br/>& Windows os.O_BINARY Mode"]
        Heartbeat["15s Bidirectional Keepalive Ping/Pong"]
        Framer["Framing Converter ('>I' ↔ '=I')"]
        Slicer["Chunk Slicer Engine (≤512 KiB Slices) [M-02]"]
    end

    subgraph BrowserExt ["Browser Companion (Chrome MV3 Extension)"]
        SW["Background Service Worker (service_worker.js)"]
        Ceiling["240s Hard Execution Ceiling [M-03]"]
        DiscardDef["Tab Discard Defense [M-04]<br/>(autoDiscardable: false, TAB_DISCARDED drain)"]
        ScottyCacheStore["Scotty Session URL Cache [P-02]<br/>(chrome.storage.session & query offset)"]
        PortExport["globalThis.ensureNativePort Export"]
    end

    subgraph InPage ["In-Page Execution (MAIN World on notebook.google.com)"]
        PageExecutor["Injected Executor (page-main.js)"]
        IDGuard["Pre-Flight Account Identity Guard [P-03]<br/>(WIZ_global_data.oM1Kwf assertion)"]
        SafeInterceptor["Safe Fetch Interceptor [M-09]<br/>(Zero Stream Consumption, bodyUsed check)"]
        WIZData["WIZ_global_data Extractor<br/>(SNlM0e CSRF & FdrFJe Session ID)"]
        NativeFetchExec["In-Browser fetch(credentials: 'include')<br/>(Hardware TPM / DBSC / App-Bound Encryption)"]
    end

    subgraph GoogleEndpoints ["Google LabsTailwindUi Endpoints"]
        BatchEndpoint["POST /_/LabsTailwindUi/data/batchexecute<br/>(wXbhsf, rLM1Ne, izAoDd, CYK0Xb, tGMBJ, o4cbdc)"]
        ScottyEndpoint["POST /upload/_/LabsTailwindUi/...<br/>(Scotty 3-Step Resumable Upload)"]
        StreamEndpoint["POST .../GenerateFreeFormStreamed<br/>(Server-Streaming gRPC-Web & Mid-Stream Error Delta [P-01])"]
    end

    IDE <-->|stdio JSON-RPC 2.0| MCPFacade
    MCPFacade --- Catalog
    Catalog --- FSM
    FSM --- SessMutex
    FSM --- IPCScottyMutex
    Catalog --- Journal
    Catalog --- CoordTrans
    Catalog --- Scrubber

    Broker <-->|Local IPC: Unix Domain Socket (0o600) / Named Pipe<br/>32-bit Big-Endian '>I'| NativeHost

    NHMain --- OSRedir
    NHMain --- Heartbeat
    NHMain --- Framer
    NHMain --- Slicer

    NativeHost <-->|Chrome Native Messaging Protocol<br/>32-bit Native-Endian '=I' Binary Stdio| BrowserExt

    SW --- Ceiling
    SW --- DiscardDef
    SW --- ScottyCacheStore
    SW --- PortExport

    BrowserExt <-->|Chrome Scripting / postMessage Bridge| InPage

    PageExecutor --- IDGuard
    PageExecutor --- SafeInterceptor
    PageExecutor --- WIZData
    PageExecutor --- NativeFetchExec

    NativeFetchExec <-->|HTTPS Form POST f.req| BatchEndpoint
    NativeFetchExec <-->|HTTPS Resumable Chunk Stream| ScottyEndpoint
    NativeFetchExec <-->|HTTPS Server-Streaming gRPC-Web| StreamEndpoint
```

---

## 2. Root Causes Identified and Resolved (Reconciliation Ledger)

The following reconciliation ledger represents the complete set of architectural failure modes identified during red-team penetration testing, edge hardware benchmarking, and closed-loop architectural self-consultation against the production `"Google Notebooks MCP"` knowledge base. Every failure mode has been definitively resolved and verified by automated regression tests.

| Code | Domain | Failure Mode / Root Cause | Architectural Solution & Enforced Invariant | Governing Invariant & Verification Suite |
| :--- | :--- | :--- | :--- | :--- |
| **M-01** | B | **Session TOCTOU & Title Resolution Race**: Unsynchronized asynchronous title resolution allows concurrent client requests to query the gateway before notebook binding completes or during transitional state. | Added `self._session_mutex = asyncio.Lock()` in `BrokerDaemon`. Wrapped title resolution (`wXbhsf`) and session locking. Serializes concurrent requests or returns retryable `RESOLVING_SESSION` envelope. | `AGENTS.md` Sec. II.1<br/>`tests/test_phase2_gating.py` |
| **M-02** | D | **IPC Framing Corruption on Scotty Streaming**: Interleaving frames on single local IPC socket from concurrent read/write tools during multi-part file chunking corrupts message framing. | Added `self._companion_ipc_mutex = asyncio.Lock()` in `BrokerDaemon`. Enforces exclusive socket ownership across all multi-part chunk dispatches. | `AGENTS.md` Sec. III<br/>`tests/test_scotty_chunking.py` |
| **M-03** | A | **Chromium MV3 300s Hard Kill Wall**: MV3 background service workers are forcefully terminated by Chrome if any task runs $> 300\text{s}$. | Clamped single synchronous RPC operations to **240 seconds**. Streaming queries (`GenerateFreeFormStreamed`) emit native port chunks incrementally to continually reset MV3 event timers. | `AGENTS.md` Sec. VIII.1<br/>`tests/test_lifecycle.py` |
| **M-04** | A | **Silent Hang on Background Tab Discard**: Chrome Memory Saver / low RAM discards background tab; promises hang indefinitely until timeout. | Added proactive `chrome.tabs.update(tab.id, { autoDiscardable: false })`. Added reactive `chrome.tabs.onUpdated` listener for `changeInfo.discarded === true`, draining promises immediately with retryable `TAB_DISCARDED`. | `AGENTS.md` Sec. VIII.1<br/>`tests/test_lifecycle.py` |
| **M-05** | C | **Silent Upstream Schema Drift in `list_notes`**: Guarding notes container with naive `if len(data[0]) > 17` returns empty `[]` when schema shifts, masking upstream breaking changes. | Enforced loud failure canary: if `data` is malformed or lacks expected array signatures, return non-retryable `UPSTREAM_SCHEMA_DRIFT` error envelope. Never mask drift as empty notes. | `AGENTS.md` Sec. XII.2<br/>`tests/test_notes_and_migration.py` |
| **M-06** | B | **Ungrounded Response Invariant Breach**: Model responses with zero citations returned `ok: true`, violating strict grounding requirements. | Enforced strict rejection barrier: If citations list is empty (`len(citations) == 0`), fail closed with `ok: false` and `error.code: "UNGROUNDED_RESPONSE"`. | `AGENTS.md` Rule XI.3<br/>`tests/test_phase2_gating.py` |
| **M-07** | A | **C-Level OS File Descriptor 2 Leakage**: `sys.stderr = log_file` does not catch writes to native C file descriptor 2, corrupting native binary framing on stdout. | In `native_host.py`, execute `os.dup2(log_file.fileno(), 2)` at early boot before any library imports. Immediately pin `os.O_BINARY` on Windows stdio. | `AGENTS.md` Sec. X.1-2<br/>`tests/test_native_framing.py` |
| **M-08** | C | **Non-Atomic SQLite Schema Migration**: `CHECK` constraint expansion without atomic transaction crashes database under Chromebook `earlyoom`. | Wrapped migration in `PRAGMA user_version < 2` guard. Executed table swap strictly inside `PRAGMA foreign_keys = OFF; BEGIN IMMEDIATE TRANSACTION; ... PRAGMA user_version = 2; COMMIT; PRAGMA foreign_keys = ON;`. | `AGENTS.md` Sec. V.1<br/>`tests/test_notes_and_migration.py` |
| **M-09** | A | **Stream Consumption in Dynamic Interceptor**: Attaching readers or reading `ReadableStream` bodies in fetch interceptors triggers `TypeError: Already read`. | Interceptor strictly inspects only string or `URLSearchParams` bodies (`bodyUsed` protected). Primary auth extraction remains isolated to `window.WIZ_global_data`. | `AGENTS.md` Sec. I.1<br/>`tests/test_protocol_healing.py` |
| **M-10** | B | **Broad Pre-Query Readiness Blocking**: Failed (`status=3`) or pending (`status=1`) non-targeted sources in notebook block querying healthy targeted sources. | Scoped pre-query readiness verification in `_handle_query_notebook` exclusively to `source_ids`. Untargeted unhealthy sources are ignored. | `AGENTS.md` Sec. IX.2<br/>`tests/test_phase2_gating.py` |
| **P-01** | E | **Mid-Stream Transport Severance Hang**: Companion IPC or HTTP stream terminates mid-stream before Google end-of-stream delimiter, causing MCP client hangs. | Gateway immediately emits an explicit error delta frame (`{"type": "error_delta", "error": {"code": "STREAM_SEVERED", "message": "Stream severed unexpectedly by upstream transport.", "retryable": true}}`) before terminating stream. | `AGENTS.md` Sec. XII.2<br/>`tests/test_protocol_healing.py` |
| **P-02** | D | **Scotty Multi-Part Upload Replay Inefficiency**: Socket disconnects during multi-megabyte file chunking forced full restart from byte 0, exhausting edge I/O. | Cache active upload session URL in `chrome.storage.session` keyed by `{notebook_id}:{source_id}`. On replay, query session via `X-Goog-Upload-Command: query` to fetch `X-Goog-Upload-Offset` and resume from server offset. | `AGENTS.md` Sec. III<br/>`tests/test_scotty_chunking.py` |
| **P-03** | A | **Multi-Account Identity Mutation Drift**: Silent fallback to default account (`authuser=0`) or identity drift in shared Chrome profiles triggers unauthorized mutation. | In `page-main.js`, assert `window.WIZ_global_data.oM1Kwf` against `payload.expectedEmail` / `payload.expectedAccounts` before dispatching mutating RPCs (`add_source`, `create_note`, `delete_note`); fail closed with `PERMISSION_DENIED`. | `AGENTS.md` Sec. I.1<br/>`tests/test_lifecycle.py` |
| **P-04** | C | **Correlation ID vs Hash Ambiguity**: Internal SHA256 hashes and W3C traceparents obscured original user-supplied correlation tokens in logs and errors. | Preserve client `request_key` / `idempotency_key` as un-hashed `_meta.mcp_correlation_id` across all log records, internal dispatch contexts, and output error envelopes. | `AGENTS.md` Sec. XII.2<br/>`tests/test_notes_and_migration.py` |

---

## 3. Signposted 4-Phase Research Progression

The architecture of the Google Notebook MCP Gateway evolved through four distinct empirical research phases:

### Phase 1: Authentication & Token Containment (DBSC / TPM / Zero Credential Export)
* **The Vulnerability & Empirical Failure:** Traditional community tools rely on scraping SQLite `Cookies` databases or prompting users to manually copy Chrome DevTools cookies (`SID`, `HSID`, `SSID`, `__Secure-1PSID`). In Chromium 127+ (Windows) and 130+ (macOS), Google enabled **App-Bound Encryption (ABE)**. Encryption keys stored in `Local State` are wrapped in DPAPI blobs accessible exclusively to the official Chrome process via the `elevation_service` COM interface (`IElevator::DecryptData`). External processes attempting direct decryption fail. Furthermore, Google enforces **Device Bound Session Credentials (DBSC)**, cryptographically binding user sessions to the machine's hardware Trusted Platform Module (TPM). Session validation requires cryptographic challenge signing (`Sec-Session-Response`). Public OAuth 2.0 (`ya29...`) fails because no public OAuth scopes exist for consumer NotebookLM, and mobile gRPC backends require high-risk master tokens (`gpsoauth`).
* **The Architectural Breakthrough:** The gateway abandons external cookie theft entirely. Instead, it deploys a lightweight, browser-resident execution companion via an unpacked Chrome Manifest V3 Extension injecting into the **MAIN world** of `notebook.google.com`. All network requests execute via the browser's native `fetch()` API with `credentials: "include"`. This automatically attaches all required cookies, CSRF tokens (`SNlM0e`), and hardware TPM DBSC signatures through the browser's own secure network stack.
* **The Zero Credential Export Invariant:** Sensitive tokens (`SID`, `HSID`, `SSID`, `ya29.*`, `SNlM0e`) **NEVER** cross local IPC sockets, are never written to disk, and never enter LLM context windows. All outbound payloads pass through `secret_scrubber.py`.

### Phase 2: Decoupled Process IPC Topology & Native Messaging Framing
* **The Transport Collision:** Chrome Native Messaging communicates strictly via standard input/output using a **32-bit native-byte-order length-prefixed binary frame format** (`=I`). Conversely, the Model Context Protocol (MCP) communicates via standard input/output using **newline-delimited JSON-RPC 2.0 text frames**. Attempting to run both protocols over the same process stdio immediately corrupts both communication channels.
* **The Decoupled Topology:** The architecture decouples the gateway into two isolated OS processes:
  1. The **Dedicated Native Messaging Host (`native_host.py`)**: Launched directly by Chrome, running purely on Python standard library modules with zero third-party dependencies. It reads and writes 32-bit native binary frames to Chrome stdin/stdout.
  2. The **Policy & Session Broker Daemon (`broker.py`)**: Runs in the user workspace, exposing the MCP stdio facade to AI clients while binding an authenticated local IPC transport (Unix Domain Socket with `0o600` permissions on POSIX, or restricted Win32 Named Pipe `\\.\pipe\notebooklm-mcp-broker` on Windows).
* **Wire Protocol Conversion & C-Level Redirection:** The native host translates between Chrome native-endian binary framing (`=I`) and broker big-endian binary framing (`>I`). To prevent C library warnings or runtime diagnostic prints from corrupting Chrome stdio, `native_host.py` redirects OS file descriptor 2 at early boot (`os.dup2(log_file.fileno(), 2)`) and pins Windows stdio to binary mode (`msvcrt.setmode(..., os.O_BINARY)`).

### Phase 3: Batchexecute & Scotty Wire Protocol Decoders
* **Google Internal RPC Protocol (`batchexecute`):** NotebookLM metadata management, source enumeration, and note operations route through Google's internal positional RPC envelope: `POST /_/LabsTailwindUi/data/batchexecute`. Payloads use double-serialized JSON wrapped in `f.req=[[[RPC_ID, JSON_STR, null, "generic"]]]` with URL-encoding. The gateway strips anti-XSSI security prefixes (`)]}'\n`) and handles fragmented frame reassembly.
* **The Scotty 3-Step Resumable Upload Pipeline:** Binary file uploads (PDF, DOCX, Markdown) route through Google's internal Scotty media ingestion pipeline:
  1. *Intent Registration (`o4cbdc`)*: Emits `[[[filename]], notebook_id, [58]]`. Returns a server-assigned `sourceId` wrapped in deeply nested arrays (e.g. `[[['uuid']], ...]`). The gateway recursively unpacks this structure and validates it against UUIDv4 regex.
  2. *Session Initiation*: Dispatches an in-browser fetch to `/upload/_/LabsTailwindUi/...` with headers `X-Goog-Upload-Command: start`, `X-Goog-Upload-Protocol: resumable`, and payload `{ PROJECT_ID, SOURCE_NAME, SOURCE_ID }`. Extracts the resumable session URL from `x-goog-upload-url`.
  3. *Finalize Byte Stream*: Streams file bytes to `x-goog-upload-url` in $\le 512\text{ KiB}$ slices. Active session URLs are cached in `chrome.storage.session` (P-02) and support query resumption (`X-Goog-Upload-Command: query`).
* **Full Jitter Exponential Backoff Readiness Polling:** Ingested sources process asynchronously (`PROCESSING = 1`). Polling `rLM1Ne` row `[102]`, index 4 utilizes Full Jitter Backoff: $delay = \text{random.uniform}(0, \min(base\_delay \times 2^{attempt}, max\_delay))$, transitioning to `READY (2)` or `FAILED (3)`. Scoped readiness (M-10) isolates checks strictly to targeted `source_ids`.
* **Streaming Natural Language Q&A (`GenerateFreeFormStreamed`):** Queries stream through a dedicated gRPC-web endpoint, emitting chunked text and citation blocks. Google's V8 engine calculates citation coordinates in UTF-16 code units; the gateway converts these to Python Unicode code points before slicing (ADR-004), enforces a strict citation grounding barrier (M-06), and emits structured error deltas on transport severance (P-01).

### Phase 4: ADR-011 Interactive Session Lock & Mutation Journaling FSM
* **ADR-011 Single-Notebook Containment:** AI coding agents must not have open-ended access to scan or alter arbitrary user notebooks. The gateway enforces a strict two-phase state machine:
  - `DISCOVERY_ONLY`: Initial state upon MCP startup. The agent is permitted to execute only `list_notebooks` and `select_notebook`. All operational tools reject invocations with `SESSION_UNLOCKED`.
  - `ACTIVE_DISPATCH`: Triggered once `select_notebook` is called with a verified `notebook_id` or unique human-readable `title`. Verifies the target against `allowlist.json`, generates an HMAC-SHA256 session token, and permanently locks all subsequent tool executions to that notebook. Subsequent attempts to switch notebooks return `SESSION_LOCKED`. Post-lock operations overwrite `notebook_id` from the locked session.
* **Session TOCTOU Mutex (`_session_mutex`):** To eliminate race windows where concurrent agent tool calls attempt to query before title resolution finishes, `BrokerDaemon` wraps title resolution and lock acquisition inside `self._session_mutex` (M-01).
* **Conservative Mutation Journaling FSM:** Every state-modifying operation (`add_source`, `create_note`, `delete_note`, `query_notebook`) requires a client-supplied `idempotency_key` or `request_key`. State transitions follow:
  $$\text{PREPARED} \longrightarrow \text{SENT} \longrightarrow \text{CONFIRMED} \;\big|\; \text{REJECTED} \;\big|\; \text{UNKNOWN}$$
  If a mutation disconnects or times out while `SENT`, it transitions to `UNKNOWN` (`MUTATION_UNKNOWN`). Blind automated retries are permanently blocked; resolution requires deterministic active reconciliation. Schema migrations use atomic `BEGIN IMMEDIATE TRANSACTION` under `PRAGMA user_version < 2` (M-08, ADR-016).

---

## 4. Closed 9-Tool MCP Surface Specification

The MCP stdio facade (`broker.py mcp` / `gemini-notebook-mcp mcp`) strictly exposes a consolidated catalog of **nine closed tools**. All tool schemas enforce `additionalProperties: false` (JSON Schema) and `extra="forbid"` (Pydantic v2). Any extraneous parameters return immediate `INVALID_ARGUMENT` errors.

### 4.1 Tool Catalog Matrix

| Tool Name | Lifecycle State | Mutation / Idempotency | Description & Enforced Invariants |
| :--- | :--- | :--- | :--- |
| `list_notebooks` | `DISCOVERY_ONLY` & `ACTIVE_DISPATCH` | Read-Only / Idempotent | Decodes allowlisted notebooks via `wXbhsf` RPC records. When locked, filters results exclusively to the active notebook. Surfaces `project_config` from `.notebook_mcp.json` and actionable `user_prompt` to double-check selection with user. Supports `page_size` (1-100) and `cursor`. |
| `select_notebook` | `DISCOVERY_ONLY` (re-locking same allowed) | State Transition / Idempotent | Resolves target notebook by UUID (`notebook_id`) or unique human-readable title (`title`). Supports `save_for_project: bool = True` to persist selection in `.notebook_mcp.json`. Serialized via `_session_mutex` (M-01). Locks session into `ACTIVE_DISPATCH`. |
| `get_notebook_metadata` | `ACTIVE_DISPATCH` only | Read-Only / Idempotent | Decodes full notebook metadata via `rLM1Ne` RPC. Parameter `notebook_id` is automatically overwritten with locked session ID. |
| `list_sources` | `ACTIVE_DISPATCH` only | Read-Only / Idempotent | Extracts source records and readiness states directly from `rLM1Ne` row `[102]`. Supports `page_size` (1-100) and `cursor`. |
| `query_notebook` | `ACTIVE_DISPATCH` only | Read / Non-Idempotent (Journaled) | Streams grounded Q&A via `GenerateFreeFormStreamed`. Requires `question` and `request_key`. Enforces citation grounding barrier (M-06), scoped readiness (M-10), and mid-stream error deltas (P-01). Preserves `_meta.mcp_correlation_id` (P-04). |
| `add_source` | `ACTIVE_DISPATCH` only | Write / Non-Idempotent (Journaled) | Ingests content via polymorphic payloads (`izAoDd` for text/url/youtube/drive; Scotty for files). Requires `idempotency_key` and `source`. Enforces pre-flight account email guard (P-03) and Full Jitter Backoff. |
| `create_note` | `ACTIVE_DISPATCH` only | Write / Non-Idempotent (Journaled) | Creates user note via `CYK0Xb` RPC. Requires `title`, `content`, `idempotency_key`. Journaled via SQLite FSM. Enforces pre-flight email guard (P-03). |
| `list_notes` | `ACTIVE_DISPATCH` only | Read-Only / Idempotent | Lists user notes extracted from `rLM1Ne` row `[0][17]`. Enforces loud failure canary (`UPSTREAM_SCHEMA_DRIFT`) on array schema anomalies (M-05). Supports `page_size` and `cursor`. |
| `delete_note` | `ACTIVE_DISPATCH` only | Write / Idempotent (Journaled) | Deletes user note via `tGMBJ` RPC. Requires `note_id`, `idempotency_key`. Journaled via SQLite FSM. Enforces pre-flight email guard (P-03). |

### 4.2 Standard Failure Envelope Contract

All tool errors across IPC and MCP stdio adhere to the closed failure contract:

```json
{
  "ok": false,
  "error": {
    "code": "ALLOWLIST_DENIED | AUTH_REQUIRED | MUTATION_UNKNOWN | INVALID_ARGUMENT | SESSION_UNLOCKED | SESSION_LOCKED | INTERNAL | NOT_FOUND | STREAM_SEVERED | UPSTREAM_SCHEMA_DRIFT",
    "message": "Human-readable descriptive failure message.",
    "retryable": false
  },
  "_meta": {
    "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    "mcp_correlation_id": "client-supplied-request-key-001"
  }
}
```

---

## 5. Architectural Decision Records (ADR-001 through ADR-017)

### ADR-001: Browser-Resident Execution Broker over Disk Cookie Extraction
* **Context:** Modern Chromium enforces App-Bound Encryption (ABE) on Windows 127+ and macOS 130+, wrapping encryption keys in DPAPI blobs accessible only via Chrome's elevation service COM interface. Furthermore, Google enforces Device Bound Session Credentials (DBSC) backed by hardware TPM challenge signatures. Direct on-disk SQLite cookie reads are obsolete and brittle.
* **Decision:** Deploy an unpacked Manifest V3 extension injecting into the MAIN world of `notebook.google.com`. In-browser `fetch()` delegates session authentication to Chrome's native network stack, preserving TPM DBSC keys and cookie rotation without credential export.
* **Status:** Accepted & Production Hardened.

### ADR-002: Decoupled Process IPC Topology (Native Messaging vs MCP Stdio)
* **Context:** Chrome Native Messaging requires 32-bit native-byte-order length-prefixed binary frames on stdio (`=I`). MCP requires newline-delimited JSON-RPC 2.0 text frames on stdio. Running both on the same process stdio corrupts framing.
* **Decision:** Decouple the architecture into two OS processes: `native_host.py` (dedicated binary launched by Chrome) and `broker.py` (standalone MCP daemon), communicating over an authenticated local Unix Domain Socket (`0o600`) or Windows Named Pipe (`\\.\pipe\notebooklm-mcp-broker`) using 32-bit big-endian binary framing (`>I`).
* **Status:** Accepted & Production Hardened.

### ADR-003: Context-Optimized Closed Tool Surface & Parameter Scrubbing
* **Context:** Exposing granular tools or unconstrained schemas causes LLM context bloat, parameter confusion, and tool selection hallucinations.
* **Decision:** Consolidate capabilities into exactly 9 closed tools enforcing `additionalProperties: false` in JSON Schema and `extra="forbid"` in Pydantic v2. Extra parameters immediately return `INVALID_ARGUMENT`.
* **Status:** Accepted & Production Hardened.

### ADR-004: UTF-16 Code Unit to Python Unicode Coordinate Translation
* **Context:** Google's V8 JavaScript engine calculates citation offsets in UTF-16 code units. Python string indexing operates on Unicode code points. Characters in the astral plane (emojis, mathematical symbols) diverge, causing off-by-one errors and citation misalignment.
* **Decision:** The broker protocol engine converts UTF-16 code unit offsets to Python Unicode character offsets before slicing text or returning citation spans to clients.
* **Status:** Accepted & Production Hardened.

### ADR-005: Conservative Mutation Journaling FSM & Ambiguity Freeze
* **Context:** Upstream Google endpoints lack server-side idempotency. Transport timeouts or disconnects during transmission can leave backend state ambiguous. Automatic blind retries can create duplicate sources or notes.
* **Decision:** Track write mutations in SQLite WAL `journal.db` (`prepared` -> `sent` -> `confirmed` / `rejected` / `unknown`) keyed by client idempotency keys. Ambiguous timeouts transition to `unknown` (`MUTATION_UNKNOWN`), freezing automated retries until deterministic active reconciliation via `rLM1Ne`.
* **Status:** Accepted & Production Hardened.

### ADR-006: Full Jitter Exponential Backoff for Source Readiness Polling
* **Context:** Ingested sources process asynchronously on Google servers. Naive tight-loop polling saturates edge CPU/network and risks upstream rate limiting.
* **Decision:** Implement Full Jitter Exponential Backoff: $delay = \text{random.uniform}(0, \min(base\_delay \times 2^{attempt}, max\_delay))$ with base delay 2.0s and max 30.0s, polling `rLM1Ne` row `[102]`, index 4 until `READY (2)` or `FAILED (3)`.
* **Status:** Accepted & Production Hardened.

### ADR-007: Multi-Account Isolation & Email Identity Verification (`authuser` + `oM1Kwf`)
* **Context:** Chrome profiles with multiple Google accounts can switch between `authuser=0`, `authuser=1`, etc. Executing mutations against the wrong account writes data to unintended notebooks or causes authorization failures.
* **Decision:** Dynamically extract `/u/{N}/` routing prefixes, append `authuser={N}` to URLs, and assert `window.WIZ_global_data.oM1Kwf === payload.expectedEmail` before dispatching mutating RPCs (P-03).
* **Status:** Accepted & Production Hardened.

### ADR-008: Edge Hardware Profile & Resource-Constrained System Governance
* **Context:** The gateway executes on an Intel Core i3-N305 Chromebook (8 E-cores, ~6.4 GB RAM, eMMC 5.1 NAND flash, zero swap, `earlyoom` active).
* **Decision:** Pin Antigravity tasks to CPU cores 0–5 (`taskset -c 0-5`), reserving cores 6–7 for ChromeOS. Enforce `UV_THREADPOOL_SIZE=3`, `NODE_OPTIONS="--max-old-space-size=1024"`, sequential execution of heavy tasks, 320 MB untouchable safety buffer, and 1000 max file watches.
* **Status:** Accepted & Production Hardened.

### ADR-009: Windows Native Framing, Binary Mode Stdio & 108-Character Path Bounds
* **Context:** Windows stdio translates `\n` to `\r\n` in text mode, corrupting Native Messaging length headers. Windows `AF_UNIX` sockets enforce a strict 108-character `UNIX_PATH_MAX` ceiling.
* **Decision:** Pin Windows stdin/stdout to binary mode via `msvcrt.setmode(..., os.O_BINARY)` at startup. Validate socket path length $\le 108$ characters, falling back to Named Pipes (`\\.\pipe\notebooklm-mcp-broker`) or hashed paths.
* **Status:** Accepted & Production Hardened.

### ADR-010: Standardized MCP Error Taxonomy (2026-07-28) & Distributed Tracing
* **Context:** Heterogeneous errors and lost correlation IDs impede root cause analysis across multi-tier agent pipelines.
* **Decision:** Enforce closed failure taxonomy in standard Failure Envelope format (`ALLOWLIST_DENIED`, `AUTH_REQUIRED`, `MUTATION_UNKNOWN`, `INVALID_ARGUMENT`, `SESSION_UNLOCKED`, `SESSION_LOCKED`, `INTERNAL`, `NOT_FOUND`, `STREAM_SEVERED`, `UPSTREAM_SCHEMA_DRIFT`). Propagate W3C `traceparent` and un-hashed `_meta.mcp_correlation_id` (P-04).
* **Status:** Accepted & Production Hardened.

### ADR-011: Mandatory Interactive Single-Notebook Session Lock FSM
* **Context:** AI coding agents must not perform operations across arbitrary notebook targets without explicit user selection, preventing prompt injection attacks from accessing other notebooks.
* **Decision:** Enforce two-tier lifecycle: gateway starts in `DISCOVERY_ONLY`, allowing only `list_notebooks` and `select_notebook`. Calling `select_notebook` transitions to `ACTIVE_DISPATCH`, locks the target notebook ID, generates an HMAC session token, and automatically locks down subsequent operations to that notebook only. Attempts to hop to another notebook return `SESSION_LOCKED`.
* **Status:** Accepted & Production Hardened.

### ADR-012: Session Transition Mutex & Handshake Serialization (M-01, M-02)
* **Context:** Asynchronous title resolution and session locking create TOCTOU race windows under concurrent client calls, potentially bypassing lock checks or reading uninitialized state.
* **Decision:** Wrap title resolution (`wXbhsf`) and ADR-011 lock acquisition inside an exclusive `asyncio.Lock()` (`self._session_mutex`) in `BrokerDaemon`. Queues concurrent requests or returns retryable `RESOLVING_SESSION`.
* **Status:** Accepted & Production Hardened.

### ADR-013: Scotty Multi-Part IPC Serialization & Resumability (M-02, P-02)
* **Context:** Interleaving multi-part file chunks over a single IPC socket with concurrent read/write tools causes framing corruption. Upload interruptions force full restarts from byte 0.
* **Decision:** Enforce exclusive IPC socket ownership during chunk transmission via `self._companion_ipc_mutex`. Cache active upload session URLs in `chrome.storage.session` and query server offset via `X-Goog-Upload-Command: query` to resume slicing from that byte offset.
* **Status:** Accepted & Production Hardened.

### ADR-014: MV3 Watchdog & Tab Discard Supervised Lifecycle (M-03, M-04)
* **Context:** Chrome MV3 hard-kills service workers after 300s of execution. Low RAM causes Chrome Memory Saver to discard background tabs, leaving promises hanging indefinitely.
* **Decision:** Clamp single RPC timeouts to 240s with incremental stream chunking to keep MV3 event loops active. Set `autoDiscardable: false` on managed tabs and listen to `chrome.tabs.onUpdated` for `changeInfo.discarded === true`, draining pending promises with `TAB_DISCARDED`.
* **Status:** Accepted & Production Hardened.

### ADR-015: Strict Grounding Citation Barrier & Loud Schema Canaries (M-05, M-06)
* **Context:** Model responses with zero citations returned `ok: true`, violating grounding invariants. Naive guards on `list_notes` returned empty arrays when Google changed array shapes, masking schema drift.
* **Decision:** Enforce strict fail-closed rejection: if `len(citations) == 0`, return `UNGROUNDED_RESPONSE`. In `list_notes`, if `rLM1Ne` row shape is malformed or lacks expected array signatures, return loud `UPSTREAM_SCHEMA_DRIFT` error envelope.
* **Status:** Accepted & Production Hardened.

### ADR-016: C-Level Descriptor Redirection & Atomic SQLite Migrations (M-07, M-08)
* **Context:** Python `sys.stderr` redirection does not catch native C-level library writes to file descriptor 2, corrupting Chrome Native Messaging stdout framing. Database migration during `earlyoom` memory events causes database corruption or lock errors.
* **Decision:** Redirect OS file descriptor 2 via `os.dup2(log_file.fileno(), 2)` at early boot before module imports. Wrap database schema migrations in `PRAGMA user_version < 2` guard inside an immediate transaction: `PRAGMA foreign_keys = OFF; BEGIN IMMEDIATE TRANSACTION; ... PRAGMA user_version = 2; COMMIT; PRAGMA foreign_keys = ON;`.
* **Status:** Accepted & Production Hardened.

### ADR-017: Project-Level Notebook Binding (`.notebook_mcp.json`) & In-Chat Confirmation Protocol
* **Context:** Users switch between multiple coding projects, each bound to a specific notebook knowledge base. In open-ended chat sessions, AI agents often either fail with `SESSION_UNLOCKED` or guess a notebook without consulting the user.
* **Decision:** Implement project working directory persistence via `.notebook_mcp.json` (`notebook_id`, `title`, `updated_at`). Expose `save_for_project: bool = True` on `select_notebook`. In `list_notebooks` and `SESSION_UNLOCKED` error envelopes, emit structured `project_config` and actionable `user_prompt` directing the AI assistant to explicitly double-check with the user at the start of each chat session before locking the session.
* **Status:** Accepted & Production Hardened.

---

## 6. System Architecture & Component Specifications

### 6.1 Architectural Stack

| Layer | Technology | Operational Role |
| :--- | :--- | :--- |
| **Agent Interface (MCP)** | JSON-RPC 2.0 over stdio (newline-delimited) | Standard Model Context Protocol transport for Claude Code, Cursor, Windsurf, Antigravity |
| **MCP Protocol Facade** | Python 3.11+ / `@modelcontextprotocol/sdk` | Implements protocol lifecycle, closed tool schema negotiation, and error sanitization |
| **Policy & Session Broker** | Python 3.11+ asyncio singleton daemon (`broker.py`) | Enforces allowlist, ADR-011 session lock FSM, mutation journaling, token scrubbing |
| **Local Host IPC** | Unix Domain Socket (macOS/Linux) / Named Pipe (Windows) | Bridges broker daemon to native host using 32-bit big-endian framed JSON (`>I`) |
| **Native Messaging Host** | Python 3.11+ standalone binary (`native_host.py`) | Reads/writes 32-bit native-byte-order framed binary messages to Chrome stdin/stdout |
| **Browser Companion** | Chrome Manifest V3 Extension (`service_worker.js`) | Maintains native messaging port, provisions background tabs, and relays commands |
| **In-Page Executor** | Injected JavaScript (`page-main.js`) in MAIN world | Extracts `SNlM0e`/`FdrFJe` and dispatches `fetch()` with native DBSC/cookie context |
| **Mutation Journal** | SQLite 3 (`journal.db` via WAL mode) | Enforces deterministic HMAC-SHA256 request idempotency and transition tracking |
| **Local Configuration** | JSON (`allowlist.json`, `.notebook_mcp.json`) | Stores local allowlisted notebooks, multi-account routing, and project bindings |
| **Upstream Services** | Google LabsTailwindUi (`batchexecute`, Scotty, gRPC-Web) | Private Google Gemini Notebook endpoints for metadata, uploads, notes, and streaming QA |

### 6.2 System Boundaries & Source Structure

* `src/mcp_gateway/broker/` — **Local Policy & Session Broker Daemon**: Owns the MCP stdio facade, mandatory notebook allowlist validation (`allowlist.py`), ADR-011 session locking (`session.py`), secret scrubbing (`secret_scrubber.py`), session TOCTOU mutex (`_session_mutex`), Scotty IPC mutex (`_companion_ipc_mutex`), and host concurrency limits (`UV_THREADPOOL_SIZE=3`).
* `src/mcp_gateway/transport/` — **Universal Local IPC Transport**: Owns cross-platform IPC abstraction (`ipc.py`, `paths.py`), providing Unix Domain Sockets with `0o700` parent / `0o600` socket permissions, Windows Named Pipes (`\\.\pipe\notebooklm-mcp-broker`) with restrictive security DACLs, and `MCP_BROKER_SOCKET` environment overrides.
* `src/mcp_gateway/engine/` — **Protocol Parsing & Normalization Engine**: Owns boundary-agnostic batchexecute response decoding, streaming gRPC chunk reassembly (`stream_decoder.py`), UTF-16 to Unicode coordinate translation (`coordinate.py`), RPC template builders (`rpc_templates.py`), and Full Jitter Exponential Backoff readiness polling (`readiness_poller.py`).
* `src/mcp_gateway/storage/` — **Mutation Journal & State Persistence**: Owns the SQLite schema (`journal.py`, `schema.sql`), atomic state transitions (`prepared` -> `sent` -> `confirmed`/`rejected`/`unknown`), user version migrations (`PRAGMA user_version`), and HMAC-SHA256 request hashing.
* `src/mcp_gateway/schemas/` — **Closed Contract & Wire Templates**: Defines the closed 9-tool JSON schemas (`tools.py`, `additionalProperties: false`, Pydantic v2 `extra="forbid"`) and standard failure envelopes (`error.py`).
* `src/mcp_gateway/host/` — **Native Messaging Bridge & Installer**: Standalone native host (`native_host.py`) with C-level fd 2 redirection and cross-platform browser installer (`installer.py`).
* `src/extension/` — **Manifest V3 Browser Companion**: Owns extension background service worker (`service_worker.js`), cold-start pinned tab provisioning, MAIN-world script injection (`page-main.js`), in-browser fetch execution, and 512 KiB frame chunking.
* `tests/` — **Verification & Golden Fixtures**: Unit regression, mock E2E integration, security canaries, coordinate edge cases, and protocol healing test suites.

### 6.3 Storage Model

* **Database (SQLite 3 - `~/.config/notebooklm-mcp-bridge/journal.db`)**: Stores the mutation journal (`request_key`, `notebook_id`, `operation_type`, `payload_hash`, `state`, `assigned_source_id`, timestamps) and the append-only `mutation_events` audit table. Enforces atomic transactions, SQLite WAL mode, and `busy_timeout=30000`.
* **Local Allowlist Configuration (`~/.config/notebooklm-mcp-bridge/allowlist.json`)**: Stores user-approved notebook UUIDs, active provider mode, and multi-account email mappings. The allowlist starts empty; all access is opt-in.
* **Project Configuration (`.notebook_mcp.json`)**: Optional workspace-local configuration storing the designated notebook ID and human-readable title for conversational project binding (ADR-017).
* **Streaming Upload Ingestion**: Document upload ingestion processes Base64 payloads or streams local binary files via Google's Scotty resumable upload protocol in $\le 512\text{ KiB}$ IPC slices, caching active session URLs in `chrome.storage.session` for instant query offset recovery.

### 6.4 Auth and Access Model

* **Authentication Mechanics**: The architecture rejects direct cookie copying and on-disk SQLite decryption due to Chrome 127+/130+ App-Bound Encryption (ABE) and Device Bound Session Credentials (DBSC). Authentication is delegated entirely to the browser's native network stack via `page-main.js` executing in the MAIN world of `notebook.google.com`. In-browser `fetch()` calls automatically attach session cookies, CSRF tokens (`SNlM0e`), and hardware TPM challenge signatures (`Sec-Session-Response`).
* **Ownership & Access Control**: Access is governed by the local policy broker enforcing an explicit allowlist and ADR-011 interactive session lock. Even if an agent discovers notebooks via `wXbhsf`, operations are rejected with `PERMISSION_DENIED` unless the notebook ID exists in `allowlist.json`.
* **Multi-Account User Isolation**: When multiple Google accounts are active in Chrome, the bridge extracts `authuser` from `/u/{N}/` URL paths, attaches `authuser={N}` query parameters on batchexecute URLs, includes `x-goog-authuser` on upload sessions, and verifies `window.WIZ_global_data.oM1Kwf` against the expected account email (P-03). If the email mismatches, the broker aborts immediately to prevent silent fallback to account 0.

### 6.5 System Invariants

1. **Zero Credential Export**: Raw Google session cookies (`SID`, `HSID`, `SSID`, `__Secure-1PSID`, `SAPISID`), Google access tokens (`ya29...`), and CSRF tokens (`SNlM0e`) must NEVER cross the local socket or leave the browser sandbox.
2. **Process & Transport Isolation**: Chrome Native Messaging binary standard I/O (32-bit native-endian length-prefixed frames) must NEVER share standard streams with MCP stdio (newline-delimited JSON-RPC). They execute as separate OS processes bridged over local IPC.
3. **ADR-011 Mandatory Session Lock & Closed Schemas**: Gateway operations follow a strict two-phase FSM (`DISCOVERY_ONLY` -> `ACTIVE_DISPATCH`). The agent must explicitly invoke `select_notebook` before performing any operations; attempts to perform notebook operations before locking fail with `SESSION_UNLOCKED`. Post-lock operations validate and overwrite `notebook_id` from the locked session, preventing session hopping (`SESSION_LOCKED`). All schemas enforce `additionalProperties: false` (JSON Schema) and `extra="forbid"` (Pydantic v2).
4. **Conservative Mutation Safety**: State transitions follow `prepared` -> `sent` -> `confirmed` / `rejected` / `unknown`. Once a mutation reaches `sent`, it must NEVER be automatically replayed on transport timeout; the broker must reconcile state via `rLM1Ne` before surfacing an error.
5. **Coordinate Translation Integrity**: All citation coordinates received from Google's V8 engine must be translated from UTF-16 code units to native Python Unicode offsets before text slicing, ensuring perfect character alignment on astral-plane characters.
6. **Defensive Resource Ceilings**: The runtime must enforce `taskset -c 0-5`, `UV_THREADPOOL_SIZE=3`, `ulimit -n 65536`, `NODE_OPTIONS="--max-old-space-size=1024"`, and strict loopback socket binding (`127.0.0.1`) to ensure stability on resource-constrained development nodes.

---

## 7. Appendix: Raw Wire Traces & Frame Dumps

This appendix preserves raw wire captures, frame encodings, and HTTP signatures gathered during protocol reverse-engineering for diagnostic reference.

### 7.1 `batchexecute` Envelope & RPC Payload Encodings

#### 7.1.1 Outer Envelope Structure
```http
POST /_/LabsTailwindUi/data/batchexecute?rpcids=wXbhsf&source-path=%2F&bl=boq_labs-tailwind-ui_20261012.08_p0&hl=en&_reqid=123456&rt=c HTTP/1.1
Host: notebook.google.com
Content-Type: application/x-www-form-urlencoded;charset=UTF-8
X-Same-Domain: 1

f.req=%5B%5B%5B%22wXbhsf%22%2C%22%5Bnull%2C1%2Cnull%2C%5B58%5D%5D%22%2Cnull%2C%22generic%22%5D%5D%5D&at=SNlM0e_CSRF_TOKEN_STRING%3A1728800000000
```

#### 7.1.2 Decoded Outer Envelope
```json
[
  [
    ["wXbhsf", "[null,1,null,[58]]", null, "generic"]
  ]
]
```

#### 7.1.3 Note Creation RPC (`CYK0Xb`) Inner Payload
```json
[
  "00000000-0000-0000-0000-000000000001",
  "Note Title String",
  "Note Markdown Content Body"
]
```
Double-serialized and placed inside `f.req`:
```json
[
  [
    ["CYK0Xb", "[\"00000000-0000-0000-0000-000000000001\",\"Note Title String\",\"Note Markdown Content Body\"]", null, "generic"]
  ]
]
```

#### 7.1.4 Note Deletion RPC (`tGMBJ`) Inner Payload
```json
[
  "00000000-0000-0000-0000-000000000001",
  ["note-uuid-to-delete-1234"]
]
```

#### 7.1.5 Source Ingestion RPC (`izAoDd`) Payloads
- **Pasted Text:** `[[[null, ["Document Title", "Text content body..."], null, 2]], "notebook-id-uuid", [58]]`
- **Web URL:** `[[[null, null, ["https://example.com/article"], null, null, null, 1]], "notebook-id-uuid", [58]]`
- **YouTube:** `[[[null, null, null, ["https://www.youtube.com/watch?v=..."], null, null, 3]], "notebook-id-uuid", [58]]`
- **Google Drive:** `[[[null, null, null, null, ["drive-doc-id-123", "application/vnd.google-apps.document"], 4]], "notebook-id-uuid", [58]]`

#### 7.1.6 Anti-XSSI Response Formatting
Google batchexecute responses begin with anti-XSSI security prefix `)]}'\n` followed by chunked length-delimited arrays:
```
)]}'
142
[["wrb.fr","wXbhsf","[[\"00000000-0000-0000-0000-000000000001\",\"Google Notebooks MCP\",null,1728800000,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,1,null,null,null,null,null,null,[\"00000000-0000-0000-0000-000000000001\"],null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,62]]",null,null,null,"generic"]]
```

### 7.2 Scotty 3-Step Resumable Upload HTTP Wire Traces

#### Step 1: Intent Registration (`o4cbdc`)
```json
[
  [
    ["o4cbdc", "[[[\"research-paper.pdf\"]],\"00000000-0000-0000-0000-000000000001\",[58]]", null, "generic"]
  ]
]
```
Response un-nesting:
```json
[[["wrb.fr", "o4cbdc", "[[[[\"11111111-1111-1111-1111-111111111111\"]], \"research-paper.pdf\", 58]]"]]]
```
Extracted clean UUIDv4: `11111111-1111-1111-1111-111111111111`.

#### Step 2: Resumable Session Creation
```http
POST /upload/_/LabsTailwindUi/data/batchexecute?authuser=0 HTTP/1.1
Host: notebook.google.com
X-Goog-Upload-Command: start
X-Goog-Upload-Header-Content-Length: 1048576
X-Goog-Upload-Header-Content-Type: application/pdf
X-Goog-Upload-Protocol: resumable
Content-Type: application/json;charset=UTF-8

{
  "PROJECT_ID": "00000000-0000-0000-0000-000000000001",
  "SOURCE_NAME": "research-paper.pdf",
  "SOURCE_ID": "11111111-1111-1111-1111-111111111111"
}
```
Response header:
```http
HTTP/1.1 200 OK
x-goog-upload-url: https://notebook.google.com/upload/_/LabsTailwindUi/session?upload_id=ADPycduXYZ...
x-goog-upload-chunk-granularity: 524288
x-goog-upload-status: active
```

#### Step 3: Byte Stream Slices & Resumption Query (P-02)
- **Offset Query (P-02 on Reconnect):**
  ```http
  POST /upload/_/LabsTailwindUi/session?upload_id=ADPycduXYZ... HTTP/1.1
  Host: notebook.google.com
  X-Goog-Upload-Command: query

  HTTP/1.1 200 OK
  X-Goog-Upload-Offset: 524288
  X-Goog-Upload-Status: active
  ```
- **Finalize Slice:**
  ```http
  POST /upload/_/LabsTailwindUi/session?upload_id=ADPycduXYZ... HTTP/1.1
  Host: notebook.google.com
  X-Goog-Upload-Command: upload, finalize
  X-Goog-Upload-Offset: 524288
  Content-Type: application/pdf
  Content-Length: 524288

  [524,288 raw bytes...]
  ```

### 7.3 `GenerateFreeFormStreamed` gRPC-Web Wire Frames

#### Request Frame
```http
POST /_/LabsTailwindUi/data/google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/GenerateFreeFormStreamed?authuser=0 HTTP/1.1
Host: notebook.google.com
Content-Type: application/json+protobuf
Accept: application/json+protobuf

[
  "00000000-0000-0000-0000-000000000001",
  "What are the 10 mitigations in Plan v4.1?",
  null,
  null,
  null,
  [
    ["source-uuid-1", "source-uuid-2"]
  ],
  null,
  "conversation-turn-uuid"
]
```

#### Response Stream Chunk (Normalized Offsets)
```
184
[["wrb.fr",null,"[null,null,null,null,null,[[null,null,null,\"The 10 mitigations resolve session TOCTOU races and IPC framing.\",null,[[[0,17,32],[\"11111111-1111-1111-1111-111111111111\"]]]]]]"]]
```
- Raw text: `"The 10 mitigations resolve session TOCTOU races and IPC framing."`
- Raw UTF-16 offset span: `[0, 17, 32]` (mapped by coordinate normalizer to Unicode character offsets).

### 7.4 Native Messaging 32-Bit Frame Layout

#### Chrome Native Messaging (Native-Endian `=I`)
```
[ 4-byte uint32 length (little-endian on x86-64) ][ UTF-8 JSON payload bytes ]
0x2A 0x00 0x00 0x00 { "action": "ping", "timestamp": 1728800000 }
```

#### Local Broker IPC (Big-Endian `>I`)
```
[ 4-byte uint32 length (big-endian network order) ][ UTF-8 JSON payload bytes ]
0x00 0x00 0x00 0x2A { "action": "ping", "timestamp": 1728800000 }
```
`native_host.py` bridges the two framing conventions with zero memory copying.
