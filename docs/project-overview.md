### Google Gemini Notebook MCP Server (gemini-notebook-mcp)

#### Overview
The Google Gemini Notebook MCP Server is a high-performance, local-first Model Context Protocol (MCP) gateway that securely bridges autonomous AI coding agents (including Claude Code, Cursor, Cline, and Windsurf) with private Google Gemini Notebook (formerly NotebookLM) knowledge bases. Existing community solutions force developers to manually extract raw browser session cookies via Chrome Developer Tools—a brittle, high-friction workflow that breaks every 2 to 4 weeks and is actively defeated by modern browser defenses such as App-Bound Encryption (ABE) and Device Bound Session Credentials (DBSC). This server eliminates manual cookie extraction entirely by deploying an out-of-process, browser-resident execution broker via a Manifest V3 Chrome Extension. The extension delegates requests to the browser's native network stack, natively preserving hardware TPM cryptographic proofs without exporting sensitive credentials to external clients or files.

#### Goals
1. **Zero-Friction Authentication**: Replace manual Chrome DevTools cookie copying with a browser-resident execution broker that leverages the user's active, authenticated browser session automatically.
2. **Cryptographic Credential Containment**: Enforce strict zero-export invariants ensuring that raw Google session cookies (SID, HSID, SSID, __Secure-1PSID, SAPISID) and CSRF tokens (SNlM0e) are never written to disk, exposed over sockets, or passed into LLM context windows.
3. **Resilient Hardware Binding**: Maintain seamless compatibility with Chromium App-Bound Encryption (Windows Chrome 127+, macOS Chrome 130+) and Device Bound Session Credentials (DBSC) by utilizing in-browser fetch execution.
4. **Context-Optimized Tool Surface**: Enforce a consolidated 5-tool closed JSON schema surface (list_notebooks, get_notebook_metadata, list_sources, query_notebook, add_source) to eliminate LLM context window bloat and tool-selection hallucinations.
5. **Deterministic Idempotency & Ingestion Safety**: Provide mathematically verified exactly-once mutation semantics and asynchronous source indexing tracking via a local SQLite mutation journal with HMAC-SHA256 request keys.

#### Core User Flow
1. **Daemon Initialization**: The developer launches the local MCP broker daemon (`python3 broker.py serve`), which initializes the SQLite mutation journal and binds an authenticated Unix domain socket (or Windows named pipe).
2. **Native Messaging Registration**: The one-time setup utility registers the dedicated native host manifest (`com.mcp.gemini.broker.json`) pointing to `native_host.py` in Chrome's native messaging directory with the extension's explicit ID in `allowed_origins`.
3. **Browser Pairing**: The user opens Google Gemini Notebook (`notebook.google.com`) in Chrome with the unpacked Manifest V3 extension loaded. In the extension popup, the user clicks "Connect this Browser", completing a pairing handshake that stores a local capability token in the OS keystore (zero Google cookies stored).
4. **IDE Agent Connection**: The AI coding assistant (e.g., Claude Code, Cursor) spawns the client facade (`python3 broker.py mcp`) over standard input/output (stdio JSON-RPC 2.0). The facade discovers the 5 consolidated MCP tools.
5. **Grounded Research Query**: The agent calls `query_notebook(notebook_id, question, request_key)`. The broker checks the mandatory allowlist (`allowlist.json`), journals the request state, and forwards the operation over local IPC to the native host.
6. **Browser-Native In-Page Execution**: The native host relays 32-bit length-prefixed frames to the extension service worker. The worker delegates execution to `page-main.js` running in the MAIN world of the active `notebook.google.com` tab, which executes `fetch()` with `credentials: "include"`.
7. **Stream Normalization & Citation Delivery**: The browser streams gRPC-web frames from `GenerateFreeFormStreamed`. The broker parses text chunks, translates V8 UTF-16 code units into Python Unicode code points, validates citation spans against source metadata, and delivers structured, grounded responses to the agent.

#### Features

##### Authentication & Session Strategy
* **Browser-Resident Execution Broker**: Eliminates disk scraping and headless browser overhead by executing requests inside the user's running browser via Manifest V3.
* **TPM / DBSC Preservation**: Retains hardware-bound session keys and native cookie rotation without credential leakage.
* **Cold-Start Tab Provisioning**: Automatically provisions an inactive, pinned background tab to `notebook.google.com` if no active tab is open, awaiting DOM hydration and `WIZ_global_data.SNlM0e` extraction before recycling after a 60-second cooldown.
* **Multi-Account Route Isolation**: Dynamically extracts `/u/{N}/` account prefixes, sets `authuser` query parameters on batchexecute URLs, and verifies `oM1Kwf` account email to prevent silent cross-profile fallback to account 0.

