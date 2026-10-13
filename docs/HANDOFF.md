# Google Gemini Notebook MCP — Full Project Handoff Document

**Last Updated:** October 12, 2026  
**Purpose:** Complete handoff reference for resuming this project in any AI coding tool or with any model. Contains exact file locations, what is done, what is in progress, what is pending, and exact next steps.

---

## 1. What This Project Is (Plain English)

A local software bridge that lets AI coding assistants (Claude Code, Cursor, Windsurf) talk to Google Gemini Notebook (notebook.google.com) without ever copying cookies or passwords. It works by running a tiny Chrome extension inside your browser that makes requests on your behalf, so your Google login stays safe inside Chrome and is never exposed anywhere.

---

## 2. Workspace Location

**All project files live here:**
```
/home/williamdeldaymarketing/Projects/Google Notebook MCP/
```

---

## 3. Active Build Workflow (Running Right Now)

**Workflow ID:** `wf_c3c35207317909c9`  
**Status as of last check:** RUNNING  

If you return to Kiro, run this to check progress:
> "Check the workflow wf_c3c35207317909c9 and tell me what's done"

If you switch to a different tool (Claude Code, Cursor, etc.), ignore the workflow — the files on disk are the truth. See Section 6 for what to tell the new tool.

---

## 4. Complete File & Folder Map

### Already Created & Verified ✅

