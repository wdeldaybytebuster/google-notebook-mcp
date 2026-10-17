### Code Standards

#### General
* **Single-Purpose Architecture**: Keep modules small, cohesive, and dedicated to a single operational concern. Decouple protocol decoding from network transport.
* **Fix Root Causes, Not Symptoms**: Do not layer speculative workarounds or retry loops over protocol rejections. If Google's wire format changes, trip the `UPSTREAM_DRIFT` circuit breaker.
* **Fail-Closed Default**: Any unverified wire format, missing token, or ambiguous network state must fail closed with a structured error envelope rather than returning ungrounded success.
* **Zero Secret Logging**: Stdio streams, application logs, and error messages must never contain session cookies, CSRF tokens, authorization headers, or raw request forms.

#### Python (Broker & Native Host)
* **Strict Type Safety**: All Python code must be fully type-annotated and pass `mypy --strict`. Use dataclasses with `frozen=True` for immutable payload representations.
* **Standard Library Priority**: Core IPC bridging, framing, and cryptographic hashing must utilize Python standard library modules (`struct`, `json`, `asyncio`, `hashlib`, `hmac`, `sqlite3`) to minimize external dependency bloat.
* **Native Byte-Order Discipline**:
  * Chrome Native Messaging: Read and write 4-byte native-byte-order unsigned integers using `struct.unpack('@I', ...)` and `struct.pack('@I', ...)`.
  * Broker Local IPC: Read and write 4-byte big-endian unsigned integers using `struct.unpack('>I', ...)` and `struct.pack('>I', ...)`.
* **Binary Standard Streams**: Force binary mode on standard input and output streams (`sys.stdin.buffer`, `sys.stdout.buffer`). On Windows platforms, explicitly invoke `msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)`.
* **UTF-16 Coordinate Arithmetic**: Never slice Python strings directly using Google citation offsets. Always normalize via UTF-16 byte conversion:
  ```python
  def utf16_slice(text: str, start: int, end: int) -> str:
      encoded = text.encode("utf-16-le")
      return encoded[start * 2 : end * 2].decode("utf-16-le", errors="replace")
  ```

#### TypeScript & JavaScript (Browser Extension)
* **Manifest V3 Compliance**: Strictly adhere to Chrome Manifest V3 standards. Background execution must reside in `service_worker.js` with keep-alive alarms; Offscreen Documents must not be used for session calls.
* **Execution World Segregation**:
  * `content_script.js`: Runs in ISOLATED world, relays messages between the extension service worker and the page via window `postMessage`.
  * `page-main.js`: Injected into MAIN world via `chrome.scripting.executeScript({ world: 'MAIN' })` to access `window.WIZ_global_data` and execute `fetch()` with credentials.
* **Chunk Sizing & Bounds**: Chrome limits host-to-browser messages to 1 MiB and browser-to-host to 64 MiB. The extension must slice all large payloads (document bytes, long responses) into ~512 KiB frames with sequential indices and terminal flags.
* **Network Header Invariants**: All in-browser `fetch()` calls to batchexecute must include `headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "X-Same-Domain": "1" }` and `credentials: "include"`.

#### MCP Tool Contracts & Schemas
* **Closed JSON Schemas & Pydantic Validation**: Every MCP tool must specify `additionalProperties: false` on JSON schemas and `extra="forbid"` on Pydantic v2 input models to reject unrecognized arguments.
* **Standardized Failure Envelopes**: Errors must return a structured payload matching the contract:
  ```json
  {
    "ok": false,
    "error": {
      "code": "ALLOWLIST_DENIED | AUTH_REQUIRED | MUTATION_UNKNOWN | INVALID_ARGUMENT | SESSION_UNLOCKED | SESSION_LOCKED | INTERNAL | NOT_FOUND | STREAM_SEVERED | UPSTREAM_SCHEMA_DRIFT",
      "message": "Descriptive message",
      "retryable": false
    }
  }
  ```
* **Protocol-Compliant Annotations**:
  * `select_notebook`: `{ readOnlyHint: false, destructiveHint: false, idempotentHint: true }` (transitions gateway from `DISCOVERY_ONLY` to `ACTIVE_DISPATCH`).
  * `list_notebooks`, `get_notebook_metadata`, `list_sources`, `list_notes`: `{ readOnlyHint: true, destructiveHint: false, idempotentHint: true }`.
  * `query_notebook`: `{ readOnlyHint: false, destructiveHint: false, idempotentHint: false }` (consumes quota, appends conversation history).
  * `add_source`, `create_note`: `{ readOnlyHint: false, destructiveHint: false, idempotentHint: false }`.
  * `delete_note`: `{ readOnlyHint: false, destructiveHint: true, idempotentHint: true }`.

#### Data Persistence & Storage
* **SQLite Transaction Discipline**: Every mutation journal state change must execute within an explicit SQLite transaction. Use parameterized queries exclusively—never interpolate SQL strings.
* **HMAC-SHA256 Request Keys**: Idempotency keys must be deterministically generated using an HMAC-SHA256 hash of canonicalized JSON arguments (`sort_keys=True, separators=(',', ':')`) salted with a local capability secret.
* **Vault Backend Allowlist**: Python `keyring` must be configured with an explicit allowlist (`Keyring`, `WinVaultKeyring`, `SecretService.Keyring`). Insecure plaintext file fallbacks must raise `VAULT_LOCKED`.

#### File Organization
* `src/mcp_gateway/broker/` — MCP stdio facade, policy broker daemon, ADR-011 session lock FSM (`session.py`).
* `src/mcp_gateway/transport/` — Universal local IPC transport (`ipc.py`), platform path resolution (`paths.py`).
* `src/mcp_gateway/host/` — Standalone native messaging host (`native_host.py`), multi-browser installer (`installer.py`).
* `src/mcp_gateway/engine/` — Stream parser, UTF-16 coordinate normalizer, readiness polling engine.
* `src/mcp_gateway/schemas/` — 9 closed tool schemas, wire RPC templates, error taxonomy.
* `src/mcp_gateway/storage/` — SQLite schema migrations, mutation journal repository.
* `src/extension/` — `manifest.json`, `service_worker.js`, `content_script.js`, `page-main.js`.
* `config/` — `allowlist.json` template, client drop-in configurations.
* `tests/` — Unit tests, synthetic wire fixtures, integration test runners.
