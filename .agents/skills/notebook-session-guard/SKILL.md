---
name: notebook-session-guard
description: Enforces ADR-011 single-notebook session lock governance, project workspace binding (.notebook_mcp.json), conversational double-check confirmation, and allowlist RBAC mode enforcement.
---

# Notebook Session Guard

Governs session lifecycle, workspace directory persistence, and zero-trust allowlist policy across all notebook operations.

## When to Use

- At the start of every chat session or task before accessing notebook resources.
- When switching between workspaces or project directories.
- Before executing mutating operations (`add_source`, `create_note`, `delete_note`).

## When NOT to Use

- For routine read-only tool calls once the session lock is established and confirmed.

---

## The Process

### Step 1: Discover Available Notebooks & Project Binding
1. Invoke `list_notebooks` to fetch allowlisted notebooks.
2. Inspect the returned `project_config` from `.notebook_mcp.json` in the current working directory.
3. If configured, read the configured notebook title and ID.

### Step 2: Conversational Double-Check Handshake
1. Always confirm target notebook selection with the human user at the start of a chat:
   *"For this project, we have notebook '<title>' configured. Would you like to use this notebook for this chat, or choose another from the list?"*
2. **Never** silently assume or auto-select a notebook without explicit user confirmation.

### Step 3: Establish ADR-011 Session Lock
1. Once confirmed, invoke `select_notebook` with `notebook_id` or `title` and `save_for_project=true`.
2. Verify state transition from `DISCOVERY_ONLY` to `LOCKED` with an HMAC session token.
3. Validate RBAC permissions (`READ_ONLY` vs `INTERACTIVE`) against `allowlist.json`.

### Step 4: Guard Mutating Dispatches
1. Enforce **Mitigation P-03**: Verify active Google account email matches before initiating mutating RPCs (`add_source`, `create_note`, `delete_note`).
2. If `allowlist.json` designates the notebook as `READ_ONLY`, reject mutating tools immediately with `PERMISSION_DENIED`.

---

## Operational Rules & Guardrails

- **Zero Overwrite of User Vault**: `allowlist.json` and `.notebook_mcp.json` are immutable to background updaters.
- **Fail-Closed Locking**: Any operation attempted prior to `select_notebook` returns `SESSION_UNLOCKED` and is halted.
- **Single-Notebook Exclusivity**: Attempting to switch notebooks mid-session without unlinking returns `SESSION_LOCKED`.
