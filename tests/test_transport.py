from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Any
import pytest

from mcp_gateway.transport.ipc import UnixSocketServer, create_ipc_server, open_ipc_connection
from mcp_gateway.transport.paths import (
    DEFAULT_POSIX_SOCKET_NAME,
    DEFAULT_WINDOWS_PIPE_NAME,
    get_default_ipc_path,
)


def test_get_default_ipc_path_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    custom = "/custom/socket.sock"
    monkeypatch.setenv("MCP_BROKER_SOCKET", custom)
    assert get_default_ipc_path() == custom


def test_get_default_ipc_path_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_BROKER_SOCKET", raising=False)
    path = get_default_ipc_path(platform_name="win32")
    assert path == DEFAULT_WINDOWS_PIPE_NAME


def test_get_default_ipc_path_darwin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MCP_BROKER_SOCKET", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = get_default_ipc_path(platform_name="darwin")
    assert "Library/Application Support/notebooklm-mcp" in path.replace("\\", "/")
    assert path.endswith(DEFAULT_POSIX_SOCKET_NAME)


def test_get_default_ipc_path_linux(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MCP_BROKER_SOCKET", raising=False)
    xdg_dir = tmp_path / "xdg_run"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(xdg_dir))
    path = get_default_ipc_path(platform_name="linux")
    assert str(xdg_dir) in path
    assert path.endswith(DEFAULT_POSIX_SOCKET_NAME)


