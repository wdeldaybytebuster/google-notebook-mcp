---
name: notebooklm-research-expert
description: Use when researching technical architecture, cross-examining multiple documents, or querying the active Google Notebook with verified citation grounding.
allowed-tools:
- query_notebook
- list_sources
- get_notebook_metadata
- select_notebook
metadata:
  category: Research & Code Intelligence
  tags:
  - notebooklm
  - research
  - citation-grounding
  - multi-source
---

# NotebookLM Research Expert

Deep technical research, multi-source cross-examination, and synthesis grounded strictly in verified NotebookLM sources with coordinate-normalized Unicode citations.

---

## When to Use

- When querying the active notebook for technical architecture, historical decisions, API specifications, or code reviews.
- When performing multi-source cross-examination across 10+ sources in a notebook.
- When verifying that architectural claims are backed by verifiable, character-offset citations.
- When investigating discrepancies between baseline specifications and actual implementation code.

## When NOT to Use

- For generic programming syntax questions that can be answered from local language documentation.
- When writing or mutating notebook content (use `add_source` or `create_note` instead).
- For ungrounded open-world brainstorming where no ingested source material is required.

---

## The Process

### Step 1: Pre-Flight Gating & Scope Resolution
1. Verify the session is locked to the target notebook (`select_notebook`). If unlocked, prompt the user with the configured project default notebook.
2. If research targets specific documents, inspect the source catalog via `list_sources`:
   - Filter by readiness state: assert `status_code == 2` (`READY`).
   - If a targeted source is in state `1` (`PROCESSING`), wait for indexing or notify the user.
3. Enforce **Mitigation M-10**: Pass exact `source_ids` in `query_notebook` to isolate research to targeted documents and eliminate irrelevant noise.

### Step 2: Query Slicing & Execution
1. Generate a unique cryptographic `request_key` (UUIDv4) and preserve client correlation (`_meta.mcp_correlation_id`).
2. **Single-Topic Query Slicing Invariant:**
   - Never dispatch monolithic multi-topic prompts across large knowledge bases.
   - Slice inquiries into focused questions designed to execute in 45–90 seconds (well beneath the MV3 240-second service worker ceiling).
3. Dispatch `query_notebook` with `question`, `request_key`, and targeted `source_ids`.

### Step 3: Citation Verification & Grounding Barrier (Mitigation M-06)
1. Inspect the returned answer and its citation array:
   - **Grounding Barrier Rule:** A response with an empty `citations` list must NEVER be accepted as factual notebook evidence. Reject with `UNGROUNDED_RESPONSE`.
2. Verify coordinate normalization:
   - Offsets must represent exact Unicode character spans (`start_char`, `end_char`) against decoded text, not raw JavaScript UTF-16 code units.
3. Cross-examine claims: If a response references specific configuration flags or numeric constants, verify that the cited span explicitly contains that data.

### Step 4: Circuit-Breaker Governance & Resiliency
1. **Tool Depth Ceiling:** Cap consecutive query dispatches to **maximum 10 calls** per research sequence.
2. **Retry Protocol:** On network or transient failure, retry at most **3 times** using Full Jitter Exponential Backoff (`delay = random.uniform(0, min(base_delay * 2**attempt, max_delay))`).
3. **Hardware Reserve Interlock:** If system memory drops below the 320 MB safety buffer (~5% of RAM), halt research immediately to avoid `earlyoom` eviction.

---

## Agent Anti-Patterns & Rationalizations (What to Avoid)

| Rationalization (DO NOT DO) | Correction |
| :--- | :--- |
| *"The model answer looks accurate and complete, so I will waive the citation requirement."* | **FORBIDDEN.** If `citations` is empty, the response is ungrounded. Treat it as speculative and fail closed (`UNGROUNDED_RESPONSE`). |
| *"I'll send a comprehensive 5-page prompt covering all 8 topics to save turns."* | **FORBIDDEN.** Monolithic prompts trigger Chrome MV3 240s execution ceilings and cause `DISPATCH_ERROR`. Slice into single-topic inquiries. |
| *"I don't need to pass `source_ids`; searching the whole notebook is fine."* | **DISCOURAGED.** When targeting specific files or RFCs, pass `source_ids` to eliminate cross-document contamination. |
| *"I will paste raw Google session cookies into the request headers."* | **STRICTLY FORBIDDEN.** Zero-Credential Export architecture. All authenticated requests must stay inside Chrome's native memory process. |

---

## Verification Checklist

Before presenting research findings to the user or downstream planning agents:

- [ ] Target notebook identity verified and session locked (`select_notebook`).
- [ ] Targeted `source_ids` confirmed in `READY` status (`status_code == 2`).
- [ ] Client `request_key` preserved in `_meta.mcp_correlation_id`.
- [ ] Answer verified to contain non-empty citation spans (`len(citations) > 0`).
- [ ] Unicode citation offsets align with actual source quotation text.
- [ ] Consecutive tool calls kept $\le 10$.
- [ ] Output formatted with explicit source title and citation cross-references.
