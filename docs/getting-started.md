# Getting Started with Google Notebook MCP

This guide walks you through setting up and running the **Google Notebook MCP Gateway** on Linux, macOS, or Windows.

---

## Prerequisites

1. **Python 3.11+** installed.
2. **Google Chrome** (v112+ or Chrome Beta) with access to [Google Notebook](https://notebook.google.com) (formerly [NotebookLM](https://notebooklm.google.com)).
3. **AI Coding Client**: Any client supporting Model Context Protocol (MCP) over stdio:
   - [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview)
   - [Cursor](https://cursor.com/)
   - [Windsurf](https://codeium.com/windsurf)
   - [Cline / Roo Code](https://github.com/cline/cline)
   - [Antigravity IDE](https://gemini.google.com) / VS Code with MCP extensions

---

## 🚀 1-Step Quickstart: Zero-Friction Onboarding (Recommended)

The gateway provides an autonomous 6-stage onboarding orchestrator ([`install_and_onboard.py`](../install_and_onboard.py)) built strictly with Python 3.11+ standard library modules. It automates browser selection, manifest registration, broker startup, extension injection, login verification, and allowlist seeding in a single command:

```bash
git clone https://github.com/wdeldaybytebuster/google-notebook-mcp.git
cd google-notebook-mcp

# Run the autonomous onboarding wizard:
python3 install_and_onboard.py

# Or via the CLI if already installed in your environment:
gemini-notebook-mcp onboard
```

### What the Onboarding Script Automates
1. **Stage 1 (Browser Selection)**: Detects your OS default browser against a 6-browser registry (`google-chrome-beta`, `google-chrome`, `chromium`, `brave`, `edge`, `edge-beta`). Automatically detects and rejects ChromeOS `garcon-url-handler` bridges, and auto-injects Wayland/Sommelier flags (`--no-sandbox --no-zygote --disable-dev-shm-usage`) on Crostini. Persists `CHROME_PATH` to `.env`.
2. **Stage 2 (Manifest Registration)**: Computes candidate extension IDs and registers `com.mcp.gemini.broker.json` in global browser config directories and isolated profile directories (including Windows Registry). Bakes the resolved socket path and resource caps (`UV_THREADPOOL_SIZE=3`) into the launcher wrapper.
3. **Stage 3 (Broker & Browser Launch)**: Cleans stale sockets and `SingletonLock` symlinks, starts the Policy Broker daemon (`mcp_gateway.cli serve`), pre-seeds Chrome's profile preferences with Developer mode enabled, and launches Chrome directly at `chrome://extensions` with CDP remote debugging (`port 9222`).
4. **Stage 4 (Extension Injection & Verification Gate)**: Injects the companion extension via CDP `Extensions.loadUnpacked` or guides 1-click manual loading with automatic folder path clipboard assist. Detects the active Extension ID from `/json`, synchronizes manifests, and forces service worker re-connection.
5. **Stage 5 (NotebookLM Navigation & Sign-In Hydration)**: Automatically navigates the active browser tab to `notebook.google.com` with the companion extension already active. Monitors Google sign-in and polls `window.WIZ_global_data.SNlM0e` (CSRF) and `oM1Kwf` (account email) in the page's MAIN world to verify login without ever reading cookies.
6. **Stage 6 (Discovery & Allowlist Seeding)**: Queries all visible notebooks using Google's live `wXbhsf` wire payload, presents a numbered selection table, atomically persists `allowlist.json` with `0o600` permissions and multi-account isolation, and binds `.notebook_mcp.json` in the project root.

---

## Manual Step-by-Step Setup (Alternative)

If you prefer to configure each component manually:

### Step 1: Install Dependencies

```bash
# Using pip:
pip install -e .

# Or using uv:
uv sync
```

### Step 2: Register Native Messaging Host

Register the native messaging bridge with your Chrome browser:

```bash
gemini-notebook-mcp install
```
*(On Linux and macOS, this writes the manifest into Chrome's `NativeMessagingHosts` directory. On Windows, it registers the required registry key under `HKCU\Software\Google\Chrome\NativeMessagingHosts`)*.

### Step 3: Load the Companion Extension in Chrome

1. Open Google Chrome and navigate to `chrome://extensions`.
2. Toggle **Developer mode** on (top-right corner).
3. Click **Load unpacked** (top-left).
4. Select the `src/extension/` directory from this repository.
5. Note the generated **Extension ID** (e.g. `abcdefghijklmnop...`). If different from the default, re-run `gemini-notebook-mcp install --extension-id <YOUR_EXTENSION_ID>`.

### Step 4: Launch the Gateway

Start the background broker and dedicated Chrome companion:

```bash
gemini-notebook-mcp launch
```

### Step 5: Authorize Your Notebooks

Run the interactive allowlist wizard to pick which notebooks your AI agents can access:

```bash
gemini-notebook-mcp allowlist seed
```

---

## Next Steps

- Configure your AI editor by following the [Client Configuration Guide](client-configuration.md).
- Review all available tools in the [MCP Tools Reference](tools-reference.md).
- Read the [Security Architecture](security.md) to understand how your session tokens remain secure.
- Browse the [Online GitHub Wiki](https://github.com/wdeldaybytebuster/google-notebook-mcp/wiki) or local [`wiki/`](../wiki/) for additional guides and interactive walkthroughs.
- Inspect the [GitHub Launch Completion Report](github-launch-completion-report.md) for full audit records and verification ledgers.
