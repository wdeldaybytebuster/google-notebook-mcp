# Quickstart Guide

This guide gets you up and running with the **Google Notebook MCP Gateway** in under two minutes.

---

## Prerequisites

- **Python 3.11+** installed on your system.
- One of the **6 supported Chromium browsers**:
  - Google Chrome Beta (`google-chrome-beta`) *(Recommended)*
  - Google Chrome Stable (`google-chrome`)
  - Chromium (`chromium`)
  - Brave Browser (`brave`)
  - Microsoft Edge (`edge`)
  - Microsoft Edge Beta (`edge-beta`)
- An active Google account signed into [notebook.google.com](https://notebook.google.com).

---

## 🚀 1-Step Automated Onboarding (Recommended)

Run the autonomous onboarding orchestrator directly from the cloned repository root:

```bash
git clone https://github.com/wdeldaybytebuster/google-notebook-mcp.git
cd google-notebook-mcp

# Run the 6-stage autonomous installer
python3 install_and_onboard.py
```

Or if you installed the package via pip or uv:
```bash
gemini-notebook-mcp onboard
```

### What Happens Automatically (Extension-First Pipeline):
1. **Browser Selection:** Checks your default browser, guards against ChromeOS Garcon bridges, and selects a compatible Chromium binary (with automatic Wayland/Sommelier flags).
2. **Native Messaging Registration:** Automatically writes the Chrome Native Messaging host manifest (`com.mcp.gemini.broker.json`) to both global and profile configuration directories, baking in the socket path and resource limits.
3. **Broker Startup & Developer Mode Pre-Seeding:** Cleans stale socket/lock files, starts the background Policy Broker daemon, pre-seeds `Default/Preferences` with Developer mode enabled, and launches your browser pointing directly to `chrome://extensions`.
4. **Extension Injection & Verification Gate:** Injects the companion extension via CDP `Extensions.loadUnpacked` or prompts 1-click **Load unpacked** with automatic folder path clipboard assist. Detects the active Extension ID and synchronizes manifests.
5. **Seamless Navigation & Login Detection:** Automatically navigates the active browser tab to `https://notebook.google.com/` with the companion extension already active. Content scripts attach immediately on load, and the script polls `window.WIZ_global_data` for CSRF and account hydration.
6. **Notebook Discovery & Allowlisting:** Reads your notebooks via Google's live `wXbhsf` RPC, presents an interactive numbered list, and writes your approved notebooks to `~/.config/notebooklm-mcp-bridge/allowlist.json` and `.notebook_mcp.json`.

---

## 💻 Connect Your AI Client

Once the wizard completes, configure your AI coding agent:

### Claude Code
Run in your project terminal:
```bash
claude mcp add gemini-notebook -- python3 -m mcp_gateway.cli mcp
```

### Cursor (`.cursor/mcp.json` or Settings)
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

### Antigravity IDE
Add to `~/.gemini/antigravity-ide/mcp_config.json`:
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

## 🤝 Project Binding & Conversational Handshake

When starting a chat session in your IDE, your AI agent will detect your project binding from `.notebook_mcp.json` and ask:

> *"For this project, we have notebook 'My Research Notebook' configured. Would you like to use this notebook for this chat, or choose another from the list?"*

Simply reply:
> *"Yes, use the project notebook."*

The assistant invokes `select_notebook`, locking the session into `ACTIVE_DISPATCH` mode and enabling all 9 MCP tools.

---

## 🛠️ Manual Step-by-Step Setup (Fallback)

If you prefer to configure each component manually:

### 1. Install Dependencies
```bash
pip install -e .
# or
uv sync
```

### 2. Register Native Host
```bash
gemini-notebook-mcp install
```

### 3. Load Companion Extension
1. Open Chrome and navigate to `chrome://extensions`.
2. Enable **Developer mode** (top-right toggle).
3. Click **Load unpacked** and select the `src/extension/` directory.
4. If your extension ID differs from the candidate hash, re-register:
   ```bash
   gemini-notebook-mcp install --extension-id <COPIED_EXTENSION_ID>
   ```

### 4. Launch Dedicated Browser & Broker
```bash
gemini-notebook-mcp launch
```

### 5. Seed Allowlist
```bash
gemini-notebook-mcp allowlist seed
```
