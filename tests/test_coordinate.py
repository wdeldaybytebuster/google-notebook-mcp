"""Unit tests for UTF-16 coordinate translation and CitationSpan normalization."""

from __future__ import annotations

import json
import pathlib

from typing import Any, cast

import pytest

from mcp_gateway.engine.coordinate import (
    CitationSpan,
    normalize_citation,
    utf16_slice,
    utf16_to_unicode_offset,
)

FIXTURES_PATH = pathlib.Path(__file__).parent / "fixtures" / "golden_wire_captures.json"


def load_fixtures() -> dict[str, Any]:
    """Load the golden wire captures fixture file."""
    return cast(dict[str, Any], json.loads(FIXTURES_PATH.read_text(encoding="utf-8")))


def test_ascii_roundtrip() -> None:
    """utf16_slice on pure-ASCII text matches simple Python slicing."""
    result = utf16_slice("hello world", 0, 5)
    assert result == "hello", f"Expected 'hello', got {result!r}"


def test_astral_offset() -> None:
    """utf16_to_unicode_offset correctly handles astral-plane characters (emoji).

    The string 'Hi 😀 end' has the emoji at UTF-16 code units 3–4 (surrogate
    pair).  The Python character index for the emoji is also 3 because 'Hi '
    is 3 characters.  We verify that asking for utf16 offset 3 returns
    Python index 3, and asking for utf16 offset 5 (just after the emoji)
    returns Python index 4.
    """
    fixtures = load_fixtures()
    source_text: str = fixtures["non_ascii_citation"]["source_text"]

    # Offset 3 (UTF-16) → Python char 3 ('😀' starts here)
    py_start = utf16_to_unicode_offset(source_text, 3)
    assert py_start == fixtures["non_ascii_citation"]["expected_python_start"], (
        f"Expected Python start {fixtures['non_ascii_citation']['expected_python_start']}, "
        f"got {py_start}"
    )

    # Offset 5 (UTF-16) → Python char 4 (just after '😀')
    py_end = utf16_to_unicode_offset(source_text, 5)
    assert py_end == fixtures["non_ascii_citation"]["expected_python_end"], (
        f"Expected Python end {fixtures['non_ascii_citation']['expected_python_end']}, "
        f"got {py_end}"
    )


def test_utf16_slice_with_astral() -> None:
    """utf16_slice on a string with emoji returns the correct substring."""
    fixtures = load_fixtures()
    source_text: str = fixtures["non_ascii_citation"]["source_text"]
    utf16_start: int = fixtures["non_ascii_citation"]["utf16_start"]
    utf16_end: int = fixtures["non_ascii_citation"]["utf16_end"]
    expected: str = fixtures["non_ascii_citation"]["expected_snippet"]

    result = utf16_slice(source_text, utf16_start, utf16_end)
    assert result == expected, (
        f"Expected {expected!r}, got {result!r}"
    )


def test_normalize_citation_valid() -> None:
    """normalize_citation builds a correct CitationSpan from a raw citation dict."""
    fixtures = load_fixtures()
    nc = fixtures["non_ascii_citation"]
    source_text: str = nc["source_text"]

    raw = {
        "source_id": nc["source_id"],
        "utf16_start": nc["utf16_start"],
        "utf16_end": nc["utf16_end"],
    }

    span = normalize_citation(raw, source_text)

    assert isinstance(span, CitationSpan)
    assert span.source_id == nc["source_id"]
    assert span.start_char == nc["expected_python_start"]
    assert span.end_char == nc["expected_python_end"]
    assert span.text_snippet == nc["expected_snippet"]


def test_normalize_citation_invalid_offsets() -> None:
    """normalize_citation raises ValueError when end < start."""
    raw = {
        "source_id": "src-test",
        "utf16_start": 10,
        "utf16_end": 5,  # end < start — invalid
    }
    with pytest.raises(ValueError):
        normalize_citation(raw, "some source text")
