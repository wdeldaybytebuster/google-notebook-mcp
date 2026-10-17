"""Transport package for cross-platform IPC and path management."""

from __future__ import annotations

from mcp_gateway.transport.ipc import (
    BaseIpcServer,
    IpcServer,
    UnixSocketServer,
    WindowsNamedPipeServer,
    create_ipc_server,
    open_ipc_connection,
)
from mcp_gateway.transport.paths import (
    DEFAULT_POSIX_SOCKET_NAME,
    DEFAULT_WINDOWS_PIPE_NAME,
    get_default_ipc_path,
    get_windows_socket_path,
)

__all__ = [
    "BaseIpcServer",
    "DEFAULT_POSIX_SOCKET_NAME",
    "DEFAULT_WINDOWS_PIPE_NAME",
    "IpcServer",
    "UnixSocketServer",
    "WindowsNamedPipeServer",
    "create_ipc_server",
    "get_default_ipc_path",
    "get_windows_socket_path",
    "open_ipc_connection",
]
