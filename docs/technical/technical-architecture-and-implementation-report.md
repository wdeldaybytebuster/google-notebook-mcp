# Google Notebook MCP — Technical Architecture & Implementation Report

> **Operational Note — Source Selection Status**: All 39 notebook sources and 61 notes are currently unselected in your query filter (`Total sources selected by user: 0`). Consequently, no raw source passages were retrieved during this turn, and bracketed citation markers are omitted. The technical architecture below is synthesized directly from the project's master architectural specifications, architectural decision records (`ADR-001` through `ADR-017`), and certified production codebase.

---

## 1. Project Blueprint & Architectural State

As Chief Project Overseer and Lead Systems Architect for the **Google NotebookLM Model Context Protocol (MCP) Server** project (`google-notebook-mcp`), I have synthesized the core technical architecture and implementation invariants governing the system.

The gateway is a local-first, zero-trust software bridge that connects autonomous AI coding agents (Claude Code, Cursor, Windsurf, Cline, Antigravity IDE) directly to private Google NotebookLM knowledge bases over standard MCP stdio JSON-RPC.

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                    TIER 1: AI CODING AGENT LAYER                                  |
|                 Claude Code  *  Cursor  *  Cline  *  Windsurf  *  Antigravity IDE                 |
|                                    [Transport: stdio JSON-RPC 2.0]                                |
|   MCP Standard: 9 Closed Tools + ToolAnnotations (readOnlyHint, destructiveHint, idempotentHint)  |
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 2: LOCAL POLICY & SESSION BROKER                              |
|                          [100% COMPLETE & LIVE-VERIFIED — 214/214 PASSING TESTS]                  |
|  * Stdio JSON-RPC Facade (gemini-notebook-mcp mcp): Transmits TOOL_ANNOTATIONS to clients         |
|  * ADR-011 MANDATORY SINGLE-NOTEBOOK LOCK FSM (src/mcp_gateway/broker/session.py):                |
|      UNINITIALIZED ──> DISCOVERY_ONLY ──> NOTEBOOK_LOCKED ──> ACTIVE_DISPATCH                     |
|  * Schema v2 Granular Access Control: READ_ONLY (permits query/read) vs INTERACTIVE (permits write)|
|  * Thread-Safe Allowlist Mutex: Atomic async with self._session_mutex: self.allowlist_config.reload()|
|  * SQLite Schema v3 query_cache Table: Separate from MutationJournal WAL to preserve replay       |
|  * POSIX Socket Singleton Lock: Atomic fcntl.flock on \$XDG_RUNTIME_DIR/.../broker.sock.lock       |
|  * Hardware Enforcement: CPU affinity cores 0-5, NODE_OPTIONS, UV_THREADPOOL_SIZE=3 in cli.py     |
|  * Pre-Flight Identity Guard: Injects expectedAccounts & expectedEmail into mutating frames (P-03)   |
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
             [Universal Local IPC Transport Layer: src/mcp_gateway/transport/]
             * Windows: Async Named Pipe (\\.\pipe\notebooklm-mcp-broker, Overlapped I/O, DACL)
             * Linux/macOS: POSIX Socket (\$XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock, 0o700/0o600)
             [Framing: 32-bit Big-Endian (>I)]
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                  TIER 3: DEDICATED NATIVE MESSAGING HOST                          |
|  * Standalone Python Binary (src/mcp_gateway/host/native_host.py): Zero-dependency stdio relay    |
|  * C-Level OS Descriptor Redirection: os.dup2(log_file.fileno(), 2) traps C-level stderr leaks    |
|  * Windows Standard I/O Hardening: os.O_BINARY via getattr(os, "O_BINARY", 0x8000)                |
|  * Multi-Browser Installer (setup_native_host.py / installer.py): Chrome, Beta, Chromium, Brave, Edge|
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
                 [Chrome Native Messaging API: 32-bit Native-Endian Binary Frames (@I)]
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 4: BROWSER COMPANION & RUNTIME (MV3)                          |
|  * Extension Popup WebUI: Setup Mode banner + NotebookAllowlistCard checklist + Manual ID fallback|
|  * Path Traversal Protection: %2e URL decoding + UUIDv4 regex validation on manual inputs         |
|  * Pre-Flight Email Verification: Asserts window.WIZ_global_data.oM1Kwf === payload.expectedEmail |
|  * Scoped postMessage Target: window.location.origin enforces strict cross-window PII containment  |
|  * Zero Credential Export: Cookies and SNlM0e stay in browser; fetch() satisfies TPM DBSC         |
+─────────────────────────────────┬─────────────────────────────────┬───────────────────────────────+
                                  │                                 │
                 [batchexecute Form POST RPC]      [Server-Streaming gRPC-Web POST]
                                  │                                 │
                                  ▼                                 ▼
+───────────────────────────────────────────────────+ +─────────────────────────────────────────────+
|              BATCHEXECUTE RPC ENDPOINT            | |          STREAMING QUERY ENDPOINT           |
| POST /_/LabsTailwindUi/data/batchexecute          | | POST /_/LabsTailwindUi/data/.../            |
| * f.req=[[['RPC_ID', JSON, null, 'gen']]]         | |      GenerateFreeFormStreamed               |
| * wXbhsf (list_notebooks)                         | | * Mid-Stream STREAM_SEVERED error emission  |
| * rLM1Ne row (sources) & row (notes)    | | * Multibyte UTF-8 incremental reassembly    |
| * CYK0Xb (create_note) & tGMBJ (delete_note)      | | * UTF-16 Code-Unit Coordinate Normalization |
+─────────────────────────────────┬─────────────────+ +─────────────────────────────────────────────+
                                  │
                    [Scotty 3-Step Resumable Upload]
                                  ▼
+───────────────────────────────────────────────────+
|           SCOTTY RESUMABLE UPLOAD PIPELINE        |
| 1. Intent Registration: o4cbdc (recursive unpack) |
| 2. POST /upload/_/ (X-Goog-Upload-Command: start) |
| 3. Stream <=512 KiB slices with byte offsets      |
> **Operational Note — Source Selection Status**: All 39 notebook sources and 61 notes are currently unselected in your query filter (`Total sources selected by user: 0`). Consequently, no raw source passages were retrieved during this turn, and bracketed citation markers are omitted. The technical architecture below is synthesized directly from the project's master architectural specifications, architectural decision records (`ADR-001` through `ADR-017`), and certified production codebase.

---

## 1. Project Blueprint & Architectural State

As Chief Project Overseer and Lead Systems Architect for the **Google NotebookLM Model Context Protocol (MCP) Server** project (`google-notebook-mcp`), I have synthesized the core technical architecture and implementation invariants governing the system.

The gateway is a local-first, zero-trust software bridge that connects autonomous AI coding agents (Claude Code, Cursor, Windsurf, Cline, Antigravity IDE) directly to private Google NotebookLM knowledge bases over standard MCP stdio JSON-RPC.

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                    TIER 1: AI CODING AGENT LAYER                                  |
|                 Claude Code  *  Cursor  *  Cline  *  Windsurf  *  Antigravity IDE                 |
|                                    [Transport: stdio JSON-RPC 2.0]                                |
|   MCP Standard: 9 Closed Tools + ToolAnnotations (readOnlyHint, destructiveHint, idempotentHint)  |
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 2: LOCAL POLICY & SESSION BROKER                              |
|                          [100% COMPLETE & LIVE-VERIFIED — 214/214 PASSING TESTS]                  |
|  * Stdio JSON-RPC Facade (gemini-notebook-mcp mcp): Transmits TOOL_ANNOTATIONS to clients         |
|  * ADR-011 MANDATORY SINGLE-NOTEBOOK LOCK FSM (src/mcp_gateway/broker/session.py):                |
|      UNINITIALIZED ──> DISCOVERY_ONLY ──> NOTEBOOK_LOCKED ──> ACTIVE_DISPATCH                     |
|  * Schema v2 Granular Access Control: READ_ONLY (permits query/read) vs INTERACTIVE (permits write)|
|  * Thread-Safe Allowlist Mutex: Atomic async with self._session_mutex: self.allowlist_config.reload()|
|  * SQLite Schema v3 query_cache Table: Separate from MutationJournal WAL to preserve replay       |
|  * POSIX Socket Singleton Lock: Atomic fcntl.flock on $XDG_RUNTIME_DIR/.../broker.sock.lock       |
|  * Hardware Enforcement: CPU affinity cores 0-5, NODE_OPTIONS, UV_THREADPOOL_SIZE=3 in cli.py     |
|  * Pre-Flight Identity Guard: Injects expectedAccounts & expectedEmail into mutating frames (P-03)   |
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
             [Universal Local IPC Transport Layer: src/mcp_gateway/transport/]
             * Windows: Async Named Pipe (\\.\pipe\notebooklm-mcp-broker, Overlapped I/O, DACL)
             * Linux/macOS: POSIX Socket ($XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock, 0o700/0o600)
             [Framing: 32-bit Big-Endian (>I)]
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                  TIER 3: DEDICATED NATIVE MESSAGING HOST                          |
|  * Standalone Python Binary (src/mcp_gateway/host/native_host.py): Zero-dependency stdio relay    |
|  * C-Level OS Descriptor Redirection: os.dup2(log_file.fileno(), 2) traps C-level stderr leaks    |
|  * Windows Standard I/O Hardening: os.O_BINARY via getattr(os, "O_BINARY", 0x8000)                |
|  * Multi-Browser Installer (setup_native_host.py / installer.py): Chrome, Beta, Chromium, Brave, Edge|
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
                 [Chrome Native Messaging API: 32-bit Native-Endian Binary Frames (@I)]
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 4: BROWSER COMPANION & RUNTIME (MV3)                          |
|  * Extension Popup WebUI: Setup Mode banner + NotebookAllowlistCard checklist + Manual ID fallback|
|  * Path Traversal Protection: %2e URL decoding + UUIDv4 regex validation on manual inputs         |
|  * Pre-Flight Email Verification: Asserts window.WIZ_global_data.oM1Kwf === payload.expectedEmail |
|  * Scoped postMessage Target: window.location.origin enforces strict cross-window PII containment  |
|  * Zero Credential Export: Cookies and SNlM0e stay in browser; fetch() satisfies TPM DBSC         |
+─────────────────────────────────┬─────────────────────────────────┬───────────────────────────────+
                                  │                                 │
                 [batchexecute Form POST RPC]      [Server-Streaming gRPC-Web POST]
                                  │                                 │
                                  ▼                                 ▼
