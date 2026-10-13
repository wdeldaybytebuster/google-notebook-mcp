# Implementation Plan — Google Gemini Notebook MCP Gateway

> Workspace root: `/home/williamdeldaymarketing/Projects/Google Notebook MCP`
> All paths below are absolute. Python 3.11+ required. Build: `uv sync` / `uv run pytest tests/ -v` / `uv run mypy --strict src/`.

---

## FEAT-001 — Project Scaffolding

- [x] 1. Create `pyproject.toml` using PEP 621 format.
      Project name `gemini-notebook-mcp`, version `0.1.0`, requires-python `>=3.11`. Runtime deps: `mcp>=1.0.0`, `keyring>=24.0.0`, `aiofiles>=23.0.0`, `httpx>=0.27.0`. Dev deps: `mypy>=1.9.0`, `pytest>=8.0.0`, `pytest-asyncio>=0.23.0`, `ruff>=0.4.0`. `[tool.mypy] strict=true, python_version="3.11"`. `[tool.pytest.ini_options] asyncio_mode="auto"`. Build backend: hatchling. `packages=["src/mcp_gateway"]` in wheel target.
      Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/pyproject.toml`
      Verify: `uv sync` completes without error.

- [x] 2. Create `README.md` with project description, prerequisites, quickstart, 5-tool reference table, security invariants, license placeholder.
      Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/README.md`
      Verify: file exists and renders valid Markdown.

- [x] 3. Create all package `__init__.py` files and directory skeleton.
      Directories to create: `src/`, `src/mcp_gateway/`, `src/mcp_gateway/engine/`, `src/mcp_gateway/broker/`, `src/mcp_gateway/schemas/`, `src/mcp_gateway/storage/`, `src/mcp_gateway/host/`, `tests/`, `tests/fixtures/`. `src/mcp_gateway/__init__.py` exports `__version__ = "0.1.0"`. All others empty.
      Files: `src/__init__.py`, `src/mcp_gateway/__init__.py`, `src/mcp_gateway/engine/__init__.py`, `src/mcp_gateway/broker/__init__.py`, `src/mcp_gateway/schemas/__init__.py`, `src/mcp_gateway/storage/__init__.py`, `src/mcp_gateway/host/__init__.py`, `tests/__init__.py`, `tests/fixtures/__init__.py`
      Verify: `uv run python -c 'import mcp_gateway; print(mcp_gateway.__version__)'` prints `0.1.0`. `uv run mypy --strict src/` reports zero errors.

- [x] 4. Create config template files.
      `config/allowlist.json`: `{"version":1,"provider_mode":"browser","accounts":[],"notebooks":[]}`. Three native host manifests (linux/macos/windows) with `name="com.mcp.gemini.broker"`, `type="stdio"`, placeholder path and extension ID. Windows variant adds registry key comment.
      Files: `config/allowlist.json`, `config/native_host_linux.json`, `config/native_host_macos.json`, `config/native_host_windows.json`
      Verify: `python3 -c 'import json; [json.load(open(f)) for f in ["config/allowlist.json","config/native_host_linux.json","config/native_host_macos.json","config/native_host_windows.json"]]; print("OK")'`

---

## FEAT-002 — Wire Protocol Engine (Phase 1)

- [x] 5. Create `src/mcp_gateway/engine/stream_decoder.py`.
      Class `BatchexecuteStreamDecoder` with `feed(chunk: bytes) -> list[dict]`: buffers bytes, strips `)]}'\n` anti-XSSI prefix on first call (stateful flag), extracts `wrb.fr` records and raises `StreamDecodeError` on `e` error frames. Class `GenerateFreeFormStreamParser` with `feed(chunk: bytes) -> list[dict]`: parses line-delimited JSON chunks, emits `{"type":"text_delta"|"citation"|"done", ...}` dicts. Exception `StreamDecodeError(error_code: int)`. All fully type-annotated. Zero raw response body logging.
      Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/mcp_gateway/engine/stream_decoder.py`
      Verify: `uv run mypy --strict src/mcp_gateway/engine/stream_decoder.py` — zero errors.

- [x] 6. Create `src/mcp_gateway/engine/coordinate.py`.
      Function `utf16_to_unicode_offset(text: str, utf16_offset: int) -> int` — encode as utf-16-le, slice to `utf16_offset*2`, decode, return len(). Function `utf16_slice(text: str, start: int, end: int) -> str` — encode utf-16-le, slice `[start*2:end*2]`, decode `errors='replace'`. Frozen dataclass `CitationSpan(source_id, start_char, end_char, text_snippet)`. Function `normalize_citation(raw: dict, source_text: str) -> CitationSpan` — converts UTF-16 offsets, raises `ValueError` for invalid ranges.
      Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/mcp_gateway/engine/coordinate.py`
      Verify: `uv run mypy --strict src/mcp_gateway/engine/coordinate.py` — zero errors.

