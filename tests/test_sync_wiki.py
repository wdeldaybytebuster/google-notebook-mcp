"""Tests for scripts/sync_wiki_to_github.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from scripts.sync_wiki_to_github import sync_wiki


def test_sync_wiki_missing_dir(tmp_path: Path) -> None:
    assert sync_wiki(repo_root=tmp_path) == 1


def test_sync_wiki_dry_run(tmp_path: Path) -> None:
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "Home.md").write_text("# Home", encoding="utf-8")

    def mock_run_call(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
        if cmd[:2] == ["git", "clone"]:
            target_dir = Path(cmd[3])
            target_dir.mkdir(parents=True, exist_ok=True)
            return MagicMock(returncode=0)
        elif cmd[:3] == ["git", "status", "--porcelain"]:
            return MagicMock(returncode=0, stdout=" M Home.md\n")
        return MagicMock(returncode=0)

    with patch("subprocess.run", side_effect=mock_run_call):
        ret = sync_wiki(repo_root=tmp_path, dry_run=True)
        assert ret == 0


def test_sync_wiki_no_changes(tmp_path: Path) -> None:
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "Home.md").write_text("# Home", encoding="utf-8")

    def mock_run_call(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
        if cmd[:2] == ["git", "clone"]:
            target_dir = Path(cmd[3])
            target_dir.mkdir(parents=True, exist_ok=True)
            return MagicMock(returncode=0)
        elif cmd[:3] == ["git", "status", "--porcelain"]:
            return MagicMock(returncode=0, stdout="")
        return MagicMock(returncode=0)

    with patch("subprocess.run", side_effect=mock_run_call):
        ret = sync_wiki(repo_root=tmp_path, dry_run=False)
        assert ret == 0
