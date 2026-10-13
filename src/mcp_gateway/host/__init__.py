"""mcp_gateway.host — Native Messaging Host & IPC Bridge."""

from mcp_gateway.host.installer import (
    generate_manifest,
    install_manifest,
    uninstall_manifest,
)
from mcp_gateway.host.native_host import (
    chunk_message,
    main,
    read_native_message,
    relay_loop,
    write_native_message,
)

__all__ = [
    "chunk_message",
    "generate_manifest",
    "install_manifest",
    "main",
    "read_native_message",
    "relay_loop",
    "uninstall_manifest",
    "write_native_message",
]
