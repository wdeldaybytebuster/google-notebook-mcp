from __future__ import annotations

import asyncio
import json
from pathlib import Path
import struct
from typing import Any, cast
import pytest

from mcp_gateway.broker.allowlist import (
    add_notebook,
    is_notebook_allowed,
    load_allowlist,
    remove_notebook,
    save_allowlist,
)
from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon, McpFacade
from mcp_gateway.broker.secret_scrubber import (
    assert_clean,
    scrub,
    scrub_dict,
)
from mcp_gateway.schemas.error import (
    ALLOWLIST_DENIED,
    AUTH_REQUIRED,
    SESSION_LOCKED,
    SESSION_UNLOCKED,
    make_error,
)
from mcp_gateway.schemas.tools import (
    ADD_SOURCE_SCHEMA,
    CREATE_NOTE_SCHEMA,
    DELETE_NOTE_SCHEMA,
    EXTRACT_ARTIFACT_SCHEMA,
    GET_ARTIFACT_METADATA_SCHEMA,
    GET_NOTEBOOK_METADATA_SCHEMA,
    LIST_ARTIFACTS_SCHEMA,
    LIST_NOTEBOOKS_SCHEMA,
    LIST_NOTES_SCHEMA,
    LIST_SOURCES_SCHEMA,
    QUERY_NOTEBOOK_SCHEMA,
    SELECT_NOTEBOOK_SCHEMA,
    TOOL_ANNOTATIONS,
)
import mcp.types as types