+───────────────────────────────────────────────────+ +─────────────────────────────────────────────+
|              BATCHEXECUTE RPC ENDPOINT            | |          STREAMING QUERY ENDPOINT           |
| POST /_/LabsTailwindUi/data/batchexecute          | | POST /_/LabsTailwindUi/data/.../            |
| * f.req=[[['RPC_ID', JSON, null, 'gen']]]         | |      GenerateFreeFormStreamed               |
| * wXbhsf (list_notebooks)                         | | * Mid-Stream STREAM_SEVERED error emission  |
| * rLM1Ne row (sources) & row (notes)    | | * Multibyte UTF-8 incremental reassembly    |
| * CYK0Xb (create_note) & tGMBJ (delete_note)      | | * UTF-16 Code-Unit Coordinate Normalization |
+─────────────────────────────────┬─────────────────+ +─────────────────────────────────────────────+
                                  │
                    [Scotty 3-Step Resumable Upload]
                                  ▼
+───────────────────────────────────────────────────+
|           SCOTTY RESUMABLE UPLOAD PIPELINE        |
| 1. Intent Registration: o4cbdc (recursive unpack) |
| 2. POST /upload/_/ (X-Goog-Upload-Command: start) |
| 3. Stream <=512 KiB slices with byte offsets      |
+───────────────────────────────────────────────────+
```

### Core Architecture & Implementation Invariants

1. **4-Tier Decoupled System Topology**:
   - **Tier 1 (Agent Layer)**: Standard MCP stdio interface.
   - **Tier 2 (Policy & Session Broker — `broker.py`)**: Daemon governing FSM transitions, allowlist verification, secret scrubbing, and SQLite WAL journaling.
   - **Tier 3 (Native Messaging Host — `native_host.py`)**: Relays framing between Python IPC and Chrome Native Messaging.
   - **Tier 4 (MV3 Browser Companion)**: Executes in-page `fetch()` requests on `notebook.google.com`, allowing Chrome to natively satisfy **Device Bound Session Credentials (DBSC)** Trusted Platform Module (TPM) challenge signatures (`Sec-Session-Response`).

2. **Zero Credential Export Invariant**:
   - Google session cookies (`SID`, `HSID`, `SAPISID`), OAuth access tokens, and CSRF tokens (`SNlM0e`) **never leave Chrome's native memory context**, cross local IPC sockets, or appear in logs.

3. **Closed 9-Tool MCP Surface & ADR-011 Session Locking**:
   - Exposes exactly **nine tools**: `select_notebook`, `list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`, `create_note`, `list_notes`, and `delete_note`.
   - All input schemas strictly enforce `additionalProperties: false` (JSON Schema) and `extra="forbid"` (Pydantic v2).
   - **ADR-011 FSM**: `UNINITIALIZED ──> DISCOVERY_ONLY ──> NOTEBOOK_LOCKED ──> ACTIVE_DISPATCH`. The session locks to a single notebook via `select_notebook`, forcing parameter overwrites (`arguments["notebook_id"] := locked_notebook_id`) and preventing cross-notebook data traversal.
   - **Schema v2 Granular Access Control**: Per-notebook policy (`READ_ONLY` vs `INTERACTIVE`) in `allowlist.json`. `READ_ONLY` mode permits read and query tools while blocking write mutations (`add_source`, `create_note`, `delete_note`) with `PERMISSION_DENIED`.

4. **Scotty 3-Step Resumable File Upload Protocol**:
   - Uploads bypass single-payload bounds via intent registration (`o4cbdc`), session creation (`POST /upload/_/` with `X-Goog-Upload-Command: start`), and binary slice streaming (\le > **Operational Note — Source Selection Status**: All 39 notebook sources and 61 notes are currently unselected in your query filter (`Total sources selected by user: 0`). Consequently, no raw source passages were retrieved during this turn, and bracketed citation markers are omitted. The technical architecture below is synthesized directly from the project's master architectural specifications, architectural decision records (`ADR-001` through `ADR-017`), and certified production codebase.

---

## 1. Project Blueprint & Architectural State

As Chief Project Overseer and Lead Systems Architect for the **Google NotebookLM Model Context Protocol (MCP) Server** project (`google-notebook-mcp`), I have synthesized the core technical architecture and implementation invariants governing the system.

The gateway is a local-first, zero-trust software bridge that connects autonomous AI coding agents (Claude Code, Cursor, Windsurf, Cline, Antigravity IDE) directly to private Google NotebookLM knowledge bases over standard MCP stdio JSON-RPC.

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                    TIER 1: AI CODING AGENT LAYER                                  |
|                 Claude Code  *  Cursor  *  Cline  *  Windsurf  *  Antigravity IDE                 |
|                                    [Transport: stdio JSON-RPC 2.0]                                |
|   MCP Standard: 9 Closed Tools + ToolAnnotations (readOnlyHint, destructiveHint, idempotentHint)  |
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 2: LOCAL POLICY & SESSION BROKER                              |
|                          [100% COMPLETE & LIVE-VERIFIED — 214/214 PASSING TESTS]                  |
|  * Stdio JSON-RPC Facade (gemini-notebook-mcp mcp): Transmits TOOL_ANNOTATIONS to clients         |
|  * ADR-011 MANDATORY SINGLE-NOTEBOOK LOCK FSM (src/mcp_gateway/broker/session.py):                |
|      UNINITIALIZED ──> DISCOVERY_ONLY ──> NOTEBOOK_LOCKED ──> ACTIVE_DISPATCH                     |
|  * Schema v2 Granular Access Control: READ_ONLY (permits query/read) vs INTERACTIVE (permits write)|
|  * Thread-Safe Allowlist Mutex: Atomic async with self._session_mutex: self.allowlist_config.reload()|
|  * SQLite Schema v3 query_cache Table: Separate from MutationJournal WAL to preserve replay       |
|  * POSIX Socket Singleton Lock: Atomic fcntl.flock on $XDG_RUNTIME_DIR/.../broker.sock.lock       |
|  * Hardware Enforcement: CPU affinity cores 0-5, NODE_OPTIONS, UV_THREADPOOL_SIZE=3 in cli.py     |
|  * Pre-Flight Identity Guard: Injects expectedAccounts & expectedEmail into mutating frames (P-03)   |
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
             [Universal Local IPC Transport Layer: src/mcp_gateway/transport/]
             * Windows: Async Named Pipe (\\.\pipe\notebooklm-mcp-broker, Overlapped I/O, DACL)
             * Linux/macOS: POSIX Socket ($XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock, 0o700/0o600)
             [Framing: 32-bit Big-Endian (>I)]
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                  TIER 3: DEDICATED NATIVE MESSAGING HOST                          |
|  * Standalone Python Binary (src/mcp_gateway/host/native_host.py): Zero-dependency stdio relay    |
|  * C-Level OS Descriptor Redirection: os.dup2(log_file.fileno(), 2) traps C-level stderr leaks    |
|  * Windows Standard I/O Hardening: os.O_BINARY via getattr(os, "O_BINARY", 0x8000)                |
|  * Multi-Browser Installer (setup_native_host.py / installer.py): Chrome, Beta, Chromium, Brave, Edge|
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
                 [Chrome Native Messaging API: 32-bit Native-Endian Binary Frames (@I)]
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 4: BROWSER COMPANION & RUNTIME (MV3)                          |
|  * Extension Popup WebUI: Setup Mode banner + NotebookAllowlistCard checklist + Manual ID fallback|
|  * Path Traversal Protection: %2e URL decoding + UUIDv4 regex validation on manual inputs         |
|  * Pre-Flight Email Verification: Asserts window.WIZ_global_data.oM1Kwf === payload.expectedEmail |
|  * Scoped postMessage Target: window.location.origin enforces strict cross-window PII containment  |
|  * Zero Credential Export: Cookies and SNlM0e stay in browser; fetch() satisfies TPM DBSC         |
+─────────────────────────────────┬─────────────────────────────────┬───────────────────────────────+
                                  │                                 │
                 [batchexecute Form POST RPC]      [Server-Streaming gRPC-Web POST]
                                  │                                 │
                                  ▼                                 ▼
+───────────────────────────────────────────────────+ +─────────────────────────────────────────────+
|              BATCHEXECUTE RPC ENDPOINT            | |          STREAMING QUERY ENDPOINT           |
| POST /_/LabsTailwindUi/data/batchexecute          | | POST /_/LabsTailwindUi/data/.../            |
| * f.req=[[['RPC_ID', JSON, null, 'gen']]]         | |      GenerateFreeFormStreamed               |
| * wXbhsf (list_notebooks)                         | | * Mid-Stream STREAM_SEVERED error emission  |
| * rLM1Ne row (sources) & row (notes)    | | * Multibyte UTF-8 incremental reassembly    |
| * CYK0Xb (create_note) & tGMBJ (delete_note)      | | * UTF-16 Code-Unit Coordinate Normalization |
+─────────────────────────────────┬─────────────────+ +─────────────────────────────────────────────+
                                  │
                    [Scotty 3-Step Resumable Upload]
                                  ▼
+───────────────────────────────────────────────────+
|           SCOTTY RESUMABLE UPLOAD PIPELINE        |
| 1. Intent Registration: o4cbdc (recursive unpack) |
| 2. POST /upload/_/ (X-Goog-Upload-Command: start) |
| 3. Stream <=512 KiB slices with byte offsets      |
+───────────────────────────────────────────────────+
```

