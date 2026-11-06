"""Allowlist policy manager for the Gemini Notebook MCP bridge.

Supports both:
- Schema v2 (structured dict mapping notebook_id -> {"title": str, "mode": "READ_ONLY" | "INTERACTIVE"})
- Schema v1 legacy fallback (flat list of notebook_id strings, defaulting to "INTERACTIVE")
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Literal
from urllib.parse import urlparse

DEFAULT_ALLOWLIST_PATH = (
    Path.home() / ".config" / "notebooklm-mcp-bridge" / "allowlist.json"
)

NotebookMode = Literal["READ_ONLY", "INTERACTIVE"]

# Strict UUID regex (8-4-4-4-12 lowercase hex) for manual notebook IDs
UUID_V4_REGEX = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
)

ALLOWED_NOTEBOOK_HOSTS: frozenset[str] = frozenset({
    "notebook.google.com",
    "notebooklm.google.com",
})

# State-mutating tools blocked when a notebook is configured as READ_ONLY.
# Read operations (list_notebooks, select_notebook, get_notebook_metadata, list_sources, list_notes)
# and grounded queries (query_notebook) are PERMITTED in READ_ONLY mode.
MUTATING_TOOLS_BLOCKED_IN_READ_ONLY: frozenset[str] = frozenset({
    "add_source",
    "create_note",
    "delete_note",
})


def parse_and_validate_notebook_id(raw_input: str) -> str:
    """Extracts and validates a strict UUIDv4 notebook ID from a raw ID or NotebookLM URL.

    Raises ValueError if the input is malformed, contains path traversal characters,
    or does not match ^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$.
    """
    candidate = (raw_input or "").strip()
    if not candidate:
        raise ValueError("Invalid notebook ID: input cannot be empty.")

    lowered_raw = candidate.lower()
    if ".." in candidate or "%2e" in lowered_raw or "\\" in candidate:
        raise ValueError("Invalid notebook ID: path traversal characters are not permitted.")

    parsed_candidate = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    is_url_like = "://" in candidate or bool(parsed_candidate.netloc)

    if is_url_like:
        parsed = parsed_candidate
        if parsed.scheme not in ("https", "http") or parsed.hostname not in ALLOWED_NOTEBOOK_HOSTS:
            raise ValueError(
                f"Invalid notebook ID: URL host {parsed.hostname!r} is not notebook.google.com."
            )
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) == 2 and path_parts[0] == "notebook":
            candidate = path_parts[1]
        elif (
            len(path_parts) == 4
            and path_parts[0] == "u"
            and path_parts[1].isdigit()
            and path_parts[2] == "notebook"
        ):
            candidate = path_parts[3]
        else:
            raise ValueError(
                "Invalid notebook ID: URL must follow https://notebook.google.com/notebook/<uuid>."
            )

    normalized = candidate.strip().lower()
    if not UUID_V4_REGEX.match(normalized):
        raise ValueError(
            f"Invalid notebook ID {raw_input!r}: must be a valid 36-character UUID "
            "(xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)."
        )
    return normalized


@dataclass(frozen=True)
class NotebookPermission:
    """Granular access control entry for a single allowlisted notebook."""

    title: str = ""
    mode: NotebookMode = "INTERACTIVE"

    def to_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "mode": self.mode,
        }


def _normalize_mode(raw_mode: Any) -> NotebookMode:
    val = str(raw_mode or "INTERACTIVE").strip().upper()
    if val in ("READ_ONLY", "READONLY", "READ-ONLY"):
        return "READ_ONLY"
    return "INTERACTIVE"


@dataclass(frozen=True)
class AllowlistConfig:
    version: int
    provider_mode: str
    accounts: list[str]
    notebooks: list[str]
    notebook_permissions: dict[str, NotebookPermission] = field(default_factory=dict)
    source_path: Path | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        perms = dict(self.notebook_permissions)
        for nb_id in self.notebooks:
            if nb_id not in perms:
                perms[nb_id] = NotebookPermission(title="", mode="INTERACTIVE")
        merged_ids = list(self.notebooks)
        for nb_id in perms:
            if nb_id not in merged_ids:
                merged_ids.append(nb_id)
        object.__setattr__(self, "notebooks", merged_ids)
        object.__setattr__(self, "notebook_permissions", perms)

    @property
    def titles(self) -> dict[str, str]:
        """Returns a mapping of notebook_id -> title for non-empty titles."""
        return {
            nb_id: perm.title
            for nb_id, perm in self.notebook_permissions.items()
            if perm.title
        }

    def reload(self, path: Path | None = None) -> AllowlistConfig:
        """Reloads allowlist configuration from disk in-place on this instance."""
        target = path or self.source_path or DEFAULT_ALLOWLIST_PATH
        fresh = load_allowlist(target)
        object.__setattr__(self, "version", fresh.version)
        object.__setattr__(self, "provider_mode", fresh.provider_mode)
        object.__setattr__(self, "accounts", fresh.accounts)
        object.__setattr__(self, "notebooks", fresh.notebooks)
        object.__setattr__(self, "notebook_permissions", fresh.notebook_permissions)
        object.__setattr__(self, "source_path", target)
        return self


def load_allowlist(path: Path | None = None) -> AllowlistConfig:
    """Loads and validates the allowlist configuration (v1 flat list or v2 structured map).

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

    raw_notebooks = data.get("notebooks", [])
    notebook_ids: list[str] = []
    permissions: dict[str, NotebookPermission] = {}

    if isinstance(raw_notebooks, dict):
        for nb_id, meta in raw_notebooks.items():
            clean_id = str(nb_id).strip()
            if not clean_id:
                continue
            notebook_ids.append(clean_id)
            if isinstance(meta, dict):
                permissions[clean_id] = NotebookPermission(
                    title=str(meta.get("title", "")),
                    mode=_normalize_mode(meta.get("mode", "INTERACTIVE")),
                )
            else:
                permissions[clean_id] = NotebookPermission(title="", mode="INTERACTIVE")
    elif isinstance(raw_notebooks, list):
        for item in raw_notebooks:
            clean_id = str(item).strip()
            if not clean_id:
                continue
            notebook_ids.append(clean_id)
            permissions[clean_id] = NotebookPermission(title="", mode="INTERACTIVE")

    return AllowlistConfig(
        version=int(data.get("version", 2 if isinstance(raw_notebooks, dict) else 1)),
        provider_mode=str(data.get("provider_mode", "browser")),
        accounts=[str(a) for a in data.get("accounts", [])],
        notebooks=notebook_ids,
        notebook_permissions=permissions,
        source_path=target_path,
    )


