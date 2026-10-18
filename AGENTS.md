<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Google Notebook MCP** (451 symbols, 608 relationships, 10 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/Google Notebook MCP/context` | Codebase overview, check index freshness |
| `gitnexus://repo/Google Notebook MCP/clusters` | All functional areas |
| `gitnexus://repo/Google Notebook MCP/processes` | All execution flows |
| `gitnexus://repo/Google Notebook MCP/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

# Google Gemini Notebook MCP Gateway — Project Directives & Architectural Invariants

## I. Security Guardrails & Credential Containment
1. **Zero Credential Export (DBSC / TPM Runtime Containment):**
   - Google session tokens (`SID`, `HSID`, `SSID`, `ya29.*`, `SNlM0e`) MUST NEVER leave Chrome's native memory or cross IPC boundaries into agent logs, environment variables, or databases.
   - All outbound data crossing IPC boundaries must pass through `secret_scrubber.py`.
   - Never attempt direct external HTTP client impersonation of Google authentication outside the dedicated Chrome extension bridge.
2. **No Raw Shell Scripts:**
   - All automated processes, builds, and test runs must execute via controlled Python subprocesses or `node-pty`, never unmonitored raw shell scripts (`.sh`).
3. **Protect Transpiled Assets:**
   - Never edit transpiled build artifacts or generated files directly. Edit original TypeScript, JavaScript, and Python source files only.
4. **No Silent Code Stripping:**
   - Refactorings must preserve all existing security canaries, HMAC-SHA256 request hashing, mutation journaling, coordinate normalization, and native host bridge logic.

## II. Closed Tool Surface & ADR-011 Interactive Session Lock
1. **Tool Surface Specification:** The MCP stdio facade (`broker.py mcp` / `gemini-notebook-mcp mcp`) strictly exposes nine closed tools:
   - `select_notebook`: Enforces ADR-011 single-notebook session lock (`notebook_id` or `title` required). Supports optional `save_for_project: bool = True` to persist selection in `.notebook_mcp.json` in project root. Serialized via `_session_mutex` (M-01). Generates HMAC session token, transitioning from `DISCOVERY_ONLY` to `ACTIVE_DISPATCH`.
   - `list_notebooks`: Decodes allowlisted notebooks via `wXbhsf` RPC records. Supports `page_size` and `cursor`. Once locked, filters results to the active notebook. Surfaces `project_config` from `.notebook_mcp.json` and actionable `user_prompt` directing the AI assistant to double-check notebook selection with the user at the start of each chat.
   - `get_notebook_metadata`: Fetches full metadata via `rLM1Ne` RPC. Parameter `notebook_id` is automatically overwritten with the locked session notebook ID.
   - `list_sources`: Extracts source records and readiness states directly from `rLM1Ne` row `[102]`. Supports `page_size` and `cursor`.
   - `query_notebook`: Streams grounded Q&A via `GenerateFreeFormStreamed` with normalized Unicode citation offsets. Requires `question` and `request_key`. Supports optional `source_ids` for targeted querying (M-10). Enforces non-empty citation grounding barrier (M-06) and emits explicit error deltas on transport severance (P-01). Preserves un-hashed `_meta.mcp_correlation_id` (P-04).
   - `add_source`: Ingests content via polymorphic payloads (`izAoDd` for text/url/youtube/drive; Scotty for files). Requires `idempotency_key` and `source`. Enforces pre-flight account email guard (P-03), Full Jitter Exponential Backoff polling, and Scotty session URL caching with query resumption (P-02).
   - `create_note`: Creates user note via `CYK0Xb` RPC. Requires `title`, `content`, `idempotency_key`. Journaled via SQLite FSM. Enforces pre-flight email guard (P-03).
   - `list_notes`: Extracts user notes from `rLM1Ne` row `[0][17]`. Enforces loud failure canary (`UPSTREAM_SCHEMA_DRIFT`) on array schema anomalies (M-05). Supports `page_size` and `cursor`.
   - `delete_note`: Deletes user note via `tGMBJ` RPC. Requires `note_id`, `idempotency_key`. Journaled via SQLite FSM. Enforces pre-flight email guard (P-03).
2. **Closed Schema Invariant:**
   - All tool schemas strictly enforce `additionalProperties: false` (JSON Schema) and `extra="forbid"` (Pydantic v2).
   - Any unrecognized parameter must immediately return an `INVALID_ARGUMENT` error envelope.
3. **ADR-011 Session Gating:**
   - Calling notebook operations before `select_notebook` returns `SESSION_UNLOCKED`.
   - Calling `select_notebook` with a different notebook after session lock returns `SESSION_LOCKED`.
4. **Standard Failure Envelope Contract:**
   - All errors across tools and IPC must conform to:
     ```json
     {
       "ok": false,
       "error": {
         "code": "ALLOWLIST_DENIED | AUTH_REQUIRED | MUTATION_UNKNOWN | INVALID_ARGUMENT | SESSION_UNLOCKED | SESSION_LOCKED | INTERNAL | NOT_FOUND | STREAM_SEVERED | UPSTREAM_SCHEMA_DRIFT",
         "message": "Descriptive message",
         "retryable": false
       },
       "_meta": {
         "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
         "mcp_correlation_id": "client-supplied-request-key-001"
       }
     }
     ```

## III. Scotty 3-Step Resumable Upload Protocol
Binary file ingestion via `add_source` (`source.type == "file"`) must follow the verified 3-step sequence:
1. **Intent Registration:** Call `o4cbdc` RPC payload `[[[filename]], notebook_id, [58]]` to acquire the server-assigned `sourceId`.
2. **Session Creation:** Execute in-browser MV3 fetch to `/upload/_/LabsTailwindUi/...` with headers `X-Goog-Upload-Command: start`, `X-Goog-Upload-Protocol: resumable`, and JSON payload `{ PROJECT_ID: notebook_id, SOURCE_NAME: filename, SOURCE_ID: sourceId }`. Extract session URL from `x-goog-upload-url` and cache in `chrome.storage.session` keyed by `{notebook_id}:{source_id}` (P-02).
3. **Finalize Byte Stream:** Stream raw file bytes directly to the session URL in $\le 512\text{ KiB}$ slices (M-02) with headers `X-Goog-Upload-Command: upload, finalize` and `X-Goog-Upload-Offset: offset`. On reconnect, query session offset via `X-Goog-Upload-Command: query` to resume transmission without full replay (P-02).

## IV. Full Jitter Exponential Backoff Readiness Polling
When `add_source` is invoked with `wait_until_ready=true`:
1. The engine polls `rLM1Ne` and inspects row `[102]`, index `4` readiness enum (`PROCESSING = 1`, `READY = 2`, `ERROR / FAILED = 3`).
2. Sleep intervals use Full Jitter Backoff:
   `delay = random.uniform(0, min(base_delay * 2**attempt, max_delay))`
3. State transitions:
   - `READY (2)` -> Confirms mutation in journal, returns success.
   - `ERROR / FAILED (3)` -> Marks mutation `REJECTED`, returns `INTERNAL` error envelope.
   - Timeout / Disconnect -> Marks mutation `UNKNOWN` (`MUTATION_UNKNOWN`), freezing automatic replay.

## V. Mutation Journaling & Unknown State Freeze
1. Every write mutation (`add_source`, `create_note`, `delete_note`, `query_notebook`) follows:
   `PREPARED -> SENT -> CONFIRMED | REJECTED`
2. **Freeze on Ambiguity:** If a mutation disconnects or times out during transmission or readiness polling, it transitions to `UNKNOWN`. Automatic replay of `UNKNOWN` or `SENT` records is strictly blocked until resolved via human or deterministic active reconciliation.
3. **Atomic Schema Migrations (M-08):** Database schema updates are guarded by `PRAGMA user_version < 2` inside `PRAGMA foreign_keys = OFF; BEGIN IMMEDIATE TRANSACTION; ... PRAGMA user_version = 2; COMMIT; PRAGMA foreign_keys = ON;` with `busy_timeout=30000`.

## VI. UTF-16 to Unicode Citation Normalization
1. Backend streaming citations return offsets indexed by JavaScript UTF-16 code units.
2. The gateway must normalize these to Unicode character spans (`start_char`, `end_char`) against the full decoded text to eliminate drift caused by astral plane characters (emojis, math symbols).

## VII. Hardware & Host Execution Bounds (Lenovo Chromebook Edge Profile)
1. **Memory & Concurrency:**
   - Prefix Node/npm invocations with `NODE_OPTIONS="--max-old-space-size=1024"`.
   - Set `UV_THREADPOOL_SIZE=3` in environment variables.
   - Restrict execution to CPU cores 0–5 (`taskset -c 0-5`), reserving cores 6–7 for ChromeOS.
   - Cap test runner concurrency (`--maxWorkers=4`).
   - Run background build and test commands sequentially to prevent `earlyoom` eviction.
2. **Browser Native Bridge:**
   - Chrome automation must point directly to `/usr/bin/google-chrome-beta` to bypass Garcon loopback bridging interference.

## VIII. Browser Companion & Native Messaging Architecture Invariants
1. **MV3 Service Worker Idle Keepalive & 240s Ceiling:**
   - Manifest V3 background service workers idle out after ~30 seconds of inactivity. Continuous 15-second bidirectional `PING`/`PONG` keepalive frames between native host and broker sustain the connection.
   - Synchronous RPC operations are clamped to **240 seconds** (`MAX_RPC_TIMEOUT_MS = 240_000`) (M-03). Streaming queries emit incremental chunks to reset Chrome's 300s execution kill wall.
   - Background tabs have `autoDiscardable: false` set proactively (M-04). A reactive `chrome.tabs.onUpdated` listener drains promises immediately with retryable `TAB_DISCARDED` on memory eviction.
2. **Native Host `sys.path` Bootstrap & Standalone Execution:**
   - `native_host.py` is invoked directly by Chrome via `/usr/bin/python3` without the virtualenv or project directory in `sys.path`. It MUST dynamically insert its source root (`sys.path.insert(0, _src_root)`) and rely solely on Python standard library modules with zero third-party dependencies.
   - Early boot C-level OS descriptor redirection (`os.dup2(log_file.fileno(), 2)`) prevents diagnostic prints from contaminating stdout framing (M-07).
   - Chrome subprocesses do not inherit terminal environment variables. The host must fallback gracefully between `$XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock`, `~/.config/notebooklm-mcp-bridge/broker.sock`, and `/tmp/notebooklm-mcp-broker.sock`.
3. **ES Module Global Export:**
   - In MV3 service workers declared as ES modules (`"type": "module"`), top-level functions are module-scoped. Any function needed by external automation (such as `ensureNativePort`) must be explicitly assigned to `globalThis` (`globalThis.ensureNativePort = ensureNativePort`).

## IX. Scotty Wire Invariants & Recursive UUID Un-Nesting
1. **Source ID Un-nesting:** `o4cbdc` returns source IDs wrapped in multi-layered arrays (e.g. `[[['uuid']], 'filename', ...]`). Implementations MUST recursively unpack nested lists (`while isinstance(cur, list) and cur: cur = cur[0]`) and validate using regex `^[0-9a-fA-F-]{36}$`. Passing bracketed strings (e.g. `"['uuid']"`) to Scotty upload headers is strictly prohibited.
2. **Pre-Consultation Readiness Barrier:** An uploaded source must never be presumed ready for Q&A immediately upon HTTP 200 completion. Readiness polling must confirm `READY (2)` in `rLM1Ne` row `[102]`, index 4 before issuing queries. Scoped readiness checking isolates verification strictly to targeted `source_ids` (M-10).

## X. Windows Platform Native Framing & Path Constraints
1. **Binary Stdin/Stdout Streams:** On `win32`, standard input and output streams must be pinned to binary mode (`msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)`) to prevent `\r\n` line ending translation from corrupting Native Messaging length headers (M-07).
2. **Atomic Stderr Redirection:** Stderr must be redirected to log files or `nul` at earliest startup (`setup_stderr_redirection`) to prevent diagnostic prints from contaminating the Native Messaging stdout wire.
3. **108-Character `UNIX_PATH_MAX` Ceiling:** Windows `AF_UNIX` sockets enforce a strict 108-character buffer in `sockaddr_un`. Path resolution must verify `len(path) <= 108` and fall back to Named Pipes (`\\.\pipe\notebooklm-mcp-broker`) or hashed paths if the limit is exceeded.

## XI. Model Consultation Disambiguation & Grounding Verification
1. **Specification vs Plan Decoupling:** In all consultation prompts, decouple the baseline specification title (`SPEC_SOURCE_TITLE`) from the candidate plan title (`CANDIDATE_PLAN_TITLE`). Never prompt the model to compare a baseline specification against itself.
2. **Notebook Identity Gating:** Resolve target notebooks by their verified human-readable title (`"Google Notebooks MCP"`) and source count before locking sessions, preventing accidental interaction with ephemeral test notebooks.
3. **Grounding Citation Verification (M-06):** Verify that Q&A responses contain non-empty citation offsets (`citations`). A response with zero citations must be treated as ungrounded and rejected (`UNGROUNDED_RESPONSE`).

## XII. Core Mitigations (M-01 to M-10) & Operational Polish (P-01 to P-04)
1. **M-01 (Session TOCTOU Mutex):** `_session_mutex = asyncio.Lock()` wraps title resolution and lock transitions in `BrokerDaemon`.
2. **M-02 (Scotty IPC Mutex):** `_companion_ipc_mutex = asyncio.Lock()` guarantees exclusive socket ownership during $\le 512\text{ KiB}$ chunk transmission.
3. **M-03 (MV3 240s Ceiling):** Clamped RPC timeout to 240s with incremental stream chunking to keep worker event loop alive.
4. **M-04 (Tab Discard Defense):** Pinned tabs set `autoDiscardable: false`; reactive listener immediately drains promises with `TAB_DISCARDED`.
5. **M-05 (Loud Schema Drift Canary):** `list_notes` returns loud `UPSTREAM_SCHEMA_DRIFT` if `rLM1Ne` row shape deviates from expected arrays.
6. **M-06 (Strict Grounding Barrier):** Zero citations in model answer returns `ok: false` with `error.code: "UNGROUNDED_RESPONSE"`.
7. **M-07 (C-Level OS fd 2 Redirection):** `os.dup2(log_file.fileno(), 2)` at early boot and `os.O_BINARY` on Windows stdio.
8. **M-08 (Atomic SQLite WAL Migration):** `PRAGMA user_version < 2` guard with `BEGIN IMMEDIATE TRANSACTION` for safe schema expansion.
9. **M-09 (Safe Fetch Interceptor):** Zero stream consumption (`bodyUsed` check); inspects only string/URLSearchParams bodies.
10. **M-10 (Scoped Pre-Query Readiness):** Readiness verification in `query_notebook` evaluates only targeted `source_ids`, ignoring unhealthy untargeted sources.
11. **P-01 (Mid-Stream Error Delta):** Emits structured `{"type": "error_delta", "error": {"code": "STREAM_SEVERED", "retryable": true}}` on abrupt stream transport severance.
12. **P-02 (Scotty Resumability Caching):** Caches upload session URLs in `chrome.storage.session`; queries offset via `X-Goog-Upload-Command: query` to resume without full replay.
13. **P-03 (Pre-Flight Account Identity Guard):** Asserts `window.WIZ_global_data.oM1Kwf === payload.expectedEmail` before dispatching mutating RPCs (`add_source`, `create_note`, `delete_note`).
14. **P-04 (Correlation ID Propagation):** Preserves client `request_key` / `idempotency_key` as un-hashed `_meta.mcp_correlation_id` across all logs, dispatches, and error envelopes.

## XIII. Feature Roadmap & Extension Invariants
1. **Closed Schema Preservation:** All upcoming MCP tools and enhancements must strictly enforce `extra="forbid"` and `additionalProperties: false`.
2. **Delivered v4.2 Invariants:**
   - `select_notebook`: Title matching with ambiguity validation (delivered).
   - `query_notebook`: Targeted source filtering via `source_ids: list[str]` (delivered).
   - Note Operations: `create_note`, `list_notes`, `delete_note` tools using `CYK0Xb` and `tGMBJ` (delivered).
   - Scotty Resumability: Session caching and query offset resumption (delivered).
   - Error Deltas: Immediate `STREAM_SEVERED` signaling on mid-stream severance (delivered).
   - Project Binding & In-Chat Confirmation: Project-level `.notebook_mcp.json` persistence and conversational double-check handshake (delivered).
   - Zero-Friction Onboarding Orchestrator: Autonomous 6-stage state machine (`install_and_onboard.py`, `gemini-notebook-mcp onboard`) with RFC 6455 stdlib WebSocket, Crostini/Wayland guards, and dual-scope manifest registration (delivered).
3. **Future Extension Capabilities:**
   - Progress Notifications: Emit MCP `notifications/progress` during long-running Scotty byte uploads and readiness polling cycles.
   - UI Integration: Visual badges reflecting ADR-011 lock state in browser extension popup.

## XIV. Project-Level Notebook Binding & In-Chat Confirmation Protocol
1. **Project Directory Persistence (`.notebook_mcp.json`):**
   - Each project working directory can persist its associated Google Notebook in `.notebook_mcp.json` (`notebook_id`, `title`, `updated_at`).
   - Calling `select_notebook` with `save_for_project=true` (the default) writes or updates this configuration automatically.
2. **Conversational Double-Check Handshake:**
   - When `list_notebooks` is called, the gateway inspects `.notebook_mcp.json` in `Path.cwd()` and returns `project_config` alongside an actionable `user_prompt`.
   - The AI assistant MUST double-check with the user at the start of each chat session:
     *"For this project, we have notebook '<title>' configured. Would you like to use this notebook for this chat, or choose another from the list?"*
   - The AI assistant MUST NOT auto-select or silently assume a notebook target without explicit user confirmation.
3. **Guiding `SESSION_UNLOCKED` Defense:**
   - If an operation is attempted before `select_notebook`, the `SESSION_UNLOCKED` error explicitly prompts the AI to consult the user with the configured project default and available notebooks list.