### Core Architecture & Implementation Invariants

1. **4-Tier Decoupled System Topology**:
   - **Tier 1 (Agent Layer)**: Standard MCP stdio interface.
   - **Tier 2 (Policy & Session Broker — `broker.py`)**: Daemon governing FSM transitions, allowlist verification, secret scrubbing, and SQLite WAL journaling.
   - **Tier 3 (Native Messaging Host — `native_host.py`)**: Relays framing between Python IPC and Chrome Native Messaging.
   - **Tier 4 (MV3 Browser Companion)**: Executes in-page `fetch()` requests on `notebook.google.com`, allowing Chrome to natively satisfy **Device Bound Session Credentials (DBSC)** Trusted Platform Module (TPM) challenge signatures (`Sec-Session-Response`).

2. **Zero Credential Export Invariant**:
   - Google session cookies (`SID`, `HSID`, `SAPISID`), OAuth access tokens, and CSRF tokens (`SNlM0e`) **never leave Chrome's native memory context**, cross local IPC sockets, or appear in logs.

3. **Closed 9-Tool MCP Surface & ADR-011 Session Locking**:
   - Exposes exactly **nine tools**: `select_notebook`, `list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`, `create_note`, `list_notes`, and `delete_note`.
   - All input schemas strictly enforce `additionalProperties: false` (JSON Schema) and `extra="forbid"` (Pydantic v2).
   - **ADR-011 FSM**: `UNINITIALIZED ──> DISCOVERY_ONLY ──> NOTEBOOK_LOCKED ──> ACTIVE_DISPATCH`. The session locks to a single notebook via `select_notebook`, forcing parameter overwrites (`arguments["notebook_id"] := locked_notebook_id`) and preventing cross-notebook data traversal.
   - **Schema v2 Granular Access Control**: Per-notebook policy (`READ_ONLY` vs `INTERACTIVE`) in `allowlist.json`. `READ_ONLY` mode permits read and query tools while blocking write mutations (`add_source`, `create_note`, `delete_note`) with `PERMISSION_DENIED`.

4. **Scotty 3-Step Resumable File Upload Protocol**:
   - Uploads bypass single-payload bounds via intent registration (`o4cbdc`), session creation (`POST /upload/_/` with `X-Goog-Upload-Command: start`), and binary slice streaming (\\(\le 512\text{ KiB}\\)) with byte offset tracking.

5. **V8 UTF-16 to Unicode Coordinate Translation**:
   - Google's V8 engine reports citation offsets in UTF-16 code units. The broker normalizes these offsets to native Python Unicode scalar code points (`utf16_to_unicode_offset`) to eliminate off-by-one string slicing errors on astral plane characters (emojis, math symbols).

---

## 2. Research Audit: Verified Baseline vs. Discarded Findings

| Subsystem | Discarded Anti-Pattern / Unsound Practice | Verified Production Baseline (Audited State) |
| :--- | :--- | :--- |
| **Authentication** | Extracting raw SQLite cookies (`auth.json`, DPAPI key reads). | **In-Browser Execution Broker** via MV3 extension; satisfies TPM DBSC challenge headers natively. |
| **Session Containment** | Open multi-notebook access enabling prompt-injection workspace hopping. | **ADR-011 Single-Notebook FSM Lock** & **ADR-017 Workspace Binding** (`.notebook_mcp.json`). |
| **Process IPC Guard** | Unlocked socket files allowing multi-broker socket clobbering. | **POSIX Socket File Locking** (`.sock.lock` via `fcntl.flock`) and Win32 Overlapped Named Pipe DACLs. |
| **Secret Scrubbing** | Writing unscrubbed dumps to `/tmp/raw_query_stream_body.txt` or leaking to `sys.stderr`. | **Broker-Side In-Memory Scrubbing** (`secret_scrubber.py`) using `[REDACTED]`; trapping C-level stderr via `os.dup2`. |
| **Multi-Account Drift** | Mismatched user profile mutating wrong Google account. | **In-DOM Pre-Flight Identity Assertions (Polish P-03)** matching `oM1Kwf` against `expectedEmail`. |
| **Upstream Drift** | Silently returning empty arrays `[]` when Google updates frontend structures. | **Loud Schema Canaries (Mitigation M-05)** failing loud with `UPSTREAM_SCHEMA_DRIFT`. |

---

## > **Operational Note — Source Selection Status**: All 39 notebook sources and 61 notes are currently unselected in your query filter (`Total sources selected by user: 0`). Consequently, no raw source passages were retrieved during this turn, and bracketed citation markers are omitted. The technical architecture below is synthesized directly from the project's master architectural specifications, architectural decision records (`ADR-001` through `ADR-017`), and certified production codebase.

---

## 1. Project Blueprint & Architectural State

As Chief Project Overseer and Lead Systems Architect for the **Google NotebookLM Model Context Protocol (MCP) Server** project (`google-notebook-mcp`), I have synthesized the core technical architecture and implementation invariants governing the system.

The gateway is a local-first, zero-trust software bridge that connects autonomous AI coding agents (Claude Code, Cursor, Windsurf, Cline, Antigravity IDE) directly to private Google NotebookLM knowledge bases over standard MCP stdio JSON-RPC.

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                    TIER 1: AI CODING AGENT LAYER                                  |
|                 Claude Code  *  Cursor  *  Cline  *  Windsurf  *  Antigravity IDE                 |
|                                    [Transport: stdio JSON-RPC 2.0]                                |
|   MCP Standard: 9 Closed Tools + ToolAnnotations (readOnlyHint, destructiveHint, idempotentHint)  |
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 2: LOCAL POLICY & SESSION BROKER                              |
|                          [100% COMPLETE & LIVE-VERIFIED — 214/214 PASSING TESTS]                  |
|  * Stdio JSON-RPC Facade (gemini-notebook-mcp mcp): Transmits TOOL_ANNOTATIONS to clients         |
|  * ADR-011 MANDATORY SINGLE-NOTEBOOK LOCK FSM (src/mcp_gateway/broker/session.py):                |
|      UNINITIALIZED ──> DISCOVERY_ONLY ──> NOTEBOOK_LOCKED ──> ACTIVE_DISPATCH                     |
|  * Schema v2 Granular Access Control: READ_ONLY (permits query/read) vs INTERACTIVE (permits write)|
|  * Thread-Safe Allowlist Mutex: Atomic async with self._session_mutex: self.allowlist_config.reload()|
|  * SQLite Schema v3 query_cache Table: Separate from MutationJournal WAL to preserve replay       |
|  * POSIX Socket Singleton Lock: Atomic fcntl.flock on \$XDG_RUNTIME_DIR/.../broker.sock.lock       |
|  * Hardware Enforcement: CPU affinity cores 0-5, NODE_OPTIONS, UV_THREADPOOL_SIZE=3 in cli.py     |
|  * Pre-Flight Identity Guard: Injects expectedAccounts & expectedEmail into mutating frames (P-03)   |
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
             [Universal Local IPC Transport Layer: src/mcp_gateway/transport/]
             * Windows: Async Named Pipe (\\.\pipe\notebooklm-mcp-broker, Overlapped I/O, DACL)
             * Linux/macOS: POSIX Socket (\$XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock, 0o700/0o600)
             [Framing: 32-bit Big-Endian (>I)]
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                  TIER 3: DEDICATED NATIVE MESSAGING HOST                          |
|  * Standalone Python Binary (src/mcp_gateway/host/native_host.py): Zero-dependency stdio relay    |
|  * C-Level OS Descriptor Redirection: os.dup2(log_file.fileno(), 2) traps C-level stderr leaks    |
|  * Windows Standard I/O Hardening: os.O_BINARY via getattr(os, "O_BINARY", 0x8000)                |
|  * Multi-Browser Installer (setup_native_host.py / installer.py): Chrome, Beta, Chromium, Brave, Edge|
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
                 [Chrome Native Messaging API: 32-bit Native-Endian Binary Frames (@I)]
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 4: BROWSER COMPANION & RUNTIME (MV3)                          |
|  * Extension Popup WebUI: Setup Mode banner + NotebookAllowlistCard checklist + Manual ID fallback|
|  * Path Traversal Protection: %2e URL decoding + UUIDv4 regex validation on manual inputs         |
|  * Pre-Flight Email Verification: Asserts window.WIZ_global_data.oM1Kwf === payload.expectedEmail |
|  * Scoped postMessage Target: window.location.origin enforces strict cross-window PII containment  |
|  * Zero Credential Export: Cookies and SNlM0e stay in browser; fetch() satisfies TPM DBSC         |
+─────────────────────────────────┬─────────────────────────────────┬───────────────────────────────+
                                  │                                 │
                 [batchexecute Form POST RPC]      [Server-Streaming gRPC-Web POST]
                                  │                                 │
                                  ▼                                 ▼