@pytest.fixture
def allowlist_file(tmp_path: Path) -> Path:
    p = tmp_path / "allowlist.json"
    data = {
        "version": 1,
        "provider_mode": "browser",
        "accounts": ["developer@gmail.com"],
        "notebooks": ["nb-allowed-1", "nb-allowed-2"],
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture
def broker(tmp_path: Path, allowlist_file: Path) -> BrokerDaemon:
    cfg = BrokerConfig(
        socket_path=str(tmp_path / "test.sock"),
        allowlist_path=allowlist_file,
        journal_db_path=tmp_path / "journal.db",
    )
    return BrokerDaemon(cfg)


def test_allowlist_operations(allowlist_file: Path, tmp_path: Path) -> None:
    config = load_allowlist(allowlist_file)
    assert config.version == 1
    assert is_notebook_allowed(config, "nb-allowed-1") is True
    assert is_notebook_allowed(config, "nb-forbidden") is False

    # Add notebook
    updated = add_notebook(config, "nb-new")
    assert is_notebook_allowed(updated, "nb-new") is True

    # Remove notebook
    removed = remove_notebook(updated, "nb-allowed-1")
    assert is_notebook_allowed(removed, "nb-allowed-1") is False

    # Save and reload
    save_path = tmp_path / "saved_allowlist.json"
    save_allowlist(removed, save_path)
    reloaded = load_allowlist(save_path)
    assert reloaded.notebooks == ["nb-allowed-2", "nb-new"]


def test_allowlist_missing_raises(tmp_path: Path) -> None:
    missing_path = tmp_path / "does_not_exist.json"
    with pytest.raises(FileNotFoundError):
        load_allowlist(missing_path)


def test_allowlist_v2_structured_modes_reload_and_v1_migration(tmp_path: Path) -> None:
    import os
    import stat
    from mcp_gateway.broker.allowlist import (
        NotebookPermission,
        get_notebook_mode,
        is_tool_permitted_for_notebook,
        parse_and_validate_notebook_id,
        set_notebook_permission,
    )

    # 1. Load legacy v1 flat list -> migrates to INTERACTIVE permissions
    v1_path = tmp_path / "v1_allowlist.json"
    v1_path.write_text(
        json.dumps({
            "version": 1,
            "provider_mode": "browser",
            "accounts": ["dev@example.com"],
            "notebooks": ["nb-legacy-1"],
        }),
        encoding="utf-8",
    )
    cfg_v1 = load_allowlist(v1_path)
    assert is_notebook_allowed(cfg_v1, "nb-legacy-1") is True
    assert get_notebook_mode(cfg_v1, "nb-legacy-1") == "INTERACTIVE"
    assert is_tool_permitted_for_notebook(cfg_v1, "nb-legacy-1", "query_notebook") is True
    assert is_tool_permitted_for_notebook(cfg_v1, "nb-legacy-1", "add_source") is True

    # 2. Set READ_ONLY permission and save as v2 structured map
    cfg_v2 = set_notebook_permission(
        cfg_v1,
        "nb-readonly-2",
        title="Project Architecture Docs",
        mode="READ_ONLY",
    )
    v2_path = tmp_path / "v2_allowlist.json"
    save_allowlist(cfg_v2, v2_path)
    if os.name != "nt":
        assert stat.S_IMODE(v2_path.stat().st_mode) == 0o600

    raw_saved = json.loads(v2_path.read_text(encoding="utf-8"))
    assert raw_saved["version"] == 2
    assert raw_saved["notebooks"]["nb-readonly-2"] == {
        "title": "Project Architecture Docs",
        "mode": "READ_ONLY",
    }

    reloaded = load_allowlist(v2_path)
    assert is_notebook_allowed(reloaded, "nb-readonly-2") is True
    assert get_notebook_mode(reloaded, "nb-readonly-2") == "READ_ONLY"
    assert reloaded.notebook_permissions["nb-readonly-2"] == NotebookPermission(
        title="Project Architecture Docs",
        mode="READ_ONLY",
    )

    # 3. Granular RBAC checks for READ_ONLY vs INTERACTIVE:
    # READ_ONLY MUST allow read + select_notebook + query_notebook, and MUST block mutating tools
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "list_notebooks") is True
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "select_notebook") is True
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "get_notebook_metadata") is True
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "list_sources") is True
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "list_notes") is True
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "query_notebook") is True
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "add_source") is False
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "create_note") is False
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "delete_note") is False

    # 4. In-place AllowlistConfig.reload() updates singleton state from disk
    v2_path.write_text(
        json.dumps({
            "version": 2,
            "provider_mode": "browser",
            "accounts": ["dev@example.com"],
            "notebooks": {
                "123e4567-e89b-12d3-a456-426614174000": {
                    "title": "Hot Reloaded NB",
                    "mode": "READ_ONLY",
                }
            },
        }),
        encoding="utf-8",
    )
    reloaded.reload()
    assert is_notebook_allowed(reloaded, "123e4567-e89b-12d3-a456-426614174000") is True
    assert get_notebook_mode(reloaded, "123e4567-e89b-12d3-a456-426614174000") == "READ_ONLY"

    # 5. Strict UUIDv4 validation and URL extraction for manual fallback input
    valid_uuid = "123e4567-e89b-12d3-a456-426614174000"
    assert parse_and_validate_notebook_id(valid_uuid) == valid_uuid
    assert (
        parse_and_validate_notebook_id(
            f"https://notebook.google.com/notebook/{valid_uuid}?authuser=0"
        )
        == valid_uuid
    )
    assert (
        parse_and_validate_notebook_id(
            f"https://notebooklm.google.com/notebook/{valid_uuid}/"
        )
        == valid_uuid
    )
    with pytest.raises(ValueError, match="Invalid notebook ID"):
        parse_and_validate_notebook_id("../../etc/passwd")
    with pytest.raises(ValueError, match="Invalid notebook ID"):
        parse_and_validate_notebook_id("https://evil.example.com/notebook/123e4567-e89b-12d3-a456-426614174000")
    with pytest.raises(ValueError, match="Invalid notebook ID"):
        parse_and_validate_notebook_id("not-a-uuid")


