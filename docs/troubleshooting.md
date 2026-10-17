# Troubleshooting & FAQs

This guide addresses common setup hurdles, platform quirks, and error recovery procedures for the **Google Notebook MCP Gateway**.

---

## Common Issues & Solutions

### 1. "Specified native messaging host not found"

**Symptoms:**
- The Chrome extension popup or service worker shows an error connecting to `com.mcp.gemini.broker`.
- AI client reports `NATIVE_HOST_NOT_FOUND` or connection refused.

**Remedy:**
1. Verify the manifest file is installed in the location Chrome expects on your platform:
   - **Linux:** `~/.config/google-chrome/NativeMessagingHosts/com.mcp.gemini.broker.json` (or `~/.config/chromium/...`)
   - **macOS:** `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.mcp.gemini.broker.json`
   - **Windows:** Registry key at `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.mcp.gemini.broker` pointing to the manifest file path.
2. Re-run automated installation:
   ```bash
   gemini-notebook-mcp install --extension-id <YOUR_CHROME_EXTENSION_ID>
   ```
3. Ensure the `path` entry inside the JSON manifest points to an existing `native_host.py` file with execution permissions (`chmod +x src/mcp_gateway/host/native_host.py`).

---

### 2. Chrome Extension ID Mismatch

**Symptoms:**
- Native messaging calls fail with `Access denied`.

**Remedy:**
- When loading an unpacked extension in Developer Mode, Chrome assigns an Extension ID based on the directory path or public key.
- Open `chrome://extensions`, copy the exact Extension ID (32 lowercase letters), and update your registration:
  ```bash
  gemini-notebook-mcp install --extension-id <COPIED_EXTENSION_ID>
  ```
- Restart Chrome.

---

### 3. ChromeOS / Crostini Linux Garcon Bypass

**Symptoms:**
- Connecting to Chrome DevTools or localhost WebSockets fails or hangs inside ChromeOS Linux container.

**Remedy:**
- ChromeOS's Garcon daemon intercepts loopback TCP traffic between Crostini and ChromeOS.
- Set `CHROME_PATH=/usr/bin/google-chrome-beta` (or `/usr/bin/google-chrome`) in your `.env` file to ensure the launcher uses the native Linux binary inside Crostini rather than calling out through the Garcon bridge.

---

### 4. Windows 108-Character Path Ceiling (`UNIX_PATH_MAX`)

**Symptoms:**
- Windows socket initialization fails with `ValueError: AF_UNIX path too long`.

**Remedy:**
- Windows `AF_UNIX` domain sockets enforce a strict 108-character ceiling in `sockaddr_un`.
- The gateway automatically falls back to Windows Named Pipes (`\\.\pipe\notebooklm-mcp-broker`) when running on Windows.
- If specifying a custom socket path, ensure the full absolute path is $\le 108$ characters or use the named pipe default.

---

### 5. Extension Service Worker Inactivity & Tab Discard

**Symptoms:**
- Long-running file uploads or background queries suddenly return `STREAM_SEVERED` or `TAB_DISCARDED`.

**Remedy:**
- Manifest V3 service workers sleep after ~30 seconds of idle time. The gateway implements continuous 15-second bidirectional `PING`/`PONG` keepalive frames to sustain the channel.
- If your system is low on RAM, Chrome may discard background tabs. The gateway automatically sets `autoDiscardable: false` on the NotebookLM companion tab and drains requests gracefully if eviction occurs.

---

### 6. Broker Socket Permission Denied

**Symptoms:**
- AI coding agent reports `PermissionDenied` when connecting to `/tmp/notebooklm-mcp-broker.sock`.

**Remedy:**
- The broker daemon creates the domain socket with mode `0600` (readable/writable only by your user).
- Ensure your AI client (e.g. Cursor, Claude Code) is running as the same local OS user as the broker daemon.
- To purge a stale socket from an unclean shutdown:
  ```bash
  rm -f /tmp/notebooklm-mcp-broker.sock
  gemini-notebook-mcp serve
  ```