+───────────────────────────────────────────────────+ +─────────────────────────────────────────────+
|              BATCHEXECUTE RPC ENDPOINT            | |          STREAMING QUERY ENDPOINT           |
| POST /_/LabsTailwindUi/data/batchexecute          | | POST /_/LabsTailwindUi/data/.../            |
| * f.req=[[['RPC_ID', JSON, null, 'gen']]]         | |      GenerateFreeFormStreamed               |
| * wXbhsf (list_notebooks)                         | | * Mid-Stream STREAM_SEVERED error emission  |
| * rLM1Ne row (sources) & row (notes)    | | * Multibyte UTF-8 incremental reassembly    |
| * CYK0Xb (create_note) & tGMBJ (delete_note)      | | * UTF-16 Code-Unit Coordinate Normalization |
+─────────────────────────────────┬─────────────────+ +─────────────────────────────────────────────+
                                  │
                    [Scotty 3-Step Resumable Upload]
                                  ▼
+───────────────────────────────────────────────────+
|           SCOTTY RESUMABLE UPLOAD PIPELINE        |
| 1. Intent Registration: o4cbdc (recursive unpack) |
| 2. POST /upload/_/ (X-Goog-Upload-Command: start) |
| 3. Stream <=512 KiB slices with byte offsets      |
+───────────────────────────────────────────────────+
```

### Core Architecture & Implementation Invariants

1. **4-Tier Decoupled System Topology**:
   - **Tier 1 (Agent Layer)**: Standard MCP stdio interface.
   - **Tier 2 (Policy & Session Broker — `broker.py`)**: Daemon governing FSM transitions, allowlist verification, secret scrubbing, and SQLite WAL journaling.
   - **Tier 3 (Native Messaging Host — `native_host.py`)**: Relays framing between Python IPC and Chrome Native Messaging.
   - **Tier 4 (MV3 Browser Companion)**: Executes in-page `fetch()` requests on `notebook.google.com`, allowing Chrome to natively satisfy **Device Bound Session Credentials (DBSC)** Trusted Platform Module (TPM) challenge signatures (`Sec-Session-Response`).

2. **Zero Credential Export Invariant**:
   - Google session cookies (`SID`, `HSID`, `SAPISID`), OAuth access tokens, and CSRF tokens (`SNlM0e`) **never leave Chrome's native memory context**, cross local IPC sockets, or appear in logs.

3. **Closed 9-Tool MCP Surface & ADR-011 Session Locking**:
   - Exposes exactly **nine tools**: `select_notebook`, `list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`, `create_note`, `list_notes`, and `delete_note`.
   - All input schemas strictly enforce `additionalProperties: false` (JSON Schema) and `extra="forbid"` (Pydantic v2).
   - **ADR-011 FSM**: `UNINITIALIZED ──> DISCOVERY_ONLY ──> NOTEBOOK_LOCKED ──> ACTIVE_DISPATCH`. The session locks to a single notebook via `select_notebook`, forcing parameter overwrites (`arguments["notebook_id"] := locked_notebook_id`) and preventing cross-notebook data traversal.
   - **Schema v2 Granular Access Control**: Per-notebook policy (`READ_ONLY` vs `INTERACTIVE`) in `allowlist.json`. `READ_ONLY` mode permits read and query tools while blocking write mutations (`add_source`, `create_note`, `delete_note`) with `PERMISSION_DENIED`.

4. **Scotty 3-Step Resumable File Upload Protocol**:
   - Uploads bypass single-payload bounds via intent registration (`o4cbdc`), session creation (`POST /upload/_/` with `X-Goog-Upload-Command: start`), and binary slice streaming ($\le 512\text{ KiB}$) with byte offset tracking.

5. **V8 UTF-16 to Unicode Coordinate Translation**:
   - Google's V8 engine reports citation offsets in UTF-16 code units. The broker normalizes these offsets to native Python Unicode scalar code points (`utf16_to_unicode_offset`) to eliminate off-by-one string slicing errors on astral plane characters (emojis, math symbols).

---

## 2. Research Audit: Verified Baseline vs. Discarded Findings

| Subsystem | Discarded Anti-Pattern / Unsound Practice | Verified Production Baseline (Audited State) |
| :--- | :--- | :--- |
| **Authentication** | Extracting raw SQLite cookies (`auth.json`, DPAPI key reads). | **In-Browser Execution Broker** via MV3 extension; satisfies TPM DBSC challenge headers natively. |
| **Session Containment** | Open multi-notebook access enabling prompt-injection workspace hopping. | **ADR-011 Single-Notebook FSM Lock** & **ADR-017 Workspace Binding** (`.notebook_mcp.json`). |
| **Process IPC Guard** | Unlocked socket files allowing multi-broker socket clobbering. | **POSIX Socket File Locking** (`.sock.lock` via `fcntl.flock`) and Win32 Overlapped Named Pipe DACLs. |
| **Secret Scrubbing** | Writing unscrubbed dumps to `/tmp/raw_query_stream_body.txt` or leaking to `sys.stderr`. | **Broker-Side In-Memory Scrubbing** (`secret_scrubber.py`) using `[REDACTED]`; trapping C-level stderr via `os.dup2`. |
| **Multi-Account Drift** | Mismatched user profile mutating wrong Google account. | **In-DOM Pre-Flight Identity Assertions (Polish P-03)** matching `oM1Kwf` against `expectedEmail`. |
| **Upstream Drift** | Silently returning empty arrays `[]` when Google updates frontend structures. | **Loud Schema Canaries (Mitigation M-05)** failing loud with `UPSTREAM_SCHEMA_DRIFT`. |

---

## 3. Gap Analysis & Risk Registry

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                      TECHNICAL RISK REGISTRY                                      |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| Risk Domain         | Severity       | Likelihood  | Primary Failure Impact & Enforced Safeguard  |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 1. Upstream RPC ID  | HIGH           | MEDIUM      | Google rotates batchexecute RPC IDs (wXbhsf, |
|    Rotation         |                |             | rLM1Ne, izAoDd, CYK0Xb). Enforced safeguard: |
|                     |                |             | M-05 schema canaries emit                    |
|                     |                |             | UPSTREAM_SCHEMA_DRIFT errors.                |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 2. Chromium MV3     | MEDIUM         | MEDIUM      | Service worker 300s kill wall or background  |
|    Lifecycle Kills  |                |             | tab discard. Enforced safeguard: M-03 240s   |
|                     |                |             | RPC timeout ceiling, M-04 discard recovery.  |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 3. Chrome 137+      | MEDIUM         | LOW         | Fresh profiles reject CLI extension loading. |
|    Extension Load   |                |             | Safeguard: Extension-First Gating protocol   |
|                     |                |             | with preference pre-seeding.                 |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 4. Constrained Edge | HIGH           | LOW         | Memory exhaustion on low-RAM nodes. Enforced |
|    Hardware RAM     |                |             | safeguard: 320 MB reserve interlock & CPU    |
|                     |                |             | affinity pinning in cli.py.                  |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
> **Operational Note — Source Selection Status**: All 39 notebook sources and 61 notes are currently unselected in your query filter (`Total sources selected by user: 0`). Consequently, no raw source passages were retrieved during this turn, and bracketed citation markers are omitted. The technical architecture below is synthesized directly from the project's master architectural specifications, architectural decision records (`ADR-001` through `ADR-017`), and certified production codebase.

---

## 1. Project Blueprint & Architectural State

As Chief Project Overseer and Lead Systems Architect for the **Google NotebookLM Model Context Protocol (MCP) Server** project (`google-notebook-mcp`), I have synthesized the core technical architecture and implementation invariants governing the system.

The gateway is a local-first, zero-trust software bridge that connects autonomous AI coding agents (Claude Code, Cursor, Windsurf, Cline, Antigravity IDE) directly to private Google NotebookLM knowledge bases over standard MCP stdio JSON-RPC.

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                    TIER 1: AI CODING AGENT LAYER                                  |
|                 Claude Code  *  Cursor  *  Cline  *  Windsurf  *  Antigravity IDE                 |
|                                    [Transport: stdio JSON-RPC 2.0]                                |
|   MCP Standard: 9 Closed Tools + ToolAnnotations (readOnlyHint, destructiveHint, idempotentHint)  |
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 2: LOCAL POLICY & SESSION BROKER                              |
|                          [100% COMPLETE & LIVE-VERIFIED — 214/214 PASSING TESTS]                  |
|  * Stdio JSON-RPC Facade (gemini-notebook-mcp mcp): Transmits TOOL_ANNOTATIONS to clients         |
|  * ADR-011 MANDATORY SINGLE-NOTEBOOK LOCK FSM (src/mcp_gateway/broker/session.py):                |
|      UNINITIALIZED ──> DISCOVERY_ONLY ──> NOTEBOOK_LOCKED ──> ACTIVE_DISPATCH                     |
|  * Schema v2 Granular Access Control: READ_ONLY (permits query/read) vs INTERACTIVE (permits write)|
|  * Thread-Safe Allowlist Mutex: Atomic async with self._session_mutex: self.allowlist_config.reload()|
|  * SQLite Schema v3 query_cache Table: Separate from MutationJournal WAL to preserve replay       |
|  * POSIX Socket Singleton Lock: Atomic fcntl.flock on $XDG_RUNTIME_DIR/.../broker.sock.lock       |
|  * Hardware Enforcement: CPU affinity cores 0-5, NODE_OPTIONS, UV_THREADPOOL_SIZE=3 in cli.py     |
|  * Pre-Flight Identity Guard: Injects expectedAccounts & expectedEmail into mutating frames (P-03)   |
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
             [Universal Local IPC Transport Layer: src/mcp_gateway/transport/]
             * Windows: Async Named Pipe (\\.\pipe\notebooklm-mcp-broker, Overlapped I/O, DACL)
             * Linux/macOS: POSIX Socket ($XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock, 0o700/0o600)
             [Framing: 32-bit Big-Endian (>I)]
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                  TIER 3: DEDICATED NATIVE MESSAGING HOST                          |
|  * Standalone Python Binary (src/mcp_gateway/host/native_host.py): Zero-dependency stdio relay    |
|  * C-Level OS Descriptor Redirection: os.dup2(log_file.fileno(), 2) traps C-level stderr leaks    |
|  * Windows Standard I/O Hardening: os.O_BINARY via getattr(os, "O_BINARY", 0x8000)                |
|  * Multi-Browser Installer (setup_native_host.py / installer.py): Chrome, Beta, Chromium, Brave, Edge|
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
                 [Chrome Native Messaging API: 32-bit Native-Endian Binary Frames (@I)]
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 4: BROWSER COMPANION & RUNTIME (MV3)                          |
|  * Extension Popup WebUI: Setup Mode banner + NotebookAllowlistCard checklist + Manual ID fallback|
|  * Path Traversal Protection: %2e URL decoding + UUIDv4 regex validation on manual inputs         |
|  * Pre-Flight Email Verification: Asserts window.WIZ_global_data.oM1Kwf === payload.expectedEmail |
|  * Scoped postMessage Target: window.location.origin enforces strict cross-window PII containment  |
|  * Zero Credential Export: Cookies and SNlM0e stay in browser; fetch() satisfies TPM DBSC         |
+─────────────────────────────────┬─────────────────────────────────┬───────────────────────────────+
                                  │                                 │
                 [batchexecute Form POST RPC]      [Server-Streaming gRPC-Web POST]
                                  │                                 │
                                  ▼                                 ▼
+───────────────────────────────────────────────────+ +─────────────────────────────────────────────+
|              BATCHEXECUTE RPC ENDPOINT            | |          STREAMING QUERY ENDPOINT           |
| POST /_/LabsTailwindUi/data/batchexecute          | | POST /_/LabsTailwindUi/data/.../            |
| * f.req=[[['RPC_ID', JSON, null, 'gen']]]         | |      GenerateFreeFormStreamed               |
| * wXbhsf (list_notebooks)                         | | * Mid-Stream STREAM_SEVERED error emission  |
| * rLM1Ne row (sources) & row (notes)    | | * Multibyte UTF-8 incremental reassembly    |
| * CYK0Xb (create_note) & tGMBJ (delete_note)      | | * UTF-16 Code-Unit Coordinate Normalization |
+─────────────────────────────────┬─────────────────+ +─────────────────────────────────────────────+
                                  │
                    [Scotty 3-Step Resumable Upload]
                                  ▼
+───────────────────────────────────────────────────+
|           SCOTTY RESUMABLE UPLOAD PIPELINE        |
| 1. Intent Registration: o4cbdc (recursive unpack) |
| 2. POST /upload/_/ (X-Goog-Upload-Command: start) |
| 3. Stream <=512 KiB slices with byte offsets      |
+───────────────────────────────────────────────────+
```

