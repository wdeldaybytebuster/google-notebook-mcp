### Google Gemini Notebook MCP Server (gemini-notebook-mcp)

#### Overview
The Google Gemini Notebook MCP Server is a high-performance, local-first Model Context Protocol (MCP) gateway that securely bridges autonomous AI coding agents (including Claude Code, Cursor, Cline, Windsurf, and Antigravity) with private Google Gemini Notebook (formerly NotebookLM) knowledge bases. Existing community solutions force developers to manually extract raw browser session cookies via Chrome Developer Tools—a brittle, high-friction workflow that breaks every 2 to 4 weeks and is actively defeated by modern browser defenses such as App-Bound Encryption (ABE) and Device Bound Session Credentials (DBSC). This server eliminates manual cookie extraction entirely by deploying an out-of-process, browser-resident execution broker via a Manifest V3 Chrome Extension. The extension delegates requests to the browser's native network stack, natively preserving hardware TPM cryptographic proofs without exporting sensitive credentials to external clients or files.

#### Goals
1. **Zero-Friction Authentication**: Replace manual Chrome DevTools cookie copying with a browser-resident execution broker that leverages the user's active, authenticated browser session automatically.
2. **Cryptographic Credential Containment**: Enforce strict zero-export invariants ensuring that raw Google session cookies (`SID`, `HSID`, `SSID`, `__Secure-1PSID`, `SAPISID`) and CSRF tokens (`SNlM0e`) are never written to disk, exposed over sockets, or passed into LLM context windows.
3. **Resilient Hardware Binding**: Maintain seamless compatibility with Chromium App-Bound Encryption (Windows Chrome 127+, macOS Chrome 130+) and Device Bound Session Credentials (DBSC) by utilizing in-browser `fetch()` execution.
4. **Context-Optimized Closed Tool Surface & ADR-011 Isolation**: Enforce a consolidated 9-tool closed JSON schema surface (`select_notebook`, `list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`, `create_note`, `list_notes`, `delete_note`) with mandatory single-notebook session locking to eliminate cross-notebook prompt injection and LLM hallucinations.
5. **Deterministic Idempotency & Ingestion Safety**: Provide mathematically verified exactly-once mutation semantics and asynchronous source indexing tracking via a local SQLite mutation journal with HMAC-SHA256 request keys and ambiguity freeze.
6. **Robust Edge Execution & Hardware Governance**: Guarantee stable host execution on resource-constrained development nodes (Chromebook Intel Core i3-N305, 6.4 GB RAM, zero swap) via CPU core pinning (`taskset -c 0-5`), memory capping (`NODE_OPTIONS="--max-old-space-size=1024"`), and thread pool bounds (`UV_THREADPOOL_SIZE=3`).

#### Core User Flow
0. **Zero-Friction Onboarding**: The operator runs `python3 install_and_onboard.py` (or `gemini-notebook-mcp onboard`). The autonomous orchestrator automatically selects a compatible Chromium browser (bypassing ChromeOS Garcon and setting Sommelier Wayland flags), registers Native Messaging manifests across global and profile scopes, starts the Policy Broker daemon, injects the companion extension via CDP (handling Chrome 137+ blocks), polls for Google Sign-In completion via `window.WIZ_global_data`, and seeds `allowlist.json` and `.notebook_mcp.json` from live `wXbhsf` discovery.
1. **Daemon Initialization**: The developer or onboarding orchestrator launches the local MCP broker daemon (`python3 -m mcp_gateway.cli serve`), which initializes the SQLite mutation journal (`journal.db`), applies user version migrations atomically (`PRAGMA user_version < 2` via M-08), and binds an authenticated local IPC transport (Unix domain socket on Linux/macOS or Named Pipe on Windows).
2. **Native Messaging Registration**: The setup utility registers the dedicated native host manifest (`com.mcp.gemini.broker.json`) pointing to `native_host.py` across supported browsers (Google Chrome, Chrome Beta, Chromium, Brave, Microsoft Edge), with environment variables baked directly into the wrapper. The native host performs early C-level file descriptor 2 redirection to eliminate framing corruption (M-07).
3. **Browser Pairing**: The user opens Google Gemini Notebook (`notebook.google.com`) in Chrome with the unpacked Manifest V3 extension loaded. The extension establishes a native messaging port with the background broker, sustained by 15-second bidirectional `PING`/`PONG` keepalive frames.
4. **IDE Agent Connection**: The AI coding assistant (e.g., Claude Code, Cursor, Windsurf, Antigravity) connects to the client facade (`python3 -m mcp_gateway.cli mcp`) over stdio JSON-RPC 2.0. The facade exposes the 9 closed MCP tools in `DISCOVERY_ONLY` state.
5. **Session Locking & Conversational Double-Check (ADR-011 & ADR-017)**: The agent calls `list_notebooks`, which inspects `.notebook_mcp.json` in the active project working directory. If configured, the response includes `project_config` and an actionable `user_prompt` instructing the AI to double-check with the user (*"For this project, we have notebook '<title>' configured. Would you like to use this notebook, or select another from the list?"*). Once the user confirms, the agent calls `select_notebook(notebook_id=... or title=..., save_for_project=true)`, which resolves the target notebook under an exclusive session mutex (`_session_mutex`, M-01), verifies the target against the allowlist (`allowlist.json`), saves `.notebook_mcp.json` for future chats, generates an HMAC session token, and transitions the session to `ACTIVE_DISPATCH`. Subsequent tool invocations are strictly locked to this notebook.
6. **Grounded Research Query**: The agent calls `query_notebook(question, request_key, source_ids=...)`. The broker validates the session lock, verifies pre-query readiness scoped strictly to targeted sources (M-10), journals the request state, and forwards the operation over local IPC to the native host.
7. **Browser-Native In-Page Execution**: The native host relays 32-bit length-prefixed frames to the extension service worker. The worker delegates execution to `page-main.js` running in the MAIN world of the active `notebook.google.com` tab, asserting account identity (`oM1Kwf`, P-03) and executing `fetch()` with `credentials: "include"`.
8. **Stream Normalization & Citation Delivery**: The browser streams gRPC-web frames from `GenerateFreeFormStreamed`. The broker parses text chunks, translates V8 UTF-16 code units into Python Unicode code points, validates non-empty citation grounding spans (M-06), and delivers structured responses to the agent. If transport drops mid-payload, an explicit `STREAM_SEVERED` error delta is emitted immediately (P-01).

