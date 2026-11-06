# Security Bugfixes, WebUI Allowlist & Granular Permissions Implementation Plan (v2 — Revised)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remediate all 8 audited architectural/security bugs and implement the Extension Popup Setup Mode, interactive `NotebookAllowlistCard` WebUI checklist with strict UUIDv4 manual fallback sanitization, dedicated `query_cache` SQLite persistence, and granular `READ_ONLY` (allows read + `query_notebook`, blocks mutating tools) vs `INTERACTIVE` per-notebook policy enforcement with live mutex-guarded reload in `BrokerDaemon`.

**Architecture:**
1. **Granular RBAC Allowlist Schema v2 (`allowlist.py`)**: Upgrade `allowlist.json` from a flat ID array (v1) to a structured v2 permission map (`{"<notebook_id>": {"title": "...", "mode": "READ_ONLY" | "INTERACTIVE"}}`) with full v1 backward compatibility and an in-place `.reload()` method on `AllowlistConfig`. Under `READ_ONLY` mode, read and grounded-query tools (`list_notebooks`, `select_notebook`, `get_notebook_metadata`, `list_sources`, `list_notes`, and `query_notebook`) are **permitted**, whereas state-mutating tools (`add_source`, `create_note`, `delete_note`) are **blocked** with `PERMISSION_DENIED`.
2. **Thread-Safe Live Reload & Broker Remediation (`broker.py`)**: `BrokerDaemon` exposes `self.allowlist_config` and executes `self.allowlist_config.reload()` inside `async with self._session_mutex:` whenever `update_allowlist` is invoked over Native Messaging, ensuring active sessions immediately enforce updated permissions without a daemon restart. It also bypasses `SessionLock` for `companion_forward` / `discover_notebooks` / `get_allowlist` / `update_allowlist` and removes the unscrubbed `/tmp/raw_query_stream_body.txt` dump.
3. **Dedicated SQLite `query_cache` Table (`schema.sql` v3 & `journal.py`)**: Keep `mutation_journal` strictly for state-machine tracking (`prepared -> sent -> confirmed/rejected/unknown`) without polluting it with large text payloads. Introduce a dedicated `query_cache` table (`cache_key`, `notebook_id`, `query_text`, `response_payload`, `created_at`) to store and replay confirmed `query_notebook` answers and citations.
4. **Popup Setup Mode, `NotebookAllowlistCard` WebUI & Strict UUIDv4 Sanitization (`popup.html`, `popup.js`, `popup.css`, `service_worker.js`)**: Render a state-driven Setup Mode banner (`python3 setup_native_host.py --extension-id <ID>`) on disconnect, an interactive `NotebookAllowlistCard` checklist with `Read Only` / `Interactive` toggles, and a manual URL/ID fallback input validated against the strict UUIDv4 regex `^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$` (or extracted from valid `https://notebook.google.com/notebook/<uuid>` URLs) in both `popup.js` and `allowlist.py`.

**Tech Stack:** Python 3.11+ (`asyncio`, `sqlite3`, `pydantic`, `mcp`), Chrome Extension Manifest V3 (Vanilla ES2022 JS, CSS Custom Properties, `chrome.runtime.connectNative`, `MessageChannel`), `pytest` / `pytest-asyncio`, `ruff`, `mypy --strict`.

---

## File Structure & Responsibility Map

| File Path | Action | Responsibility |
|---|---|---|
| `src/mcp_gateway/broker/allowlist.py` | Modify | v2 `allowlist.json` schema (`NotebookPermission`, `READ_ONLY`/`INTERACTIVE` modes), `AllowlistConfig.reload()`, strict UUIDv4 parser `parse_and_validate_notebook_id()`, `0o600` atomic save, RBAC tool permission checks (`READ_ONLY` allows `query_notebook`, blocks `add_source`/`create_note`/`delete_note`). |
| `config/allowlist.json` | Modify | Default v2 template documenting the structured `notebooks` map and `READ_ONLY`/`INTERACTIVE` modes. |
| `src/mcp_gateway/broker/broker.py` | Modify | Guard `self.allowlist_config.reload()` with `self._session_mutex`; enforce `PERMISSION_DENIED` on mutating tools (`add_source`, `create_note`, `delete_note`) when notebook is `READ_ONLY` while allowing `query_notebook`; bypass `SessionLock` for `companion_forward`/`discover_notebooks`/`get_allowlist`/`update_allowlist`; remove `/tmp/raw_query_stream_body.txt` leak; wire dedicated `query_cache` for `query_notebook`. |
| `src/mcp_gateway/storage/schema.sql` | Modify | Upgrade `PRAGMA user_version=3` and create dedicated `query_cache` table (`cache_key`, `notebook_id`, `query_text`, `response_payload`, `created_at`) leaving `mutation_journal` clean. |
| `src/mcp_gateway/storage/journal.py` | Modify | Add v2->v3 SQLite migration creating `query_cache`, plus `put_query_cache()` and `get_query_cache()` methods on `MutationJournal`. |
| `src/mcp_gateway/allowlist_wizard.py` | Modify | Use unfiltered `discover_notebooks` broker action and support selecting `READ_ONLY` vs `INTERACTIVE` mode. |
| `setup_native_host.py` | Create | Root CLI entry script supporting `python3 setup_native_host.py --extension-id <ID>` for zero-friction Setup Mode copy-paste. |
| `src/extension/service_worker.js` | Modify | Route `scotty_chunk`/`scotty_upload` to `page-main.js` (enforcing P-03); handle `discover_notebooks`, `get_allowlist`, and `update_allowlist` messages between `popup.js`, `page-main.js`, and `nativePort`. |
| `src/extension/popup.html` | Modify | Add Setup Mode banner (`#setup-mode-banner`), interactive `NotebookAllowlistCard` list, refresh button, and manual Notebook ID/URL fallback form with validation error feedback. |
| `src/extension/popup.css` | Modify | Style Setup Mode drawer, copyable command box, `READ_ONLY`/`INTERACTIVE` mode toggle pills, checkbox rows, and manual fallback form using `:root` design tokens. |
| `src/extension/popup.js` | Modify | Implement state-driven Setup Mode, `wXbhsf` + broker checklist rendering, `Read Only`/`Interactive` toggles, strict UUIDv4 URL/ID validator (`^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$`), and Native Messaging persistence. |
| `src/mcp_gateway/transport/ipc.py` | Modify | Complete `WindowsNamedPipeServer._listen_loop` stream reader/writer dispatch to `self.client_connected_cb`. |
| `tests/test_broker.py` | Modify | Unit/integration tests for v2 allowlist modes, `READ_ONLY` permitting `query_notebook` while blocking `add_source`/`create_note`/`delete_note`, `self.allowlist_config.reload()` under `self._session_mutex`, UUIDv4 sanitization, and `companion_forward` routing. |
| `tests/test_journal.py` | Modify | Unit tests for dedicated `query_cache` table persistence and `query_notebook` idempotent replay without polluting `mutation_journal`. |
| `tests/test_popup_webui.py` | Create | Structural and contract tests verifying `setup_native_host.py`, `popup.html`, `popup.js` UUIDv4 regex sanitization, and `service_worker.js` WebUI allowlist flows. |

