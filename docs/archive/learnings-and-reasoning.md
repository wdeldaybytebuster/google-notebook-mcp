# Google Notebook MCP System Learnings & Architectural Reasoning

**Version:** 4.2.0-STRICT  
**Status:** Active Invariant (Closed-Loop Grounded & Production Hardened)  
**Complementary Directives:** [`AGENTS.md`](../AGENTS.md), [`docs/ai-workflow-rules.md`](ai-workflow-rules.md), [`docs/architecture.md`](architecture.md)

---

## Executive Summary

During the architectural design, implementation, testing, live self-ingestion, adversarial red-team stress testing, and closed-loop architectural consultation of the **Google Notebooks MCP Gateway**, thirteen core engineering domains produced critical architectural learnings. 

This document serves as the comprehensive repository knowledge base explaining **what** was learned across each domain and the deep **reasoning and root causes** behind each architectural rule. Together with [`AGENTS.md`](../AGENTS.md), these principles preserve system stability, security containment, and deterministic execution.

---

## Domain 1: Closed-Loop Architectural Self-Consultation Protocol

### The Operational Learning
When evaluating complex system designs, formulating implementation plans, or refactoring safety-critical infrastructure:
1. **Source Ingestion Precedes Consultation:** Never rely on transient prompt context alone. Ingest complete project state, architecture documentation, and proposed implementation plans directly into the target notebook via `add_source` with explicit semantic versioning in the title (e.g., `NotebookLM Implementation Plan v2.1`).
2. **Explicit Source-Targeted Grounding:** Queries submitted to the notebook via `query_notebook` must explicitly instruct NotebookLM to ground its evaluation against the exact ingested source titles by name.
3. **Multi-Round Iterative Critique:** Architectural reviews must proceed through distinct evolutionary stages (e.g., v1.0 -> v2.0 -> v2.1), ingesting each refined version as a distinct source until all structural gaps, session lock nuances, and edge failure modes are addressed.
4. **Persistent Provenance Synchronization:** Once an implementation plan is approved and executed, the loop must be closed by appending decisions to repository documentation (`architecture.md`, `progress-tracker.md`), formulating a full completion report, and ingesting the updated documentation back into the notebook.

### The Architectural Reasoning
* **Token Window vs. Grounded RAG:** LLM context windows suffer from attention decay, context dilution, and recency bias when presented with large raw file dumps. In contrast, NotebookLM’s multi-source retrieval-augmented generation (RAG) builds dense semantic indices across ingested documents, enabling deep cross-document synthesis and pinpoint verification of invariants without token degradation.
* **Elimination of Hallucinatory Approvals:** Standard LLM chats frequently produce sycophantic approvals of flawed plans. By forcing NotebookLM to ground its evaluation strictly against ingested sources containing verified wire captures, golden RPC payloads, and hardware constraints, the model surfaces genuine omissions (such as ADR-011 interactive gating gaps and missing wait-until-ready parameters).
* **Immutable Audit Trail:** Storing iterative versions and final completion reports directly within the notebook creates an immutable historical ledger of architectural intent, consultation feedback, and delivery verification accessible to human maintainers and AI agents alike.

---

## Domain 2: Chrome MV3 Service Worker Idle Lifecycle & Keepalive Architecture

### The Operational Learning
1. **30-Second Service Worker Inactivity Limit:** Manifest V3 (MV3) background service workers are ephemeral. Chrome automatically terminates the service worker thread after approximately 30 seconds of inactivity.
2. **Native Messaging Severance on Termination:** When the service worker is terminated by Chrome, all open `chrome.runtime.Port` connections are abruptly destroyed. This causes Chrome to immediately close the stdin/stdout pipes of `native_host.py`, terminating the native host process and dropping the broker's active companion connection.
3. **Active Keepalive Protocol for Multi-Step Ingestion:** Any long-running batch ingestion, multi-source readiness polling, or automated consultation workflow must maintain an active keepalive channel (such as a periodic CDP WebSocket ping evaluating `ensureNativePort()`) every 15–20 seconds to prevent service worker suspension.
4. **`globalThis` Export Invariant:** In MV3 service workers configured as ES modules (`"type": "module"`), top-level functions are module-scoped. Any function needed by external browser automation or CDP inspection must be explicitly bound to `globalThis` (`globalThis.ensureNativePort = ensureNativePort`).

### The Architectural Reasoning
* **Chromium Resource Management:** Google designed Manifest V3 to aggressively reclaim memory on low-power devices by eliminating persistent background pages in favor of event-driven service workers. Chrome does not consider open Native Messaging ports alone as justification to keep a service worker alive if no runtime events are queued.
* **Cascade Failure Mode:** When the service worker idles out, Chrome kills the child process `native_host.py` via `SIGPIPE`/`EOF`. The broker daemon (`broker.py`) detects the socket EOF and resets `_active_companion_writer` to `None`. Subsequent MCP tool calls immediately fail with `AUTH_REQUIRED` error envelopes, aborting multi-source ingestion tasks midway.
* **Non-Disruptive Keepalive:** By pinging `ensureNativePort()` via Chrome DevTools Protocol (CDP) WebSocket, the worker’s event loop receives synthetic activity, maintaining port continuity without triggering intrusive DOM reflows or interfering with active user browsing.