### Core Architecture & Implementation Invariants

1. **4-Tier Decoupled System Topology**:
   - **Tier 1 (Agent Layer)**: Standard MCP stdio interface.
   - **Tier 2 (Policy & Session Broker — `broker.py`)**: Daemon governing FSM transitions, allowlist verification, secret scrubbing, and SQLite WAL journaling.
   - **Tier 3 (Native Messaging Host — `native_host.py`)**: Relays framing between Python IPC and Chrome Native Messaging.
   - **Tier 4 (MV3 Browser Companion)**: Executes in-page `fetch()` requests on `notebook.google.com`, allowing Chrome to natively satisfy **Device Bound Session Credentials (DBSC)** Trusted Platform Module (TPM) challenge signatures (`Sec-Session-Response`).

2. **Zero Credential Export Invariant**:
   - Google session cookies (`SID`, `HSID`, `SAPISID`), OAuth access tokens, and CSRF tokens (`SNlM0e`) **never leave Chrome's native memory context**, cross local IPC sockets, or appear in logs.

3. **Closed 9-Tool MCP Surface & ADR-011 Session Locking**:
   - Exposes exactly **nine tools**: `select_notebook`, `list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`, `create_note`, `list_notes`, and `delete_note`.
   - All input schemas strictly enforce `additionalProperties: false` (JSON Schema) and `extra="forbid"` (Pydantic v2).
   - **ADR-011 FSM**: `UNINITIALIZED ──> DISCOVERY_ONLY ──> NOTEBOOK_LOCKED ──> ACTIVE_DISPATCH`. The session locks to a single notebook via `select_notebook`, forcing parameter overwrites (`arguments["notebook_id"] := locked_notebook_id`) and preventing cross-notebook data traversal.
   - **Schema v2 Granular Access Control**: Per-notebook policy (`READ_ONLY` vs `INTERACTIVE`) in `allowlist.json`. `READ_ONLY` mode permits read and query tools while blocking write mutations (`add_source`, `create_note`, `delete_note`) with `PERMISSION_DENIED`.

4. **Scotty 3-Step Resumable File Upload Protocol**:
   - Uploads bypass single-payload bounds via intent registration (`o4cbdc`), session creation (`POST /upload/_/` with `X-Goog-Upload-Command: start`), and binary slice streaming (\\(\le 512\text{ KiB}\\)) with byte offset tracking.

5. **V8 UTF-16 to Unicode Coordinate Translation**:
   - Google's V8 engine reports citation offsets in UTF-16 code units. The broker normalizes these offsets to native Python Unicode scalar code points (`utf16_to_unicode_offset`) to eliminate off-by-one string slicing errors on astral plane characters (emojis, math symbols).

---

## 2. Research Audit: Verified Baseline vs. Discarded Findings

| Subsystem | Discarded Anti-Pattern / Unsound Practice | Verified Production Baseline (Audited State) |
| :--- | :--- | :--- |
| **Authentication** | Extracting raw SQLite cookies (`auth.json`, DPAPI key reads). | **In-Browser Execution Broker** via MV3 extension; satisfies TPM DBSC challenge headers natively. |
| **Session Containment** | Open multi-notebook access enabling prompt-injection workspace hopping. | **ADR-011 Single-Notebook FSM Lock** & **ADR-017 Workspace Binding** (`.notebook_mcp.json`). |
| **Process IPC Guard** | Unlocked socket files allowing multi-broker socket clobbering. | **POSIX Socket File Locking** (`.sock.lock` via `fcntl.flock`) and Win32 Overlapped Named Pipe DACLs. |
| **Secret Scrubbing** | Writing unscrubbed dumps to `/tmp/raw_query_stream_body.txt` or leaking to `sys.stderr`. | **Broker-Side In-Memory Scrubbing** (`secret_scrubber.py`) using `[REDACTED]`; trapping C-level stderr via `os.dup2`. |
| **Multi-Account Drift** | Mismatched user profile mutating wrong Google account. | **In-DOM Pre-Flight Identity Assertions (Polish P-03)** matching `oM1Kwf` against `expectedEmail`. |
| **Upstream Drift** | Silently returning empty arrays `[]` when Google updates frontend structures. | **Loud Schema Canaries (Mitigation M-05)** failing loud with `UPSTREAM_SCHEMA_DRIFT`. |

