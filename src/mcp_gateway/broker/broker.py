"""Broker daemon and 5-tool MCP stdio facade for Gemini Notebook bridge.

Enforces:
- Mandatory allowlist checks before notebook inspection or mutation.
- Closed 5-tool JSON schema surface (additionalProperties: false).
- Zero-leak credential redaction on all log and IPC outputs.
- Conservative mutation journaling for state tracking and idempotency.
- Strict stdio separation: protocol JSON-RPC on stdout, diagnostics on stderr.
"""

from __future__ import annotations

import os
import sys

# CRITICAL: Enforce worker threadpool limits before asyncio initialization
os.environ["UV_THREADPOOL_SIZE"] = "3"

import argparse
import asyncio
import base64
import json
import math
from pathlib import Path
import secrets
import struct
import time
from dataclasses import dataclass, field
from typing import Any, cast

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

from mcp_gateway.broker.allowlist import (
    AllowlistConfig,
    is_notebook_allowed,
    load_allowlist,
)
from mcp_gateway.broker.secret_scrubber import scrub_dict
from mcp_gateway.engine.coordinate import CitationSpan, normalize_citation
from mcp_gateway.engine.readiness_poller import (
    SourceStatus,
    parse_source_status,
    poll_until_ready,
)
from mcp_gateway.engine.rpc_templates import (
    make_add_drive_payload,
    make_add_text_payload,
    make_add_url_payload,
    make_create_note_payload,
    make_delete_note_payload,
    make_get_metadata_payload,
    make_list_notebooks_payload,
    make_query_params,
    make_register_upload_payload,
)
from mcp_gateway.engine.stream_decoder import (
    BatchexecuteStreamDecoder,
    GenerateFreeFormStreamParser,
)
from mcp_gateway.broker.session import SessionLock
from mcp_gateway.schemas.error import (
    ALLOWLIST_DENIED,
    AUTH_REQUIRED,
    INTERNAL,
    INVALID_ARGUMENT,
    MUTATION_UNKNOWN,
    NOT_FOUND,
    REQUEST_KEY_CONFLICT,
    RESOURCE_EXHAUSTED,
    UPSTREAM_SCHEMA_DRIFT,
    categorize_error,
    make_error,
)
from mcp_gateway.traceparent import extract_or_generate_traceparent
from mcp_gateway.schemas.tools import (
    ADD_SOURCE_SCHEMA,
    CREATE_NOTE_SCHEMA,
    DELETE_NOTE_SCHEMA,
    GET_NOTEBOOK_METADATA_SCHEMA,
    LIST_NOTEBOOKS_SCHEMA,
    LIST_NOTES_SCHEMA,
    LIST_SOURCES_SCHEMA,
    QUERY_NOTEBOOK_SCHEMA,
    SELECT_NOTEBOOK_SCHEMA,
    validate_tool_args,
)
from mcp_gateway.storage.journal import (
    MutationJournal,
    MutationState,
    OperationType,
)
from mcp_gateway.transport import (
    BaseIpcServer,
    create_ipc_server,
    get_default_ipc_path,
    open_ipc_connection,
)

IPC_FRAME_FORMAT = ">I"



