---
name: studio-artifact-harvester
description: Discovers, monitors, and extracts Studio deliverables (Mind Maps, Audio Overviews, Video Overviews, Studio Reports, Briefing Docs, Study Guides) from the Google NotebookLM Studio panel.
---

# Studio Artifact Harvester

Discovers, monitors asynchronous generation, and extracts Studio deliverables without freezing broker event loops or causing edge memory exhaustion.

## When to Use

- When the user asks to list, inspect, or retrieve artifacts from the Studio panel.
- When extracting generated Audio Overviews, Video Overviews, Mind Maps, Reports, or Study Guides.
- When polling asynchronous studio generation operations.

## When NOT to Use

- For standard text chat queries or notebook note creation.
- For managing source documents (use `add_source` or `list_sources` instead).

---

## The Process

### Step 1: Discover Studio Artifacts
1. Invoke `list_artifacts` with optional `artifact_type_filter` (`"AUDIO"`, `"VIDEO"`, `"REPORT"`, `"MIND_MAP"`, `"STUDY_GUIDE"`).
2. Inspect artifact metadata, titles, creation timestamps, and readiness states (`READY`, `GENERATING`, `FAILED`).

### Step 2: Asynchronous Generation Polling (Invariant 1)
1. If an artifact is in `GENERATING` state, obtain its operation handle (`op_art_xxx`).
2. Never block the stdio JSON-RPC stream with synchronous sleep loops.
3. Emit or await standard `notifications/progress` out-of-band notifications.
4. Poll periodically using `get_artifact_metadata` until state transitions to `READY` or `FAILED`.

### Step 3: High-Bandwidth Binary Streaming (Invariant 2)
1. For text/markdown artifacts (Reports, Study Guides, Briefing Docs), invoke `extract_artifact` with `output_format="MARKDOWN"`.
2. For binary media (Audio MP3, Video MP4), stream bytes directly to owner-only (`0o700`) tmpfs files:
   `/tmp/notebooklm-mcp-artifacts/art_<uuid>.<ext>`
3. Bytes must be streamed in $\le 512\text{ KiB}$ slices.
4. Return the opaque file path (`FILE_PATH`) to the client. **NEVER** Base64-encode binary media into JSON-RPC text to prevent `earlyoom` process termination on edge devices.

---

## Operational Rules & Guardrails

- **Fail-Closed loud canaries (Invariant 4)**: Assert tuple length and array signatures before decoding; raise `UPSTREAM_SCHEMA_DRIFT` on anomalous structures.
- **UUIDv4 Path Sanitization**: Ensure all artifact identifiers conform strictly to regex `^[0-9a-fA-F-]{36}$` to prevent directory traversal.
- **Owner-Only Tmpfs Isolation**: Restrict permissions on extracted media files to `0o700` (`-rwx------`).
