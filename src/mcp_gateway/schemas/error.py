"""Standardized error models and failure envelopes for MCP gateway."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

PERMISSION_DENIED = "PERMISSION_DENIED"
NOT_FOUND = "NOT_FOUND"
ALLOWLIST_DENIED = "ALLOWLIST_DENIED"
AUTH_REQUIRED = "AUTH_REQUIRED"
UPSTREAM_DRIFT = "UPSTREAM_DRIFT"
UPSTREAM_SCHEMA_DRIFT = "UPSTREAM_SCHEMA_DRIFT"
MUTATION_UNKNOWN = "MUTATION_UNKNOWN"
REQUEST_KEY_CONFLICT = "REQUEST_KEY_CONFLICT"
VAULT_LOCKED = "VAULT_LOCKED"
INVALID_ARGUMENT = "INVALID_ARGUMENT"
INTERNAL = "INTERNAL"
SESSION_UNLOCKED = "SESSION_UNLOCKED"
SESSION_LOCKED = "SESSION_LOCKED"
BATCH_NOT_PERMITTED_DURING_HANDSHAKE = "BATCH_NOT_PERMITTED_DURING_HANDSHAKE"
DUPLICATE_COMPANION_REJECTED = "DUPLICATE_COMPANION_REJECTED"
STREAM_DISCONNECTED = "STREAM_DISCONNECTED"
STREAM_SEVERED = "STREAM_SEVERED"
RESOLVING_SESSION = "RESOLVING_SESSION"
UNGROUNDED_RESPONSE = "UNGROUNDED_RESPONSE"
RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
SCHEMA_DRIFT_DETECTED = "SCHEMA_DRIFT_DETECTED"


ErrorCategory = Literal["transient", "validation", "permission", "business"]


def categorize_error(code: str) -> ErrorCategory:
    """Categorizes an error code into one of four MCP 2026-07-28 taxonomy categories."""
    if code in (AUTH_REQUIRED, STREAM_DISCONNECTED, STREAM_SEVERED, RESOLVING_SESSION, RESOURCE_EXHAUSTED):
        return "transient"
    elif code in (INVALID_ARGUMENT, SCHEMA_DRIFT_DETECTED, UPSTREAM_DRIFT, UPSTREAM_SCHEMA_DRIFT):
        return "validation"
    elif code in (
        ALLOWLIST_DENIED,
        SESSION_LOCKED,
        SESSION_UNLOCKED,
        PERMISSION_DENIED,
        VAULT_LOCKED,
    ):
        return "permission"
    else:
        return "business"


@dataclass(frozen=True)
class ErrorDetail:
    code: str
    message: str
    retryable: bool
    errorCategory: ErrorCategory | None = None
    isRetryable: bool | None = None
    mcp_correlation_id: str | None = None

    def __post_init__(self) -> None:
        if self.errorCategory is None:
            object.__setattr__(self, "errorCategory", categorize_error(self.code))
        if self.isRetryable is None:
            object.__setattr__(self, "isRetryable", self.retryable)


@dataclass(frozen=True)
class FailureEnvelope:
    error: ErrorDetail
    ok: Literal[False] = False
    _meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.error.mcp_correlation_id and "mcp_correlation_id" not in data["_meta"]:
            data["_meta"]["mcp_correlation_id"] = self.error.mcp_correlation_id
        return data


def make_error(
    code: str,
    message: str,
    retryable: bool = False,
    mcp_correlation_id: str | None = None,
    traceparent: str | None = None,
) -> FailureEnvelope:
    """Constructs a standardized FailureEnvelope."""
    meta: dict[str, Any] = {}
    if mcp_correlation_id:
        meta["mcp_correlation_id"] = mcp_correlation_id
    if traceparent:
        meta["traceparent"] = traceparent

    return FailureEnvelope(
        error=ErrorDetail(
            code=code,
            message=message,
            retryable=retryable,
            mcp_correlation_id=mcp_correlation_id,
        ),
        _meta=meta,
    )