```
/home/williamdeldaymarketing/Projects/Google Notebook MCP/
│
├── pyproject.toml                          ✅ Project config, dependencies, mypy settings
├── README.md                               ✅ Project readme
├── uv.lock                                 ✅ Dependency lockfile
│
├── config/
│   ├── allowlist.json                      ✅ Template: {"version":1,"notebooks":[],"provider":"browser","accounts":{}}
│   ├── native_host_linux.json              ✅ Chrome native messaging manifest for Linux
│   ├── native_host_macos.json              ✅ Chrome native messaging manifest for macOS
│   └── native_host_windows.json            ✅ Chrome native messaging manifest for Windows
│
├── src/
│   ├── mcp_gateway/                        ✅ Main Python package
│   │   ├── __init__.py                     ✅ Package init, version = "0.1.0"
│   │   ├── py.typed                        ✅ PEP 561 marker for mypy
│   │   ├── cli.py                          ✅ Unified CLI entrypoint (mcp, serve, install)
│   │   │
│   │   ├── engine/                         ✅ FULLY COMPLETE (FEAT-002)
│   │   │   ├── __init__.py                 ✅ Exports all engine symbols
│   │   │   ├── stream_decoder.py           ✅ BatchexecuteStreamDecoder, GenerateFreeFormStreamParser
│   │   │   ├── coordinate.py               ✅ utf16_to_unicode_offset, utf16_slice, CitationSpan, normalize_citation
│   │   │   ├── rpc_templates.py            ✅ All 7 RPC payload builders + batchexecute envelope builder
│   │   │   └── readiness_poller.py         ✅ SourceStatus IntEnum, poll_until_ready (Full Jitter Backoff)
│   │   │
│   │   ├── host/                           ✅ FULLY COMPLETE (FEAT-003)
│   │   │   ├── __init__.py                 ✅ Clean exports
│   │   │   ├── native_host.py              ✅ Chrome 32-bit native-endian ↔ broker big-endian IPC, 512KiB chunking
│   │   │   └── installer.py                ✅ Cross-platform native messaging manifest installer
│   │   │
│   │   ├── broker/                         ✅ FULLY COMPLETE (FEAT-005)
│   │   │   ├── __init__.py                 ✅ Clean exports
│   │   │   ├── broker.py                   ✅ BrokerDaemon, McpFacade, stdio JSON-RPC facade
│   │   │   ├── allowlist.py                ✅ AllowlistConfig manager, atomic write, policy check
│   │   │   └── secret_scrubber.py          ✅ Regex redaction engine for cookies and tokens
│   │   │
│   │   ├── schemas/                        ✅ FULLY COMPLETE (FEAT-005)
│   │   │   ├── __init__.py                 ✅ Clean exports
│   │   │   ├── tools.py                    ✅ 5 closed JSON Schemas & validate_tool_args
│   │   │   └── error.py                    ✅ Standardized FailureEnvelope & REQUEST_KEY_CONFLICT
│   │   │
│   │   └── storage/                        ✅ FULLY COMPLETE (FEAT-006)
│   │       ├── __init__.py                 ✅ Clean exports
│   │       ├── schema.sql                  ✅ WAL mode, foreign-key schema
│   │       └── journal.py                  ✅ MutationJournal state machine & active reconcile()
│   │
│   └── extension/                          ✅ FULLY COMPLETE (FEAT-004)
│       ├── manifest.json                   ✅ Strict MV3 permissions, no cookies perm
│       ├── service_worker.js               ✅ Cold-start pinned tab, keep-alive alarms
│       ├── content_script.js               ✅ Relays background/MAIN world postMessage
│       ├── page-main.js                    ✅ MAIN-world fetch(), CSRF/oM1Kwf verification
│       ├── popup.html                      ✅ 360x480 dark UI
│       ├── popup.js                        ✅ Popup controller and connection test
│       ├── popup.css                       ✅ Design tokens applied
│       └── icons/                          ✅ Valid binary PNG icons (16, 48, 128)
│
├── tests/
│   ├── __init__.py                         ✅
│   ├── fixtures/
│   │   └── golden_wire_captures.json       ✅ Synthetic test vectors (no real credentials)
│   ├── test_cli.py                         ✅ 6 CLI parsing & dispatch tests — passing
│   ├── test_stream_decoder.py              ✅ 4 tests — all passing
│   ├── test_coordinate.py                  ✅ 5 tests — all passing
│   ├── test_coordinate_edge_cases.py       ✅ 7 tests — all passing
│   ├── test_native_framing.py              ✅ 7 tests — all passing
│   ├── test_journal.py                     ✅ 11 tests — all passing
│   ├── test_journal_reconciliation.py      ✅ 3 tests — all passing
│   ├── test_broker.py                      ✅ 8 tests — all passing
│   ├── test_security_canaries.py           ✅ 5 tests — all passing
│   ├── test_installer.py                   ✅ 5 tests — all passing
│   └── test_e2e_mock.py                    ✅ 1 comprehensive mock flow test — passing
│
├── docs/
│   ├── Full Project Scope and Info Read First.md   ✅ Master spec (read-only)
│   ├── architecture.md                             ✅ System design (read-only)
│   ├── code-standards.md                           ✅ Coding rules (read-only)
│   ├── project-overview.md                         ✅ Product spec (read-only)
│   ├── progress-tracker.md                         ✅ Living status doc (100% complete)
│   ├── client-configuration.md                     ✅ Drop-in configs for all 5 clients
│   ├── ai-workflow-rules.md                        ✅ AI agent rules (read-only)
│   ├── ui-context.md                               ✅ Design tokens (read-only)
│   └── HANDOFF.md                                  ✅ THIS FILE

│
└── .agents/tasks/
    ├── plan.md                             ✅ Full ordered implementation plan
    └── task-google-notebook-mcp/           ✅ Per-feature task files (FEAT-001 through FEAT-006)
```

---

## 5. Build Phase Status

| Phase | Feature | Status | Commit |
|-------|---------|--------|--------|
| 1 — Scaffolding | FEAT-001 | ✅ COMPLETE | root commit (15 files) |
| 2 — Wire Protocol Engine | FEAT-002 | ✅ COMPLETE | a7b9309 |
| 3 — Native Host IPC | FEAT-003 | ✅ COMPLETE | feat: FEAT-003 |
| 4 — Manifest V3 Extension | FEAT-004 | ✅ COMPLETE | feat: FEAT-004 |
| 5 — Broker Daemon + 5 Tools | FEAT-005 | ✅ COMPLETE | feat: FEAT-005 |
| 6 — Mutation Journal + Storage | FEAT-006 | ✅ COMPLETE | feat: FEAT-006 |
| — | Hermetic Test Convergence | ✅ COMPLETE | 56/56 tests passing, mypy strict clean (31 files) |
| — | Living Documentation Updates | ✅ COMPLETE | docs updated |

---

## 6. Exact State of Each Completed File

