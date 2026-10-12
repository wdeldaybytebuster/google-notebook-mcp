"""Unit tests for BatchexecuteStreamDecoder and GenerateFreeFormStreamParser."""

from __future__ import annotations

import json
import pathlib

import pytest

from mcp_gateway.engine.stream_decoder import (
    BatchexecuteStreamDecoder,
    GenerateFreeFormStreamParser,
    StreamDecodeError,
)

FIXTURES_PATH = pathlib.Path(__file__).parent / "fixtures" / "golden_wire_captures.json"


def load_fixtures() -> dict:  # type: ignore[type-arg]
    """Load the golden wire captures fixture file."""
    return json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))


def hex_to_bytes(hex_str: str) -> bytes:
    """Decode a hex-encoded bytes string."""
    return bytes.fromhex(hex_str)


def test_antixssi_strip() -> None:
    """Feeding the antixssi_single_frame fixture yields one decoded wrb.fr record."""
    fixtures = load_fixtures()
    raw = hex_to_bytes(fixtures["antixssi_single_frame"])

    decoder = BatchexecuteStreamDecoder()
    results = decoder.feed(raw)

    assert len(results) == 1, f"Expected 1 result, got {len(results)}: {results}"
    record = results[0]
    assert record["rpc_id"] == "wXbhsf", f"Unexpected rpc_id: {record['rpc_id']!r}"
    # Inner data should be a list containing the synthetic notebook row.
    data = record["data"]
    assert isinstance(data, list), f"Expected list data, got {type(data)}"
    assert len(data) == 1
    notebook_row = data[0]
    assert notebook_row[0] == "nb-0001-synthetic"
    assert notebook_row[1] == "My Test Notebook"


def test_fragment_reassembly() -> None:
    """First chunk returns no results; second chunk completes the frame."""
    fixtures = load_fixtures()
    chunk1 = hex_to_bytes(fixtures["fragmented_two_chunks"][0])
    chunk2 = hex_to_bytes(fixtures["fragmented_two_chunks"][1])

    decoder = BatchexecuteStreamDecoder()

    results1 = decoder.feed(chunk1)
    assert results1 == [], f"Expected no results after first chunk, got: {results1}"

    results2 = decoder.feed(chunk2)
    assert len(results2) == 1, f"Expected 1 result after second chunk, got {len(results2)}: {results2}"
    assert results2[0]["rpc_id"] == "wXbhsf"


def test_error_frame_raises() -> None:
    """An 'e' error frame causes StreamDecodeError with the correct error_code."""
    fixtures = load_fixtures()
    raw = hex_to_bytes(fixtures["error_frame_132"])

    decoder = BatchexecuteStreamDecoder()

    with pytest.raises(StreamDecodeError) as exc_info:
        decoder.feed(raw)

    assert exc_info.value.error_code == 132, (
        f"Expected error_code 132, got {exc_info.value.error_code}"
    )


def test_gffs_citation_extraction() -> None:
    """GenerateFreeFormStreamParser extracts at least one citation from non_ascii_citation fixture."""
    fixtures = load_fixtures()
    raw = hex_to_bytes(fixtures["non_ascii_citation"]["hex"])

    parser = GenerateFreeFormStreamParser()
    results = parser.feed(raw)

    citation_events = [r for r in results if r.get("type") == "citation"]
    assert len(citation_events) >= 1, (
        f"Expected at least one citation event, got results: {results}"
    )
    citations = citation_events[0]["citations"]
    assert len(citations) >= 1

    cit = citations[0]
    assert cit["source_id"] == fixtures["non_ascii_citation"]["source_id"]
    assert cit["utf16_start"] == fixtures["non_ascii_citation"]["utf16_start"]
    assert cit["utf16_end"] == fixtures["non_ascii_citation"]["utf16_end"]
