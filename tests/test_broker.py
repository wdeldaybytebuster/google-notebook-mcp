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
    make_error,
)
from mcp_gateway.schemas.tools import (
    ADD_SOURCE_SCHEMA,
    GET_NOTEBOOK_METADATA_SCHEMA,
    LIST_NOTEBOOKS_SCHEMA,
    LIST_SOURCES_SCHEMA,
    QUERY_NOTEBOOK_SCHEMA,
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
    # Denied notebook
    cmd_denied = {
        "action": "get_notebook_metadata",
        "notebook_id": "nb-forbidden",
    }
    res_denied = await broker.dispatch(cmd_denied)
    assert res_denied["ok"] is False
    assert res_denied["error"]["code"] == ALLOWLIST_DENIED

    # Allowed notebook but companion extension not connected -> AUTH_REQUIRED
    cmd_allowed = {
        "action": "get_notebook_metadata",
        "notebook_id": "nb-allowed-1",
    }
    res_allowed = await broker.dispatch(cmd_allowed)
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
        "get_notebook_metadata",
        "list_sources",
        "query_notebook",
        "add_source",
    ]

    # Call tool with forbidden notebook
    call_entry = facade.server._request_handlers.get("tools/call")
    assert call_entry is not None

    call_req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(
            name="get_notebook_metadata",
            arguments={"notebook_id": "nb-forbidden"},
        ),
    )
    call_res = await call_entry.handler(cast(Any, None), call_req)
    assert isinstance(call_res, types.CallToolResult)
    assert call_res.is_error is True
    assert len(call_res.content) == 1
    item = call_res.content[0]
    assert isinstance(item, types.TextContent)
    payload = json.loads(item.text)
    assert payload["ok"] is False
    assert payload["error"]["code"] == ALLOWLIST_DENIED