def test_secret_scrubber_tokens() -> None:
    sample = "User logged in with ya29.a0AfH6SMDI890123456789 and Bearer ya29.xyz1234567890123"
    cleaned = scrub(sample)
    assert "ya29." not in cleaned
    assert "[REDACTED]" in cleaned

    cookie_sample = "Cookie: SID=abc1234.def; HSID=xyz; SSID=123; __Secure-1PSID=val.99; SAPISID=sec.1"
    cleaned_cookie = scrub(cookie_sample)
    assert "abc1234" not in cleaned_cookie
    assert "val.99" not in cleaned_cookie
    assert "[REDACTED]" in cleaned_cookie

    csrf_sample = 'window.WIZ_global_data = {SNlM0e: "csrf_token_secret_123", FdrFJe: "session_id_456"};'
    cleaned_csrf = scrub(csrf_sample)
    assert "csrf_token_secret_123" not in cleaned_csrf
    assert "session_id_456" not in cleaned_csrf
    assert "[REDACTED]" in cleaned_csrf


def test_secret_scrubber_dict_and_assert_clean() -> None:
    data = {
        "title": "Clean Title",
        "nested": {
            "token": "ya29.secret_token_123456789",
            "list": ["clean", "SID=session_cookie.123"],
        },
    }
    scrubbed = scrub_dict(data)
    assert scrubbed["title"] == "Clean Title"
    assert scrubbed["nested"]["token"] == "[REDACTED]"
    assert scrubbed["nested"]["list"][1] == "[REDACTED]"

    assert_clean("Normal log line with no secrets.")
    with pytest.raises(ValueError, match=r"\[SECRET DETECTED\]"):
        assert_clean("Leaked ya29.token_value_12345")


def test_failure_envelope() -> None:
    envelope = make_error(ALLOWLIST_DENIED, "Access forbidden", retryable=False)
    d = envelope.to_dict()
    assert d["ok"] is False
    assert d["error"]["code"] == ALLOWLIST_DENIED
    assert d["error"]["message"] == "Access forbidden"
    assert d["error"]["retryable"] is False


def test_twelve_tool_schemas_and_annotations() -> None:
    schemas = [
        LIST_NOTEBOOKS_SCHEMA,
        SELECT_NOTEBOOK_SCHEMA,
        GET_NOTEBOOK_METADATA_SCHEMA,
        LIST_SOURCES_SCHEMA,
        QUERY_NOTEBOOK_SCHEMA,
        ADD_SOURCE_SCHEMA,
        CREATE_NOTE_SCHEMA,
        LIST_NOTES_SCHEMA,
        DELETE_NOTE_SCHEMA,
        LIST_ARTIFACTS_SCHEMA,
        GET_ARTIFACT_METADATA_SCHEMA,
        EXTRACT_ARTIFACT_SCHEMA,
    ]
    assert len(schemas) == 12
    for s in schemas:
        assert s["additionalProperties"] is False
        assert s["type"] == "object"

    assert len(TOOL_ANNOTATIONS) == 12
    for tool_name, hints in TOOL_ANNOTATIONS.items():
        assert "readOnlyHint" in hints
        assert "destructiveHint" in hints
        assert "idempotentHint" in hints


# Backward compatibility aliases
test_nine_tool_schemas_and_annotations = test_twelve_tool_schemas_and_annotations
test_five_tool_schemas_and_annotations = test_twelve_tool_schemas_and_annotations


@pytest.mark.asyncio
async def test_broker_allowlist_enforcement(broker: BrokerDaemon) -> None:
    # 1. Calling specific notebook operation before select_notebook is rejected with SESSION_UNLOCKED
    cmd_pre_lock = {
        "action": "get_notebook_metadata",
        "notebook_id": "nb-allowed-1",
    }
    res_pre_lock = await broker.dispatch(cmd_pre_lock)
    assert res_pre_lock["ok"] is False
    assert res_pre_lock["error"]["code"] == SESSION_UNLOCKED

    # 2. Selecting a forbidden notebook is rejected with ALLOWLIST_DENIED
    cmd_select_denied = {
        "action": "select_notebook",
        "notebook_id": "nb-forbidden",
    }
    res_select_denied = await broker.dispatch(cmd_select_denied)
    assert res_select_denied["ok"] is False
    assert res_select_denied["error"]["code"] == ALLOWLIST_DENIED

    # 3. Selecting an allowed notebook succeeds and locks session
    cmd_select_allowed = {
        "action": "select_notebook",
        "notebook_id": "nb-allowed-1",
    }
    res_select_allowed = await broker.dispatch(cmd_select_allowed)
    assert res_select_allowed["ok"] is True
    assert res_select_allowed["status"] == "LOCKED"
    assert res_select_allowed["notebook_id"] == "nb-allowed-1"

    # 4. Attempting to access a different notebook post-lock is rejected with SESSION_LOCKED
    cmd_cross_access = {
        "action": "get_notebook_metadata",
        "notebook_id": "nb-forbidden",
    }
    res_cross = await broker.dispatch(cmd_cross_access)
    assert res_cross["ok"] is False
    assert res_cross["error"]["code"] == SESSION_LOCKED

    # 5. Allowed notebook reaches companion layer (companion not connected -> AUTH_REQUIRED)
    cmd_locked_allowed = {
        "action": "get_notebook_metadata",
        "notebook_id": "nb-allowed-1",
    }
    res_allowed = await broker.dispatch(cmd_locked_allowed)
    assert res_allowed["ok"] is False
    assert res_allowed["error"]["code"] == AUTH_REQUIRED


