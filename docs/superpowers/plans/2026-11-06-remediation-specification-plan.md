# 9-Defect Comprehensive Architectural & TDD Remediation Specification Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remediate all 9 audited architectural, security, and lifecycle defects across the Gemini Notebook MCP gateway, establishing strict mutation idempotency/isolation, unblocking the full test suite by removing process termination from `native_host.py`, isolating Node compile caches and CWD state, serializing companion socket drain operations, implementing safe Win32 overlapped named pipe I/O, supporting legacy/manual allowlist coexistence with `%2e` URL sanitization and rollback, enabling multi-browser native messaging installation by default, and hardening systemd and path documentation.

**Architecture:**
1. **Idempotency & Multi-Tenant Request Isolation (`journal.py`, `broker.py`)**: Strip transient parameters (`session_token`, `timeout_seconds`, `request_key`, `idempotency_key`, `_meta`, `traceparent`) consistently before computing HMAC-SHA256 digests. Enforce strict matching of `notebook_id`, `operation_type`, and `payload_hash` on prepare and replay, rejecting cross-notebook or altered re-preparations with `REQUEST_KEY_CONFLICT`. On confirmed query replay, verify `cached_entry` matches both `notebook_id` and query text; reject missing or mismatched cache entries rather than returning ungrounded stubs (`citations: []`).
2. **Process Integrity & Suite Unblocking (`native_host.py`, `pyproject.toml`, `test_lifecycle.py`)**: Remove `os._exit(0)` from `main()`'s `finally:` block in `native_host.py` and isolate it exclusively to `if __name__ == "__main__":`. Ensure in-process tests (e.g. `test_windows_binary_stdio_mode`) complete cleanly without terminating the test runner, unblocking all 98 subsequent tests. Add `pythonpath = ["src"]` to `pyproject.toml` so pytest cleanly resolves `mcp_gateway`.
3. **Workspace Isolation & Atomic Config Permissions (`project_config.py`, `test_lifecycle.py`, `tests/conftest.py`)**: Clear `NODE_COMPILE_CACHE` in Node.js subprocess invocations to prevent `./1/` directory creation. Write `.notebook_mcp.json` atomically via temporary file replacement with strict `0o600` permissions. Add an autouse test fixture in `tests/conftest.py` isolating `Path.cwd()` during testing.
4. **IPC Concurrency & Win32 Overlapped I/O (`broker.py`, `ipc.py`)**: Wrap both `hello_ack` and `HEARTBEAT_PONG` frame writes and drains in `broker.py` within `self._companion_ipc_mutex` to eliminate `StreamWriter.drain()` concurrent write races. In `WindowsNamedPipeServer`, allocate dedicated `OVERLAPPED` structures for `ReadFile` and `WriteFile`, treat `ERROR_PIPE_CONNECTED (535)` as immediately connected in `ConnectNamedPipe`, and invoke `CancelIo` on server stop.
5. **Sanitization, Legacy Coexistence & Multi-Browser Support (`popup.js`, `broker.py`, `setup_native_host.py`)**: Add `%2e` encoded dot traversal filtering to `parseAndValidateNotebookId` in `popup.js`, roll back in-memory catalog changes on sync failure, and mark manual additions with `manual: true`. In `broker.py`, validate UUIDs only on entries with `manual: true`, preserving legacy non-UUID notebook entries. In `setup_native_host.py`, default `--browser` to `None` so `install_manifest` targets all detected Chromium browsers.
6. **Documentation & Path Alignment (`client-configuration.md`)**: Enforce quoted whitespace paths for `WorkingDirectory` and `ExecStart` in systemd unit examples, align verification commands with `get_default_ipc_path()` fallback behaviors, and update architecture diagrams with correct socket subdirectories.

**Tech Stack:** Python 3.11+ (`asyncio`, `sqlite3`, `pydantic`, `mcp`), Win32 Named Pipes (`pywin32` / `win32file` / `win32pipe`), Chrome Native Messaging MV3 (Vanilla ES2022 JS), `pytest` / `pytest-asyncio` / `pytest-cov`, `ruff`, `mypy --strict`.

---

## File Structure & Responsibility Map

