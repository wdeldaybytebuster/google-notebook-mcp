# Google Gemini Notebook MCP — Client Configuration Guide

This guide details drop-in setup configurations for AI coding environments connecting to the **Google Gemini Notebook MCP Server** via standard MCP stdio JSON-RPC 2.0.

---

## 1. Prerequisites & Topology

The Google Notebook MCP operates on a 5-tier zero-raw-cookie bridge:
```
[Client (AI Agent)] 
       │ (stdio JSON-RPC)
[Tier 2: MCP Facade (`cli.py mcp`)]
       │ (Local IPC: $XDG_RUNTIME_DIR/broker.sock or Windows Named Pipe, >I)
[Tier 2: Broker Daemon (`cli.py serve`)]
       │ (Local IPC: $XDG_RUNTIME_DIR/broker.sock or Windows Named Pipe, >I)
[Tier 3: Native Messaging Host (`native_host.py`)]
       │ (Chrome stdio framing: @I, chunked 512 KiB)
[Tier 4: Browser Companion Extension (MV3)]
       │ (fetch() credentials: "include" in MAIN world)
[Tier 5: Google NotebookLM (notebook.google.com)]
```

### Automated 1-Step Setup (Recommended)
Run the automated onboarding orchestrator to complete all extension, manifest, broker, and allowlist setup in one pass:
```bash
python3 install_and_onboard.py
# or: gemini-notebook-mcp onboard
```

### Manual Pre-requisites Checklist
If configuring manually:
1. **Chrome Extension Loaded**: Unpacked extension in `src/extension/` loaded into Google Chrome (`chrome://extensions` with Developer Mode enabled). Note your Extension ID (e.g. `abcdefghijklmnop...`).
2. **Native Messaging Host Registered**:
   ```bash
   python3 -m mcp_gateway.cli install --extension-id <YOUR_EXTENSION_ID>
   ```
3. **Broker Daemon Running**:
   ```bash
   python3 -m mcp_gateway.cli serve
   ```
4. **Notebook Allowlist Configured**:
   Ensure notebook IDs are present in `~/.config/notebooklm-mcp-bridge/allowlist.json`.

---

## 2. Drop-In Client Configurations

### A. Antigravity IDE
Place configuration in `~/.gemini/antigravity-ide/mcp_config.json` or project-level `.gemini/config/mcp_config.json`:

```json
{
  "mcpServers": {
    "gemini-notebook": {
      "command": "python3",
      "args": [
        "-m",
        "mcp_gateway.cli",
        "mcp"
      ],
      "env": {
        "MCP_BROKER_SOCKET": "/tmp/notebooklm-mcp-broker.sock",
        "UV_THREADPOOL_SIZE": "3"
      }
    }
  }
}
```

*Verification:* Open Antigravity IDE MCP Servers panel; `gemini-notebook` will report 9 registered tools (`select_notebook`, `list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`, `create_note`, `list_notes`, `delete_note`).

---

### B. Antigravity CLI (`agy`)
Register via `agy` command line:

```bash
agy mcp add gemini-notebook -- command "python3" "-m" "mcp_gateway.cli" "mcp"
```

Or configure via `config/clients/antigravity_cli.json`:
```json
{
  "name": "gemini-notebook",
  "command": "python3",
  "args": ["-m", "mcp_gateway.cli", "mcp"],
  "env": {
    "MCP_BROKER_SOCKET": "/tmp/notebooklm-mcp-broker.sock",
    "UV_THREADPOOL_SIZE": "3"
  }
}
```

*Verification:*
```bash
agy mcp list
```

---

### C. Claude Code
Register via CLI command:

```bash
claude mcp add gemini-notebook python3 -- -m mcp_gateway.cli mcp
```

Or add directly to `~/.claude.json` or `.claude.json`:

```json
{
  "mcpServers": {
    "gemini-notebook": {
      "command": "python3",
      "args": [
        "-m",
        "mcp_gateway.cli",
        "mcp"
      ],
      "env": {
        "MCP_BROKER_SOCKET": "/tmp/notebooklm-mcp-broker.sock",
        "UV_THREADPOOL_SIZE": "3"
      }
    }
  }
}
```

*Verification:*
```bash
claude mcp list
```

---

### D. Cursor
Add to `~/.cursor/mcp.json` or `.cursor/mcp.json` within your workspace:

```json
{
  "mcpServers": {
    "gemini-notebook": {
      "command": "python3",
      "args": [
        "-m",
        "mcp_gateway.cli",
        "mcp"
      ],
      "env": {
        "MCP_BROKER_SOCKET": "/tmp/notebooklm-mcp-broker.sock",
        "UV_THREADPOOL_SIZE": "3"
      }
    }
  }
}
```

*Verification:* Navigate to Cursor Settings > Features > MCP. Verify the green active status indicator next to `gemini-notebook`.

---

### E. Windsurf
Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "gemini-notebook": {
      "command": "python3",
      "args": [
        "-m",
        "mcp_gateway.cli",
        "mcp"
      ],
      "env": {
        "MCP_BROKER_SOCKET": "/tmp/notebooklm-mcp-broker.sock",
        "UV_THREADPOOL_SIZE": "3"
      }
    }
  }
}
```

*Verification:* In Windsurf Cascade, inspect MCP tools and verify tools under `gemini-notebook`.

---

## 3. Background Daemon Management (systemd service)

For persistent background operation on Linux/Debian/ChromeOS Crostini, create a systemd user unit at `~/.config/systemd/user/gemini-notebook-mcp.service`:

```ini
[Unit]
Description=Gemini Notebook MCP Broker Daemon
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/Projects/Google Notebook MCP
ExecStart=%h/Projects/Google Notebook MCP/.venv/bin/python3 -m mcp_gateway.cli serve
Restart=always
RestartSec=5
Environment=UV_THREADPOOL_SIZE=3
Environment=MCP_BROKER_SOCKET=/tmp/notebooklm-mcp-broker.sock