---

## Domain 3: Native Messaging Host Isolation & Path Resiliency

### The Operational Learning
1. **Dynamic `sys.path` Root Injection:** `native_host.py` must explicitly insert its source root into `sys.path` (`sys.path.insert(0, _src_root)`) at startup before importing project modules.
2. **Zero Third-Party Dependencies:** `native_host.py` and its direct imports (`secret_scrubber.py`, etc.) must run purely on the Python standard library with zero external pip dependencies (`pydantic`, `click`, etc.).
3. **Multi-Tier Runtime Socket Discovery:** The native bridge must dynamically probe and resolve Unix domain socket paths in order:
   - `$XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock`
   - `~/.config/notebooklm-mcp-bridge/broker.sock`
   - `/tmp/notebooklm-mcp-broker.sock`
   A symlink should link `~/.config/notebooklm-mcp-bridge/broker.sock` directly to `/tmp/notebooklm-mcp-broker.sock` for cross-environment compatibility.

### The Architectural Reasoning
* **Host Subprocess Execution Environment:** Chrome launches native messaging hosts as direct subprocesses of `/usr/bin/python3` using the manifest path defined in `~/.config/google-chrome-beta/NativeMessagingHosts/`. Chrome does **not** activate the virtual environment (`.venv`), does not source shell profiles (`.bashrc`), and does not inherit terminal environment variables (`PYTHONPATH`, `MCP_BROKER_SOCKET`).
* **The Silent Crash Anti-Pattern:** If `native_host.py` attempts to import a third-party dependency not present in global system Python, or fails to find internal modules because the current working directory is the user's home folder, the Python interpreter exits immediately with an unhandled `ImportError`. Chrome logs this generically as `Native host has exited`, giving no stderr feedback to the extension.
* **Process Sandboxing & Permissions:** Different Linux desktop environments (Crostini, GNOME, Wayland compositors) grant differing permissions to `$XDG_RUNTIME_DIR`. Providing robust fallback across standard XDG paths and `/tmp/` guarantees deterministic bridge connection across CLI shells, IDE tasks, and browser subprocesses.

---

## Domain 4: ADR-011 Interactive Single-Notebook Session Lock

### The Operational Learning
1. **Two-Tier Operational Lifecycle:** The MCP gateway strictly enforces two mutually exclusive states:
   - `DISCOVERY_ONLY`: The initial state upon connection. The client can only execute `list_notebooks` and `select_notebook`. All operational tools (`get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`) are gated and reject requests with `SESSION_UNLOCKED`.
   - `ACTIVE_DISPATCH`: Triggered once `select_notebook` successfully locks a valid `notebook_id`. Generates an HMAC-SHA256 session token and binds all operational tools strictly to that single notebook.
2. **Deterministic Session Locking Contract:**
   - Attempting an operational call before `select_notebook` -> Returns `SESSION_UNLOCKED`.
   - Attempting to call `select_notebook` with a different notebook ID after a lock is established -> Returns `SESSION_LOCKED`.
   - `list_notebooks` once locked automatically filters results exclusively to the active locked notebook.
3. **Strict Parameter Validation:** All schemas enforce `additionalProperties: false` and `extra="forbid"`. Unrecognized parameters return `INVALID_ARGUMENT`.

### The Architectural Reasoning
* **Cross-Notebook Contamination & Prompt Injection:** NotebookLM allows users to store highly confidential personal, medical, financial, or proprietary corporate data across multiple notebooks. If an AI agent could switch notebooks dynamically or issue queries against arbitrary notebook IDs without interactive human consent, a prompt injection attack in one notebook could exfiltrate private data from another notebook.
* **Blast-Radius Containment:** By locking the session at initialization, the agent’s execution envelope is physically restricted to a single verified domain. Even if an agent hallucinates or receives malicious prompt instructions to inspect another notebook, the broker gateway strictly rejects the call at the IPC boundary.
* **HMAC Session Integrity:** Generating a cryptographically signed session token prevents session hijacking across multiplexed IPC clients and guarantees that only the authenticated orchestrator that initiated the session can dispatch mutations.

---

## Domain 5: Google Internal RPC Wire Invariants & Resumable Streaming

### The Operational Learning
1. **Polymorphic Ingestion Routing:**
   - Text, pasted snippets, URLs, and YouTube links must be ingested via the batchexecute `izAoDd` RPC envelope.
   - Binary files (PDFs, Markdown documents, images, audio) must follow the Scotty 3-step resumable upload protocol:
     1. Intent Registration (`o4cbdc` payload acquiring server `sourceId`).
     2. Session Creation (in-browser MV3 fetch to `/upload/_/LabsTailwindUi/...` acquiring `x-goog-upload-url`).
     3. Raw Byte Finalization (`upload, finalize` streaming).