### `src/mcp_gateway/engine/stream_decoder.py`
- `BatchexecuteStreamDecoder` class — stateful, handles anti-XSSI `)]}'\n` stripping, incremental TCP buffer reassembly, `wrb.fr` data frame extraction, `e`/`google.rpc.Status` error frame extraction
- `GenerateFreeFormStreamParser` — line-oriented citation/text-delta classifier for streaming query responses
- `StreamDecodeError` exception class
- `WrbFrame` frozen dataclass: `rpc_id: str`, `payload: Any`, `is_error: bool`, `error_code: int | None`
- Fully typed, mypy --strict clean

### `src/mcp_gateway/engine/coordinate.py`
- `utf16_to_unicode_offset(text: str, utf16_offset: int) -> int`
- `utf16_slice(text: str, start: int, end: int) -> str`
- `CitationSpan` dataclass
- `normalize_citation(...)` — applies UTF-16→Unicode translation to citation coordinates from Google's V8 engine
- Handles all edge cases: negative offsets, offset beyond text length, astral plane characters (emoji, math symbols)

### `src/mcp_gateway/engine/rpc_templates.py`
Implements `BatchexecuteRequest` dataclass and payload builders for all 7 verified RPC IDs:
- `build_list_notebooks_payload()` → `wXbhsf` payload `[None, 1, None, [58]]`
- `build_get_notebook_payload(notebook_id)` → `rLM1Ne` payload + source-path URL param
- `build_add_url_payload(url, notebook_id)` → `izAoDd` URL variant
- `build_add_text_payload(title, content)` → `izAoDd` text variant
- `build_add_drive_payload(doc_id, mime_type, title, notebook_id)` → `izAoDd` Drive variant (fail-closed)
- `build_register_upload_payload(filename, notebook_id)` → `o4cbdc`
- `build_delete_source_payload(source_id)` → `tGMBJ`
- `build_get_conversation_id_payload(notebook_id)` → `hPTbtc`
- `build_get_turns_payload(conversation_id)` → `khqZz`
- `make_query_params(source_ids, question, history, notebook_id, message_uuid, chat_session_id)` → `GenerateFreeFormStreamed` params (triple-nested source IDs)
- `build_batchexecute_body(rpc_id, payload, csrf_token)` → URL-encoded form body string

### `src/mcp_gateway/engine/readiness_poller.py`
- `SourceStatus` IntEnum: `UNKNOWN=-1, PROCESSING=1, READY=2, ERROR=3, PREPARING=5`
- `parse_source_status(row)` — defensively scans indices 3, 4, 5 for int values
- `poll_until_ready(notebook_id, source_id, timeout_seconds=300.0)` async — Full Jitter Exponential Backoff, base 2.0s, max 30.0s
- Raises `TimeoutError` at 300s; raises `SourceIndexingError` if status=ERROR

### `src/mcp_gateway/host/native_host.py`
- `CHROME_FRAME_FORMAT = "@I"` (native-byte-order — correct for Chrome Native Messaging)
- `IPC_FRAME_FORMAT = ">I"` (big-endian — correct for broker IPC)
- These are kept strictly separate — never mixed
- `read_native_message()` / `write_native_message()` — sync, native-endian, stdin.buffer/stdout.buffer
- `read_ipc_message()` / `write_ipc_message()` — async, big-endian, Unix socket
- `chunk_message(payload)` — splits payloads >512 KiB into base64 frames with `final=True` marker
- Connects to `/tmp/notebooklm-mcp-broker.sock`
- All diagnostic output to stderr only

### `tests/fixtures/golden_wire_captures.json`
Synthetic test vectors — NO real credentials anywhere:
- Normal `wXbhsf` response with `)]}'\n` prefix
- Chunked response split mid-frame across two TCP reads
- Error frame with application error code 132 (PERMISSION_DENIED)
- Astral-plane Unicode notebook title with emoji (🎉)
- Surrogate pair divergence test: `"Hello 😀 World"` — UTF-16 offset 8 → Unicode offset 7

---

## 7. Implementation Deliverables (All Completed)