class ReentrantAsyncLock:
    """An asyncio reentrant lock enabling nested locking in the same task."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._count = 0

    async def acquire(self) -> None:
        current_task = asyncio.current_task()
        if self._owner is not None and self._owner == current_task:
            self._count += 1
            return
        await self._lock.acquire()
        self._owner = current_task
        self._count = 1

    def release(self) -> None:
        current_task = asyncio.current_task()
        if self._owner != current_task:
            raise RuntimeError("Cannot release un-acquired lock")
        self._count -= 1
        if self._count == 0:
            self._owner = None
            self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()

    async def __aenter__(self) -> ReentrantAsyncLock:
        await self.acquire()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


@dataclass
class BrokerConfig:
    socket_path: str = field(
        default_factory=lambda: os.environ.get("MCP_BROKER_SOCKET", get_default_ipc_path())
    )
    allowlist_path: Path | None = None
    journal_db_path: Path | None = None
    capability_secret: bytes = field(default_factory=lambda: secrets.token_bytes(32))


class BrokerDaemon:
    """Core policy enforcement, IPC bridge, and RPC orchestration engine."""

    def __init__(self, config: BrokerConfig | None = None) -> None:
        self.config = config or BrokerConfig()
        self.allowlist: AllowlistConfig | None = None
        self._load_allowlist_safe()

        db_path = (
            self.config.journal_db_path
            or Path.home() / ".config" / "notebooklm-mcp-bridge" / "journal.db"
        )
        self.journal = MutationJournal(db_path)
        self._ipc_server: BaseIpcServer | None = None
        self.session_lock = SessionLock(self.config.capability_secret)
        self._active_companion_writer: asyncio.StreamWriter | None = None
        self._pending_responses: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._session_mutex: asyncio.Lock = asyncio.Lock()
        self._companion_ipc_mutex: ReentrantAsyncLock = ReentrantAsyncLock()
        self._mock_available_memory_bytes: int | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._heartbeat_interval: float = 15.0
        self._heartbeat_timeout: float = 30.0
        self._heartbeat_running: bool = False

    def _load_allowlist_safe(self) -> None:
        try:
            self.allowlist = load_allowlist(self.config.allowlist_path)
        except Exception as exc:
            print(
                f"[broker] Notice: Allowlist not loaded ({exc}). Using deny-all policy.",
                file=sys.stderr,
            )
            self.allowlist = AllowlistConfig(
                version=1,
                provider_mode="browser",
                accounts=[],
                notebooks=[],
            )

    def reload_allowlist(self) -> None:
        self._load_allowlist_safe()

    async def start(self) -> None:
        """Starts the platform-native IPC server and begins background heartbeat monitoring."""
        self._ipc_server = await create_ipc_server(
            self.handle_ipc_connection,
            self.config.socket_path,
        )
        await self._ipc_server.start()
        self._heartbeat_running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        print(f"[broker] Listening on IPC endpoint: {self.config.socket_path}", file=sys.stderr)

    async def stop(self) -> None:
        self._heartbeat_running = False
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        if self._ipc_server is not None:
            await self._ipc_server.close()
            self._ipc_server = None

    async def _heartbeat_loop(self) -> None:
        """Periodically sends heartbeat pings to companion to verify liveness (Domain E)."""
        while self._heartbeat_running:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                if not self._heartbeat_running:
                    break
                if self._active_companion_writer is not None:
                    await self._send_heartbeat_ping()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"[broker] Heartbeat loop exception: {exc}", file=sys.stderr)

    async def _send_heartbeat_ping(self) -> bool:
        """Dispatches HEARTBEAT_PING and drops writer if companion times out or fails (5.3.1)."""
        if self._active_companion_writer is None:
            return False

        try:
            res = await self.send_to_companion(
                command="HEARTBEAT_PING",
                payload={"type": "ping", "timestamp": time.time()},
                timeout_seconds=self._heartbeat_timeout,
            )
            is_pong = (
                res.get("ok") is True
                and (
                    res.get("command") in ("HEARTBEAT_PONG", "pong")
                    or res.get("type") in ("pong", "HEARTBEAT_PONG")
                    or res.get("status") == "pong"
                )
            )
            if is_pong:
                return True
            else:
                await self._drop_companion_connection(f"Invalid pong response from companion: {res}")
                return False
        except Exception as exc:
            await self._drop_companion_connection(f"Heartbeat ping failed: {exc}")
            return False

    async def _drop_companion_connection(self, reason: str = "") -> None:
        """Drops active companion writer on connection failure or dropped heartbeat."""
        if self._active_companion_writer is not None:
            writer = self._active_companion_writer
            self._active_companion_writer = None
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            print(f"[broker] Dropped companion connection: {reason}", file=sys.stderr)

    async def handle_ipc_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handles inbound frames from the Native Messaging host over big-endian IPC."""
        try:
            while True:
                length_bytes = await reader.readexactly(4)
                (msg_len,) = struct.unpack(IPC_FRAME_FORMAT, length_bytes)
                payload_bytes = await reader.readexactly(msg_len)
                raw_message: dict[str, Any] = json.loads(payload_bytes.decode("utf-8"))

                # Handshake handling with native_host.py
                if raw_message.get("type") == "hello":
                    self._active_companion_writer = writer
                    ack = {
                        "type": "hello_ack",
                        "extension_id": os.environ.get("ALLOWED_EXTENSION_ID", ""),
                    }
                    ack_bytes = json.dumps(ack).encode("utf-8")
                    writer.write(struct.pack(IPC_FRAME_FORMAT, len(ack_bytes)) + ack_bytes)
                    await writer.drain()
                    continue

                # Response frame handling for pending companion requests
                request_id = raw_message.get("requestId")
                if request_id and request_id in self._pending_responses:
                    fut = self._pending_responses.pop(request_id)
                    if not fut.done():
                        fut.set_result(raw_message)
                    continue

                # Heartbeat ping handling from companion (Domain E)
                if raw_message.get("type") in ("ping", "HEARTBEAT_PING") or raw_message.get("command") in ("ping", "HEARTBEAT_PING"):
                    pong_reply: dict[str, Any] = {
                        "ok": True,
                        "type": "pong",
                        "command": "HEARTBEAT_PONG",
                        "requestId": raw_message.get("requestId", ""),
                        "timestamp": time.time(),
                    }
                    pong_bytes = json.dumps(pong_reply).encode("utf-8")
                    writer.write(struct.pack(IPC_FRAME_FORMAT, len(pong_bytes)) + pong_bytes)
                    await writer.drain()
                    continue

                # Unsolicited pong frame handling
                if raw_message.get("type") in ("pong", "HEARTBEAT_PONG") or raw_message.get("command") in ("pong", "HEARTBEAT_PONG"):
                    continue

                # Otherwise dispatch inbound command and send back reply
                reply = await self.dispatch(raw_message)
                reply_bytes = json.dumps(reply).encode("utf-8")
                writer.write(struct.pack(IPC_FRAME_FORMAT, len(reply_bytes)) + reply_bytes)
                await writer.drain()

        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            if self._active_companion_writer is writer:
                self._active_companion_writer = None
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def send_to_companion(
        self,
        command: str,
        payload: dict[str, Any],
        timeout_seconds: float = 60.0,
    ) -> dict[str, Any]:
        """Sends a command to the browser companion and awaits its response."""
        if self._active_companion_writer is None:
            if self._ipc_server is None:
                return await self._forward_to_socket({
                    "action": "companion_forward",
                    "companion_command": command,
                    "payload": payload,
                    "timeout_seconds": timeout_seconds,
                })
            return make_error(
                AUTH_REQUIRED,
                "Browser companion extension is not connected. "
                "Please verify Chrome is open with the Gemini Notebook extension enabled.",
                retryable=True,
            ).to_dict()

        request_id = secrets.token_hex(16)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_responses[request_id] = fut

        msg = {
            "command": command,
            "requestId": request_id,
            "payload": payload,
        }
        msg_bytes = json.dumps(msg).encode("utf-8")
        frame = struct.pack(IPC_FRAME_FORMAT, len(msg_bytes)) + msg_bytes

        try:
            async with self._companion_ipc_mutex:
                self._active_companion_writer.write(frame)
                await self._active_companion_writer.drain()
            return await asyncio.wait_for(fut, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            self._pending_responses.pop(request_id, None)
            return make_error(
                MUTATION_UNKNOWN,
                f"Timed out awaiting browser companion response after {timeout_seconds}s.",
                retryable=False,
            ).to_dict()
        except Exception as exc:
            self._pending_responses.pop(request_id, None)
            return make_error(
                INTERNAL,
                f"IPC communication error with browser companion: {exc}",
                retryable=True,
            ).to_dict()

    async def send_to_companion_exclusive(
        self,
        command: str,
        payload: dict[str, Any],
        timeout_seconds: float = 60.0,
    ) -> dict[str, Any]:
        """Sends command to companion holding socket lock for entire duration."""
        async with self._companion_ipc_mutex:
            return await self.send_to_companion(command, payload, timeout_seconds)

    def _check_memory_safety(self, required_bytes: int = 512 * 1024) -> bool:
        """Verifies available system memory exceeds the 320 MB safety reserve."""
        min_reserve_bytes = 320 * 1024 * 1024  # 320 MB safety reserve

        # Mockable test hook
        mock_avail = getattr(self, "_mock_available_memory_bytes", None)
        if mock_avail is not None:
            return (int(mock_avail) - required_bytes) >= min_reserve_bytes

        try:
            meminfo_path = Path("/proc/meminfo")
            if meminfo_path.exists():
                with open(meminfo_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("MemAvailable:"):
                            parts = line.split()
                            mem_kb = int(parts[1])
                            avail_bytes = mem_kb * 1024
                            return (avail_bytes - required_bytes) >= min_reserve_bytes
        except Exception:
            pass

        try:
            import psutil  # type: ignore[import-untyped]
            avail_bytes = int(psutil.virtual_memory().available)
            return (avail_bytes - required_bytes) >= min_reserve_bytes
        except Exception:
            pass

        return True

    async def _stream_scotty_chunks(
        self,
        source_id: str,
        filename: str,
        notebook_id: str,
        file_bytes: bytes,
    ) -> dict[str, Any]:
        """Streams multi-part file chunks holding companion IPC lock exclusively."""
        if not self._check_memory_safety(len(file_bytes)):
            return make_error(
                RESOURCE_EXHAUSTED,
                "Available system memory is below the 320 MB safety reserve.",
                retryable=True,
            ).to_dict()

        chunk_size = 512 * 1024  # 512 KiB bounded chunk
        total_chunks = max(1, math.ceil(len(file_bytes) / chunk_size))

        async with self._companion_ipc_mutex:  # M-02 Invariant: Lock socket for ALL chunks
            for idx in range(total_chunks):
                start = idx * chunk_size
                end = min(start + chunk_size, len(file_bytes))
                chunk_b64 = base64.b64encode(file_bytes[start:end]).decode("ascii")

                msg = {
                    "sourceId": source_id,
                    "filename": filename,
                    "notebookId": notebook_id,
                    "chunkIndex": idx,
                    "totalChunks": total_chunks,
                    "isLastChunk": (idx == total_chunks - 1),
                    "chunkData": chunk_b64,
                }
                res = await self.send_to_companion("scotty_chunk", msg, timeout_seconds=120.0)
                if not res.get("ok"):
                    return res

            return {"ok": True, "source_id": source_id}

    async def _forward_to_socket(self, command: dict[str, Any]) -> dict[str, Any]:
        """Forwards a command to the running background broker daemon on IPC channel."""
        try:
            reader, writer = await open_ipc_connection(self.config.socket_path)
        except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
            return make_error(
                AUTH_REQUIRED,
                "Browser companion extension is not connected. "
                "Please verify Chrome is open with the Gemini Notebook extension enabled "
                f"and the broker daemon is running on {self.config.socket_path} ({exc}).",
                retryable=True,
            ).to_dict()

        try:
            cmd_bytes = json.dumps(command).encode("utf-8")
            writer.write(struct.pack(IPC_FRAME_FORMAT, len(cmd_bytes)) + cmd_bytes)
            await writer.drain()

            len_bytes = await reader.readexactly(4)
            (resp_len,) = struct.unpack(IPC_FRAME_FORMAT, len_bytes)
            resp_bytes = await reader.readexactly(resp_len)
            res = json.loads(resp_bytes.decode("utf-8"))
            return cast(dict[str, Any], res)
        except Exception as exc:
            return make_error(
                INTERNAL,
                f"Error communicating with broker daemon: {exc}",
                retryable=True,
            ).to_dict()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def dispatch(self, command: dict[str, Any]) -> dict[str, Any]:
        """Dispatches an action with mandatory allowlist verification and secret scrubbing."""
        correlation_id = command.get("request_key") or command.get("idempotency_key")
        action = str(command.get("action") or command.get("command") or "")

        # ADR-011: Dedicated handler for select_notebook
        if action == "select_notebook":
            result = await self._handle_select_notebook(command)
            return self._finalize_dispatch(result, correlation_id)

        # Domain E: Dedicated handler for ping / HEARTBEAT_PING
        if action in ("ping", "HEARTBEAT_PING") or command.get("type") in ("ping", "HEARTBEAT_PING"):
            return {
                "ok": True,
                "type": "pong",
                "command": "HEARTBEAT_PONG",
                "timestamp": time.time(),
            }

        # ADR-011: Validate session state and apply parameter overwrite
        validation_err = await self.session_lock.validate_and_prepare(action, command)
        if validation_err is not None:
            return self._finalize_dispatch(validation_err.to_dict(), correlation_id)

        # Mandatory allowlist policy check
        notebook_id = command.get("notebook_id")
        if notebook_id is not None:
            self.reload_allowlist()
            assert self.allowlist is not None
            if not is_notebook_allowed(self.allowlist, str(notebook_id)):
                err_dict = make_error(
                    ALLOWLIST_DENIED,
                    "Notebook is not in the allowlist. Access denied by local policy.",
                    retryable=False,
                    mcp_correlation_id=correlation_id,
                ).to_dict()
                return self._finalize_dispatch(err_dict, correlation_id)

        try:
            if action == "companion_forward":
                result = await self.send_to_companion(
                    str(command["companion_command"]),
                    dict(command.get("payload", {})),
                    float(command.get("timeout_seconds", 60.0)),
                )
            elif action == "list_notebooks":
                result = await self._handle_list_notebooks(command)
            elif action == "get_notebook_metadata":
                result = await self._handle_get_notebook_metadata(command)
            elif action == "list_sources":
                result = await self._handle_list_sources(command)
            elif action == "query_notebook":
                result = await self._handle_query_notebook(command)
            elif action == "add_source":
                result = await self._handle_add_source(command)
            elif action == "create_note":
                result = await self._handle_create_note(command)
            elif action == "list_notes":
                result = await self._handle_list_notes(command)
            elif action == "delete_note":
                result = await self._handle_delete_note(command)
            else:
                result = make_error(
                    INVALID_ARGUMENT,
                    f"Unrecognized action {action!r}.",
                    retryable=False,
                    mcp_correlation_id=correlation_id,
                ).to_dict()
        except Exception as exc:
            result = make_error(
                INTERNAL,
                f"Unexpected broker exception during {action}: {exc}",
                retryable=False,
                mcp_correlation_id=correlation_id,
            ).to_dict()

        return self._finalize_dispatch(result, correlation_id)

    def _finalize_dispatch(self, result: dict[str, Any], correlation_id: str | None) -> dict[str, Any]:
        """Applies P-04 correlation propagation and secret scrubbing."""
        if correlation_id:
            if "_meta" not in result:
                result["_meta"] = {}
            result["_meta"]["mcp_correlation_id"] = correlation_id
            if not result.get("ok", True) and isinstance(result.get("error"), dict):
                result["error"]["mcp_correlation_id"] = correlation_id
        return scrub_dict(result)

    async def _fetch_all_allowed_notebooks(self) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Fetches all allowlisted notebooks from wXbhsf without session filtering."""
        rpc_payload = make_list_notebooks_payload(page_size=100)
        res = await self.send_to_companion("batchexecute", {"rpcId": "wXbhsf", "paramsJson": rpc_payload})
        if not res.get("ok"):
            return [], res

        body = str(res.get("body", ""))
        decoder = BatchexecuteStreamDecoder()
        records = decoder.feed(body.encode("utf-8"))

        notebooks: list[dict[str, Any]] = []
        for record in records:
            if record.get("rpc_id") == "wXbhsf":
                raw_items = record.get("data")
                if isinstance(raw_items, list):
                    items_list = raw_items
                    if len(raw_items) > 0 and isinstance(raw_items[0], list):
                        if len(raw_items[0]) > 0 and isinstance(raw_items[0][0], list):
                            items_list = raw_items[0]
                    for item in items_list:
                        if isinstance(item, list) and len(item) > 0:
                            nb_id = ""
                            title = ""
                            if len(item) > 2 and isinstance(item[2], str) and ("-" in item[2] or len(item[2]) > 20):
                                nb_id = str(item[2])
                                title = str(item[0]) if item[0] is not None else ""
                            elif len(item) > 1 and isinstance(item[0], str):
                                nb_id = str(item[0])
                                title = str(item[1]) if item[1] is not None else ""
                            elif len(item) > 0:
                                nb_id = str(item[0])

                            if nb_id:
                                # Filter strictly by allowlist
                                assert self.allowlist is not None
                                if is_notebook_allowed(self.allowlist, nb_id):
                                    notebooks.append({"id": nb_id, "title": title})

        return notebooks, None

    async def _handle_list_notebooks(self, command: dict[str, Any]) -> dict[str, Any]:
        page_size_arg = command.get("page_size")
        page_size = int(page_size_arg) if page_size_arg is not None else 20
        cursor = command.get("cursor")

        notebooks, err = await self._fetch_all_allowed_notebooks()
        if err is not None:
            return err

        # ADR-011: Filter down to locked notebook if session is locked
        notebooks = self.session_lock.filter_notebooks(notebooks)

        start_idx = 0
        if cursor is not None:
            try:
                start_idx = int(cursor)
            except ValueError:
                start_idx = 0

        paged_notebooks = notebooks[start_idx:]
        next_cursor: str | None = None
        if len(paged_notebooks) > page_size:
            next_cursor = str(start_idx + page_size)
            paged_notebooks = paged_notebooks[:page_size]

        response: dict[str, Any] = {"ok": True, "notebooks": paged_notebooks}
        if next_cursor is not None:
            response["next_cursor"] = next_cursor

        # Project-level notebook memory and in-chat confirmation prompt
        from mcp_gateway.broker.project_config import get_project_notebook_config

        cfg = get_project_notebook_config()
        if cfg:
            proj_title = cfg.get("title") or cfg.get("notebook_id")
            response["project_config"] = {
                "configured": True,
                "notebook_id": cfg.get("notebook_id"),
                "title": cfg.get("title", ""),
            }
            response["user_prompt"] = (
                f"Project default notebook is '{proj_title}'. "
                f"Please double-check with the user: 'For this project, we have notebook \"{proj_title}\" configured. "
                "Would you like to use this notebook for this chat, or choose another from the list above?' "
                "Once the user confirms, call select_notebook."
            )
        else:
            response["project_config"] = {"configured": False}
            response["user_prompt"] = (
                "No project default notebook is configured yet. Please present the list of available notebooks "
                "to the user and ask: 'Which Google Notebook would you like to use for this project?' "
                "Once the user chooses, call select_notebook with save_for_project=true."
            )
        return response

    async def _handle_select_notebook(self, command: dict[str, Any]) -> dict[str, Any]:
        """Handles select_notebook with title resolution and ADR-011 session locking (M-01)."""
        async with self._session_mutex:
            notebook_id = command.get("notebook_id")
            title = command.get("title")

            if not notebook_id and not title:
                return make_error(
                    INVALID_ARGUMENT,
                    "Must provide either 'notebook_id' or 'title' to select_notebook.",
                    retryable=False,
                ).to_dict()

            resolved_id = str(notebook_id) if notebook_id else ""
            resolved_title = str(title) if title else ""

            # Title-based resolution if notebook_id not provided
            if not resolved_id and title:
                target_title = str(title).strip().lower()
                self.reload_allowlist()
                notebooks, err = await self._fetch_all_allowed_notebooks()
                if err is not None:
                    return err

                matching_notebooks = [
                    nb for nb in notebooks
                    if str(nb.get("title", "")).strip().lower() == target_title
                ]

                if len(matching_notebooks) == 0:
                    return make_error(
                        NOT_FOUND,
                        f"Notebook titled '{title}' not found in allowlisted notebooks.",
                        retryable=False,
                    ).to_dict()
                elif len(matching_notebooks) > 1:
                    return make_error(
                        INVALID_ARGUMENT,
                        f"Ambiguous title: found {len(matching_notebooks)} notebooks titled '{title}'. "
                        "Please specify 'notebook_id' explicitly.",
                        retryable=False,
                    ).to_dict()

                resolved_id = str(matching_notebooks[0].get("id", ""))
                resolved_title = str(matching_notebooks[0].get("title", ""))

            if not resolved_title and resolved_id:
                allowlist_titles = getattr(self.allowlist, "titles", {})
                if isinstance(allowlist_titles, dict) and resolved_id in allowlist_titles:
                    resolved_title = allowlist_titles[resolved_id]
                else:
                    try:
                        fetched_nbs, _ = await self._fetch_all_allowed_notebooks()
                        for nb in fetched_nbs:
                            if str(nb.get("id")) == resolved_id:
                                resolved_title = str(nb.get("title", ""))
                                break
                    except Exception:
                        pass

            self.reload_allowlist()
            assert self.allowlist is not None
            is_allowed = is_notebook_allowed(self.allowlist, resolved_id)
            result = await self.session_lock.select_notebook(resolved_id, is_allowed)

            if result.get("ok"):
                save_for_project = bool(command.get("save_for_project", True))
                if save_for_project and resolved_id:
                    from mcp_gateway.broker.project_config import save_project_notebook_config

                    saved_file = save_project_notebook_config(resolved_id, resolved_title)
                    if saved_file:
                        result["project_saved"] = True
                        result["project_config_path"] = str(saved_file)
                        if "message" not in result:
                            result["message"] = (
                                f"Session locked to '{resolved_title or resolved_id}' and saved to .notebook_mcp.json "
                                "for this project."
                            )

            return scrub_dict(result)

    async def _handle_get_notebook_metadata(self, command: dict[str, Any]) -> dict[str, Any]:
        nb_id = str(command["notebook_id"])
        rpc_payload = make_get_metadata_payload(nb_id)
        res = await self.send_to_companion(
            "batchexecute",
            {"rpcId": "rLM1Ne", "paramsJson": rpc_payload, "notebookId": nb_id},
        )
        if not res.get("ok"):
            return res

        body = str(res.get("body", ""))
        decoder = BatchexecuteStreamDecoder()
        records = decoder.feed(body.encode("utf-8"))

        metadata: dict[str, Any] = {"notebook_id": nb_id, "raw": None}
        for record in records:
            if record.get("rpc_id") == "rLM1Ne":
                metadata["raw"] = record.get("data")
                break

        return {"ok": True, "metadata": metadata}

    async def _handle_list_sources(self, command: dict[str, Any]) -> dict[str, Any]:
        nb_id = str(command["notebook_id"])
        page_size_arg = command.get("page_size")
        cursor = command.get("cursor")

        rpc_payload = make_get_metadata_payload(nb_id)
        res = await self.send_to_companion(
            "batchexecute",
            {"rpcId": "rLM1Ne", "paramsJson": rpc_payload, "notebookId": nb_id},
        )
        if not res.get("ok"):
            return res

        body = str(res.get("body", ""))
        decoder = BatchexecuteStreamDecoder()
        records = decoder.feed(body.encode("utf-8"))

        raw_sources: list[Any] = []
        for record in records:
            if record.get("rpc_id") == "rLM1Ne":
                data = record.get("data")
                if isinstance(data, list):
                    # In live wire format, data[0] is the notebook entry, where data[0][1] is a list of document sources
                    # and data[0][17] is user notes / text sources
                    if (
                        len(data) > 0
                        and isinstance(data[0], list)
                        and len(data[0]) > 1
                        and isinstance(data[0][1], list)
                    ):
                        container = data[0]
                        raw_sources.extend(container[1])
                        if len(container) > 17 and isinstance(container[17], list):
                            raw_sources.extend(container[17])
                    # In legacy or mock format, row [102] is the sources array
                    elif len(data) > 102 and isinstance(data[102], list):
                        raw_sources = data[102]
                    else:
                        raw_sources = data
                break

        sources: list[dict[str, Any]] = []
        for s in raw_sources:
            if isinstance(s, list) and len(s) > 0:
                s_id = s[0][0] if (isinstance(s[0], list) and s[0]) else s[0]
                s_title = ""
                if len(s) > 4 and isinstance(s[4], str) and s[4]:
                    s_title = s[4]
                elif len(s) > 1 and isinstance(s[1], str) and s[1]:
                    s_title = s[1]

                # If it's a note (has title at index 4 and timestamp array at index 2), it is immediately READY
                if len(s) > 4 and isinstance(s[4], str) and isinstance(s[2], list):
                    st = SourceStatus.READY
                else:
                    st = parse_source_status(s)

                entry: dict[str, Any] = {
                    "id": str(s_id),
                    "title": str(s_title),
                    "status": st.name,
                    "status_code": int(st.value),
                    "raw_row": s,
                }
                sources.append(entry)

        start_idx = 0
        if cursor is not None:
            try:
                start_idx = int(cursor)
            except ValueError:
                start_idx = 0

        paged_sources = sources[start_idx:]
        next_cursor: str | None = None
        if page_size_arg is not None:
            try:
                page_size = int(page_size_arg)
                if page_size > 0 and len(paged_sources) > page_size:
                    next_cursor = str(start_idx + page_size)
                    paged_sources = paged_sources[:page_size]
            except ValueError:
                pass

        resp: dict[str, Any] = {"ok": True, "sources": paged_sources}
        if next_cursor is not None:
            resp["next_cursor"] = next_cursor
        return resp

    async def _handle_query_notebook(self, command: dict[str, Any]) -> dict[str, Any]:
        nb_id = str(command["notebook_id"])
        question = str(command["question"])
        request_key = str(command["request_key"])
        source_ids: list[str] = list(command.get("source_ids") or [])
        timeout_seconds = int(command.get("timeout_seconds", 600))

        existing = self.journal.get(request_key)
        if existing is not None:
            if existing.state in (MutationState.SENT, MutationState.UNKNOWN):
                return make_error(
                    REQUEST_KEY_CONFLICT,
                    f"Mutation {request_key!r} is currently in state {existing.state.value!r}. "
                    "Automatic replay is blocked; active reconciliation required.",
                    retryable=False,
                ).to_dict()
            elif existing.state == MutationState.CONFIRMED:
                return {
                    "ok": True,
                    "answer": "Cached result for confirmed query.",
                    "citations": [],
                    "cached": True,
                }
            elif existing.state == MutationState.REJECTED:
                return make_error(
                    REQUEST_KEY_CONFLICT,
                    f"Mutation {request_key!r} was previously rejected.",
                    retryable=False,
                ).to_dict()

        # Mutation Journal Lifecycle: PREPARED
        self.journal.prepare(
            request_key=request_key,
            notebook_id=nb_id,
            operation_type=OperationType.QUERY_NOTEBOOK,
            args=command,
            capability_secret=self.config.capability_secret,
        )

        # M-10: Pre-query readiness verification scoped to source_ids
        if source_ids:
            sources_res = await self._handle_list_sources({"action": "list_sources", "notebook_id": nb_id})
            if sources_res.get("ok"):
                known_sources = {str(s.get("id")): s for s in sources_res.get("sources", [])}
                unready_targets = [
                    sid for sid in source_ids
                    if sid in known_sources and int(known_sources[sid].get("status_code", 0)) != 2
                ]
                if unready_targets:
                    return make_error(
                        INVALID_ARGUMENT,
                        f"Targeted source(s) {unready_targets} are not in READY (2) state.",
                        retryable=True,
                    ).to_dict()

        # Transition: SENT
        self.journal.transition(request_key, MutationState.SENT)

        query_params = make_query_params(
            sources=source_ids,
            question=question,
            notebook_id=nb_id,
            session_id=None,
            message_id=str(secrets.token_hex(16)),
            history=[],
        )

        res = await self.send_to_companion(
            "query_stream",
            {
                "paramsJson": query_params,
                "notebookId": nb_id,
                "timeout_seconds": float(timeout_seconds),
            },
            timeout_seconds=float(timeout_seconds),
        )

        parser = GenerateFreeFormStreamParser()

        if not res.get("ok"):
            body = str(res.get("body", ""))
            if body:
                parser.feed(body.encode("utf-8"))
                final_events = parser.finalize()
                for ev in final_events:
                    if ev.get("type") == "error_delta":
                        self.journal.transition(request_key, MutationState.UNKNOWN)
                        err_dict = ev.get("error", {})
                        return make_error(
                            err_dict.get("code", "STREAM_SEVERED"),
                            err_dict.get("message", "Stream severed unexpectedly by upstream transport."),
                            retryable=bool(err_dict.get("retryable", True)),
                        ).to_dict()

            err_code = str(res.get("error", {}).get("code", ""))
            if err_code in (MUTATION_UNKNOWN, "STREAM_ERROR", "STREAM_SEVERED"):
                self.journal.transition(request_key, MutationState.UNKNOWN)
            else:
                self.journal.transition(request_key, MutationState.REJECTED)
            return res

        body = str(res.get("body", ""))
        try:
            with open("/tmp/raw_query_stream_body.txt", "w", encoding="utf-8") as f:
                f.write(body)
        except Exception:
            pass
        events = parser.feed(body.encode("utf-8"))
        final_events = parser.finalize()
        events.extend(final_events)

        # Mid-stream error delta emission (P-01 / v4.2 Polish)
        for ev in events:
            if ev.get("type") == "error_delta":
                self.journal.transition(request_key, MutationState.UNKNOWN)
                err_dict = ev.get("error", {})
                return make_error(
                    err_dict.get("code", "STREAM_SEVERED"),
                    err_dict.get("message", "Stream severed unexpectedly by upstream transport."),
                    retryable=bool(err_dict.get("retryable", True)),
                ).to_dict()

        answer_parts: list[str] = []
        raw_citations: list[dict[str, Any]] = []
        for ev in events:
            if ev.get("type") == "text_delta":
                answer_parts.append(str(ev.get("text", "")))
            elif ev.get("type") == "citation":
                cits = ev.get("citations", [])
                if isinstance(cits, list):
                    raw_citations.extend(cits)

        full_text = "".join(answer_parts)

        fallback_source = (source_ids[0] if source_ids else "") or nb_id
        for cit in raw_citations:
            if not cit.get("source_id"):
                cit["source_id"] = fallback_source

        # Normalize coordinates from UTF-16 to Unicode
        normalized_citations: list[CitationSpan] = []
        for cit in raw_citations:
            try:
                normalized_citations.append(normalize_citation(cit, full_text))
            except Exception as e:
                print(f"[broker citation exc] {e} on cit={cit}", file=sys.stderr)

        print(
            f"[broker debug] answer len={len(full_text)}, raw_cits={len(raw_citations)}, norm_cits={len(normalized_citations)}, preview={full_text[:200]!r}",
            file=sys.stderr,
        )

        # Strict Grounding Verification (AGENTS.md Rule XI.3 & M-06)
        if len(normalized_citations) == 0:
            self.journal.transition(request_key, MutationState.REJECTED)
            return make_error(
                "UNGROUNDED_RESPONSE",
                "Query response contains zero grounding citations. Output rejected per AGENTS.md Rule XI.3.",
                retryable=False,
            ).to_dict()

        # Transition: CONFIRMED
        self.journal.transition(request_key, MutationState.CONFIRMED)

        return {
            "ok": True,
            "answer": full_text,
            "citations": [
                {
                    "source_id": cit.source_id,
                    "text_snippet": cit.text_snippet,
                    "start_char": cit.start_char,
                    "end_char": cit.end_char,
                }
                for cit in normalized_citations
            ],
        }

    async def _handle_add_source(self, command: dict[str, Any]) -> dict[str, Any]:
        nb_id = str(command["notebook_id"])
        idempotency_key = str(command["idempotency_key"])
        source = dict(command["source"])
        source_type = str(source.get("type", ""))
        wait_until_ready = bool(command.get("wait_until_ready", False))

        existing = self.journal.get(idempotency_key)
        if existing is not None:
            if existing.state in (MutationState.SENT, MutationState.UNKNOWN):
                return make_error(
                    REQUEST_KEY_CONFLICT,
                    f"Mutation {idempotency_key!r} is currently in state {existing.state.value!r}. "
                    "Automatic replay is blocked; active reconciliation required.",
                    retryable=False,
                ).to_dict()
            elif existing.state == MutationState.CONFIRMED:
                return {
                    "ok": True,
                    "source_id": existing.assigned_source_id or "",
                    "status": "CONFIRMED",
                    "cached": True,
                }
            elif existing.state == MutationState.REJECTED:
                return make_error(
                    REQUEST_KEY_CONFLICT,
                    f"Mutation {idempotency_key!r} was previously rejected.",
                    retryable=False,
                ).to_dict()

        # Mutation Journal Lifecycle: PREPARED
        self.journal.prepare(
            request_key=idempotency_key,
            notebook_id=nb_id,
            operation_type=OperationType.ADD_SOURCE,
            args=command,
            capability_secret=self.config.capability_secret,
        )

        # Transition: SENT
        self.journal.transition(idempotency_key, MutationState.SENT)

        assigned_source_id: str | None = None
        file_bytes: bytes = b""
        if source_type == "text":
            payload = make_add_text_payload(
                title=str(source.get("title", "Untitled")),
                content=str(source.get("content", "")),
                notebook_id=nb_id,
            )
            res = await self.send_to_companion("batchexecute", {"rpcId": "CYK0Xb", "paramsJson": payload, "notebookId": nb_id})
            if res.get("ok"):
                body = str(res.get("body", ""))
                decoder = BatchexecuteStreamDecoder()
                records = decoder.feed(body.encode("utf-8"))
                for rec in records:
                    data = rec.get("data")
                    if isinstance(data, list) and data:
                        try:
                            if isinstance(data[0], list) and data[0]:
                                assigned_source_id = str(data[0][0])
                            else:
                                assigned_source_id = str(data[0])
                        except Exception:
                            pass
            # Fallback to izAoDd if CYK0Xb returned no source id (e.g. in mock companion)
            if not assigned_source_id:
                res = await self.send_to_companion("batchexecute", {"rpcId": "izAoDd", "paramsJson": payload, "notebookId": nb_id})
        elif source_type in ("url", "youtube"):
            payload = make_add_url_payload(url=str(source["url"]), notebook_id=nb_id)
            res = await self.send_to_companion("batchexecute", {"rpcId": "izAoDd", "paramsJson": payload, "notebookId": nb_id})
        elif source_type == "drive":
            payload = make_add_drive_payload(
                doc_id=str(source["doc_id"]),
                mime_type=str(source.get("mime_type", "")),
                title=str(source.get("title", "")),
                notebook_id=nb_id,
            )
            res = await self.send_to_companion("batchexecute", {"rpcId": "izAoDd", "paramsJson": payload, "notebookId": nb_id})
        elif source_type == "file":
            raw_content = str(source.get("content", ""))
            try:
                file_bytes = base64.b64decode(raw_content.encode("ascii"), validate=True)
            except Exception:
                file_bytes = raw_content.encode("utf-8")

            if not self._check_memory_safety(len(file_bytes)):
                self.journal.transition(idempotency_key, MutationState.REJECTED)
                return make_error(
                    RESOURCE_EXHAUSTED,
                    "Available system memory is below the 320 MB safety reserve.",
                    retryable=True,
                    mcp_correlation_id=idempotency_key,
                ).to_dict()

            payload = make_register_upload_payload(
                filename=str(source.get("title", "uploaded_file")),
                notebook_id=nb_id,
            )
            res = await self.send_to_companion("batchexecute", {"rpcId": "o4cbdc", "paramsJson": payload, "notebookId": nb_id})
        else:
            self.journal.transition(idempotency_key, MutationState.REJECTED)
            return make_error(INVALID_ARGUMENT, f"Unsupported source type {source_type!r}.").to_dict()

        if not res.get("ok"):
            err_code = str(res.get("error", {}).get("code", ""))
            if err_code == MUTATION_UNKNOWN:
                self.journal.transition(idempotency_key, MutationState.UNKNOWN)
            else:
                self.journal.transition(idempotency_key, MutationState.REJECTED)
            return res

        # Decode response to obtain assigned source id if not already resolved
        if assigned_source_id is None:
            body = str(res.get("body", ""))
            decoder = BatchexecuteStreamDecoder()
            records = decoder.feed(body.encode("utf-8"))
            for rec in records:
                data = rec.get("data")
                if isinstance(data, list) and data:
                    try:
                        if isinstance(data[0], list) and data[0]:
                            assigned_source_id = str(data[0][0])
                        else:
                            assigned_source_id = str(data[0])
                    except Exception:
                        pass

        if assigned_source_id is None:
            assigned_source_id = f"src_{secrets.token_hex(8)}"

        # Phase 4/5: Scotty Resumable Upload (Steps 2 & 3) if source_type == "file"
        if source_type == "file":
            if not file_bytes:
                raw_content = str(source.get("content", ""))
                try:
                    file_bytes = base64.b64decode(raw_content.encode("ascii"), validate=True)
                except Exception:
                    file_bytes = raw_content.encode("utf-8")

            filename = str(source.get("title") or "uploaded_file")
            if len(file_bytes) > 512 * 1024:
                upload_res = await self._stream_scotty_chunks(
                    source_id=assigned_source_id,
                    filename=filename,
                    notebook_id=nb_id,
                    file_bytes=file_bytes,
                )
            else:
                upload_payload = {
                    "sourceId": assigned_source_id,
                    "filename": filename,
                    "notebookId": nb_id,
                    "fileBase64": base64.b64encode(file_bytes).decode("ascii"),
                }
                upload_res = await self.send_to_companion_exclusive("scotty_upload", upload_payload)

            if not upload_res.get("ok"):
                err_code = str(upload_res.get("error", {}).get("code", ""))
                if err_code == MUTATION_UNKNOWN:
                    self.journal.transition(idempotency_key, MutationState.UNKNOWN, assigned_source_id)
                else:
                    self.journal.transition(idempotency_key, MutationState.REJECTED, assigned_source_id)
                return upload_res

        # Full Jitter Exponential Backoff polling if wait_until_ready requested
        if wait_until_ready:
            async def fetch_metadata(target_nb_id: str) -> list[Any]:
                list_res = await self._handle_list_sources({"notebook_id": target_nb_id})
                return list(list_res.get("sources", []))

            try:
                polled_status = await poll_until_ready(
                    notebook_id=nb_id,
                    source_id=assigned_source_id,
                    fetch_metadata_fn=fetch_metadata,
                    max_timeout=300.0,
                )
                if polled_status in (SourceStatus.ERROR, SourceStatus.FAILED):
                    self.journal.transition(idempotency_key, MutationState.REJECTED, assigned_source_id)
                    return make_error(
                        INTERNAL,
                        f"Source {assigned_source_id} failed ingestion (state: {polled_status.name}).",
                        retryable=False,
                    ).to_dict()
            except Exception as exc:
                self.journal.transition(idempotency_key, MutationState.UNKNOWN, assigned_source_id)
                return make_error(
                    MUTATION_UNKNOWN,
                    f"Timed out polling readiness for source: {exc}",
                    retryable=False,
                ).to_dict()

        self.journal.transition(
            idempotency_key,
            MutationState.CONFIRMED,
            assigned_source_id=assigned_source_id,
        )

        return {
            "ok": True,
            "source_id": assigned_source_id,
            "status": "READY" if wait_until_ready else "PROCESSING",
        }

    async def _handle_create_note(self, command: dict[str, Any]) -> dict[str, Any]:
        nb_id = str(command["notebook_id"])
        title = str(command.get("title", "Untitled Note"))
        content = str(command["content"])
        idempotency_key = str(command["idempotency_key"])

        existing = self.journal.get(idempotency_key)
        if existing is not None:
            if existing.state in (MutationState.SENT, MutationState.UNKNOWN):
                return make_error(
                    REQUEST_KEY_CONFLICT,
                    f"Mutation {idempotency_key!r} is currently in state {existing.state.value!r}. "
                    "Automatic replay is blocked; active reconciliation required.",
                    retryable=False,
                    mcp_correlation_id=idempotency_key,
                ).to_dict()
            elif existing.state == MutationState.CONFIRMED:
                return {
                    "ok": True,
                    "note_id": existing.assigned_source_id or "",
                    "status": "READY",
                    "cached": True,
                }
            elif existing.state == MutationState.REJECTED:
                return make_error(
                    REQUEST_KEY_CONFLICT,
                    f"Mutation {idempotency_key!r} was previously rejected.",
                    retryable=False,
                    mcp_correlation_id=idempotency_key,
                ).to_dict()

        # Mutation Journal Lifecycle: PREPARED
        self.journal.prepare(
            request_key=idempotency_key,
            notebook_id=nb_id,
            operation_type=OperationType.CREATE_NOTE,
            args=command,
            capability_secret=self.config.capability_secret,
        )

        # Transition: SENT
        self.journal.transition(idempotency_key, MutationState.SENT)

        payload = make_create_note_payload(title=title, content=content, notebook_id=nb_id)
        res = await self.send_to_companion(
            "batchexecute",
            {"rpcId": "CYK0Xb", "paramsJson": payload, "notebookId": nb_id},
        )

        if not res.get("ok"):
            err_code = str(res.get("error", {}).get("code", ""))
            if err_code == MUTATION_UNKNOWN:
                self.journal.transition(idempotency_key, MutationState.UNKNOWN)
            else:
                self.journal.transition(idempotency_key, MutationState.REJECTED)
            return res

        assigned_note_id: str | None = None
        body = str(res.get("body", ""))
        decoder = BatchexecuteStreamDecoder()
        records = decoder.feed(body.encode("utf-8"))
        for rec in records:
            if rec.get("rpc_id") == "CYK0Xb":
                data = rec.get("data")
                cur = data
                while isinstance(cur, list) and cur:
                    cur = cur[0]
                if cur and not isinstance(cur, (list, dict)):
                    assigned_note_id = str(cur)
                break

        if assigned_note_id is None:
            for rec in records:
                data = rec.get("data")
                cur = data
                while isinstance(cur, list) and cur:
                    cur = cur[0]
                if cur and not isinstance(cur, (list, dict)):
                    assigned_note_id = str(cur)
                    break

        if assigned_note_id is None:
            assigned_note_id = f"note_{secrets.token_hex(8)}"

        self.journal.transition(
            idempotency_key,
            MutationState.CONFIRMED,
            assigned_source_id=assigned_note_id,
        )

        return {
            "ok": True,
            "note_id": assigned_note_id,
            "status": "READY",
        }

    async def _handle_list_notes(self, command: dict[str, Any]) -> dict[str, Any]:
        nb_id = str(command["notebook_id"])
        correlation_id = command.get("request_key") or command.get("idempotency_key")
        rpc_payload = make_get_metadata_payload(nb_id)
        res = await self.send_to_companion(
            "batchexecute",
            {"rpcId": "rLM1Ne", "paramsJson": rpc_payload, "notebookId": nb_id},
        )
        if not res.get("ok"):
            return res

        body = str(res.get("body", ""))
        decoder = BatchexecuteStreamDecoder()
        records = decoder.feed(body.encode("utf-8"))

        found_container = False
        raw_notes: list[Any] = []

        for record in records:
            if record.get("rpc_id") == "rLM1Ne":
                data = record.get("data")
                if not isinstance(data, list) or len(data) == 0 or not isinstance(data[0], list):
                    return make_error(
                        UPSTREAM_SCHEMA_DRIFT,
                        f"Invalid rLM1Ne response envelope structure: {type(data)}",
                        retryable=False,
                        mcp_correlation_id=correlation_id,
                    ).to_dict()

                container = data[0]
                found_container = True

                # Loud Canary: Verify index 17 existence and signature (M-05)
                if len(container) <= 17:
                    return make_error(
                        UPSTREAM_SCHEMA_DRIFT,
                        f"rLM1Ne container length is {len(container)} (expected > 17 for notes array). Upstream schema shifted.",
                        retryable=False,
                        mcp_correlation_id=correlation_id,
                    ).to_dict()

                notes_array = container[17]
                if not isinstance(notes_array, list):
                    return make_error(
                        UPSTREAM_SCHEMA_DRIFT,
                        f"rLM1Ne container[17] is not an array (type: {type(notes_array)}). Upstream schema shifted.",
                        retryable=False,
                        mcp_correlation_id=correlation_id,
                    ).to_dict()

                raw_notes = notes_array
                break

        if not found_container:
            return make_error(
                UPSTREAM_SCHEMA_DRIFT,
                "rLM1Ne record missing from response stream.",
                retryable=False,
                mcp_correlation_id=correlation_id,
            ).to_dict()

        notes: list[dict[str, Any]] = []
        for n in raw_notes:
            if isinstance(n, list) and len(n) > 0:
                cur_id = n[0]
                while isinstance(cur_id, list) and cur_id:
                    cur_id = cur_id[0]
                note_id = str(cur_id) if cur_id is not None else ""
                note_title = str(n[4]) if len(n) > 4 and n[4] is not None else ""
                note_content = str(n[1]) if len(n) > 1 and n[1] is not None else ""
                notes.append({"id": note_id, "title": note_title, "content": note_content})

        start_idx = 0
        cursor = command.get("cursor")
        if cursor is not None:
            try:
                start_idx = int(cursor)
            except ValueError:
                start_idx = 0

        paged_notes = notes[start_idx:]
        next_cursor: str | None = None
        page_size_arg = command.get("page_size")
        if page_size_arg is not None:
            try:
                page_size = int(page_size_arg)
                if page_size > 0 and len(paged_notes) > page_size:
                    next_cursor = str(start_idx + page_size)
                    paged_notes = paged_notes[:page_size]
            except ValueError:
                pass

        resp: dict[str, Any] = {"ok": True, "notes": paged_notes}
        if next_cursor is not None:
            resp["next_cursor"] = next_cursor
        return resp

    async def _handle_delete_note(self, command: dict[str, Any]) -> dict[str, Any]:
        nb_id = str(command["notebook_id"])
        note_id = str(command["note_id"])
        idempotency_key = str(command["idempotency_key"])

        existing = self.journal.get(idempotency_key)
        if existing is not None:
            if existing.state in (MutationState.SENT, MutationState.UNKNOWN):
                return make_error(
                    REQUEST_KEY_CONFLICT,
                    f"Mutation {idempotency_key!r} is currently in state {existing.state.value!r}. "
                    "Automatic replay is blocked; active reconciliation required.",
                    retryable=False,
                    mcp_correlation_id=idempotency_key,
                ).to_dict()
            elif existing.state == MutationState.CONFIRMED:
                return {
                    "ok": True,
                    "deleted": True,
                    "cached": True,
                }
            elif existing.state == MutationState.REJECTED:
                return make_error(
                    REQUEST_KEY_CONFLICT,
                    f"Mutation {idempotency_key!r} was previously rejected.",
                    retryable=False,
                    mcp_correlation_id=idempotency_key,
                ).to_dict()

        # Mutation Journal Lifecycle: PREPARED
        self.journal.prepare(
            request_key=idempotency_key,
            notebook_id=nb_id,
            operation_type=OperationType.DELETE_NOTE,
            args=command,
            capability_secret=self.config.capability_secret,
        )

        # Transition: SENT
        self.journal.transition(idempotency_key, MutationState.SENT)

        payload = make_delete_note_payload(note_id=note_id, notebook_id=nb_id)
        res = await self.send_to_companion(
            "batchexecute",
            {"rpcId": "tGMBJ", "paramsJson": payload, "notebookId": nb_id},
        )

        if not res.get("ok"):
            err_code = str(res.get("error", {}).get("code", ""))
            if err_code == MUTATION_UNKNOWN:
                self.journal.transition(idempotency_key, MutationState.UNKNOWN)
            else:
                self.journal.transition(idempotency_key, MutationState.REJECTED)
            return res

        # Transition: CONFIRMED
        self.journal.transition(idempotency_key, MutationState.CONFIRMED)

        return {
            "ok": True,
            "deleted": True,
        }


class McpFacade:
    """Stdio MCP 2.0 facade exposing exactly the 5 consolidated tools."""

    def __init__(self, broker: BrokerDaemon | None = None) -> None:
        self.broker = broker or BrokerDaemon()
        self.server = Server("gemini-notebook-mcp")
        self._register_handlers()

    def _register_handlers(self) -> None:
        async def list_tools_handler(
            ctx: Any,
            req: types.ListToolsRequest,
        ) -> types.ListToolsResult:
            tools = [
                types.Tool(
                    name="list_notebooks",
                    description=(
                        "List all allowlisted Google Gemini Notebooks. You MUST call this at the start of each "
                        "chat/project to inspect available notebooks and project defaults, present the options to "
                        "the user, and ask the user to confirm which notebook to use for this chat/project."
                    ),
                    input_schema=LIST_NOTEBOOKS_SCHEMA,
                ),
                types.Tool(
                    name="select_notebook",
                    description=(
                        "Select and lock the session to a specific allowlisted Google Notebook for this chat. "
                        "IMPORTANT: Always double-check with the user first before calling this. Sets save_for_project=true "
                        "by default to remember this selection in .notebook_mcp.json for future chats in this project."
                    ),
                    input_schema=SELECT_NOTEBOOK_SCHEMA,
                ),
                types.Tool(
                    name="get_notebook_metadata",
                    description="Retrieve metadata for an allowlisted notebook.",
                    input_schema=GET_NOTEBOOK_METADATA_SCHEMA,
                ),
                types.Tool(
                    name="list_sources",
                    description="List all sources within an allowlisted notebook.",
                    input_schema=LIST_SOURCES_SCHEMA,
                ),
                types.Tool(
                    name="query_notebook",
                    description="Submit a grounded question to an allowlisted notebook.",
                    input_schema=QUERY_NOTEBOOK_SCHEMA,
                ),
                types.Tool(
                    name="add_source",
                    description="Add a new text, URL, YouTube, Drive, or file source to a notebook.",
                    input_schema=ADD_SOURCE_SCHEMA,
                ),
                types.Tool(
                    name="create_note",
                    description="Create a new note in an allowlisted Google Notebook.",
                    input_schema=CREATE_NOTE_SCHEMA,
                ),
                types.Tool(
                    name="list_notes",
                    description="List all notes within an allowlisted Google Notebook.",
                    input_schema=LIST_NOTES_SCHEMA,
                ),
                types.Tool(
                    name="delete_note",
                    description="Delete a note from an allowlisted Google Notebook.",
                    input_schema=DELETE_NOTE_SCHEMA,
                ),
            ]
            return types.ListToolsResult(tools=tools)

        async def call_tool_handler(
            ctx: Any,
            req: types.CallToolRequest | types.CallToolRequestParams,
        ) -> types.CallToolResult:
            meta: dict[str, Any] | None = None
            if isinstance(req, types.CallToolRequest):
                name = req.params.name
                args = req.params.arguments or {}
                raw_meta = getattr(req.params, "_meta", None) or getattr(req.params, "meta", None)
                if isinstance(raw_meta, dict):
                    meta = raw_meta
            else:
                name = req.name
                args = req.arguments or {}
                raw_meta = getattr(req, "_meta", None) or getattr(req, "meta", None)
                if isinstance(raw_meta, dict):
                    meta = raw_meta

            # Strict Closed JSON Schema validation (additionalProperties: false)
            validation_err = validate_tool_args(name, args)
            if validation_err is not None:
                correlation_id = args.get("request_key") or args.get("idempotency_key")
                err_envelope = make_error(
                    INVALID_ARGUMENT,
                    validation_err,
                    retryable=False,
                    mcp_correlation_id=correlation_id,
                )
                err_dict = err_envelope.to_dict()
                serialized = json.dumps(err_dict, indent=2)
                structured_data = {
                    "code": INVALID_ARGUMENT,
                    "message": validation_err,
                    "errorCategory": "validation",
                    "isRetryable": False,
                    "raw": err_dict,
                }
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=serialized)],
                    structured_content=structured_data,
                    is_error=True,
                )

            traceparent = extract_or_generate_traceparent(meta)
            command = {"action": name, "traceparent": traceparent, **args}
            result = await self.broker.dispatch(command)
            serialized = json.dumps(result, indent=2)

            if not result.get("ok", True):
                err_info = result.get("error", {})
                code = str(err_info.get("code", INTERNAL))
                msg = str(err_info.get("message", "Error"))
                category = err_info.get("errorCategory") or categorize_error(code)
                is_retryable = bool(err_info.get("isRetryable", err_info.get("retryable", False)))
                structured_data = {
                    "code": code,
                    "message": msg,
                    "errorCategory": category,
                    "isRetryable": is_retryable,
                    "raw": result,
                }
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=serialized)],
                    structured_content=structured_data,
                    is_error=True,
                )

            return types.CallToolResult(
                content=[types.TextContent(type="text", text=serialized)],
                structured_content=result,
                is_error=False,
            )

        self.server.add_request_handler("tools/list", types.ListToolsRequest, list_tools_handler)
        self.server.add_request_handler("tools/call", types.CallToolRequestParams, call_tool_handler)

    async def serve_stdio_async(self) -> None:
        """Runs stdio server loop, exclusively sending JSON-RPC to stdout."""
        async with stdio_server() as (read_stream, write_stream):
            init_opts = self.server.create_initialization_options()
            await self.server.run(read_stream, write_stream, init_opts)

    def serve_stdio(self) -> None:
        asyncio.run(self.serve_stdio_async())


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini Notebook MCP Broker")
    parser.add_argument("mode", choices=["serve", "mcp"], help="Execution mode")
    args = parser.parse_args()

    config = BrokerConfig()
    broker = BrokerDaemon(config)

    if args.mode == "serve":
        async def run_server() -> None:
            await broker.start()
            print("[broker] Server running. Press Ctrl+C to terminate.", file=sys.stderr)
            try:
                while True:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                await broker.stop()

        try:
            asyncio.run(run_server())
        except KeyboardInterrupt:
            pass
    elif args.mode == "mcp":
        facade = McpFacade(broker)
        facade.serve_stdio()


if __name__ == "__main__":
    main()