2. **UTF-16 to Unicode Citation Span Normalization:** NotebookLM backend streaming citations return character offsets indexed by JavaScript UTF-16 code units. These must be transformed into Unicode scalar code points (`start_char`, `end_char`) against the full decoded text.
3. **Readiness Polling with Exponential Backoff and Full Jitter:** When `add_source` is invoked with `wait_until_ready=true`, poll `rLM1Ne` row `[102]`, index `4` readiness enum (`PROCESSING = 1`, `READY = 2`, `ERROR = 3`). Polling intervals must use full jitter:
   $$\text{delay} = \text{random.uniform}(0, \min(\text{base\_delay} \times 2^{\text{attempt}}, \text{max\_delay}))$$

### The Architectural Reasoning
* **Google batchexecute Serialization Mechanics:** Google internal web applications rely on batchexecute RPC serialization where payload envelopes contain positional array indices rather than named keys. Bypassing the browser session to send synthetic HTTP requests violates Device Bound Session Credentials (DBSC) and triggers bot-detection barriers. Routing through the native extension preserves valid authentication cookies and session state natively.
* **JavaScript Surrogate Pair Drift:** JavaScript strings represent astral plane characters (emojis, complex symbols, math notations) as surrogate pairs (two 16-bit code units). Python strings index Unicode codepoints as single characters. Without normalized span translation, citation highlights drift out of alignment, corrupting grounded source references.
* **Thundering Herd & Rate Limit Prevention:** Polling Google endpoints at fixed intervals during multi-source ingestions triggers rate-limiting (`429 Too Many Requests`) or abrupt connection throttling. Full jitter distributes network requests probabilistically across time, ensuring smooth, deterministic convergence to `READY`.

---

## Domain 6: Edge Hardware Profile & Resource-Constrained System Governance

### The Operational Learning
1. **Strictly Sequential Command Spawning:** Never run concurrent long-running commands, test suites, or heavy background processes. Each process must fully exit and allow kernel/V8 garbage collection before the next begins.
2. **V8 Memory Ceilings:** All Node.js and npm invocations must be prefixed with `NODE_OPTIONS="--max-old-space-size=1024"`.
3. **Thread Pool and Worker Capping:** Set `UV_THREADPOOL_SIZE=3` in environment variables. Cap test runners and worker pools to `--maxWorkers=4`, reserving at least 2 CPU cores for the Linux OS and Wayland graphical compositor.
4. **GitNexus Worker Timeout Buffering:** On low-power hardware, initialize GitNexus knowledge graph commands with `GITNEXUS_WORKER_READY_TIMEOUT_MS=20000` to prevent IPC worker ready timeouts during code analysis.

### The Architectural Reasoning
* **Hardware Profile Reality:** The host system operates on an Intel Core i3-N305 (8 Gracemont E-cores, no hyperthreading, 15W TDP) with ~6.4 GiB RAM and zero swap space under an active `earlyoom` daemon (`-m 5 -s 5`).
* **eMMC 5.1 Storage Bottleneck:** The storage subsystem uses eMMC 5.1 flash memory, which lacks Native Command Queuing (NCQ) and full-duplex operation. Concurrent disk write operations (e.g., parallel builds + vector indexing + test runner logs) saturate the flash controller queue, causing extreme I/O wait latency and UI lockups.
* **The `earlyoom` Cliff:** When memory usage exceeds 95%, `earlyoom` immediately kills the highest-memory process without warning. Spawning concurrent Node.js processes or unconstrained Python workers easily triggers this threshold. Imposing strict memory ceilings and sequential execution guarantees uninterrupted system stability.

---

## Domain 7: Scotty Resumable Upload Wire Un-Nesting & Status Invariants

### The Operational Learning
1. **Recursive Source ID Unpacking:** The `o4cbdc` RPC response format nests the server-assigned source identifier inside multi-layered arrays (e.g., `data[0] = [['<uuid>'], 'filename', ...]`). Extracting this value with standard indexing or naive stringification yields `str(source_id) == "['<uuid>']"` (containing literal brackets and quotes).
2. **Scotty Wire Failure Mode:** Passing a bracketed string into Scotty session creation headers (`SOURCE_ID: "['<uuid>']"`) results in an HTTP 200 upload acceptance, but the backend ingestion worker cannot map the byte stream to the notebook's internal metadata row. The source hangs indefinitely in processing status `0` or `5`.
3. **Mandatory Regex Validation:** The gateway must recursively unpack nested arrays until a string is reached:
   ```python
   while isinstance(sid, list) and sid:
       sid = sid[0]
   if not isinstance(sid, str) or not re.match(r"^[0-9a-fA-F-]{36}$", sid):
       raise ValueError(f"Malformed source ID unpacked: {sid}")
   ```