### FEAT-004 — Manifest V3 Chrome Extension (COMPLETE ✅)
Files verified: `src/extension/` (all files complete, JS syntax valid, icons generated)
- `manifest.json`: permissions ONLY `["nativeMessaging", "scripting", "tabs", "alarms", "storage"]` — NO cookie permissions.
- `service_worker.js`: keep-alive alarms every 25s, cold-start pinned tab provisioning with 60s auto-teardown, MAIN-world injection.
- `page-main.js`: extracts SNlM0e (CSRF), FdrFJe (f.sid), authuser from page; verifies oM1Kwf email; executes fetch() with credentials:include; NEVER puts cookies/tokens in postMessage payloads.
- `popup.html/css/js`: 360×480px dark UI, design tokens from ui-context.md, connection status test.

### FEAT-005 — Broker Daemon + 5-Tool MCP Surface (COMPLETE ✅)
Files verified:
- `src/mcp_gateway/broker/broker.py` — main daemon: Unix socket IPC server (`0o600`) + MCP stdio facade (`McpFacade`).
- `src/mcp_gateway/broker/allowlist.py` — AllowlistConfig manager with atomic writes and deny-by-default policy.
- `src/mcp_gateway/broker/secret_scrubber.py` — removes cookies/tokens/auth headers from logs and payloads.
- `src/mcp_gateway/schemas/tools.py` — exactly 5 closed JSON schemas (additionalProperties: false).
- `src/mcp_gateway/schemas/error.py` — standardized FailureEnvelope & typed ErrorDetail helpers.

### FEAT-006 — Mutation Journal + Storage (COMPLETE ✅)
Files verified:
- `src/mcp_gateway/storage/schema.sql` — SQLite schema (mutation_journal + mutation_events tables) in WAL mode.
- `src/mcp_gateway/storage/journal.py` — MutationJournal class: prepared→sent→confirmed/rejected/unknown state machine with deterministic HMAC-SHA256 request_key generation.
- `tests/test_journal.py` — 11 state machine, idempotency, and SQL injection unit tests passing.

---

## 8. Verified Technical Parameters (For Any AI Tool)

These are all CODE-VERIFIED — do not change them:

**RPC IDs (batchexecute):**
- List notebooks: `wXbhsf`
- Get notebook + sources: `rLM1Ne`
- Add source (URL/text/Drive/YouTube): `izAoDd`
- Register file upload: `o4cbdc`
- Delete source: `tGMBJ`
- Get conversation ID: `hPTbtc`
- Get conversation turns: `khqZz`

**Endpoints:**
- batchexecute: `POST https://notebook.google.com/_/LabsTailwindUi/data/batchexecute`
- Streaming query: `POST https://notebook.google.com/_/LabsTailwindUi/data/google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/GenerateFreeFormStreamed`
- Scotty upload start: `POST https://notebook.google.com/upload/_/`

**Source readiness enums (rLM1Ne row[39] index 4):**
- `UNKNOWN = -1`, `PROCESSING = 1`, `READY = 2`, `ERROR = 3`, `PREPARING = 5`

**Framing:**
- Chrome Native Messaging: 32-bit **native-byte-order** (`struct.pack('@I', ...)`)
- Broker IPC socket: 32-bit **big-endian** (`struct.pack('>I', ...)`)

**Security invariants (NEVER break these):**
1. Cookies (SID, HSID, SSID, __Secure-1PSID, SAPISID), ya29 tokens, and SNlM0e NEVER leave the browser or appear in logs/IPC frames
2. Chrome Native Messaging framing and MCP JSON-RPC stdio are in SEPARATE processes
3. Exactly 5 MCP tools — no more, no fewer
4. Mutations that reach `sent` state are NEVER auto-replayed — mark `unknown` on timeout
5. All citation coordinates: translate UTF-16 → Python Unicode before returning
6. `UV_THREADPOOL_SIZE=3` set on broker startup
7. Unix socket permissions: `0o600`, bound to `/tmp/notebooklm-mcp-broker.sock`

---

## 9. How to Resume in a Different AI Tool

If you need to continue this in Claude Code, Cursor, Windsurf, or any other AI coding assistant, give it this exact message:

---

**PASTE THIS INTO THE NEW AI TOOL:**

