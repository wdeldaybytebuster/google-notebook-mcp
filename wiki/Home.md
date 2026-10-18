# Welcome to the Google Notebook MCP Gateway Wiki

The **Google Notebook MCP Gateway** provides a high-performance, production-hardened Model Context Protocol (MCP) interface bridging autonomous AI coding assistants (Claude Code, Cursor, Windsurf, Cline, Antigravity) to your private Google Gemini Notebook (`notebook.google.com`) knowledge bases.

---

## 🌟 Core Philosophy: Zero-Credential Export

Traditional scrapers and unauthorized bridges extract session cookies or OAuth tokens, storing them in plain text or forwarding them to cloud LLM providers. 

The Google Notebook MCP Gateway enforces **Zero-Credential Export**:
* **Hardware TPM & DBSC Isolation:** All authenticated HTTP requests execute inside Google Chrome's native network stack via an injected browser companion executing in the MAIN world of `notebook.google.com`.
* **Zero Cookie Export:** Session cookies (`SID`, `HSID`, `SSID`) and CSRF tokens (`SNlM0e`) never cross IPC boundaries and are never saved to disk.
* **Hermetic Native Host:** Decoupled 32-bit native messaging framing keeps Chrome stdio independent from MCP JSON-RPC 2.0 stdio.
* **Secret Scrubbing:** Outbound diagnostic logs and IPC messages are scrubbed in real-time via `secret_scrubber.py`.

---

## 🚀 1-Step Autonomous Onboarding

Bootstrap the entire gateway with a single command from your repository root:

```bash
python3 install_and_onboard.py
```

Or via the installed CLI:
```bash
gemini-notebook-mcp onboard
```

The 6-stage autonomous state machine handles browser discovery, native messaging host manifest registration across global and profile scopes, browser launch with edge resource protections, zero-touch extension injection via CDP, login hydration polling, and interactive allowlist/project binding.

---

## 📚 Wiki Contents

| Document | Description |
| :--- | :--- |
| **[Quickstart](Quickstart)** | Get running in under 2 minutes with automated or manual steps. |
| **[Zero-Friction Onboarding](Zero-Friction-Onboarding)** | Deep dive into the 6-stage autonomous onboarding state machine and CDP engine. |
| **[System Architecture](Architecture)** | Complete systems architecture, decoupled process IPC, and ADR decision log. |
| **[Security & Privacy](Security-and-Privacy)** | Threat model, TPM/DBSC containment, and mutation journaling. |
| **[Tools Reference](Tools-Reference)** | The 9 closed MCP tools, schemas, parameters, annotations, and failure envelopes. |
| **[Client Configuration](Client-Configuration)** | Configuration snippets for Claude Code, Cursor, Windsurf, Cline, and Antigravity. |
| **[Troubleshooting](Troubleshooting)** | Comprehensive recovery steps, ChromeOS Sommelier flags, and diagnostic guides. |

---

## 🛠️ The 9 Closed Production MCP Tools

The gateway exposes a strictly closed catalog of 9 production tools:

1. `select_notebook`: Enforces ADR-011 single-notebook session lock and updates `.notebook_mcp.json`.
2. `list_notebooks`: Decodes allowlisted notebooks via `wXbhsf` RPC records.
3. `get_notebook_metadata`: Fetches full notebook metadata, sources count, and timestamps via `rLM1Ne`.
4. `list_sources`: Lists all ingested sources, document types, and processing states.
5. `query_notebook`: Streams grounded answers with normalized Unicode citation offsets via `GenerateFreeFormStreamed`.
6. `add_source`: Ingests text, URLs, Google Drive documents, or binary files via Scotty resumable uploads.
7. `create_note`: Creates user notes within the active notebook via `CYK0Xb`.
8. `list_notes`: Retrieves user notes with upstream schema anomaly detection via `rLM1Ne`.
9. `delete_note`: Deletes user notes by unique identifier via `tGMBJ`.

---

## 🧭 Hardware & Resource Profile

Engineered to operate reliably under resource-constrained edge environments:
- **CPU Affinity:** Capped to cores 0–5 (`taskset -c 0-5`), reserving cores 6–7 for ChromeOS / Wayland compositor.
- **Node Memory Ceiling:** `NODE_OPTIONS="--max-old-space-size=1024 --max-semi-space-size=128"`.
- **Threadpool Throttling:** `UV_THREADPOOL_SIZE=3`, `OMP_NUM_THREADS=3`.
- **RAM Safety Reserve:** Strict 320MB untouchable safety buffer against `earlyoom` process termination.