4. **Pre-Consultation Readiness Barrier:** An uploaded source must NOT be presumed available for query consultation simply because the HTTP upload completed. The gateway and agent must verify via `rLM1Ne` row `[102]` index 4 that the source has transitioned to `READY (2)`. In UI testing, the source checkbox must be verified active in the DOM before submitting queries.

### The Architectural Reasoning
* **Google Internal RPC Protocol Drift:** Google’s internal batchexecute RPC serialization uses position-indexed JSON arrays whose depth and structure vary between RPC versions. Naive type conversions introduce silent serialization errors that pass boundary validation but fail silently in Google's asynchronous processing pipeline.
* **Asynchronous Indexing Latency:** Scotty uploads only finalize raw storage ingestion; text extraction, layout parsing, and embedding indexing occur asynchronously on Google Cloud workers. Querying before readiness causes the model to either hallucinate answers or fall back to pre-existing sources without incorporating the new document.

---

## Domain 8: Windows Native Framing, Stderr Redirection & Socket Path Bounds

### The Operational Learning
1. **Binary Stdin/Stdout Stream Pinning:** On Windows platforms, Python defaults `sys.stdin` and `sys.stdout` to text translation mode, converting newline characters `\n` to `\r\n`. This silently corrupts the 4-byte little-endian length prefix (`struct.pack("<I", length)`) expected by Chrome's Native Messaging protocol. Windows hosts must explicitly force binary translation:
   ```python
   if sys.platform == "win32":
       import msvcrt, os
       msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
       msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
   ```
2. **Atomic Stderr Redirection:** Chrome’s Native Messaging host architecture captures the child process's stdout pipe as the message wire. Any unhandled library log or diagnostic print (e.g. from Pydantic, Click, or Python warnings) written to stdout breaks JSON framing and crashes the host. Native hosts must redirect stderr to dedicated log files or `nul` at the earliest startup hook via `setup_stderr_redirection()`.
3. **Windows `UNIX_PATH_MAX` Buffer Limit (108-Character Ceiling):** While modern Windows 10/11 supports `AF_UNIX` sockets, Microsoft’s WinSock `sockaddr_un` structure enforces a strict 108-character buffer limit. Paths in `%LOCALAPPDATA%` frequently exceed 108 characters on corporate or long username profiles, triggering `[WinError 10040]` or `FileNotFoundError`.
4. **Safe Fallback Pathing:** The socket path resolution must check `len(path) <= 108`. If the path exceeds 108 characters, it must fall back to short directory hashing or Windows Named Pipes (`\\.\pipe\notebooklm-mcp-broker`).

### The Architectural Reasoning
* **Chrome Native Messaging Protocol Rigidity:** Chrome’s Native Messaging protocol is an unforgiving wire contract: exactly 4 bytes of unsigned length header followed by exactly N bytes of valid JSON. Any extraneous byte inserted by `\r\n` line-ending conversion or stderr leakage desynchronizes the frame boundary, causing Chrome to immediately kill the native host with `Error: Native host has exited`.
* **Platform POSIX Parity Limits:** Developers assume `AF_UNIX` behaves identically across Linux, macOS, and Windows. On Linux, socket paths support up to 108 bytes, but paths are typically short (`/run/user/1000/...`). On Windows, user application data paths are deeply nested (`C:\Users\username\AppData\Local\...`). Explicit length gating prevents unpredictable crashes on Windows deployments.

---

## Domain 9: Model Consultation Disambiguation & Grounding Verification

### The Operational Learning
1. **Decoupling Baseline Specs from Candidate Plans:** When querying NotebookLM for architectural critique, query templates must never conflate the baseline specification title with the candidate plan title.
   - **Anti-Pattern:** *"Evaluate the Google Notebooks MCP Architecture Updated Information v2.1 against our plan..."* (causes the model to review the baseline against itself).
   - **Correct Protocol:**
     ```
     SPEC_SOURCE: "Google Notebooks MCP Architecture Updated Information v2.1"
     CANDIDATE_PLAN: "NotebookLM Implementation Plan v3.1"
     PROMPT: "Evaluate the proposed architecture in candidate source [CANDIDATE_PLAN] against all verified constraints in baseline source [SPEC_SOURCE]."
     ```
2. **Notebook Identity Verification:** Never identify target notebooks by transient UUIDs alone. The agent/gateway must resolve notebooks by their verified human title (`"Google Notebooks MCP"`) and verify source count (e.g. 46 sources) to prevent navigating to temporary test workspaces.
3. **Grounding Verification via Citation Offsets:** Every consultation response must be verified for non-empty citation offsets (`citations`). A response with zero citations indicates that NotebookLM responded from general model weights rather than ingested sources, indicating ungrounded evaluation.

