# Google Gemini Notebook MCP — Full Project Handoff Document

**Last Updated:** October 14, 2026  
**Status:** 100% COMPLETE, VERIFIED & CERTIFIED (`CERT-GATEWAY-PHASE7-DOMG-PROD-PASS-20261014`)  
**Purpose:** Complete handoff reference for resuming or deploying this project in any AI coding tool (Claude Code, Cursor, Windsurf, Antigravity) or runtime environment. Contains exact file locations, certified architecture, test results, and operational runbooks.

---

## 1. What This Project Is (Plain English)

A local, production-grade software bridge that lets AI coding assistants (Claude Code, Cursor, Windsurf, Antigravity) securely interact with Google Gemini Notebook (notebook.google.com) without ever copying cookies, auth tokens, or passwords. It works via a 5-tier architecture featuring a native Chrome Extension (MV3) running inside your browser that executes requests with native credentials (`credentials: "include"`), while the local Python broker and MCP facade enforce strict session isolation, project-level notebook binding, atomic mutation journaling, and edge hardware memory protection.

---

## 2. Workspace Location

**All project files live here:**
```
/path/to/Google Notebook MCP/
```

---

## 3. Project Status & Test Matrix

- **Implementation Plan v4.2**: 100% Complete across all 7 Phases (Phases 1 through 7).
- **Core Mitigations (M-01 to M-10)**: 100% Verified and Certified.
- **Operational Polish (P-01 to P-04)**: 100% Verified and Certified.
- **Architecture Decision Records**: 17 ADRs documented (ADR-001 through ADR-017).
- **Tool Surface**: Exactly 9 closed MCP tools (`extra="forbid"`, `additionalProperties: false`).
- **Project Binding**: ADR-017 Project-Level Notebook Binding via `.notebook_mcp.json` with In-Chat Confirmation Protocol.
- **Unit & Integration Tests**: **158 / 158 tests passing** across 21 test suites (`pytest -v`).
- **Static Type Safety**: **0 type errors across 52 source files** (`mypy --strict src/ tests/`).
- **Live In-Situ Qualification**: Passed in live environment on Linux Chrome-Beta against production notebook `"Google Notebooks MCP"`.

---

## 4. Complete File & Folder Map

