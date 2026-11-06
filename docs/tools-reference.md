# Google Notebook MCP — Tools & MCP 2025/2026 Protocol Reference

The gateway exposes 12 closed tools, standardized MCP resources (`resources/*`), dynamic prompts (`prompts/*`), progress notifications (`notifications/progress`), and protocol-level logging via standard Model Context Protocol (MCP) JSON-RPC 2.0 stdio transport.

All schemas strictly enforce `additionalProperties: false` (JSON Schema) and `extra="forbid"` (Pydantic v2). Any unrecognized argument immediately returns an `INVALID_ARGUMENT` error envelope.

---

## Tool Summary

| Tool Name | Operation Type | Key Parameters | Purpose |
| :--- | :--- | :--- | :--- |
| `select_notebook` | Session Lock | `notebook_id` or `title`, `save_for_project` | Locks session to a single notebook (ADR-011) and updates `.notebook_mcp.json`. |
| `list_notebooks` | Read-only | `page_size`, `cursor` | Lists allowlisted notebooks and returns project binding status. |
| `get_notebook_metadata` | Read-only | `notebook_id` (auto-overwritten when locked) | Retrieves full notebook metadata, sources count, and timestamps. |
| `list_sources` | Read-only | `notebook_id`, `page_size`, `cursor` | Returns all ingested sources, document types, and readiness states. |
| `query_notebook` | Grounded Q&A | `question`, `request_key`, `source_ids` | Streams grounded answers with normalized Unicode citation offsets. |
| `add_source` | Write Mutation | `source`, `idempotency_key`, `wait_until_ready` | Ingests text, URLs, Google Drive documents, or binary files via Scotty. |
| `create_note` | Write Mutation | `title`, `content`, `idempotency_key` | Creates a new user note within the active notebook. |
| `list_notes` | Read-only | `page_size`, `cursor` | Retrieves user notes with upstream schema anomaly canaries. |
| `delete_note` | Write Mutation | `note_id`, `idempotency_key` | Deletes a user note by its unique identifier. |
| `list_artifacts` | Read-only | `notebook_id`, `artifact_type`, `page_size`, `cursor` | Lists generated studio artifacts (audio overviews, study guides, mind maps, briefings). |
| `get_artifact_metadata` | Read-only | `notebook_id`, `artifact_id` | Fetches generation parameters, readiness state, duration, and download URI. |
| `extract_artifact` | Write/Export | `notebook_id`, `artifact_id`, `destination_path` | Extracts artifact to tmpfs/disk in $\le 512\text{ KiB}$ streams returning `FILE_PATH`. |

### MCP Tool Annotations