---

### Task 1: Upgrade `allowlist.json` Schema to v2 (`READ_ONLY` vs `INTERACTIVE` RBAC, `AllowlistConfig.reload()`, and Strict UUIDv4 Sanitization)

**Files:**
- Modify: `src/mcp_gateway/broker/allowlist.py:1-95`
- Modify: `config/allowlist.json:1-12`
- Test: `tests/test_broker.py:67-93`

- [x] **Step 1: Write the failing tests for v2 structured allowlist, `READ_ONLY` RBAC (allowing `query_notebook`, blocking mutations), `.reload()`, and UUIDv4 sanitization in `tests/test_broker.py`**

Add the following test functions to `tests/test_broker.py` right after `test_allowlist_missing_raises`:

```python
def test_allowlist_v2_structured_modes_reload_and_v1_migration(tmp_path: Path) -> None:
    from mcp_gateway.broker.allowlist import (
        NotebookPermission,
        get_notebook_mode,
        is_tool_permitted_for_notebook,
        parse_and_validate_notebook_id,
        set_notebook_permission,
    )

    # 1. Load legacy v1 flat list -> migrates to INTERACTIVE permissions
    v1_path = tmp_path / "v1_allowlist.json"
    v1_path.write_text(
        json.dumps({
            "version": 1,
            "provider_mode": "browser",
            "accounts": ["dev@example.com"],
            "notebooks": ["nb-legacy-1"],
        }),
        encoding="utf-8",
    )
    cfg_v1 = load_allowlist(v1_path)
    assert is_notebook_allowed(cfg_v1, "nb-legacy-1") is True
    assert get_notebook_mode(cfg_v1, "nb-legacy-1") == "INTERACTIVE"
    assert is_tool_permitted_for_notebook(cfg_v1, "nb-legacy-1", "query_notebook") is True
    assert is_tool_permitted_for_notebook(cfg_v1, "nb-legacy-1", "add_source") is True

    # 2. Set READ_ONLY permission and save as v2 structured map
    cfg_v2 = set_notebook_permission(
        cfg_v1,
        "nb-readonly-2",
        title="Project Architecture Docs",
        mode="READ_ONLY",
    )
    v2_path = tmp_path / "v2_allowlist.json"
    save_allowlist(cfg_v2, v2_path)

    raw_saved = json.loads(v2_path.read_text(encoding="utf-8"))
    assert raw_saved["version"] == 2
    assert raw_saved["notebooks"]["nb-readonly-2"] == {
        "title": "Project Architecture Docs",
        "mode": "READ_ONLY",
    }

    reloaded = load_allowlist(v2_path)
    assert is_notebook_allowed(reloaded, "nb-readonly-2") is True
    assert get_notebook_mode(reloaded, "nb-readonly-2") == "READ_ONLY"
    assert reloaded.notebook_permissions["nb-readonly-2"] == NotebookPermission(
        title="Project Architecture Docs",
        mode="READ_ONLY",
    )

    # 3. Granular RBAC checks for READ_ONLY vs INTERACTIVE:
    # READ_ONLY MUST allow read + query_notebook, and MUST block mutating tools
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "list_notebooks") is True
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "get_notebook_metadata") is True
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "list_sources") is True
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "list_notes") is True
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "query_notebook") is True
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "add_source") is False
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "create_note") is False
    assert is_tool_permitted_for_notebook(reloaded, "nb-readonly-2", "delete_note") is False

    # 4. In-place AllowlistConfig.reload() updates singleton state from disk
    v2_path.write_text(
        json.dumps({
            "version": 2,
            "provider_mode": "browser",
            "accounts": ["dev@example.com"],
            "notebooks": {
                "123e4567-e89b-12d3-a456-426614174000": {
                    "title": "Hot Reloaded NB",
                    "mode": "READ_ONLY",
                }
            },
        }),
        encoding="utf-8",
    )
    reloaded.reload()
    assert is_notebook_allowed(reloaded, "123e4567-e89b-12d3-a456-426614174000") is True
    assert get_notebook_mode(reloaded, "123e4567-e89b-12d3-a456-426614174000") == "READ_ONLY"

    # 5. Strict UUIDv4 validation and URL extraction for manual fallback input
    valid_uuid = "123e4567-e89b-12d3-a456-426614174000"
    assert parse_and_validate_notebook_id(valid_uuid) == valid_uuid
    assert (
        parse_and_validate_notebook_id(
            f"https://notebook.google.com/notebook/{valid_uuid}?authuser=0"
        )
        == valid_uuid
    )
    assert (
        parse_and_validate_notebook_id(
            f"https://notebooklm.google.com/notebook/{valid_uuid}/"
        )
        == valid_uuid
    )
    with pytest.raises(ValueError, match="Invalid notebook ID"):
        parse_and_validate_notebook_id("../../etc/passwd")
    with pytest.raises(ValueError, match="Invalid notebook ID"):
        parse_and_validate_notebook_id("https://evil.example.com/notebook/123e4567-e89b-12d3-a456-426614174000")
    with pytest.raises(ValueError, match="Invalid notebook ID"):
        parse_and_validate_notebook_id("not-a-uuid")
```

