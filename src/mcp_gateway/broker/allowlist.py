"""Allowlist policy manager for the Gemini Notebook MCP bridge."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_ALLOWLIST_PATH = (
    Path.home() / ".config" / "notebooklm-mcp-bridge" / "allowlist.json"
)


@dataclass(frozen=True)
class AllowlistConfig:
    version: int
    provider_mode: str
    accounts: list[str]
    notebooks: list[str]


def load_allowlist(path: Path | None = None) -> AllowlistConfig:
    """Loads and validates the allowlist configuration.

    Raises FileNotFoundError if the allowlist file does not exist.
    """
    target_path = path or DEFAULT_ALLOWLIST_PATH
    if not target_path.exists():
        raise FileNotFoundError(
            f"Allowlist configuration file not found at {target_path}. "
            "Please initialize it before accessing notebook resources."
        )

    content = target_path.read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(content)

    return AllowlistConfig(
        version=int(data.get("version", 1)),
        provider_mode=str(data.get("provider_mode", "browser")),
        accounts=[str(a) for a in data.get("accounts", [])],
        notebooks=[str(n) for n in data.get("notebooks", [])],
    )


def save_allowlist(config: AllowlistConfig, path: Path | None = None) -> None:
    """Atomically writes allowlist configuration to disk."""
    target_path = path or DEFAULT_ALLOWLIST_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)

    payload = asdict(config)
    serialized = json.dumps(payload, indent=2)

    with tempfile.NamedTemporaryFile(
        "w",
        dir=target_path.parent,
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(serialized)
        tmp.flush()
        temp_name = tmp.name

    os.replace(temp_name, target_path)


def is_notebook_allowed(config: AllowlistConfig, notebook_id: str) -> bool:
    """Checks whether the given notebook ID is explicitly allowlisted."""
    return notebook_id in config.notebooks


def add_notebook(config: AllowlistConfig, notebook_id: str) -> AllowlistConfig:
    """Returns a new AllowlistConfig with the notebook ID added."""
    if notebook_id in config.notebooks:
        return config
    return AllowlistConfig(
        version=config.version,
        provider_mode=config.provider_mode,
        accounts=list(config.accounts),
        notebooks=[*config.notebooks, notebook_id],
    )


def remove_notebook(config: AllowlistConfig, notebook_id: str) -> AllowlistConfig:
    """Returns a new AllowlistConfig with the notebook ID removed."""
    if notebook_id not in config.notebooks:
        return config
    return AllowlistConfig(
        version=config.version,
        provider_mode=config.provider_mode,
        accounts=list(config.accounts),
        notebooks=[n for n in config.notebooks if n != notebook_id],
    )
