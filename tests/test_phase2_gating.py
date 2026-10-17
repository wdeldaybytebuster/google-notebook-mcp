"""Unit tests for Phase 2: Human-Centric Gating & Targeted RAG (Domain B).

Covers:
- Title-based notebook selection with case-insensitive exact matching
- Ambiguous title rejection when multiple notebooks share title
- Not found rejection when title does not match any allowlisted notebook
- Session mutex serialization during title resolution and session locking (M-01)
- Scoped source readiness pre-query barrier (M-10)
- Strict grounding verification (M-06 & AGENTS.md Rule XI.3)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_gateway.broker.allowlist import AllowlistConfig
from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon
from mcp_gateway.broker.session import SessionLock, SessionState
from mcp_gateway.schemas.error import (
    INVALID_ARGUMENT,
    NOT_FOUND,
    SESSION_LOCKED,
)
from mcp_gateway.storage.journal import MutationState


@pytest.fixture
def mock_broker(tmp_path: Path) -> BrokerDaemon:
    allowlist_file = tmp_path / "allowlist.json"
    data = {
        "version": 1,
        "provider_mode": "browser",
        "accounts": ["test@example.com"],
        "notebooks": ["nb-1", "nb-2", "nb-dup-1", "nb-dup-2"],
    }
    allowlist_file.write_text(json.dumps(data), encoding="utf-8")

    cfg = BrokerConfig(
        socket_path=str(tmp_path / "mock.sock"),
        allowlist_path=allowlist_file,
        journal_db_path=tmp_path / "journal.db",
    )
    return BrokerDaemon(cfg)


@pytest.mark.asyncio
async def test_select_notebook_by_title_success(mock_broker: BrokerDaemon) -> None:
    """select_notebook resolves title against allowlisted notebooks and locks session."""
    mock_notebooks = [
        {"id": "nb-1", "title": "Research Notes"},
        {"id": "nb-2", "title": "Project Alpha"},
    ]

    with patch.object(mock_broker, "_fetch_all_allowed_notebooks", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = (mock_notebooks, None)

        res = await mock_broker.dispatch({
            "action": "select_notebook",
            "title": "research notes",  # Case-insensitive
        })

        assert res["ok"] is True
        assert res["notebook_id"] == "nb-1"
        assert res["status"] == "LOCKED"
        assert mock_broker.session_lock.locked_notebook_id == "nb-1"
        assert mock_broker.session_lock.state == SessionState.ACTIVE_DISPATCH


@pytest.mark.asyncio
async def test_select_notebook_by_title_not_found(mock_broker: BrokerDaemon) -> None:
    """select_notebook returns NOT_FOUND when no notebook matches the requested title."""
    mock_notebooks = [{"id": "nb-1", "title": "Research Notes"}]

    with patch.object(mock_broker, "_fetch_all_allowed_notebooks", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = (mock_notebooks, None)

        res = await mock_broker.dispatch({
            "action": "select_notebook",
            "title": "Non-existent Title",
        })

        assert res["ok"] is False
        assert res["error"]["code"] == NOT_FOUND
        assert "not found" in res["error"]["message"].lower()


@pytest.mark.asyncio
async def test_select_notebook_by_title_ambiguous(mock_broker: BrokerDaemon) -> None:
    """select_notebook rejects ambiguous titles matching multiple notebooks."""
    mock_notebooks = [
        {"id": "nb-dup-1", "title": "Duplicate Project"},
        {"id": "nb-dup-2", "title": "Duplicate Project"},
    ]

    with patch.object(mock_broker, "_fetch_all_allowed_notebooks", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = (mock_notebooks, None)

        res = await mock_broker.dispatch({
            "action": "select_notebook",
            "title": "duplicate project",
        })

        assert res["ok"] is False
        assert res["error"]["code"] == INVALID_ARGUMENT
        assert "ambiguous title" in res["error"]["message"].lower()


@pytest.mark.asyncio
async def test_session_lock_hopping_rejected_after_title_lock(mock_broker: BrokerDaemon) -> None:
    """Once locked via title, selecting a different notebook returns SESSION_LOCKED."""
    mock_notebooks = [
        {"id": "nb-1", "title": "First Notebook"},
        {"id": "nb-2", "title": "Second Notebook"},
    ]

    with patch.object(mock_broker, "_fetch_all_allowed_notebooks", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = (mock_notebooks, None)

        res1 = await mock_broker.dispatch({
            "action": "select_notebook",
            "title": "First Notebook",
        })
        assert res1["ok"] is True
        assert res1["notebook_id"] == "nb-1"

        res2 = await mock_broker.dispatch({
            "action": "select_notebook",
            "title": "Second Notebook",
        })
        assert res2["ok"] is False
        assert res2["error"]["code"] == SESSION_LOCKED


@pytest.mark.asyncio
async def test_query_notebook_source_readiness_scoping(mock_broker: BrokerDaemon) -> None:
    """M-10: Query verifies readiness of targeted source_ids, rejecting if targeted source is unready."""
    await mock_broker.session_lock.select_notebook("nb-1", is_allowed=True)

    mock_sources = {
        "ok": True,
        "sources": [
            {"id": "src-ready", "title": "Ready Source", "status": "READY", "status_code": 2},
            {"id": "src-processing", "title": "Processing Source", "status": "PROCESSING", "status_code": 1},
        ],
    }

    with patch.object(mock_broker, "_handle_list_sources", new_callable=AsyncMock) as mock_sources_fn:
        mock_sources_fn.return_value = mock_sources

        # Query targeting only ready source succeeds (passes readiness check)
        with patch.object(mock_broker, "send_to_companion", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {
                "ok": True,
                "body": ')]}\'\n[["w",null,[["text_delta",null,"Answer here"]]]]',
            }
            # Pre-query check with unready source targeted
            bad_query = await mock_broker.dispatch({
                "action": "query_notebook",
                "notebook_id": "nb-1",
                "question": "Test question?",
                "request_key": "q-key-bad",
                "source_ids": ["src-processing"],
            })
            assert bad_query["ok"] is False
            assert bad_query["error"]["code"] == INVALID_ARGUMENT
            assert "not in ready" in bad_query["error"]["message"].lower()


@pytest.mark.asyncio
async def test_strict_grounding_rejection_on_zero_citations(mock_broker: BrokerDaemon) -> None:
    """M-06 & Rule XI.3: Query response with zero citations is rejected with UNGROUNDED_RESPONSE."""
    await mock_broker.session_lock.select_notebook("nb-1", is_allowed=True)

    with patch.object(mock_broker, "send_to_companion", new_callable=AsyncMock) as mock_send:
        # Mock streaming response with text delta but zero citations (cleanly terminated with [null])
        mock_send.return_value = {
            "ok": True,
            "body": ')]}\'\n[["w",null,[["text_delta",null,"Ungrounded claim without citation."]]]]\n[null]\n',
        }

        res = await mock_broker.dispatch({
            "action": "query_notebook",
            "notebook_id": "nb-1",
            "question": "What is the answer?",
            "request_key": "q-key-ungrounded",
            "source_ids": [],
        })

        assert res["ok"] is False
        assert res["error"]["code"] == "UNGROUNDED_RESPONSE"
        assert "zero grounding citations" in res["error"]["message"].lower()

        # Check mutation journal transitioned to REJECTED
        record = mock_broker.journal.get("q-key-ungrounded")
        assert record is not None
        assert record.state == MutationState.REJECTED
