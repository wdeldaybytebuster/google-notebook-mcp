"""Unit tests for MCP 2026-07-28 error schema taxonomy and failure envelopes."""

from __future__ import annotations

import json
import pytest
import mcp.types as types

from mcp_gateway.schemas.error import (
    ALLOWLIST_DENIED,
    AUTH_REQUIRED,
    INTERNAL,
    INVALID_ARGUMENT,
    MUTATION_UNKNOWN,
    NOT_FOUND,
    PERMISSION_DENIED,
    REQUEST_KEY_CONFLICT,
    RESOURCE_EXHAUSTED,
    SCHEMA_DRIFT_DETECTED,
    SESSION_LOCKED,
    SESSION_UNLOCKED,
    STREAM_DISCONNECTED,
    UPSTREAM_DRIFT,
    VAULT_LOCKED,
    ErrorDetail,
    FailureEnvelope,
    categorize_error,
    make_error,
)


def test_categorize_error_transient() -> None:
    assert categorize_error(AUTH_REQUIRED) == "transient"
    assert categorize_error(STREAM_DISCONNECTED) == "transient"
    assert categorize_error(RESOURCE_EXHAUSTED) == "transient"


def test_categorize_error_validation() -> None:
    assert categorize_error(INVALID_ARGUMENT) == "validation"
    assert categorize_error(SCHEMA_DRIFT_DETECTED) == "validation"
    assert categorize_error(UPSTREAM_DRIFT) == "validation"


def test_categorize_error_permission() -> None:
    assert categorize_error(ALLOWLIST_DENIED) == "permission"
    assert categorize_error(SESSION_LOCKED) == "permission"
    assert categorize_error(SESSION_UNLOCKED) == "permission"
    assert categorize_error(PERMISSION_DENIED) == "permission"
    assert categorize_error(VAULT_LOCKED) == "permission"


def test_categorize_error_business() -> None:
    assert categorize_error(REQUEST_KEY_CONFLICT) == "business"
    assert categorize_error(MUTATION_UNKNOWN) == "business"
    assert categorize_error(INTERNAL) == "business"
    assert categorize_error(NOT_FOUND) == "business"
    assert categorize_error("UNKNOWN_CUSTOM_CODE") == "business"


def test_error_detail_auto_categorization() -> None:
    detail = ErrorDetail(code=AUTH_REQUIRED, message="Login needed", retryable=True)
    assert detail.errorCategory == "transient"
    assert detail.isRetryable is True

    detail_val = ErrorDetail(code=INVALID_ARGUMENT, message="Bad args", retryable=False)
    assert detail_val.errorCategory == "validation"
    assert detail_val.isRetryable is False


def test_make_error_and_to_dict() -> None:
    envelope = make_error(ALLOWLIST_DENIED, "Access denied to notebook", retryable=False)
    assert envelope.ok is False
    d = envelope.to_dict()
    assert d["ok"] is False
    assert d["error"]["code"] == ALLOWLIST_DENIED
    assert d["error"]["errorCategory"] == "permission"
    assert d["error"]["isRetryable"] is False
    assert d["error"]["retryable"] is False


def test_call_tool_result_structured_content_error() -> None:
    envelope = make_error(SESSION_UNLOCKED, "Session not locked", retryable=False)
    err_dict = envelope.to_dict()
    serialized = json.dumps(err_dict, indent=2)

    structured_data = {
        "code": SESSION_UNLOCKED,
        "message": "Session not locked",
        "errorCategory": "permission",
        "isRetryable": False,
        "raw": err_dict,
    }

    result = types.CallToolResult(
        content=[types.TextContent(type="text", text=serialized)],
        structured_content=structured_data,
        is_error=True,
    )

    dumped = result.model_dump()
    assert dumped["is_error"] is True
    assert dumped["structured_content"]["code"] == SESSION_UNLOCKED
    assert dumped["structured_content"]["errorCategory"] == "permission"
    assert dumped["structured_content"]["isRetryable"] is False