### The Architectural Reasoning
* **Attention Bias in LLM RAG:** Large language models in multi-source RAG settings exhibit strong lexical matching bias. If a query mentions "v2.1", the retrieval engine retrieves chunks from the v2.1 baseline source and ignores newly uploaded v3.1 plan chunks, resulting in false approvals of superseded plans.
* **Workspace Isolation:** Developers and testers frequently create temporary scratchpad notebooks (`"Test Notebook"`). If an orchestrator locks the wrong notebook, consultation queries run against incomplete or missing reference documents, compromising safety verification.

---

## Domain 10: Modern MCP Error Taxonomy (2026-07-28), Distributed Tracing & Storage Concurrency

### The Operational Learning
1. **MCP Error Taxonomy Compliance:** All tool failures must return `CallToolResult(is_error=True)` containing structured failure payloads with closed error categorization:
   - `AUTH_REQUIRED`: Chrome companion or Google session disconnected.
   - `SESSION_UNLOCKED`: Operation attempted in `DISCOVERY_ONLY` before `select_notebook`.
   - `SESSION_LOCKED`: Attempted to switch notebooks after lock established.
   - `ALLOWLIST_DENIED`: Notebook not in configured allowlist.
   - `NOT_FOUND`: Notebook, source, or note not found.
   - `INVALID_ARGUMENT`: Schema validation or parameter parsing error.
   - `MUTATION_UNKNOWN`: Timeout or ambiguous state during mutation.
   - `INTERNAL`: Unhandled gateway exception.
2. **Distributed W3C `traceparent` Propagation:** Every request across the 5-hop bridge (MCP Client $\rightarrow$ Broker $\rightarrow$ Native Host $\rightarrow$ Service Worker $\rightarrow$ Page DOM) must carry a W3C `traceparent` header (`00-{trace_id}-{parent_id}-{flags}`). This enables single-trace correlation across Python logs, native messaging framing, and browser console events.
3. **SQLite WAL Concurrency & Jitter Retry:** Fast concurrent access to `journal.db` causes database lock contention. The storage layer must enforce:
   - `PRAGMA journal_mode=WAL;`
   - `PRAGMA busy_timeout=30000;`
   - Exponential backoff retry loop with full jitter (`_execute_with_busy_retry`) for all journal writes.

### The Architectural Reasoning
* **Client-Side Error Handling Determinism:** Modern MCP clients (Claude Code, Antigravity IDE, Cursor) parse structured error codes to decide whether to prompt the user, retry automatically, or abort. Generic string errors force agents to guess failure causes.
* **Multi-Process Observability:** When an ingestion or streaming call stalls, developers need to know whether the failure occurred in the Python broker, the native host IPC pipe, the Chrome service worker, or Google's backend. W3C distributed tracing provides end-to-end auditability.
* **Journal Resiliency:** SQLite in default rollback journal mode acquires exclusive file locks during write transactions, causing multi-process clients to fail with `sqlite3.OperationalError: database is locked`. WAL mode permits concurrent readers while writes execute.

---

## Domain 11: System Roadmap & Required Functional Enhancements

Through full-system testing and closed-loop operational consultation, five critical functional additions have been identified for the project roadmap:

### 1. Human-Readable Notebook Selection (`notebook_title` in `select_notebook`)
* **Problem:** Currently, `select_notebook` requires a 36-character UUID. Users naturally specify notebooks by human title (e.g. `"Google Notebooks MCP"`).
* **Feature:** Extend `select_notebook` to accept optional `title: str`. When provided:
  - Gateway queries `list_notebooks`.
  - Performs exact or normalized case-insensitive title matching.
  - Verifies uniqueness (errors if ambiguous duplicates exist).
  - Resolves to `notebook_id` and establishes ADR-011 session lock.

### 2. Autonomous Bidirectional Broker Keepalive & Healthcheck
* **Problem:** Keeping Chrome MV3 alive currently requires an external CDP script (`scripts/keepalive.js`).
* **Feature:**
  - Broker daemon transmits a periodic `PING` frame to the native host every 15 seconds over the Unix domain socket.
  - Extension service worker schedules a `chrome.alarms` periodic tick (every 20s) that calls `ensureNativePort()`.
  - Proactive companion health reporting: broker marks companion as `DEGRADED` or `DISCONNECTED` immediately on heartbeat failure, returning diagnostic hints in `AUTH_REQUIRED` errors.

### 3. Source-Restricted Q&A Filtering (`source_ids` in `query_notebook`)
* **Problem:** `query_notebook` currently queries all active sources in the notebook. In large notebooks (40+ sources), this dilutes focus and increases response latency.
* **Feature:** Add optional `source_ids: list[str]` parameter to `query_notebook`.
  - Gateway instructs the page bridge to select only the specified sources in the DOM before initiating `GenerateFreeFormStreamed`.
  - Enables pinpoint, source-restricted RAG consultation (e.g. querying only the architecture spec and plan v3.1).