- [x] 7. Create `src/mcp_gateway/engine/rpc_templates.py`.
      Frozen dataclass `BatchexecuteRequest(rpc_id, params_json, notebook_id, authuser)` with `to_form_body(csrf_token) -> str` — builds URL-encoded body; NEVER logs csrf_token. Payload builder functions: `make_list_notebooks_payload`, `make_get_metadata_payload`, `make_add_url_payload`, `make_add_text_payload`, `make_add_drive_payload`, `make_register_upload_payload`, `make_delete_source_payload`. Function `make_query_params(sources, question, notebook_id, session_id, message_id, history) -> str` — triple-nested source IDs (depth=2), newest-first history, verbosity=120, origin=1. Constants `BATCHEXECUTE_URL` and `QUERY_URL`.
      Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/mcp_gateway/engine/rpc_templates.py`
      Verify: `uv run mypy --strict src/mcp_gateway/engine/rpc_templates.py` — zero errors.

- [x] 8. Create `src/mcp_gateway/engine/readiness_poller.py`.
      `SourceStatus(IntEnum)`: UNKNOWN=-1, PROCESSING=1, READY=2, ERROR=3, PREPARING=5. `parse_source_status(source_row) -> SourceStatus` — scans indices 3,4,5 defensively. Async `poll_until_ready(notebook_id, source_id, fetch_metadata_fn, max_timeout=300.0, base_delay=2.0, max_delay=30.0) -> SourceStatus` — Full Jitter Exponential Backoff: `delay = random.uniform(0, min(base_delay * (2**attempt), max_delay))`, raises `TimeoutError` after `max_timeout` seconds.
      Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/mcp_gateway/engine/readiness_poller.py`
      Verify: `uv run mypy --strict src/mcp_gateway/engine/readiness_poller.py` — zero errors.