@pytest.mark.asyncio
async def test_mcp_facade_integration(broker: BrokerDaemon) -> None:
    facade = McpFacade(broker)
    list_entry = facade.server._request_handlers.get("tools/list")
    assert list_entry is not None

    list_req = types.ListToolsRequest(method="tools/list")
    list_res = await list_entry.handler(cast(Any, None), list_req)
    assert isinstance(list_res, types.ListToolsResult)
    tool_names = [t.name for t in list_res.tools]
    assert tool_names == [
        "list_notebooks",
        "select_notebook",
        "get_notebook_metadata",
        "list_sources",
        "query_notebook",
        "add_source",
        "create_note",
        "list_notes",
        "delete_note",
        "list_artifacts",
        "get_artifact_metadata",
        "extract_artifact",
    ]
    for t in list_res.tools:
        assert t.annotations is not None
        expected = TOOL_ANNOTATIONS[t.name]
        assert t.annotations.read_only_hint == expected["readOnlyHint"]
        assert t.annotations.destructive_hint == expected["destructiveHint"]
        assert t.annotations.idempotent_hint == expected["idempotentHint"]

    call_entry = facade.server._request_handlers.get("tools/call")
    assert call_entry is not None

    # Step 1: Pre-lock call returns SESSION_UNLOCKED
    req_pre = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(
            name="get_notebook_metadata",
            arguments={"notebook_id": "nb-allowed-1"},
        ),
    )
    res_pre = await call_entry.handler(cast(Any, None), req_pre)
    assert isinstance(res_pre, types.CallToolResult)
    assert res_pre.is_error is True
    item_pre = res_pre.content[0]
    assert isinstance(item_pre, types.TextContent)
    payload_pre = json.loads(item_pre.text)
    assert payload_pre["error"]["code"] == SESSION_UNLOCKED

    # Step 2: Select forbidden notebook returns ALLOWLIST_DENIED
    req_sel_denied = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(
            name="select_notebook",
            arguments={"notebook_id": "nb-forbidden"},
        ),
    )
    res_sel_denied = await call_entry.handler(cast(Any, None), req_sel_denied)
    assert isinstance(res_sel_denied, types.CallToolResult)
    assert res_sel_denied.is_error is True
    item_denied = res_sel_denied.content[0]
    assert isinstance(item_denied, types.TextContent)
    payload_denied = json.loads(item_denied.text)
    assert payload_denied["error"]["code"] == ALLOWLIST_DENIED

    # Step 3: Select allowed notebook succeeds
    req_sel_ok = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(
            name="select_notebook",
            arguments={"notebook_id": "nb-allowed-1"},
        ),
    )
    res_sel_ok = await call_entry.handler(cast(Any, None), req_sel_ok)
    assert isinstance(res_sel_ok, types.CallToolResult)
    assert res_sel_ok.is_error is False
    item_ok = res_sel_ok.content[0]
    assert isinstance(item_ok, types.TextContent)
    payload_ok = json.loads(item_ok.text)
    assert payload_ok["ok"] is True
    assert payload_ok["status"] == "LOCKED"

    # Step 4: Trying to select another notebook is rejected with SESSION_LOCKED
    req_sel_re = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(
            name="select_notebook",
            arguments={"notebook_id": "nb-allowed-2"},
        ),
    )
    res_sel_re = await call_entry.handler(cast(Any, None), req_sel_re)
    assert isinstance(res_sel_re, types.CallToolResult)
    assert res_sel_re.is_error is True
    item_re = res_sel_re.content[0]
    assert isinstance(item_re, types.TextContent)
    payload_re = json.loads(item_re.text)
    assert payload_re["error"]["code"] == SESSION_LOCKED