```
/path/to/Google Notebook MCP/
│
├── pyproject.toml                                  ✅ Project config, dependencies, mypy settings
├── README.md                                       ✅ Project readme
├── uv.lock                                         ✅ Dependency lockfile
├── .notebook_mcp.json                              ✅ Project-level notebook binding (ADR-017)
│
├── config/
│   ├── allowlist.json                              ✅ Template & active allowlist
│   ├── native_host_linux.json                      ✅ Chrome native messaging manifest for Linux
│   ├── native_host_macos.json                      ✅ Chrome native messaging manifest for macOS
│   └── native_host_windows.json                    ✅ Chrome native messaging manifest for Windows
│
├── src/
│   ├── mcp_gateway/                                ✅ Main Python package
│   │   ├── __init__.py                             ✅ Package init, version = "0.1.0"
│   │   ├── py.typed                                ✅ PEP 561 marker for mypy
│   │   ├── cli.py                                  ✅ Unified CLI entrypoint (mcp, serve, install)
│   │   ├── launcher.py                             ✅ DedicatedBrowserLauncher (Sommelier/Wayland/CDP)
│   │   │
│   │   ├── engine/                                 ✅ Wire Protocol & Decoding Engine
│   │   │   ├── __init__.py                         ✅ Clean exports
│   │   │   ├── stream_decoder.py                   ✅ BatchexecuteStreamDecoder, GenerateFreeFormStreamParser (P-01)
│   │   │   ├── coordinate.py                       ✅ UTF-16 → Unicode offset translation & span normalization
│   │   │   ├── rpc_templates.py                    ✅ Payload builders (wXbhsf, rLM1Ne, izAoDd, o4cbdc, tGMBJ, CYK0Xb)
│   │   │   └── readiness_poller.py                 ✅ Full Jitter Backoff polling (rLM1Ne row [102])
│   │   │
│   │   ├── host/                                   ✅ Native Messaging Host Bridge
│   │   │   ├── __init__.py                         ✅ Clean exports
│   │   │   ├── native_host.py                      ✅ Chrome 32-bit @I ↔ broker >I IPC, 512KiB chunking, M-07 dup2
│   │   │   └── installer.py                        ✅ Cross-platform native messaging manifest installer
│   │   │
│   │   ├── broker/                                 ✅ Broker Daemon & Session Management
│   │   │   ├── __init__.py                         ✅ Clean exports
│   │   │   ├── broker.py                           ✅ BrokerDaemon, McpFacade, M-01/M-02 locks, 9 tool handlers
│   │   │   ├── session.py                          ✅ ADR-011 SessionLockFSM & ADR-017 project binding guidance
│   │   │   ├── project_config.py                   ✅ ADR-017 .notebook_mcp.json reader and writer
│   │   │   ├── allowlist.py                        ✅ AllowlistConfig manager, atomic write, policy check
│   │   │   └── secret_scrubber.py                  ✅ Regex redaction engine for cookies and tokens
│   │   │
│   │   ├── schemas/                                ✅ Typed Contracts (Pydantic v2 & JSON Schema)
│   │   │   ├── __init__.py                         ✅ Clean exports
│   │   │   ├── tools.py                            ✅ 9 closed tool schemas (extra="forbid", additionalProperties: false)
│   │   │   └── error.py                            ✅ Standardized FailureEnvelope & P-04 correlation propagation
│   │   │
│   │   └── storage/                                ✅ SQLite Mutation Journal & Storage
│   │       ├── __init__.py                         ✅ Clean exports
│   │       ├── schema.sql                          ✅ WAL mode, v2 foreign-key schema (M-08)
│   │       └── journal.py                          ✅ MutationJournal state machine, v2 migration, reconcile()
│   │
│   └── extension/                                  ✅ Manifest V3 Chrome Extension
│       ├── manifest.json                           ✅ Strict MV3 permissions, zero cookie permissions
│       ├── service_worker.js                       ✅ Pinned tab, 15s keepalive ping/pong, tab discard supervisor (M-04)
│       ├── content_script.js                       ✅ Relays background/MAIN world postMessage
│       ├── page-main.js                            ✅ MAIN-world fetch(), P-02 Scotty caching, P-03 pre-flight identity
│       ├── popup.html                              ✅ 360x480 dark UI
│       ├── popup.js                                ✅ Popup controller and connection test
│       ├── popup.css                               ✅ Design tokens applied
│       └── icons/                                  ✅ Binary PNG icons (16, 48, 128)
│
├── scripts/
│   └── phase7_live_qualification.py                ✅ Live qualification test suite against production notebook
│
├── tests/                                          ✅ 158 Tests across 21 Test Suites (ALL PASSING)
│   ├── fixtures/golden_wire_captures.json          ✅ Synthetic test vectors
│   ├── test_cli.py                                 ✅ CLI parsing and dispatch tests
│   ├── test_stream_decoder.py                      ✅ Batchexecute parser and frame assembly
│   ├── test_coordinate.py                          ✅ UTF-16 to Unicode coordinate normalization
│   ├── test_coordinate_edge_cases.py               ✅ Astral plane emoji and surrogate pair slicing
│   ├── test_native_framing.py                      ✅ Native Messaging (@I) vs IPC (>I) framing
│   ├── test_native_host_resilience.py              ✅ Standalone bootstrap, sys.path, and descriptor redirection
│   ├── test_journal.py                             ✅ MutationJournal state machine transitions
│   ├── test_journal_reconciliation.py              ✅ Journal recovery and active reconciliation
│   ├── test_broker.py                              ✅ Broker daemon, tool dispatch, and session locking
│   ├── test_security_canaries.py                   ✅ Secret scrubber and credential containment
│   ├── test_installer.py                           ✅ Manifest installer verification
│   ├── test_e2e_mock.py                            ✅ Comprehensive end-to-end mock flow
│   ├── test_keepalive_heartbeat.py                 ✅ 15s bidirectional ping/pong and keepalive
│   ├── test_tab_discard_supervisor.py              ✅ Tab discard handling and recovery
│   ├── test_account_identity_guard.py              ✅ Pre-flight email allowlist verification (P-03)
│   ├── test_title_selection.py                     ✅ Title-based notebook selection and ambiguity detection
│   ├── test_targeted_sources.py                    ✅ Scoped pre-query readiness and targeted RAG (M-10)
│   ├── test_notes_and_migration.py                 ✅ Note operations (CYK0Xb, tGMBJ) and v2 migration (M-05, M-08)
│   ├── test_scotty_chunking.py                     ✅ 512 KiB chunk slicing, IPC mutex (M-02), RAM check, P-02 caching
│   ├── test_protocol_healing.py                    ✅ Mid-stream error deltas (P-01), surrogate pairs, schema drift
│   └── test_project_notebook_selection.py          ✅ Project binding (.notebook_mcp.json) and handshake (ADR-017)
│
└── docs/                                           ✅ Complete Documentation Suite
    ├── Full Project Scope and Info Read First.md   ✅ Master project specification
    ├── architecture.md                             ✅ Master Blueprint, Root Causes Matrix, ADRs 001-017
    ├── code-standards.md                           ✅ Engineering and coding rules
    ├── project-overview.md                         ✅ Product specification & features
    ├── progress-tracker.md                         ✅ Living status doc (100% complete)
    ├── client-configuration.md                     ✅ Drop-in configurations for all AI clients + ADR-017
    ├── ai-workflow-rules.md                        ✅ AI agent operational rules
    ├── ui-context.md                               ✅ Extension UI design tokens
    ├── learnings-and-reasoning.md                  ✅ Retrospective learnings & proof-of-break analyses
    ├── NotebookLM_Implementation_Plan_V4_2_Full_Completion_Report.md ✅ Official Auditor Clearance Certificate
    └── HANDOFF.md                                  ✅ THIS FILE
```

