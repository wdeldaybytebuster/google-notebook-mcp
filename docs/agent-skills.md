# Google Notebook MCP — Packaged Agent Skills Ecosystem

The Google Notebook MCP Gateway packages a production-grade **Agent Skills Ecosystem** designed for modern AI coding assistants (Claude Code, Cursor, Windsurf, Cline, Antigravity IDE, and OpenClaw).

Each skill adheres strictly to the OpenClaw / Anthropic Agent Skills specification with standardized `Use when...` triggering conditions, actionable step-by-step procedures, anti-pattern guardrails, and machine-readable `STATE_SCHEMA.yaml` definitions.

---

## 1. Skill Catalog Overview

| Skill Name | Primary Domain | Trigger Condition | State Schema |
| :--- | :--- | :--- | :--- |
| **[`notebooklm-research-expert`](.agents/skills/notebooklm-research-expert/SKILL.md)** | Research & Grounding | `Use when researching technical architecture, cross-examining multiple documents, or querying the active Google Notebook with verified citation grounding.` | Stateless |
| **[`studio-artifact-harvester`](.agents/skills/studio-artifact-harvester/SKILL.md)** | Studio Media & Extraction | `Use when listing, monitoring, or extracting Google NotebookLM Studio panel deliverables (Audio Deep Dives, Video Overviews, Mind Maps, Briefing Docs, Study Guides) without RAM exhaustion.` | `STATE_SCHEMA.yaml` |
| **[`notebook-session-guard`](.agents/skills/notebook-session-guard/SKILL.md)** | Session Lifecycle & RBAC | `Use at the start of any session or task before accessing Google Notebook resources to enforce ADR-011 single-notebook session locking, project binding (.notebook_mcp.json), and RBAC allowlist policies.` | `STATE_SCHEMA.yaml` |
| **[`adversarial-consultation-planner`](.agents/skills/adversarial-consultation-planner/SKILL.md)** | Strategy & Planning | `Use before creating plans or modifying code for complex or undocumented systems to conduct closed-loop consultations with live models, adversarial stress-testing, and remediation invariant synthesis.` | `STATE_SCHEMA.yaml` |

---

## 2. Detailed Skill Workflows

### 2.1 `notebooklm-research-expert`
- **Objective:** Guarantees that all technical research extracted from Google NotebookLM is strictly grounded in verified source documents.
- **Key Invariants Enforced:**
  - **Mitigation M-06 (Grounding Barrier):** If `citations` is empty in a model response, the skill mandates rejecting the answer with `UNGROUNDED_RESPONSE` rather than accepting speculative output.
  - **Single-Topic Query Slicing:** Dispatches focused, bite-sized questions (45–90 seconds) to prevent Chrome Manifest V3 240-second execution kill walls.
  - **Mitigation M-10 (Targeted Source Scoping):** Filters queries by exact `source_ids` so irrelevant sources do not contaminate context.
  - **Unicode Offset Normalization:** Converts JavaScript UTF-16 code units to exact Unicode character spans against decoded text.

### 2.2 `studio-artifact-harvester`
- **Objective:** Discovers, polls, and extracts NotebookLM Studio deliverables (Audio Deep Dives, Video Overviews, Mind Maps, Briefing Docs, Study Guides) safely.
- **Key Invariants Enforced:**
  - **Invariant 1 (Non-Blocking Polling):** Never executes synchronous sleep loops on the main thread; monitors asynchronous generation operations using non-blocking handles and `notifications/progress` frames.
  - **Invariant 2 (Zero-OOM Tmpfs Streaming):** Streams binary media (Audio MP3, Video MP4) in $\le 512\text{ KiB}$ slices directly to owner-only (`0o700`) tmpfs files (`/tmp/notebooklm-mcp-artifacts/art_<uuid>.<ext>`), returning `file_path`. Never Base64-encodes binary media over JSON-RPC text.
  - **Invariant 4 (Loud Schema Canary):** Validates upstream tuple shapes; raises `UPSTREAM_SCHEMA_DRIFT` loudly on unexpected data structures.

### 2.3 `notebook-session-guard`
- **Objective:** Enforces ADR-011 single-notebook session lock governance, project workspace binding, and granular RBAC allowlists.
- **Key Invariants Enforced:**
  - **ADR-011 Conversational Handshake:** Mandates that the AI coding assistant confirm the target notebook with the user at the start of every chat before locking.
  - **Session Lock Transition:** Moves session state from `DISCOVERY_ONLY` to `ACTIVE_DISPATCH`, issuing an HMAC session token and persisting `.notebook_mcp.json`.
  - **Mitigation P-03 (Identity Assertion):** Asserts active Google account identity before mutating RPCs.
  - **RBAC Policy Guard:** Rejects mutating operations on notebooks configured as `READ_ONLY` in `allowlist.json`.

### 2.4 `adversarial-consultation-planner`
- **Objective:** Executes closed-loop consultations with living models (or NotebookLM) to stress-test architectural plans before implementation begins.
- **Key Invariants Enforced:**
  - **Section XI Invariant 1 (Spec vs Plan Decoupling):** Strictly decouples baseline specification (`SPEC_SOURCE_TITLE`) from candidate plan (`CANDIDATE_PLAN_TITLE`), preventing circular self-evaluations.
  - **Tripartite Consultation Lifecycle:** Reconnaissance $\rightarrow$ Round 1 Positive Gap Analysis $\rightarrow$ Round 2 Adversarial Red-Team Stress-Test across 5 core failure domains.
  - **Invariant Synthesis:** Translates every red-team vulnerability into non-negotiable numbered invariants incorporated directly into `implementation_plan.md`.

---

## 3. Installation & Discovery

All four skills are packaged directly inside the repository under `.agents/skills/` and mirrored to `.claude/skills/` and `~/.agents/skills/`:
- **Claude Code:** Auto-discovered from `.claude/skills/` in the workspace root or `~/.claude/skills/`.
- **OpenClaw / Codex:** Auto-discovered from `.agents/skills/` in the workspace root or `~/.agents/skills/`.
- **Antigravity IDE / Cursor:** Referenced via system rules and the MCP Prompts protocol (`prompts/get` for `adversarial_audit`, `synthesize_sources`, etc.).