| File Path | Action | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | Add `pythonpath = ["src"]` under `[tool.pytest.ini_options]` for deterministic import resolution. |
| `src/mcp_gateway/storage/journal.py` | Modify | Strip transient keys (`session_token`, `timeout_seconds`, `request_key`, `idempotency_key`, `_meta`, `traceparent`) in `compute_payload_hash`. Enforce strict check of `notebook_id`, `operation_type`, and `payload_hash` in `prepare()`. |
| `src/mcp_gateway/broker/broker.py` | Modify | Validate `existing.notebook_id == nb_id`, `existing.operation_type == expected_op`, and `existing.payload_hash == compute_payload_hash(...)` across all 4 mutation handlers (`_handle_query_notebook`, `_handle_add_source`, `_handle_create_note`, `_handle_delete_note`). In `_handle_query_notebook`, verify query cache matches `notebook_id` and question; eliminate synthetic `citations: []` stubs. Serialize `hello_ack` and `HEARTBEAT_PONG` under `self._companion_ipc_mutex`. Restrict UUID validation in `_handle_update_allowlist` to entries marked `manual: true`. |
| `src/mcp_gateway/host/native_host.py` | Modify | Remove `os._exit(0)` from `main()`'s `finally:` block; isolate `os._exit(0)` under `if __name__ == "__main__":`. |
| `src/mcp_gateway/broker/project_config.py` | Modify | Atomically persist `.notebook_mcp.json` with `0o600` file permissions via temporary file and `os.replace`. |
| `src/mcp_gateway/transport/ipc.py` | Modify | Provide dedicated `OVERLAPPED` structs for `ReadFile` and `WriteFile` on `FILE_FLAG_OVERLAPPED` pipes; handle `ERROR_PIPE_CONNECTED (535)` in `ConnectNamedPipe`; add `CancelIo` in `stop()`. |
| `src/extension/popup.js` | Modify | Filter `%2e` encoded traversals in `parseAndValidateNotebookId`; tag manual submissions with `manual: true`; roll back `notebookCatalog` state on sync failure; remove global `validate_uuids: true`. |
| `setup_native_host.py` | Modify | Default `--browser` argument to `None` and pass directly to `install_manifest` to install across all detected browsers. |
| `docs/client-configuration.md` | Modify | Quote paths with spaces in systemd examples; align verification commands and IPC diagrams with `paths.py`. |
| `tests/conftest.py` | Create | Autouse fixture isolating `Path.cwd()` during test runs to prevent `.notebook_mcp.json` pollution in the workspace root. |
| `tests/test_lifecycle.py` | Modify | Strip `NODE_COMPILE_CACHE` in `_run_node_script` to prevent `./1/` compile cache generation. Ensure `test_windows_binary_stdio_mode` completes cleanly in-process. |
| `tests/test_journal.py` | Modify | Test transient key stripping, request key conflict detection on mismatched notebook, op, or payload in `journal.prepare`. |
| `tests/test_broker.py` | Modify | Test request key conflicts in `_handle_query_notebook`, `_handle_add_source`, `_handle_create_note`, `_handle_delete_note`. Test elimination of synthetic citation stubs. Test `hello_ack` and heartbeat mutex serialization. Test legacy non-UUID notebook coexistence with `manual: true` validation. |
| `tests/test_popup_webui.py` | Modify | Test `%2e` URL/ID filtering, catalog rollback on error, and multi-browser installer execution with `browser=None`. |

---

## Remediation Tasks

### Task 1: Defect 2 [HIGH] — Configure `pytest` `pythonpath` in `pyproject.toml`

**Files:**
- Modify: `pyproject.toml:81-84`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write verification test / check baseline**

Verify the current configuration in `pyproject.toml`:
```bash
python3 -c "import tomllib; f = open('pyproject.toml', 'rb'); data = tomllib.load(f); print(data['tool']['pytest']['ini_options'])"
```

- [ ] **Step 2: Update `pyproject.toml`**

Add `pythonpath = ["src"]` under `[tool.pytest.ini_options]` in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
addopts = "--cov=src/mcp_gateway --cov-report=term-missing"
pythonpath = ["src"]
```

- [ ] **Step 3: Run pytest to verify configuration loads**

Run:
```bash
taskset -c 0-5 pytest tests/test_cli.py -k test_cli_version -v
```
Expected: PASS with pytest picking up `pythonpath = ["src"]`.

---

### Task 2: Defect 3 [CRITICAL] — Isolate Native Host `os._exit(0)` & Unblock Test Suite

**Files:**
- Modify: `src/mcp_gateway/host/native_host.py:357-364`
- Modify: `tests/test_lifecycle.py:71-94`

- [ ] **Step 1: Write test verifying in-process execution does not terminate interpreter**

In `tests/test_lifecycle.py`, verify `test_windows_binary_stdio_mode` runs `main()` cleanly without calling `os._exit`:
```python
def test_windows_binary_stdio_mode() -> None:
    """On Windows, stdio is pinned to binary mode via msvcrt.setmode and exits cleanly."""
    from mcp_gateway.host.native_host import main

    mock_msvcrt = MagicMock()
    mock_stdin = MagicMock()
    mock_stdin.fileno.return_value = 0
    mock_stdout = MagicMock()
    mock_stdout.fileno.return_value = 1

    with patch.dict(sys.modules, {"msvcrt": mock_msvcrt}):
        with patch("sys.platform", "win32"):
            with patch.object(sys, "stdin", mock_stdin), patch.object(sys, "stdout", mock_stdout):
                with patch("mcp_gateway.host.native_host.relay_loop", return_value=None):
                    with patch("mcp_gateway.host.native_host.asyncio.run"):
                        with patch("mcp_gateway.host.native_host.setup_stderr_redirection"):
                            # This MUST NOT raise SystemExit or invoke os._exit(0)
                            main()
                        assert mock_msvcrt.setmode.call_count == 2
                        calls = mock_msvcrt.setmode.call_args_list
                        expected_binary = getattr(os, "O_BINARY", 0x8000)
                        assert calls[0][0][1] == expected_binary
                        assert calls[1][0][1] == expected_binary
