# Client Configuration Guide

Configure any MCP-compatible AI coding assistant to communicate with the **Google Notebook MCP Gateway**.

---

## 🧭 Canonical Socket & Command Resolution

The gateway exposes its Model Context Protocol facade via standard input/output (`stdio`) by invoking:

```bash
python3 -m mcp_gateway.cli mcp
```

By default, the gateway connects to the canonical IPC socket:
- **Linux:** `$XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock` (falling back to `~/.config/notebooklm-mcp-bridge/broker.sock` or `/tmp/notebooklm-mcp-broker.sock`).
- **macOS:** `~/Library/Application Support/notebooklm-mcp-bridge/broker.sock` (or `/tmp/notebooklm-mcp-broker.sock`).
- **Windows:** Named Pipe `\\.\pipe\notebooklm-mcp-broker` or restricted user local data directory.

To explicitly point the client to a specific socket, pass the `MCP_BROKER_SOCKET` environment variable.

---

## 1. Claude Code (CLI)

Run in your project directory:

```bash
claude mcp add gemini-notebook -- python3 -m mcp_gateway.cli mcp
```

Or configure via `~/.claude.json`:
```json
{
  "mcpServers": {
    "gemini-notebook": {
      "command": "python3",
      "args": ["-m", "mcp_gateway.cli", "mcp"],
      "env": {
        "MCP_BROKER_SOCKET": "/tmp/notebooklm-mcp-broker.sock",
        "UV_THREADPOOL_SIZE": "3"
      }
    }
  }
}
```

---

## 2. Cursor (`.cursor/mcp.json` or Cursor Settings)

Add to `.cursor/mcp.json` in your workspace root (or Cursor Global MCP Settings):

```json
{
  "mcpServers": {
    "gemini-notebook": {
      "command": "python3",
      "args": ["-m", "mcp_gateway.cli", "mcp"],
      "env": {
        "MCP_BROKER_SOCKET": "/tmp/notebooklm-mcp-broker.sock",
        "UV_THREADPOOL_SIZE": "3"
      }
    }
  }
}
```

---

## 3. Windsurf (`~/.codeium/windsurf/mcp_config.json`)

```json
{
  "mcpServers": {
    "gemini-notebook": {
      "command": "python3",
      "args": ["-m", "mcp_gateway.cli", "mcp"],
      "env": {
        "MCP_BROKER_SOCKET": "/tmp/notebooklm-mcp-broker.sock",
        "UV_THREADPOOL_SIZE": "3"
      }
    }
  }
}
```

---

## 4. Cline / Roo Code (VS Code Extension)

Open the Cline MCP Settings (`settings.json` or Cline UI):

```json
{
  "mcpServers": {
    "gemini-notebook": {
      "command": "python3",
      "args": ["-m", "mcp_gateway.cli", "mcp"],
      "env": {
        "MCP_BROKER_SOCKET": "/tmp/notebooklm-mcp-broker.sock",
        "UV_THREADPOOL_SIZE": "3"
      },
      "disabled": false,
      "autoApprove": [
        "list_notebooks",
        "select_notebook",
        "get_notebook_metadata",
        "list_sources",
        "query_notebook",
        "list_notes"
      ]
    }
  }
}
```

---

## 5. Google Antigravity (IDE & CLI)

### Antigravity IDE
Place configuration in `~/.gemini/antigravity-ide/mcp_config.json`:

```json
{
  "mcpServers": {
    "gemini-notebook": {
      "command": "python3",
      "args": ["-m", "mcp_gateway.cli", "mcp"],
      "env": {
        "MCP_BROKER_SOCKET": "/tmp/notebooklm-mcp-broker.sock",
        "UV_THREADPOOL_SIZE": "3"
      }
    }
  }
}
```

### Antigravity CLI (`agy`)
Register directly via CLI:
```bash
agy mcp add gemini-notebook -- command "python3" "-m" "mcp_gateway.cli" "mcp"
```

---

## 6. Zed Editor (`~/.config/zed/settings.json`)

```json
{
  "context_servers": {
    "gemini-notebook": {
      "command": {
        "path": "python3",
        "args": ["-m", "mcp_gateway.cli", "mcp"],
        "env": {
          "MCP_BROKER_SOCKET": "/tmp/notebooklm-mcp-broker.sock",
          "UV_THREADPOOL_SIZE": "3"
        }
      }
    }
  }
}
```

---

## 📁 Project Directory Binding (`.notebook_mcp.json`)

The gateway supports binding a working directory to a specific notebook:

```json
{
  "notebook_id": "00000000-0000-0000-0000-000000000001",
  "title": "My Project Knowledge Base",
  "updated_at": 1729200000
}
```

When an AI chat starts, the assistant calls `list_notebooks`, detects this file, and confirms with you:
> *"For this project, we have notebook 'My Project Knowledge Base' configured. Would you like to use this notebook for this chat, or choose another from the list?"*
