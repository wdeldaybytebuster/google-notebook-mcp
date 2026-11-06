from __future__ import annotations

from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def isolate_test_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates the current working directory to a unique tmp_path per test to prevent repo root pollution."""
    monkeypatch.chdir(tmp_path)