- [x] **Step 2: Run pytest to verify the new test fails**

Run:
```bash
taskset -c 0-5 env UV_THREADPOOL_SIZE=3 pytest tests/test_broker.py -k "test_allowlist_v2_structured_modes_reload_and_v1_migration" -v
```
Expected: `FAIL` with `ImportError: cannot import name 'NotebookPermission' from 'mcp_gateway.broker.allowlist'`

- [x] **Step 3: Implement v2 structured schema, `READ_ONLY` RBAC, `.reload()`, and `parse_and_validate_notebook_id` in `src/mcp_gateway/broker/allowlist.py` and `config/allowlist.json`**

Replace `src/mcp_gateway/broker/allowlist.py` with:

```python
"""Allowlist policy manager for the Gemini Notebook MCP bridge.

Supports both:
- Schema v2 (structured dict mapping notebook_id -> {"title": str, "mode": "READ_ONLY" | "INTERACTIVE"})
- Schema v1 legacy fallback (flat list of notebook_id strings, defaulting to "INTERACTIVE")
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from dataclasses import dataclass, field
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
# Read operations (list_notebooks, get_notebook_metadata, list_sources, list_notes)
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

    if "://" in candidate or candidate.startswith("notebook.google.com") or candidate.startswith("notebooklm.google.com"):
        url_str = candidate if "://" in candidate else f"https://{candidate}"
        parsed = urlparse(url_str)
        if parsed.scheme not in ("https", "http") or parsed.hostname not in ALLOWED_NOTEBOOK_HOSTS:
            raise ValueError(
                f"Invalid notebook ID: URL host {parsed.hostname!r} is not notebook.google.com."
            )
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) >= 2 and path_parts[0] == "notebook":
            candidate = path_parts[1]
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
```

Also update `config/allowlist.json` to document the v2 structured map:
```json
{
  "_comment": {
    "version": "Schema version (2 = structured notebook permissions map; 1 = legacy flat array).",
    "provider_mode": "Execution mode for the browser companion. 'browser' = Manifest V3 extension (default).",
    "accounts": "List of Google account email addresses permitted to access notebooks via MCP. Empty = all authenticated accounts.",
    "notebooks": "Map of notebook IDs to {'title': str, 'mode': 'READ_ONLY' | 'INTERACTIVE'}. Empty = no notebooks allowed (deny-all default)."
  },
  "version": 2,
  "provider_mode": "browser",
  "accounts": [],
  "notebooks": {}
}
```

- [x] **Step 4: Run pytest on `tests/test_broker.py` to verify all allowlist tests pass**

Run:
```bash
taskset -c 0-5 env UV_THREADPOOL_SIZE=3 pytest tests/test_broker.py -v
```
Expected: `PASS`

- [x] **Step 5: Commit Task 1**

```bash
git add src/mcp_gateway/broker/allowlist.py config/allowlist.json tests/test_broker.py
git commit -m "feat(allowlist): upgrade allowlist.json to v2 with READ_ONLY RBAC, live reload(), and UUIDv4 validation"
```

---

### Task 2: Enforce `READ_ONLY` Policy (Permitting `query_notebook`, Blocking Mutations), Live Mutex-Guarded Reload & `companion_forward` Fix in `BrokerDaemon`

**Files:**
- Modify: `src/mcp_gateway/broker/broker.py:35-690, 906-1083`
- Modify: `src/mcp_gateway/allowlist_wizard.py:100-215`
- Test: `tests/test_broker.py`

- [x] **Step 1: Write failing tests in `tests/test_broker.py` for `READ_ONLY` permitting `query_notebook` while blocking mutating tools, live `self.allowlist_config.reload()` under `self._session_mutex`, and `companion_forward` bypass**

Add the following tests to the bottom of `tests/test_broker.py`:

```python
@pytest.mark.asyncio
async def test_broker_readonly_permits_query_notebook_and_blocks_mutations(tmp_path: Path) -> None:
    from mcp_gateway.schemas.error import PERMISSION_DENIED

    allowlist_p = tmp_path / "allowlist.json"
    allowlist_p.write_text(
        json.dumps({
            "version": 2,
            "provider_mode": "browser",
            "accounts": ["developer@gmail.com"],
            "notebooks": {
                "nb-ro": {"title": "Read Only Docs", "mode": "READ_ONLY"},
                "nb-rw": {"title": "Interactive Docs", "mode": "INTERACTIVE"},
            },
        }),
        encoding="utf-8",
    )
    daemon = BrokerDaemon(
        BrokerConfig(
            socket_path=str(tmp_path / "ro.sock"),
            allowlist_path=allowlist_p,
            journal_db_path=tmp_path / "journal.db",
        )
    )

    # Lock session to nb-ro
    sel_res = await daemon.dispatch({"action": "select_notebook", "notebook_id": "nb-ro"})
    assert sel_res["ok"] is True
    assert sel_res.get("mode") == "READ_ONLY"

    # 1. query_notebook MUST BE PERMITTED on READ_ONLY notebooks (reaches companion -> AUTH_REQUIRED in unit test)
    q_res = await daemon.dispatch({
        "action": "query_notebook",
        "notebook_id": "nb-ro",
        "question": "What is the architecture?",
        "request_key": "req-ro-allowed-1",
    })
    assert q_res["ok"] is False
    assert q_res["error"]["code"] == AUTH_REQUIRED  # Permitted past RBAC policy!

    # 2. Mutating tools (add_source, create_note, delete_note) MUST BE BLOCKED with PERMISSION_DENIED
    add_res = await daemon.dispatch({
        "action": "add_source",
        "notebook_id": "nb-ro",
        "idempotency_key": "idem-ro-1",
        "source": {"type": "text", "title": "Note", "content": "Body"},
    })
    assert add_res["ok"] is False
    assert add_res["error"]["code"] == PERMISSION_DENIED
    assert "READ_ONLY" in add_res["error"]["message"]

    note_res = await daemon.dispatch({
        "action": "create_note",
        "notebook_id": "nb-ro",
        "title": "Note",
        "content": "Body",
        "idempotency_key": "idem-ro-note",
    })
    assert note_res["ok"] is False
    assert note_res["error"]["code"] == PERMISSION_DENIED

    del_res = await daemon.dispatch({
        "action": "delete_note",
        "notebook_id": "nb-ro",
        "note_id": "note-1",
        "idempotency_key": "idem-ro-del",
    })
    assert del_res["ok"] is False
    assert del_res["error"]["code"] == PERMISSION_DENIED


@pytest.mark.asyncio
async def test_broker_live_allowlist_reload_with_mutex_and_uuid_validation(
    broker: BrokerDaemon,
) -> None:
    from mcp_gateway.schemas.error import INVALID_ARGUMENT, PERMISSION_DENIED

    valid_uuid = "123e4567-e89b-12d3-a456-426614174000"

    # 1. get_allowlist works in DISCOVERY_ONLY without SESSION_UNLOCKED
    get_res = await broker.dispatch({"action": "get_allowlist"})
    assert get_res["ok"] is True
    assert "nb-allowed-1" in get_res["notebooks"]

    # 2. update_allowlist rejects path traversal / malformed manual IDs when validate_uuids=True
    bad_res = await broker.dispatch({
        "action": "update_allowlist",
        "validate_uuids": True,
        "notebooks": {
            "../../etc/passwd": {"title": "Traversal", "mode": "READ_ONLY"},
        },
    })
    assert bad_res["ok"] is False
    assert bad_res["error"]["code"] == INVALID_ARGUMENT

    # 3. update_allowlist accepts valid UUIDs, saves atomically, and calls self.allowlist_config.reload() under _session_mutex
    upd_res = await broker.dispatch({
        "action": "update_allowlist",
        "validate_uuids": True,
        "notebooks": {
            valid_uuid: {"title": "Live Reloaded NB", "mode": "READ_ONLY"},
        },
    })
    assert upd_res["ok"] is True
    assert upd_res["notebooks"][valid_uuid]["mode"] == "READ_ONLY"
    assert is_notebook_allowed(broker.allowlist_config, valid_uuid) is True

    # 4. Selecting the newly added notebook succeeds immediately in the live session and enforces READ_ONLY
    sel_res = await broker.dispatch({"action": "select_notebook", "notebook_id": valid_uuid})
    assert sel_res["ok"] is True
    assert sel_res["mode"] == "READ_ONLY"

    mut_res = await broker.dispatch({
        "action": "add_source",
        "notebook_id": valid_uuid,
        "idempotency_key": "idem-live-1",
        "source": {"type": "text", "title": "T", "content": "C"},
    })
    assert mut_res["ok"] is False
    assert mut_res["error"]["code"] == PERMISSION_DENIED

    # 5. companion_forward is not blocked by SessionLock in DISCOVERY_ONLY or LOCKED
    fwd_res = await broker.dispatch({
        "action": "companion_forward",
        "companion_command": "batchexecute",
        "payload": {"rpcId": "wXbhsf", "paramsJson": "[]"},
    })
    assert fwd_res["ok"] is False
    assert fwd_res["error"]["code"] == AUTH_REQUIRED
```

- [x] **Step 2: Run pytest to verify the new tests fail**

Run:
```bash
taskset -c 0-5 env UV_THREADPOOL_SIZE=3 pytest tests/test_broker.py -k "test_broker_readonly_permits_query_notebook_and_blocks_mutations or test_broker_live_allowlist_reload_with_mutex_and_uuid_validation" -v
```
Expected: `FAIL`

- [x] **Step 3: Update `src/mcp_gateway/broker/broker.py` and `src/mcp_gateway/allowlist_wizard.py`**

