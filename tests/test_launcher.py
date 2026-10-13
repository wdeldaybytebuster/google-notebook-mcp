"""Tests for the Phase 1 Dedicated Browser Launcher and Phase 2 Allowlist Wizard."""

from __future__ import annotations

import asyncio
import json
import struct
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from mcp_gateway.launcher import (
    DedicatedBrowserLauncher,
    _cdp_check_auth,
    find_chrome_binary,
)
from mcp_gateway.broker.allowlist import (
    AllowlistConfig,
    DEFAULT_ALLOWLIST_PATH,
    save_allowlist,
)


# ---------------------------------------------------------------------------
# find_chrome_binary
# ---------------------------------------------------------------------------


def test_find_chrome_binary_returns_none_when_missing(tmp_path: Path) -> None:
    """Returns None when no Chrome binary is found."""
    with patch("mcp_gateway.launcher.CHROME_BETA_CANDIDATES", []):
        with patch("shutil.which", return_value=None):
            result = find_chrome_binary()
    assert result is None


def test_find_chrome_binary_respects_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CHROME_BINARY env var should be honoured by DedicatedBrowserLauncher._build_chrome_args."""
    fake_bin = tmp_path / "my-chrome"
    fake_bin.write_text("")
    monkeypatch.setenv("CHROME_BINARY", str(fake_bin))

    launcher = DedicatedBrowserLauncher(
        extension_dir=tmp_path,
        profile_dir=tmp_path / "profile",
    )
    args = launcher._build_chrome_args()
    assert args[0] == str(fake_bin)


# ---------------------------------------------------------------------------
# DedicatedBrowserLauncher._build_chrome_args
# ---------------------------------------------------------------------------


def test_build_chrome_args_contains_required_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chrome args must include --load-extension and --user-data-dir."""
    fake_bin = tmp_path / "chrome"
    fake_bin.write_text("")
    monkeypatch.setenv("CHROME_BINARY", str(fake_bin))

    launcher = DedicatedBrowserLauncher(
        extension_dir=tmp_path / "ext",
        profile_dir=tmp_path / "profile",
        cdp_port=19222,
    )
    # Ensure profile_dir exists so _build_chrome_args doesn't fail
    (tmp_path / "ext").mkdir(exist_ok=True)

    args = launcher._build_chrome_args()

    joined = " ".join(args)
    assert "--load-extension=" in joined
    assert "--user-data-dir=" in joined
    assert "--remote-debugging-port=19222" in joined
    assert "https://notebook.google.com/" in args


