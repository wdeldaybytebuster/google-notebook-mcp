# Google Gemini Notebook MCP Gateway

A local Model Context Protocol (MCP) gateway that connects AI coding agents (Claude Code, Cursor, Cline, Windsurf) to private [Google NotebookLM](https://notebook.google.com/) knowledge bases — without ever exporting your session credentials.

The gateway runs entirely in your browser's authenticated context via a Manifest V3 Chrome companion extension. All Google session cookies, CSRF tokens, and hardware TPM keys remain inside Chrome's native network stack and are never written to disk, passed over local sockets, or exposed to any MCP client.

## Prerequisites

- **Python 3.11+**
- **Google Chrome** (Manifest V3 support, Chrome 112+)
- **[uv](https://github.com/astral-sh/uv)** package manager

## Quickstart

1. **Install Python dependencies**
   ```bash
   uv sync
   ```

2. **Register the native messaging host**

   Copy the appropriate config template and fill in the placeholder values:
   ```bash
   # Linux
   cp config/native_host_linux.json ~/.config/google-chrome/NativeMessagingHosts/com.mcp.gemini.broker.json

   # macOS
   cp config/native_host_macos.json ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/com.mcp.gemini.broker.json

   # Windows — also add registry key (see config/native_host_windows.json)
   copy config\native_host_windows.json %LOCALAPPDATA%\Google\Chrome\User Data\NativeMessagingHosts\com.mcp.gemini.broker.json
   ```
   Edit the copied file and replace `PLACEHOLDER_ABSOLUTE_PATH_TO_native_host.py` with the real path.

3. **Load the unpacked extension**

   Open `chrome://extensions`, enable Developer Mode, click **Load unpacked**, and select the `src/extension/` directory.
   Copy the generated Extension ID and replace `PLACEHOLDER_EXTENSION_ID` in your native host manifest.

4. **Run the broker daemon**
   ```bash
   uv run python -m mcp_gateway.broker
   ```

5. **Connect your AI coding agent**

   Point your MCP client at the broker's stdio transport. See `config/allowlist.json` to configure which notebooks are accessible.

## MCP Tool Reference

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `list_notebooks` | List visible, allowlisted notebooks | `page_size`, `cursor` |
| `get_notebook_metadata` | Fetch full metadata for a notebook | `notebook_id` |
| `list_sources` | List ingested sources and readiness states | `notebook_id` |
| `query_notebook` | Submit a natural-language query | `question`, `request_key`, `source_ids` |
| `add_source` | Add a new knowledge source | `notebook_id`, `source_type`, payload fields |

## Security Invariants

- **Zero credential export**: Session cookies, CSRF tokens (`SNlM0e`/`at`), and access tokens never leave the browser sandbox.
- **Allowlist enforcement**: Only explicitly allowlisted notebooks are accessible via MCP.
- **Conservative mutation journaling**: All write operations are tracked in an SQLite state machine (`prepared → sent → confirmed / rejected / unknown`). Ambiguous timeouts are never auto-replayed.
- **Isolated HTTP jars**: Streaming query requests use a separate cookie jar to prevent session poisoning from batchexecute `Set-Cookie` responses.
- **Parameterized SQL only**: No string interpolation in any database query.

## License

[MIT License] — placeholder, to be updated.