- [x] 9. Create golden wire fixture `tests/fixtures/golden_wire_captures.json`.
      Keys: `antixssi_single_frame` (hex bytes, complete batchexecute response with `)]}'\n` prefix + one `wrb.fr` record), `fragmented_two_chunks` (array of two hex strings forming one `wrb.fr` record), `error_frame_132` (batchexecute response with `e` error frame, code 132), `non_ascii_citation` (GenerateFreeFormStreamed line with astral-plane emoji, known UTF-16 offsets, expected Python slice). ZERO real cookies, ZERO real SNlM0e, ZERO real notebook IDs.
      Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/tests/fixtures/golden_wire_captures.json`
      Verify: `python3 -c 'import json; d=json.load(open("tests/fixtures/golden_wire_captures.json")); assert set(d.keys()) == {"antixssi_single_frame","fragmented_two_chunks","error_frame_132","non_ascii_citation"}; print("fixture OK")'`

- [x] 10. Create `tests/test_stream_decoder.py` and `tests/test_coordinate.py`.
       test_stream_decoder.py: `test_antixssi_strip`, `test_fragment_reassembly`, `test_error_frame_raises` (asserts StreamDecodeError with code 132), `test_gffs_citation_extraction`. test_coordinate.py: `test_ascii_roundtrip`, `test_astral_offset`, `test_utf16_slice_with_astral`, `test_normalize_citation_valid`, `test_normalize_citation_invalid_offsets`. Use golden fixture for ground truth.
       Files: `tests/test_stream_decoder.py`, `tests/test_coordinate.py`
       Verify: `uv run pytest tests/test_stream_decoder.py tests/test_coordinate.py -v` — all tests pass.

- [x] 11. Update `src/mcp_gateway/engine/__init__.py` with exports from all 4 engine modules.
       Verify: `uv run mypy --strict src/mcp_gateway/engine/` — zero errors.

---

## FEAT-003 — Native Host & IPC Bridge (Phase 2)

- [x] 12. Create `src/mcp_gateway/host/native_host.py`.
       Constants: `CHROME_FRAME_FORMAT='@I'` (native endian), `IPC_FRAME_FORMAT='>I'` (big endian), `MAX_MESSAGE_SIZE=1024*1024`, `CHUNK_SIZE=512*1024`, `IPC_SOCKET_PATH='/tmp/mcp-gemini-broker.sock'`. Functions: `read_native_message(stream) -> bytes` (struct `@I`, raises `ValueError` if > MAX), `write_native_message(stream, data)` (struct `@I`), `read_ipc_message(reader) -> bytes` (struct `>I`), `write_ipc_message(writer, data)` (struct `>I`). `chunk_message(data, chunk_size) -> list[dict]` — splits into ≤512 KiB frames with `{payload, chunk_index, total_chunks, final}`. `connect_to_broker(socket_path)`. `validate_origin(writer, allowed_extension_id)`. Async `relay_loop(socket_path, allowed_extension_id)` — reads Chrome frame via executor (non-blocking), forwards to IPC, chunks response, writes back to stdout. `main()` — sets `UV_THREADPOOL_SIZE=3`, Windows binary mode via `msvcrt`, calls `asyncio.run(relay_loop(...))`. Zero imports from engine/broker/storage. All logs to stderr only.
       Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/mcp_gateway/host/native_host.py`
       Verify: `uv run mypy --strict src/mcp_gateway/host/native_host.py` — zero errors.

- [x] 13. Create `tests/test_native_framing.py`.
       Tests: `test_read_native_message_roundtrip`, `test_write_native_message_roundtrip`, `test_ipc_big_endian_framing` (confirms `struct.pack('>I',256) == b'\x00\x00\x01\x00'`), `test_chunk_message_small`, `test_chunk_message_large` (600 KiB → 2 chunks), `test_max_message_size_rejected`, `test_chrome_vs_ipc_byte_order` (explicit LE assertion on x86).
       Files: `tests/test_native_framing.py`
       Verify: `uv run pytest tests/test_native_framing.py -v` — all tests pass.

---

## FEAT-004 — Manifest V3 Browser Extension (Phase 3)

- [x] 14. Create `src/extension/manifest.json`.
       `manifest_version:3`, permissions: `["nativeMessaging","scripting","tabs","alarms","storage"]`, host_permissions: `["https://notebook.google.com/*","https://notebooklm.google.com/*"]`. NO `cookies` permission. `background.service_worker: "service_worker.js"`, `background.type: "module"`. Content script at `document_idle` in `ISOLATED` world.
       Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/extension/manifest.json`
       Verify: `python3 -c 'import json; m=json.load(open("src/extension/manifest.json")); assert m["manifest_version"]==3; assert "cookies" not in m.get("permissions",[]); print("OK")'`

- [x] 15. Create `src/extension/service_worker.js`.
       Keep-alive alarm every 30 s. `ensureNativePort()` opens/reconnects `chrome.runtime.connectNative("com.mcp.gemini.broker")`. `ensureNotebookTab()` finds or creates pinned inactive tab, polls for `WIZ_global_data.SNlM0e` up to 15 s, injects `page-main.js` via `chrome.scripting.executeScript({world:"MAIN"})`. Routes commands (`batchexecute`, `query_stream`, `scotty_upload`) via `postMessage` to content_script. Tab recycling after 60 s cooldown for provisioned tabs. Zero `chrome.cookies` API calls. Zero message body logging.
       Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/extension/service_worker.js`
       Verify: Manual — no `chrome.cookies` call (grep confirms), no SNlM0e/ya29 in log statements.

