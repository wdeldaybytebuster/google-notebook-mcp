from __future__ import annotations

from pathlib import Path
import sys
import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Configures short basetemp on Darwin to comply with 104-byte AF_UNIX socket path limits."""
    if sys.platform == "darwin" and getattr(config.option, "basetemp", None) is None:
        short_temp = Path("/tmp/pytest_mcp")
        short_temp.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(short_temp)


@pytest.fixture(autouse=True)
def isolate_test_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates the current working directory to a unique tmp_path per test to prevent repo root pollution."""
    monkeypatch.chdir(tmp_path)
