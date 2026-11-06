---
name: studio-artifact-harvester
description: Use when listing, monitoring, or extracting Google NotebookLM Studio panel deliverables (Audio Deep Dives, Video Overviews, Mind Maps, Briefing Docs, Study Guides) without RAM exhaustion.
allowed-tools:
- list_artifacts
- get_artifact_metadata
- extract_artifact
- select_notebook
metadata:
  category: Deliverables & Media Extraction
  tags:
  - notebooklm
  - studio-artifacts
  - audio-overview
  - tmpfs-streaming
  - non-blocking-polling
---

# Studio Artifact Harvester

Discovers, monitors asynchronous generation, and extracts NotebookLM Studio deliverables without freezing broker event loops or causing edge memory exhaustion.

---

## When to Use

- When the user asks to list, inspect, or retrieve artifacts from the Studio panel (Audio Deep Dives, Video Overviews, Mind Maps, Reports, Study Guides).
- When monitoring background generation of Studio deliverables across polling intervals.
- When safely extracting high-bandwidth binary media (Audio MP3, Video MP4) to local files.

## When NOT to Use

- For standard text Q&A queries against the notebook (use `query_notebook` or `notebooklm-research-expert`).
- For creating or reading personal notes (use `create_note` or `list_notes`).
- For uploading source documents (use `add_source`).

---

## The Process

### Step 1: Discover Studio Deliverables (`list_artifacts`)
1. Ensure the session is locked to the target notebook (`select_notebook`).
2. Invoke `list_artifacts` with optional `artifact_type_filter`:
   - Allowed filters: `"AUDIO"`, `"VIDEO"`, `"REPORT"`, `"MIND_MAP"`, `"STUDY_GUIDE"`, `"ALL"`.
3. Inspect returned entries: `artifact_id`, `title`, `artifact_type`, `created_at`, and `status`:
   - `READY`: Artifact is generated and available for immediate extraction.
   - `GENERATING`: Artifact is actively rendering upstream.
   - `FAILED`: Generation failed upstream.

### Step 2: Asynchronous Generation Polling (Invariant 1)
1. If an artifact is in `GENERATING` state:
   - Extract its operation handle (`op_art_xxx`).
   - **Non-Blocking Invariant:** NEVER block the stdio JSON-RPC stream with synchronous thread sleep loops.
   - Use asynchronous polling intervals: check `get_artifact_metadata` periodically (recommended: 15–30s interval).
   - Emit `notifications/progress` frames to the MCP client UI to inform the user without stalling.
2. If polling exceeds 15 minutes or transitions to `FAILED`, halt and report diagnostic error details.

### Step 3: High-Bandwidth Binary Streaming (Invariant 2)
1. **Text & Markdown Deliverables** (Study Guides, Briefing Docs, Mind Maps):
   - Invoke `extract_artifact` with `output_format="MARKDOWN"`.
   - Content is safely returned as structured text.
2. **Binary Media Deliverables** (Audio MP3, Video MP4):
   - Invoke `extract_artifact`.
   - The gateway streams bytes in $\le 512\text{ KiB}$ IPC slices directly to owner-only (`0o700`) tmpfs storage:
     `/tmp/notebooklm-mcp-artifacts/art_<uuid>.<ext>`
   - The tool returns the local filesystem path (`file_path`), file size in bytes, and MIME type.
   - **Base64 Ban Invariant:** NEVER serialize multi-megabyte binary media into JSON-RPC text strings. This protects edge devices (Chromebook i3-N305, 6.4 GB RAM, zero swap) from `earlyoom` process eviction.

---

## Agent Anti-Patterns & Rationalizations (What to Avoid)

| Rationalization (DO NOT DO) | Correction |
| :--- | :--- |
| *"The audio file is only 5 MB, so I'll just embed it as a base64 string in my response."* | **FORBIDDEN.** Large Base64 payloads cause severe JSON serialization overhead and trigger kernel out-of-memory kills. Always stream to tmpfs and return `file_path`. |
| *"The artifact is generating, so I will run a 60-second synchronous sleep in Python."* | **FORBIDDEN.** Synchronous sleep blocks the broker event loop and starves client keepalive pings. Use non-blocking async checks with progress notifications. |
| *"The upstream array structure changed slightly, but I'll add a silent fallback to ignore it."* | **FORBIDDEN.** Enforce Invariant 4 Loud Failure Canary: If array shapes deviate from expected specifications, raise `UPSTREAM_SCHEMA_DRIFT` immediately. |
| *"I'll use any string as an artifact ID."* | **FORBIDDEN.** All artifact IDs must be validated as UUIDv4 (`^[0-9a-fA-F-]{36}$`) to prevent directory traversal exploits. |

---

## Verification Checklist

Before reporting artifact harvesting results:

- [ ] Target notebook verified and session locked (`select_notebook`).
- [ ] Artifact status verified (`READY` before extraction).
- [ ] For text artifacts: markdown structure decoded and clean.
- [ ] For binary media: file streamed in $\le 512\text{ KiB}$ slices to `/tmp/notebooklm-mcp-artifacts/`.
- [ ] Permissions on extracted files verified as `0o700` (`-rwx------`).
- [ ] Returned payload contains `file_path` and `bytes_written`, zero base64 bloat.
- [ ] Any schema anomalies raised loudly as `UPSTREAM_SCHEMA_DRIFT`.
