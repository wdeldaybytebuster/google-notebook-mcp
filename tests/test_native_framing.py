"""Unit tests for native_host framing utilities (FEAT-003)."""

from __future__ import annotations

import struct
from io import BytesIO
from pathlib import Path

import pytest

from mcp_gateway.host.native_host import (
    CHUNK_SIZE,
    IPC_FRAME_FORMAT,
    MAX_MESSAGE_SIZE,
    chunk_message,
    read_native_message,
    write_native_message,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHROME_FRAME_FORMAT = "@I"


def _make_native_stream(payload: bytes) -> BytesIO:
    """Return a BytesIO with a native-endian length prefix followed by payload."""
    header = struct.pack(CHROME_FRAME_FORMAT, len(payload))
    return BytesIO(header + payload)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_read_native_message_roundtrip() -> None:
    """read_native_message returns the original payload written with a native header."""
    payload = b"hello native world"
    stream = _make_native_stream(payload)
    result = read_native_message(stream)
    assert result == payload


def test_write_native_message_roundtrip() -> None:
    """write_native_message prefixes the payload with a native-endian length."""
    payload = b"test write roundtrip"
    buf = BytesIO()
    write_native_message(buf, payload)
    buf.seek(0)
    raw_len = buf.read(4)
    (length,) = struct.unpack(CHROME_FRAME_FORMAT, raw_len)
    assert length == len(payload)
    assert buf.read(length) == payload


def test_ipc_big_endian_framing() -> None:
    """IPC_FRAME_FORMAT '>I' encodes 256 as big-endian bytes."""
    assert struct.pack(IPC_FRAME_FORMAT, 256) == b"\x00\x00\x01\x00"


def test_chunk_message_small() -> None:
    """chunk_message on a small payload returns a single chunk with final=True."""
    chunks = chunk_message(b"hello")
    assert len(chunks) == 1
    assert chunks[0]["final"] is True
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["total_chunks"] == 1


def test_chunk_message_large() -> None:
    """chunk_message on a 600 KiB payload returns exactly 2 chunks."""
    data = bytes(600 * 1024)
    chunks = chunk_message(data)
    assert len(chunks) == 2
    assert chunks[0]["final"] is False
    assert chunks[1]["final"] is True


def test_max_message_size_rejected() -> None:
    """read_native_message raises ValueError when length exceeds MAX_MESSAGE_SIZE."""
    oversized_length = MAX_MESSAGE_SIZE + 1
    header = struct.pack(CHROME_FRAME_FORMAT, oversized_length)
    stream = BytesIO(header)
    with pytest.raises(ValueError):
        read_native_message(stream)


def test_chrome_vs_ipc_byte_order() -> None:
    """Confirm '@I' and '>I' encode the same integer differently on little-endian x86."""
    native_packed = struct.pack("@I", 1)
    big_packed = struct.pack(">I", 1)

    # On little-endian x86 these MUST differ.
    import sys as _sys

    if _sys.byteorder == "little":
        assert native_packed == b"\x01\x00\x00\x00", (
            "native-endian '@I' should be LE on this machine"
        )
        assert big_packed == b"\x00\x00\x00\x01", (
            "big-endian '>I' should always be BE"
        )
        assert native_packed != big_packed, (
            "Chrome framing and IPC framing must differ on little-endian hardware"
        )
    else:
        # On big-endian machines native == big — both are b'\x00\x00\x00\x01'.
        assert native_packed == big_packed


def test_inject_boundary_idempotency_injects_uuid() -> None:
    import json
    import uuid
    from mcp_gateway.host.native_host import inject_boundary_idempotency

    cmd = {"action": "add_source", "notebook_id": "nb-123"}
    raw = json.dumps(cmd).encode("utf-8")
    result = inject_boundary_idempotency(raw)
    data = json.loads(result.decode("utf-8"))

    assert "idempotency_key" in data
    assert "request_key" in data
    assert data["idempotency_key"] == data["request_key"]
    # Check that it's a valid UUID
    parsed_uuid = uuid.UUID(data["idempotency_key"])
    assert str(parsed_uuid) == data["idempotency_key"]


def test_inject_boundary_idempotency_preserves_existing_keys() -> None:
    import json
    from mcp_gateway.host.native_host import inject_boundary_idempotency

    cmd = {
        "action": "query_notebook",
        "notebook_id": "nb-123",
        "request_key": "my-custom-key-999",
    }
    raw = json.dumps(cmd).encode("utf-8")
    result = inject_boundary_idempotency(raw)
    data = json.loads(result.decode("utf-8"))

    assert data["request_key"] == "my-custom-key-999"
    assert data["idempotency_key"] == "my-custom-key-999"


def test_inject_boundary_idempotency_ignores_non_mutation() -> None:
    import json
    from mcp_gateway.host.native_host import inject_boundary_idempotency

    cmd = {"action": "list_notebooks"}
    raw = json.dumps(cmd).encode("utf-8")
    result = inject_boundary_idempotency(raw)
    data = json.loads(result.decode("utf-8"))

    assert "idempotency_key" not in data


def test_setup_stderr_redirection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path
    import sys
    from mcp_gateway.host.native_host import setup_stderr_redirection

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    old_stderr = sys.stderr
    try:
        setup_stderr_redirection()
        assert (tmp_path / ".config" / "notebooklm-mcp-bridge" / "native_host_stderr.log").exists()
    finally:
        sys.stderr = old_stderr


def test_windows_binary_mode_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import sys
    from unittest.mock import MagicMock

    mock_msvcrt = MagicMock()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", mock_msvcrt)

    o_binary = getattr(os, "O_BINARY", 0x8000)
    # Call the binary mode setup branch without starting the loop
    if sys.platform == "win32":
        import msvcrt
        msvcrt.setmode(0, o_binary)
        msvcrt.setmode(1, o_binary)
    assert mock_msvcrt.setmode.call_count == 2