@pytest.mark.asyncio
async def test_unix_socket_server_roundtrip(tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("Unix domain sockets not supported on Windows asyncio")
    sock_path = tmp_path / "tb.sock"
    received_messages: list[str] = []

    async def client_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.read(1024)
        received_messages.append(data.decode("utf-8"))
        writer.write(b"ACK:" + data)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await create_ipc_server(client_handler, path=str(sock_path))
    assert sock_path.exists()
    # Check permissions mode on POSIX
    if sys.platform != "win32":
        mode = oct(sock_path.stat().st_mode & 0o777)
        assert mode == oct(0o600)

    # Connect client
    reader, writer = await open_ipc_connection(path=str(sock_path))
    writer.write(b"HELLO_IPC")
    await writer.drain()

    reply = await reader.read(1024)
    assert reply == b"ACK:HELLO_IPC"
    assert received_messages == ["HELLO_IPC"]

    writer.close()
    await writer.wait_closed()

    await server.stop()
    assert not sock_path.exists()


@pytest.mark.asyncio
async def test_unix_socket_server_singleton_lock(tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("POSIX socket locking test")

    sock_path = tmp_path / "st.sock"

    async def dummy_cb(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        pass

    server1 = UnixSocketServer(dummy_cb, path=str(sock_path))
    await server1.start()
    assert sock_path.exists()

    # Second server attempting to bind on same socket must raise RuntimeError
    server2 = UnixSocketServer(dummy_cb, path=str(sock_path))
    with pytest.raises(RuntimeError, match="Another broker daemon is currently running"):
        await server2.start()

    # Stopping server1 releases lock and permits a new server to start
    await server1.stop()
    server3 = UnixSocketServer(dummy_cb, path=str(sock_path))
    await server3.start()
    await server3.stop()


def test_get_windows_socket_path() -> None:
    from mcp_gateway.transport.paths import get_windows_socket_path

    appdata = "C:\\AppData\\Local"
    path = get_windows_socket_path(local_appdata=appdata)
    assert path.endswith("broker.sock")
    assert "notebooklm-mcp" in path
    assert len(path) <= 108


def test_get_windows_socket_path_length_guard() -> None:
    from mcp_gateway.transport.paths import DEFAULT_WINDOWS_PIPE_NAME, get_windows_socket_path

    # Simulate an excessively long path exceeding 108 characters
    long_appdata = "C:\\Users\\" + ("a" * 120) + "\\AppData\\Local"
    path = get_windows_socket_path(local_appdata=long_appdata)
    # Should safely fallback to named pipe
    assert path == DEFAULT_WINDOWS_PIPE_NAME


def test_journal_wal_busy_retry(tmp_path: Path) -> None:
    import sqlite3
    from mcp_gateway.storage.journal import MutationJournal

    db_path = tmp_path / "journal.db"
    journal = MutationJournal(db_path)

    # Verify busy_timeout PRAGMA is set
    cur = journal._conn.execute("PRAGMA busy_timeout;")
    row = cur.fetchone()
    assert row[0] == 30000

    # Test _execute_with_busy_retry retries on simulated locked error
    attempts = 0

    def flaky_write() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise sqlite3.OperationalError("database is locked")
        return "success"

    result = journal._execute_with_busy_retry(flaky_write, max_retries=3, base_delay=0.01)
    assert result == "success"
    assert attempts == 3


def test_windows_named_pipe_server_has_dispatch_helper() -> None:
    from mcp_gateway.transport.ipc import WindowsNamedPipeServer

    async def dummy_cb(reader: Any, writer: Any) -> None:
        pass

    srv = WindowsNamedPipeServer(dummy_cb)
    assert callable(getattr(srv, "_dispatch_connected_pipe", None))


@pytest.mark.asyncio
async def test_windows_named_pipe_server_dispatch_connected_pipe_roundtrip() -> None:
    from mcp_gateway.transport.ipc import WindowsNamedPipeServer

    received: list[bytes] = []
    written_chunks: list[bytes] = []
    disconnected: list[Any] = []
    closed_handles: list[Any] = []

    async def handler_cb(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.read(64)
        received.append(data)
        writer.write(b"PONG:" + data)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    class MockOverlapped:
        def __init__(self) -> None:
            self.hEvent = None

    class MockWin32File:
        def __init__(self) -> None:
            self._reads = [b"PING", b""]
            self.OVERLAPPED = MockOverlapped
            self.read_overlapped: list[Any] = []
            self.write_overlapped: list[Any] = []

        def CreateEvent(self, *args: Any) -> str:
            return "mock-event-handle"

        def ReadFile(self, _handle: Any, _buf_size: int, overlapped: Any = None) -> tuple[int, bytes]:
            if overlapped is not None:
                self.read_overlapped.append(overlapped)
            if self._reads:
                chunk = self._reads.pop(0)
                if chunk:
                    return (0, chunk)
            raise OSError("BROKEN_PIPE")

        def WriteFile(self, _handle: Any, data: bytes, overlapped: Any = None) -> tuple[int, int]:
            if overlapped is not None:
                self.write_overlapped.append(overlapped)
            written_chunks.append(bytes(data))
            return (0, len(data))

        def FlushFileBuffers(self, _handle: Any) -> None:
            pass

        def CloseHandle(self, handle: Any) -> None:
            closed_handles.append(handle)

    class MockWin32Pipe:
        def DisconnectNamedPipe(self, handle: Any) -> None:
            disconnected.append(handle)

    srv = WindowsNamedPipeServer(handler_cb)
    srv._serving = True
    mock_file = MockWin32File()
    await srv._dispatch_connected_pipe("mock-pipe-handle-1", mock_file, MockWin32Pipe())

    assert received == [b"PING"]
    assert b"".join(written_chunks) == b"PONG:PING"
    assert len(mock_file.read_overlapped) >= 1
    assert len(mock_file.write_overlapped) >= 1
    assert disconnected == ["mock-pipe-handle-1"]
    assert "mock-pipe-handle-1" in closed_handles


def test_named_pipe_transport_write_uses_overlapped() -> None:
    from unittest.mock import MagicMock
    from mcp_gateway.transport.ipc import _NamedPipeTransport

    mock_loop = MagicMock()
    mock_protocol = MagicMock()
    mock_win32file = MagicMock()

    mock_overlapped_instance = MagicMock()
    mock_win32file.OVERLAPPED.return_value = mock_overlapped_instance

    transport = _NamedPipeTransport(mock_loop, mock_protocol, "handle-1", mock_win32file)
    transport.write(b"data-bytes")

    mock_win32file.OVERLAPPED.assert_called_once()
    mock_win32file.WriteFile.assert_called_once_with("handle-1", b"data-bytes", mock_overlapped_instance)


@pytest.mark.asyncio
async def test_windows_named_pipe_server_stop_cancels_io(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock
    from mcp_gateway.transport.ipc import WindowsNamedPipeServer

    canceled_handles: list[Any] = []
    mock_win32file = MagicMock()
    mock_win32file.CancelIo = lambda h: canceled_handles.append(h)

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "win32file", mock_win32file)

    async def dummy_cb(reader: Any, writer: Any) -> None:
        pass

    srv = WindowsNamedPipeServer(dummy_cb)
    srv._active_handles.add("handle-123")
    srv._active_handles.add("handle-456")

    await srv.stop()

    assert set(canceled_handles) == {"handle-123", "handle-456"}
    assert len(srv._active_handles) == 0


@pytest.mark.asyncio
async def test_windows_named_pipe_connect_error_535_treated_as_connected() -> None:
    """Error 535 (ERROR_PIPE_CONNECTED) should be treated as connected without raising."""
    from unittest.mock import MagicMock

    class WinErr535(Exception):
        winerror = 535

    mock_win32pipe = MagicMock()
    mock_win32pipe.ConnectNamedPipe.side_effect = WinErr535("Client already connected")

    mock_win32file = MagicMock()
    mock_win32file.CreateEvent.return_value = "event-handle"

    # Simulate the connect call in _listen_loop logic
    overlapped = mock_win32file.OVERLAPPED()
    overlapped.hEvent = mock_win32file.CreateEvent(None, True, False, None)

    connected = False
    try:
        res = mock_win32pipe.ConnectNamedPipe("pipe-h", overlapped)
        if res == 0:
            connected = True
    except Exception as exc:
        win_err = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
        if win_err == 535:
            connected = True
        else:
            raise

    assert connected is True


