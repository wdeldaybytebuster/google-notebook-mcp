"""
Native Messaging Host — standalone IPC bridge.

Translates between:
  - Chrome Native Messaging 32-bit **native-endian** frames (CHROME_FRAME_FORMAT)
  - Broker Unix domain socket 32-bit **big-endian** frames (IPC_FRAME_FORMAT)

Zero imports from mcp_gateway.engine, mcp_gateway.broker, or mcp_gateway.storage.
sys.stdout is ONLY written via write_native_message() — no print() calls.
All diagnostic output goes to sys.stderr.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import struct
import sys
from typing import BinaryIO

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHROME_FRAME_FORMAT: str = "@I"   # native-endian 4-byte unsigned int
IPC_FRAME_FORMAT: str = ">I"      # big-endian 4-byte unsigned int
MAX_MESSAGE_SIZE: int = 1024 * 1024       # 1 MiB — Chrome's hard limit
CHUNK_SIZE: int = 512 * 1024              # 512 KiB slice threshold
IPC_SOCKET_PATH: str = "/tmp/mcp-gemini-broker.sock"

# ---------------------------------------------------------------------------
# Chrome Native Messaging I/O (sync, native-endian)
# ---------------------------------------------------------------------------


def read_native_message(stream: BinaryIO) -> bytes:
    """Read one Chrome Native Messaging frame from *stream*.

    Reads a 4-byte native-endian length header followed by that many payload
    bytes.  Raises EOFError on short read and ValueError when the declared
    length exceeds MAX_MESSAGE_SIZE.
    """
    raw_len = stream.read(4)
    if len(raw_len) < 4:
        raise EOFError("stdin closed — no length header")
    (length,) = struct.unpack(CHROME_FRAME_FORMAT, raw_len)
    if length > MAX_MESSAGE_SIZE:
        raise ValueError(
            f"Message length {length} exceeds MAX_MESSAGE_SIZE {MAX_MESSAGE_SIZE}"
        )
    payload = stream.read(length)
    if len(payload) < length:
        raise EOFError(
            f"Truncated payload: expected {length} bytes, got {len(payload)}"
        )
    return payload


def write_native_message(stream: BinaryIO, data: bytes) -> None:
    """Write one Chrome Native Messaging frame to *stream*.

    Packs len(data) as a 4-byte native-endian header, writes header+data, then
    flushes.  This is the **only** place that writes to sys.stdout.
    """
    header = struct.pack(CHROME_FRAME_FORMAT, len(data))
    stream.write(header + data)
    stream.flush()


# ---------------------------------------------------------------------------
# Broker IPC I/O (async, big-endian)
# ---------------------------------------------------------------------------


async def read_ipc_message(reader: asyncio.StreamReader) -> bytes:
    """Read one broker IPC frame (big-endian length prefix)."""
    raw_len = await reader.readexactly(4)
    (length,) = struct.unpack(IPC_FRAME_FORMAT, raw_len)
    payload = await reader.readexactly(length)
    return payload


async def write_ipc_message(writer: asyncio.StreamWriter, data: bytes) -> None:
    """Write one broker IPC frame (big-endian length prefix) and drain."""
    header = struct.pack(IPC_FRAME_FORMAT, len(data))
    writer.write(header + data)
    await writer.drain()


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def chunk_message(
    data: bytes,
    chunk_size: int = CHUNK_SIZE,
) -> list[dict[str, object]]:
    """Split *data* into sequential frames, each at most *chunk_size* bytes.

    Returns a list of dicts::

        {
            "payload": <base64-encoded str>,
            "chunk_index": <int>,
            "total_chunks": <int>,
            "final": <bool>,
        }

    The last element always has ``final=True``; all others have ``final=False``.
    """
    if len(data) <= chunk_size:
        return [
            {
                "payload": base64.b64encode(data).decode("ascii"),
                "chunk_index": 0,
                "total_chunks": 1,
                "final": True,
            }
        ]

    total_chunks = math.ceil(len(data) / chunk_size)
    chunks: list[dict[str, object]] = []
    for i in range(total_chunks):
        slice_start = i * chunk_size
        slice_end = slice_start + chunk_size
        chunk_bytes = data[slice_start:slice_end]
        chunks.append(
            {
                "payload": base64.b64encode(chunk_bytes).decode("ascii"),
                "chunk_index": i,
                "total_chunks": total_chunks,
                "final": i == total_chunks - 1,
            }
        )
    return chunks


# ---------------------------------------------------------------------------
# Broker connection helpers
# ---------------------------------------------------------------------------


async def connect_to_broker(
    socket_path: str,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open a Unix domain socket connection to the broker.

    Raises ConnectionRefusedError if the broker is not running.
    """
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        raise ConnectionRefusedError(
            f"Broker not reachable at {socket_path!r}: {exc}"
        ) from exc
    return reader, writer