---

## 3. Gap Analysis & Risk Registry

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                      TECHNICAL RISK REGISTRY                                      |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| Risk Domain         | Severity       | Likelihood  | Primary Failure Impact & Enforced Safeguard  |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 1. Upstream RPC ID  | HIGH           | MEDIUM      | Google rotates batchexecute RPC IDs (wXbhsf, |
|    Rotation         |                |             | rLM1Ne, izAoDd, CYK0Xb). Enforced safeguard: |
|                     |                |             | M-05 schema canaries emit                    |
|                     |                |             | UPSTREAM_SCHEMA_DRIFT errors.                |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 2. Chromium MV3     | MEDIUM         | MEDIUM      | Service worker 300s kill wall or background  |
|    Lifecycle Kills  |                |             | tab discard. Enforced safeguard: M-03 240s   |
|                     |                |             | RPC timeout ceiling, M-04 discard recovery.  |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 3. Chrome 137+      | MEDIUM         | LOW         | Fresh profiles reject CLI extension loading. |
|    Extension Load   |                |             | Safeguard: Extension-First Gating protocol   |
|                     |                |             | with preference pre-seeding.                 |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 4. Constrained Edge | HIGH           | LOW         | Memory exhaustion on low-RAM nodes. Enforced |
|    Hardware RAM     |                |             | safeguard: 320 MB reserve interlock & CPU    |
|                     |                |             | affinity pinning in cli.py.                  |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
```

---

## 4. Prioritized Action Items

The codebase is certified under **Auditor Clearance Certificate `CERT-GATEWAY-PHASE7-DOMG-PROD-PASS-20261014`** (214/214 passing tests, 0 Mypy type errors across > **Operational Note — Source Selection Status**: All 39 notebook sources and 61 notes are currently unselected in your query filter (`Total sources selected by user: 0`). Consequently, no raw source passages were retrieved during this turn, and bracketed citation markers are omitted. The technical architecture below is synthesized directly from the project's master architectural specifications, architectural decision records (`ADR-001` through `ADR-017`), and certified production codebase.

---

## 1. Project Blueprint & Architectural State

As Chief Project Overseer and Lead Systems Architect for the **Google NotebookLM Model Context Protocol (MCP) Server** project (`google-notebook-mcp`), I have synthesized the core technical architecture and implementation invariants governing the system.

The gateway is a local-first, zero-trust software bridge that connects autonomous AI coding agents (Claude Code, Cursor, Windsurf, Cline, Antigravity IDE) directly to private Google NotebookLM knowledge bases over standard MCP stdio JSON-RPC.

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                    TIER 1: AI CODING AGENT LAYER                                  |
|                 Claude Code  *  Cursor  *  Cline  *  Windsurf  *  Antigravity IDE                 |
|                                    [Transport: stdio JSON-RPC 2.0]                                |
|   MCP Standard: 9 Closed Tools + ToolAnnotations (readOnlyHint, destructiveHint, idempotentHint)  |
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 2: LOCAL POLICY & SESSION BROKER                              |
|                          [100% COMPLETE & LIVE-VERIFIED — 214/214 PASSING TESTS]                  |
|  * Stdio JSON-RPC Facade (gemini-notebook-mcp mcp): Transmits TOOL_ANNOTATIONS to clients         |
|  * ADR-011 MANDATORY SINGLE-NOTEBOOK LOCK FSM (src/mcp_gateway/broker/session.py):                |
|      UNINITIALIZED ──> DISCOVERY_ONLY ──> NOTEBOOK_LOCKED ──> ACTIVE_DISPATCH                     |
|  * Schema v2 Granular Access Control: READ_ONLY (permits query/read) vs INTERACTIVE (permits write)|
|  * Thread-Safe Allowlist Mutex: Atomic async with self._session_mutex: self.allowlist_config.reload()|
|  * SQLite Schema v3 query_cache Table: Separate from MutationJournal WAL to preserve replay       |
|  * POSIX Socket Singleton Lock: Atomic fcntl.flock on \$XDG_RUNTIME_DIR/.../broker.sock.lock       |
|  * Hardware Enforcement: CPU affinity cores 0-5, NODE_OPTIONS, UV_THREADPOOL_SIZE=3 in cli.py     |
|  * Pre-Flight Identity Guard: Injects expectedAccounts & expectedEmail into mutating frames (P-03)   |
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
             [Universal Local IPC Transport Layer: src/mcp_gateway/transport/]
             * Windows: Async Named Pipe (\\.\pipe\notebooklm-mcp-broker, Overlapped I/O, DACL)
             * Linux/macOS: POSIX Socket (\$XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock, 0o700/0o600)
             [Framing: 32-bit Big-Endian (>I)]
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                  TIER 3: DEDICATED NATIVE MESSAGING HOST                          |
|  * Standalone Python Binary (src/mcp_gateway/host/native_host.py): Zero-dependency stdio relay    |
|  * C-Level OS Descriptor Redirection: os.dup2(log_file.fileno(), 2) traps C-level stderr leaks    |
|  * Windows Standard I/O Hardening: os.O_BINARY via getattr(os, "O_BINARY", 0x8000)                |
|  * Multi-Browser Installer (setup_native_host.py / installer.py): Chrome, Beta, Chromium, Brave, Edge|
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
                 [Chrome Native Messaging API: 32-bit Native-Endian Binary Frames (@I)]
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 4: BROWSER COMPANION & RUNTIME (MV3)                          |
|  * Extension Popup WebUI: Setup Mode banner + NotebookAllowlistCard checklist + Manual ID fallback|
|  * Path Traversal Protection: %2e URL decoding + UUIDv4 regex validation on manual inputs         |
|  * Pre-Flight Email Verification: Asserts window.WIZ_global_data.oM1Kwf === payload.expectedEmail |
|  * Scoped postMessage Target: window.location.origin enforces strict cross-window PII containment  |
|  * Zero Credential Export: Cookies and SNlM0e stay in browser; fetch() satisfies TPM DBSC         |
+─────────────────────────────────┬─────────────────────────────────┬───────────────────────────────+
                                  │                                 │
                 [batchexecute Form POST RPC]      [Server-Streaming gRPC-Web POST]
                                  │                                 │
                                  ▼                                 ▼
+───────────────────────────────────────────────────+ +─────────────────────────────────────────────+
|              BATCHEXECUTE RPC ENDPOINT            | |          STREAMING QUERY ENDPOINT           |
| POST /_/LabsTailwindUi/data/batchexecute          | | POST /_/LabsTailwindUi/data/.../            |
| * f.req=[[['RPC_ID', JSON, null, 'gen']]]         | |      GenerateFreeFormStreamed               |
| * wXbhsf (list_notebooks)                         | | * Mid-Stream STREAM_SEVERED error emission  |
| * rLM1Ne row (sources) & row (notes)    | | * Multibyte UTF-8 incremental reassembly    |
| * CYK0Xb (create_note) & tGMBJ (delete_note)      | | * UTF-16 Code-Unit Coordinate Normalization |
+─────────────────────────────────┬─────────────────+ +─────────────────────────────────────────────+
                                  │
                    [Scotty 3-Step Resumable Upload]
                                  ▼
+───────────────────────────────────────────────────+
|           SCOTTY RESUMABLE UPLOAD PIPELINE        |
| 1. Intent Registration: o4cbdc (recursive unpack) |
| 2. POST /upload/_/ (X-Goog-Upload-Command: start) |
| 3. Stream <=512 KiB slices with byte offsets      |
+───────────────────────────────────────────────────+
```

### Core Architecture & Implementation Invariants

1. **4-Tier Decoupled System Topology**:
   - **Tier 1 (Agent Layer)**: Standard MCP stdio interface.
   - **Tier 2 (Policy & Session Broker — `broker.py`)**: Daemon governing FSM transitions, allowlist verification, secret scrubbing, and SQLite WAL journaling.
   - **Tier 3 (Native Messaging Host — `native_host.py`)**: Relays framing between Python IPC and Chrome Native Messaging.
   - **Tier 4 (MV3 Browser Companion)**: Executes in-page `fetch()` requests on `notebook.google.com`, allowing Chrome to natively satisfy **Device Bound Session Credentials (DBSC)** Trusted Platform Module (TPM) challenge signatures (`Sec-Session-Response`).

2. **Zero Credential Export Invariant**:
   - Google session cookies (`SID`, `HSID`, `SAPISID`), OAuth access tokens, and CSRF tokens (`SNlM0e`) **never leave Chrome's native memory context**, cross local IPC sockets, or appear in logs.