### 4. Dedicated Note Management Tools (`create_note`, `list_notes`, `delete_note`)
* **Problem:** NotebookLM supports user notes alongside sources. Ingesting completion reports into Notes is instantaneous and bypasses Scotty processing delays.
* **Feature:** Expose dedicated MCP tools:
  - `create_note(title: str, content: str) -> dict`
  - `list_notes(page_size: int = 50, cursor: str | None = None) -> dict`
  - `delete_note(note_id: str) -> dict`
  - Enables agents to save intermediate reasoning, planning artifacts, and completion summaries directly into the notebook studio.

### 5. MCP Streaming Progress Notifications
* **Problem:** Binary file uploads and readiness polling can take 15–60 seconds, during which the client UI appears frozen.
* **Feature:** Implement MCP protocol `notifications/progress`:
  - Send progress updates during Scotty byte stream chunks (0% $\rightarrow$ 100%).
  - Send progress updates on each readiness polling attempt with elapsed time and retry count.

---

## Domain 12: Adversarial Red-Team Proof-of-Break Discoveries & System Vulnerabilities

During the formulation and adversarial stress-testing of Implementation Plan v4.1, ten critical architectural vulnerabilities and edge failure modes were uncovered across the distributed system topology:

### 1. Session Transition TOCTOU & Asynchronous Title Resolution Race (M-01)
* **The Operational Learning:** When `select_notebook` is called with a human-readable title, it performs an asynchronous network fetch (`wXbhsf`) to enumerate notebooks and resolve the title to a UUID. If concurrent requests from other tools or agent threads arrive before title resolution completes, they observe an unlocked session state (`DISCOVERY_ONLY`) and either race to claim the lock or fail with `SESSION_UNLOCKED`.
* **The Architectural Reasoning:** Without an atomic session mutex (`self._session_mutex = asyncio.Lock()`), the time-of-check to time-of-use (TOCTOU) gap permits concurrent coroutines to interleave. Wrapping title resolution and state transition inside `_session_mutex` guarantees that all concurrent calls either queue deterministically behind the lock acquisition or immediately receive a retryable `RESOLVING_SESSION` envelope.

### 2. IPC Socket Frame Interleaving During Multi-Part 512 KiB Scotty Chunk Streaming (M-02)
* **The Operational Learning:** Binary file ingestion via the Scotty protocol requires slicing payloads into 512 KiB chunks and transmitting them across the single local IPC socket connecting the Python broker and the native host. If another tool (such as `list_sources` or `query_notebook`) sends an IPC frame while chunk streaming is underway, raw byte frames interleave, destroying the length-prefixed framing and crashing the native messaging host.
* **The Architectural Reasoning:** The companion IPC channel is a single multiplexed stream. A dedicated `_companion_ipc_mutex = asyncio.Lock()` must enforce exclusive ownership of the IPC writer across all multi-part chunk dispatches until the upload stream is fully finalized or aborted.

### 3. Chromium MV3 300-Second Hard Execution Watchdog Ceiling (M-03)
* **The Operational Learning:** Manifest V3 background service workers enforce a hard 300-second execution watchdog. Any asynchronous operation or promise that remains pending at 300 seconds triggers abrupt termination of the service worker thread by Chrome without executing rejection handlers or cleanup logic.
* **The Architectural Reasoning:** Single synchronous RPC operations must be strictly clamped to a **240-second ceiling**, providing a 60-second safety buffer below Chrome's 300-second hard kill wall. Streaming queries (`GenerateFreeFormStreamed`) must emit native port message deltas incrementally to continually reset the Chrome event loop watchdog.

### 4. Chromium Memory Saver Proactive Tab Discard Prevention vs Reactive Fail-Safe (M-04)
* **The Operational Learning:** Under system memory pressure (typical on edge devices with 6.4 GB RAM), Chromium's proactive Memory Saver silently discards background tabs. When the `notebook.google.com` tab is discarded, all pending `window.postMessage` promises hang indefinitely until gateway timeouts elapse.
* **The Architectural Reasoning:** A two-tier defense is required:
  - **Proactive:** Explicitly mark the notebook tab with `chrome.tabs.update(tab.id, { autoDiscardable: false })` immediately upon creation and during health checks.
  - **Reactive:** Register a `chrome.tabs.onUpdated` listener monitoring `changeInfo.discarded === true`. If discarded, immediately drain and reject all pending promises with a retryable `TAB_DISCARDED` error envelope, preventing hanging requests and tab thrashing.

### 5. Silent Upstream Schema Drift Traps in `list_notes` & Mandatory Loud Canaries (M-05)
* **The Operational Learning:** User notes reside at `rLM1Ne` row `[0][17]`. Naive extraction logic using defensive guards (e.g. `if len(data[0]) > 17: notes = data[0][17]` or `try ... except: return []`) silently returns an empty list `[]` whenever Google updates or shifts the underlying array index.
* **The Architectural Reasoning:** Masking upstream schema drift as an empty collection leads AI agents to falsely believe a notebook contains no notes, potentially recreating duplicate notes or missing critical instructions. The gateway must implement loud failure canaries: if the expected array layout or type signature shifts, it must fail closed and return a non-retryable `UPSTREAM_SCHEMA_DRIFT` error envelope with complete structural diagnostics.