#### Features

##### Authentication & Session Strategy
* **Browser-Resident Execution Broker**: Eliminates disk scraping and headless browser overhead by executing requests inside the user's running browser via Manifest V3.
* **TPM / DBSC Preservation**: Retains hardware-bound session keys and native cookie rotation without credential leakage.
* **Project-Level Notebook Binding (`.notebook_mcp.json`) & In-Chat Confirmation (ADR-017)**: Automatically persists project notebook preferences in the project root. On every chat start, `list_notebooks` and `SESSION_UNLOCKED` direct the AI assistant to double-check with the user rather than silently guessing.
* **ADR-011 Single-Notebook Session Lock**: Enforces a strict two-phase state machine (`DISCOVERY_ONLY` -> `ACTIVE_DISPATCH`). Any notebook query or ingestion attempted before `select_notebook` fails with `SESSION_UNLOCKED`. Post-lock operations validate and overwrite `notebook_id` from the locked session, preventing session hopping (`SESSION_LOCKED`).
* **Session TOCTOU Mutex (M-01)**: Serializes title resolution (`wXbhsf`) and session locking via `_session_mutex` to prevent concurrent race windows.
* **Cold-Start Tab Provisioning**: Automatically provisions an inactive, pinned background tab to `notebook.google.com` if no active tab is open, awaiting DOM hydration and `WIZ_global_data.SNlM0e` extraction before recycling after a 60-second cooldown. Managed tabs have `autoDiscardable: false` set proactively with reactive tab discard recovery (`TAB_DISCARDED`, M-04).
* **Multi-Account Route Isolation (P-03)**: Dynamically extracts `/u/{N}/` account prefixes, sets `authuser` query parameters on batchexecute URLs, and verifies `window.WIZ_global_data.oM1Kwf` against the expected account email before executing mutating RPCs.

##### Protocol & Transport Engine
* **Universal Local IPC Transport**: Cross-platform IPC abstraction supporting Unix Domain Sockets with restrictive permissions (`0o700` parent / `0o600` socket) and Windows Named Pipes (`\\.\pipe\notebooklm-mcp-broker`) with Win32 DACL restrictions and 108-character `UNIX_PATH_MAX` path validation (ADR-009).
* **Multi-Browser Registry Support**: Installer supports 6 browser profiles across Chrome, Chrome Beta, Chromium, Brave, and Edge on Linux, macOS, and Windows.
* **Process-Isolated Native Messaging Bridge**: Dedicated binary host decouples Chrome's 32-bit native-byte-order length-prefixed standard I/O from MCP's newline-delimited JSON-RPC stdio. Features early boot C-level file descriptor 2 redirection (`os.dup2(log_file.fileno(), 2)`, M-07) and Windows binary stdio mode.
* **Dual Endpoint Routing**: Segregates metadata and note management (`POST /_/LabsTailwindUi/data/batchexecute`) from natural language chat (`POST /_/LabsTailwindUi/data/.../GenerateFreeFormStreamed`).
* **Boundary-Agnostic Anti-XSSI Stream Parser**: Strips `)]}'\n` prefixes and reassembles fragmented TCP frames and `wrb.fr` / `e` error records across arbitrary network chunks. Emits structured `STREAM_SEVERED` error deltas on transport drop (P-01).
* **UTF-16 Citation Coordinate Normalizer (ADR-004)**: Accurately maps Google V8 UTF-16 code unit offsets to Python Unicode character offsets, eliminating off-by-one errors on astral plane characters (emojis, math symbols).

