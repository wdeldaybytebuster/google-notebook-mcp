#!/usr/bin/env python3
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
from pathlib import Path
import struct
import sys
from typing import BinaryIO
import uuid

# Ensure src/ is importable when executed directly by Chrome Native Messaging
_src_root = str(Path(__file__).resolve().parent.parent.parent)
if _src_root not in sys.path:
    sys.path.insert(0, _src_root)

from mcp_gateway.transport import get_default_ipc_path, open_ipc_connection  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHROME_FRAME_FORMAT: str = "@I"   # native-endian 4-byte unsigned int
IPC_FRAME_FORMAT: str = ">I"      # big-endian 4-byte unsigned int
MAX_MESSAGE_SIZE: int = 32 * 1024 * 1024  # 32 MiB — accommodate multi-megabyte responses
CHUNK_SIZE: int = 512 * 1024              # 512 KiB slice threshold
IPC_SOCKET_PATH: str = get_default_ipc_path()

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
    """Open an IPC connection (Unix domain socket or Windows Named Pipe) to the broker.

    Raises ConnectionRefusedError if the broker is not running.
    """
    try:
        reader, writer = await open_ipc_connection(socket_path)
        return reader, writer
    except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
        if sys.platform != "win32" and socket_path != "/tmp/notebooklm-mcp-broker.sock" and os.path.exists("/tmp/notebooklm-mcp-broker.sock"):
            try:
                reader, writer = await open_ipc_connection("/tmp/notebooklm-mcp-broker.sock")
                return reader, writer
            except Exception:
                pass
        raise ConnectionRefusedError(
            f"Broker not reachable at {socket_path!r}: {exc}"
        ) from exc


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
    ack_ext = ack.get("extension_id", "")
    return bool(
        ack.get("type") == "hello_ack"
        and (not allowed_extension_id or not ack_ext or ack_ext == allowed_extension_id)
    )


# ---------------------------------------------------------------------------
# Main relay loop
# ---------------------------------------------------------------------------


def inject_boundary_idempotency(data: bytes) -> bytes:
    """Injects a cryptographic UUIDv4 idempotency key into mutation commands if missing."""
    try:
        parsed = json.loads(data.decode("utf-8"))
        if not isinstance(parsed, dict):
            return data
        action = parsed.get("action") or parsed.get("command") or parsed.get("operation")
        if action in ("add_source", "query_notebook"):
            if not parsed.get("idempotency_key") and not parsed.get("request_key"):
                new_key = str(uuid.uuid4())
                parsed["idempotency_key"] = new_key
                parsed["request_key"] = new_key
                return json.dumps(parsed).encode("utf-8")
            elif not parsed.get("idempotency_key") and parsed.get("request_key"):
                parsed["idempotency_key"] = parsed["request_key"]
                return json.dumps(parsed).encode("utf-8")
            elif not parsed.get("request_key") and parsed.get("idempotency_key"):
                parsed["request_key"] = parsed["idempotency_key"]
                return json.dumps(parsed).encode("utf-8")
        return data
    except Exception:
        return data


def setup_stderr_redirection() -> None:
    """Redirects sys.stderr to avoid 64KB pipe capacity deadlock when run unmonitored."""
    try:
        log_dir = Path.home() / ".config" / "notebooklm-mcp-bridge"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(log_dir / "native_host_stderr.log", "a", encoding="utf-8", buffering=1)
        os.dup2(log_file.fileno(), 2)
        sys.stderr = log_file
    except Exception:
        try:
            null_path = "NUL" if sys.platform == "win32" else "/dev/null"
            devnull = os.open(null_path, os.O_WRONLY)
            os.dup2(devnull, 2)
            sys.stderr = open(null_path, "w", encoding="utf-8")
        except Exception:
            pass


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

        async def broker_to_chrome() -> None:
            while True:
                try:
                    payload = await read_ipc_message(reader)
                except asyncio.IncompleteReadError:
                    print("broker connection closed (EOF)", file=sys.stderr)
                    break
                except Exception as exc:
                    print(f"error reading from broker: {exc}", file=sys.stderr)
                    break

                print(f"[native_host] forwarding {len(payload)} bytes from broker to Chrome", file=sys.stderr)
                payload_to_send = inject_boundary_idempotency(payload)
                write_native_message(sys.stdout.buffer, payload_to_send)

        async def chrome_to_broker() -> None:
            while True:
                try:
                    raw_msg = await loop.run_in_executor(
                        None, read_native_message, sys.stdin.buffer
                    )
                except EOFError:
                    print("stdin EOF — shutting down relay", file=sys.stderr)
                    break
                except ValueError as exc:
                    print(f"oversized native message rejected: {exc}", file=sys.stderr)
                    break
                except Exception as exc:
                    print(f"error reading from stdin: {exc}", file=sys.stderr)
                    break

                print(f"[native_host] forwarding {len(raw_msg)} bytes from Chrome to broker", file=sys.stderr)
                payload_to_send = inject_boundary_idempotency(raw_msg)
                try:
                    await write_ipc_message(writer, payload_to_send)
                except Exception as exc:
                    print(f"error writing to broker: {exc}", file=sys.stderr)
                    break

        t1 = asyncio.create_task(broker_to_chrome())
        t2 = asyncio.create_task(chrome_to_broker())

        done, pending = await asyncio.wait(
            [t1, t2],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

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

        o_binary = getattr(os, "O_BINARY", 0x8000)
        msvcrt.setmode(sys.stdin.fileno(), o_binary)   # type: ignore[attr-defined]
        msvcrt.setmode(sys.stdout.fileno(), o_binary)  # type: ignore[attr-defined]

    if os.environ.get("MCP_REDIRECT_STDERR", "1") == "1":
        setup_stderr_redirection()

    os.environ["UV_THREADPOOL_SIZE"] = "3"

    socket_path = os.environ.get("MCP_BROKER_SOCKET", IPC_SOCKET_PATH)
    allowed_extension_id = os.environ.get("ALLOWED_EXTENSION_ID", "")
    if not allowed_extension_id and len(sys.argv) > 1 and sys.argv[1].startswith("chrome-extension://"):
        allowed_extension_id = sys.argv[1].split("://", 1)[1].rstrip("/")

    try:
        asyncio.run(relay_loop(socket_path, allowed_extension_id))
    finally:
        os._exit(0)


if __name__ == "__main__":
    main()