@pytest.mark.asyncio
async def test_session_lock_isolation_and_parameter_overwrite(broker: BrokerDaemon) -> None:
    # Lock to nb-allowed-1
    res = await broker.dispatch({"action": "select_notebook", "notebook_id": "nb-allowed-1"})
    assert res["ok"] is True

    # Invariant: Idempotent re-selection of the same notebook succeeds
    res_idempotent = await broker.dispatch({"action": "select_notebook", "notebook_id": "nb-allowed-1"})
    assert res_idempotent["ok"] is True
    assert res_idempotent["message"] == "Already locked to this notebook."

    # Post-lock filtering: only nb-allowed-1 is visible
    filtered = broker.session_lock.filter_notebooks([
        {"id": "nb-allowed-1", "title": "Allowed 1"},
        {"id": "nb-allowed-2", "title": "Allowed 2"},
    ])
    assert len(filtered) == 1
    assert filtered[0]["id"] == "nb-allowed-1"


def test_account_identity_preflight_attaches_expected_email_and_accounts(broker: BrokerDaemon) -> None:
    # broker fixture has accounts=["developer@gmail.com"]
    payload: dict[str, Any] = {"rpcId": "CYK0Xb"}
    out = broker._attach_identity_preflight(payload)
    assert out["expectedAccounts"] == ["developer@gmail.com"]
    assert out["expectedEmail"] == "developer@gmail.com"

    # Command-level overrides take precedence
    custom_cmd: dict[str, Any] = {
        "expectedEmail": "custom@example.com",
        "expectedAccounts": ["custom@example.com", "other@example.com"],
    }
    payload2: dict[str, Any] = {"rpcId": "tGMBJ"}
    out2 = broker._attach_identity_preflight(payload2, custom_cmd)
    assert out2["expectedEmail"] == "custom@example.com"
    assert out2["expectedAccounts"] == ["custom@example.com", "other@example.com"]


@pytest.mark.asyncio
async def test_broker_readonly_permits_query_notebook_and_blocks_mutations(tmp_path: Path) -> None:
    from mcp_gateway.schemas.error import PERMISSION_DENIED

    allowlist_p = tmp_path / "allowlist.json"
    allowlist_p.write_text(
        json.dumps({
            "version": 2,
            "provider_mode": "browser",
            "accounts": ["developer@gmail.com"],
            "notebooks": {
                "nb-ro": {"title": "Read Only Docs", "mode": "READ_ONLY"},
                "nb-rw": {"title": "Interactive Docs", "mode": "INTERACTIVE"},
            },
        }),
        encoding="utf-8",
    )
    daemon = BrokerDaemon(
        BrokerConfig(
            socket_path=str(tmp_path / "ro.sock"),
            allowlist_path=allowlist_p,
            journal_db_path=tmp_path / "journal.db",
        )
    )

    # Lock session to nb-ro
    sel_res = await daemon.dispatch({"action": "select_notebook", "notebook_id": "nb-ro"})
    assert sel_res["ok"] is True
    assert sel_res.get("mode") == "READ_ONLY"

    # 1. query_notebook MUST BE PERMITTED on READ_ONLY notebooks (reaches companion -> AUTH_REQUIRED in unit test)
    q_res = await daemon.dispatch({
        "action": "query_notebook",
        "notebook_id": "nb-ro",
        "question": "What is the architecture?",
        "request_key": "req-ro-allowed-1",
    })
    assert q_res["ok"] is False
    assert q_res["error"]["code"] == AUTH_REQUIRED  # Permitted past RBAC policy!

    # 2. Mutating tools (add_source, create_note, delete_note) MUST BE BLOCKED with PERMISSION_DENIED
    add_res = await daemon.dispatch({
        "action": "add_source",
        "notebook_id": "nb-ro",
        "idempotency_key": "idem-ro-1",
        "source": {"type": "text", "title": "Note", "content": "Body"},
    })
    assert add_res["ok"] is False
    assert add_res["error"]["code"] == PERMISSION_DENIED
    assert "READ_ONLY" in add_res["error"]["message"]

    note_res = await daemon.dispatch({
        "action": "create_note",
        "notebook_id": "nb-ro",
        "title": "Note",
        "content": "Body",
        "idempotency_key": "idem-ro-note",
    })
    assert note_res["ok"] is False
    assert note_res["error"]["code"] == PERMISSION_DENIED

    del_res = await daemon.dispatch({
        "action": "delete_note",
        "notebook_id": "nb-ro",
        "note_id": "note-1",
        "idempotency_key": "idem-ro-del",
    })
    assert del_res["ok"] is False
    assert del_res["error"]["code"] == PERMISSION_DENIED


