from __future__ import annotations

import asyncio
import json
from pathlib import Path
import struct
from typing import Any, cast
import pytest

from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon, McpFacade
from mcp_gateway.schemas.error import SESSION_UNLOCKED
from mcp_gateway.storage.journal import MutationState
from mcp_gateway.transport import open_ipc_connection
import mcp.types as types

IPC_FRAME_FORMAT = ">I"


class MockBrowserCompanion:
    """Simulates the Chrome extension + Native Messaging Host bridge over Unix socket."""

    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        self._reader, self._writer = await open_ipc_connection(self.socket_path)
        self._running = True

        # Send handshake hello frame
        hello = {"type": "hello"}
        payload = json.dumps(hello).encode("utf-8")
        self._writer.write(struct.pack(IPC_FRAME_FORMAT, len(payload)) + payload)
        await self._writer.drain()

        # Read hello_ack
        length_bytes = await self._reader.readexactly(4)
        (msg_len,) = struct.unpack(IPC_FRAME_FORMAT, length_bytes)
        ack_bytes = await self._reader.readexactly(msg_len)
        ack_msg = json.loads(ack_bytes.decode("utf-8"))
        assert ack_msg.get("type") == "hello_ack"

        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        assert self._reader is not None
        assert self._writer is not None
        try:
            while self._running:
                length_bytes = await self._reader.readexactly(4)
                (msg_len,) = struct.unpack(IPC_FRAME_FORMAT, length_bytes)
                payload_bytes = await self._reader.readexactly(msg_len)
                msg: dict[str, Any] = json.loads(payload_bytes.decode("utf-8"))

                command = msg.get("command")
                req_id = msg.get("requestId")
                payload = msg.get("payload", {})

                reply: dict[str, Any] = {"ok": True, "requestId": req_id}

                if command == "batchexecute":
                    rpc_id = payload.get("rpcId")
                    if rpc_id == "wXbhsf":
                        # Returns 3 notebooks: nb-mock-1, nb-mock-2 (allowlisted), and nb-forbidden (not allowlisted)
                        inner_data = [
                            ["nb-mock-1", "Mock Notebook One", None, None, None, 1],
                            ["nb-mock-2", "Mock Notebook Two", None, None, None, 1],
                            ["nb-forbidden", "Forbidden Notebook", None, None, None, 1],
                        ]
                        frame = [["wrb.fr", "wXbhsf", json.dumps(inner_data), None, None, None, None, 1]]
                        reply["body"] = ")]}'\n" + json.dumps(frame)
                    elif rpc_id == "rLM1Ne":
                        # Returns 2 sources
                        inner_data = [
                            ["src-1", "Source Alpha", None, None, 2],
                            ["src-2", "Source Beta", None, None, 2],
                        ]
                        frame = [["wrb.fr", "rLM1Ne", json.dumps(inner_data), None, None, None, None, 1]]
                        reply["body"] = ")]}'\n" + json.dumps(frame)
                    elif rpc_id == "izAoDd":
                        raw_inner: list[Any] = ["src-created-999"]
                        frame = [["wrb.fr", "izAoDd", json.dumps(raw_inner), None, None, None, None, 1]]
                        reply["body"] = ")]}'\n" + json.dumps(frame)
                    else:
                        reply["body"] = ")]}'\n[]"

                elif command == "query_stream":
                    # Stream chunks: text_delta + citation + done sentinel
                    delta_line = json.dumps([["Hello from mock NotebookLM!", None]]) + "\n"
                    cit_line = json.dumps([[[["src-1", 0, 5, None]]]]) + "\n"
                    done_line = json.dumps([None]) + "\n"
                    reply["body"] = delta_line + cit_line + done_line

                out_bytes = json.dumps(reply).encode("utf-8")
                self._writer.write(struct.pack(IPC_FRAME_FORMAT, len(out_bytes)) + out_bytes)
                await self._writer.drain()

        except (asyncio.IncompleteReadError, ConnectionResetError, asyncio.CancelledError):
            pass

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass


