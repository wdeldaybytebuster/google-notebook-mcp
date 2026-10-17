"""Unit tests for W3C Trace Context (traceparent) generation, validation, and parsing."""

from __future__ import annotations

import pytest

from mcp_gateway.traceparent import (
    ALL_ZEROS_PARENT_ID,
    ALL_ZEROS_TRACE_ID,
    extract_or_generate_traceparent,
    generate_traceparent,
    parse_traceparent,
    validate_traceparent,
)


def test_generate_traceparent_format() -> None:
    tp = generate_traceparent()
    assert validate_traceparent(tp) is True
    parts = tp.split("-")
    assert len(parts) == 4
    assert parts[0] == "00"
    assert len(parts[1]) == 32
    assert len(parts[2]) == 16
    assert parts[3] == "01"


def test_generate_traceparent_unsampled() -> None:
    tp = generate_traceparent(sampled=False)
    assert validate_traceparent(tp) is True
    assert tp.endswith("-00")


def test_generate_traceparent_custom_ids() -> None:
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    parent_id = "00f067aa0ba902b7"
    tp = generate_traceparent(trace_id=trace_id, parent_id=parent_id)
    assert tp == f"00-{trace_id}-{parent_id}-01"


def test_generate_traceparent_rejects_all_zeros() -> None:
    with pytest.raises(ValueError, match="Invalid trace_id"):
        generate_traceparent(trace_id=ALL_ZEROS_TRACE_ID)

    with pytest.raises(ValueError, match="Invalid parent_id"):
        generate_traceparent(parent_id=ALL_ZEROS_PARENT_ID)


def test_validate_traceparent_valid() -> None:
    valid = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    assert validate_traceparent(valid) is True


def test_validate_traceparent_invalid_version() -> None:
    # W3C Level 1: version 01 or ff is rejected
    assert validate_traceparent("01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01") is False


def test_validate_traceparent_rejects_zeros() -> None:
    # All zeros trace_id is forbidden by W3C specification
    assert validate_traceparent(f"00-{ALL_ZEROS_TRACE_ID}-00f067aa0ba902b7-01") is False
    # All zeros parent_id is forbidden by W3C specification
    assert validate_traceparent(f"00-4bf92f3577b34da6a3ce929d0e0e4736-{ALL_ZEROS_PARENT_ID}-01") is False


def test_validate_traceparent_invalid_lengths_and_chars() -> None:
    assert validate_traceparent("00-short-00f067aa0ba902b7-01") is False
    assert validate_traceparent("00-4bf92f3577b34da6a3ce929d0e0e4736-short-01") is False
    # Uppercase letters forbidden in canonical hex
    assert validate_traceparent("00-4BF92F3577B34DA6A3CE929D0E0E4736-00f067aa0ba902b7-01") is False
    # Non-hex characters
    assert validate_traceparent("00-4bf92f3577b34da6a3ce929d0e0e47zz-00f067aa0ba902b7-01") is False


def test_parse_traceparent_success() -> None:
    tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    parsed = parse_traceparent(tp)
    assert parsed is not None
    assert parsed["version"] == "00"
    assert parsed["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert parsed["parent_id"] == "00f067aa0ba902b7"
    assert parsed["trace_flags"] == "01"


def test_parse_traceparent_invalid() -> None:
    assert parse_traceparent("invalid-traceparent") is None
    assert parse_traceparent(f"00-{ALL_ZEROS_TRACE_ID}-00f067aa0ba902b7-01") is None


def test_extract_or_generate_traceparent() -> None:
    valid = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    # Extracts existing valid header
    assert extract_or_generate_traceparent({"traceparent": valid}) == valid
    assert extract_or_generate_traceparent({"traceParent": valid}) == valid

    # Generates fresh header if absent or invalid
    fresh_1 = extract_or_generate_traceparent(None)
    assert validate_traceparent(fresh_1) is True

    fresh_2 = extract_or_generate_traceparent({"traceparent": "corrupted"})
    assert validate_traceparent(fresh_2) is True
    assert fresh_2 != "corrupted"