In `src/mcp_gateway/broker/broker.py`:
1. Import `NotebookPermission`, `get_notebook_mode`, `is_tool_permitted_for_notebook`, `parse_and_validate_notebook_id`, `save_allowlist` from `mcp_gateway.broker.allowlist`, and import `PERMISSION_DENIED` from `mcp_gateway.schemas.error`.
2. Expose `self.allowlist_config: AllowlistConfig` on `BrokerDaemon` (aliased with `self.allowlist` so both `self.allowlist` and `self.allowlist_config` reference the same `AllowlistConfig` instance), and update `reload_allowlist(self)` to call `self.allowlist_config.reload(self.config.allowlist_path)`.
3. In `BrokerDaemon.dispatch()`:
   - Handle `"companion_forward"`, `"get_allowlist"`, `"update_allowlist"`, and `"discover_notebooks"` **before** `self.session_lock.validate_and_prepare(action, command)`.
   - Inside `_handle_update_allowlist(self, command: dict[str, Any])`:
     - Acquire `async with self._session_mutex:`
     - Validate notebook IDs using `parse_and_validate_notebook_id(nb_id)` when `command.get("validate_uuids", False)` or when `manual_entry` is provided (returning `make_error(INVALID_ARGUMENT, str(exc))` on malformed IDs).
     - Write the updated `AllowlistConfig` via `save_allowlist(new_cfg, self.config.allowlist_path)`.
     - Call `self.allowlist_config.reload(self.config.allowlist_path)` while holding `self._session_mutex` so active sessions immediately see the updated permissions!
   - After `if not is_notebook_allowed(self.allowlist, str(notebook_id)):`, check `if not is_tool_permitted_for_notebook(self.allowlist, str(notebook_id), action):` and return:
     ```python
     err_dict = make_error(
         PERMISSION_DENIED,
         f"Notebook '{notebook_id}' is configured as READ_ONLY in allowlist.json. "
         f"Mutating tool '{action}' requires INTERACTIVE mode.",
         retryable=False,
         mcp_correlation_id=correlation_id,
     ).to_dict()
     return self._finalize_dispatch(err_dict, correlation_id)
     ```
4. In `BrokerDaemon._handle_query_notebook()`, remove lines 1008–1012 (`with open("/tmp/raw_query_stream_body.txt"...)`) and remove `preview={full_text[:200]!r}` from the `stderr` log on line 1054.
5. In `src/mcp_gateway/allowlist_wizard.py`, change `{"action": "list_notebooks"}` to `{"action": "discover_notebooks"}` so initial seeding discovers all notebooks even when `allowlist.json` is empty.

- [x] **Step 4: Run pytest to verify the new broker tests pass**

Run:
```bash
taskset -c 0-5 env UV_THREADPOOL_SIZE=3 pytest tests/test_broker.py -v
```
Expected: `PASS`

- [x] **Step 5: Commit Task 2**

```bash
git add src/mcp_gateway/broker/broker.py src/mcp_gateway/allowlist_wizard.py tests/test_broker.py
git commit -m "fix(broker): enforce READ_ONLY RBAC, mutex-guarded allowlist_config.reload(), and companion_forward bypass"
```

---

### Task 3: Create Dedicated `query_cache` Table in `schema.sql` v3 for `query_notebook` Replay (Leaving `mutation_journal` Strictly for State Tracking)

**Files:**
- Modify: `src/mcp_gateway/storage/schema.sql:1-31`
- Modify: `src/mcp_gateway/storage/journal.py:52-155, 309-342`
- Modify: `src/mcp_gateway/broker/broker.py:920-930, 1067-1083`
- Test: `tests/test_journal.py`

- [x] **Step 1: Write the failing test in `tests/test_journal.py` for the dedicated `query_cache` table**

Add to the bottom of `tests/test_journal.py`:

```python
def test_dedicated_query_cache_stores_and_replays_without_polluting_mutation_journal(
    journal: MutationJournal,
) -> None:
    import json

    payload_str = json.dumps({
        "answer": "DBSC binds cookies to hardware TPM keys.",
        "citations": [
            {
                "source_id": "src-1",
                "text_snippet": "hardware TPM keys",
                "start_char": 20,
                "end_char": 37,
            }
        ],
    })

    journal.put_query_cache(
        cache_key="req-query-cache-1",
        notebook_id="nb-001",
        query_text="What is DBSC?",
        response_payload=payload_str,
    )

    cached = journal.get_query_cache("req-query-cache-1")
    assert cached is not None
    assert cached["cache_key"] == "req-query-cache-1"
    assert cached["notebook_id"] == "nb-001"
    assert cached["query_text"] == "What is DBSC?"
    assert json.loads(cached["response_payload"])["answer"] == "DBSC binds cookies to hardware TPM keys."
    assert journal.get_query_cache("non-existent-key") is None
```

- [x] **Step 2: Run pytest to verify the test fails**

Run:
```bash
taskset -c 0-5 env UV_THREADPOOL_SIZE=3 pytest tests/test_journal.py -k "test_dedicated_query_cache_stores_and_replays_without_polluting_mutation_journal" -v
```
Expected: `FAIL` with `AttributeError: 'MutationJournal' object has no attribute 'put_query_cache'`

- [x] **Step 3: Add `query_cache` table to `schema.sql` (v3), `journal.py`, and wire into `BrokerDaemon._handle_query_notebook`**