@pytest.fixture
def allowlist_file(tmp_path: Path) -> Path:
    p = tmp_path / "allowlist.json"
    p.write_text(
        json.dumps({
            "version": 1,
            "provider_mode": "browser",
            "accounts": ["engineer@example.com"],
            "notebooks": ["nb-mock-1", "nb-mock-2"],
        }),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def socket_path(tmp_path: Path) -> str:
    return str(tmp_path / "e2e_mock_broker.sock")


@pytest.fixture
def broker(tmp_path: Path, allowlist_file: Path, socket_path: str) -> BrokerDaemon:
    cfg = BrokerConfig(
        socket_path=socket_path,
        allowlist_path=allowlist_file,
        journal_db_path=tmp_path / "e2e_journal.db",
    )
    return BrokerDaemon(cfg)


def extract_text_payload(result: types.CallToolResult) -> dict[str, Any]:
    assert len(result.content) > 0
    item = result.content[0]
    assert isinstance(item, types.TextContent)
    return cast(dict[str, Any], json.loads(item.text))


@pytest.mark.asyncio
async def test_hermetic_end_to_end_mcp_flow(
    broker: BrokerDaemon,
    socket_path: str,
) -> None:
    # 1. Start Broker Daemon on Unix domain socket
    await broker.start()

    # 2. Start Mock Browser Companion and connect
    companion = MockBrowserCompanion(socket_path)
    await companion.start()

    facade = McpFacade(broker)
    call_entry = facade.server._request_handlers.get("tools/call")
    assert call_entry is not None

    try:
        # 3. Test list_notebooks (with allowlist filtering)
        req_list = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name="list_notebooks", arguments={}),
        )
        res_list = await call_entry.handler(cast(Any, None), req_list)
        assert isinstance(res_list, types.CallToolResult)
        assert res_list.is_error is False
        body_list = extract_text_payload(res_list)
        assert body_list["ok"] is True
        nbs = body_list["notebooks"]
        # nb-forbidden was in raw upstream response but MUST be filtered out by allowlist!
        assert len(nbs) == 2
        nb_ids = [n["id"] for n in nbs]
        assert "nb-mock-1" in nb_ids
        assert "nb-mock-2" in nb_ids
        assert "nb-forbidden" not in nb_ids

        # Verify ADR-011 gate: pre-lock call is rejected
        req_unlocked = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="get_notebook_metadata",
                arguments={"notebook_id": "nb-mock-1"},
            ),
        )
        res_unlocked = await call_entry.handler(cast(Any, None), req_unlocked)
        assert isinstance(res_unlocked, types.CallToolResult)
        assert res_unlocked.is_error is True
        assert extract_text_payload(res_unlocked)["error"]["code"] == SESSION_UNLOCKED

        # Lock session via select_notebook
        req_select = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="select_notebook",
                arguments={"notebook_id": "nb-mock-1"},
            ),
        )
        res_select = await call_entry.handler(cast(Any, None), req_select)
        assert isinstance(res_select, types.CallToolResult)
        assert res_select.is_error is False
        body_select = extract_text_payload(res_select)
        assert body_select["ok"] is True
        assert body_select["status"] == "LOCKED"

        # 4. Test get_notebook_metadata & list_sources
        req_meta = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="get_notebook_metadata",
                arguments={"notebook_id": "nb-mock-1"},
            ),
        )
        res_meta = await call_entry.handler(cast(Any, None), req_meta)
        assert isinstance(res_meta, types.CallToolResult)
        assert res_meta.is_error is False
        body_meta = extract_text_payload(res_meta)
        assert body_meta["ok"] is True
        assert body_meta["metadata"]["notebook_id"] == "nb-mock-1"

        req_sources = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="list_sources",
                arguments={"notebook_id": "nb-mock-1"},
            ),
        )
        res_sources = await call_entry.handler(cast(Any, None), req_sources)
        assert isinstance(res_sources, types.CallToolResult)
        assert res_sources.is_error is False
        body_sources = extract_text_payload(res_sources)
        assert body_sources["ok"] is True
        sources = body_sources["sources"]
        assert len(sources) == 2
        assert sources[0]["id"] == "src-1"
        assert sources[0]["title"] == "Source Alpha"
        assert sources[1]["id"] == "src-2"
        assert sources[1]["title"] == "Source Beta"

        # 5. Test query_notebook (with chunked gRPC-web stream and UTF-16 coordinate conversion)
        req_query = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="query_notebook",
                arguments={
                    "notebook_id": "nb-mock-1",
                    "question": "What is in Source Alpha?",
                    "request_key": "e2e-query-key-1",
                    "source_ids": ["src-1"],
                },
            ),
        )
        res_query = await call_entry.handler(cast(Any, None), req_query)
        assert isinstance(res_query, types.CallToolResult)
        assert res_query.is_error is False
        body_query = extract_text_payload(res_query)
        assert body_query["ok"] is True
        assert "Hello from mock NotebookLM!" in body_query["answer"]
        assert len(body_query["citations"]) == 1
        cit = body_query["citations"][0]
        assert cit["source_id"] == "src-1"
        assert cit["start_char"] == 0
        assert cit["end_char"] == 5
        assert cit["text_snippet"] == "Hello"

        # Verify mutation journal committed to CONFIRMED
        q_record = broker.journal.get("e2e-query-key-1")
        assert q_record is not None
        assert q_record.state == MutationState.CONFIRMED

        # 6. Test add_source (text variant)
        req_add_text = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="add_source",
                arguments={
                    "notebook_id": "nb-mock-1",
                    "idempotency_key": "e2e-add-text-1",
                    "source": {
                        "type": "text",
                        "title": "E2E Added Doc",
                        "content": "This is synthetic body text.",
                    },
                },
            ),
        )
        res_add_text = await call_entry.handler(cast(Any, None), req_add_text)
        assert isinstance(res_add_text, types.CallToolResult)
        assert res_add_text.is_error is False
        body_add_text = extract_text_payload(res_add_text)
        assert body_add_text["ok"] is True
        assert body_add_text["source_id"] == "src-created-999"

        # Verify mutation journal state is CONFIRMED
        add_record = broker.journal.get("e2e-add-text-1")
        assert add_record is not None
        assert add_record.state == MutationState.CONFIRMED
        assert add_record.assigned_source_id == "src-created-999"

        # 7. Test add_source (URL variant)
        req_add_url = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="add_source",
                arguments={
                    "notebook_id": "nb-mock-1",
                    "idempotency_key": "e2e-add-url-2",
                    "source": {
                        "type": "url",
                        "url": "https://notebooklm.google.com/test-article",
                    },
                },
            ),
        )
        res_add_url = await call_entry.handler(cast(Any, None), req_add_url)
        assert isinstance(res_add_url, types.CallToolResult)
        assert res_add_url.is_error is False
        body_add_url = extract_text_payload(res_add_url)
        assert body_add_url["ok"] is True
        assert body_add_url["source_id"] == "src-created-999"

        url_record = broker.journal.get("e2e-add-url-2")
        assert url_record is not None
        assert url_record.state == MutationState.CONFIRMED

    finally:
        await companion.stop()
        await broker.stop()
