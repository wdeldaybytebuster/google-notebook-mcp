"""Standardized error models and failure envelopes for MCP gateway."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

PERMISSION_DENIED = "PERMISSION_DENIED"
NOT_FOUND = "NOT_FOUND"
ALLOWLIST_DENIED = "ALLOWLIST_DENIED"
AUTH_REQUIRED = "AUTH_REQUIRED"
UPSTREAM_DRIFT = "UPSTREAM_DRIFT"
MUTATION_UNKNOWN = "MUTATION_UNKNOWN"
REQUEST_KEY_CONFLICT = "REQUEST_KEY_CONFLICT"
VAULT_LOCKED = "VAULT_LOCKED"
INVALID_ARGUMENT = "INVALID_ARGUMENT"
INTERNAL = "INTERNAL"


@dataclass(frozen=True)
class ErrorDetail:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class FailureEnvelope:
    error: ErrorDetail
    ok: Literal[False] = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_error(code: str, message: str, retryable: bool = False) -> FailureEnvelope:
    """Constructs a standardized FailureEnvelope."""
    return FailureEnvelope(
        error=ErrorDetail(code=code, message=message, retryable=retryable)
    )
