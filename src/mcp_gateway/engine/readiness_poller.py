"""Asynchronous source-ingestion readiness poller with Full Jitter Backoff."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from enum import IntEnum
from typing import Any


class SourceStatus(IntEnum):
    """Ingestion state for a NotebookLM source.

    Values are the integers returned by the ``rLM1Ne`` metadata RPC.
    """

    UNKNOWN = -1
    PROCESSING = 1
    READY = 2
    ERROR = 3
    FAILED = 3
    PREPARING = 5


def parse_source_status(source_row: list[Any]) -> SourceStatus:
    """Extract a :class:`SourceStatus` from a raw source-row array.

    The status integer appears at index 4 of the source row inside the
    ``rLM1Ne`` response, but the exact position has varied across API
    versions.  This function checks index 4 first, then scans indices 3
    and 5 to tolerate minor schema shifts.

    Parameters
    ----------
    source_row:
        A raw source row list from the ``rLM1Ne`` metadata response.

    Returns
    -------
    SourceStatus
        The detected status, or :attr:`SourceStatus.UNKNOWN` if no
        recognisable status value is found at any of the scanned indices.
    """
    _status_values = {s.value for s in SourceStatus if s != SourceStatus.UNKNOWN}
    for idx in (4, 3, 5):
        if idx >= len(source_row):
            continue
        candidate = source_row[idx]
        if isinstance(candidate, int) and candidate in _status_values:
            try:
                return SourceStatus(candidate)
            except ValueError:
                continue
    return SourceStatus.UNKNOWN


async def poll_until_ready(
    notebook_id: str,
    source_id: str,
    fetch_metadata_fn: Callable[[str], Awaitable[list[Any]]],
    max_timeout: float = 300.0,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
) -> SourceStatus:
    """Poll until *source_id* reaches :attr:`SourceStatus.READY`.

    Implements **Full Jitter Exponential Backoff**:

    .. code-block:: text

        delay = random.uniform(0, min(base_delay * 2**attempt, max_delay))

    Parameters
    ----------
    notebook_id:
        UUID of the notebook that owns the source.
    source_id:
        Opaque source identifier to watch.
    fetch_metadata_fn:
        Async callable that accepts *notebook_id* and returns the raw list
        of source rows from the ``rLM1Ne`` RPC response.
    max_timeout:
        Hard ceiling in seconds before a :class:`TimeoutError` is raised
        (default 300 s).
    base_delay:
        Base delay in seconds for the backoff formula (default 2.0 s).
    max_delay:
        Maximum cap on the computed delay (default 30.0 s).

    Returns
    -------
    SourceStatus
        :attr:`SourceStatus.READY` on success, or
        :attr:`SourceStatus.ERROR` if the backend reports an error.

    Raises
    ------
    TimeoutError
        If the source has not reached READY within *max_timeout* seconds.
    """
    deadline = time.monotonic() + max_timeout
    attempt = 0

    while True:
        source_rows: list[Any] = await fetch_metadata_fn(notebook_id)

        # Find the row that matches our source_id.
        status = SourceStatus.UNKNOWN
        for row in source_rows:
            if isinstance(row, dict):
                if str(row.get("id")) == source_id:
                    if "status_code" in row:
                        try:
                            status = SourceStatus(int(row["status_code"]))
                        except ValueError:
                            status = SourceStatus.UNKNOWN
                    elif "status" in row:
                        try:
                            status = SourceStatus[str(row["status"])]
                        except KeyError:
                            status = SourceStatus.UNKNOWN
                    elif "raw_row" in row and isinstance(row["raw_row"], list):
                        status = parse_source_status(row["raw_row"])
                    break
            elif isinstance(row, list):
                if row and str(row[0]) == source_id:
                    status = parse_source_status(row)
                    break

        if status == SourceStatus.READY:
            return SourceStatus.READY
        if status in (SourceStatus.ERROR, SourceStatus.FAILED):
            return SourceStatus.ERROR
        # UNKNOWN keeps polling — do not raise.

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Source '{source_id}' did not reach READY within {max_timeout}s "
                f"(last status: {status!r})"
            )

        # Full Jitter Exponential Backoff.
        cap = min(base_delay * (2**attempt), max_delay)
        delay = random.uniform(0, cap)
        sleep_time = min(delay, remaining)
        await asyncio.sleep(sleep_time)
        attempt += 1
