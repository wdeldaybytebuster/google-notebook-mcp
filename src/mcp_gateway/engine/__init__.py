"""Wire protocol engine for Google NotebookLM batchexecute and streaming RPCs."""

from mcp_gateway.engine.coordinate import (
    CitationSpan,
    normalize_citation,
    utf16_slice,
    utf16_to_unicode_offset,
)
from mcp_gateway.engine.readiness_poller import (
    SourceStatus,
    poll_until_ready,
)
from mcp_gateway.engine.rpc_templates import (
    BATCHEXECUTE_URL,
    QUERY_URL,
    BatchexecuteRequest,
    make_query_params,
)
from mcp_gateway.engine.stream_decoder import (
    BatchexecuteStreamDecoder,
    GenerateFreeFormStreamParser,
    StreamDecodeError,
)

__all__ = [
    # coordinate
    "CitationSpan",
    "normalize_citation",
    "utf16_slice",
    "utf16_to_unicode_offset",
    # readiness_poller
    "SourceStatus",
    "poll_until_ready",
    # rpc_templates
    "BATCHEXECUTE_URL",
    "QUERY_URL",
    "BatchexecuteRequest",
    "make_query_params",
    # stream_decoder
    "BatchexecuteStreamDecoder",
    "GenerateFreeFormStreamParser",
    "StreamDecodeError",
]
