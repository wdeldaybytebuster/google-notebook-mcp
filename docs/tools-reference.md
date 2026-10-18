# Google Notebook MCP — Tools Reference

The gateway exposes nine closed tools via standard Model Context Protocol (MCP) JSON-RPC 2.0 stdio transport.

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

### MCP Tool Annotations

Every tool declaration transmits standard Model Context Protocol (MCP) annotations via `list_tools`:
- **Read-only tools** (`list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `list_notes`): Transmit `readOnlyHint: true`, `destructiveHint: false`, and `idempotentHint: true`.
- **Write / Mutating tools** (`add_source`, `create_note`, `delete_note`): Transmit `readOnlyHint: false` and `destructiveHint: true` (for `delete_note`) or `false`, alongside `idempotentHint` hints matching their idempotency key protections.
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

Ingests new material into the notebook.

### Parameters
```json
{
  "idempotency_key": "string (required; unique mutation key)",
  "wait_until_ready": "boolean (default: true)",
  "source": {
    "type": "text | url | youtube | drive | file",
    "content": "string (required for text/url/youtube/drive)",
    "filename": "string (required for file uploads)",
    "file_path": "string (required for local file uploads)"
  }
}
```

### Scotty Resumable File Uploads
Binary files (`.pdf`, `.docx`, `.txt`, `.csv`, `.md`) use Google's 3-step Scotty upload protocol:
1. Intent registration via `o4cbdc` RPC.
2. In-browser session creation with chunked caching (`chrome.storage.session`).
3. Streaming byte transfer in $\le 512\text{ KiB}$ slices with offset recovery.

---

## 7. Note Operations (`create_note`, `list_notes`, `delete_note`)

Allows creating, reading, and removing user notes in NotebookLM.

### `create_note`
- Parameters: `title`, `content`, `idempotency_key`.
- Journaled via SQLite WAL state machine.

### `list_notes`
- Parameters: `page_size`, `cursor`.
- Enforces loud failure canary (`UPSTREAM_SCHEMA_DRIFT`) if Google changes internal array layouts.

### `delete_note`
- Parameters: `note_id`, `idempotency_key`.

---

## Standard Error Envelope Contract

All errors return a deterministic JSON error contract:

```json
{
  "ok": false,
  "error": {
    "code": "ALLOWLIST_DENIED | AUTH_REQUIRED | MUTATION_UNKNOWN | INVALID_ARGUMENT | SESSION_UNLOCKED | SESSION_LOCKED | INTERNAL | NOT_FOUND | STREAM_SEVERED | UPSTREAM_SCHEMA_DRIFT",
    "message": "Human-readable explanation",
    "retryable": false
  },
  "_meta": {
    "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    "mcp_correlation_id": "client-request-id"
  }
}
```
