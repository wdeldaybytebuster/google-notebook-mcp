"""Unit tests for project notebook configuration and in-chat user confirmation prompts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from mcp_gateway.broker.allowlist import AllowlistConfig
from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon
from mcp_gateway.broker.project_config import (
    PROJECT_CONFIG_FILENAME,
    get_project_notebook_config,
    save_project_notebook_config,
)
from mcp_gateway.broker.session import SessionLock, SessionState
from mcp_gateway.schemas.error import SESSION_UNLOCKED
from mcp_gateway.schemas.tools import (
    SELECT_NOTEBOOK_SCHEMA,
    SelectNotebookInput,
    validate_tool_args,
)


def test_project_config_read_write(tmp_path: Path) -> None:
    """Verifies reading and saving .notebook_mcp.json."""
    assert get_project_notebook_config(tmp_path) is None

    saved = save_project_notebook_config(
        notebook_id="test-nb-123",
        title="My Project Notebook",
        project_dir=tmp_path,
    )
    assert saved is not None
    assert saved.exists()

    cfg = get_project_notebook_config(tmp_path)
    assert cfg is not None
    assert cfg["notebook_id"] == "test-nb-123"
    assert cfg["title"] == "My Project Notebook"
    assert "updated_at" in cfg


def test_select_notebook_schema_validation() -> None:
    """Verifies SELECT_NOTEBOOK_SCHEMA and SelectNotebookInput with save_for_project."""
    valid_args: dict[str, Any] = {"notebook_id": "nb-123", "save_for_project": True}
    assert validate_tool_args("select_notebook", valid_args) is None

    pydantic_obj = SelectNotebookInput.model_validate(valid_args)
    assert pydantic_obj.save_for_project is True

    # Closed schema validation: extra field must fail
    invalid_args: dict[str, Any] = {"notebook_id": "nb-123", "unknown_field": "disallowed"}
    assert validate_tool_args("select_notebook", invalid_args) is not None

    with pytest.raises(ValueError):
        SelectNotebookInput.model_validate(invalid_args)


@pytest.mark.asyncio
async def test_session_unlocked_message_with_and_without_project_config(tmp_path: Path) -> None:
    """Verifies SESSION_UNLOCKED error envelope contains actionable in-chat confirmation prompt."""
    lock = SessionLock()

    # Without project config
    with patch("pathlib.Path.cwd", return_value=tmp_path):
        err = await lock.validate_and_prepare("list_sources", {"notebook_id": "any"})
        assert err is not None
        assert err.error.code == SESSION_UNLOCKED
        assert "Which Google Notebook would you like to use for this project?" in err.error.message

    # With project config
    save_project_notebook_config("nb-configured-456", "Configured Architecture Notebook", tmp_path)
    with patch("pathlib.Path.cwd", return_value=tmp_path):
        err2 = await lock.validate_and_prepare("list_sources", {"notebook_id": "any"})
        assert err2 is not None
        assert err2.error.code == SESSION_UNLOCKED
        assert "Configured Architecture Notebook" in err2.error.message
        assert "Please double-check with the user" in err2.error.message


@pytest.mark.asyncio
async def test_list_notebooks_includes_project_config_and_user_prompt(tmp_path: Path) -> None:
    """Verifies list_notebooks surfaces project default and guidance prompt."""
    allowlist_file = tmp_path / "allowlist.json"
    allowlist_file.write_text(
        json.dumps({
            "version": 1,
            "provider_mode": "browser",
            "accounts": ["test@example.com"],
            "notebooks": ["nb-allowed-1"],
        }),
        encoding="utf-8",
    )
    config = BrokerConfig(allowlist_path=allowlist_file)
    broker = BrokerDaemon(config)

    # Mock _fetch_all_allowed_notebooks
    broker._fetch_all_allowed_notebooks = AsyncMock(  # type: ignore[method-assign]
        return_value=([{"id": "nb-allowed-1", "title": "Allowed Project Notebook"}], None)
    )

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        # Case 1: No project config
        res_no_cfg = await broker.dispatch({"action": "list_notebooks"})
        assert res_no_cfg["ok"] is True
        assert res_no_cfg["project_config"]["configured"] is False
        assert "No project default notebook is configured yet" in res_no_cfg["user_prompt"]

        # Case 2: Config exists
        save_project_notebook_config("nb-allowed-1", "Allowed Project Notebook", tmp_path)
        res_cfg = await broker.dispatch({"action": "list_notebooks"})
        assert res_cfg["ok"] is True
        assert res_cfg["project_config"]["configured"] is True
        assert res_cfg["project_config"]["notebook_id"] == "nb-allowed-1"
        assert "Please double-check with the user" in res_cfg["user_prompt"]


@pytest.mark.asyncio
async def test_select_notebook_saves_project_config(tmp_path: Path) -> None:
    """Verifies select_notebook writes .notebook_mcp.json when save_for_project is True."""
    allowlist_file = tmp_path / "allowlist.json"
    allowlist_file.write_text(
        json.dumps({
            "version": 1,
            "provider_mode": "browser",
            "accounts": ["test@example.com"],
            "notebooks": ["nb-allowed-1"],
        }),
        encoding="utf-8",
    )
    config = BrokerConfig(allowlist_path=allowlist_file)
    broker = BrokerDaemon(config)
    broker._fetch_all_allowed_notebooks = AsyncMock(  # type: ignore[method-assign]
        return_value=([{"id": "nb-allowed-1", "title": "Allowed Project Notebook"}], None)
    )

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        res = await broker.dispatch({
            "action": "select_notebook",
            "notebook_id": "nb-allowed-1",
            "save_for_project": True,
        })
        assert res["ok"] is True
        assert res.get("project_saved") is True

        cfg = get_project_notebook_config(tmp_path)
        assert cfg is not None
        assert cfg["notebook_id"] == "nb-allowed-1"
        assert cfg["title"] == "Allowed Project Notebook"
