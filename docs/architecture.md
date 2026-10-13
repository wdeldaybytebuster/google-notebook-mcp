### Architecture Context

#### Stack
| Layer | Technology | Role |
| :--- | :--- | :--- |
| **Agent Interface (MCP)** | JSON-RPC 2.0 over stdio (newline-delimited) | Standard Model Context Protocol transport for Claude Code, Cursor, Windsurf |
| **MCP Protocol Facade** | Python 3.11+ / `@modelcontextprotocol/sdk` | Implements protocol lifecycle, tool schema negotiation, and error sanitization |
| **Policy & Session Broker** | Python 3.11+ asyncio singleton daemon (`broker.py`) | Enforces allowlist, mutation journaling, token scrubbing, and concurrency caps |
| **Local Host IPC** | Unix Domain Socket (macOS/Linux) / Named Pipe (Windows) | Bridges broker daemon to native host using 32-bit big-endian framed JSON |
| **Native Messaging Host** | Python 3.11+ standalone binary (`native_host.py`) | Reads/writes 32-bit native-byte-order framed binary messages to Chrome stdin/stdout |
| **Browser Companion** | Chrome Manifest V3 Extension (`service_worker.js`) | Maintains native messaging port, provisions background tabs, and relays commands |
| **In-Page Executor** | Injected JavaScript (`page-main.js`) in MAIN world | Extracts `SNlM0e`/`FdrFJe` and dispatches `fetch()` with native DBSC/cookie context |
| **Mutation Journal** | SQLite 3 (`journal.db` via WAL mode) | Enforces deterministic HMAC-SHA256 request idempotency and transition tracking |
| **Capability Keystore** | Python `keyring` (macOS Keychain, WinLocker, SecretService)| Stores local pairing tokens and capability grants (zero Google session cookies) |
| **Upstream Services** | Google LabsTailwindUi (`batchexecute`, Scotty, gRPC-Web) | Private Google Gemini Notebook endpoints for metadata, uploads, and streaming QA |

#### System Boundaries

* `src/mcp_gateway/broker/` — **Local Policy & Session Broker Daemon**: Owns the MCP stdio facade, mandatory notebook allowlist validation, local IPC server, secret scrubbing, and host concurrency limits (`UV_THREADPOOL_SIZE=3`).
* `src/mcp_gateway/engine/` — **Protocol Parsing & Normalization Engine**: Owns boundary-agnostic batchexecute response decoding, streaming gRPC chunk reassembly, UTF-16 to Unicode coordinate translation, and asynchronous readiness polling.
* `src/mcp_gateway/storage/` — **Mutation Journal & State Persistence**: Owns the SQLite schema (`mutation_journal`, `mutation_events`), atomic state transitions (`prepared` -> `sent` -> `confirmed`/`rejected`/`unknown`), and HMAC-SHA256 request hashing.
* `src/mcp_gateway/schemas/` — **Closed Contract & Wire Templates**: Defines the 5 consolidated tool JSON schemas (`additionalProperties: false`) and position-sensitive Google RPC array templates.
* `src/extension/` — **Manifest V3 Browser Companion**: Owns extension background service worker, cold-start pinned tab provisioning, MAIN-world script injection, in-browser fetch execution, and 512 KiB frame chunking.
* `tests/` — **Verification & Golden Fixtures**: Owns synthetic chunked test vectors, offline anti-XSSI stripping suites, non-ASCII Unicode fixtures, and IPC mock relays.

#### Storage Model

* **Database (SQLite 3 - `~/.config/notebooklm-mcp-bridge/journal.db`)**: Stores the mutation journal (`request_key`, `notebook_id`, `operation_type`, `payload_hash`, `state`, `assigned_source_id`, timestamps) and the append-only `mutation_events` audit table. Enforces atomic transactions and SQLite WAL mode.
* **Local Allowlist Configuration (`~/.config/notebooklm-mcp-bridge/allowlist.json`)**: Stores user-approved notebook UUIDs, active provider mode, and multi-account email mappings. The allowlist starts empty; all access is opt-in.
* **OS Keystore (Platform Vault via Python `keyring`)**: Stores only local pairing tokens and capability keys granting the MCP broker permission to communicate with the browser companion. Google cookies and master tokens are strictly forbidden from vault storage.
* **Upload Staging Buffer (`/tmp/mcp-gemini-uploads/` or tmpfs RAM disk)**: Ephemeral, owner-only directory (`0o700`) holding local files approved by the user for upload. The server issues single-use opaque `upload_id` tokens, preventing arbitrary filesystem exfiltration.

#### Auth and Access Model

* **Authentication Mechanics**: The architecture rejects direct cookie copying and on-disk SQLite decryption due to Chrome 127+/130+ App-Bound Encryption (ABE) and Device Bound Session Credentials (DBSC). Authentication is delegated entirely to the browser's native network stack via `page-main.js` executing in the MAIN world of `notebook.google.com`. In-browser `fetch()` calls automatically attach session cookies, CSRF tokens (`SNlM0e`), and hardware TPM challenge signatures (`Sec-Session-Response`).
* **Ownership & Access Control**: Access is governed by the local policy broker enforcing an explicit allowlist. Even if an agent discovers notebooks via `wXbhsf`, operations are rejected with `PERMISSION_DENIED` unless the notebook ID exists in `allowlist.json`.
* **Multi-Account User Isolation**: When multiple Google accounts are active in Chrome, the bridge extracts `authuser` from `/u/{N}/` URL paths, attaches `authuser={N}` query parameters on batchexecute URLs, includes `x-goog-authuser` on upload sessions, and verifies `window.WIZ_global_data.oM1Kwf` against the expected account email. If the email mismatches, the broker aborts immediately to prevent silent fallback to account 0.

#### Invariants

1. **Zero Credential Export**: Raw Google session cookies (`SID`, `HSID`, `SSID`, `__Secure-1PSID`, `SAPISID`), Google access tokens (`ya29...`), and CSRF tokens (`SNlM0e`) must NEVER cross the local socket or leave the browser sandbox.
2. **Process & Transport Isolation**: Chrome Native Messaging binary standard I/O (32-bit native-endian length-prefixed frames) must NEVER share standard streams with MCP stdio (newline-delimited JSON-RPC). They execute as separate OS processes bridged over local IPC.
3. **Consolidated 5-Tool Surface**: Exactly 5 tools are exposed to the AI agent (`list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`). All schemas enforce `additionalProperties: false` to eliminate hallucination.
4. **Conservative Mutation Safety**: State transitions follow `prepared` -> `sent` -> `confirmed` / `rejected` / `unknown`. Once a mutation reaches `sent`, it must NEVER be automatically replayed on transport timeout; the broker must reconcile state via `rLM1Ne` before surfacing an error.
5. **Coordinate Translation Integrity**: All citation coordinates received from Google's V8 engine must be translated from UTF-16 code units to native Python Unicode offsets before text slicing, ensuring perfect character alignment on astral-plane characters.
6. **Defensive Resource Ceilings**: The runtime must enforce `UV_THREADPOOL_SIZE=3`, `ulimit -n 65536`, `NODE_OPTIONS="--max-old-space-size=1024"`, and strict loopback socket binding (`127.0.0.1`) to ensure stability on resource-constrained development nodes.
