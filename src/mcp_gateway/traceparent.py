"""W3C Trace Context (traceparent) generation, validation, and parsing.

Specification: W3C Trace Context Level 1 (Recommendation).
Format: {version}-{trace_id}-{parent_id}-{trace_flags}
  - version: '00' (2 hex digits)
  - trace_id: 32 hex characters (16 bytes / 128 bits entropy). Must not be all zeros.
  - parent_id: 16 hex characters (8 bytes / 64 bits entropy). Must not be all zeros.
  - trace_flags: '01' (recorded/sampled) or '00'.

Collision bound: P(collision) <= k^2 / (2 * 2^128) < 10^-20 for k <= 10^9.
"""

from __future__ import annotations

import re
import secrets
from typing import Any

W3C_TRACEPARENT_REGEX = re.compile(
    r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"
)

ALL_ZEROS_TRACE_ID = "0" * 32
ALL_ZEROS_PARENT_ID = "0" * 16


def validate_traceparent(header: str) -> bool:
    """Validates if *header* complies strictly with W3C Trace Context Level 1."""
    if not isinstance(header, str):
        return False
    match = W3C_TRACEPARENT_REGEX.match(header.strip())
    if not match:
        return False
    trace_id, parent_id, _ = match.groups()
    if trace_id == ALL_ZEROS_TRACE_ID or parent_id == ALL_ZEROS_PARENT_ID:
        return False
    return True


def parse_traceparent(header: str) -> dict[str, str] | None:
    """Parses a valid W3C traceparent header into its components."""
    if not isinstance(header, str):
        return None
    match = W3C_TRACEPARENT_REGEX.match(header.strip())
    if not match:
        return None
    trace_id, parent_id, flags = match.groups()
    if trace_id == ALL_ZEROS_TRACE_ID or parent_id == ALL_ZEROS_PARENT_ID:
        return None
    return {
        "version": "00",
        "trace_id": trace_id,
        "parent_id": parent_id,
        "trace_flags": flags,
    }


def generate_traceparent(
    trace_id: str | None = None,
    parent_id: str | None = None,
    sampled: bool = True,
) -> str:
    """Generates a cryptographically random, compliant W3C traceparent header."""
    if trace_id is None:
        while True:
            trace_id = secrets.token_hex(16)
            if trace_id != ALL_ZEROS_TRACE_ID:
                break
    elif len(trace_id) != 32 or trace_id == ALL_ZEROS_TRACE_ID:
        raise ValueError(f"Invalid trace_id {trace_id!r}: must be 32 non-zero hex digits")

    if parent_id is None:
        while True:
            parent_id = secrets.token_hex(8)
            if parent_id != ALL_ZEROS_PARENT_ID:
                break
    elif len(parent_id) != 16 or parent_id == ALL_ZEROS_PARENT_ID:
        raise ValueError(f"Invalid parent_id {parent_id!r}: must be 16 non-zero hex digits")

    flags = "01" if sampled else "00"
    return f"00-{trace_id}-{parent_id}-{flags}"


def extract_or_generate_traceparent(meta: dict[str, Any] | None = None) -> str:
    """Extracts existing valid traceparent from metadata, or generates a new root traceparent."""
    if meta and isinstance(meta, dict):
        candidate = meta.get("traceparent") or meta.get("traceParent")
        if candidate and isinstance(candidate, str) and validate_traceparent(candidate):
            return candidate.strip()
    return generate_traceparent()