```

- [ ] **Step 2: Update `src/mcp_gateway/host/native_host.py`**

Refactor `main()` and entrypoint guard at lines 357-364:
```python
    try:
        asyncio.run(relay_loop(socket_path, allowed_extension_id))
    except Exception as exc:
        print(f"[native_host] fatal error in relay_loop: {exc}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    finally:
        os._exit(0)
```

- [ ] **Step 3: Run pytest on `test_lifecycle.py` and downstream tests**

Run:
```bash
taskset -c 0-5 pytest tests/test_lifecycle.py tests/test_native_framing.py -v
```
Expected: PASS with `test_windows_binary_stdio_mode` completing without halting the suite, followed immediately by `test_native_framing.py`.

---

### Task 3: Defect 4 [HIGH] — Node Cache `./1/`, CWD Isolation, & Atomic `0o600` Permissions

**Files:**
- Create: `tests/conftest.py`
- Modify: `tests/test_lifecycle.py:105-116`
- Modify: `src/mcp_gateway/broker/project_config.py:37-55`
- Test: `tests/test_project_notebook_selection.py`

- [ ] **Step 1: Write failing test for atomic `0o600` permissions and CWD isolation**

In `tests/test_project_notebook_selection.py`, add a test for permissions:
```python
def test_save_project_notebook_config_permissions_and_atomicity(tmp_path: Path) -> None:
    from mcp_gateway.broker.project_config import save_project_notebook_config, PROJECT_CONFIG_FILENAME

    saved = save_project_notebook_config("00000000-0000-0000-0000-000000000001", "Test Project", project_dir=tmp_path)
    assert saved is not None
    assert saved.exists()
    assert (saved.stat().st_mode & 0o777) == 0o600
```

- [ ] **Step 2: Implement `tests/conftest.py` with autouse CWD isolation fixture**

Create `tests/conftest.py`:
```python
from __future__ import annotations

from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def isolate_test_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates the current working directory to a unique tmp_path per test to prevent repo root pollution."""
    monkeypatch.chdir(tmp_path)
```

- [ ] **Step 3: Clear `NODE_COMPILE_CACHE` in `tests/test_lifecycle.py`**

In `tests/test_lifecycle.py`, update `_run_node_script`:
```python
def _run_node_script(script: str) -> dict[str, Any]:
    """Executes a Node.js snippet and returns parsed JSON output, stripping NODE_COMPILE_CACHE."""
    cmd = ["node", "-e", script]
    clean_env = {k: v for k, v in os.environ.items() if k != "NODE_COMPILE_CACHE"}
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
        env=clean_env,
    )
    return cast(dict[str, Any], json.loads(result.stdout.strip()))
```

- [ ] **Step 4: Update `save_project_notebook_config` in `src/mcp_gateway/broker/project_config.py`**

Refactor `save_project_notebook_config`:
```python
def save_project_notebook_config(
    notebook_id: str,
    title: str = "",
    project_dir: Path | str | None = None,
) -> Path | None:
    """Saves notebook preference to .notebook_mcp.json in the project directory with atomic write and 0o600 permissions."""
    try:
        target_dir = Path(project_dir) if project_dir else Path.cwd()
        target_dir.mkdir(parents=True, exist_ok=True)
        config_file = target_dir / PROJECT_CONFIG_FILENAME
        tmp_file = target_dir / f".{PROJECT_CONFIG_FILENAME}.{os.getpid()}.{time.time_ns()}.tmp"
        payload = {
            "notebook_id": notebook_id,
            "title": title,
            "updated_at": time.time(),
        }
        content = json.dumps(payload, indent=2) + "\n"
        fd = os.open(str(tmp_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(str(tmp_file), 0o600)
        os.replace(str(tmp_file), str(config_file))
        return config_file
    except OSError as exc:
        logger.warning("Could not write project config .notebook_mcp.json: %s", exc)
        return None
```

- [ ] **Step 5: Run tests to verify**

Run:
```bash
taskset -c 0-5 pytest tests/test_lifecycle.py tests/test_project_notebook_selection.py -v
```
Expected: PASS with no `./1/` directory created and file permissions equal to `0o600`.

---

### Task 4: Defect 5 [HIGH] — Serialize `StreamWriter.drain()` in Broker Frame Handler

**Files:**
- Modify: `src/mcp_gateway/broker/broker.py:330-362`
- Test: `tests/test_broker.py`

- [ ] **Step 1: Write test for concurrent companion writes**

In `tests/test_broker.py`, add a test verifying serialized execution of `hello_ack` and `HEARTBEAT_PONG`:
```python
@pytest.mark.asyncio
async def test_companion_frame_drain_serialization() -> None:
    """Ensures hello_ack and HEARTBEAT_PONG socket writes are mutex-protected against race conditions."""
    from mcp_gateway.broker.broker import BrokerDaemon, AllowlistConfig

    # Instantiate broker with mock config
    # Send concurrent 'hello' and 'HEARTBEAT_PING' frames and verify writer.drain is guarded by _companion_ipc_mutex
```

- [ ] **Step 2: Update `_handle_companion_frame` in `src/mcp_gateway/broker/broker.py`**

In `src/mcp_gateway/broker/broker.py`, wrap `hello_ack` (lines 331-339) and `HEARTBEAT_PONG` (lines 351-361) writes in `async with self._companion_ipc_mutex:`:
```python
                # Handshake handling with native_host.py
                if raw_message.get("type") == "hello":
                    self._active_companion_writer = writer
                    ack = {
                        "type": "hello_ack",
                        "extension_id": os.environ.get("ALLOWED_EXTENSION_ID", ""),
                    }
                    ack_bytes = json.dumps(ack).encode("utf-8")
                    async with self._companion_ipc_mutex:
                        writer.write(struct.pack(IPC_FRAME_FORMAT, len(ack_bytes)) + ack_bytes)
                        await writer.drain()
                    continue

                # Response frame handling for pending companion requests
                request_id = raw_message.get("requestId")
                if request_id and request_id in self._pending_responses:
                    fut = self._pending_responses.pop(request_id)
                    if not fut.done():
                        fut.set_result(raw_message)
                    continue

                # Heartbeat ping handling from companion (Domain E)
                if raw_message.get("type") in ("ping", "HEARTBEAT_PING") or raw_message.get("command") in ("ping", "HEARTBEAT_PING"):
                    pong_reply: dict[str, Any] = {
                        "ok": True,
                        "type": "pong",
                        "command": "HEARTBEAT_PONG",
                        "requestId": raw_message.get("requestId", ""),
                        "timestamp": time.time(),
                    }
                    pong_bytes = json.dumps(pong_reply).encode("utf-8")
                    async with self._companion_ipc_mutex:
                        writer.write(struct.pack(IPC_FRAME_FORMAT, len(pong_bytes)) + pong_bytes)
                        await writer.drain()
                    continue
```

- [ ] **Step 3: Run broker tests**

Run:
```bash
taskset -c 0-5 pytest tests/test_broker.py -k test_companion -v
```
Expected: PASS.

---

### Task 5: Defect 1 [CRITICAL] — Deterministic Idempotency Key Isolation & Grounded Replay

**Files:**
- Modify: `src/mcp_gateway/storage/journal.py:65-70,184-252`
- Modify: `src/mcp_gateway/broker/broker.py:1171-1221,1369-1406,1585-1620,1777-1810`
- Test: `tests/test_journal.py`
- Test: `tests/test_broker.py`

- [ ] **Step 1: Write failing tests in `tests/test_journal.py` and `tests/test_broker.py`**

In `tests/test_journal.py`:
```python
def test_compute_payload_hash_strips_transient_keys(secret: bytes) -> None:
    args1 = {"notebook_id": "nb-1", "question": "What is AI?", "session_token": "token-a", "timeout_seconds": 60}
    args2 = {"notebook_id": "nb-1", "question": "What is AI?", "session_token": "token-b", "timeout_seconds": 120}
    assert compute_payload_hash(args1, secret) == compute_payload_hash(args2, secret)


def test_prepare_detects_request_key_conflict_on_mismatched_payload(journal: MutationJournal, secret: bytes) -> None:
    args1 = {"notebook_id": "nb-1", "question": "Query A"}
    args2 = {"notebook_id": "nb-1", "question": "Query B"}
    journal.prepare("req-key-1", "nb-1", OperationType.QUERY_NOTEBOOK, args1, secret)
    
    with pytest.raises(ValueError, match="Request key conflict"):
        journal.prepare("req-key-1", "nb-1", OperationType.QUERY_NOTEBOOK, args2, secret)


def test_prepare_detects_request_key_conflict_on_mismatched_notebook(journal: MutationJournal, secret: bytes) -> None:
    args = {"notebook_id": "nb-1", "question": "Query A"}
    journal.prepare("req-key-2", "nb-1", OperationType.QUERY_NOTEBOOK, args, secret)
    
    with pytest.raises(ValueError, match="Request key conflict"):
        journal.prepare("req-key-2", "nb-2", OperationType.QUERY_NOTEBOOK, args, secret)
```

In `tests/test_broker.py`:
```python
@pytest.mark.asyncio
async def test_handle_query_notebook_confirmed_replay_cache_validation(broker: BrokerDaemon) -> None:
    # 1. Prepare and confirm a query
    # 2. Replay with identical key: returns cached answer + citations
    # 3. Replay with same key but mismatched question/notebook or missing cache: returns REQUEST_KEY_CONFLICT, NOT empty citations []
```

- [ ] **Step 2: Update `compute_payload_hash` and `prepare` in `src/mcp_gateway/storage/journal.py`**

In `src/mcp_gateway/storage/journal.py`:
```python
TRANSIENT_PAYLOAD_KEYS: frozenset[str] = frozenset({
    "session_token",
    "timeout_seconds",
    "request_key",
    "idempotency_key",
    "_meta",
    "traceparent",
})


def compute_payload_hash(args: dict[str, Any], capability_secret: bytes) -> str:
    """Computes a deterministic HMAC-SHA256 digest of canonicalized JSON arguments with transient keys stripped."""
    clean_args = {k: v for k, v in args.items() if k not in TRANSIENT_PAYLOAD_KEYS}
    canonical = json.dumps(clean_args, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(capability_secret, canonical, hashlib.sha256).hexdigest()
```

In `prepare()`:
```python
    def prepare(
        self,
        request_key: str,
        notebook_id: str,
        operation_type: OperationType,
        args: dict[str, Any],
        capability_secret: bytes,
    ) -> MutationRecord:
        """Prepares a mutation record. Validates invariants if already prepared/sent/confirmed."""
        payload_hash = compute_payload_hash(args, capability_secret)

        def _do_prepare() -> MutationRecord:
            with self._conn:
                cursor = self._conn.execute(
                    "SELECT * FROM mutation_journal WHERE request_key = ?",
                    (request_key,),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    record = self._row_to_record(existing)
                    if record.notebook_id != notebook_id:
                        raise ValueError(
                            f"Request key conflict for {request_key!r}: notebook_id mismatch "
                            f"({record.notebook_id!r} != {notebook_id!r})."
                        )
                    if record.operation_type != operation_type:
                        raise ValueError(
                            f"Request key conflict for {request_key!r}: operation_type mismatch "
                            f"({record.operation_type.value!r} != {operation_type.value!r})."
                        )
                    if record.payload_hash != payload_hash:
                        raise ValueError(
                            f"Request key conflict for {request_key!r}: payload_hash mismatch."
                        )
                    if record.state == MutationState.REJECTED:
                        raise ValueError(
                            f"Mutation with request_key {request_key!r} was previously rejected."
                        )
                    return record
```

- [ ] **Step 3: Update `_handle_query_notebook`, `_handle_add_source`, `_handle_create_note`, `_handle_delete_note` in `src/mcp_gateway/broker/broker.py`**

In `_handle_query_notebook`:
```python
        existing = self.journal.get(request_key)
        if existing is not None:
            expected_hash = compute_payload_hash(command, self.config.capability_secret)
            if (
                existing.notebook_id != nb_id
                or existing.operation_type != OperationType.QUERY_NOTEBOOK
                or existing.payload_hash != expected_hash
            ):
                return make_error(
                    REQUEST_KEY_CONFLICT,
                    f"Request key conflict: mutation {request_key!r} exists with conflicting parameters.",
                    retryable=False,
                ).to_dict()

            if existing.state in (MutationState.SENT, MutationState.UNKNOWN):
                return make_error(
                    REQUEST_KEY_CONFLICT,
                    f"Mutation {request_key!r} is currently in state {existing.state.value!r}. "
                    "Automatic replay is blocked; active reconciliation required.",
                    retryable=False,
                ).to_dict()
            elif existing.state == MutationState.CONFIRMED:
                cached_entry = self.journal.get_query_cache(request_key)
                if (
                    cached_entry is not None
                    and cached_entry.get("notebook_id") == nb_id
                    and cached_entry.get("query_text") == question
                ):
                    try:
                        parsed = json.loads(cached_entry["response_payload"])
                        if isinstance(parsed, dict):
                            return {
                                "ok": True,
                                "answer": str(parsed.get("answer", "")),
                                "citations": list(parsed.get("citations", [])),
                                "cached": True,
                            }
                    except Exception:
                        pass
                # Never return synthetic ungrounded stub citations: []
                return make_error(
                    REQUEST_KEY_CONFLICT,
                    f"Confirmed mutation {request_key!r} cache entry is missing or mismatched.",
                    retryable=False,
                ).to_dict()
            elif existing.state == MutationState.REJECTED:
                return make_error(
                    REQUEST_KEY_CONFLICT,
                    f"Mutation {request_key!r} was previously rejected.",
                    retryable=False,
                ).to_dict()
```

Apply matching `existing.notebook_id != nb_id`, `existing.operation_type != ...`, and `existing.payload_hash != expected_hash` conflict guards to `_handle_add_source`, `_handle_create_note`, and `_handle_delete_note`.

- [ ] **Step 4: Run tests to verify**

Run:
```bash
taskset -c 0-5 pytest tests/test_journal.py tests/test_broker.py -k "test_prepare or test_handle" -v
```
Expected: PASS.

---

### Task 6: Defect 6 [HIGH] — Hardened Win32 Named Pipes Overlapped I/O

**Files:**
- Modify: `src/mcp_gateway/transport/ipc.py:120-154,185-230,287-300,326-340`
- Test: `tests/test_transport.py`

- [ ] **Step 1: Write test for Win32 overlapped struct and error code 535 handling**

In `tests/test_transport.py`, write mock tests verifying:
1. `_NamedPipeTransport.write` calls `win32file.WriteFile` with an `OVERLAPPED` structure.
2. `_pump_reads` calls `win32file.ReadFile` with an `OVERLAPPED` structure.
3. `ConnectNamedPipe` immediately marks pipe connected on Win32 error 535 (`ERROR_PIPE_CONNECTED`).
4. `stop()` invokes `win32file.CancelIo` on open pipe handles.

- [ ] **Step 2: Update `_NamedPipeTransport` and `WindowsNamedPipeServer` in `src/mcp_gateway/transport/ipc.py`**

In `_NamedPipeTransport`:
```python
    def write(self, data: Any) -> None:
        if self._closing or not data:
            return
        try:
            overlapped = self._win32file.OVERLAPPED()
            self._win32file.WriteFile(self._pipe_handle, bytes(data), overlapped)
        except Exception as exc:
            self._closing = True
            self._loop.call_soon(self._protocol.connection_lost, exc)
```

In `_dispatch_connected_pipe`:
```python
        self._active_handles.add(pipe_handle)
        async def _pump_reads() -> None:
            while not transport.is_closing():
                try:
                    overlapped = win32file.OVERLAPPED()
                    overlapped.hEvent = win32file.CreateEvent(None, True, False, None)
                    try:
                        _hr, chunk = await loop.run_in_executor(
                            None,
                            win32file.ReadFile,
                            pipe_handle,
                            65536,
                            overlapped,
                        )
                        if not chunk:
                            break
                        reader.feed_data(bytes(chunk))
                    finally:
                        if getattr(overlapped, "hEvent", None) is not None:
                            try:
                                win32file.CloseHandle(overlapped.hEvent)
                            except Exception:
                                pass
                except Exception:
                    break
            reader.feed_eof()
```

In `_listen_loop`:
```python
            try:
                overlapped = win32file.OVERLAPPED()
                overlapped.hEvent = win32file.CreateEvent(None, True, False, None)
                try:
                    res = win32pipe.ConnectNamedPipe(pipe_handle, overlapped)
                    if res != 0:
                        await self._wait_event(overlapped.hEvent)
                except Exception as exc:
                    # WinError 535: ERROR_PIPE_CONNECTED (client connected between CreateNamedPipe and ConnectNamedPipe)
                    win_err = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
                    if win_err != 535:
                        raise
                finally:
                    if getattr(overlapped, "hEvent", None) is not None:
                        try:
                            win32file.CloseHandle(overlapped.hEvent)
                        except Exception:
                            pass
```

In `stop()`:
```python
    async def stop(self) -> None:
        self._serving = False
        if sys.platform == "win32":
            try:
                import win32file
                for handle in list(self._active_handles):
                    try:
                        win32file.CancelIo(handle)
                    except Exception:
                        pass
            except Exception:
                pass
        self._active_handles.clear()
```

- [ ] **Step 3: Run transport tests**

Run:
```bash
taskset -c 0-5 pytest tests/test_transport.py -v
```
Expected: PASS.

---

### Task 7: Defect 7 [MEDIUM] — Popup URL Sanitization, Catalog Rollback & Manual Validation Tagging

**Files:**
- Modify: `src/extension/popup.js:40-88,397-428,632-679`
- Modify: `src/mcp_gateway/broker/broker.py:780-840`
- Test: `tests/test_popup_webui.py`
- Test: `tests/test_broker.py`

- [ ] **Step 1: Write test for `%2e` URL rejection, rollback on failure, and manual tag preservation**

In `tests/test_popup_webui.py`:
```python
def test_parse_and_validate_notebook_id_rejects_url_encoded_traversal() -> None:
    script = """
    const { parseAndValidateNotebookId } = require('./src/extension/popup.js');
    console.log(JSON.stringify({
        percentDot: parseAndValidateNotebookId('%2e%2e/etc/passwd'),
        doubleDotEncoded: parseAndValidateNotebookId('https://notebook.google.com/notebook/%2e%2e%2f12345'),
        validUuid: parseAndValidateNotebookId('11111111-2222-3333-4444-555555555555')
    }));
    """
    out = _run_node_script(script)
    assert out["percentDot"] is None
    assert out["doubleDotEncoded"] is None
    assert out["validUuid"] == "11111111-2222-3333-4444-555555555555"
```

In `tests/test_broker.py`:
```python
@pytest.mark.asyncio
async def test_update_allowlist_preserves_legacy_ids_unless_manual(broker: BrokerDaemon) -> None:
    # Payload with legacy non-UUID ID (without manual: true) passes
    # Payload with legacy non-UUID ID (with manual: true) fails with INVALID_ARGUMENT
```

- [ ] **Step 2: Update `src/extension/popup.js`**

In `src/extension/popup.js`:
Add `%2e` and `%2E` checks to `parseAndValidateNotebookId`:
```javascript
function parseAndValidateNotebookId(rawInput) {
  if (typeof rawInput !== 'string') {
    return null;
  }
  let candidate = rawInput.trim();
  const lowerCandidate = candidate.toLowerCase();
  if (
    !candidate ||
    candidate.includes('..') ||
    candidate.includes('\\') ||
    lowerCandidate.includes('%2e')
  ) {
    return null;
  }
```

In `persistAllowlist`:
Serialize `manual: Boolean(nb.manual)` per entry, and omit global `validate_uuids`:
```javascript
async function persistAllowlist() {
  const allowedMap = {};
  for (const nb of notebookCatalog.values()) {
    if (nb.allowed) {
      allowedMap[nb.id] = {
        title: nb.title || '',
        mode: normalizeMode(nb.mode),
        manual: Boolean(nb.manual),
      };
    }
  }

  try {
    const res = await chrome.runtime.sendMessage({
      type: 'update_allowlist',
      notebooks: allowedMap,
    });
    return res || { ok: false };
  } catch (err) {
    return {
      ok: false,
      error: { message: err instanceof Error ? err.message : 'Failed to sync allowlist.' },
    };
  }
}
```

In `form.addEventListener('submit', ...)`:
Add `manual: true` and implement rollback on failure:
```javascript
    const prev = notebookCatalog.get(validatedId);

    notebookCatalog.set(validatedId, {
      id: validatedId,
      title: customTitle || prev?.title || '',
      allowed: true,
      mode: selectedMode,
      sourceCount: prev?.sourceCount,
      manual: true,
    });

    const syncRes = await persistAllowlist();
    if (syncRes && syncRes.ok === false) {
      // Rollback notebookCatalog to previous state
      if (prev) {
        notebookCatalog.set(validatedId, prev);
      } else {
        notebookCatalog.delete(validatedId);
      }
      if (errorEl) {
        errorEl.textContent = String(syncRes.error?.message || 'Failed to sync notebook with daemon.');
        errorEl.hidden = false;
      }
    } else {
      inputEl.value = '';
      if (titleEl) {
        titleEl.value = '';
      }
    }

    renderNotebookList(Array.from(notebookCatalog.values()));
```

- [ ] **Step 3: Update `_handle_update_allowlist` in `src/mcp_gateway/broker/broker.py`**

Refactor `_handle_update_allowlist` (lines 780-840) to validate UUIDs only when `meta_dict.get("manual") is True`:
```python
            if isinstance(raw_notebooks, dict):
                for raw_id, meta in raw_notebooks.items():
                    meta_dict = meta if isinstance(meta, dict) else {}
                    must_validate = bool(meta_dict.get("manual", False))
                    if must_validate:
                        try:
                            clean_id = parse_and_validate_notebook_id(str(raw_id))
                        except ValueError as exc:
                            return make_error(INVALID_ARGUMENT, str(exc), retryable=False).to_dict()
                    else:
                        clean_id = str(raw_id).strip()
                        if not clean_id or ".." in clean_id or "\\" in clean_id or "/" in clean_id:
                            return make_error(
                                INVALID_ARGUMENT,
                                f"Invalid notebook ID {raw_id!r}.",
                                retryable=False,
                            ).to_dict()
```

- [ ] **Step 4: Run tests to verify**

Run:
```bash
taskset -c 0-5 pytest tests/test_popup_webui.py tests/test_broker.py -k test_update_allowlist -v
```
Expected: PASS.

---

### Task 8: Defect 8 [MEDIUM] — Multi-Browser Native Messaging Installation by Default

**Files:**
- Modify: `setup_native_host.py:28-44`
- Test: `tests/test_installer.py`
- Test: `tests/test_popup_webui.py`

- [ ] **Step 1: Write test for multi-browser installation when `--browser` is omitted**

In `tests/test_installer.py`, add a test for `setup_native_host.main()`:
```python
def test_setup_native_host_cli_defaults_to_all_browsers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import setup_native_host

    installed_targets: list[str | None] = []

    def mock_install_manifest(**kwargs: Any) -> list[Path]:
        installed_targets.append(kwargs.get("browser"))
        return [tmp_path / "mock_manifest.json"]

    monkeypatch.setattr(setup_native_host, "install_manifest", mock_install_manifest)
    exit_code = setup_native_host.main(["--extension-id", "abcdefghijklmnopqrstuvwxyzabcdef"])
    assert exit_code == 0
    assert installed_targets == [None]
```

- [ ] **Step 2: Update `setup_native_host.py`**

Change default of `--browser` from `"google-chrome"` to `None`, and pass `browser=args.browser`:
```python
    parser.add_argument(
        "--browser",
        default=None,
        help="Target browser family (default: install across all detected browsers).",
    )
    args = parser.parse_args(argv)

    ext_id = str(args.extension_id).strip()
    native_host_script = Path(__file__).resolve().parent / "src" / "mcp_gateway" / "host" / "native_host.py"
    try:
        manifest_paths = install_manifest(
            host_path=native_host_script,
            extension_id=ext_id,
            browser=args.browser,
        )
```

- [ ] **Step 3: Run installer and setup tests**

Run:
```bash
taskset -c 0-5 pytest tests/test_installer.py -v
```
Expected: PASS.

---

### Task 9: Defect 9 [LOW] — Systemd Service Quoting & Path Documentation Alignment

**Files:**
- Modify: `docs/client-configuration.md:14,16,201-208,225`

- [ ] **Step 1: Inspect and update `docs/client-configuration.md`**

1. In the topology diagram (lines 14, 16):
   Change:
   `│ (Local IPC: $XDG_RUNTIME_DIR/broker.sock or Windows Named Pipe, >I)`
   To:
   `│ (Local IPC: $XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock or Windows Named Pipe, >I)`

2. In the systemd unit example (lines 201-208):
   Quote paths with spaces:
   ```ini
   [Service]
   Type=simple
   WorkingDirectory="%h/Projects/Google Notebook MCP"
   ExecStart="%h/Projects/Google Notebook MCP/.venv/bin/python3" -m mcp_gateway.cli serve
   Restart=always
   RestartSec=5
   Environment=UV_THREADPOOL_SIZE=3
   Environment=MCP_BROKER_SOCKET=%t/notebooklm-mcp/broker.sock
   ```

3. In verification section (line 225):
   Align verification command with `paths.py`:
   ```bash
   # If XDG_RUNTIME_DIR is set:
   ls -la "${XDG_RUNTIME_DIR:-$HOME/.config/notebooklm-mcp-bridge}/notebooklm-mcp/broker.sock"
   # Fallback if XDG_RUNTIME_DIR is unset:
   ls -la "$HOME/.config/notebooklm-mcp-bridge/broker.sock"
   # Or query gateway directly:
   python3 -c "from mcp_gateway.transport.paths import get_default_ipc_path; print(get_default_ipc_path())"
   ```

- [ ] **Step 2: Verify markdown documentation syntax**

Ensure no syntax errors or formatting breaks in `docs/client-configuration.md`.

---

## Full Suite Quality Gate & Final Verification

Once all 9 remediation tasks are completed, execute the following commands sequentially to confirm 100% compliance:

```bash
# 1. Linting & Style Check
taskset -c 0-5 ruff check .

# 2. Strict Type Safety Check
taskset -c 0-5 mypy --strict

# 3. Full Comprehensive Test Suite Run (all unblocked tests passing)
taskset -c 0-5 pytest tests/ -v
```