1. In `src/mcp_gateway/storage/schema.sql`, update `PRAGMA user_version=3;` and append the dedicated `query_cache` table (leaving `mutation_journal` untouched):
```sql
CREATE TABLE IF NOT EXISTS query_cache (
    cache_key TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    response_payload TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

2. In `src/mcp_gateway/storage/journal.py`:
   - In `_run_migrations()`, add a `if current_version < 3:` block that creates `query_cache` and sets `PRAGMA user_version = 3;`:
     ```python
     if current_version < 3:
         with self._conn:
             self._conn.executescript(
                 """
                 CREATE TABLE IF NOT EXISTS query_cache (
                     cache_key TEXT PRIMARY KEY,
                     notebook_id TEXT NOT NULL,
                     query_text TEXT NOT NULL,
                     response_payload TEXT NOT NULL,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                 );
                 PRAGMA user_version = 3;
                 """
             )
     ```
   - Add `put_query_cache(self, cache_key: str, notebook_id: str, query_text: str, response_payload: str) -> None` and `get_query_cache(self, cache_key: str) -> dict[str, Any] | None` to `MutationJournal`.

3. In `src/mcp_gateway/broker/broker.py` (`_handle_query_notebook`):
   - When `existing.state == MutationState.CONFIRMED`: call `cached_entry = self.journal.get_query_cache(request_key)`. If present, parse `cached_entry["response_payload"]` and return `{"ok": True, "answer": parsed["answer"], "citations": parsed["citations"], "cached": True}`.
   - When transitioning to `MutationState.CONFIRMED` at the end of `_handle_query_notebook`: call `self.journal.put_query_cache(cache_key=request_key, notebook_id=nb_id, query_text=question, response_payload=json.dumps({"answer": full_text, "citations": serialized_citations}))`.

- [x] **Step 4: Run pytest on `tests/test_journal.py` and `tests/test_broker.py`**

Run:
```bash
taskset -c 0-5 env UV_THREADPOOL_SIZE=3 pytest tests/test_journal.py tests/test_broker.py -v
```
Expected: `PASS`

- [x] **Step 5: Commit Task 3**

```bash
git add src/mcp_gateway/storage/schema.sql src/mcp_gateway/storage/journal.py src/mcp_gateway/broker/broker.py tests/test_journal.py
git commit -m "feat(storage): add dedicated query_cache table in schema v3 for query_notebook replay"
```

---

### Task 4: Create `setup_native_host.py`, Route Scotty Uploads via `page-main.js` & Add WebUI Native Messaging Handlers in `service_worker.js`

**Files:**
- Create: `setup_native_host.py`
- Modify: `src/extension/service_worker.js:79-245, 704-764`
- Test: `tests/test_scotty_chunking.py`, `tests/test_installer.py`

- [x] **Step 1: Write failing test in `tests/test_installer.py` verifying `setup_native_host.py --extension-id`**

Add to the bottom of `tests/test_installer.py`:

```python
def test_setup_native_host_cli_script_writes_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import setup_native_host

    monkeypatch.setattr(
        "mcp_gateway.host.installer.get_manifest_dir",
        lambda **_kwargs: tmp_path,
    )
    ext_id = "a" * 32
    rc = setup_native_host.main(["--extension-id", ext_id])
    assert rc == 0
    manifest_file = tmp_path / "com.mcp.gemini.broker.json"
    assert manifest_file.exists()
    content = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert f"chrome-extension://{ext_id}/" in content["allowed_origins"]