[Install]
WantedBy=default.target
```

Enable and start with:
```bash
systemctl --user daemon-reload
systemctl --user enable --now gemini-notebook-mcp.service
```

---

## 4. Verification & Diagnostics

1. **Verify Broker Listening**:
   ```bash
   ls -la /tmp/notebooklm-mcp-broker.sock
   # Must show srw------- (permissions 0o600)
   ```
2. **Verify Native Host Manifest**:
   ```bash
   cat ~/.config/google-chrome/NativeMessagingHosts/com.mcp.gemini.broker.json
   ```
3. **Verify Tool Surface & Session Lifecycle (ADR-011)**:
   The facade exposes 9 closed tools enforcing strict single-notebook isolation:
   - `select_notebook`: Selects and locks the active notebook session (`notebook_id` or `title` required). Generates an HMAC session token and transitions the gateway from `DISCOVERY_ONLY` to `ACTIVE_DISPATCH`. Serialized via `_session_mutex` (M-01).
   - `list_notebooks`: In discovery phase, lists all accessible notebooks matching `allowlist.json`. Once locked, returns only the locked active notebook.
   - `get_notebook_metadata`: Retrieves detailed metadata & sources for the locked notebook.
   - `list_sources`: Returns list of source documents and readiness states for the locked notebook.
   - `query_notebook`: Streams or returns query responses with normalized citations for the locked notebook. Enforces strict grounding barrier (M-06), scoped readiness (M-10), and mid-stream error delta (P-01).
   - `add_source`: Ingests URL, text, YouTube, Drive, or file documents for the locked notebook with pre-flight identity check (P-03) and resumable Scotty upload (P-02).
   - `create_note`: Creates user note via `CYK0Xb` RPC with idempotency journaling.
   - `list_notes`: Lists user notes extracted from `rLM1Ne` row `[0][17]` with loud schema drift canaries (M-05).
   - `delete_note`: Deletes user note via `tGMBJ` RPC with idempotency journaling.

### 5. Interaction Protocol (ADR-011 Session Lifecycle)

To prevent unintentional cross-notebook writes or leakage across multiple notebooks, the gateway enforces a strict two-phase state machine:

1. **Discovery Phase (`DISCOVERY_ONLY`)**:
   - The AI agent calls `list_notebooks` to present available notebooks to the user.
   - If the agent attempts to call `get_notebook_metadata`, `list_sources`, `query_notebook`, or `add_source` before locking, the gateway rejects the request with error code `SESSION_UNLOCKED`:
     ```json
     {
       "ok": false,
       "error": {
         "code": "SESSION_UNLOCKED",
         "message": "Gateway locked. You must call select_notebook with a valid notebook_id before any operations can be performed.",
         "retryable": false
       }
     }
     ```

2. **Session Lock (`select_notebook`)**:
   - The user selects the desired notebook.
   - The agent invokes `select_notebook(notebook_id="<UUID>")`.
   - The broker validates the ID against `allowlist.json`, locks the session, generates an HMAC token, and responds:
     ```json
     {
       "ok": true,
       "notebook_id": "<UUID>",
       "token": "<HMAC_SHA256_HEX>",
       "status": "LOCKED"
     }
     ```

3. **Active Dispatch Phase (`ACTIVE_DISPATCH`)**:
   - All subsequent operations (`query_notebook`, `add_source`, `list_sources`, etc.) are securely locked to this notebook.
   - The broker automatically enforces and overwrites `arguments["notebook_id"] = session.locked_notebook_id` on all dispatched calls.
   - If an agent attempts to target a different notebook ID, the broker rejects the mutation with `SESSION_LOCKED`:
     ```json
     {
       "ok": false,
       "error": {
         "code": "SESSION_LOCKED",
         "message": "Session is already locked to notebook_id '...'. Switching to '...' is forbidden.",
         "retryable": false
       }
     }
     ```
   - Calling `list_notebooks` during this phase returns only the locked notebook, maintaining perfect context isolation.

---

## 6. Project-Level Notebook Binding & In-Chat Confirmation Protocol (ADR-017)

To prevent confusion across multiple client projects and eliminate manual notebook selection in every session while maintaining user control, the MCP gateway supports **Project-Level Notebook Binding** via `.notebook_mcp.json`.

### How It Works
1. **Config File Location**: Stored in the workspace root as `.notebook_mcp.json`:
   ```json
   {
     "notebook_id": "00000000-0000-0000-0000-000000000001",
     "title": "Google Notebooks MCP",
     "updated_at": "2026-10-14T12:00:00Z"
   }
   ```
2. **Automatic Guidance on Startup (`SESSION_UNLOCKED`)**:
   When an AI agent attempts to run a notebook operation before selecting a notebook, the gateway inspects `.notebook_mcp.json` and returns:
   - If `.notebook_mcp.json` exists:
     ```json
     {
       "ok": false,
       "error": {
         "code": "SESSION_UNLOCKED",
         "message": "Gateway locked. This project is configured to use notebook 'Google Notebooks MCP' (UUID). Please ask the user to confirm: 'This project is set to use notebook \"Google Notebooks MCP\". Would you like to use this notebook, or select another from list_notebooks?' Then call select_notebook with save_for_project=true.",
         "retryable": false
       }
     }
     ```
   - If `.notebook_mcp.json` is missing:
     ```json
     {
       "ok": false,
       "error": {
         "code": "SESSION_UNLOCKED",
         "message": "Gateway locked. No default notebook configured. Call list_notebooks to see available notebooks, prompt the user to choose, then call select_notebook with save_for_project=true.",
         "retryable": false
       }
     }
     ```
3. **Discovery Dynamic Prompting (`list_notebooks`)**:
   `list_notebooks` returns `project_config` and `user_prompt`:
   ```json
   {
     "notebooks": [...],
     "project_config": {
       "notebook_id": "00000000-0000-0000-0000-000000000001",
       "title": "Google Notebooks MCP"
     },
     "user_prompt": "This project is currently associated with notebook 'Google Notebooks MCP' (00000000-0000-0000-0000-000000000001). Ask the user: 'Would you like to use \"Google Notebooks MCP\" for this project, or choose a different notebook from the list above?' Once confirmed, call select_notebook with your choice."
   }
   ```
4. **Persistent Project Selection (`select_notebook`)**:
   When calling `select_notebook`:
   - `save_for_project: true` (default): Persists the choice into `.notebook_mcp.json` in the current project root, ensuring future sessions recall this choice.
   - `save_for_project: false`: Locks the current session only without updating `.notebook_mcp.json`.

### Recommended AI Client Prompt Rule (Add to `AGENTS.md`, `.cursorrules`, or System Instructions)

Add the following directive to your AI tool's project instruction file:

```markdown
### NotebookLM MCP Session Initialization Rule
When starting any task that interacts with Google NotebookLM via the `gemini-notebook` MCP:
1. Call `list_notebooks` to check available notebooks and the project default in `.notebook_mcp.json`.
2. Always ask the user to confirm the active notebook before proceeding:
   > "This project is set to use notebook **[Title]**. Would you like to use this notebook, or select another from your allowlist?"
3. Upon confirmation or selection, invoke `select_notebook(notebook_id=..., save_for_project=true)`.
4. Proceed with `query_notebook`, `create_note`, `add_source`, etc.
```


