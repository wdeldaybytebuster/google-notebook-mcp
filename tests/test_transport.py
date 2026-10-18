from __future__ import annotations

import asyncio
from pathlib import Path
import sys
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
    assert "Library/Application Support/notebooklm-mcp" in path
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
    sock_path = tmp_path / "test_broker.sock"
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

    sock_path = tmp_path / "singleton_test.sock"

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

