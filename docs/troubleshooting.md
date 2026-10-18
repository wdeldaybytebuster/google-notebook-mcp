# Troubleshooting & FAQs

This guide addresses common setup hurdles, platform quirks, and error recovery procedures for the **Google Notebook MCP Gateway**.

> [!TIP]
> The fastest way to resolve setup and pairing issues is to run the automated onboarding orchestrator:
> ```bash
> python3 install_and_onboard.py
> # or: gemini-notebook-mcp onboard
> ```
> It automatically detects your browser, repairs Native Messaging manifests, clears stale locks, and verifies authentication.

---

## Common Issues & Solutions

### 1. "Specified native messaging host not found"

**Symptoms:**
- The Chrome extension popup or service worker shows an error connecting to `com.mcp.gemini.broker`.
- AI client reports `NATIVE_HOST_NOT_FOUND` or connection refused.

**Remedy:**
1. Run the zero-friction onboarding script to automatically detect your browser and register manifests in both global and profile scopes:
   ```bash
   python3 install_and_onboard.py
   ```
2. For manual registration, verify the manifest file is installed in the location Chrome expects on your platform:
   - **Linux:** `~/.config/google-chrome-beta/NativeMessagingHosts/com.mcp.gemini.broker.json` (or `~/.config/google-chrome/...`, `~/.config/chromium/...`)
   - **macOS:** `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.mcp.gemini.broker.json`
   - **Windows:** Registry key at `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.mcp.gemini.broker` pointing to the manifest file path.
3. Re-run manual installation:
   ```bash
   gemini-notebook-mcp install --extension-id <YOUR_CHROME_EXTENSION_ID>
   ```
4. Ensure `native_host_launcher.py` has execution permissions (`chmod 0700 ~/.config/notebooklm-mcp-bridge/native_host_launcher.py`).

---

### 2. Chrome Extension ID Mismatch & Chrome 137+ Unpacked Blocks

**Symptoms:**
- Native messaging calls fail with `Access denied`.
- On Chrome 137+, command-line `--load-extension` flags are ignored.

**Remedy:**
- `install_and_onboard.py` automatically injects unpacked extensions via CDP `Extensions.loadUnpacked` over a local RFC 6455 WebSocket.
- If the live Extension ID differs from candidate calculations, the script automatically updates `allowed_origins` in `com.mcp.gemini.broker.json` on-the-fly and forces service worker re-connection.
- For manual setups, open `chrome://extensions`, copy the 32-letter Extension ID, and run:
  ```bash
  gemini-notebook-mcp install --extension-id <COPIED_EXTENSION_ID>
  ```

---

### 3. ChromeOS / Crostini Linux Garcon Bypass & Wayland Sommelier

**Symptoms:**
- Connecting to Chrome DevTools or localhost WebSockets fails or hangs inside ChromeOS Linux container.
- Chrome crashes immediately on startup inside Crostini without displaying a window.

**Remedy:**
- **Garcon Rejection:** ChromeOS's Garcon bridge (`garcon-url-handler.desktop`) intercepts loopback traffic and attempts to open the host ChromeOS browser where Crostini Unix domain sockets are unreachable. `install_and_onboard.py` detects and rejects Garcon, prompting you to select a container-local browser (`google-chrome-beta` or `chromium`).
- **Sommelier Zygote Protection:** Containerized Linux kernels on Crostini lack unprivileged user namespaces. The onboarding orchestrator automatically detects `/usr/bin/sommelier` and injects:
  ```bash
  --no-sandbox --no-zygote --disable-dev-shm-usage
  ```
- To set this manually in `.env`:
  ```bash
  CHROME_PATH=/usr/bin/google-chrome-beta
  CHROME_NO_SANDBOX=1
  ```

---

### 4. Windows 108-Character Path Ceiling (`UNIX_PATH_MAX`)

**Symptoms:**
- Windows socket initialization fails with `ValueError: AF_UNIX path too long`.

**Remedy:**
- Windows `AF_UNIX` domain sockets enforce a strict 108-character ceiling in `sockaddr_un`.
- The gateway and onboarding script automatically fall back to Windows Named Pipes (`\\.\pipe\notebooklm-mcp-broker`) when running on Windows.
- If specifying a custom socket path, ensure the full absolute path is $\le 108$ characters or use the named pipe default.

---

### 5. Extension Service Worker Inactivity & Tab Discard

**Symptoms:**
- Long-running file uploads or background queries suddenly return `STREAM_SEVERED` or `TAB_DISCARDED`.

**Remedy:**
- Manifest V3 service workers sleep after ~30 seconds of idle time. The gateway implements continuous 15-second bidirectional `PING`/`PONG` keepalive frames to sustain the channel.
- If your system is low on RAM, Chrome may discard background tabs. The gateway automatically sets `autoDiscardable: false` on the NotebookLM companion tab and drains requests gracefully if eviction occurs.

---

### 6. Broker Socket Permission Denied & Stale Locks

**Symptoms:**
- AI coding agent reports `PermissionDenied` or `ConnectionRefusedError` when connecting to the broker socket.
- Chrome refuses to launch with error mentioning `SingletonLock`.

**Remedy:**
- The broker daemon creates the domain socket with mode `0600` (readable/writable only by your user) in `$XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock` (or `~/.config/notebooklm-mcp-bridge/broker.sock`).
- `install_and_onboard.py` automatically probes the socket; if the socket file exists but refuses connections (unclean daemon exit), it automatically unlinks the stale socket before spawning a fresh daemon.
- It also unlinks stale `SingletonLock`, `SingletonSocket`, and `SingletonCookie` symlinks in `~/.config/notebooklm-mcp-bridge/chrome-profile/` if no Chrome process is running.
- To clean up manually:
  ```bash
  rm -f /tmp/notebooklm-mcp-broker.sock ~/.config/notebooklm-mcp-bridge/broker.sock
  rm -f ~/.config/notebooklm-mcp-bridge/chrome-profile/Singleton*
  gemini-notebook-mcp serve
  ```
