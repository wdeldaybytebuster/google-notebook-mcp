"""Unit and integration tests for Phase 3: First-Class Note Management & SQLite Migration (Domain C).

Covers:
- test_sqlite_user_version_migration: Version 1 DB migration to user_version 2 with CHECK constraint expansion
- test_create_note_journal_state_machine: create_note lifecycle (prepared -> sent -> confirmed)
- test_list_notes_loud_canary_failure: M-05 canary on len(container) <= 17, non-list, or missing container
- test_list_notes_success: extraction of note records and pagination from rLM1Ne container[17]
- test_delete_note_idempotency: delete_note journal transitions and cached confirmation on replay
- test_correlation_id_propagation_in_error_envelopes: P-04 un-hashed _meta.mcp_correlation_id on success and error
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
from typing import Any, Generator
from unittest.mock import AsyncMock, patch

import pytest

from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon, McpFacade
from mcp_gateway.broker.session import SessionState
from mcp_gateway.engine.rpc_templates import (
    make_create_note_payload,
    make_delete_note_payload,
)
from mcp_gateway.schemas.error import (
    ALLOWLIST_DENIED,
    INVALID_ARGUMENT,
    REQUEST_KEY_CONFLICT,
    UPSTREAM_SCHEMA_DRIFT,
)
from mcp_gateway.storage.journal import (
    MutationJournal,
    MutationState,
    OperationType,
)


@pytest.fixture
def mock_broker(tmp_path: Path) -> Generator[BrokerDaemon, None, None]:
    allowlist_file = tmp_path / "allowlist.json"
    data = {
        "version": 1,
        "provider_mode": "browser",
        "accounts": ["test@example.com"],
        "notebooks": ["nb-1", "nb-2"],
    }
    allowlist_file.write_text(json.dumps(data), encoding="utf-8")

    cfg = BrokerConfig(
        socket_path=str(tmp_path / "mock.sock"),
        allowlist_path=allowlist_file,
        journal_db_path=tmp_path / "journal.db",
    )
    broker = BrokerDaemon(cfg)
    yield broker
    broker.journal.close()


def test_sqlite_user_version_migration(tmp_path: Path) -> None:
    """Verifies atomic migration from schema version 1 to 2, expanding operation_type CHECK constraint."""
    db_file = tmp_path / "legacy_v1.db"
    conn = sqlite3.connect(str(db_file))
    
    # Setup legacy version 1 schema
    v1_sql = """
    PRAGMA user_version = 1;
    PRAGMA foreign_keys = ON;

    CREATE TABLE mutation_journal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_key TEXT NOT NULL UNIQUE,
        notebook_id TEXT NOT NULL,
        operation_type TEXT NOT NULL CHECK(operation_type IN ('add_source', 'query_notebook')),
        payload_hash TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'prepared' CHECK(state IN ('prepared', 'sent', 'confirmed', 'rejected', 'unknown')),
        assigned_source_id TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );

    CREATE TABLE mutation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mutation_id INTEGER NOT NULL REFERENCES mutation_journal(id),
        event_type TEXT NOT NULL,
        old_state TEXT,
        new_state TEXT,
        detail TEXT,
        occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );
    """
    conn.executescript(v1_sql)

    # Insert valid v1 record
    conn.execute(
        "INSERT INTO mutation_journal (request_key, notebook_id, operation_type, payload_hash, state) "
        "VALUES (?, ?, ?, ?, ?)",
        ("v1-key", "nb-1", "add_source", "hash1", "confirmed"),
    )
    conn.commit()

    # Prior to migration, inserting create_note or delete_note MUST fail CHECK constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO mutation_journal (request_key, notebook_id, operation_type, payload_hash, state) "
            "VALUES (?, ?, ?, ?, ?)",
            ("v1-note", "nb-1", "create_note", "hash2", "prepared"),
        )
    conn.close()

    # Initialize MutationJournal which executes _run_migrations
    journal = MutationJournal(db_file)

    # Verify user_version bumped to 2
    cur = journal._conn.execute("PRAGMA user_version;")
    version = cur.fetchone()[0]
    assert version == 2

    # Verify legacy record was preserved
    rec = journal.get("v1-key")
    assert rec is not None
    assert rec.notebook_id == "nb-1"
    assert rec.operation_type == OperationType.ADD_SOURCE
    assert rec.state == MutationState.CONFIRMED

    # Verify create_note and delete_note are now legally accepted in CHECK constraint
    rec_create = journal.prepare(
        request_key="v2-create-note",
        notebook_id="nb-1",
        operation_type=OperationType.CREATE_NOTE,
        args={"title": "Test", "content": "Hello"},
        capability_secret=b"test-secret-32-bytes-long-padded",
    )
    assert rec_create.operation_type == OperationType.CREATE_NOTE
    assert rec_create.state == MutationState.PREPARED

    rec_delete = journal.prepare(
        request_key="v2-delete-note",
        notebook_id="nb-1",
        operation_type=OperationType.DELETE_NOTE,
        args={"note_id": "note-123"},
        capability_secret=b"test-secret-32-bytes-long-padded",
    )
    assert rec_delete.operation_type == OperationType.DELETE_NOTE
    assert rec_delete.state == MutationState.PREPARED

    journal.close()


@pytest.mark.asyncio
async def test_create_note_journal_state_machine(mock_broker: BrokerDaemon) -> None:
    """Verifies create_note lifecycle transitions: prepared -> sent -> confirmed with assigned note ID."""
    # Select and lock notebook
    await mock_broker.session_lock.select_notebook("nb-1", is_allowed=True)

    # Wire response from CYK0Xb returning server-assigned note ID
    mock_wire_body = ")]}'\n" + json.dumps([
        [
            "wrb.fr",
            "CYK0Xb",
            json.dumps([[["server-assigned-note-uuid-456"]]]),
        ]
    ])

    with patch.object(mock_broker, "send_to_companion", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"ok": True, "body": mock_wire_body}

        cmd = {
            "action": "create_note",
            "notebook_id": "nb-1",
            "title": "My Research Note",
            "content": "Detailed note content.",
            "idempotency_key": "note-key-001",
        }

        res = await mock_broker.dispatch(cmd)

        assert res["ok"] is True
        assert res["note_id"] == "server-assigned-note-uuid-456"
        assert res["status"] == "READY"
        assert res["_meta"]["mcp_correlation_id"] == "note-key-001"

        # Check journal entry
        rec = mock_broker.journal.get("note-key-001")
        assert rec is not None
        assert rec.state == MutationState.CONFIRMED
        assert rec.assigned_source_id == "server-assigned-note-uuid-456"
        assert rec.operation_type == OperationType.CREATE_NOTE

        # Replay with same idempotency_key returns cached confirmed result
        mock_send.reset_mock()
        replay_res = await mock_broker.dispatch(cmd)
        assert replay_res["ok"] is True
        assert replay_res["note_id"] == "server-assigned-note-uuid-456"
        assert replay_res.get("cached") is True
        assert mock_send.call_count == 0


@pytest.mark.asyncio
async def test_list_notes_loud_canary_failure(mock_broker: BrokerDaemon) -> None:
    """Verifies M-05 loud canary: returns UPSTREAM_SCHEMA_DRIFT when container len <= 17 or non-list."""
    await mock_broker.session_lock.select_notebook("nb-1", is_allowed=True)

    # Case 1: container length <= 17 (e.g. truncated container of length 5)
    truncated_container: list[Any] = [None, [], [], [], None]
    mock_wire_body_truncated = ")]}'\n" + json.dumps([
        [
            "wrb.fr",
            "rLM1Ne",
            json.dumps([truncated_container]),
        ]
    ])

    with patch.object(mock_broker, "send_to_companion", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"ok": True, "body": mock_wire_body_truncated}

        res = await mock_broker.dispatch({
            "action": "list_notes",
            "notebook_id": "nb-1",
            "idempotency_key": "list-canary-01",
        })

        assert res["ok"] is False
        assert res["error"]["code"] == UPSTREAM_SCHEMA_DRIFT
        assert "expected > 17" in res["error"]["message"]
        assert res["error"]["retryable"] is False
        assert res["_meta"]["mcp_correlation_id"] == "list-canary-01"

    # Case 2: container[17] is not a list (e.g. integer or dict)
    malformed_container: list[Any] = [None] * 20
    malformed_container[17] = "not-a-list"
    mock_wire_body_malformed = ")]}'\n" + json.dumps([
        [
            "wrb.fr",
            "rLM1Ne",
            json.dumps([malformed_container]),
        ]
    ])

    with patch.object(mock_broker, "send_to_companion", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"ok": True, "body": mock_wire_body_malformed}

        res = await mock_broker.dispatch({
            "action": "list_notes",
            "notebook_id": "nb-1",
            "idempotency_key": "list-canary-02",
        })

        assert res["ok"] is False
        assert res["error"]["code"] == UPSTREAM_SCHEMA_DRIFT
        assert "is not an array" in res["error"]["message"]
        assert res["error"]["retryable"] is False

    # Case 3: data is not a valid list container
    mock_wire_body_empty = ")]}'\n" + json.dumps([
        [
            "wrb.fr",
            "rLM1Ne",
            json.dumps("invalid-string-instead-of-list"),
        ]
    ])

    with patch.object(mock_broker, "send_to_companion", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"ok": True, "body": mock_wire_body_empty}

        res = await mock_broker.dispatch({
            "action": "list_notes",
            "notebook_id": "nb-1",
            "idempotency_key": "list-canary-03",
        })

        assert res["ok"] is False
        assert res["error"]["code"] == UPSTREAM_SCHEMA_DRIFT
        assert "Invalid rLM1Ne response envelope structure" in res["error"]["message"]


@pytest.mark.asyncio
async def test_list_notes_success(mock_broker: BrokerDaemon) -> None:
    """Verifies extraction and pagination of note records from valid rLM1Ne container[17]."""
    await mock_broker.session_lock.select_notebook("nb-1", is_allowed=True)

    # Construct container with notes at index 17
    container: list[Any] = [None] * 20
    note_rows = [
        [[["note-uuid-1"]], "Content for note 1", [1, 2], None, "First Note"],
        [[["note-uuid-2"]], "Content for note 2", [1, 2], None, "Second Note"],
        [[["note-uuid-3"]], "Content for note 3", [1, 2], None, "Third Note"],
    ]
    container[17] = note_rows

    mock_wire_body = ")]}'\n" + json.dumps([
        [
            "wrb.fr",
            "rLM1Ne",
            json.dumps([container]),
        ]
    ])

    with patch.object(mock_broker, "send_to_companion", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"ok": True, "body": mock_wire_body}

        # Request with pagination page_size=2
        res = await mock_broker.dispatch({
            "action": "list_notes",
            "notebook_id": "nb-1",
            "page_size": 2,
            "idempotency_key": "list-page-1",
        })

        assert res["ok"] is True
        assert len(res["notes"]) == 2
        assert res["notes"][0] == {
            "id": "note-uuid-1",
            "title": "First Note",
            "content": "Content for note 1",
        }
        assert res["notes"][1] == {
            "id": "note-uuid-2",
            "title": "Second Note",
            "content": "Content for note 2",
        }
        assert res["next_cursor"] == "2"
        assert res["_meta"]["mcp_correlation_id"] == "list-page-1"

        # Request page 2
        res_page2 = await mock_broker.dispatch({
            "action": "list_notes",
            "notebook_id": "nb-1",
            "page_size": 2,
            "cursor": "2",
        })

        assert res_page2["ok"] is True
        assert len(res_page2["notes"]) == 1
        assert res_page2["notes"][0]["id"] == "note-uuid-3"
        assert "next_cursor" not in res_page2


@pytest.mark.asyncio
async def test_delete_note_idempotency(mock_broker: BrokerDaemon) -> None:
    """Verifies delete_note journal transitions and cached confirmation on replay."""
    await mock_broker.session_lock.select_notebook("nb-1", is_allowed=True)

    mock_wire_body = ")]}'\n" + json.dumps([
        [
            "wrb.fr",
            "tGMBJ",
            json.dumps([[None]]),
        ]
    ])

    with patch.object(mock_broker, "send_to_companion", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"ok": True, "body": mock_wire_body}

        cmd = {
            "action": "delete_note",
            "notebook_id": "nb-1",
            "note_id": "note-to-delete-999",
            "idempotency_key": "del-key-001",
        }

        res = await mock_broker.dispatch(cmd)

        assert res["ok"] is True
        assert res["deleted"] is True
        assert res["_meta"]["mcp_correlation_id"] == "del-key-001"

        # Verify journal state
        rec = mock_broker.journal.get("del-key-001")
        assert rec is not None
        assert rec.state == MutationState.CONFIRMED
        assert rec.operation_type == OperationType.DELETE_NOTE

        # Replay with same idempotency_key returns cached confirmed result without calling companion
        mock_send.reset_mock()
        replay_res = await mock_broker.dispatch(cmd)
        assert replay_res["ok"] is True
        assert replay_res["deleted"] is True
        assert replay_res.get("cached") is True
        assert mock_send.call_count == 0


@pytest.mark.asyncio
async def test_correlation_id_propagation_in_error_envelopes(mock_broker: BrokerDaemon) -> None:
    """Verifies P-04: un-hashed _meta.mcp_correlation_id is propagated across all envelopes."""
    correlation_token = "consultation-query-alpha-42"

    # Test 1: Unlocked session failure preserves correlation ID
    res1 = await mock_broker.dispatch({
        "action": "create_note",
        "notebook_id": "nb-1",
        "content": "Un-locked attempt",
        "idempotency_key": correlation_token,
    })
    assert res1["ok"] is False
    assert res1["_meta"]["mcp_correlation_id"] == correlation_token
    assert res1["error"]["mcp_correlation_id"] == correlation_token

    # Test 2: Allowlist denied error preserves correlation ID
    unlocked_broker = BrokerDaemon(mock_broker.config)
    try:
        res_allowlist = await unlocked_broker.dispatch({
            "action": "select_notebook",
            "notebook_id": "unauthorized-nb",
            "request_key": correlation_token,
        })
        assert res_allowlist["ok"] is False
        assert res_allowlist["error"]["code"] == ALLOWLIST_DENIED
        assert res_allowlist["_meta"]["mcp_correlation_id"] == correlation_token
        assert res_allowlist["error"]["mcp_correlation_id"] == correlation_token
    finally:
        unlocked_broker.journal.close()

    # Test 3: Unrecognized action error preserves correlation ID
    await mock_broker.session_lock.select_notebook("nb-1", is_allowed=True)
    res3 = await mock_broker.dispatch({
        "action": "invalid_unknown_action",
        "request_key": correlation_token,
    })
    assert res3["ok"] is False
    assert res3["error"]["code"] == INVALID_ARGUMENT
    assert res3["_meta"]["mcp_correlation_id"] == correlation_token
    assert res3["error"]["mcp_correlation_id"] == correlation_token

    # Test 4: Upstream companion failure preserves correlation ID
    with patch.object(mock_broker, "send_to_companion", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {
            "ok": False,
            "error": {"code": "INTERNAL", "message": "Companion unreachable"},
        }
        res4 = await mock_broker.dispatch({
            "action": "delete_note",
            "notebook_id": "nb-1",
            "note_id": "note-err-1",
            "idempotency_key": correlation_token,
        })
        assert res4["ok"] is False
        assert res4["_meta"]["mcp_correlation_id"] == correlation_token
        assert res4["error"]["mcp_correlation_id"] == correlation_token


def test_rpc_template_payload_builders() -> None:
    """Verifies wire structure of make_create_note_payload and make_delete_note_payload."""
    create_payload = make_create_note_payload("My Title", "My Content", "nb-uuid")
    decoded_create = json.loads(create_payload)
    assert decoded_create == ["nb-uuid", "My Title", "My Content"]

    del_payload_with_nb = make_delete_note_payload("note-uuid", "nb-uuid")
    decoded_del_with_nb = json.loads(del_payload_with_nb)
    assert decoded_del_with_nb == [[["note-uuid"]], "nb-uuid", [58]]

    del_payload_without_nb = make_delete_note_payload("note-uuid")
    decoded_del_without_nb = json.loads(del_payload_without_nb)
    assert decoded_del_without_nb == [[["note-uuid"]], [58]]


@pytest.mark.asyncio
async def test_mcp_facade_note_tools_registration(mock_broker: BrokerDaemon) -> None:
    """Verifies McpFacade registers create_note, list_notes, delete_note and enforces closed schemas."""
    import mcp.types as types
    from typing import cast

    facade = McpFacade(mock_broker)
    list_entry = facade.server._request_handlers.get("tools/list")
    assert list_entry is not None

    req = types.ListToolsRequest(method="tools/list")
    res = await list_entry.handler(cast(Any, None), req)
    assert isinstance(res, types.ListToolsResult)
    tool_names = [t.name for t in res.tools]

    assert "create_note" in tool_names
    assert "list_notes" in tool_names
    assert "delete_note" in tool_names
    assert len(tool_names) == 9

    # Test call_tool_handler rejects extra properties (closed schema) and propagates correlation ID
    call_entry = facade.server._request_handlers.get("tools/call")
    assert call_entry is not None

    call_req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(
            name="create_note",
            arguments={
                "notebook_id": "nb-1",
                "content": "Valid note content",
                "idempotency_key": "corr-token-facade-01",
                "unauthorized_extra_field": "injected",
            },
        ),
    )

    tool_res = await call_entry.handler(cast(Any, None), call_req)
    assert isinstance(tool_res, types.CallToolResult)
    assert tool_res.is_error is True
    parsed_structured = cast(dict[str, Any], tool_res.structured_content)
    assert parsed_structured["code"] == INVALID_ARGUMENT
    assert parsed_structured["raw"]["_meta"]["mcp_correlation_id"] == "corr-token-facade-01"


