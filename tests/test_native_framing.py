"""Unit tests for native_host framing utilities (FEAT-003)."""

from __future__ import annotations

import struct
from io import BytesIO

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