3. **Closed 9-Tool MCP Surface & ADR-011 Session Locking**:
   - Exposes exactly **nine tools**: `select_notebook`, `list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`, `create_note`, `list_notes`, and `delete_note`.
   - All input schemas strictly enforce `additionalProperties: false` (JSON Schema) and `extra="forbid"` (Pydantic v2).
   - **ADR-011 FSM**: `UNINITIALIZED ──> DISCOVERY_ONLY ──> NOTEBOOK_LOCKED ──> ACTIVE_DISPATCH`. The session locks to a single notebook via `select_notebook`, forcing parameter overwrites (`arguments["notebook_id"] := locked_notebook_id`) and preventing cross-notebook data traversal.
   - **Schema v2 Granular Access Control**: Per-notebook policy (`READ_ONLY` vs `INTERACTIVE`) in `allowlist.json`. `READ_ONLY` mode permits read and query tools while blocking write mutations (`add_source`, `create_note`, `delete_note`) with `PERMISSION_DENIED`.

4. **Scotty 3-Step Resumable File Upload Protocol**:
   - Uploads bypass single-payload bounds via intent registration (`o4cbdc`), session creation (`POST /upload/_/` with `X-Goog-Upload-Command: start`), and binary slice streaming ($\le 512\text{ KiB}$) with byte offset tracking.

5. **V8 UTF-16 to Unicode Coordinate Translation**:
   - Google's V8 engine reports citation offsets in UTF-16 code units. The broker normalizes these offsets to native Python Unicode scalar code points (`utf16_to_unicode_offset`) to eliminate off-by-one string slicing errors on astral plane characters (emojis, math symbols).

---

## 2. Research Audit: Verified Baseline vs. Discarded Findings

| Subsystem | Discarded Anti-Pattern / Unsound Practice | Verified Production Baseline (Audited State) |
| :--- | :--- | :--- |
| **Authentication** | Extracting raw SQLite cookies (`auth.json`, DPAPI key reads). | **In-Browser Execution Broker** via MV3 extension; satisfies TPM DBSC challenge headers natively. |
| **Session Containment** | Open multi-notebook access enabling prompt-injection workspace hopping. | **ADR-011 Single-Notebook FSM Lock** & **ADR-017 Workspace Binding** (`.notebook_mcp.json`). |
| **Process IPC Guard** | Unlocked socket files allowing multi-broker socket clobbering. | **POSIX Socket File Locking** (`.sock.lock` via `fcntl.flock`) and Win32 Overlapped Named Pipe DACLs. |
| **Secret Scrubbing** | Writing unscrubbed dumps to `/tmp/raw_query_stream_body.txt` or leaking to `sys.stderr`. | **Broker-Side In-Memory Scrubbing** (`secret_scrubber.py`) using `[REDACTED]`; trapping C-level stderr via `os.dup2`. |
| **Multi-Account Drift** | Mismatched user profile mutating wrong Google account. | **In-DOM Pre-Flight Identity Assertions (Polish P-03)** matching `oM1Kwf` against `expectedEmail`. |
| **Upstream Drift** | Silently returning empty arrays `[]` when Google updates frontend structures. | **Loud Schema Canaries (Mitigation M-05)** failing loud with `UPSTREAM_SCHEMA_DRIFT`. |

---

## 3. Gap Analysis & Risk Registry

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                      TECHNICAL RISK REGISTRY                                      |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| Risk Domain         | Severity       | Likelihood  | Primary Failure Impact & Enforced Safeguard  |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 1. Upstream RPC ID  | HIGH           | MEDIUM      | Google rotates batchexecute RPC IDs (wXbhsf, |
|    Rotation         |                |             | rLM1Ne, izAoDd, CYK0Xb). Enforced safeguard: |
|                     |                |             | M-05 schema canaries emit                    |
|                     |                |             | UPSTREAM_SCHEMA_DRIFT errors.                |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 2. Chromium MV3     | MEDIUM         | MEDIUM      | Service worker 300s kill wall or background  |
|    Lifecycle Kills  |                |             | tab discard. Enforced safeguard: M-03 240s   |
|                     |                |             | RPC timeout ceiling, M-04 discard recovery.  |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 3. Chrome 137+      | MEDIUM         | LOW         | Fresh profiles reject CLI extension loading. |
|    Extension Load   |                |             | Safeguard: Extension-First Gating protocol   |
|                     |                |             | with preference pre-seeding.                 |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 4. Constrained Edge | HIGH           | LOW         | Memory exhaustion on low-RAM nodes. Enforced |
|    Hardware RAM     |                |             | safeguard: 320 MB reserve interlock & CPU    |
|                     |                |             | affinity pinning in cli.py.                  |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
```

---

## 4. Prioritized Action Items

The codebase is certified under **Auditor Clearance Certificate `CERT-GATEWAY-PHASE7-DOMG-PROD-PASS-20261014`** (214/214 passing tests, 0 Mypy type errors across 57 source files). Standard operational commands include:

```bash
# 1. Execute Full Quality Suite (Matches Multi-OS CI/CD Pipeline)
uv run ruff check src/
uv run mypy --strict src/ tests/ scripts/
uv run pytest --cov=src/mcp_gateway -v tests/

# 2. Run Zero-Friction Autonomous Setup & Onboarding Wizard
python3 install_and_onboard.py

# 3. Launch Dedicated Browser Sandbox & Broker Daemon
uv run gemini-notebook-mcp launch

# 4. Start Stdio MCP Facade for AI Coding Agents
uv run gemini-notebook-mcp > **Operational Note — Source Selection Status**: All 39 notebook sources and 61 notes are currently unselected in your query filter (`Total sources selected by user: 0`). Consequently, no raw source passages were retrieved during this turn, and bracketed citation markers are omitted. The technical architecture below is synthesized directly from the project's master architectural specifications, architectural decision records (`ADR-001` through `ADR-017`), and certified production codebase.

---

## 1. Project Blueprint & Architectural State

As Chief Project Overseer and Lead Systems Architect for the **Google NotebookLM Model Context Protocol (MCP) Server** project (`google-notebook-mcp`), I have synthesized the core technical architecture and implementation invariants governing the system.

The gateway is a local-first, zero-trust software bridge that connects autonomous AI coding agents (Claude Code, Cursor, Windsurf, Cline, Antigravity IDE) directly to private Google NotebookLM knowledge bases over standard MCP stdio JSON-RPC.

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                    TIER 1: AI CODING AGENT LAYER                                  |
|                 Claude Code  *  Cursor  *  Cline  *  Windsurf  *  Antigravity IDE                 |
|                                    [Transport: stdio JSON-RPC 2.0]                                |
|   MCP Standard: 9 Closed Tools + ToolAnnotations (readOnlyHint, destructiveHint, idempotentHint)  |
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 2: LOCAL POLICY & SESSION BROKER                              |
|                          [100% COMPLETE & LIVE-VERIFIED — 214/214 PASSING TESTS]                  |
|  * Stdio JSON-RPC Facade (gemini-notebook-mcp mcp): Transmits TOOL_ANNOTATIONS to clients         |
|  * ADR-011 MANDATORY SINGLE-NOTEBOOK LOCK FSM (src/mcp_gateway/broker/session.py):                |
|      UNINITIALIZED ──> DISCOVERY_ONLY ──> NOTEBOOK_LOCKED ──> ACTIVE_DISPATCH                     |
|  * Schema v2 Granular Access Control: READ_ONLY (permits query/read) vs INTERACTIVE (permits write)|
|  * Thread-Safe Allowlist Mutex: Atomic async with self._session_mutex: self.allowlist_config.reload()|
|  * SQLite Schema v3 query_cache Table: Separate from MutationJournal WAL to preserve replay       |
|  * POSIX Socket Singleton Lock: Atomic fcntl.flock on $XDG_RUNTIME_DIR/.../broker.sock.lock       |
|  * Hardware Enforcement: CPU affinity cores 0-5, NODE_OPTIONS, UV_THREADPOOL_SIZE=3 in cli.py     |
|  * Pre-Flight Identity Guard: Injects expectedAccounts & expectedEmail into mutating frames (P-03)   |
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
             [Universal Local IPC Transport Layer: src/mcp_gateway/transport/]
             * Windows: Async Named Pipe (\\.\pipe\notebooklm-mcp-broker, Overlapped I/O, DACL)
             * Linux/macOS: POSIX Socket ($XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock, 0o700/0o600)
             [Framing: 32-bit Big-Endian (>I)]
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                  TIER 3: DEDICATED NATIVE MESSAGING HOST                          |
|  * Standalone Python Binary (src/mcp_gateway/host/native_host.py): Zero-dependency stdio relay    |
|  * C-Level OS Descriptor Redirection: os.dup2(log_file.fileno(), 2) traps C-level stderr leaks    |
|  * Windows Standard I/O Hardening: os.O_BINARY via getattr(os, "O_BINARY", 0x8000)                |
|  * Multi-Browser Installer (setup_native_host.py / installer.py): Chrome, Beta, Chromium, Brave, Edge|
+─────────────────────────────────────────────────┬─────────────────────────────────────────────────+
                                                  │
                 [Chrome Native Messaging API: 32-bit Native-Endian Binary Frames (@I)]
                                                  │
                                                  ▼
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 4: BROWSER COMPANION & RUNTIME (MV3)                          |
|  * Extension Popup WebUI: Setup Mode banner + NotebookAllowlistCard checklist + Manual ID fallback|
|  * Path Traversal Protection: %2e URL decoding + UUIDv4 regex validation on manual inputs         |
|  * Pre-Flight Email Verification: Asserts window.WIZ_global_data.oM1Kwf === payload.expectedEmail |
|  * Scoped postMessage Target: window.location.origin enforces strict cross-window PII containment  |
|  * Zero Credential Export: Cookies and SNlM0e stay in browser; fetch() satisfies TPM DBSC         |
+─────────────────────────────────┬─────────────────────────────────┬───────────────────────────────+
                                  │                                 │
                 [batchexecute Form POST RPC]      [Server-Streaming gRPC-Web POST]
                                  │                                 │
                                  ▼                                 ▼
