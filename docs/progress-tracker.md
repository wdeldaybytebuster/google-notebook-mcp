### Progress Tracker
Update this file after every meaningful implementation change.

#### Current Phase
* **Convergence & Verification Complete** (100% Complete)

#### Current Goal
* Project fully verified and ready for production deployment with AI coding agents (Claude Code, Cursor, Windsurf).

#### Completed
* **Architectural Blueprint Consensus**: Synthesized and reconciled technical specifications into a definitive 4-pillar production blueprint.
* **Evidentiary Protocol Audit**: Classified all RPC IDs and endpoints into 5 evidence tiers; eradicated unverified folklore (`VfAZjd`, `hizoJc` as listing, `ozz5Z` as add source).
* **Wire Protocol Engine (FEAT-002)**: Complete implementations for `BatchexecuteStreamDecoder`, `GenerateFreeFormStreamParser`, coordinate conversions (`utf16_to_unicode_offset`), RPC payload builders, and full jitter exponential backoff readiness poller.
* **Native Messaging Host (FEAT-003)**: Standalone binary handling 32-bit native-byte-order framing over `sys.stdin.buffer` / `sys.stdout.buffer`, relaying to broker via big-endian length-prefixed Unix domain socket (`0o600`), and 512 KiB chunking.
* **Manifest V3 Browser Companion (FEAT-004)**: Complete unpacked extension in `src/extension/` with strict permissions (`["nativeMessaging", "scripting", "tabs", "alarms", "storage"]`), cold-start background tab provisioning, MAIN-world injection (`page-main.js`), CSRF (`SNlM0e`) and session (`FdrFJe`) validation, email verification against `WIZ_global_data.oM1Kwf`, and zero-leakage `window.postMessage` boundary. Valid PNG icon assets generated.
* **Mutation Journal & SQLite Storage (FEAT-006)**: Complete WAL-mode transactional storage (`~/.config/notebooklm-mcp-bridge/journal.db`) with state machine (`prepared` -> `sent` -> `confirmed` / `rejected` / `unknown`), deterministic HMAC-SHA256 idempotency request keys, and conservative reconciliation (no auto-replay on ambiguous timeouts).
* **Broker Daemon & 5-Tool MCP Surface (FEAT-005)**: Standardized MCP stdio JSON-RPC 2.0 facade with exactly 5 closed JSON Schemas (`additionalProperties: false`): `list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`. Strict allowlist checking (`allowlist.json`), secret scrubber redacting cookies/tokens from all diagnostics, and standardized failure envelopes (`FailureEnvelope`).
* **Cross-Platform Native Host Setup Utility**: Developed `src/mcp_gateway/host/installer.py` supporting Linux, macOS, and Windows with secure permissions (`0o600`) and registry registration, verified by unit tests in `tests/test_installer.py`.
* **Security Canaries & Invariant Regression Suite**: Implemented `tests/test_security_canaries.py` asserting zero leakage of synthetic cookies and tokens, strict allowlist enforcement before IPC dispatch, closed schema fuzzing rejection (`additionalProperties: false`), and disk keystore credential containment.
* **Mutation Reconciliation Suite**: Implemented `tests/test_journal_reconciliation.py` proving state freeze on timeout (`unknown`), blind auto-replay prevention (`REQUEST_KEY_CONFLICT`), and active reconciliation flows.
* **Coordinate Normalizer Edge Case Suite**: Implemented `tests/test_coordinate_edge_cases.py` verifying multi-codepoint emojis, blackboard bold math symbols, ZWJ sequences, flag sequences, inverted ranges, and document length overflows.
* **Hermetic End-to-End Mock Integration Suite**: Built `tests/test_e2e_mock.py` simulating full browser companion loop over Unix domain socket with mock `batchexecute` and `GenerateFreeFormStreamed` gRPC-web streams, testing all 5 MCP tools end-to-end.
* **Unified CLI Entrypoint & Console Script**: Implemented `src/mcp_gateway/cli.py` exposing `mcp`, `serve`, `install`, `launch`, and `allowlist` subcommands with POSIX resource limits (`ulimit -n 65536`, `UV_THREADPOOL_SIZE=3`) and registered `gemini-notebook-mcp`, `gemini-notebook-mcp-launcher`, and `gemini-notebook-mcp-allowlist` scripts in `pyproject.toml`. Verified by unit tests in `tests/test_cli.py`.
* **Dedicated Browser Launcher (Phase 1 Zero-Friction Onboarding)**: Built `src/mcp_gateway/launcher.py` managing dedicated Chrome instances with automated extension injection (`--load-extension` and `--user-data-dir`), CDP session detection, non-blocking auth prompt, and child broker supervisor. Fully covered in `tests/test_launcher.py`.
* **Interactive Allowlist Seed Wizard (Phase 2 User-In-The-Loop Authorization)**: Implemented `src/mcp_gateway/allowlist_wizard.py` querying visible notebooks via broker IPC, presenting an interactive numbered selector in the terminal, and atomically saving user selections to `~/.config/notebooklm-mcp-bridge/allowlist.json`. Fully covered in `tests/test_launcher.py`.
* **Phase 4 Consolidated 5-Tool MCP Surface & Facade**: Implemented standard MCP stdio JSON-RPC 2.0 facade with exactly 5 closed JSON Schemas (`additionalProperties: false`). Enforced pagination for `list_notebooks` and `list_sources`, extracted normalized source records and readiness states directly from `rLM1Ne` row `[102]`, and implemented standard failure envelopes (`{ "ok": false, "error": { "code", "message", "retryable" } }`).
* **Phase 5 Scotty Resumable Uploads & Readiness Polling**: Finalized file ingestion via Scotty 3-step upload protocol (`o4cbdc` intent registration -> `/upload/_/` session creation with `PROJECT_ID`, `SOURCE_NAME`, `SOURCE_ID` -> finalized byte streaming). Implemented Full Jitter Exponential Backoff state machine for `wait_until_ready=true` polling `rLM1Ne` row `[102]` until `READY` (2) or `FAILED`/`ERROR` (3).
* **Harmonized IPC Socket Path**: Standardized default Unix domain socket path to `/tmp/notebooklm-mcp-broker.sock` (`0o600`) across `native_host.py` and `broker.py` with `MCP_BROKER_SOCKET` environment variable override.
* **Multi-Client Drop-In Configurations & Documentation**: Generated ready-to-copy client configuration snippets for Antigravity IDE, Antigravity CLI (`agy`), Claude Code, Cursor, and Windsurf in `config/clients/` alongside a comprehensive setup guide in `docs/client-configuration.md`.
* **Full Test Suite & Strict Typing Convergence**: 85 unit and integration tests passing (`pytest -v tests/`). Strict type checking clean (`mypy --strict src/ tests/` - 37 source files with zero errors).