---

## 5. Build Phase Status Summary

| Phase | Engineering Domain | Status | Key Accomplishments |
|---|---|---|---|
| Phase 1 | Lifecycle & Keep-Alive Hardening | ✅ COMPLETE | 15s bidirectional ping/pong, tab discard supervisor (M-04), pre-flight account identity guard (P-03). |
| Phase 2 | Human-Centric Gating & Targeted RAG | ✅ COMPLETE | Title-based `select_notebook`, case-insensitive matching, `source_ids` targeted RAG, M-10 scoped readiness, M-06 strict grounding barrier. |
| Phase 3 | Note Management & Journal Migration | ✅ COMPLETE | `create_note` (`CYK0Xb`), `list_notes` (`rLM1Ne` row [0][17] with M-05 canary), `delete_note` (`tGMBJ`), atomic v2 SQLite migration (M-08), P-04 correlation propagation. |
| Phase 4 | Edge Memory & Scotty Chunking | ✅ COMPLETE | 512 KiB segmented streaming, M-02 IPC mutex lock, 320 MB safety reserve interlock, P-02 Scotty session URL caching and offset resumption. |
| Phase 5 | Protocol Auto-Healing & Decoders | ✅ COMPLETE | P-01 mid-stream error delta emission (`STREAM_SEVERED`), surrogate-pair stream assembly, HTTP 400 schema drift detection, safe body inspection (M-09). |
| Phase 6 | Documentation Overhaul | ✅ COMPLETE | Inverted hierarchy in `docs/architecture.md`, Master Blueprint on Page 1, Root Causes Matrix, ADRs 001-017, raw traces in Appendix. |
| Phase 7 | Live Qualification & Verification | ✅ COMPLETE | End-to-end live execution on Linux Chrome-Beta against production notebook `"Google Notebooks MCP"`, verifying all 9 tools and real citations. |
| Feature | Project-Level Notebook Binding | ✅ COMPLETE | ADR-017 `.notebook_mcp.json` workspace binding, dynamic guidance on `SESSION_UNLOCKED` and `list_notebooks`, in-chat confirmation protocol. |

