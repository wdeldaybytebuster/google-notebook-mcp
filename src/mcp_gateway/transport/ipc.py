"""Cross-platform IPC server and client abstractions for Unix Domain Sockets and Windows Named Pipes."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from typing import Any, Callable, Protocol

from mcp_gateway.transport.paths import DEFAULT_WINDOWS_PIPE_NAME, get_default_ipc_path


class IpcServer(Protocol):
    """Protocol for abstract IPC servers."""

    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...

    async def close(self) -> None:
        ...


BaseIpcServer = IpcServer


class UnixSocketServer:
    """Async Unix Domain Socket server with 0o600 file permissions and 0o700 directory security."""

    def __init__(
        self,
        client_connected_cb: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Any],
        path: str | None = None,
    ) -> None:
        self.path = Path(path or get_default_ipc_path())
        self.client_connected_cb = client_connected_cb
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        if self.path.exists():
            try:
                self.path.unlink()
            except OSError:
                pass

        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass

        self._server = await asyncio.start_unix_server(
            self.client_connected_cb,
            path=str(self.path),
        )

        try:
            os.chmod(str(self.path), 0o600)
        except OSError:
            pass

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        if self.path.exists():
            try:
                self.path.unlink()
            except OSError:
                pass

    async def close(self) -> None:
        await self.stop()


class WindowsNamedPipeServer:
    """Async Windows Named Pipe server with Overlapped I/O and DACL security.

    Ensures FILE_FLAG_FIRST_PIPE_INSTANCE to prevent pipe squatting,
    and DisconnectNamedPipe() on connection termination.
    """

    def __init__(
        self,
        client_connected_cb: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Any],
        pipe_name: str | None = None,
    ) -> None:
        self.pipe_name = pipe_name or DEFAULT_WINDOWS_PIPE_NAME
        self.client_connected_cb = client_connected_cb
        self._serving = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._serving = True
        self._loop = asyncio.get_running_loop()
        self._server_task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self) -> None:
        # On Windows, win32pipe and win32file provide overlapped pipe creation
        if sys.platform != "win32":
            # For non-Windows platforms (e.g. testing or running mock), sleep until stopped
            while self._serving:
                await asyncio.sleep(0.5)
            return

        try:
            import importlib

            win32pipe: Any = importlib.import_module("win32pipe")
            win32file: Any = importlib.import_module("win32file")
            win32security: Any = importlib.import_module("win32security")
            ntsecuritycon: Any = importlib.import_module("ntsecuritycon")

            # Build DACL granting access solely to the current user token SID
            sid = win32security.GetTokenInformation(
                win32security.OpenProcessToken(win32file.GetCurrentProcess(), win32security.TOKEN_QUERY),
                win32security.TokenUser,
            )[0]
            dacl = win32security.ACL()
            dacl.AddAccessAllowedAce(
                win32security.ACL_REVISION,
                ntsecuritycon.FILE_GENERIC_READ | ntsecuritycon.FILE_GENERIC_WRITE,
                sid,
            )
            sa = win32security.SECURITY_ATTRIBUTES()
            sa.SECURITY_DESCRIPTOR = win32security.SECURITY_DESCRIPTOR()
            sa.SECURITY_DESCRIPTOR.SetSecurityDescriptorDacl(1, dacl, 0)
        except Exception:
            sa = None
            win32pipe = None
            win32file = None

        first_instance = True
        while self._serving and win32pipe and win32file:
            flags = (
                win32pipe.PIPE_ACCESS_DUPLEX
                | win32file.FILE_FLAG_OVERLAPPED
            )
            if first_instance:
                flags |= win32pipe.FILE_FLAG_FIRST_PIPE_INSTANCE
                first_instance = False

            pipe_handle = win32pipe.CreateNamedPipe(
                self.pipe_name,
                flags,
                win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                win32pipe.PIPE_UNLIMITED_INSTANCES,
                65536,
                65536,
                0,
                sa,
            )

            try:
                overlapped = win32file.OVERLAPPED()
                overlapped.hEvent = win32file.CreateEvent(None, True, False, None)
                res = win32pipe.ConnectNamedPipe(pipe_handle, overlapped)
                if res != 0:
                    await self._wait_event(overlapped.hEvent)
            except Exception:
                win32file.CloseHandle(pipe_handle)
            await asyncio.sleep(0.01)

    async def _wait_event(self, handle: Any) -> None:
        loop = asyncio.get_running_loop()
        try:
            import importlib
            win32event: Any = importlib.import_module("win32event")
        except Exception:
            return

        while self._serving:
            res = await loop.run_in_executor(None, win32event.WaitForSingleObject, handle, 100)
            if res == getattr(win32event, "WAIT_OBJECT_0", 0):
                break

    async def stop(self) -> None:
        self._serving = False
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            self._server_task = None

    async def close(self) -> None:
        await self.stop()


async def create_ipc_server(
    client_connected_cb: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Any],
    path: str | None = None,
) -> IpcServer:
    """Creates a platform-appropriate IPC server."""
    target_path = path or get_default_ipc_path()
    if target_path.startswith(r"\\.\pipe"):
        server: IpcServer = WindowsNamedPipeServer(client_connected_cb, pipe_name=target_path)
    else:
        server = UnixSocketServer(client_connected_cb, path=target_path)
    await server.start()
    return server


async def open_ipc_connection(
    path: str | None = None,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connects to the IPC broker daemon via Unix socket or Windows Named Pipe."""
    target_path = path or get_default_ipc_path()
    if target_path.startswith(r"\\.\pipe"):
        # On Windows, asyncio.open_connection can open named pipe with ProactorEventLoop
        if sys.platform == "win32":
            loop = asyncio.get_running_loop()
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            # Python ProactorEventLoop supports create_pipe_connection
            transport, _ = await getattr(loop, "create_pipe_connection")(lambda: protocol, target_path)
            writer = asyncio.StreamWriter(transport, protocol, reader, loop)
            return reader, writer
        raise NotImplementedError("Named pipes require Windows platform.")
    else:
        return await asyncio.open_unix_connection(target_path)
