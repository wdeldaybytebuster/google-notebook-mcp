# Getting Started with Google Notebook MCP

This guide walks you through setting up and running the **Google Notebook MCP Gateway** on Linux, macOS, or Windows.

---

## Prerequisites

1. **Python 3.11+** installed.
2. **Google Chrome** (v112+ or Chrome Beta) with access to [Google NotebookLM](https://notebooklm.google.com).
3. **AI Coding Client**: Any client supporting Model Context Protocol (MCP) over stdio:
   - [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview)
   - [Cursor](https://cursor.com/)
   - [Windsurf](https://codeium.com/windsurf)
   - [Cline / Roo Code](https://github.com/cline/cline)
   - [Antigravity IDE](https://gemini.google.com) / VS Code with MCP extensions

---

## 3-Minute Quickstart

### Step 1: Clone and Install

```bash
git clone https://github.com/wdeldaybytebuster/google-notebook-mcp.git
cd google-notebook-mcp

# Using pip:
pip install -e .

# Or using uv:
uv sync
```

### Step 2: Register Native Messaging Host

Register the native messaging bridge with your Chrome browser so Chrome and the MCP gateway can communicate:

```bash
# Automated cross-platform registration:
gemini-notebook-mcp install
```
*(On Linux and macOS, this writes the manifest into Chrome's default `NativeMessagingHosts` directory. On Windows, it registers the required registry key under `HKCU\Software\Google\Chrome\NativeMessagingHosts`)*.

### Step 3: Load the Companion Extension in Chrome

1. Open Google Chrome and navigate to `chrome://extensions`.
2. Toggle **Developer mode** on (top-right corner).
3. Click **Load unpacked** (top-left).
4. Select the `src/extension/` directory from this repository.
5. Note the generated **Extension ID** (e.g. `abcdefghijklmnop...`). If different from the default, re-run `gemini-notebook-mcp install --extension-id <YOUR_EXTENSION_ID>`.

### Step 4: Launch the Gateway

Start the background broker and Chrome companion:

```bash
gemini-notebook-mcp launch
```

This launches a dedicated, isolated browser session with the companion extension loaded and starts the local IPC broker daemon.

### Step 5: Authorize Your Notebooks

Run the interactive allowlist wizard to pick which notebooks your AI agents can access:

```bash
gemini-notebook-mcp allowlist seed
```

This presents a numbered list of all your NotebookLM notebooks. Enter the numbers you wish to allowlist for MCP access.

---

## Next Steps

- Configure your AI editor by following the [Client Configuration Guide](client-configuration.md).
- Review all available tools in the [MCP Tools Reference](tools-reference.md).
- Read the [Security Architecture](security.md) to understand how your session tokens remain secure.