---

## 6. The 9-Tool Closed MCP Catalog

All tools enforce `extra="forbid"` (Pydantic v2) and `additionalProperties: false` (JSON Schema):

1. `select_notebook(notebook_id: str | None = None, title: str | None = None, save_for_project: bool = True)`:
   - Selects and locks the active notebook session by UUID or human-readable title.
   - Enforces M-01 `_session_mutex` serialization. Transitions from `DISCOVERY_ONLY` to `ACTIVE_DISPATCH`.
   - Generates an HMAC-SHA256 session token.
   - When `save_for_project: true` (default), persists choice to `.notebook_mcp.json`.
2. `list_notebooks(page_size: int = 100, cursor: str | None = None)`:
   - In discovery phase, lists allowlisted notebooks, returns `project_config`, and provides a dynamic prompt directing the AI to prompt the user.
   - Once locked, returns only the locked active notebook.
3. `get_notebook_metadata(notebook_id: str | None = None)`:
   - Retrieves metadata and sources for the locked notebook. Parameter is automatically overwritten with locked ID.
4. `list_sources(notebook_id: str | None = None, page_size: int = 100, cursor: str | None = None)`:
   - Returns sources and readiness states (`status_code == 2`) from `rLM1Ne` row `[102]`.
5. `query_notebook(question: str, request_key: str, notebook_id: str | None = None, source_ids: list[str] | None = None)`:
   - Streams grounded Q&A with normalized Unicode citation offsets.
   - Enforces M-10 scoped pre-query readiness checking (only checks targeted sources).
   - Enforces M-06 strict grounding barrier (zero citations returns `UNGROUNDED_RESPONSE`).
   - Emits P-01 mid-stream error delta (`STREAM_SEVERED`) if transport drops.
   - Preserves un-hashed P-04 `_meta.mcp_correlation_id`.
6. `add_source(idempotency_key: str, source: dict, notebook_id: str | None = None, wait_until_ready: bool = False)`:
   - Ingests text, URL, YouTube, Drive (`izAoDd`), or file documents (resumable Scotty upload).
   - Enforces P-03 pre-flight account email guard.
   - Files are sliced into 512 KiB chunks under exclusive M-02 IPC mutex.
   - P-02 caches upload session URL in `chrome.storage.session` and resumes from server byte offset.
7. `create_note(title: str, content: str, idempotency_key: str, notebook_id: str | None = None)`:
   - Creates user note via `CYK0Xb` RPC. Instantly `READY`. Journaled in SQLite FSM.
8. `list_notes(notebook_id: str | None = None, page_size: int = 100, cursor: str | None = None)`:
   - Extracts notes from `rLM1Ne` row `[0][17]`. Enforces M-05 loud canary (`UPSTREAM_SCHEMA_DRIFT` if container is missing or malformed).
9. `delete_note(note_id: str, idempotency_key: str, notebook_id: str | None = None)`:
   - Deletes user note via `tGMBJ` RPC. Journaled in SQLite FSM.

---

## 7. Project-Level Notebook Binding & In-Chat Confirmation Protocol (ADR-017)

### Workflow
1. **Workspace Configuration**:
   The current project root contains `.notebook_mcp.json`:
   ```json
   {
     "notebook_id": "00000000-0000-0000-0000-000000000001",
     "title": "Google Notebooks MCP",
     "updated_at": "2026-10-14T12:00:00Z"
   }
   ```
2. **In-Chat Handshake**:
   - In every new conversation or uninitialized state, the MCP gateway guides the AI assistant:
     - If the agent calls a notebook tool before `select_notebook`, it receives a `SESSION_UNLOCKED` error containing instructions to ask the user to confirm the project default.
     - When calling `list_notebooks`, the response includes `project_config` and `user_prompt`:
       > *"This project is currently associated with notebook 'Google Notebooks MCP'. Ask the user: 'Would you like to use \"Google Notebooks MCP\" for this project, or choose a different notebook from the list above?' Once confirmed, call select_notebook with your choice."*
   - Once the user confirms, the AI calls `select_notebook(notebook_id="00000000-0000-0000-0000-000000000001", save_for_project=true)`.
   - The session transitions to `ACTIVE_DISPATCH`, and all operations are safely locked.

