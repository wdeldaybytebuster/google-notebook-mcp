"""mcp_gateway.host — Native Messaging Host & IPC Bridge."""

from mcp_gateway.host.native_host import (
    chunk_message,
    main,
    read_native_message,
    relay_loop,
    write_native_message,
)

__all__ = [
    "chunk_message",
    "main",
    "read_native_message",
    "relay_loop",
    "write_native_message",
]
