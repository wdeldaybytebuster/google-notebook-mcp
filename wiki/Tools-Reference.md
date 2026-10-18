# Closed 9-Tool MCP Surface Reference

The gateway strictly exposes **nine closed tools** via standard Model Context Protocol (MCP) JSON-RPC 2.0 stdio transport.

All schemas enforce `additionalProperties: false` (JSON Schema) and `extra="forbid"` (Pydantic v2). Any unrecognized parameter returns an immediate `INVALID_ARGUMENT` error envelope.

---

## Tool Catalog Summary

| Tool Name | Lifecycle State | Type | Description |
| :--- | :--- | :--- | :--- |
| `select_notebook` | `DISCOVERY_ONLY` | State Transition | Locks session to a single notebook and saves to `.notebook_mcp.json`. |
| `list_notebooks` | All | Read-Only | Lists allowlisted notebooks and returns project configuration status. |
| `get_notebook_metadata` | `ACTIVE_DISPATCH` | Read-Only | Retrieves full notebook metadata, sources count, and timestamps. |
| `list_sources` | `ACTIVE_DISPATCH` | Read-Only | Lists all ingested sources, document types, and processing states. |
| `query_notebook` | `ACTIVE_DISPATCH` | Grounded Q&A | Streams grounded answers with normalized Unicode citation offsets. |
| `add_source` | `ACTIVE_DISPATCH` | Write Mutation | Ingests text, URLs, Google Drive documents, or binary files via Scotty. |
| `create_note` | `ACTIVE_DISPATCH` | Write Mutation | Creates a user note within the active notebook. |
| `list_notes` | `ACTIVE_DISPATCH` | Read-Only | Lists user notes with loud upstream schema drift detection. |
| `delete_note` | `ACTIVE_DISPATCH` | Write Mutation | Deletes a user note by unique ID. |

---

## 1. `select_notebook`

Enforces ADR-011 single-notebook session lock, transitioning the gateway from `DISCOVERY_ONLY` to `ACTIVE_DISPATCH`.

### Parameters
```json
{
  "notebook_id": "string (optional; UUIDv4 format)",
  "title": "string (optional; human-readable notebook title)",
  "save_for_project": "boolean (optional; default: true)"
}
```
*Note: Exactly one of `notebook_id` or `title` must be provided.*

### Behavior
- Resolves human-readable titles against allowlisted notebooks.
- If `save_for_project` is `true`, persists selection into `.notebook_mcp.json` in the current working directory.
- Subsequent calls during the same session with a different notebook fail with `SESSION_LOCKED`.

---

## 2. `list_notebooks`

Lists notebooks authorized in `allowlist.json`.

### Parameters
```json
{
  "page_size": "integer (optional; default: 20, max: 100)",
  "cursor": "string (optional)"
}
```

### Response
Surfaces `project_config` from `.notebook_mcp.json` and an actionable `user_prompt` directing the AI assistant to confirm notebook selection at the start of each chat session.

---

## 3. `get_notebook_metadata`

Fetches metadata for the active notebook via `rLM1Ne`.

### Parameters
```json
{
  "notebook_id": "string (optional; automatically overwritten by locked session ID)"
}
```

---

## 4. `list_sources`

Lists all sources ingested into the active notebook.

### Parameters
```json
{
  "page_size": "integer (optional; default: 50, max: 100)",
  "cursor": "string (optional)"
}
```

---

## 5. `query_notebook`

Streams grounded natural-language answers backed by notebook citations via `GenerateFreeFormStreamed`.

### Parameters
```json
{
  "question": "string (required)",
  "request_key": "string (required; client-supplied idempotency key)",
  "source_ids": "array of strings (optional; target query to specific sources)"
}
```

### Invariants Enforced
- **Strict Grounding Barrier (M-06):** Returns `UNGROUNDED_RESPONSE` if model output contains zero citations.
- **Scoped Pre-Query Readiness (M-10):** Validates readiness only for targeted `source_ids`.
- **Unicode Citation Normalization (ADR-004):** Converts Google V8 UTF-16 offsets to Unicode code point spans.
- **Mid-Stream Error Deltas (P-01):** Emits `STREAM_SEVERED` frame if transport disconnects mid-stream.

---

## 6. `add_source`

Ingests content into the active notebook.

### Parameters
```json
{
  "idempotency_key": "string (required; unique client token)",
  "source": {
    "type": "text | url | drive | file (required)",
    "title": "string (required for text/file)",
    "content": "string (required for text; raw text body)",
    "url": "string (required for url; http/https or YouTube URL)",
    "doc_id": "string (required for drive; Google Drive document ID)",
    "file_path": "string (required for file; local absolute path)",
    "mime_type": "string (optional; e.g. application/pdf)"
  },
  "wait_until_ready": "boolean (optional; default: false)"
}
```

### Invariants Enforced
- **Pre-Flight Account Identity Guard (P-03):** Asserts active email before dispatching mutations.
- **Scotty 3-Step Resumable Upload (M-02, P-02):** Slices files into $\le 512\text{ KiB}$ chunks with session URL caching and query resumption.
- **Full Jitter Exponential Backoff (ADR-006):** Polls readiness without saturating network.

---

## 7. `create_note`

Creates a user note within the active notebook.

### Parameters
```json
{
  "title": "string (required)",
  "content": "string (required; markdown formatted)",
  "idempotency_key": "string (required)"
}
```

---

## 8. `list_notes`

Lists user notes from the active notebook.

### Parameters
```json
{
  "page_size": "integer (optional; default: 50, max: 100)",
  "cursor": "string (optional)"
}
```

### Invariants Enforced
- **Loud Schema Canary (M-05):** Returns `UPSTREAM_SCHEMA_DRIFT` if upstream array shapes deviate, preventing silent empty list returns.

---

## 9. `delete_note`

Permanently deletes a user note.

### Parameters
```json
{
  "note_id": "string (required)",
  "idempotency_key": "string (required)"
}
```

---

## 🚨 Standard Failure Envelope Contract

All errors across IPC and MCP stdio adhere to the following contract:

```json
{
  "ok": false,
  "error": {
    "code": "ALLOWLIST_DENIED | AUTH_REQUIRED | MUTATION_UNKNOWN | INVALID_ARGUMENT | SESSION_UNLOCKED | SESSION_LOCKED | INTERNAL | NOT_FOUND | STREAM_SEVERED | UPSTREAM_SCHEMA_DRIFT",
    "message": "Human-readable failure description.",
    "retryable": false
  },
  "_meta": {
    "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    "mcp_correlation_id": "client-supplied-request-key"
  }
}
```