- [x] 16. Create `src/extension/content_script.js`.
       ISOLATED world relay. `window.addEventListener("message")` — forwards `page_main_result` messages to service_worker via `chrome.runtime.sendMessage`. `chrome.runtime.onMessage` — forwards `mcp_bridge_cmd` commands to page via `window.postMessage`. On `DOMContentLoaded`, sends `{type:"content_script_ready", url}`.
       Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/extension/content_script.js`
       Verify: file exists, no `window.WIZ_global_data` access (wrong world).

- [x] 17. Create `src/extension/page-main.js`.
       MAIN world execution. `getAuthContext()` reads `window.WIZ_global_data.SNlM0e`, `FdrFJe`, `authuser` from pathname, `oM1Kwf` email — returns object; tokens never included in responses back to extension. `executeBatchexecute(rpcId, paramsJson, notebookId)` — builds form body with `at={snlm0e}`, calls `fetch(BATCHEXECUTE_URL, {credentials:"include", headers:{Content-Type:"application/x-www-form-urlencoded;charset=UTF-8","X-Same-Domain":"1"}})`, returns `{ok:true, body:text}` or error envelope without any auth values. `executeQueryStream(paramsJson)` — POST to QUERY_URL with isolated response handling. `executeScottyUpload(sourceId, filename, notebookId, fileBase64, authuser)` — 2-step fetch (start + upload,finalize). `window.addEventListener("message")` dispatcher with requestId correlation.
       Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/extension/page-main.js`
       Verify: `grep -n 'SNlM0e\|ya29\|SID\|HSID' src/extension/page-main.js` — only appears in `getAuthContext()` reads, never in `postMessage` payloads.

- [x] 18. Create `src/extension/popup.html`, `popup.css`, `popup.js`.
       popup.html: 360×480px, top-bar (logo, `ConnectionHealthBadge`, `AccountSelector`), main-viewport (`NotebookAllowlistCard` list), action-bar (connect button). popup.css: all 13 CSS custom property tokens from ui-context.md in `:root`, dark theme, `--font-mono` for notebook IDs, no hardcoded hex values outside `:root`. popup.js: reads status from `chrome.runtime.sendMessage({type:"get_status"})`, renders badge; reads `allowlisted_notebooks` from `chrome.storage.local`; connect button handler; no `innerHTML` with user data (XSS prevention).
       Files: `src/extension/popup.html`, `src/extension/popup.css`, `src/extension/popup.js`
       Verify: `python3 -c 'from html.parser import HTMLParser; HTMLParser().feed(open("src/extension/popup.html").read()); print("HTML valid")'`

- [x] 19. Create `src/extension/icons/README.md` noting placeholder PNGs needed.
       Files: `src/extension/icons/README.md`
       Verify: file exists.

---

## FEAT-005 — Broker Daemon & 5-Tool Surface (Phase 4)

- [x] 20. Create `src/mcp_gateway/schemas/error.py`.
       Frozen dataclass `ErrorDetail(code: str, message: str, retryable: bool)`. Frozen dataclass `FailureEnvelope(ok: Literal[False], error: ErrorDetail)` with `to_dict()`. Error code constants: `PERMISSION_DENIED`, `NOT_FOUND`, `ALLOWLIST_DENIED`, `AUTH_REQUIRED`, `UPSTREAM_DRIFT`, `MUTATION_UNKNOWN`, `VAULT_LOCKED`, `INVALID_ARGUMENT`, `INTERNAL`. Function `make_error(code, message, retryable=False) -> FailureEnvelope`.
       Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/mcp_gateway/schemas/error.py`
       Verify: `uv run mypy --strict src/mcp_gateway/schemas/error.py` — zero errors.

- [x] 21. Create `src/mcp_gateway/schemas/tools.py`.
       5 JSON Schema dicts: `LIST_NOTEBOOKS_SCHEMA`, `GET_NOTEBOOK_METADATA_SCHEMA`, `LIST_SOURCES_SCHEMA`, `QUERY_NOTEBOOK_SCHEMA`, `ADD_SOURCE_SCHEMA`. All have `additionalProperties: false`. `ADD_SOURCE_SCHEMA.source.enum` = `["text","url","youtube","drive","file"]`. `TOOL_ANNOTATIONS` dict with readOnly/destructive/idempotent hints per code-standards.md.
       Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/mcp_gateway/schemas/tools.py`
       Verify: `uv run python -c 'from mcp_gateway.schemas.tools import LIST_NOTEBOOKS_SCHEMA,GET_NOTEBOOK_METADATA_SCHEMA,LIST_SOURCES_SCHEMA,QUERY_NOTEBOOK_SCHEMA,ADD_SOURCE_SCHEMA; assert all(s.get("additionalProperties")==False for s in [LIST_NOTEBOOKS_SCHEMA,GET_NOTEBOOK_METADATA_SCHEMA,LIST_SOURCES_SCHEMA,QUERY_NOTEBOOK_SCHEMA,ADD_SOURCE_SCHEMA]); print("OK")'`