```

- [x] **Step 2: Run pytest to verify the test fails**

Run:
```bash
taskset -c 0-5 env UV_THREADPOOL_SIZE=3 pytest tests/test_installer.py -k "test_setup_native_host_cli_script_writes_manifest" -v
```
Expected: `FAIL` with `ModuleNotFoundError: No module named 'setup_native_host'`

- [x] **Step 3: Create `setup_native_host.py` and update `src/extension/service_worker.js`**

1. Create `setup_native_host.py` in the repository root:
```python
#!/usr/bin/env python3
"""Zero-friction CLI entry point for Chrome Native Messaging Host registration.

Invoked directly from the Extension Popup Setup Mode:
    python3 setup_native_host.py --extension-id <CURRENT_EXTENSION_ID>
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

_src_root = str(Path(__file__).resolve().parent / "src")
if _src_root not in sys.path:
    sys.path.insert(0, _src_root)

from mcp_gateway.host.installer import install_manifest  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="setup_native_host.py",
        description="Register the Gemini Notebook MCP Chrome Native Messaging Host manifest.",
    )
    parser.add_argument(
        "--extension-id",
        required=True,
        help="32-character Chrome Extension ID shown in the extension popup.",
    )
    parser.add_argument(
        "--browser",
        default="google-chrome",
        help="Target browser family (default: google-chrome).",
    )
    args = parser.parse_args(argv)

    ext_id = args.extension_id.strip()
    native_host_script = Path(__file__).resolve().parent / "src" / "mcp_gateway" / "host" / "native_host.py"
    try:
        manifest_path = install_manifest(
            host_path=native_host_script,
            extension_id=ext_id,
            browser=args.browser,
        )
        print(f"[+] Native Messaging Host registered at: {manifest_path}")
        print(f"[+] Bound to extension origin: chrome-extension://{ext_id}/")
        return 0
    except Exception as exc:
        print(f"[!] Failed to register Native Messaging Host: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

2. Update `src/extension/service_worker.js`:
   - Track `let lastNativeError = null;` on `nativePort.onDisconnect` and clear it when a message arrives.
   - Add a `pendingBrokerRequests = new Map()` helper `sendBrokerCommand(action, payload)` so `service_worker.js` can send `{ action: 'discover_notebooks', requestId }`, `{ action: 'get_allowlist', requestId }`, and `{ action: 'update_allowlist', notebooks, validate_uuids: true, requestId }` over `nativePort` to `native_host.py` -> `BrokerDaemon` and resolve the response when `BrokerDaemon` replies with `{ requestId, ... }`.
   - When `scotty_chunk` or `scotty_upload` arrives in `handleNativeMessage`, if `chrome.tabs` and `chrome.scripting` are available and a provisioned/active notebook tab can be reached, route via `sendCommandToPage(tab.id, { command, requestId, payload })` so `page-main.js` enforces P-03 (`verifyAccountIdentityPreflight`) in the `MAIN` world; fall back to `handleScottyChunkSW` / `executeResumableScottyUpload` only when no tab injection environment is present (unit test mocks).
   - In `chrome.runtime.onMessage`:
     - Enhance `get_status` to return `{ ok: true, connected: nativePort !== null, authuser: lastKnownAuthuser, extensionId: chrome.runtime?.id || '', lastError: lastNativeError }`.
     - Add `discover_notebooks` handler: queries the broker via `sendBrokerCommand('discover_notebooks', {})` (or falls back to querying `page-main.js` directly with `wXbhsf` if a `notebook.google.com` tab is hydrated), caches in `chrome.storage.local`, and returns `{ ok: true, notebooks }`.
     - Add `update_allowlist` handler: sends `{ action: 'update_allowlist', notebooks: message.notebooks, validate_uuids: Boolean(message.validate_uuids), requestId }` over `nativePort` to the Python broker (which atomically saves `allowlist.json` with `0o600` and calls `self.allowlist_config.reload()` under `self._session_mutex`), updates `chrome.storage.local.set({ allowlisted_notebooks })`, and returns the broker response.

- [x] **Step 4: Run pytest on `tests/test_installer.py` and `tests/test_scotty_chunking.py`**

Run:
```bash
taskset -c 0-5 env UV_THREADPOOL_SIZE=3 pytest tests/test_installer.py tests/test_scotty_chunking.py -v
```
Expected: `PASS`

- [x] **Step 5: Commit Task 4**

```bash
git add setup_native_host.py src/extension/service_worker.js tests/test_installer.py
git commit -m "feat(extension): add setup_native_host.py and wire Native Messaging allowlist sync in service_worker"
```

---

### Task 5: Implement Extension Popup Setup Mode, `NotebookAllowlistCard` Checklist, `READ_ONLY`/`INTERACTIVE` Toggles & Strict UUIDv4 Manual Fallback Input

**Files:**
- Modify: `src/extension/popup.html:1-143`
- Modify: `src/extension/popup.css:1-353`
- Modify: `src/extension/popup.js:1-240`
- Create: `tests/test_popup_webui.py`

- [x] **Step 1: Write failing tests in `tests/test_popup_webui.py` verifying Popup WebUI structure, Setup Mode command template, and strict UUIDv4 input sanitization**

Create `tests/test_popup_webui.py`:

```python
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXT_DIR = REPO_ROOT / "src" / "extension"


def test_popup_html_contains_setup_mode_checklist_and_manual_fallback() -> None:
    html = (EXT_DIR / "popup.html").read_text(encoding="utf-8")
    # 1. State-driven Setup Mode container & command element
    assert 'id="setup-mode-banner"' in html
    assert 'id="setup-command-code"' in html
    assert 'id="copy-setup-cmd-btn"' in html
    # 2. Refresh discovery button and manual fallback form for older notebooks
    assert 'id="refresh-notebooks-btn"' in html
    assert 'id="manual-notebook-form"' in html
    assert 'id="manual-notebook-input"' in html
    assert 'id="manual-notebook-mode"' in html
    assert 'id="manual-notebook-error"' in html
    # 3. Fixed documentation link
    assert "https://github.com/wdeldaybytebuster/google-notebook-mcp" in html


def test_popup_js_enforces_xss_safety_uuid_regex_and_renders_setup_and_modes() -> None:
    js = (EXT_DIR / "popup.js").read_text(encoding="utf-8")
    # Zero innerHTML usage (strict XSS invariant)
    assert ".innerHTML" not in js
    # Dynamically renders exact setup_native_host.py command with extension ID
    assert "python3 setup_native_host.py --extension-id " in js
    # Strict UUIDv4 regex validation for manual fallback inputs
    assert "^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$" in js
    assert "notebook.google.com/notebook/" in js
    # Supports READ_ONLY and INTERACTIVE granular modes
    assert "READ_ONLY" in js
    assert "INTERACTIVE" in js
    # Sends discover_notebooks and update_allowlist messages
    assert "discover_notebooks" in js
    assert "update_allowlist" in js
```

- [x] **Step 2: Run pytest to verify `tests/test_popup_webui.py` fails**

Run:
```bash
taskset -c 0-5 env UV_THREADPOOL_SIZE=3 pytest tests/test_popup_webui.py -v
```
Expected: `FAIL`

- [x] **Step 3: Update `src/extension/popup.html`, `src/extension/popup.css`, and `src/extension/popup.js`**

1. In `src/extension/popup.html`:
   - Add `<section id="setup-mode-banner" class="setup-banner" hidden>` inside `<main class="main-viewport">` containing:
     - Heading: `"Native Host Setup Required"`
     - Instructions: `"Run this command in your terminal to link Chrome with the local MCP broker:"`
     - Monospace `<code id="setup-command-code" class="setup-banner__code">python3 setup_native_host.py --extension-id ...</code>`
     - Copy button: `<button id="copy-setup-cmd-btn" class="btn btn--secondary btn--sm" type="button">Copy Command</button>`
   - Update the Notebooks section header to include `<button id="refresh-notebooks-btn" class="btn btn--secondary btn--sm" type="button">Sync</button>`.
   - Add `<form id="manual-notebook-form" class="manual-form">` below `<ul id="notebook-list">` with:
     - `<input id="manual-notebook-input" class="manual-form__input" type="text" placeholder="Paste Notebook URL or UUID…" required />`
     - `<input id="manual-notebook-title" class="manual-form__input" type="text" placeholder="Title (optional)" />`
     - `<select id="manual-notebook-mode" class="manual-form__select"><option value="READ_ONLY">Read Only</option><option value="INTERACTIVE">Interactive</option></select>`
     - `<button id="manual-notebook-add-btn" class="btn btn--primary btn--sm" type="submit">Add</button>`
     - `<div id="manual-notebook-error" class="manual-form__error" role="alert" hidden></div>`
   - Update `#docs-link` `href` to `"https://github.com/wdeldaybytebuster/google-notebook-mcp"`.

2. In `src/extension/popup.css`:
   - Add styles for `.setup-banner`, `.setup-banner__code`, `.section-header-row`, `.notebook-card__checkbox`, `.notebook-card__controls`, `.mode-toggle`, `.mode-toggle--readonly`, `.mode-toggle--interactive`, `.manual-form`, `.manual-form__input`, `.manual-form__select`, `.manual-form__error`, and `.btn--secondary` / `.btn--sm` using ONLY the existing `:root` CSS custom properties.

3. In `src/extension/popup.js`:
   - Strictly use `document.createElement` and `textContent` (zero `.innerHTML`).
   - Define `const UUID_V4_REGEX = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;`
   - Implement `parseAndValidateNotebookId(rawInput)`:
     - Extracts the UUID segment if `rawInput` is a valid `https://notebook.google.com/notebook/<uuid>` (or `https://notebooklm.google.com/notebook/<uuid>`) URL.
     - Validates the extracted/trimmed lowercase string against `UUID_V4_REGEX`. Returns `null` if invalid (and displays a clear validation message in `#manual-notebook-error` without submitting).
   - In `initStatus()`: fetch `{ type: 'get_status' }`. If `!status?.connected`, unhide `#setup-mode-banner` and set `#setup-command-code` `textContent` to `python3 setup_native_host.py --extension-id ${extId}`.
   - Implement `initNotebookList()` and `discoverNotebooks()` to render `NotebookAllowlistCard` rows with a checkbox (`allowed`), title (`row[0]`), monospace ID (`row[2]`), and `Read Only` / `Interactive` mode toggle pill, persisting updates via `chrome.runtime.sendMessage({ type: 'update_allowlist', notebooks: allowedMap })`.

- [x] **Step 4: Run pytest on `tests/test_popup_webui.py` and `tests/test_phase4_phase5.py`**

Run:
```bash
taskset -c 0-5 env UV_THREADPOOL_SIZE=3 pytest tests/test_popup_webui.py tests/test_phase4_phase5.py -v
```
Expected: `PASS`

- [x] **Step 5: Commit Task 5**

```bash
git add src/extension/popup.html src/extension/popup.css src/extension/popup.js tests/test_popup_webui.py
git commit -m "feat(popup): add Setup Mode banner, NotebookAllowlistCard checklist, READ_ONLY/INTERACTIVE toggles, and UUIDv4 sanitization"
```

---

### Task 6: Fix Windows Named Pipe Server Dispatch, Align Docs/Client Socket Paths & Clean Workspace Root

**Files:**
- Modify: `src/mcp_gateway/transport/ipc.py:188-208`
- Modify: `README.md`, `docs/client-configuration.md`, `docs/tools-reference.md`, `config/clients/cursor.json`, `config/clients/windsurf.json`, `config/clients/claude_code.json`, `config/clients/antigravity.json`
- Test: `tests/test_transport.py`

- [x] **Step 1: Write a test in `tests/test_transport.py` verifying `WindowsNamedPipeServer` dispatches connected pipe handles**

Add to `tests/test_transport.py`:

```python
def test_windows_named_pipe_server_has_dispatch_helper() -> None:
    from mcp_gateway.transport.ipc import WindowsNamedPipeServer

    async def dummy_cb(reader: Any, writer: Any) -> None:
        pass

    srv = WindowsNamedPipeServer(dummy_cb)
    assert callable(getattr(srv, "_dispatch_connected_pipe", None))
```

- [x] **Step 2: Run pytest to verify the test fails**

Run:
```bash
taskset -c 0-5 env UV_THREADPOOL_SIZE=3 pytest tests/test_transport.py -k "test_windows_named_pipe_server_has_dispatch_helper" -v
```
Expected: `FAIL`

- [x] **Step 3: Implement `_dispatch_connected_pipe` in `src/mcp_gateway/transport/ipc.py`, align docs/configs, and remove stray directories**

1. In `src/mcp_gateway/transport/ipc.py`, add `_dispatch_connected_pipe(self, pipe_handle: Any, win32file: Any, win32pipe: Any)` on `WindowsNamedPipeServer` and call `asyncio.create_task(self._dispatch_connected_pipe(pipe_handle, win32file, win32pipe))` inside `_listen_loop()` when `ConnectNamedPipe` succeeds.
2. In `README.md`, `docs/client-configuration.md`, and `config/clients/*.json`, align `MCP_BROKER_SOCKET` documentation with `get_default_ipc_path()`, and document the v2 `READ_ONLY` (allows read + `query_notebook`, blocks `add_source`/`create_note`/`delete_note`) vs `INTERACTIVE` allowlist modes in `docs/tools-reference.md`.
3. Remove the stray untracked directories `./1`, `./C:\AppData\Local`, and `./C:\Users\aaaa...` from the working tree.

- [x] **Step 4: Run the full linter, strict typechecker, and test suite sequentially**

Run:
```bash
taskset -c 0-5 env UV_THREADPOOL_SIZE=3 python3 -m ruff check src/ tests/ setup_native_host.py
taskset -c 0-5 env UV_THREADPOOL_SIZE=3 python3 -m mypy --strict src/ tests/ setup_native_host.py
taskset -c 0-5 env UV_THREADPOOL_SIZE=3 pytest tests/ -v
```
Expected: `0 errors` from `ruff` and `mypy --strict`, and `100% PASS` across the entire `pytest` suite.

- [x] **Step 5: Commit Task 6**

```bash
git add src/mcp_gateway/transport/ipc.py tests/test_transport.py README.md docs/client-configuration.md docs/tools-reference.md config/clients/
git commit -m "fix(transport,docs): wire WindowsNamedPipeServer callback and align client socket configs and READ_ONLY docs"
```
