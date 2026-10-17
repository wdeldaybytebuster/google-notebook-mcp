"""ADR-011: Mandatory Single-Notebook Session Lock Finite State Machine.

Enforces:
- UNINITIALIZED -> DISCOVERY_ONLY -> NOTEBOOK_LOCKED -> ACTIVE_DISPATCH
- In-memory asyncio.Lock() session state mutex to prevent TOCTOU race conditions.
- Strict tool gating: only list_notebooks and select_notebook permitted in DISCOVERY_ONLY.
- Parameter Overwrite Invariant: arguments["notebook_id"] := session.locked_notebook_id in ACTIVE_DISPATCH.
- Post-Lock Context Scoping: filtering notebook listings to only the locked context.
"""

from __future__ import annotations

import asyncio
from enum import Enum
import hashlib
import hmac
import secrets
from typing import Any

from mcp_gateway.schemas.error import (
    ALLOWLIST_DENIED,
    FailureEnvelope,
    SESSION_LOCKED,
    SESSION_UNLOCKED,
    make_error,
)


class SessionState(str, Enum):
    """ADR-011 session lifecycle states."""

    UNINITIALIZED = "UNINITIALIZED"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    NOTEBOOK_LOCKED = "NOTEBOOK_LOCKED"
    ACTIVE_DISPATCH = "ACTIVE_DISPATCH"


class SessionLock:
    """Manages session isolation, mutex-protected gating, and single-notebook binding."""

    def __init__(self, capability_secret: bytes | None = None) -> None:
        self.state: SessionState = SessionState.DISCOVERY_ONLY
        self.locked_notebook_id: str | None = None
        self.session_id: str = secrets.token_hex(16)
        self.capability_secret: bytes = capability_secret or secrets.token_bytes(32)
        self.capability_token: str | None = None
        self._mutex: asyncio.Lock = asyncio.Lock()

    async def select_notebook(
        self,
        notebook_id: str,
        is_allowed: bool,
    ) -> dict[str, Any]:
        """Binds the session to the given notebook ID if allowlist policy permits."""
        async with self._mutex:
            if not is_allowed:
                return make_error(
                    ALLOWLIST_DENIED,
                    f"Notebook '{notebook_id}' is not in the allowlist. Access denied by local policy.",
                    retryable=False,
                ).to_dict()

            if self.state == SessionState.ACTIVE_DISPATCH:
                if self.locked_notebook_id != notebook_id:
                    return make_error(
                        SESSION_LOCKED,
                        f"Session is already locked to notebook_id '{self.locked_notebook_id}'. "
                        f"Switching to '{notebook_id}' is forbidden.",
                        retryable=False,
                    ).to_dict()
                return {
                    "ok": True,
                    "notebook_id": self.locked_notebook_id,
                    "status": "LOCKED",
                    "message": "Already locked to this notebook.",
                }

            self.locked_notebook_id = notebook_id
            payload = f"{self.session_id}:{notebook_id}".encode("utf-8")
            self.capability_token = hmac.new(
                self.capability_secret,
                payload,
                hashlib.sha256,
            ).hexdigest()
            self.state = SessionState.ACTIVE_DISPATCH

            return {
                "ok": True,
                "notebook_id": notebook_id,
                "status": "LOCKED",
                "token": self.capability_token,
            }

    async def validate_and_prepare(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> FailureEnvelope | None:
        """Validates action against the session state machine and applies parameter invariants."""
        async with self._mutex:
            if action in ("list_notebooks", "select_notebook"):
                return None

            if self.state == SessionState.DISCOVERY_ONLY:
                from mcp_gateway.broker.project_config import get_project_notebook_config

                cfg = get_project_notebook_config()
                if cfg:
                    name = cfg.get("title") or cfg.get("notebook_id")
                    msg = (
                        f"Gateway locked (SESSION_UNLOCKED). Project default notebook is '{name}'. "
                        f"Please double-check with the user at the start of this chat: 'For this project, we have notebook \"{name}\" configured. "
                        "Would you like to use this notebook, or select another from list_notebooks?' "
                        "Once the user confirms, call select_notebook to lock the session for this chat."
                    )
                else:
                    msg = (
                        "Gateway locked (SESSION_UNLOCKED). At the start of each chat, you must take the list of notebooks from list_notebooks, "
                        "present the available notebooks to the user, and ask: 'Which Google Notebook would you like to use for this project?' "
                        "Once confirmed by the user, call select_notebook with save_for_project=true."
                    )
                return make_error(
                    SESSION_UNLOCKED,
                    msg,
                    retryable=False,
                )

            if self.state == SessionState.ACTIVE_DISPATCH:
                assert self.locked_notebook_id is not None
                requested_id = arguments.get("notebook_id")
                if requested_id and str(requested_id) != self.locked_notebook_id:
                    return make_error(
                        SESSION_LOCKED,
                        f"Session is locked exclusively to notebook_id '{self.locked_notebook_id}'. Access to notebook '{requested_id}' is forbidden.",
                        retryable=False,
                    )

                # Parameter Overwrite Invariant: Re-bind target notebook strictly to locked ID
                arguments["notebook_id"] = self.locked_notebook_id
                return None

            return make_error(
                SESSION_UNLOCKED,
                "Session is uninitialized.",
                retryable=False,
            )

    def filter_notebooks(self, notebooks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filters notebook listings down to exclusively the locked notebook if locked."""
        if self.state == SessionState.ACTIVE_DISPATCH and self.locked_notebook_id:
            return [
                nb for nb in notebooks
                if str(nb.get("id") or nb.get("notebook_id") or "") == self.locked_notebook_id
            ]
        return notebooks