#### In Progress
* None (All implementation and test convergence milestones completed).

#### Next Up
1. **Zero-Friction Launch**: Run `gemini-notebook-mcp launch` to open the dedicated Chrome window with the extension auto-loaded.
2. **User-In-The-Loop Allowlist Seeding**: Run `gemini-notebook-mcp allowlist seed` to interactively select which notebooks the AI coding agent is permitted to view.
3. **Agent Configuration**: Add `gemini-notebook` MCP server using the drop-in configs in `config/clients/` or `docs/client-configuration.md`.

#### Open Questions & Resolved Mitigations
1. **Google Drive Native Ingestion Wire Format**: Resolved via fail-closed validation and clear error messaging on incomplete parameters.
2. **Numeric Source Readiness Index Variance**: Resolved via multi-index defensive scan across indices 3, 4, 5 of `rLM1Ne` row metadata before falling back to `UNKNOWN`.

#### Architecture Decisions
* **ADR-001 (Browser-Resident Broker over Disk Cookie Extraction)**: Direct on-disk SQLite cookie reads fail on modern Chrome due to App-Bound Encryption and Device Bound Session Credentials. Executing in-browser via Manifest V3 natively satisfies TPM cryptographic challenges and preserves session renewal without exporting credentials.
* **ADR-002 (Decoupled Process IPC Topology)**: Chrome Native Messaging requires 32-bit binary length-prefixed stdin/stdout, colliding with MCP's newline-delimited JSON-RPC stdio. The architecture strictly decouples them into two separate processes communicating over an authenticated local Unix domain socket.
* **ADR-003 (5-Tool Closed Surface)**: Exposing 50+ granular tools saturates LLM context windows and triggers hallucinations. Collapsing server capabilities into 5 closed tools prevents context degradation and ensures deterministic agent execution.
* **ADR-004 (UTF-16 Code Unit Coordinate Translation)**: Google's V8 engine calculates citation coordinates in UTF-16 code units. Direct Python string slicing causes off-by-one errors on astral characters (emojis). Normalizing offsets at the broker level ensures memory-safe, perfectly aligned citations.
* **ADR-005 (Conservative Mutation Journaling)**: Upstream private Google endpoints lack server-side idempotency. Dispatched mutations must never be automatically retried upon timeout; the broker marks ambiguous requests `unknown` and executes active `rLM1Ne` metadata inspection before returning an error.

#### Session Notes
* Operating environment: ChromeOS Crostini / Debian 12 development node.
* Enforced runtime caps: `UV_THREADPOOL_SIZE=3`, `NODE_OPTIONS="--max-old-space-size=1024"`, `ulimit -n 65536`, zero swap allocated.
* Test status: 62/62 passing (`pytest -v tests/`). Type check: `mypy --strict src/ tests/` clean (33 files).