##### Protocol & Transport Engine
* **Process-Isolated Native Messaging Bridge**: Dedicated binary host decouples Chrome's 32-bit native-byte-order length-prefixed standard I/O from MCP's newline-delimited JSON-RPC stdio.
* **Dual Endpoint Routing**: Segregates metadata management (`POST /_/LabsTailwindUi/data/batchexecute`) from natural language chat (`POST /_/LabsTailwindUi/data/.../GenerateFreeFormStreamed`).
* **Boundary-Agnostic Anti-XSSI Stream Parser**: Strips `)]}'\n` prefixes and reassembles fragmented TCP frames and `wrb.fr` / `e` error records across arbitrary network chunks.
* **UTF-16 Citation Coordinate Normalizer**: Accurately maps Google V8 UTF-16 code unit offsets to Python Unicode character offsets, eliminating off-by-one errors on astral plane characters (emojis, math symbols).

##### Source Ingestion & Resumable Upload Pipeline
* **Unified Source Ingestion (`izAoDd`)**: Handles web URLs, pasted text, and YouTube links via position-sensitive nested arrays.
* **Scotty 3-Step Resumable Upload Pipeline**: Executes file source intent registration (`o4cbdc`), session initiation (`POST /upload/_/`), and byte streaming to `x-goog-upload-url` for local documents (PDF, DOCX, Markdown).
* **Asynchronous Readiness Polling Engine**: Polls `rLM1Ne` source status enums using Full Jitter Exponential Backoff (base delay 2.0s, max 30.0s, timeout 300s) to confirm indexing completion (`READY = 2`).
* **Upload Staging Service**: Grants single-use opaque `upload_id` tokens to prevent LLM agents from injecting arbitrary host filesystem paths.

##### Security Governance & Edge Hardening
* **Mandatory Notebook Allowlist**: Enforces strict allowlist checking (`~/.config/notebooklm-mcp-bridge/allowlist.json`), preventing prompt-injection enumeration attacks.
* **Deterministic Mutation Journal**: Tracks mutations across `prepared` -> `sent` -> `confirmed` / `rejected` / `unknown` using HMAC-SHA256 request digests, refusing blind retries on ambiguous timeouts.
* **Edge Workstation Governance**: Adheres to strict hardware constraints (`UV_THREADPOOL_SIZE=3`, `ulimit -n 65536`, `NODE_OPTIONS="--max-old-space-size=1024"`, zero swap) to prevent out-of-memory container termination.

#### Scope

##### In Scope
* Bridge for consumer Google Gemini Notebook (`notebook.google.com`) and historical (`notebooklm.google.com`).
* Standard Model Context Protocol (MCP) clients: Claude Code, Cursor, Cline, Windsurf.
* 5 consolidated core tools: `list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`.
* Chrome Manifest V3 companion extension paired via Chrome Native Messaging.
* Local SQLite mutation journal, allowlist policy engine, and OS keyring pairing token storage.
* Operating systems: Linux (Debian/Ubuntu/Arch/ChromeOS Crostini), macOS (Darwin), Windows (via named pipe adapter).

##### Out of Scope
* Direct scraping or reading of on-disk SQLite cookie databases (`Cookies` file).
* Public OAuth 2.0 consumer workflows (conclusively rejected by Google Cloud scope architecture).
* Official Enterprise Discovery Engine REST chat integration (chat endpoints are absent from official Google REST API).
* Arbitrary DOM automation, visual UI scraping, or third-party CAPTCHA solving bypasses.
* Storing raw Google account passwords, 2FA seeds, or master tokens.

#### Success Criteria
1. **Zero DevTools Friction**: An operator with zero technical knowledge completes setup once in under 2 minutes and never manually inspects network requests or copies cookies.
2. **Cryptographic Grounding**: All queries return grounded answers with verified source citation spans mapped to legitimate source IDs.
3. **100% Token Containment**: Audited packet logs and MCP stdio traces prove zero instances of `SID`, `HSID`, `SSID`, `__Secure-1PSID`, `SAPISID`, or `SNlM0e` leaking to the IDE agent.
4. **Resilient Mutation State**: Terminating the network or browser mid-upload results in an `unknown` journal state and active reconciliation via `rLM1Ne` without creating duplicate sources.
5. **Host Stability**: The server runs continuously under constrained developer workstations without triggering `earlyoom` process termination or memory exhaustion.