Every tool declaration transmits standard Model Context Protocol (MCP) annotations via `tools/list`:
- **Read-only tools** (`list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `list_notes`, `list_artifacts`, `get_artifact_metadata`): Transmit `readOnlyHint: true`, `destructiveHint: false`, and `idempotentHint: true`.
- **Write / Mutating tools** (`add_source`, `create_note`, `delete_note`, `extract_artifact`): Transmit `readOnlyHint: false` and `destructiveHint: true` (for `delete_note`) or `false`, alongside `idempotentHint` hints matching their idempotency key protections.
- **Session management** (`select_notebook`): Transmits `readOnlyHint: false`, `destructiveHint: false`, and `idempotentHint: true`.

---

## 1. `select_notebook`

Enforces ADR-011 single-notebook session lock. Transitions MCP session from `DISCOVERY_ONLY` to `ACTIVE_DISPATCH`.

### Parameters
```json
{
  "notebook_id": "string (optional; UUID format)",
  "title": "string (optional; human-readable title)",
  "save_for_project": "boolean (default: true)"
}
```
*Note: Exactly one of `notebook_id` or `title` must be provided.*

### Behavior
- Resolves fuzzy titles and validates ambiguity.
- If `save_for_project` is `true`, writes or updates `.notebook_mcp.json` in the current project root.
- Re-selecting a different notebook during an active session is blocked with `SESSION_LOCKED`.

---

## 2. `list_notebooks`

Lists allowlisted notebooks visible to the authenticated Google account.

### Parameters
```json
{
  "page_size": "integer (optional; default: 20, max: 100)",
  "cursor": "string (optional; pagination token)"
}
```

### Returns
```json
{
  "notebooks": [
    {
      "notebook_id": "00000000-0000-0000-0000-000000000001",
      "title": "My Knowledge Base",
      "updated_at": 1728800000.0,
      "source_count": 12
    }
  ],
  "project_config": {
    "notebook_id": "00000000-0000-0000-0000-000000000001",
    "title": "My Knowledge Base"
  },
  "user_prompt": "For this project, we have notebook 'My Knowledge Base' configured. Would you like to use this notebook?"
}
```

---

## 3. `get_notebook_metadata`

Fetches comprehensive metadata for the active notebook.

### Parameters
```json
{
  "notebook_id": "string (optional; automatically bound to session notebook)"
}
```

---

## 4. `list_sources`

Lists all sources currently ingested in the notebook, along with parsing and readiness status.

### Parameters
```json
{
  "notebook_id": "string (optional; bound to session)",
  "page_size": "integer (optional)",
  "cursor": "string (optional)"
}
```

### Readiness Enum
- `1`: `PROCESSING` — Source is currently being indexed by Google.
- `2`: `READY` — Source is indexed and available for querying.
- `3`: `FAILED` — Source parsing failed upstream.

---

## 5. `query_notebook`

Executes a natural language query against the notebook knowledge base with grounded citations.

### Parameters
```json
{
  "question": "string (required; natural language query)",
  "request_key": "string (required; client-generated correlation ID)",
  "source_ids": ["array of strings (optional; targeted source filtering)"]
}
```

### Grounding & Coordinate Normalization
- Enforces strict grounding barrier (ADR-006): Answers with zero citations return an `UNGROUNDED_RESPONSE` error.
- All citation offsets are converted from JavaScript UTF-16 code units to exact Unicode character spans (`start_char`, `end_char`).

---

## 6. `add_source`

Ingests new material into the notebook (requires `INTERACTIVE` allowlist mode; blocked with `PERMISSION_DENIED` on `READ_ONLY` notebooks).

### Parameters
```json
{
  "notebook_id": "string (required; automatically bound to locked session notebook)",
  "idempotency_key": "string (required; unique mutation key)",
  "wait_until_ready": "boolean (optional; default: false)",
  "source": {
    "type": "text | url | youtube | drive | file",
    "title": "string (optional; source title or filename for file uploads)",
    "content": "string (optional; pasted text or raw/base64 file content)",
    "url": "string (optional; target URL for url or youtube sources)",
    "doc_id": "string (optional; Google Drive document ID for drive sources)",
    "mime_type": "string (optional; MIME type hint for drive or file sources)"
  }
}
```

### Scotty Resumable File Uploads
Binary files (`.pdf`, `.docx`, `.txt`, `.csv`, `.md`) use Google's 3-step Scotty upload protocol:
1. Intent registration via `o4cbdc` RPC.
2. In-browser session creation routed through `page-main.js` (enforcing P-03 identity preflight) with chunked caching (`chrome.storage.session`).
3. Streaming byte transfer in $\le 512\text{ KiB}$ slices with offset recovery.

---

## 7. Note Operations (`create_note`, `list_notes`, `delete_note`)

Allows creating, reading, and removing user notes in NotebookLM (`create_note` and `delete_note` require `INTERACTIVE` mode; `list_notes` is permitted in both `READ_ONLY` and `INTERACTIVE` modes).

### `create_note`
- Parameters: `notebook_id`, `title` (optional), `content`, `idempotency_key`.
- Journaled via SQLite WAL state machine.

### `list_notes`
- Parameters: `notebook_id`, `page_size`, `cursor`.
- Enforces loud failure canary (`UPSTREAM_SCHEMA_DRIFT`) if Google changes internal array layouts.

### `delete_note`
- Parameters: `notebook_id`, `note_id`, `idempotency_key`.

---

## 8. Studio Artifact Operations (`list_artifacts`, `get_artifact_metadata`, `extract_artifact`)

Allows querying, inspecting, and extracting NotebookLM Studio artifacts (Audio Overviews / Deep Dives, Study Guides, Mind Maps, Briefing Docs, Video Overviews).

### `list_artifacts`
Lists generated studio artifacts in the notebook.
- **Parameters:**
  ```json
  {
    "notebook_id": "string (optional; automatically bound to session)",
    "artifact_type": "string (optional; filter by 'audio', 'study_guide', 'mind_map', 'briefing_doc', 'video', 'all')",
    "page_size": "integer (optional; default: 20)",
    "cursor": "string (optional; pagination token)"
  }
  ```
- **Returns:** List of artifacts including `artifact_id`, `artifact_type`, `title`, `created_at`, `status` (`READY`, `GENERATING`, `FAILED`), and duration/word count.

### `get_artifact_metadata`
Retrieves detailed metadata for a specific artifact.
- **Parameters:**
  ```json
  {
    "notebook_id": "string (optional; automatically bound to session)",
    "artifact_id": "string (required; artifact identifier)"
  }
  ```
- **Returns:** Comprehensive generation parameters, source grounding references, duration seconds (for audio/video), file size bytes, and download readiness.

### `extract_artifact`
Extracts and streams artifact content safely to the local filesystem.
- **Parameters:**
  ```json
  {
    "notebook_id": "string (optional; automatically bound to session)",
    "artifact_id": "string (required; artifact identifier)",
    "destination_path": "string (optional; target path on disk. If omitted, extracts to isolated owner-only tmpfs: /tmp/notebooklm-mcp-artifacts/)"
  }
  ```
- **Stream Invariant:** Binary media (audio/video) streams in $\le 512\text{ KiB}$ IPC chunks and is written directly to disk. The tool returns `{ "status": "extracted", "file_path": "/tmp/...", "bytes_written": 1234567, "mime_type": "audio/mp3" }` preventing OOM exhaustion from large Base64 payloads over stdio.

---

## 9. Standardized MCP Resources (`resources/*`)

The gateway implements the MCP Resources protocol, allowing AI clients to inspect notebook resources directly via standard URI schemes without executing tool calls.

### Dynamic Resource Listing (`resources/list`)
Returns all allowlisted notebooks as browseable MCP resources:
- `notebooklm://notebooks/{nb_id}/metadata`: JSON document of notebook metadata and statistics.
- `notebooklm://notebooks/{nb_id}/sources`: Ingested source inventory.
- `notebooklm://notebooks/{nb_id}/notes`: User notes collection.
- `notebooklm://notebooks/{nb_id}/artifacts`: Studio artifacts collection.

### Resource Templates (`resources/templates/list`)
Provides URI templates:
- `notebooklm://notebooks/{notebook_id}/{resource_type}` (types: `metadata`, `sources`, `notes`, `artifacts`)
- `notebooklm://notebooks/{notebook_id}/{resource_type}/{item_id}`

### Resource Reading (`resources/read`) & Security Interceptor Gate
Enforces **Invariant 3 (Universal Security Interceptor Gate)**:
1. Strict URI regex validation: `^notebooklm://notebooks/([a-zA-Z0-9_\-]+)/([a-zA-Z0-9_\-]+)(?:/([a-zA-Z0-9_\-]+))?$`
2. ADR-011 Session Lock check: Rejects requests with `SESSION_UNLOCKED` if session is not locked.
3. Notebook Lock Identity check: Accessing a notebook other than the locked session notebook returns `SESSION_LOCKED`.
4. Allowlist verification: Unlisted notebooks return `ALLOWLIST_DENIED`.

---

## 10. Standardized MCP Prompts (`prompts/*`)

Exposes curated, parameter-validated prompt templates directly to AI coding assistants:

| Prompt Name | Arguments | Description |
| :--- | :--- | :--- |
| `synthesize_sources` | `topic` (required) | Prompts NotebookLM to synthesize all ingested sources around a specific topic with strict citation grounding. |
| `generate_study_guide` | `focus_area` (optional) | Prompts generation of a structured conceptual study guide and key question breakdown. |
| `extract_action_items` | `scope` (optional) | Directs the notebook to extract actionable milestones, tasks, and deliverables from source transcripts. |
| `adversarial_audit` | `spec_source` (required), `plan_source` (required) | Triggers deep adversarial verification comparing an implementation plan against a baseline specification. |

Clients list prompts via `prompts/list` and retrieve formatted messages with parameter substitution via `prompts/get`.

---

## 11. Progress Notifications (`notifications/progress`)

Long-running operations (such as Scotty resumable byte uploads and readiness polling loops) emit standard MCP `notifications/progress` frames to the client:
```json
{
  "jsonrpc": "2.0",
  "method": "notifications/progress",
  "params": {
    "progressToken": "req-12345",
    "progress": 3,
    "total": 5
  }
}
```
Clients display live upload and polling progress bars in their UI without blocking execution.

---

## Granular Per-Notebook RBAC Modes (`allowlist.json` v2)

Each allowlisted notebook in `~/.config/notebooklm-mcp-bridge/allowlist.json` (configurable live via the Chrome Extension Popup checklist) supports two granular access modes:

| Mode | Permitted Tools | Blocked Tools (`PERMISSION_DENIED`) |
| :--- | :--- | :--- |
| **`READ_ONLY`** | `select_notebook`, `list_notebooks`, `get_notebook_metadata`, `list_sources`, `list_notes`, `list_artifacts`, `get_artifact_metadata`, **`query_notebook`** | `add_source`, `create_note`, `delete_note`, `extract_artifact` |
| **`INTERACTIVE`** | All 12 tools (`select_notebook`, `list_notebooks`, `get_notebook_metadata`, `list_sources`, `list_notes`, `query_notebook`, `add_source`, `create_note`, `delete_note`, `list_artifacts`, `get_artifact_metadata`, `extract_artifact`) | None |

Updates made in the Extension Popup call `update_allowlist` over Native Messaging, atomically saving `allowlist.json` (`0o600`) and invoking `BrokerDaemon.allowlist_config.reload()` inside `_session_mutex` so active sessions enforce permission changes immediately without restarting the daemon.

---

## Standard Error Envelope Contract

All errors return a deterministic JSON error contract:

```json
{
  "ok": false,
  "error": {
    "code": "ALLOWLIST_DENIED | PERMISSION_DENIED | AUTH_REQUIRED | MUTATION_UNKNOWN | INVALID_ARGUMENT | SESSION_UNLOCKED | SESSION_LOCKED | INTERNAL | NOT_FOUND | STREAM_SEVERED | UPSTREAM_SCHEMA_DRIFT",
    "message": "Human-readable explanation",
    "retryable": false
  },
  "_meta": {
    "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    "mcp_correlation_id": "client-request-id"
  }
}
```
