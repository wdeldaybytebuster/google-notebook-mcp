"""Tests for Phase 8: Full MCP 2025/2026 Protocol Standardization.

Verifies:
- Standard capability negotiation (tools, resources, prompts, logging).
- Resources list and resource templates list.
- Read resource handler with Invariant 3 (Universal Security Interceptor Gate).
- Prompts list and prompts get handlers with ADR-011 session lock gating.
- Progress notification delivery.
- Tool behavioral annotations (readOnlyHint, destructiveHint, idempotentHint).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generator, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import mcp.types as types
from mcp.server.lowlevel.server import NotificationOptions
from mcp.shared.exceptions import MCPError

from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon, McpFacade
from mcp_gateway.schemas.error import (
    ALLOWLIST_DENIED,
    INVALID_ARGUMENT,
    NOT_FOUND,
    PERMISSION_DENIED,
    SESSION_UNLOCKED,
)
from mcp_gateway.schemas.tools import TOOL_ANNOTATIONS


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


def test_mcp_capability_negotiation(mock_broker: BrokerDaemon) -> None:
    """Verifies that McpFacade advertises tools, resources, prompts, and logging capabilities."""
    facade = McpFacade(mock_broker)
    notif_opts = NotificationOptions(
        tools_changed=True,
        prompts_changed=True,
        resources_changed=True,
    )
    caps = facade.server.get_capabilities(notification_options=notif_opts)

    assert caps.tools is not None
    assert caps.tools.list_changed is True

    assert caps.resources is not None
    assert caps.resources.subscribe is False
    assert caps.resources.list_changed is True

    assert caps.prompts is not None
    assert caps.prompts.list_changed is True

    assert caps.logging is not None


@pytest.mark.asyncio
async def test_mcp_resource_templates_list(mock_broker: BrokerDaemon) -> None:
    """Verifies resources/templates/list returns standard notebooklm:// templates."""
    facade = McpFacade(mock_broker)
    entry = facade.server._request_handlers.get("resources/templates/list")
    assert entry is not None

    req = types.ListResourceTemplatesRequest(method="resources/templates/list")
    res = await entry.handler(cast(Any, None), req)
    assert isinstance(res, types.ListResourceTemplatesResult)
    templates = res.resource_templates
    assert len(templates) == 4

    uris = [t.uri_template for t in templates]
    assert "notebooklm://notebooks/{notebook_id}/metadata" in uris
    assert "notebooklm://notebooks/{notebook_id}/sources/{source_id}" in uris
    assert "notebooklm://notebooks/{notebook_id}/notes/{note_id}" in uris
    assert "notebooklm://notebooks/{notebook_id}/artifacts/{artifact_id}" in uris


@pytest.mark.asyncio
async def test_mcp_resources_list(mock_broker: BrokerDaemon) -> None:
    """Verifies resources/list returns active resources when locked and empty when unlocked."""
    facade = McpFacade(mock_broker)
    entry = facade.server._request_handlers.get("resources/list")
    assert entry is not None

    # Step 1: Unlocked session returns empty resources list
    req = types.ListResourcesRequest(method="resources/list")
    res_unlocked = await entry.handler(cast(Any, None), req)
    assert isinstance(res_unlocked, types.ListResourcesResult)
    assert len(res_unlocked.resources) == 0

    # Step 2: Lock session to nb-1
    await mock_broker.session_lock.select_notebook("nb-1", is_allowed=True)
    res_locked = await entry.handler(cast(Any, None), req)
    assert isinstance(res_locked, types.ListResourcesResult)
    assert len(res_locked.resources) == 4
    uris = [r.uri for r in res_locked.resources]
    assert "notebooklm://notebooks/nb-1/metadata" in uris
    assert "notebooklm://notebooks/nb-1/sources" in uris
    assert "notebooklm://notebooks/nb-1/notes" in uris
    assert "notebooklm://notebooks/nb-1/artifacts" in uris


