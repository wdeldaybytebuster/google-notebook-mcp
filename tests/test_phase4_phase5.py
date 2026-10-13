"""Tests for Phase 4 (Consolidated 5-Tool MCP Surface & Facade)
and Phase 5 (Scotty Resumable Uploads & Readiness Polling).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
import pytest

from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon, McpFacade
from mcp_gateway.engine.readiness_poller import (
    SourceStatus,
    parse_source_status,
    poll_until_ready,
)
from mcp_gateway.schemas.error import (
    ALLOWLIST_DENIED,
    INTERNAL,
    INVALID_ARGUMENT,
    MUTATION_UNKNOWN,
    make_error,
)
from mcp_gateway.schemas.tools import (
    ADD_SOURCE_SCHEMA,
    GET_NOTEBOOK_METADATA_SCHEMA,
    LIST_NOTEBOOKS_SCHEMA,
    LIST_SOURCES_SCHEMA,
    QUERY_NOTEBOOK_SCHEMA,
    AddSourceInput,
    GetNotebookMetadataInput,
    ListNotebooksInput,
    ListSourcesInput,
    QueryNotebookInput,
    SourceSpec,
    validate_tool_args,
)
from mcp_gateway.storage.journal import MutationState


@pytest.fixture
def allowlist_file(tmp_path: Path) -> Path:
    p = tmp_path / "allowlist.json"
    data = {
        "version": 1,
        "provider_mode": "browser",
        "accounts": ["engineer@example.com"],
        "notebooks": ["nb-1", "nb-2"],
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture
def broker(tmp_path: Path, allowlist_file: Path) -> BrokerDaemon:
    cfg = BrokerConfig(
        socket_path=str(tmp_path / "test_phase45.sock"),
        allowlist_path=allowlist_file,
        journal_db_path=tmp_path / "test_phase45.db",
    )
    return BrokerDaemon(cfg)


# ---------------------------------------------------------------------------
# Phase 4: list_sources row [102] extraction and readiness states
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_extracts_from_row_102(broker: BrokerDaemon) -> None:
    """rLM1Ne response row [102] must be parsed for sources and readiness states."""
    # Build a metadata payload where index 102 contains the sources array
    sources_array = [
        ["src-a", "Document Alpha", None, None, 2],  # READY (2)
        ["src-b", "Document Beta", None, None, 1],   # PROCESSING (1)
        ["src-c", "Document Gamma", None, None, 3],  # ERROR / FAILED (3)
    ]
    raw_metadata: list[Any] = [None] * 105
    raw_metadata[102] = sources_array

    frame = [["wrb.fr", "rLM1Ne", json.dumps(raw_metadata), None, None, None, None, 1]]
    fake_body = ")]}'\n" + json.dumps(frame)

    with patch.object(
        broker,
        "send_to_companion",
        new=AsyncMock(return_value={"ok": True, "body": fake_body}),
    ):
        res = await broker.dispatch({"action": "list_sources", "notebook_id": "nb-1"})

    assert res["ok"] is True
    sources = res["sources"]
    assert len(sources) == 3

    assert sources[0]["id"] == "src-a"
    assert sources[0]["title"] == "Document Alpha"
    assert sources[0]["status"] == "READY"
    assert sources[0]["status_code"] == 2

    assert sources[1]["id"] == "src-b"
    assert sources[1]["title"] == "Document Beta"
    assert sources[1]["status"] == "PROCESSING"
    assert sources[1]["status_code"] == 1

    assert sources[2]["id"] == "src-c"
    assert sources[2]["title"] == "Document Gamma"
    assert sources[2]["status"] in ("ERROR", "FAILED")
    assert sources[2]["status_code"] == 3


@pytest.mark.asyncio
async def test_list_sources_pagination(broker: BrokerDaemon) -> None:
    """list_sources respects page_size and cursor parameters."""
    sources_array = [
        [f"src-{i}", f"Document {i}", None, None, 2] for i in range(5)
    ]
    frame = [["wrb.fr", "rLM1Ne", json.dumps(sources_array), None, None, None, None, 1]]
    fake_body = ")]}'\n" + json.dumps(frame)

    with patch.object(
        broker,
        "send_to_companion",
        new=AsyncMock(return_value={"ok": True, "body": fake_body}),
    ):
        # First page of 2
        p1 = await broker.dispatch({
            "action": "list_sources",
            "notebook_id": "nb-1",
            "page_size": 2,
        })
        assert p1["ok"] is True
        assert len(p1["sources"]) == 2
        assert p1["sources"][0]["id"] == "src-0"
        assert p1["sources"][1]["id"] == "src-1"
        assert p1.get("next_cursor") == "2"

        # Second page of 2 using cursor
        p2 = await broker.dispatch({
            "action": "list_sources",
            "notebook_id": "nb-1",
            "page_size": 2,
            "cursor": p1["next_cursor"],
        })
        assert p2["ok"] is True
        assert len(p2["sources"]) == 2
        assert p2["sources"][0]["id"] == "src-2"
        assert p2["sources"][1]["id"] == "src-3"
        assert p2.get("next_cursor") == "4"


@pytest.mark.asyncio
async def test_list_notebooks_pagination(broker: BrokerDaemon) -> None:
    """list_notebooks respects page_size and cursor parameters."""
    raw_notebooks = [
        ["nb-1", "Notebook 1", None, None, None, 1],
        ["nb-2", "Notebook 2", None, None, None, 1],
    ]
    frame = [["wrb.fr", "wXbhsf", json.dumps(raw_notebooks), None, None, None, None, 1]]
    fake_body = ")]}'\n" + json.dumps(frame)

    with patch.object(
        broker,
        "send_to_companion",
        new=AsyncMock(return_value={"ok": True, "body": fake_body}),
    ):
        res = await broker.dispatch({
            "action": "list_notebooks",
            "page_size": 1,
        })
        assert res["ok"] is True
        assert len(res["notebooks"]) == 1
        assert res["notebooks"][0]["id"] == "nb-1"
        assert res.get("next_cursor") == "1"


# ---------------------------------------------------------------------------
# Phase 5: Scotty 3-Step Resumable Upload Protocol
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scotty_resumable_upload_success(broker: BrokerDaemon) -> None:
    """add_source with type=file executes Intent Registration (o4cbdc) then scotty_upload."""
    o4cbdc_frame = [["wrb.fr", "o4cbdc", json.dumps(["src-scotty-42"]), None, None, None, None, 1]]
    o4cbdc_body = ")]}'\n" + json.dumps(o4cbdc_frame)

    companion_calls: list[tuple[str, dict[str, Any]]] = []

    async def mock_send(command: str, payload: dict[str, Any], timeout_seconds: float = 60.0) -> dict[str, Any]:
        companion_calls.append((command, payload))
        if command == "batchexecute" and payload.get("rpcId") == "o4cbdc":
            return {"ok": True, "body": o4cbdc_body}
        elif command == "scotty_upload":
            return {"ok": True, "sourceId": payload.get("sourceId")}
        return {"ok": False}

    with patch.object(broker, "send_to_companion", side_effect=mock_send):
        res = await broker.dispatch({
            "action": "add_source",
            "notebook_id": "nb-1",
            "idempotency_key": "scotty-test-key-1",
            "source": {
                "type": "file",
                "title": "architecture.pdf",
                "content": "Sovereign OS Architecture Specs",
            },
            "wait_until_ready": False,
        })

    assert res["ok"] is True
    assert res["source_id"] == "src-scotty-42"
    assert res["status"] == "PROCESSING"

    # Verify both steps were called in order: o4cbdc then scotty_upload
    assert len(companion_calls) == 2
    assert companion_calls[0][0] == "batchexecute"
    assert companion_calls[0][1]["rpcId"] == "o4cbdc"

    assert companion_calls[1][0] == "scotty_upload"
    scotty_payload = companion_calls[1][1]
    assert scotty_payload["sourceId"] == "src-scotty-42"
    assert scotty_payload["filename"] == "architecture.pdf"
    assert scotty_payload["notebookId"] == "nb-1"
    # Decoded base64 must match original content
    decoded = base64.b64decode(scotty_payload["fileBase64"]).decode("utf-8")
    assert decoded == "Sovereign OS Architecture Specs"

    # Journal must be CONFIRMED
    record = broker.journal.get("scotty-test-key-1")
    assert record is not None
    assert record.state == MutationState.CONFIRMED


@pytest.mark.asyncio
async def test_scotty_resumable_upload_failure(broker: BrokerDaemon) -> None:
    """If scotty_upload fails, mutation state transitions to REJECTED and returns error."""
    o4cbdc_frame = [["wrb.fr", "o4cbdc", json.dumps(["src-fail-1"]), None, None, None, None, 1]]
    o4cbdc_body = ")]}'\n" + json.dumps(o4cbdc_frame)

    async def mock_send(command: str, payload: dict[str, Any], timeout_seconds: float = 60.0) -> dict[str, Any]:
        if command == "batchexecute" and payload.get("rpcId") == "o4cbdc":
            return {"ok": True, "body": o4cbdc_body}
        elif command == "scotty_upload":
            return {
                "ok": False,
                "error": {
                    "code": "UPLOAD_STREAM_ERROR",
                    "message": "TCP reset during stream",
                    "retryable": True,
                },
            }
        return {"ok": False}

    with patch.object(broker, "send_to_companion", side_effect=mock_send):
        res = await broker.dispatch({
            "action": "add_source",
            "notebook_id": "nb-1",
            "idempotency_key": "scotty-fail-key-1",
            "source": {
                "type": "file",
                "title": "bad_file.bin",
                "content": "corrupted",
            },
            "wait_until_ready": False,
        })

    assert res["ok"] is False
    assert res["error"]["code"] == "UPLOAD_STREAM_ERROR"

    record = broker.journal.get("scotty-fail-key-1")
    assert record is not None
    assert record.state == MutationState.REJECTED


# ---------------------------------------------------------------------------
# Phase 5: Readiness Polling Engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_readiness_polling_full_jitter_transitions_to_ready(broker: BrokerDaemon) -> None:
    """Polling rLM1Ne transitions from PROCESSING (1) to READY (2)."""
    poll_count = 0

    async def mock_fetch_metadata(nb_id: str) -> list[Any]:
        nonlocal poll_count
        poll_count += 1
        if poll_count < 2:
            return [{"id": "src-poll-1", "title": "Doc", "status_code": 1, "status": "PROCESSING"}]
        return [{"id": "src-poll-1", "title": "Doc", "status_code": 2, "status": "READY"}]

    status = await poll_until_ready(
        notebook_id="nb-1",
        source_id="src-poll-1",
        fetch_metadata_fn=mock_fetch_metadata,
        max_timeout=5.0,
        base_delay=0.01,
        max_delay=0.05,
    )

    assert status == SourceStatus.READY
    assert poll_count >= 2


@pytest.mark.asyncio
async def test_readiness_polling_transitions_to_failed(broker: BrokerDaemon) -> None:
    """Polling rLM1Ne returning ERROR/FAILED (3) transitions to ERROR and rejects mutation."""
    # o4cbdc registration
    iz_frame = [["wrb.fr", "izAoDd", json.dumps(["src-fail-polled"]), None, None, None, None, 1]]
    iz_body = ")]}'\n" + json.dumps(iz_frame)

    # rLM1Ne returns status 3 (ERROR / FAILED)
    rlm_sources = [["src-fail-polled", "Failed Doc", None, None, 3]]
    rlm_frame = [["wrb.fr", "rLM1Ne", json.dumps(rlm_sources), None, None, None, None, 1]]
    rlm_body = ")]}'\n" + json.dumps(rlm_frame)

    async def mock_send(command: str, payload: dict[str, Any], timeout_seconds: float = 60.0) -> dict[str, Any]:
        rpc_id = payload.get("rpcId")
        if rpc_id == "izAoDd":
            return {"ok": True, "body": iz_body}
        elif rpc_id == "rLM1Ne":
            return {"ok": True, "body": rlm_body}
        return {"ok": False}

    with patch.object(broker, "send_to_companion", side_effect=mock_send):
        res = await broker.dispatch({
            "action": "add_source",
            "notebook_id": "nb-1",
            "idempotency_key": "poll-fail-key-1",
            "source": {
                "type": "text",
                "title": "Failed Ingestion",
                "content": "Will fail",
            },
            "wait_until_ready": True,
        })

    assert res["ok"] is False
    assert "failed ingestion" in res["error"]["message"].lower()

    record = broker.journal.get("poll-fail-key-1")
    assert record is not None
    assert record.state == MutationState.REJECTED


@pytest.mark.asyncio
async def test_readiness_polling_timeout_marks_mutation_unknown(broker: BrokerDaemon) -> None:
    """Readiness polling timeout marks mutation as UNKNOWN and returns MUTATION_UNKNOWN."""
    iz_frame = [["wrb.fr", "izAoDd", json.dumps(["src-timeout-polled"]), None, None, None, None, 1]]
    iz_body = ")]}'\n" + json.dumps(iz_frame)

    # Continues to return PROCESSING (1)
    rlm_sources = [["src-timeout-polled", "Pending Doc", None, None, 1]]
    rlm_frame = [["wrb.fr", "rLM1Ne", json.dumps(rlm_sources), None, None, None, None, 1]]
    rlm_body = ")]}'\n" + json.dumps(rlm_frame)

    async def mock_send(command: str, payload: dict[str, Any], timeout_seconds: float = 60.0) -> dict[str, Any]:
        rpc_id = payload.get("rpcId")
        if rpc_id == "izAoDd":
            return {"ok": True, "body": iz_body}
        elif rpc_id == "rLM1Ne":
            return {"ok": True, "body": rlm_body}
        return {"ok": False}

    with patch.object(broker, "send_to_companion", side_effect=mock_send):
        with patch("mcp_gateway.broker.broker.poll_until_ready", side_effect=TimeoutError("Poller timeout")):
            res = await broker.dispatch({
                "action": "add_source",
                "notebook_id": "nb-1",
                "idempotency_key": "poll-timeout-key-1",
                "source": {
                    "type": "text",
                    "title": "Pending Ingestion",
                    "content": "Will timeout",
                },
                "wait_until_ready": True,
            })

    assert res["ok"] is False
    assert res["error"]["code"] == MUTATION_UNKNOWN

    record = broker.journal.get("poll-timeout-key-1")
    assert record is not None
    assert record.state == MutationState.UNKNOWN


# ---------------------------------------------------------------------------
# Closed JSON Schema Invariants & Standard Failure Envelopes
# ---------------------------------------------------------------------------


def test_closed_json_schemas_reject_additional_properties() -> None:
    """All 5 MCP tools enforce additionalProperties: False."""
    assert validate_tool_args("list_notebooks", {"extra": "illegal"}) is not None
    assert validate_tool_args("get_notebook_metadata", {"notebook_id": "nb-1", "extra": 1}) is not None
    assert validate_tool_args("list_sources", {"notebook_id": "nb-1", "unexpected": True}) is not None
    assert validate_tool_args("query_notebook", {
        "notebook_id": "nb-1",
        "question": "q",
        "request_key": "k",
        "bad_prop": 123,
    }) is not None
    assert validate_tool_args("add_source", {
        "notebook_id": "nb-1",
        "idempotency_key": "k",
        "source": {"type": "text"},
        "unknown_flag": True,
    }) is not None


def test_standard_failure_envelope_structure() -> None:
    """Failure envelope format is standardized: {ok: false, error: {code, message, retryable}}."""
    envelope = make_error(ALLOWLIST_DENIED, "Access denied by policy", retryable=False).to_dict()
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == ALLOWLIST_DENIED
    assert envelope["error"]["message"] == "Access denied by policy"
    assert envelope["error"]["retryable"] is False


def test_pydantic_closed_models_validation() -> None:
    """Pydantic models enforce closed fields (extra='forbid') and validation rules."""
    from pydantic import ValidationError

    # 1. list_notebooks
    valid_ln = ListNotebooksInput(page_size=10, cursor="abc")
    assert valid_ln.page_size == 10
    assert valid_ln.cursor == "abc"
    with pytest.raises(ValidationError):
        ListNotebooksInput.model_validate({"extra_field": "bad"})
    with pytest.raises(ValidationError):
        ListNotebooksInput(page_size=0)  # ge=1

    # 2. get_notebook_metadata
    valid_gnm = GetNotebookMetadataInput(notebook_id="nb-123")
    assert valid_gnm.notebook_id == "nb-123"
    with pytest.raises(ValidationError):
        GetNotebookMetadataInput.model_validate({"notebook_id": "nb-1", "unexpected": 1})
    with pytest.raises(ValidationError):
        GetNotebookMetadataInput(notebook_id="")

    # 3. list_sources
    valid_ls = ListSourcesInput(notebook_id="nb-123", page_size=20)
    assert valid_ls.page_size == 20
    with pytest.raises(ValidationError):
        ListSourcesInput.model_validate({"notebook_id": "nb-1", "foo": "bar"})

    # 4. query_notebook
    valid_qn = QueryNotebookInput(
        notebook_id="nb-123",
        question="What is the architecture?",
        request_key="req-1",
        source_ids=["src-1"],
        timeout_seconds=60,
    )
    assert valid_qn.timeout_seconds == 60
    with pytest.raises(ValidationError):
        QueryNotebookInput.model_validate({
            "notebook_id": "nb-1",
            "question": "q",
            "request_key": "k",
            "extra": True,
        })
    with pytest.raises(ValidationError):
        QueryNotebookInput(notebook_id="nb-1", question="q", request_key="k", timeout_seconds=5)  # ge=10

    # 5. add_source
    valid_as = AddSourceInput(
        notebook_id="nb-123",
        idempotency_key="idemp-1",
        source=SourceSpec(type="text", title="Doc", content="Hello world"),
        wait_until_ready=True,
    )
    assert valid_as.wait_until_ready is True
    with pytest.raises(ValidationError):
        AddSourceInput.model_validate({
            "notebook_id": "nb-1",
            "idempotency_key": "k",
            "source": {"type": "text"},
            "extra_param": 123,
        })
    with pytest.raises(ValidationError):
        SourceSpec.model_validate({"type": "invalid_type"})
    with pytest.raises(ValidationError):
        SourceSpec.model_validate({"type": "text", "extra": "not_allowed"})
