from __future__ import annotations

import pytest

from mcp_gateway.engine.coordinate import (
    CitationSpan,
    normalize_citation,
    utf16_slice,
    utf16_to_unicode_offset,
)


def test_astral_plane_mathematical_symbols() -> None:
    # 𝕏 (U+1D54F: 2 UTF-16 code units, 1 Python char)
    text = "Math: 𝕏 is blackboard bold X, and 𝔸 is bold A."
    # "Math: " is 6 chars, 6 code units.
    # "𝕏" is 1 char, 2 code units.
    # " is blackboard bold X, and " is 27 chars, 27 code units.
    # Total before 𝔸: 6 + 2 + 27 = 35 code units.
    # "𝔸" is 1 char, 2 code units.

    # Slicing "𝕏"
    assert utf16_slice(text, 6, 8) == "𝕏"
    assert utf16_to_unicode_offset(text, 6) == 6
    assert utf16_to_unicode_offset(text, 8) == 7

    span = normalize_citation({"source_id": "math_doc", "utf16_start": 6, "utf16_end": 8}, text)
    assert span.text_snippet == "𝕏"
    assert span.start_char == 6
    assert span.end_char == 7
    assert text[span.start_char:span.end_char] == span.text_snippet


def test_astral_plane_zwj_sequences() -> None:
    # Family emoji 👨‍👩‍👧‍👦 is composed of:
    # 👨 (2 code units, 1 char) + ZWJ (1 code unit, 1 char) +
    # 👩 (2 code units, 1 char) + ZWJ (1 code unit, 1 char) +
    # 👧 (2 code units, 1 char) + ZWJ (1 code unit, 1 char) +
    # 👦 (2 code units, 1 char)
    # Total UTF-16 code units = 2 + 1 + 2 + 1 + 2 + 1 + 2 = 11 code units
    # Total Python chars = 7 chars
    family = "👨‍👩‍👧‍👦"
    text = f"Family: {family} at park."

    start_utf16 = 8  # "Family: " is 8 chars / 8 code units
    end_utf16 = start_utf16 + 11

    assert utf16_slice(text, start_utf16, end_utf16) == family
    py_start = utf16_to_unicode_offset(text, start_utf16)
    py_end = utf16_to_unicode_offset(text, end_utf16)
    assert py_start == 8
    assert py_end == 8 + 7
    assert text[py_start:py_end] == family

    span = normalize_citation(
        {"source_id": "family_src", "utf16_start": start_utf16, "utf16_end": end_utf16},
        text,
    )
    assert span.text_snippet == family
    assert span.start_char == 8
    assert span.end_char == 15
    assert text[span.start_char:span.end_char] == family


def test_astral_plane_flag_sequences() -> None:
    # 🇺🇸 is U+1F1FA (2 code units) + U+1F1F8 (2 code units) = 4 code units, 2 chars
    flag = "🇺🇸"
    text = f"Flag: {flag} flying high."

    start_utf16 = 6  # "Flag: "
    end_utf16 = 6 + 4

    assert utf16_slice(text, start_utf16, end_utf16) == flag
    py_start = utf16_to_unicode_offset(text, start_utf16)
    py_end = utf16_to_unicode_offset(text, end_utf16)
    assert py_start == 6
    assert py_end == 8
    assert text[py_start:py_end] == flag


def test_negative_offsets_raise_value_error() -> None:
    text = "Sample citation document"
    with pytest.raises(ValueError, match="non-negative"):
        normalize_citation({"source_id": "s1", "utf16_start": -1, "utf16_end": 5}, text)

    with pytest.raises(ValueError, match="non-negative"):
        normalize_citation({"source_id": "s1", "utf16_start": 0, "utf16_end": -5}, text)


def test_inverted_ranges_raise_value_error() -> None:
    text = "Sample citation document"
    with pytest.raises(ValueError, match="end offset must be >= start"):
        normalize_citation({"source_id": "s1", "utf16_start": 10, "utf16_end": 4}, text)


def test_offsets_exceeding_document_length() -> None:
    text = "Short text 😀"
    # len(text) in Python = 12
    # UTF-16 length = 11 + 2 = 13 code units
    doc_utf16_len = 13

    # Asking for offset 100 exceeds document length
    py_offset = utf16_to_unicode_offset(text, 100)
    assert py_offset == len(text)

    # Slicing beyond document length clamps cleanly without IndexError
    sliced = utf16_slice(text, 0, 100)
    assert sliced == text

    span = normalize_citation({"source_id": "s_overflow", "utf16_start": 0, "utf16_end": 100}, text)
    assert span.text_snippet == text
    assert span.start_char == 0
    assert span.end_char == len(text)


def test_zero_length_empty_citation() -> None:
    text = "Sample document"
    span = normalize_citation({"source_id": "empty", "utf16_start": 5, "utf16_end": 5}, text)
    assert span.start_char == 5
    assert span.end_char == 5
    assert span.text_snippet == ""