- [x] 22. Create `src/mcp_gateway/broker/allowlist.py`.
       `AllowlistConfig` dataclass (version, provider_mode, accounts, notebooks). `load_allowlist(path) -> AllowlistConfig` — reads from path or `~/.config/notebooklm-mcp-bridge/allowlist.json`. `save_allowlist(config, path)` — atomic write (tempfile + rename). `is_notebook_allowed(config, notebook_id) -> bool`. `add_notebook` / `remove_notebook` — return new `AllowlistConfig` (immutable pattern).
       Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/mcp_gateway/broker/allowlist.py`
       Verify: `uv run mypy --strict src/mcp_gateway/broker/allowlist.py` — zero errors.

- [x] 23. Create `src/mcp_gateway/broker/secret_scrubber.py`.
       Compiled regex patterns for: SID, HSID, SSID, `__Secure-1PSID`, SAPISID, `ya29.` access tokens, `SNlM0e`, `FdrFJe`, Bearer tokens. `scrub(text: str) -> str` — replaces all matches with `[REDACTED]`. `scrub_dict(obj: dict) -> dict` — recursively scrubs string values. `assert_clean(text: str) -> None` — raises `ValueError('[SECRET DETECTED]')` if `scrub(text) != text`.
       Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/mcp_gateway/broker/secret_scrubber.py`
       Verify: `uv run python -c 'from mcp_gateway.broker.secret_scrubber import scrub; assert scrub("ya29.A0ARrdaM_test") == "[REDACTED]"; assert scrub("SNlM0e=abc123") == "[REDACTED]"; print("scrubber OK")'`

- [x] 24. Create `src/mcp_gateway/broker/broker.py`.
       Sets `os.environ["UV_THREADPOOL_SIZE"] = "3"` at module import (before any asyncio). `BrokerConfig` dataclass. Class `BrokerDaemon`: `start()` creates Unix socket at `config.socket_path`, `chmod(0o600)`, accepts IPC connections; `handle_ipc_connection()` reads big-endian 32-bit framed JSON, calls `_dispatch()`, writes response frame; `_dispatch()` validates allowlist, routes to handler, calls `secret_scrubber.scrub_dict()` on all responses. Class `McpFacade`: uses `mcp.Server` from `mcp` PyPI package; registers 5 tools with schemas from `tools.py` and annotations; each tool handler validates input, checks allowlist, calls `BrokerDaemon`, returns structured response or `FailureEnvelope`. `main()` — parses CLI args (`serve` | `mcp`), runs appropriate mode. NEVER writes to sys.stdout outside MCP SDK transport. All diagnostic output to stderr.
       Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/mcp_gateway/broker/broker.py`
       Verify: `uv run mypy --strict src/mcp_gateway/broker/broker.py` — zero errors.

- [x] 25. Update `__init__.py` exports for broker and schemas packages. Run full mypy check.
       Verify: `uv run mypy --strict src/` — zero errors across all modules.

---

## FEAT-006 — Mutation Journal & Scotty Upload (Phase 5)

- [x] 26. Create `src/mcp_gateway/storage/schema.sql`.
       `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;`. Table `mutation_journal(id, request_key UNIQUE, notebook_id, operation_type CHECK IN('add_source','query_notebook'), payload_hash, state CHECK IN('prepared','sent','confirmed','rejected','unknown'), assigned_source_id, created_at, updated_at)`. Append-only `mutation_events(id, mutation_id FK, event_type, old_state, new_state, detail, occurred_at)`. Indexes on `request_key` and `mutation_id`. ZERO SQL string interpolation.
       Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/mcp_gateway/storage/schema.sql`
       Verify: `sqlite3 /tmp/test_schema.db < src/mcp_gateway/storage/schema.sql && echo "schema OK"`