@pytest.mark.asyncio
async def test_mcp_resources_read_invariant_3(mock_broker: BrokerDaemon) -> None:
    """Verifies Invariant 3: Universal Security Interceptor Gate on resources/read."""
    facade = McpFacade(mock_broker)
    entry = facade.server._request_handlers.get("resources/read")
    assert entry is not None

    # 1. Malformed URI raises MCPError with INVALID_ARGUMENT
    req_malformed = types.ReadResourceRequestParams(uri="http://malicious.com/data")
    with pytest.raises(MCPError) as exc_info:
        await entry.handler(cast(Any, None), req_malformed)
    assert "Invalid notebooklm resource URI" in str(exc_info.value)

    # 2. Reading resource before ADR-011 lock raises MCPError with SESSION_UNLOCKED
    req_pre_lock = types.ReadResourceRequestParams(uri="notebooklm://notebooks/nb-1/metadata")
    with pytest.raises(MCPError) as exc_info:
        await entry.handler(cast(Any, None), req_pre_lock)
    assert "SESSION_UNLOCKED" in str(exc_info.value.data)

    # Lock session to nb-1
    await mock_broker.session_lock.select_notebook("nb-1", is_allowed=True)

    # 3. Cross-notebook read targeting nb-2 while locked to nb-1 raises PERMISSION_DENIED
    req_cross = types.ReadResourceRequestParams(uri="notebooklm://notebooks/nb-2/metadata")
    with pytest.raises(MCPError) as exc_info:
        await entry.handler(cast(Any, None), req_cross)
    assert "PERMISSION_DENIED" in str(exc_info.value.data)

    # 4. Read targeting non-allowlisted notebook raises ALLOWLIST_DENIED
    # Unlock and lock to non-allowlisted is prevented by select_notebook,
    # but test interceptor directly if somehow forced:
    with patch.object(mock_broker.session_lock, "locked_notebook_id", "nb-forbidden"):
        req_forbidden = types.ReadResourceRequestParams(uri="notebooklm://notebooks/nb-forbidden/metadata")
        with pytest.raises(MCPError) as exc_info:
            await entry.handler(cast(Any, None), req_forbidden)
        assert "ALLOWLIST_DENIED" in str(exc_info.value.data)

    # 5. Valid metadata read returns TextResourceContents
    with patch.object(mock_broker, "dispatch", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = {
            "ok": True,
            "notebook_id": "nb-1",
            "title": "My Test Notebook",
            "sources": [],
        }
        req_valid = types.ReadResourceRequestParams(uri="notebooklm://notebooks/nb-1/metadata")
        res_valid = await entry.handler(cast(Any, None), req_valid)
        assert isinstance(res_valid, types.ReadResourceResult)
        assert len(res_valid.contents) == 1
        content = res_valid.contents[0]
        assert isinstance(content, types.TextResourceContents)
        assert content.uri == "notebooklm://notebooks/nb-1/metadata"
        assert content.mime_type == "application/json"
        parsed = json.loads(content.text)
        assert parsed["title"] == "My Test Notebook"


@pytest.mark.asyncio
async def test_mcp_prompts_list_and_get(mock_broker: BrokerDaemon) -> None:
    """Verifies prompts/list and prompts/get with ADR-011 session lock gating."""
    facade = McpFacade(mock_broker)
    list_entry = facade.server._request_handlers.get("prompts/list")
    get_entry = facade.server._request_handlers.get("prompts/get")
    assert list_entry is not None
    assert get_entry is not None

    # Step 1: prompts/list returns 3 standard prompts
    req_list = types.ListPromptsRequest(method="prompts/list")
    res_list = await list_entry.handler(cast(Any, None), req_list)
    assert isinstance(res_list, types.ListPromptsResult)
    names = [p.name for p in res_list.prompts]
    assert "synthesize-research" in names
    assert "audit-security-invariants" in names
    assert "summarize-notebook-context" in names

    # Step 2: prompts/get before lock raises SESSION_UNLOCKED
    req_get = types.GetPromptRequestParams(name="synthesize-research")
    with pytest.raises(MCPError) as exc_info:
        await get_entry.handler(cast(Any, None), req_get)
    assert "SESSION_UNLOCKED" in str(exc_info.value.data)

    # Lock session to nb-1
    await mock_broker.session_lock.select_notebook("nb-1", is_allowed=True)

    # Step 3: prompts/get when locked returns prompt message referencing locked notebook
    res_get = await get_entry.handler(cast(Any, None), req_get)
    assert isinstance(res_get, types.GetPromptResult)
    assert len(res_get.messages) == 1
    msg = res_get.messages[0]
    assert msg.role == "user"
    assert isinstance(msg.content, types.TextContent)
    assert "nb-1" in msg.content.text

    # Step 4: Unknown prompt name raises NOT_FOUND
    req_unknown = types.GetPromptRequestParams(name="non-existent-prompt")
    with pytest.raises(MCPError) as exc_info:
        await get_entry.handler(cast(Any, None), req_unknown)
    assert "NOT_FOUND" in str(exc_info.value.data)


@pytest.mark.asyncio
async def test_mcp_progress_notification(mock_broker: BrokerDaemon) -> None:
    """Verifies send_progress_notification forwards parameters to active session."""
    facade = McpFacade(mock_broker)
    mock_session = MagicMock()
    mock_session.send_progress_notification = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.session = mock_session

    await facade.send_progress_notification(
        mock_ctx,
        progress_token="prog-token-123",
        progress=45.0,
        total=100.0,
        message="Generating Audio Overview...",
    )

    mock_session.send_progress_notification.assert_awaited_once_with(
        progress_token="prog-token-123",
        progress=45.0,
        total=100.0,
        message="Generating Audio Overview...",
    )


def test_twelve_tool_annotations() -> None:
    """Verifies all 12 tools have valid hints registered in TOOL_ANNOTATIONS."""
    assert len(TOOL_ANNOTATIONS) == 12
    for tool_name, hints in TOOL_ANNOTATIONS.items():
        assert "readOnlyHint" in hints
        assert isinstance(hints["readOnlyHint"], bool)
        assert "destructiveHint" in hints
        assert isinstance(hints["destructiveHint"], bool)
        assert "idempotentHint" in hints
        assert isinstance(hints["idempotentHint"], bool)
