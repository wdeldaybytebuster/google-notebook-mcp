# Master System Architecture & Specifications

**System Status:** Production Hardened & Grounded  
**Specification Version:** v4.2.0-STRICT  

---

## 🏗️ Architectural Topology

The Google Notebook MCP Gateway bridges AI coding clients to private Google Notebooks without exporting user credentials.

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

## 🛡️ Core Mitigations (M-01 to M-10) & Operational Polish (P-01 to P-04)

| Identifier | Domain | Description | Enforcement Invariant |
| :--- | :--- | :--- | :--- |
| **M-01** | Session | **TOCTOU Race on Session Lock**: Title resolution race under concurrent agent calls. | Wrapped in `_session_mutex = asyncio.Lock()` in `BrokerDaemon`. |
| **M-02** | Transport | **IPC Framing Corruption**: Interleaved frames during file chunk uploads corrupt transport. | Wrapped in `_companion_ipc_mutex = asyncio.Lock()` during $\le 512\text{ KiB}$ slices. |
| **M-03** | Lifecycle | **MV3 300s Hard Execution Ceiling**: Chrome kills service workers after 300s. | Clamped RPC calls to 240s; incremental stream chunking resets timer. |
| **M-04** | Lifecycle | **Silent Background Tab Discard**: Memory Saver discards tabs; promises hang indefinitely. | Sets `autoDiscardable: false`; listens to `onUpdated.discarded`, draining promises with `TAB_DISCARDED`. |
| **M-05** | Schema | **Silent Upstream Schema Drift**: Missing array bounds silently returns empty lists. | Enforces loud `UPSTREAM_SCHEMA_DRIFT` failure canary on array shape anomalies. |
| **M-06** | Grounding | **Ungrounded Model Response**: Answers with zero citations violating grounding. | Enforces strict barrier: zero citations returns `ok: false`, `code: "UNGROUNDED_RESPONSE"`. |
| **M-07** | Framing | **Native Host Stderr Wire Corruption**: C prints to fd 2 corrupt Chrome stdio binary framing. | C-level `os.dup2(log_file.fileno(), 2)` at early boot; `os.O_BINARY` on Windows. |
| **M-08** | Database | **Non-Atomic SQLite Migrations**: Schema alterations crash under edge memory pressure. | Atomic transactions under `PRAGMA user_version < 2` with `BEGIN IMMEDIATE TRANSACTION`. |
| **M-09** | Interceptor | **Stream Consumption Panic**: Reading streams in fetch interceptor triggers `TypeError: Already read`. | Interceptor inspects only strings/`URLSearchParams` with strict `bodyUsed` protection. |
| **M-10** | Readiness | **Broad Pre-Query Readiness Blocking**: Unhealthy untargeted sources block targeted queries. | Scoped pre-query readiness checks exclusively to targeted `source_ids`. |
| **P-01** | Streaming | **Mid-Stream Transport Severance**: Abrupt disconnect causes agent client hang. | Emits structured `STREAM_SEVERED` error delta frame before closing stream. |
| **P-02** | Upload | **Scotty Multi-Part Slicing Inefficiency**: Upload disconnect forced restart from byte 0. | Caches session URL in `chrome.storage.session`; queries offset via `X-Goog-Upload-Command: query`. |
| **P-03** | Auth | **Multi-Account Identity Mutation Drift**: Silent fallback to account 0 mutates wrong profile. | Asserts `window.WIZ_global_data.oM1Kwf === payload.expectedEmail` before mutating RPCs. |
| **P-04** | Tracing | **Correlation ID vs Hash Ambiguity**: Internal SHA256 obscured client request keys. | Preserves un-hashed `request_key` as `_meta.mcp_correlation_id` across all responses. |

---

## 📜 Architectural Decision Records (ADR Summary)

* **ADR-001:** Browser-Resident Execution Broker over Disk Cookie Extraction (DBSC / TPM Containment).
* **ADR-002:** Decoupled Process IPC Topology (Native Messaging stdio vs MCP stdio).
* **ADR-003:** Context-Optimized Closed Tool Surface & Parameter Scrubbing (`additionalProperties: false`).
* **ADR-004:** UTF-16 Code Unit to Python Unicode Coordinate Translation.
* **ADR-005:** Conservative Mutation Journaling FSM & Ambiguity Freeze (SQLite WAL).
* **ADR-006:** Full Jitter Exponential Backoff for Source Readiness Polling.
* **ADR-007:** Multi-Account Isolation & Email Identity Verification (`authuser` + `oM1Kwf`).
* **ADR-008:** Edge Hardware Profile & Resource-Constrained System Governance (`taskset -c 0-5`).
* **ADR-009:** Windows Native Framing, Binary Mode Stdio & 108-Character Path Bounds.
* **ADR-010:** Standardized MCP Error Taxonomy & Distributed Tracing.
* **ADR-011:** Mandatory Interactive Single-Notebook Session Lock FSM.
* **ADR-012:** Session Transition Mutex & Handshake Serialization (M-01, M-02).
* **ADR-013:** Scotty Multi-Part IPC Serialization & Resumability (M-02, P-02).
* **ADR-014:** MV3 Watchdog & Tab Discard Supervised Lifecycle (M-03, M-04).
* **ADR-015:** Strict Grounding Citation Barrier & Loud Schema Canaries (M-05, M-06).
* **ADR-016:** C-Level Descriptor Redirection & Atomic SQLite Migrations (M-07, M-08).
* **ADR-017:** Project-Level Notebook Binding (`.notebook_mcp.json`) & In-Chat Confirmation Protocol.
* **ADR-018:** Zero-Friction Autonomous Onboarding Orchestrator & Standalone RFC 6455 CDP Engine.