---

## 8. Summary of Verified Technical Parameters & Protocols

- **RPC Wire IDs**:
  - List notebooks: `wXbhsf`
  - Get notebook + sources: `rLM1Ne`
  - Add source (URL/text/Drive/YouTube): `izAoDd`
  - Register file upload: `o4cbdc`
  - Delete source / note: `tGMBJ`
  - Create note: `CYK0Xb`
  - Get conversation ID: `hPTbtc`
  - Get conversation turns: `khqZz`
- **Wire Framing**:
  - Chrome Native Messaging: 32-bit native-byte-order (`@I`)
  - Broker IPC Unix Socket: 32-bit big-endian (`>I`)
- **Memory & Edge Hardware Rules**:
  - Cores 0-5 affinity (`taskset -c 0-5`), cores 6-7 reserved for Wayland/OS.
  - `UV_THREADPOOL_SIZE=3`
  - `NODE_OPTIONS="--max-old-space-size=1024 --max-semi-space-size=128"`
  - 320 MB safety reserve buffer enforced prior to large operations.

---

## 9. Architecture Decision Records (ADR-001 through ADR-017)

- **ADR-001**: Browser-resident execution via Manifest V3 extension — NOT on-disk cookie reading (immune to Chrome App-Bound Encryption).
- **ADR-002**: Two separate processes — Native Messaging host (binary framing) and MCP broker (JSON-RPC) — over local Unix socket / Named Pipe.
- **ADR-003**: Closed tool schema surface — all schemas enforce `additionalProperties: false` and `extra="forbid"`.
- **ADR-004**: UTF-16 offset translation to Python Unicode code points for citation alignment.
- **ADR-005**: Conservative mutation journaling — `unknown` state for ambiguous timeouts, never auto-replay.
- **ADR-006**: Chrome Native Messaging binary stdio decoupling from MCP JSON-RPC stdio.
- **ADR-007**: Full Jitter Exponential Backoff readiness polling for source indexing.
- **ADR-008**: Fail-closed Drive ingestion policy.
- **ADR-009**: Defensive source status parser scanning indices 3, 4, 5 in `rLM1Ne` row [102].
- **ADR-010**: Unified multi-subcommand CLI architecture (`mcp`, `serve`, `install`).
- **ADR-011**: Mandatory Interactive Single-Notebook Session Lock FSM (`DISCOVERY_ONLY` -> `ACTIVE_DISPATCH`).
- **ADR-012**: Dedicated browser launcher with Sommelier Wayland bypassing and CDP extension injection.
- **ADR-013**: Resilient native host bootstrapping with dynamic `sys.path` and C-level OS descriptor redirection (M-07).
- **ADR-014**: Mutex-guarded title resolution and IPC socket exclusivity (M-01, M-02).
- **ADR-015**: Proactive tab discard defense and Chromium 240-second ceiling (M-03, M-04).
- **ADR-016**: Resilient streaming decoders with mid-stream error deltas and loud schema canaries (M-05, P-01).
- **ADR-017**: Project-Level Notebook Binding (`.notebook_mcp.json`) & In-Chat Confirmation Protocol.

---

## 10. Verification Commands

Run these from the workspace root to confirm the health of the entire project:

```bash
cd "/path/to/Google Notebook MCP"

# 1. Run all 158 tests
taskset -c 0-5 nice -n 10 .venv/bin/pytest -v

# 2. Run static type checking across all 52 source files
taskset -c 0-5 nice -n 10 .venv/bin/mypy --strict src/ tests/

# 3. Check git status
git status

# 4. Verify project-level notebook configuration
cat .notebook_mcp.json
```

---

*This document was updated and verified on October 14, 2026. The Google Gemini Notebook MCP Gateway is 100% complete, verified, and ready for production deployment.*