### 6. Strict Grounding Invariant & Zero-Citation Rejection (M-06)
* **The Operational Learning:** During Q&A queries, NotebookLM can occasionally return responses where the model answered entirely from internal pre-training weights rather than ingested sources, resulting in an empty citation list (`len(citations) == 0`).
* **The Architectural Reasoning:** Returning ungrounded answers breaches `AGENTS.md` Rule XI.3 and defeats the purpose of grounded enterprise RAG. The gateway must enforce a hard fail-closed gate: if citations are empty, return `ok: false` with `error.code: "UNGROUNDED_RESPONSE"`.

### 7. Native C-Level File Descriptor 2 Leaks Corrupting 32-Bit Binary Length Headers (M-07)
* **The Operational Learning:** Python-level redirection (`sys.stderr = log_file`) only intercepts writes issued through Python's standard library. Low-level C extensions, runtime aborts, and glibc warnings write directly to OS file descriptor 2. In Chrome Native Messaging, any stray byte written to standard error can desynchronize or corrupt the 4-byte little-endian message framing.
* **The Architectural Reasoning:** Native host bootstrap must execute `os.dup2(log_file.fileno(), 2)` at early boot before any library imports or third-party modules initialize. Additionally, standard input and output streams must immediately be pinned to binary mode (`os.O_BINARY`) on Windows platforms.

### 8. Atomic SQLite Table Recreation & WAL Schema Migrations (M-08)
* **The Operational Learning:** Altering SQLite tables to expand `CHECK` constraints (e.g. adding new mutation types or statuses) requires dropping and recreating tables. If an `earlyoom` eviction or power drop occurs during table migration on low-resource hardware, the database file is left corrupted or empty.
* **The Architectural Reasoning:** Schema upgrades must be guarded by `PRAGMA user_version < 2` and wrapped strictly within an atomic transaction:
  `PRAGMA foreign_keys = OFF; BEGIN IMMEDIATE TRANSACTION; ... PRAGMA user_version = 2; COMMIT; PRAGMA foreign_keys = ON;`.
  Combined with WAL mode and `busy_timeout=30000`, this guarantees complete atomicity against crashes.

### 9. Fetch Interceptor Stream Consumption Hazard (`bodyUsed`) & Safe String Inspection (M-09)
* **The Operational Learning:** In-browser fetch interception intended to harvest session tokens (`SNlM0e`, `FdrFJe`) by attaching stream readers or calling `.text()` / `.json()` on a `ReadableStream` body locks the stream and sets `bodyUsed = true`. This causes the application's original fetch to throw `TypeError: Already read`.
* **The Architectural Reasoning:** Fetch interceptors must strictly verify `!response.bodyUsed` and only inspect string or `URLSearchParams` bodies. Primary authentication tokens must be extracted directly from `window.WIZ_global_data` rather than mutating runtime network streams.

### 10. Scope-Restricted Source Readiness Gating (M-10)
* **The Operational Learning:** Production notebooks often accumulate legacy or scratchpad sources that have permanently failed (`status=3`) or stalled in processing (`status=1`). If `query_notebook` validates the readiness of all sources in the notebook prior to dispatching queries, healthy sources cannot be queried.
* **The Architectural Reasoning:** Readiness verification must be strictly scoped to the `source_ids` targeted for the query (or active allowlisted sources). Stalled or failed sources outside the active query scope are ignored, preventing global query blockades.

---

## Domain 13: NotebookLM Grounded Consultation Protocol & Operational Polish (Plan v4.2)

During the live in-situ closed-loop architectural consultation of Plan v4.1 against the official `"Google Notebooks MCP"` knowledge base (Source ID `11111111-1111-1111-1111-111111111111`), four operational polish items were identified and incorporated into Plan v4.2:

### 1. Mid-Stream Error Delta Emission (`STREAM_SEVERED`) on Transport Drop (P-01)
* **The Operational Learning:** During long streaming queries (`GenerateFreeFormStreamed`), if the upstream browser connection or companion socket severs mid-stream after initial token chunks have already been emitted, standard MCP clients hang indefinitely waiting for the end-of-stream delimiter.
* **The Architectural Reasoning:** The stream parser and broker must trap abrupt transport EOF or disconnect events and immediately emit a structured error delta frame:
  `{"type": "error_delta", "error": {"code": "STREAM_SEVERED", "message": "Stream severed unexpectedly by upstream transport.", "retryable": true}}`
  before terminating the stream. This allows client agents to immediately detect the failure and execute recovery or retry logic without waiting for timeout.

