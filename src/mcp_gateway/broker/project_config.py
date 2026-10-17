"""Project-level notebook configuration manager.

Enforces:
- .notebook_mcp.json storage in project working directory.
- Preserves configured notebook selection across chats.
- Generates in-chat prompt for AI assistant to double-check with the user.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from typing import Any

logger = logging.getLogger("mcp_gateway.project_config")

PROJECT_CONFIG_FILENAME = ".notebook_mcp.json"


def get_project_notebook_config(project_dir: Path | str | None = None) -> dict[str, Any] | None:
    """Reads .notebook_mcp.json from the project directory if it exists and is valid."""
    try:
        target_dir = Path(project_dir) if project_dir else Path.cwd()
        config_file = target_dir / PROJECT_CONFIG_FILENAME
        if not config_file.is_file():
            return None
        data = json.loads(config_file.read_text(encoding="utf-8"))
        if isinstance(data, dict) and (data.get("notebook_id") or data.get("title")):
            return data
    except (json.JSONDecodeError, OSError, Exception) as exc:
        logger.debug("Failed to read project config: %s", exc)
    return None


def save_project_notebook_config(
    notebook_id: str,
    title: str = "",
    project_dir: Path | str | None = None,
) -> Path | None:
    """Saves notebook preference to .notebook_mcp.json in the project directory."""
    try:
        target_dir = Path(project_dir) if project_dir else Path.cwd()
        config_file = target_dir / PROJECT_CONFIG_FILENAME
        payload = {
            "notebook_id": notebook_id,
            "title": title,
            "updated_at": time.time(),
        }
        config_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return config_file
    except OSError as exc:
        logger.warning("Could not write project config .notebook_mcp.json: %s", exc)
        return None