def save_allowlist(config: AllowlistConfig, path: Path | None = None) -> None:
    """Atomically writes allowlist configuration to disk with 0o600 permissions."""
    target_path = path or config.source_path or DEFAULT_ALLOWLIST_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)

    has_v2_features = config.version >= 2 or any(
        perm.mode != "INTERACTIVE" or bool(perm.title)
        for perm in config.notebook_permissions.values()
    )

    if has_v2_features:
        notebooks_payload: Any = {
            nb_id: config.notebook_permissions.get(
                nb_id, NotebookPermission(title="", mode="INTERACTIVE")
            ).to_dict()
            for nb_id in config.notebooks
        }
        out_version = max(2, config.version)
    else:
        notebooks_payload = list(config.notebooks)
        out_version = config.version

    payload: dict[str, Any] = {
        "version": out_version,
        "provider_mode": config.provider_mode,
        "accounts": list(config.accounts),
        "notebooks": notebooks_payload,
    }
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

    try:
        os.chmod(temp_name, 0o600)
    except OSError:
        pass
    os.replace(temp_name, target_path)


def is_notebook_allowed(config: AllowlistConfig, notebook_id: str) -> bool:
    """Checks whether the given notebook ID is explicitly allowlisted."""
    return notebook_id in config.notebook_permissions or notebook_id in config.notebooks


def get_notebook_mode(config: AllowlistConfig, notebook_id: str) -> NotebookMode:
    """Returns the configured permission mode ('READ_ONLY' or 'INTERACTIVE') for a notebook."""
    perm = config.notebook_permissions.get(notebook_id)
    if perm is None:
        return "INTERACTIVE"
    return perm.mode


def is_tool_permitted_for_notebook(
    config: AllowlistConfig,
    notebook_id: str,
    tool_name: str,
) -> bool:
    """Checks whether `tool_name` is permitted on `notebook_id` under its granular mode.

    READ_ONLY allows read operations and `query_notebook`, while rejecting mutating
    operations (`add_source`, `create_note`, `delete_note`).
    """
    if not is_notebook_allowed(config, notebook_id):
        return False
    mode = get_notebook_mode(config, notebook_id)
    if mode == "READ_ONLY" and tool_name in MUTATING_TOOLS_BLOCKED_IN_READ_ONLY:
        return False
    return True


def set_notebook_permission(
    config: AllowlistConfig,
    notebook_id: str,
    title: str = "",
    mode: NotebookMode = "INTERACTIVE",
) -> AllowlistConfig:
    """Returns a new AllowlistConfig with the notebook's title and mode set (v2)."""
    perms = dict(config.notebook_permissions)
    existing = perms.get(notebook_id)
    resolved_title = title if title else (existing.title if existing else "")
    perms[notebook_id] = NotebookPermission(
        title=resolved_title,
        mode=_normalize_mode(mode),
    )
    ids = list(config.notebooks)
    if notebook_id not in ids:
        ids.append(notebook_id)
    return AllowlistConfig(
        version=2,
        provider_mode=config.provider_mode,
        accounts=list(config.accounts),
        notebooks=ids,
        notebook_permissions=perms,
        source_path=config.source_path,
    )


def add_notebook(
    config: AllowlistConfig,
    notebook_id: str,
    title: str = "",
    mode: NotebookMode = "INTERACTIVE",
) -> AllowlistConfig:
    """Returns a new AllowlistConfig with the notebook ID added."""
    if notebook_id in config.notebooks and not title and mode == "INTERACTIVE":
        return config
    perms = dict(config.notebook_permissions)
    perms[notebook_id] = NotebookPermission(title=title, mode=_normalize_mode(mode))
    ids = [*config.notebooks, notebook_id] if notebook_id not in config.notebooks else list(config.notebooks)
    new_version = 2 if (title or mode != "INTERACTIVE" or config.version >= 2) else config.version
    return AllowlistConfig(
        version=new_version,
        provider_mode=config.provider_mode,
        accounts=list(config.accounts),
        notebooks=ids,
        notebook_permissions=perms,
        source_path=config.source_path,
    )


def remove_notebook(config: AllowlistConfig, notebook_id: str) -> AllowlistConfig:
    """Returns a new AllowlistConfig with the notebook ID removed."""
    if notebook_id not in config.notebooks and notebook_id not in config.notebook_permissions:
        return config
    perms = {k: v for k, v in config.notebook_permissions.items() if k != notebook_id}
    return AllowlistConfig(
        version=config.version,
        provider_mode=config.provider_mode,
        accounts=list(config.accounts),
        notebooks=[n for n in config.notebooks if n != notebook_id],
        notebook_permissions=perms,
        source_path=config.source_path,
    )