### 2. Scotty Upload Session URL Resumability Caching & Byte Offset Query Resumption (P-02)
* **The Operational Learning:** On edge hardware with limited RAM and network fluctuations, multi-megabyte file uploads via Scotty that disconnect midway previously forced a full restart from byte 0, wasting bandwidth and wearing eMMC 5.1 NAND flash.
* **The Architectural Reasoning:** Cache the active Scotty `upload_session_url` in `chrome.storage.session` keyed by `{notebook_id}:{source_id}`. On replay, issue an `X-Goog-Upload-Command: query` request to fetch the current server-side `X-Goog-Upload-Offset`, then resume byte slicing from that exact offset.

### 3. Pre-Flight Active Account Identity Verification Before Mutating RPCs (P-03)
* **The Operational Learning:** Chrome profiles with multiple signed-in Google accounts can silently switch between `authuser=0`, `authuser=1`, etc., if tabs are navigated or background sync occurs. A mutation dispatched to the wrong account causes authorization failures or writes data to an unintended user's notebook.
* **The Architectural Reasoning:** In `page-main.js`, assert `window.WIZ_global_data.oM1Kwf === payload.expectedEmail` before dispatching any mutating RPC (`add_source`, `create_note`, `delete_note`). If mismatched, fail closed with `PERMISSION_DENIED` and diagnostic account details.

### 4. Un-Hashed Client Request ID Propagation (`_meta.mcp_correlation_id`) (P-04)
* **The Operational Learning:** While internal HMAC-SHA256 hashing is required for database idempotency keys and journal records, converting client-supplied alphanumeric correlation tokens purely into hashes makes cross-system debugging and client log correlation opaque.
* **The Architectural Reasoning:** The gateway must preserve the raw client `request_key` / `idempotency_key` as an un-hashed `_meta.mcp_correlation_id` across all log records, internal dispatch contexts, and output error envelopes alongside W3C `traceparent` headers.

---

## Architecture Traceability Matrix

| Learning Domain | Governing File | Enforced Guardrail |
| :--- | :--- | :--- |
| **Closed-Loop Consultation** | [`docs/ai-workflow-rules.md`](ai-workflow-rules.md) | Ingest source first $\rightarrow$ Grounded query $\rightarrow$ Multi-round review $\rightarrow$ Sync |
| **MV3 Service Worker Keepalive** | [`AGENTS.md`](../AGENTS.md) (Sec. VIII.1) | CDP/Alarm pinging `ensureNativePort()` every 15s prevents 30s worker termination |
| **Native Host Resiliency** | [`AGENTS.md`](../AGENTS.md) (Sec. VIII.2) | Standard library only; dynamic `sys.path`; multi-tier socket fallback |
| **ADR-011 Interactive Lock** | [`AGENTS.md`](../AGENTS.md) (Sec. II) | Two-tier lifecycle; `SESSION_UNLOCKED` gating; single-notebook containment |
| **Google RPC Wire Protocol** | [`AGENTS.md`](../AGENTS.md) (Sec. III-VI) | Scotty 3-step; full jitter backoff; UTF-16 Unicode citation normalization |
| **Edge Hardware Bounds** | [`AGENTS.md`](../AGENTS.md) (Sec. VII) | Sequential execution; 1024MB V8 heap ceiling; `UV_THREADPOOL_SIZE=3` |
| **Scotty Wire Invariants** | [`AGENTS.md`](../AGENTS.md) (Sec. IX) | Recursive UUID un-nesting; UUIDv4 regex validation; pre-consultation readiness barrier |
| **Windows Native Framing** | [`AGENTS.md`](../AGENTS.md) (Sec. X) | Binary mode pinning; atomic stderr redirection; 108-char `UNIX_PATH_MAX` ceiling |
| **Consultation Disambiguation**| [`AGENTS.md`](../AGENTS.md) (Sec. XI) | Decouple spec from candidate plan; human title resolution; citation grounding check |
| **MCP Error & Tracing** | [`AGENTS.md`](../AGENTS.md) (Sec. II) | MCP 2026-07-28 error taxonomy; W3C `traceparent` end-to-end; SQLite WAL retry |
| **Future Functional Roadmap** | [`AGENTS.md`](../AGENTS.md) (Sec. XII) | Title-based selection; bidirectional keepalive; note tools; source filtering; progress bars |
| **Adversarial Red-Team Mitigations** | [`AGENTS.md`](../AGENTS.md) (Sec. II, VII, VIII, IX) | M-01 to M-10: session mutex, Scotty IPC lock, 240s MV3 ceiling, tab discard defense, loud canaries, strict grounding, C fd2 redirect, atomic SQLite, bodyUsed check, scoped readiness |
| **Operational Consultation Polish** | [`AGENTS.md`](../AGENTS.md) (Sec. III, XI, XII) | P-01 to P-04: mid-stream error delta, Scotty session cache & query resumption, pre-flight email guard, un-hashed correlation ID |

---

*Authored and verified by Antigravity Systems Architecture Team. Synchronized with repository documentation and ingested into live NotebookLM knowledge base.*
