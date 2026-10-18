# Security Architecture & Privacy Policy

The **Google Notebook MCP Gateway** is engineered from the ground up around a **Zero-Credential Export** security model.

---

## 🔒 1. Zero-Credential Export

### The Problem
Traditional browser automation libraries and unofficial reverse-engineered APIs extract browser cookies (`SID`, `HSID`, `SSID`) or OAuth refresh tokens (`ya29...`) and save them in plain text configuration files, SQLite caches, or environment variables. If an AI coding assistant prints prompt logs or traces, these credentials can leak directly to third-party model providers, cloud storage, or external logging systems.

Modern Google authentication employs:
- **App-Bound Encryption (ABE):** In Chromium 127+ (Windows) and 130+ (macOS), encryption keys in `Local State` are bound to Chrome's native binary signature via DPAPI COM elevation (`elevation_service`). External binaries cannot decrypt cookies on disk.
- **Device Bound Session Credentials (DBSC):** Cryptographically binds user sessions to hardware Trusted Platform Modules (TPM), requiring cryptographic signatures (`Sec-Session-Response`) on sensitive requests.

### The Architectural Solution
1. **In-Browser Execution:** The gateway never attempts to read cookies from disk or intercept session keys. All HTTP traffic to `notebook.google.com` runs via the browser's native `fetch()` API with `credentials: "include"`.
2. **Hardware Key Retention:** DBSC cryptographic signing occurs transparently inside Chrome's secure network process. Keys never cross process boundaries.
3. **Real-Time Secret Scrubbing:** Every message traversing the local IPC transport is filtered through `secret_scrubber.py`. Accidental matches to Google OAuth tokens, bearer tokens, or cookie headers are immediately replaced with `[REDACTED]`.

---

## 🛑 2. ADR-011 Prompt Injection & Containment Boundary

### The Problem
If an AI coding assistant has unrestricted, open-ended access to all user notebooks, an adversarial prompt injection in a public source repository could instruct the agent to query a confidential notebook (e.g. personal notes or internal corporate docs) and summarize its contents into git commit messages or external endpoints.

### The Defense
1. **Interactive Single-Notebook Session Lock:**
   - The gateway starts in `DISCOVERY_ONLY` state.
   - All operational tools (`get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`, `create_note`, `list_notes`, `delete_note`) strictly reject calls with `SESSION_UNLOCKED`.
   - The user or assistant must explicitly invoke `select_notebook`.
   - Once selected, the gateway generates an HMAC session token and transitions permanently to `ACTIVE_DISPATCH`.
   - Attempts to access or switch to any other notebook return `SESSION_LOCKED`.
2. **Explicit Allowlist Gate:**
   - Even during discovery, the gateway only surfaces notebooks explicitly authorized in `~/.config/notebooklm-mcp-bridge/allowlist.json`.

---

## 🛡️ 3. Conservative Mutation Journaling

### The Problem
In distributed networks, transport disconnects or timeouts during mutating operations (`add_source`, `create_note`, `delete_note`) leave the state unknown: was the mutation received and processed upstream, or did it drop? Automated naive retries cause duplicate notes and duplicate document ingestions.

### The Defense
The gateway maintains an SQLite Write-Ahead Logging (WAL) state machine:
$$\text{PREPARED} \longrightarrow \text{SENT} \longrightarrow \text{CONFIRMED} \;\big|\; \text{REJECTED} \;\big|\; \text{UNKNOWN}$$

- Every write requires a client `idempotency_key`.
- If a disconnect occurs while `SENT`, the record transitions to `UNKNOWN` (`MUTATION_UNKNOWN`).
- Automatic blind retries are permanently frozen until deterministic state reconciliation is performed via `rLM1Ne`.
- Schema migrations use atomic `BEGIN IMMEDIATE TRANSACTION` under `PRAGMA user_version < 2` (M-08).

---

## 👤 4. Multi-Account Identity Isolation (P-03)

In shared Chrome profiles where multiple Google accounts are signed in, the gateway enforces:
1. Dynamic `/u/{N}/` routing extraction and `authuser={N}` query parameters.
2. In-page pre-flight assertion of `window.WIZ_global_data.oM1Kwf` against the expected authorized email before dispatching any mutating RPC.
3. If an account mismatch occurs, the mutation is immediately aborted with `PERMISSION_DENIED`, preventing data from being written to unintended Google accounts.
