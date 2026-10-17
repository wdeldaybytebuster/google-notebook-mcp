"""Platform-aware IPC path resolution for POSIX sockets and Windows Named Pipes."""

from __future__ import annotations

import os
from pathlib import Path
import sys

DEFAULT_WINDOWS_PIPE_NAME = r"\\.\pipe\notebooklm-mcp-broker"
DEFAULT_POSIX_SOCKET_NAME = "broker.sock"


def get_default_ipc_path(platform_name: str | None = None) -> str:
    """Resolves the default cross-platform IPC path.

    - Overridden by MCP_BROKER_SOCKET if set.
    - Windows: \\\\.\\pipe\\notebooklm-mcp-broker
    - Linux: $XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock (fallback: ~/.config/notebooklm-mcp-bridge/broker.sock)
    - macOS: ~/Library/Application Support/notebooklm-mcp/broker.sock
    """
    env_override = os.environ.get("MCP_BROKER_SOCKET")
    if env_override:
        return env_override

    plat = (platform_name or sys.platform).lower()

    if plat in ("win32", "windows"):
        return DEFAULT_WINDOWS_PIPE_NAME

    home = Path.home()

    if plat == "darwin":
        base_dir = home / "Library" / "Application Support" / "notebooklm-mcp"
    else:
        xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
        if xdg_runtime:
            base_dir = Path(xdg_runtime) / "notebooklm-mcp"
        else:
            base_dir = home / ".config" / "notebooklm-mcp-bridge"

    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(base_dir, 0o700)
    except OSError:
        pass

    return str(base_dir / DEFAULT_POSIX_SOCKET_NAME)


def get_windows_socket_path(local_appdata: str | None = None) -> str:
    """Resolves the Windows AF_UNIX domain socket path under %LOCALAPPDATA% with length guard."""
    base = local_appdata or os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    sock_dir = Path(base) / "notebooklm-mcp"
    try:
        sock_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    sock_path = str(sock_dir / DEFAULT_POSIX_SOCKET_NAME)
    if len(sock_path) > 108:
        return DEFAULT_WINDOWS_PIPE_NAME
    return sock_path