@pytest.mark.asyncio
async def test_broker_live_allowlist_reload_with_mutex_and_uuid_validation(
    broker: BrokerDaemon,
) -> None:
    from mcp_gateway.schemas.error import INVALID_ARGUMENT, PERMISSION_DENIED

    valid_uuid = "123e4567-e89b-12d3-a456-426614174000"

    # 1. get_allowlist works in DISCOVERY_ONLY without SESSION_UNLOCKED
    get_res = await broker.dispatch({"action": "get_allowlist"})
    assert get_res["ok"] is True
    assert "nb-allowed-1" in get_res["notebooks"]

    # 2. update_allowlist rejects path traversal / malformed manual IDs when validate_uuids=True
    bad_res = await broker.dispatch({
        "action": "update_allowlist",
        "validate_uuids": True,
        "notebooks": {
            "../../etc/passwd": {"title": "Traversal", "mode": "READ_ONLY"},
        },
    })
    assert bad_res["ok"] is False
    assert bad_res["error"]["code"] == INVALID_ARGUMENT

    # 3. update_allowlist accepts valid UUIDs, saves atomically, and calls self.allowlist_config.reload() under _session_mutex
    upd_res = await broker.dispatch({
        "action": "update_allowlist",
        "validate_uuids": True,
        "notebooks": {
            valid_uuid: {"title": "Live Reloaded NB", "mode": "READ_ONLY"},
        },
    })
    assert upd_res["ok"] is True
    assert upd_res["notebooks"][valid_uuid]["mode"] == "READ_ONLY"
    assert is_notebook_allowed(broker.allowlist_config, valid_uuid) is True

    # 4. Selecting the newly added notebook succeeds immediately in the live session and enforces READ_ONLY
    sel_res = await broker.dispatch({"action": "select_notebook", "notebook_id": valid_uuid})
    assert sel_res["ok"] is True
    assert sel_res["mode"] == "READ_ONLY"

    mut_res = await broker.dispatch({
        "action": "add_source",
        "notebook_id": valid_uuid,
        "idempotency_key": "idem-live-1",
        "source": {"type": "text", "title": "T", "content": "C"},
    })
    assert mut_res["ok"] is False
    assert mut_res["error"]["code"] == PERMISSION_DENIED

    # 5. companion_forward is not blocked by SessionLock in DISCOVERY_ONLY or LOCKED
    fwd_res = await broker.dispatch({
        "action": "companion_forward",
        "companion_command": "batchexecute",
        "payload": {"rpcId": "wXbhsf", "paramsJson": "[]"},
    })
    assert fwd_res["ok"] is False
    assert fwd_res["error"]["code"] == AUTH_REQUIRED


