"""Wire protocol stream decoder for batchexecute and GenerateFreeFormStreamed responses."""

from __future__ import annotations

import codecs
import json
import sys
from typing import Any


class StreamDecodeError(Exception):
    """Raised when a batchexecute response contains an error frame."""

    def __init__(self, message: str, error_code: int) -> None:
        super().__init__(message)
        self.error_code: int = error_code


class BatchexecuteStreamDecoder:
    """Incremental decoder for Google batchexecute responses.

    Strips the anti-XSSI prefix ``)]}'\\n`` on the first call only (stateful).
    Accumulates bytes across ``feed()`` calls until complete JSON frames can be
    extracted.  Returns decoded inner payloads from ``wrb.fr`` records and raises
    :class:`StreamDecodeError` for ``e`` (error) records.

    No raw response body is ever logged.
    """

    _ANTIXSSI_PREFIX: bytes = b")]}'\\n"

    def __init__(self) -> None:
        self._buffer: bytes = b""
        self._prefix_stripped: bool = False

    def feed(self, chunk: bytes) -> list[dict[str, Any]]:
        """Append *chunk* to the internal buffer and extract any complete frames.

        Parameters
        ----------
        chunk:
            Raw bytes received from the network response.

        Returns
        -------
        list[dict]
            Zero or more decoded dicts extracted from ``wrb.fr`` frames.

        Raises
        ------
        StreamDecodeError
            If an ``e`` error frame is encountered in the response.
        """
        if not self._prefix_stripped:
            # Prepend any previously buffered bytes so we can strip across chunks.
            combined = self._buffer + chunk
            if combined.startswith(self._ANTIXSSI_PREFIX):
                combined = combined[len(self._ANTIXSSI_PREFIX):]
            # Mark as stripped regardless — we only attempt once.
            self._prefix_stripped = True
            self._buffer = combined
        else:
            self._buffer += chunk

        return self._extract_frames()

    def _extract_frames(self) -> list[dict[str, Any]]:
        """Try to parse complete JSON arrays from the internal buffer."""
        results: list[dict[str, Any]] = []
        buf = self._buffer.decode("utf-8", errors="replace")

        # batchexecute responses are a sequence of JSON arrays.  We scan for
        # complete top-level arrays by finding matching brackets.
        pos = 0
        last_consumed = 0

        while pos < len(buf):
            # Find the start of the next JSON array.
            start = buf.find("[", pos)
            if start == -1:
                break

            # Walk forward looking for a complete JSON array.
            depth = 0
            in_string = False
            escape_next = False
            end = -1

            for i in range(start, len(buf)):
                ch = buf[i]
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\" and in_string:
                    escape_next = True
                    continue
                if ch == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break

            if end == -1:
                # Incomplete — wait for more data.
                break

            candidate = buf[start: end + 1]
            try:
                outer = json.loads(candidate)
            except json.JSONDecodeError:
                # Not a valid JSON array; advance past this '[' and keep scanning.
                pos = start + 1
                continue

            last_consumed = end + 1
            pos = last_consumed

            if not isinstance(outer, list) or not outer:
                continue

            # Each top-level frame is itself wrapped in another array layer by
            # batchexecute.  The actual content arrays are in outer[0].
            frames: list[Any] = outer if isinstance(outer[0], list) else [outer]

            for frame in frames:
                if not isinstance(frame, list) or not frame:
                    continue
                frame_type = frame[0] if frame else None

                if frame_type == "wrb.fr":
                    # frame shape: ['wrb.fr', rpc_id, json_str, ...]
                    if len(frame) >= 3 and isinstance(frame[2], str):
                        try:
                            inner = json.loads(frame[2])
                        except json.JSONDecodeError:
                            inner = {}
                        results.append({"rpc_id": frame[1], "data": inner})
                elif frame_type == "e":
                    # frame shape: ['e', [[error_code, message, ...]]]
                    if len(frame) >= 2 and isinstance(frame[1], list):
                        error_code = -1
                        inner_list = frame[1]
                        if inner_list and isinstance(inner_list[0], list):
                            code_candidate = inner_list[0][0] if inner_list[0] else -1
                            if isinstance(code_candidate, int):
                                error_code = code_candidate
                        raise StreamDecodeError(
                            f"batchexecute error frame received (code={error_code})",
                            error_code=error_code,
                        )
                    # Normal completion frame: ['e', chunk_count, None, None, byte_len] -> ignore
                elif frame_type == "er":
                    # frame shape: ['er', null, null, null, null, error_code]
                    code_candidate = frame[5] if len(frame) > 5 else -1
                    error_code = code_candidate if isinstance(code_candidate, int) else -1
                    raise StreamDecodeError(
                        f"batchexecute error frame received (code={error_code})",
                        error_code=error_code,
                    )

        # Consume only the bytes we successfully parsed.
        if last_consumed > 0:
            self._buffer = self._buffer[len(buf[:last_consumed].encode("utf-8", errors="replace")):]

        return results


