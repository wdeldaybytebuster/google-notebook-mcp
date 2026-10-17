from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
import pytest

from mcp_gateway.broker.allowlist import (
    AllowlistConfig,
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
    GET_NOTEBOOK_METADATA_SCHEMA,
    LIST_NOTEBOOKS_SCHEMA,
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


def test_five_tool_schemas_and_annotations() -> None:
    schemas = [
        LIST_NOTEBOOKS_SCHEMA,
        SELECT_NOTEBOOK_SCHEMA,
        GET_NOTEBOOK_METADATA_SCHEMA,
        LIST_SOURCES_SCHEMA,
        QUERY_NOTEBOOK_SCHEMA,
        ADD_SOURCE_SCHEMA,
    ]
    for s in schemas:
        assert s["additionalProperties"] is False
        assert s["type"] == "object"

    for tool_name, hints in TOOL_ANNOTATIONS.items():
        assert "readOnlyHint" in hints
        assert "destructiveHint" in hints
        assert "idempotentHint" in hints


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
    ]

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