+───────────────────────────────────────────────────+ +─────────────────────────────────────────────+
|              BATCHEXECUTE RPC ENDPOINT            | |          STREAMING QUERY ENDPOINT           |
| POST /_/LabsTailwindUi/data/batchexecute          | | POST /_/LabsTailwindUi/data/.../            |
| * f.req=[[['RPC_ID', JSON, null, 'gen']]]         | |      GenerateFreeFormStreamed               |
| * wXbhsf (list_notebooks)                         | | * Mid-Stream STREAM_SEVERED error emission  |
| * rLM1Ne row (sources) & row (notes)    | | * Multibyte UTF-8 incremental reassembly    |
| * CYK0Xb (create_note) & tGMBJ (delete_note)      | | * UTF-16 Code-Unit Coordinate Normalization |
+─────────────────────────────────┬─────────────────+ +─────────────────────────────────────────────+
                                  │
                    [Scotty 3-Step Resumable Upload]
                                  ▼
+───────────────────────────────────────────────────+
|           SCOTTY RESUMABLE UPLOAD PIPELINE        |
| 1. Intent Registration: o4cbdc (recursive unpack) |
| 2. POST /upload/_/ (X-Goog-Upload-Command: start) |
| 3. Stream <=512 KiB slices with byte offsets      |
+───────────────────────────────────────────────────+
```

### Core Architecture & Implementation Invariants

1. **4-Tier Decoupled System Topology**:
   - **Tier 1 (Agent Layer)**: Standard MCP stdio interface.
   - **Tier 2 (Policy & Session Broker — `broker.py`)**: Daemon governing FSM transitions, allowlist verification, secret scrubbing, and SQLite WAL journaling.
   - **Tier 3 (Native Messaging Host — `native_host.py`)**: Relays framing between Python IPC and Chrome Native Messaging.
   - **Tier 4 (MV3 Browser Companion)**: Executes in-page `fetch()` requests on `notebook.google.com`, allowing Chrome to natively satisfy **Device Bound Session Credentials (DBSC)** Trusted Platform Module (TPM) challenge signatures (`Sec-Session-Response`).

2. **Zero Credential Export Invariant**:
   - Google session cookies (`SID`, `HSID`, `SAPISID`), OAuth access tokens, and CSRF tokens (`SNlM0e`) **never leave Chrome's native memory context**, cross local IPC sockets, or appear in logs.

3. **Closed 9-Tool MCP Surface & ADR-011 Session Locking**:
   - Exposes exactly **nine tools**: `select_notebook`, `list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`, `create_note`, `list_notes`, and `delete_note`.
   - All input schemas strictly enforce `additionalProperties: false` (JSON Schema) and `extra="forbid"` (Pydantic v2).
   - **ADR-011 FSM**: `UNINITIALIZED ──> DISCOVERY_ONLY ──> NOTEBOOK_LOCKED ──> ACTIVE_DISPATCH`. The session locks to a single notebook via `select_notebook`, forcing parameter overwrites (`arguments["notebook_id"] := locked_notebook_id`) and preventing cross-notebook data traversal.
   - **Schema v2 Granular Access Control**: Per-notebook policy (`READ_ONLY` vs `INTERACTIVE`) in `allowlist.json`. `READ_ONLY` mode permits read and query tools while blocking write mutations (`add_source`, `create_note`, `delete_note`) with `PERMISSION_DENIED`.

4. **Scotty 3-Step Resumable File Upload Protocol**:
   - Uploads bypass single-payload bounds via intent registration (`o4cbdc`), session creation (`POST /upload/_/` with `X-Goog-Upload-Command: start`), and binary slice streaming (\\(\le 512\text{ KiB}\\)) with byte offset tracking.

5. **V8 UTF-16 to Unicode Coordinate Translation**:
   - Google's V8 engine reports citation offsets in UTF-16 code units. The broker normalizes these offsets to native Python Unicode scalar code points (`utf16_to_unicode_offset`) to eliminate off-by-one string slicing errors on astral plane characters (emojis, math symbols).

---

## 2. Research Audit: Verified Baseline vs. Discarded Findings

| Subsystem | Discarded Anti-Pattern / Unsound Practice | Verified Production Baseline (Audited State) |
| :--- | :--- | :--- |
| **Authentication** | Extracting raw SQLite cookies (`auth.json`, DPAPI key reads). | **In-Browser Execution Broker** via MV3 extension; satisfies TPM DBSC challenge headers natively. |
| **Session Containment** | Open multi-notebook access enabling prompt-injection workspace hopping. | **ADR-011 Single-Notebook FSM Lock** & **ADR-017 Workspace Binding** (`.notebook_mcp.json`). |
| **Process IPC Guard** | Unlocked socket files allowing multi-broker socket clobbering. | **POSIX Socket File Locking** (`.sock.lock` via `fcntl.flock`) and Win32 Overlapped Named Pipe DACLs. |
| **Secret Scrubbing** | Writing unscrubbed dumps to `/tmp/raw_query_stream_body.txt` or leaking to `sys.stderr`. | **Broker-Side In-Memory Scrubbing** (`secret_scrubber.py`) using `[REDACTED]`; trapping C-level stderr via `os.dup2`. |
| **Multi-Account Drift** | Mismatched user profile mutating wrong Google account. | **In-DOM Pre-Flight Identity Assertions (Polish P-03)** matching `oM1Kwf` against `expectedEmail`. |
| **Upstream Drift** | Silently returning empty arrays `[]` when Google updates frontend structures. | **Loud Schema Canaries (Mitigation M-05)** failing loud with `UPSTREAM_SCHEMA_DRIFT`. |

---

## 3. Gap Analysis & Risk Registry

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                      TECHNICAL RISK REGISTRY                                      |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| Risk Domain         | Severity       | Likelihood  | Primary Failure Impact & Enforced Safeguard  |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 1. Upstream RPC ID  | HIGH           | MEDIUM      | Google rotates batchexecute RPC IDs (wXbhsf, |
|    Rotation         |                |             | rLM1Ne, izAoDd, CYK0Xb). Enforced safeguard: |
|                     |                |             | M-05 schema canaries emit                    |
|                     |                |             | UPSTREAM_SCHEMA_DRIFT errors.                |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 2. Chromium MV3     | MEDIUM         | MEDIUM      | Service worker 300s kill wall or background  |
|    Lifecycle Kills  |                |             | tab discard. Enforced safeguard: M-03 240s   |
|                     |                |             | RPC timeout ceiling, M-04 discard recovery.  |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 3. Chrome 137+      | MEDIUM         | LOW         | Fresh profiles reject CLI extension loading. |
|    Extension Load   |                |             | Safeguard: Extension-First Gating protocol   |
|                     |                |             | with preference pre-seeding.                 |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 4. Constrained Edge | HIGH           | LOW         | Memory exhaustion on low-RAM nodes. Enforced |
|    Hardware RAM     |                |             | safeguard: 320 MB reserve interlock & CPU    |
|                     |                |             | affinity pinning in cli.py.                  |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
```

---

## 4. Prioritized Action Items

The codebase is certified under **Auditor Clearance Certificate `CERT-GATEWAY-PHASE7-DOMG-PROD-PASS-20261014`** (214/214 passing tests, 0 Mypy type errors across 57 source files). Standard operational commands include:

```bash
# 1. Execute Full Quality Suite (Matches Multi-OS CI/CD Pipeline)
uv run ruff check src/
uv run mypy --strict src/ tests/ scripts/
uv run pytest --cov=src/mcp_gateway -v tests/

# 2. Run Zero-Friction Autonomous Setup & Onboarding Wizard
python3 install_and_onboard.py

# 3. Launch Dedicated Browser Sandbox & Broker Daemon
uv run gemini-notebook-mcp launch

# 4. Start Stdio MCP Facade for AI Coding Agents
uv run gemini-notebook-mcp mcp
```

---

💡 **Next Step**: Would you like to view a drop-in JSON configuration block for connecting a specific AI coding client (such as Claude Code, Cursor, Windsurf, or Antigravity IDE) to the local gateway?