class GenerateFreeFormStreamParser:
    """Incremental parser for server-sent GenerateFreeFormStreamed chunks.

    Each non-empty line in the chunked response is a complete JSON array.
    Records are classified into ``text_delta``, ``citation``, and ``done``
    event dicts.

    No raw response body is ever logged.
    """

    def __init__(self) -> None:
        self._line_buffer: str = ""
        self._last_cumulative_text: str = ""
        self._is_terminated_cleanly: bool = False
        self._utf8_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def feed(self, chunk: bytes) -> list[dict[str, Any]]:
        """Append *chunk* and return any complete event dicts extracted.

        Parameters
        ----------
        chunk:
            Raw bytes from the streaming response body.

        Returns
        -------
        list[dict]
            Decoded event dicts with key ``type`` set to ``'text_delta'``,
            ``'citation'``, or ``'done'``.
        """
        self._line_buffer += self._utf8_decoder.decode(chunk, final=False)
        results: list[dict[str, Any]] = []

        while "\n" in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            parsed = self._classify(record)
            if parsed is not None:
                parsed_list = parsed if isinstance(parsed, list) else [parsed]
                for item in parsed_list:
                    if item.get("type") == "done":
                        self._is_terminated_cleanly = True
                    results.append(item)
            else:
                rec_str = json.dumps(record)
                if len(rec_str) > 10 and not rec_str.startswith('[["wrb.fr"'):
                    print(f"[stream_decoder unclassified]: {rec_str[:300]}", file=sys.stderr)

        return results

    def finalize(self) -> list[dict[str, Any]]:
        """Invoked on stream closure to detect abrupt mid-stream severance (P-01).

        If the stream ended without receiving Google's clean done delimiter,
        emits an explicit error delta frame so downstream clients do not hang.
        """
        # Flush any trailing bytes from incremental decoder
        self._line_buffer += self._utf8_decoder.decode(b"", final=True)
        if not self._is_terminated_cleanly and not self._last_cumulative_text:
            return [
                {
                    "type": "error_delta",
                    "error": {
                        "code": "STREAM_SEVERED",
                        "message": "Stream severed unexpectedly by upstream transport.",
                        "retryable": True,
                    },
                }
            ]
        return []

    def _classify(self, record: Any) -> list[dict[str, Any]] | dict[str, Any] | None:
        """Classify a parsed JSON record into one or more event dicts."""
        if not isinstance(record, list) or not record:
            return None

        # Check for done sentinel or completion indicators (di / null / empty)
        if (len(record) >= 1 and record[0] is None and len(record) == 1) or record == []:
            return {"type": "done"}
        if len(record) > 0 and record[0] == "di":
            return {"type": "done"}
        if len(record) > 0 and isinstance(record[0], list) and record[0] and record[0][0] == "di":
            return {"type": "done"}

        # Check for batchexecute-wrapped wrb.fr record: [['wrb.fr', None, 'JSON_STR', ...]]
        if (
            len(record) > 0
            and isinstance(record[0], list)
            and len(record[0]) > 2
            and record[0][0] == "wrb.fr"
            and isinstance(record[0][2], str)
        ):
            events: list[dict[str, Any]] = []
            try:
                inner_data = json.loads(record[0][2])
                cits = self._extract_citations(inner_data)
                if cits:
                    events.append({"type": "citation", "citations": cits})

                if isinstance(inner_data, list):
                    if (
                        len(inner_data) > 0
                        and isinstance(inner_data[0], list)
                        and len(inner_data[0]) > 4
                        and isinstance(inner_data[0][4], list)
                    ):
                        ast_cits = self._extract_ast_citations(inner_data[0][4])
                        if ast_cits and not cits:
                            events.append({"type": "citation", "citations": ast_cits})

                    text_candidate = inner_data[0][0]
                    if isinstance(text_candidate, str):
                        if text_candidate.startswith(self._last_cumulative_text):
                            delta = text_candidate[len(self._last_cumulative_text):]
                            self._last_cumulative_text = text_candidate
                            if delta:
                                events.append({"type": "text_delta", "text": delta})
                        else:
                            self._last_cumulative_text = text_candidate
                            if text_candidate:
                                events.append({"type": "text_delta", "text": text_candidate})
            except Exception:
                pass

            if events:
                return events
            return None

        # Check for done sentinel.
        if len(record) >= 1 and record[0] is None and len(record) == 1:
            return {"type": "done"}

        # Try to extract text delta: record is [[text_string, ...], ...]
        if isinstance(record[0], list):
            inner = record[0]
            if inner and isinstance(inner[0], str):
                if inner[0] in ("wrb.fr", "di", "af.httprm", "e", "er"):
                    return None
                return {"type": "text_delta", "text": inner[0]}

            # Citation coordinates: inner contains nested lists with int offsets.
            # Shape heuristic: inner[0] is a list with at least one sub-list
            # containing numeric offsets.
            if inner and isinstance(inner[0], list):
                citations = self._extract_citations(record)
                if citations:
                    return {"type": "citation", "citations": citations}

        # Text delta at record[0] directly.
        if isinstance(record[0], str):
            if record[0] in ("wrb.fr", "di", "af.httprm", "e", "er"):
                return None
            return {"type": "text_delta", "text": record[0]}

        return None

    def _extract_citations(self, record: list[Any]) -> list[dict[str, Any]]:
        """Walk the record tree looking for citation coordinate blocks."""
        citations: list[dict[str, Any]] = []
        self._walk_for_citations(record, citations)
        return citations

    def _walk_for_citations(
        self, node: Any, out: list[dict[str, Any]]
    ) -> None:
        """Recursively search *node* for citation-shaped sub-arrays."""
        if not isinstance(node, list):
            return
        # A citation block looks like: [source_id_str, start_int, end_int, ...]
        # where source_id is a non-empty string and start/end are ints.
        if (
            len(node) >= 3
            and isinstance(node[0], str)
            and node[0]  # non-empty source id
            and isinstance(node[1], int)
            and isinstance(node[2], int)
        ):
            out.append(
                {
                    "source_id": node[0],
                    "utf16_start": node[1],
                    "utf16_end": node[2],
                }
            )
            return
        for child in node:
            self._walk_for_citations(child, out)

    def _extract_ast_citations(self, ast_root: Any) -> list[dict[str, Any]]:
        """Walk Google's rich-text AST to extract coordinate spans for grounding."""
        spans: list[dict[str, Any]] = []
        seen: set[tuple[int, int]] = set()

        def _walk(node: Any) -> None:
            if not isinstance(node, list):
                return
            if (
                len(node) >= 2
                and isinstance(node[0], int)
                and isinstance(node[1], int)
                and node[1] > node[0] >= 0
            ):
                key = (node[0], node[1])
                if key not in seen:
                    seen.add(key)
                    spans.append({"source_id": "", "utf16_start": node[0], "utf16_end": node[1]})
                return
            for child in node:
                _walk(child)

        _walk(ast_root)
        return spans