def test_build_chrome_args_raises_when_no_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RuntimeError raised when no Chrome binary is found and CHROME_BINARY is unset."""
    monkeypatch.delenv("CHROME_BINARY", raising=False)
    with patch("mcp_gateway.launcher.find_chrome_binary", return_value=None):
        launcher = DedicatedBrowserLauncher(
            extension_dir=tmp_path,
            profile_dir=tmp_path / "profile",
        )
        with pytest.raises(RuntimeError, match="Chrome"):
            launcher._build_chrome_args()


# ---------------------------------------------------------------------------
# _cdp_check_auth — unit tests with mocked urllib
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cdp_check_auth_returns_false_when_unreachable() -> None:
    """Returns False when CDP port is not reachable within timeout."""

    def raising_urlopen(*args: Any, **kwargs: Any) -> Any:
        raise OSError("connection refused")

    with patch("urllib.request.urlopen", side_effect=raising_urlopen):
        result = await _cdp_check_auth(cdp_port=29222, timeout_s=0.1)

    assert result is False


@pytest.mark.asyncio
async def test_cdp_check_auth_returns_true_when_notebook_tab_present() -> None:
    """Returns True when a notebook.google.com tab (not redirected) is found."""
    version_cm = MagicMock()
    version_cm.__enter__ = MagicMock(
        return_value=MagicMock(status=200, read=MagicMock(return_value=b"{}"))
    )
    version_cm.__exit__ = MagicMock(return_value=False)

    pages = [{"url": "https://notebook.google.com/notebooks"}]
    list_cm = MagicMock()
    list_cm.__enter__ = MagicMock(
        return_value=MagicMock(
            status=200,
            read=MagicMock(return_value=json.dumps(pages).encode()),
        )
    )
    list_cm.__exit__ = MagicMock(return_value=False)

    call_count = 0

    def mock_urlopen(url: Any, timeout: Any = None) -> Any:
        nonlocal call_count
        call_count += 1
        if "version" in str(url):
            return version_cm
        return list_cm

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        result = await _cdp_check_auth(cdp_port=39222, timeout_s=5.0)

    assert result is True


@pytest.mark.asyncio
async def test_cdp_check_auth_returns_false_when_redirected_to_google_accounts() -> None:
    """Returns False when the notebook tab is redirected to accounts.google.com."""
    version_cm = MagicMock()
    version_cm.__enter__ = MagicMock(
        return_value=MagicMock(status=200, read=MagicMock(return_value=b"{}"))
    )
    version_cm.__exit__ = MagicMock(return_value=False)

    pages = [{"url": "https://accounts.google.com/o/oauth2/auth?...notebook.google.com"}]
    list_cm = MagicMock()
    list_cm.__enter__ = MagicMock(
        return_value=MagicMock(
            status=200,
            read=MagicMock(return_value=json.dumps(pages).encode()),
        )
    )
    list_cm.__exit__ = MagicMock(return_value=False)

    def mock_urlopen(url: Any, timeout: Any = None) -> Any:
        if "version" in str(url):
            return version_cm
        return list_cm

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        result = await _cdp_check_auth(cdp_port=49222, timeout_s=5.0)

    assert result is False


# ---------------------------------------------------------------------------
# Phase 2: allowlist wizard — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allowlist_wizard_broker_unreachable(tmp_path: Path) -> None:
    """Wizard returns exit code 1 when broker is not running."""
    from mcp_gateway.allowlist_wizard import run_seed_wizard

    result = await run_seed_wizard(
        socket_path=str(tmp_path / "nonexistent.sock"),
        allowlist_path=tmp_path / "allowlist.json",
    )
    assert result == 1


@pytest.mark.asyncio
async def test_allowlist_wizard_saves_selection(tmp_path: Path) -> None:
    """Wizard writes selected notebook IDs to allowlist.json."""
    from mcp_gateway.allowlist_wizard import run_seed_wizard

    # Simulate a running broker that returns two notebooks
    IPC = ">I"
    notebooks_response = {
        "ok": True,
        "notebooks": [
            {"id": "nb-aaa", "title": "Project Alpha"},
            {"id": "nb-bbb", "title": "Project Beta"},
        ],
    }

    async def fake_handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        # Read one IPC frame
        raw_len = await reader.readexactly(4)
        (length,) = struct.unpack(IPC, raw_len)
        await reader.readexactly(length)
        # Reply with notebooks
        resp = json.dumps(notebooks_response).encode("utf-8")
        writer.write(struct.pack(IPC, len(resp)) + resp)
        await writer.drain()
        writer.close()

    sock_path = str(tmp_path / "broker.sock")
    server = await asyncio.start_unix_server(fake_handler, path=sock_path)

    allowlist_path = tmp_path / "allowlist.json"

    # Simulate user entering "1" to select the first notebook
    with patch("builtins.input", return_value="1"):
        result = await run_seed_wizard(
            socket_path=sock_path, allowlist_path=allowlist_path
        )

    server.close()
    await server.wait_closed()

    assert result == 0
    assert allowlist_path.exists()
    data = json.loads(allowlist_path.read_text())
    assert "nb-aaa" in data["notebooks"]
    assert "nb-bbb" not in data["notebooks"]


@pytest.mark.asyncio
async def test_allowlist_wizard_select_all(tmp_path: Path) -> None:
    """'all' selection allowlists every returned notebook."""
    from mcp_gateway.allowlist_wizard import run_seed_wizard

    IPC = ">I"
    notebooks_response = {
        "ok": True,
        "notebooks": [
            {"id": "nb-1", "title": "One"},
            {"id": "nb-2", "title": "Two"},
            {"id": "nb-3", "title": "Three"},
        ],
    }

    async def fake_handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        raw_len = await reader.readexactly(4)
        (length,) = struct.unpack(IPC, raw_len)
        await reader.readexactly(length)
        resp = json.dumps(notebooks_response).encode("utf-8")
        writer.write(struct.pack(IPC, len(resp)) + resp)
        await writer.drain()
        writer.close()

    sock_path = str(tmp_path / "broker2.sock")
    server = await asyncio.start_unix_server(fake_handler, path=sock_path)

    allowlist_path = tmp_path / "allowlist2.json"

    with patch("builtins.input", return_value="all"):
        result = await run_seed_wizard(
            socket_path=sock_path, allowlist_path=allowlist_path
        )

    server.close()
    await server.wait_closed()

    assert result == 0
    data = json.loads(allowlist_path.read_text())
    assert set(data["notebooks"]) == {"nb-1", "nb-2", "nb-3"}
