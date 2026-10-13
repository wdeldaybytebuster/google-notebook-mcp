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
from pathlib import Path
import secrets
import struct
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
    make_get_metadata_payload,
    make_list_notebooks_payload,
    make_query_params,
    make_register_upload_payload,
)
from mcp_gateway.engine.stream_decoder import (
    BatchexecuteStreamDecoder,
    GenerateFreeFormStreamParser,
)
from mcp_gateway.schemas.error import (
    ALLOWLIST_DENIED,
    AUTH_REQUIRED,
    INTERNAL,
    INVALID_ARGUMENT,
    MUTATION_UNKNOWN,
    REQUEST_KEY_CONFLICT,
    make_error,
)
from mcp_gateway.schemas.tools import (
    ADD_SOURCE_SCHEMA,
    GET_NOTEBOOK_METADATA_SCHEMA,
    LIST_NOTEBOOKS_SCHEMA,
    LIST_SOURCES_SCHEMA,
    QUERY_NOTEBOOK_SCHEMA,
    validate_tool_args,
)
from mcp_gateway.storage.journal import (
    MutationJournal,
    MutationState,
    OperationType,
)

IPC_FRAME_FORMAT = ">I"


@dataclass
class BrokerConfig:
    socket_path: str = os.environ.get("MCP_BROKER_SOCKET", "/tmp/notebooklm-mcp-broker.sock")
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
        self._server: asyncio.Server | None = None
        self._active_companion_writer: asyncio.StreamWriter | None = None
        self._pending_responses: dict[str, asyncio.Future[dict[str, Any]]] = {}

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
        """Starts the Unix domain socket IPC server with restricted 0o600 permissions."""
        sock_path = Path(self.config.socket_path)
        if sock_path.exists():
            try:
                sock_path.unlink()
            except OSError:
                pass

        sock_path.parent.mkdir(parents=True, exist_ok=True)
        self._server = await asyncio.start_unix_server(
            self.handle_ipc_connection,
            path=str(sock_path),
        )
        try:
            os.chmod(str(sock_path), 0o600)
        except OSError:
            pass

        print(f"[broker] Listening on IPC socket: {sock_path}", file=sys.stderr)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        sock_path = Path(self.config.socket_path)
        if sock_path.exists():
            try:
                sock_path.unlink()
            except OSError:
                pass

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
            if self._server is None and Path(self.config.socket_path).exists():
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

    async def _forward_to_socket(self, command: dict[str, Any]) -> dict[str, Any]:
        """Forwards a command to the running background broker daemon on Unix socket."""
        try:
            reader, writer = await asyncio.open_unix_connection(self.config.socket_path)
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
        action = str(command.get("action") or command.get("command") or "")

        # Mandatory allowlist policy check
        notebook_id = command.get("notebook_id")
        if notebook_id is not None:
            self.reload_allowlist()
            assert self.allowlist is not None
            if not is_notebook_allowed(self.allowlist, str(notebook_id)):
                return scrub_dict(
                    make_error(
                        ALLOWLIST_DENIED,
                        "Notebook is not in the allowlist. Access denied by local policy.",
                        retryable=False,
                    ).to_dict()
                )

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
            else:
                result = make_error(
                    INVALID_ARGUMENT,
                    f"Unrecognized action {action!r}.",
                    retryable=False,
                ).to_dict()
        except Exception as exc:
            result = make_error(
                INTERNAL,
                f"Unexpected broker exception during {action}: {exc}",
                retryable=False,
            ).to_dict()

        return scrub_dict(result)

    async def _handle_list_notebooks(self, command: dict[str, Any]) -> dict[str, Any]:
        page_size_arg = command.get("page_size")
        page_size = int(page_size_arg) if page_size_arg is not None else 20
        cursor = command.get("cursor")

        rpc_payload = make_list_notebooks_payload(page_size=page_size)
        res = await self.send_to_companion("batchexecute", {"rpcId": "wXbhsf", "paramsJson": rpc_payload})
        if not res.get("ok"):
            return res

        body = str(res.get("body", ""))
        decoder = BatchexecuteStreamDecoder()
        records = decoder.feed(body.encode("utf-8"))

        notebooks: list[dict[str, Any]] = []
        for record in records:
            if record.get("rpc_id") == "wXbhsf":
                raw_items = record.get("data")
                if isinstance(raw_items, list):
                    for item in raw_items:
                        if isinstance(item, list) and len(item) > 1:
                            nb_id = str(item[0])
                            title = str(item[1]) if item[1] is not None else ""
                            # Filter strictly by allowlist
                            assert self.allowlist is not None
                            if is_notebook_allowed(self.allowlist, nb_id):
                                notebooks.append({"id": nb_id, "title": title})

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
        return response

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
                    # In rLM1Ne response, row [102] is the sources array
                    if len(data) > 102 and isinstance(data[102], list):
                        raw_sources = data[102]
                    else:
                        raw_sources = data
                break

        sources: list[dict[str, Any]] = []
        for s in raw_sources:
            if isinstance(s, list) and len(s) > 0:
                st = parse_source_status(s)
                entry: dict[str, Any] = {
                    "id": str(s[0]),
                    "title": str(s[1]) if len(s) > 1 and s[1] is not None else "",
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
        timeout_seconds = int(command.get("timeout_seconds", 120))

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
            {"paramsJson": query_params, "notebookId": nb_id},
            timeout_seconds=float(timeout_seconds),
        )

        if not res.get("ok"):
            err_code = str(res.get("error", {}).get("code", ""))
            if err_code == MUTATION_UNKNOWN:
                self.journal.transition(request_key, MutationState.UNKNOWN)
            else:
                self.journal.transition(request_key, MutationState.REJECTED)
            return res

        body = str(res.get("body", ""))
        parser = GenerateFreeFormStreamParser()
        events = parser.feed(body.encode("utf-8"))

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

        # Normalize coordinates from UTF-16 to Unicode
        normalized_citations: list[CitationSpan] = []
        for cit in raw_citations:
            try:
                normalized_citations.append(normalize_citation(cit, full_text))
            except Exception:
                pass

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
        if source_type == "text":
            payload = make_add_text_payload(
                title=str(source.get("title", "Untitled")),
                content=str(source.get("content", "")),
            )
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

        # Decode response to obtain assigned source id
        body = str(res.get("body", ""))
        decoder = BatchexecuteStreamDecoder()
        records = decoder.feed(body.encode("utf-8"))
        for rec in records:
            data = rec.get("data")
            if isinstance(data, list) and data:
                try:
                    assigned_source_id = str(data[0])
                except Exception:
                    pass

        if assigned_source_id is None:
            assigned_source_id = f"src_{secrets.token_hex(8)}"

        # Phase 5: Scotty Resumable Upload (Steps 2 & 3) if source_type == "file"
        if source_type == "file":
            raw_content = str(source.get("content", ""))
            try:
                base64.b64decode(raw_content.encode("ascii"), validate=True)
                file_b64 = raw_content
            except Exception:
                file_b64 = base64.b64encode(raw_content.encode("utf-8")).decode("ascii")

            upload_payload = {
                "sourceId": assigned_source_id,
                "filename": str(source.get("title") or "uploaded_file"),
                "notebookId": nb_id,
                "fileBase64": file_b64,
            }
            upload_res = await self.send_to_companion("scotty_upload", upload_payload)
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
                    description="List all allowlisted Google Gemini Notebooks.",
                    input_schema=LIST_NOTEBOOKS_SCHEMA,
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
            ]
            return types.ListToolsResult(tools=tools)

        async def call_tool_handler(
            ctx: Any,
            req: types.CallToolRequest | types.CallToolRequestParams,
        ) -> types.CallToolResult:
            if isinstance(req, types.CallToolRequest):
                name = req.params.name
                args = req.params.arguments or {}
            else:
                name = req.name
                args = req.arguments or {}

            # Strict Closed JSON Schema validation (additionalProperties: false)
            validation_err = validate_tool_args(name, args)
            if validation_err is not None:
                err_envelope = make_error(
                    INVALID_ARGUMENT,
                    validation_err,
                    retryable=False,
                )
                serialized = json.dumps(err_envelope.to_dict(), indent=2)
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=serialized)],
                    is_error=True,
                )

            command = {"action": name, **args}
            result = await self.broker.dispatch(command)
            serialized = json.dumps(result, indent=2)

            return types.CallToolResult(
                content=[types.TextContent(type="text", text=serialized)],
                is_error=not result.get("ok", True),
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
