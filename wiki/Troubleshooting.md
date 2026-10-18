# Troubleshooting & Diagnostics Guide

This guide details resolutions for edge hardware constraints, container bridges, and network protocol recovery.

---

## ⚡ First Line of Defense: Automated Re-Onboarding

If anything becomes unresponsive, run the autonomous onboarding orchestrator to re-align socket paths, manifests, and active targets:

```bash
python3 install_and_onboard.py
# or
gemini-notebook-mcp onboard
```

The orchestrator automatically unlinks stale sockets, cleans Chrome lock files, re-synchronizes the extension manifest, and verifies page hydration.

---

## 🔍 Common Symptoms & Diagnostic Runbooks

### 1. ChromeOS / Crostini Garcon Bridge Rejection
* **Symptom:** On Chromebooks running Linux (Crostini), clicking launch opens the outside ChromeOS browser, or `install_and_onboard.py` warns about Garcon.
* **Root Cause:** ChromeOS uses `garcon-url-handler` as the default browser wrapper. The host ChromeOS browser runs in a separate mount/network namespace from the Linux container and cannot reach `/tmp/notebooklm-mcp-broker.sock` or load unpacked extensions from the Crostini filesystem.
* **Resolution:** Use a native Linux Chromium binary inside the container:
  ```bash
  python3 install_and_onboard.py --browser google-chrome-beta
  ```

---

### 2. ChromeOS Wayland / Sommelier Crash
* **Symptom:** Chrome crashes immediately on launch with `exit code 139` or a Wayland compositor lockup.
* **Root Cause:** Chrome's sandboxed zygote process conflicts with the ChromeOS Sommelier Wayland bridge.
* **Resolution:** The orchestrator automatically passes these flags, or add them to your browser launch flags:
  ```bash
  --no-sandbox --no-zygote --disable-dev-shm-usage
  ```

---

### 3. Chrome 137+ / Linux Ignores `--load-extension`
* **Symptom:** Browser opens with an isolated profile, but `chrome://extensions` is empty or the installer hangs waiting for the companion extension.
* **Root Cause:** Modern Chromium security and enterprise policies ignore `--load-extension` CLI flags when launching with clean profiles or `--remote-debugging-port`.
* **Resolution:** 
  `install_and_onboard.py` employs an **Extension-First Gating Protocol**:
  1. It pre-seeds `chrome-profile/Default/Preferences` with Developer mode turned ON.
  2. It launches Chrome pointing directly at `chrome://extensions`.
  3. It automatically copies the `src/extension` folder path to your system clipboard (`wl-copy`, `xclip`, `xsel`, `pbcopy`, `clip`).
  4. If automated injection was restricted, click **Load unpacked** (top-left) and press `Ctrl+V`.
  5. As soon as the service worker registers, the script automatically navigates the browser tab to `https://notebook.google.com/`, ensuring content scripts attach properly.

---

### 4. Stale Socket Deadlock (`ConnectionRefusedError`)
* **Symptom:** Broker or Native Host fails with `ConnectionRefusedError` connecting to `broker.sock`.
* **Root Cause:** A previous broker process crashed or was terminated without unlinking its Unix domain socket file.
* **Resolution:** Unlink the stale socket:
  ```bash
  rm -f /tmp/notebooklm-mcp-broker.sock ~/.config/notebooklm-mcp-bridge/broker.sock $XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock
  ```

---

### 5. Chrome `SingletonLock` Profile Deadlock
* **Symptom:** Browser fails to launch, complaining that profile is already in use.
* **Root Cause:** Stale `SingletonLock`, `SingletonSocket`, or `SingletonCookie` symlinks remain after an unexpected shutdown.
* **Resolution:**
  ```bash
  rm -f ~/.config/notebooklm-mcp-bridge/chrome-profile/Singleton*
  ```

---

### 6. `SESSION_UNLOCKED` Error
* **Symptom:** AI agent returns `SESSION_UNLOCKED` when querying or adding sources.
* **Root Cause:** Under ADR-011, the gateway starts in `DISCOVERY_ONLY` mode. No notebook operation can run until `select_notebook` is called.
* **Resolution:** Instruct your assistant to select a notebook:
  > *"Please select the notebook for this project using select_notebook."*

---

### 7. `SESSION_LOCKED` Error
* **Symptom:** AI agent fails when trying to access a second notebook.
* **Root Cause:** For security containment (preventing prompt injections from hopping between confidential notebooks), each MCP session is locked to exactly one notebook.
* **Resolution:** Restart your AI chat session to unlock the gateway, or run another MCP server instance.

---

### 8. `STREAM_SEVERED` Error Delta
* **Symptom:** Streaming query aborts with `STREAM_SEVERED`.
* **Root Cause:** Upstream transport disconnected before Google sent its completion delimiter.
* **Resolution:** The error is marked `retryable: true`. The AI client can safely re-issue the query with the same `request_key`.

---

### 9. `UPSTREAM_SCHEMA_DRIFT` Canary
* **Symptom:** `list_notes` returns `UPSTREAM_SCHEMA_DRIFT`.
* **Root Cause:** Google changed positional indices in internal `batchexecute` payloads.
* **Resolution:** The gateway fails loudly rather than returning silent empty lists. Check repository issues or update `rpc_templates.py`.

---

## 🩺 Diagnostic Commands

```bash
# Check status of native host and allowlist
gemini-notebook-mcp status

# Test raw connection to broker socket
python3 -c "import socket; s = socket.socket(socket.AF_UNIX); s.connect('/tmp/notebooklm-mcp-broker.sock'); print('Broker socket alive!')"

# View broker logs
tail -n 50 ~/.config/notebooklm-mcp-bridge/broker.log

# View native host stderr log
tail -n 50 ~/.config/notebooklm-mcp-bridge/native_host.log
```
