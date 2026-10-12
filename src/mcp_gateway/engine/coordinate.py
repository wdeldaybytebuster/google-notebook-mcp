"""UTF-16 coordinate translation utilities for Google citation offsets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def utf16_to_unicode_offset(text: str, utf16_offset: int) -> int:
    """Convert a UTF-16 code-unit offset into a Python Unicode char offset.

    Google's backend computes character positions in terms of UTF-16 code
    units (V8 JavaScript convention).  Astral-plane characters (e.g. emoji)
    occupy **two** UTF-16 code units but only **one** Python ``str`` character,
    so naive Python slicing diverges from Google offsets for such texts.

    Parameters
    ----------
    text:
        The source document text.
    utf16_offset:
        The number of UTF-16 code units from the start of *text*.

    Returns
    -------
    int
        The equivalent Python ``len()``-based character offset.
    """
    utf16_bytes = text.encode("utf-16-le")
    sliced = utf16_bytes[: utf16_offset * 2]
    return len(sliced.decode("utf-16-le", errors="replace"))


def utf16_slice(text: str, start: int, end: int) -> str:
    """Extract a substring using UTF-16 code-unit offsets.

    Uses byte-level slicing of the UTF-16-LE encoding to avoid misalignment
    on strings containing astral-plane characters.

    Parameters
    ----------
    text:
        The source document text.
    start:
        Start position in UTF-16 code units (inclusive).
    end:
        End position in UTF-16 code units (exclusive).

    Returns
    -------
    str
        The extracted substring.  Invalid surrogate sequences are replaced
        rather than raising an error.
    """
    utf16_bytes = text.encode("utf-16-le")
    sliced = utf16_bytes[start * 2 : end * 2]
    return sliced.decode("utf-16-le", errors="replace")


@dataclass(frozen=True)
class CitationSpan:
    """An immutable citation span resolved to Python Unicode character offsets.

    Attributes
    ----------
    source_id:
        The opaque source identifier returned by the API.
    start_char:
        Start character offset in the source text (Python ``str`` units).
    end_char:
        End character offset in the source text (Python ``str`` units).
    text_snippet:
        The extracted text slice corresponding to the span.
    """

    source_id: str
    start_char: int
    end_char: int
    text_snippet: str


def normalize_citation(raw: dict[str, Any], source_text: str) -> CitationSpan:
    """Translate a raw API citation dict into a :class:`CitationSpan`.

    Extracts UTF-16 code-unit offsets from *raw*, converts them to Python
    Unicode character offsets via :func:`utf16_to_unicode_offset`, and
    extracts the text snippet via :func:`utf16_slice`.

    Parameters
    ----------
    raw:
        A citation dict containing at minimum ``source_id``, ``utf16_start``,
        and ``utf16_end`` keys.
    source_text:
        The full source document text to slice the snippet from.

    Returns
    -------
    CitationSpan
        The normalized citation with Python-native character offsets.

    Raises
    ------
    ValueError
        If the offsets are negative or *utf16_end* < *utf16_start*.
    """
    source_id: str = str(raw.get("source_id", ""))
    utf16_start: int = int(raw.get("utf16_start", 0))
    utf16_end: int = int(raw.get("utf16_end", 0))

    if utf16_start < 0 or utf16_end < 0:
        raise ValueError(
            f"Citation offsets must be non-negative; got start={utf16_start}, end={utf16_end}"
        )
    if utf16_end < utf16_start:
        raise ValueError(
            f"Citation end offset must be >= start; got start={utf16_start}, end={utf16_end}"
        )

    start_char = utf16_to_unicode_offset(source_text, utf16_start)
    end_char = utf16_to_unicode_offset(source_text, utf16_end)
    snippet = utf16_slice(source_text, utf16_start, utf16_end)

    return CitationSpan(
        source_id=source_id,
        start_char=start_char,
        end_char=end_char,
        text_snippet=snippet,
    )
