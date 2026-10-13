# Google Gemini Notebook MCP — Client Configuration Guide

This guide details drop-in setup configurations for AI coding environments connecting to the **Google Gemini Notebook MCP Server** via standard MCP stdio JSON-RPC 2.0.

---

## 1. Prerequisites & Topology

The Google Notebook MCP operates on a 5-tier zero-raw-cookie bridge:
```
[Client (AI Agent)] 
       │ (stdio JSON-RPC)
[Tier 2: MCP Facade (`cli.py mcp`)]
       │ (Unix socket: /tmp/notebooklm-mcp-broker.sock, >I)
[Tier 2: Broker Daemon (`cli.py serve`)]
       │ (Unix socket: /tmp/notebooklm-mcp-broker.sock, >I)
[Tier 3: Native Messaging Host (`native_host.py`)]
       │ (Chrome stdio framing: @I, chunked 512 KiB)
[Tier 4: Browser Companion Extension (MV3)]
       │ (fetch() credentials: "include" in MAIN world)
[Tier 5: Google NotebookLM (notebook.google.com)]
```

### Pre-requisites Checklist
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

*Verification:* Open Antigravity IDE MCP Servers panel; `gemini-notebook` will report 5 registered tools (`list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`).

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
3. **Verify Tool Surface**:
   The facade exposes exactly 5 closed tools:
   - `list_notebooks`: Lists accessible notebooks matching allowlist
   - `get_notebook_metadata`: Retrieves detailed metadata & sources
   - `list_sources`: Returns list of source documents
   - `query_notebook`: Streams or returns query responses with normalized citations
   - `add_source`: Ingests URL, text, or Drive documents