@pytest.mark.asyncio
async def test_companion_frame_drain_serialization(allowlist_file: Path) -> None:
    """Ensures hello_ack and HEARTBEAT_PONG socket writes are mutex-protected against race conditions."""
    config = BrokerConfig(allowlist_path=allowlist_file)
    broker = BrokerDaemon(config)

    drain_locked_states: list[bool] = []

    class MockWriter:
        def __init__(self) -> None:
            self.written_bytes = bytearray()

        def write(self, data: bytes) -> None:
            self.written_bytes.extend(data)

        async def drain(self) -> None:
            drain_locked_states.append(broker._companion_ipc_mutex.locked())

        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    writer = MockWriter()

    # Test hello handshake
    hello_payload = json.dumps({"type": "hello"}).encode("utf-8")
    hello_frame = struct.pack(">I", len(hello_payload)) + hello_payload

    # Test ping frame
    ping_payload = json.dumps({"type": "HEARTBEAT_PING", "requestId": "req-999"}).encode("utf-8")
    ping_frame = struct.pack(">I", len(ping_payload)) + ping_payload

    mock_reader = asyncio.StreamReader()
    mock_reader.feed_data(hello_frame + ping_frame)
    mock_reader.feed_eof()

    await broker.handle_ipc_connection(mock_reader, cast(Any, writer))

    assert len(drain_locked_states) == 2
    assert drain_locked_states == [True, True]


@pytest.mark.asyncio
async def test_handle_query_notebook_confirmed_replay_cache_validation(broker: BrokerDaemon) -> None:
    """Ensures confirmed query replay strictly verifies cached entry and rejects corrupted cache without stubs."""
    from mcp_gateway.schemas.error import REQUEST_KEY_CONFLICT
    from mcp_gateway.storage.journal import MutationState, OperationType

    sel = await broker.dispatch({"action": "select_notebook", "notebook_id": "nb-allowed-1"})
    assert sel["ok"] is True

    req_key = "req-query-cache-test-1"

    # 1. Prepare and confirm mutation in journal
    broker.journal.prepare(
        request_key=req_key,
        notebook_id="nb-allowed-1",
        operation_type=OperationType.QUERY_NOTEBOOK,
        args={"action": "query_notebook", "notebook_id": "nb-allowed-1", "question": "What is AI?", "request_key": req_key},
        capability_secret=broker.config.capability_secret,
    )
    broker.journal.transition(req_key, MutationState.SENT)
    broker.journal.transition(req_key, MutationState.CONFIRMED)

    # 2. Replay with missing query_cache returns REQUEST_KEY_CONFLICT, NOT {citations: []}
    res_missing = await broker.dispatch({
        "action": "query_notebook",
        "notebook_id": "nb-allowed-1",
        "question": "What is AI?",
        "request_key": req_key,
    })
    assert res_missing["ok"] is False
    assert res_missing["error"]["code"] == REQUEST_KEY_CONFLICT
    assert "cache entry is missing or mismatched" in res_missing["error"]["message"]

    # 3. Save matching cache entry
    broker.journal.put_query_cache(
        cache_key=req_key,
        notebook_id="nb-allowed-1",
        query_text="What is AI?",
        response_payload=json.dumps({"answer": "AI is artificial intelligence.", "citations": ["doc-1"]}),
    )

    # Replay with matching key & args succeeds from cache
    res_cached = await broker.dispatch({
        "action": "query_notebook",
        "notebook_id": "nb-allowed-1",
        "question": "What is AI?",
        "request_key": req_key,
    })
    assert res_cached["ok"] is True
    assert res_cached["cached"] is True
    assert res_cached["answer"] == "AI is artificial intelligence."
    assert res_cached["citations"] == ["doc-1"]

    # 4. Replay with conflicting question returns REQUEST_KEY_CONFLICT
    res_conflict = await broker.dispatch({
        "action": "query_notebook",
        "notebook_id": "nb-allowed-1",
        "question": "What is Machine Learning?",
        "request_key": req_key,
    })
    assert res_conflict["ok"] is False
    assert res_conflict["error"]["code"] == REQUEST_KEY_CONFLICT