##### Source Ingestion & Resumable Upload Pipeline
* **Unified Source Ingestion (`izAoDd`)**: Handles web URLs, pasted text, YouTube links, and Drive documents via position-sensitive nested arrays.
* **Scotty 3-Step Resumable Upload Pipeline**: Executes file source intent registration (`o4cbdc`), session initiation (`POST /upload/_/`), and byte streaming to `x-goog-upload-url` for local documents (PDF, DOCX, Markdown) in $\le 512\text{ KiB}$ slices under companion IPC mutex serialization (`_companion_ipc_mutex`, M-02).
* **Scotty Resumability & Caching (P-02)**: Active upload session URLs are cached in `chrome.storage.session`. Interrupted uploads resume from server offset queried via `X-Goog-Upload-Command: query`.
* **Asynchronous Readiness Polling Engine**: Polls `rLM1Ne` source status enums using Full Jitter Exponential Backoff (base delay 2.0s, max 30.0s, timeout 240s) to confirm indexing completion (`READY = 2`). Pre-query readiness verification is scoped exclusively to targeted sources (M-10).
* **Direct Streaming File Ingestion**: Ingests document content via direct Base64 encoding or local documents through Scotty resumable upload streaming with offset recovery.

##### Note Operations & Schema Integrity
* **First-Class Note Management**: Exposes `create_note` (via `CYK0Xb`), `list_notes` (extracting row `[0][17]` from `rLM1Ne`), and `delete_note` (via `tGMBJ`) tools under ADR-011 session lock.
* **Loud Upstream Schema Canaries (M-05)**: If `rLM1Ne` row shape deviates from expected array structures, `list_notes` returns a loud non-retryable `UPSTREAM_SCHEMA_DRIFT` error envelope rather than masking drift as an empty list.
* **Strict Grounding Barrier (M-06)**: Model responses with zero citations fail closed with `UNGROUNDED_RESPONSE`.

##### Security Governance & Edge Hardening
* **Mandatory Notebook Allowlist**: Enforces strict allowlist checking (`~/.config/notebooklm-mcp-bridge/allowlist.json`), preventing prompt-injection enumeration attacks.
* **Deterministic Mutation Journal (ADR-005, M-08)**: Tracks mutations across `prepared` -> `sent` -> `confirmed` / `rejected` / `unknown` using HMAC-SHA256 request digests, refusing blind retries on ambiguous timeouts. Schema upgrades guarded by `PRAGMA user_version < 2` with `BEGIN IMMEDIATE TRANSACTION`.
* **Un-Hashed Correlation ID Propagation (P-04)**: Preserves client `request_key` / `idempotency_key` as un-hashed `_meta.mcp_correlation_id` across all log records, internal dispatch contexts, and output error envelopes alongside W3C `traceparent` headers.
* **Edge Workstation Governance (ADR-008)**: Adheres to strict hardware constraints (`taskset -c 0-5`, `UV_THREADPOOL_SIZE=3`, `ulimit -n 65536`, `NODE_OPTIONS="--max-old-space-size=1024"`, 320 MB safety reserve, zero swap) to prevent out-of-memory container termination.

#### Scope

##### In Scope
* Bridge for consumer Google Gemini Notebook (`notebook.google.com`) and historical (`notebooklm.google.com`).
* Standard Model Context Protocol (MCP) clients: Claude Code, Cursor, Cline, Windsurf, Antigravity IDE.
* 9 closed core tools: `select_notebook`, `list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`, `create_note`, `list_notes`, `delete_note`.
* Chrome Manifest V3 companion extension paired via Chrome Native Messaging across Chrome, Chrome Beta, Chromium, Brave, and Edge.
* Local SQLite mutation journal and allowlist policy engine.
* Operating systems: Linux (Debian/Ubuntu/Arch/ChromeOS Crostini), macOS (Darwin), Windows (via native named pipe).

##### Out of Scope
* Direct scraping or reading of on-disk SQLite cookie databases (`Cookies` file).
* Public OAuth 2.0 consumer workflows (conclusively rejected by Google Cloud scope architecture).
* Official Enterprise Discovery Engine REST chat integration (chat endpoints are absent from official Google REST API).
* Arbitrary DOM automation, visual UI scraping, or third-party CAPTCHA solving bypasses.
* Storing raw Google account passwords, 2FA seeds, or master tokens.

#### Success Criteria
1. **Zero DevTools Friction**: An operator with zero technical knowledge completes setup once in under 2 minutes and never manually inspects network requests or copies cookies.
2. **Cryptographic Grounding**: All queries return grounded answers with verified source citation spans mapped to legitimate source IDs. Zero-citation responses are rejected (`UNGROUNDED_RESPONSE`).
3. **100% Token Containment**: Audited packet logs and MCP stdio traces prove zero instances of `SID`, `HSID`, `SSID`, `__Secure-1PSID`, `SAPISID`, or `SNlM0e` leaking to the IDE agent.
4. **Resilient Mutation State**: Terminating the network or browser mid-upload results in an `unknown` journal state and active reconciliation via `rLM1Ne` without creating duplicate sources.
5. **Host Stability**: The server runs continuously under constrained developer workstations without triggering `earlyoom` process termination or memory exhaustion.