- [x] 27. Create `src/mcp_gateway/storage/journal.py`.
       `MutationState(str,Enum)`: PREPARED/SENT/CONFIRMED/REJECTED/UNKNOWN. `OperationType(str,Enum)`. Frozen dataclass `MutationRecord`. `compute_payload_hash(args, capability_secret) -> str` — HMAC-SHA256 of `json.dumps(args, sort_keys=True, separators=(',',':'))`. Class `MutationJournal`: `__init__(db_path)`, `_apply_schema()` (reads schema.sql via `Path(__file__).parent / "schema.sql"`). `prepare(request_key, notebook_id, operation_type, args, capability_secret) -> MutationRecord` — idempotent (returns existing if not rejected), uses parameterized INSERT. `transition(request_key, new_state, assigned_source_id=None) -> MutationRecord` — legal transitions: prepared→sent, sent→{confirmed|rejected|unknown}; raises `ValueError` on all others (especially sent→prepared, sent→sent). CRITICAL: timeout always → UNKNOWN, never auto-replay. `get(request_key) -> MutationRecord | None`. `list_by_notebook(notebook_id) -> list[MutationRecord]`. ZERO SQL f-strings or % formatting.
       Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/src/mcp_gateway/storage/journal.py`
       Verify: `uv run mypy --strict src/mcp_gateway/storage/journal.py` — zero errors.

- [x] 28. Create `tests/test_journal.py`.
       11 tests (see FEAT-006 steps above). All use `tmp_path` fixture. `test_sql_injection_in_request_key` uses `request_key="'; DROP TABLE mutation_journal; --"` and confirms record created without error.
       Files: `/home/williamdeldaymarketing/Projects/Google Notebook MCP/tests/test_journal.py`
       Verify: `uv run pytest tests/test_journal.py -v` — all 11 tests pass.

- [x] 29. Wire `MutationJournal` into `broker.py`.
       `BrokerDaemon.__init__` instantiates `MutationJournal`. Mutation operations: `prepare()` before send, `transition(SENT)` before forwarding, `transition(CONFIRMED|REJECTED|UNKNOWN)` on outcome. Timeout → always UNKNOWN. `query_notebook` uses `request_key` from tool input. `add_source` uses `idempotency_key` as `request_key`.
       Files: `src/mcp_gateway/broker/broker.py`
       Verify: `uv run mypy --strict src/` — zero errors. `uv run pytest tests/ -v` — all tests pass.

- [x] 30. Final full verification pass.
       Run complete test suite and type checker. Update `docs/progress-tracker.md` marking all phases complete.
       Files: `docs/progress-tracker.md`
       Verify: `uv run mypy --strict src/` zero errors. `uv run pytest tests/ -v` all pass.

---

## Critical Invariants Summary (enforced at every step)

| Invariant | Where enforced |
|-----------|---------------|
| Raw cookies/ya29/SNlM0e never in logs/IPC/responses | secret_scrubber.py + page-main.js response shape |
| Native Messaging and MCP stdio in separate processes | native_host.py has zero MCP imports; broker.py has zero Chrome framing |
| Exactly 5 MCP tools | tools.py + McpFacade |
| `sent` mutations never auto-replayed | journal.py transition() ValueError guards |
| UTF-16 → Python Unicode before returning citations | coordinate.py normalize_citation() |
| UV_THREADPOOL_SIZE=3 set before asyncio | broker.py module-level os.environ |
| Unix socket under /tmp/, chmod 0o600 | broker.py BrokerDaemon.start() |
| All Python mypy --strict clean | verification step on every FEAT |
| Zero SQL string interpolation | schema.sql + journal.py parameterized queries only |