@pytest.mark.asyncio
async def test_mutation_handlers_detect_conflicting_parameters(broker: BrokerDaemon) -> None:
    """Verifies add_source, create_note, delete_note reject reused idempotency keys with different arguments."""
    from mcp_gateway.schemas.error import REQUEST_KEY_CONFLICT
    from mcp_gateway.storage.journal import OperationType

    sel = await broker.dispatch({"action": "select_notebook", "notebook_id": "nb-allowed-1"})
    assert sel["ok"] is True

    # Conflicting add_source
    k1 = "idem-src-1"
    broker.journal.prepare(
        request_key=k1,
        notebook_id="nb-allowed-1",
        operation_type=OperationType.ADD_SOURCE,
        args={"action": "add_source", "notebook_id": "nb-allowed-1", "idempotency_key": k1, "source": {"type": "text", "title": "A", "content": "1"}},
        capability_secret=broker.config.capability_secret,
    )
    # Attempt same key on different notebook via direct handler
    res_nb_diff = await broker._handle_add_source({
        "notebook_id": "nb-allowed-2",
        "idempotency_key": k1,
        "source": {"type": "text", "title": "A", "content": "1"},
    })
    assert res_nb_diff["ok"] is False
    assert res_nb_diff["error"]["code"] == REQUEST_KEY_CONFLICT

    # Attempt same key with conflicting payload via dispatch
    res_payload_diff = await broker.dispatch({
        "action": "add_source",
        "notebook_id": "nb-allowed-1",
        "idempotency_key": k1,
        "source": {"type": "text", "title": "A", "content": "DIFFERENT"},
    })
    assert res_payload_diff["ok"] is False
    assert res_payload_diff["error"]["code"] == REQUEST_KEY_CONFLICT

    # Conflicting create_note
    k2 = "idem-note-1"
    broker.journal.prepare(
        request_key=k2,
        notebook_id="nb-allowed-1",
        operation_type=OperationType.CREATE_NOTE,
        args={"action": "create_note", "notebook_id": "nb-allowed-1", "idempotency_key": k2, "title": "T1", "content": "C1"},
        capability_secret=broker.config.capability_secret,
    )
    res_note_diff = await broker.dispatch({
        "action": "create_note",
        "notebook_id": "nb-allowed-1",
        "idempotency_key": k2,
        "title": "T2",
        "content": "C2",
    })
    assert res_note_diff["ok"] is False
    assert res_note_diff["error"]["code"] == REQUEST_KEY_CONFLICT

    # Conflicting delete_note
    k3 = "idem-del-1"
    broker.journal.prepare(
        request_key=k3,
        notebook_id="nb-allowed-1",
        operation_type=OperationType.DELETE_NOTE,
        args={"action": "delete_note", "notebook_id": "nb-allowed-1", "idempotency_key": k3, "note_id": "note-1"},
        capability_secret=broker.config.capability_secret,
    )
    res_del_diff = await broker.dispatch({
        "action": "delete_note",
        "notebook_id": "nb-allowed-1",
        "idempotency_key": k3,
        "note_id": "note-2",
    })
    assert res_del_diff["ok"] is False
    assert res_del_diff["error"]["code"] == REQUEST_KEY_CONFLICT


@pytest.mark.asyncio
async def test_update_allowlist_preserves_legacy_ids_unless_manual(broker: BrokerDaemon) -> None:
    # 1. Update allowlist with legacy non-UUID notebook ID (without manual: true) passes
    res_legacy = await broker.dispatch({
        "action": "update_allowlist",
        "notebooks": {
            "legacy-nb-custom-1": {"title": "Legacy Notebook", "mode": "READ_ONLY"},
        },
    })
    assert res_legacy["ok"] is True
    assert "legacy-nb-custom-1" in broker.allowlist_config.notebook_permissions

    # 2. Update allowlist with legacy non-UUID notebook ID with manual: true fails
    res_manual_bad = await broker.dispatch({
        "action": "update_allowlist",
        "notebooks": {
            "legacy-nb-custom-2": {"title": "Manual Non-UUID", "mode": "READ_ONLY", "manual": True},
        },
    })
    assert res_manual_bad["ok"] is False
    assert res_manual_bad["error"]["code"] == "INVALID_ARGUMENT"
