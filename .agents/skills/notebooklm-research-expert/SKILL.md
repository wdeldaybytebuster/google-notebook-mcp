---
name: notebooklm-research-expert
description: Executes grounded technical research, multi-source cross-examination, and citation verification against the active Google NotebookLM notebook.
---

# NotebookLM Research Expert

Deep technical research and synthesis grounded strictly in verified sources with coordinate-normalized citations.

## When to Use

- When querying the active notebook for technical architecture, historical decisions, specifications, or code reviews.
- When performing multi-source cross-examination across 10+ sources in a notebook.
- When verifying that findings are cited with exact character offsets.

## When NOT to Use

- For generic coding questions unrelated to the notebook's knowledge base.
- When modifying notebook content (use `add_source` or `create_note` instead).

---

## The Process

### Step 1: Pre-Flight Lock & Target Scoping
1. Verify the session is locked to the target notebook (`select_notebook`).
2. If querying specific documents, list sources (`list_sources`) and inspect row readiness (`status_code == 2`).
3. Enforce **Mitigation M-10**: Only pass verified `source_ids` to Q&A.

### Step 2: Query Execution with Correlation Tracking
1. Generate an explicit, unique `request_key` (UUIDv4) and preserve client correlation (`_meta.mcp_correlation_id`).
2. Dispatch `query_notebook` with targeted `question`, `request_key`, and optional `source_ids`.
3. Set appropriate `timeout_seconds` (clamped to $\le 210$s to respect the MV3 240s service worker ceiling).

### Step 3: Citation Verification & Grounding Check
1. Enforce **Mitigation M-06**: Every response must contain non-empty citation offsets (`citations`).
2. If `citations` is empty, treat the response as ungrounded and fail with `UNGROUNDED_RESPONSE`.
3. Verify that citation spans (`start_char`, `end_char`) have been normalized from JavaScript UTF-16 code units to Unicode character offsets against decoded text.

### Step 4: Circuit-Breaker Governance
1. Cap consecutive tool calls to **maximum 10 calls** per research sequence.
2. If an error occurs, retry at most **3 times** using Full Jitter Exponential Backoff.
3. If memory usage approaches the 320 MB safety reserve, pause immediately.

---

## Operational Rules & Guardrails

- **Zero Credential Exposure**: Never log or inspect cookies or session tokens.
- **Fail-Closed Verification**: Uncited claims must not be presented to the user as factual notebook findings.
- **Single-Topic Query Slicing**: When querying across 50+ documents, slice complex multi-part questions into focused, bite-sized inquiries (60–120s execution ceiling) to prevent browser companion timeouts.