async def validate_origin(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    allowed_extension_id: str,
) -> bool:
    """Perform the HELLO handshake with the broker.

    Sends ``{"type": "hello", "version": 1}`` and waits for a
    ``{"type": "hello_ack", "extension_id": ...}`` reply.  Returns True when
    the ack's extension_id matches *allowed_extension_id*.
    """
    hello_frame = json.dumps({"type": "hello", "version": 1}).encode("utf-8")
    await write_ipc_message(writer, hello_frame)
    raw_ack = await read_ipc_message(reader)
    ack = json.loads(raw_ack.decode("utf-8"))
    return bool(
        ack.get("type") == "hello_ack"
        and ack.get("extension_id") == allowed_extension_id
    )


# ---------------------------------------------------------------------------
# Main relay loop
# ---------------------------------------------------------------------------


async def relay_loop(socket_path: str, allowed_extension_id: str) -> None:
    """Relay messages between Chrome Native Messaging and the broker.

    - Reads native messages from sys.stdin.buffer (run in executor).
    - Forwards them to the broker via big-endian IPC.
    - Reads responses from the broker.
    - Chunks responses and writes each chunk to sys.stdout.buffer via
      write_native_message.

    Never logs message body content; never writes to sys.stdout directly.
    """
    print("connecting to broker", file=sys.stderr)
    reader, writer = await connect_to_broker(socket_path)

    try:
        origin_ok = await validate_origin(
            reader, writer, allowed_extension_id
        )
        if not origin_ok:
            print(
                "Origin validation failed — extension_id mismatch",
                file=sys.stderr,
            )
            return

        print("broker handshake OK", file=sys.stderr)
        loop = asyncio.get_running_loop()

        while True:
            # Read from Chrome stdin in a thread pool to avoid blocking the loop.
            try:
                raw_msg = await loop.run_in_executor(
                    None, read_native_message, sys.stdin.buffer
                )
            except EOFError:
                print("stdin EOF — shutting down relay", file=sys.stderr)
                break
            except ValueError as exc:
                print(f"oversized native message rejected: {exc}", file=sys.stderr)
                continue

            # Forward to broker.
            await write_ipc_message(writer, raw_msg)

            # Read broker response.
            try:
                response = await read_ipc_message(reader)
            except asyncio.IncompleteReadError:
                print("broker connection closed unexpectedly", file=sys.stderr)
                break

            # Chunk and send back to Chrome.
            for chunk in chunk_message(response):
                frame = json.dumps(chunk).encode("utf-8")
                write_native_message(sys.stdout.buffer, frame)

    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Configure the process and start the relay loop."""
    if sys.platform == "win32":
        import msvcrt

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)   # type: ignore[attr-defined]
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)  # type: ignore[attr-defined]

    os.environ["UV_THREADPOOL_SIZE"] = "3"

    socket_path = os.environ.get("MCP_BROKER_SOCKET", IPC_SOCKET_PATH)
    allowed_extension_id = os.environ.get("ALLOWED_EXTENSION_ID", "")

    asyncio.run(relay_loop(socket_path, allowed_extension_id))


if __name__ == "__main__":
    main()