```
You are continuing an in-progress implementation of the Google Gemini Notebook MCP server.

ALL specification files are in:
/home/williamdeldaymarketing/Projects/Google Notebook MCP/docs/

Read ALL of these first before doing anything:
1. docs/Full Project Scope and Info Read First.md  (master spec)
2. docs/architecture.md
3. docs/code-standards.md
4. docs/project-overview.md
5. docs/progress-tracker.md
6. docs/ai-workflow-rules.md
7. docs/ui-context.md
8. docs/HANDOFF.md  ← THIS FILE — tells you exactly what's done and what's left

The workspace root is:
/home/williamdeldaymarketing/Projects/Google Notebook MCP/

What is COMPLETE & VERIFIED (do not rewrite):
- src/mcp_gateway/engine/stream_decoder.py  ✅
- src/mcp_gateway/engine/coordinate.py       ✅
- src/mcp_gateway/engine/rpc_templates.py    ✅
- src/mcp_gateway/engine/readiness_poller.py ✅
- src/mcp_gateway/host/native_host.py        ✅
- src/mcp_gateway/host/installer.py          ✅
- src/extension/ (all files + icons)         ✅
- src/mcp_gateway/broker/broker.py          ✅
- src/mcp_gateway/broker/allowlist.py       ✅
- src/mcp_gateway/broker/secret_scrubber.py ✅
- src/mcp_gateway/schemas/tools.py          ✅
- src/mcp_gateway/schemas/error.py          ✅
- src/mcp_gateway/storage/schema.sql        ✅
- src/mcp_gateway/storage/journal.py        ✅
- src/mcp_gateway/cli.py                    ✅
- tests/ (62 tests across 11 test suites)   ✅ (all 62 passing)
- mypy --strict src/ tests/                 ✅ (zero errors across 33 source files)

Project status: 100% COMPLETE & VERIFIED.
Automated End-to-End Test Convergence Achieved.
Ready for deployment and agent onboarding.

To verify in this repo:
- Run: cd "/home/williamdeldaymarketing/Projects/Google Notebook MCP" && .venv/bin/pytest -v tests/
- Run: .venv/bin/mypy --strict src/ tests/

```

---

## 10. Quick Verification Commands

Run these from the workspace root to confirm current state:

```bash
# Check what's installed
cd "/home/williamdeldaymarketing/Projects/Google Notebook MCP"

# Run all passing tests
python -m pytest tests/ -x --tb=short

# Check type safety on completed files
python -m mypy --strict src/mcp_gateway/engine/ src/mcp_gateway/host/

# Check git commit history
git log --oneline

# See full file tree
find src/ tests/ config/ -type f | sort
```

---

## 11. Architecture Decisions Already Made (Do Not Revisit)

- **ADR-001**: Browser-resident execution via Manifest V3 extension — NOT on-disk cookie reading (breaks on Chrome 127+ due to App-Bound Encryption)
- **ADR-002**: Two separate processes — Native Messaging host (binary framing) and MCP broker (JSON-RPC) — they communicate over a Unix socket. NEVER combine them.
- **ADR-003**: Exactly 5 tools — more causes LLM hallucinations and context window bloat
- **ADR-004**: UTF-16 offset translation — Google's V8 engine uses UTF-16 code units, Python uses Unicode code points. They diverge on emoji/math symbols.
- **ADR-005**: Conservative mutation journaling — `unknown` state for ambiguous timeouts, never auto-replay

---

## 12. Design Token Quick Reference (For Extension UI)

```css
--bg-base: #0B0F19
--bg-surface: #111827
--bg-elevated: #1F2937
--text-primary: #F9FAFB
--text-muted: #9CA3AF
--accent-primary: #3B82F6
--accent-hover: #2563EB
--border-default: #374151
--state-success: #10B981
--state-warning: #F59E0B
--state-error: #EF4444
```

Extension popup: 360×480px. Fonts: Inter (UI), JetBrains Mono (IDs/data). Icons: Lucide (stroke 1.75px).

---

*This document was generated on October 12, 2026. If the workflow `wf_c3c35207317909c9` is still running when you read this, check its status first — more files may have been completed since this was written.*
