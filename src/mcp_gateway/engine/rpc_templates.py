"""RPC payload builders and URL constants for Google NotebookLM batchexecute."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

# ---------------------------------------------------------------------------
# URL constants
# ---------------------------------------------------------------------------

BATCHEXECUTE_URL: str = (
    "https://notebook.google.com/_/LabsTailwindUi/data/batchexecute"
)

QUERY_URL: str = (
    "https://notebook.google.com/_/LabsTailwindUi/data/"
    "google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/"
    "GenerateFreeFormStreamed"
)


# ---------------------------------------------------------------------------
# BatchexecuteRequest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BatchexecuteRequest:
    """An immutable descriptor for a single batchexecute RPC call.

    Attributes
    ----------
    rpc_id:
        The Google internal RPC method identifier (e.g. ``'wXbhsf'``).
    params_json:
        JSON-serialised positional parameter array for the RPC.
    notebook_id:
        Optional notebook UUID; included in the URL query parameters when
        the endpoint requires a ``source-path`` context.
    authuser:
        Google account index (0 = primary account).
    """

    rpc_id: str
    params_json: str
    notebook_id: str | None
    authuser: int

    def to_form_body(self, csrf_token: str) -> str:
        """Build the URL-encoded POST body for this batchexecute request.

        The CSRF token is embedded in the form body as the ``at`` parameter.
        It is **never** interpolated into log strings or error messages.

        Parameters
        ----------
        csrf_token:
            The page-resident SNlM0e CSRF token extracted by the extension.

        Returns
        -------
        str
            URL-encoded form body suitable for ``Content-Type:
            application/x-www-form-urlencoded``.
        """
        f_req_value = json.dumps(
            [[[self.rpc_id, self.params_json, None, "generic"]]]
        )
        encoded_f_req = quote_plus(f_req_value)
        encoded_at = quote_plus(csrf_token)
        return f"f.req={encoded_f_req}&at={encoded_at}"


# ---------------------------------------------------------------------------
# Individual RPC payload builders
# ---------------------------------------------------------------------------


def make_list_notebooks_payload(page_size: int = 58) -> str:
    """Build the JSON params for the ``wXbhsf`` list-notebooks RPC.

    Parameters
    ----------
    page_size:
        Maximum number of notebooks to return per page (default 58).

    Returns
    -------
    str
        JSON-serialised positional parameter array.
    """
    payload: list[Any] = [None, 1, None, [page_size]]
    return json.dumps(payload)


def make_get_metadata_payload(notebook_id: str) -> str:
    """Build the JSON params for the ``rLM1Ne`` get-notebook-metadata RPC.

    Parameters
    ----------
    notebook_id:
        The UUID of the target notebook.

    Returns
    -------
    str
        JSON-serialised positional parameter array.
    """
    payload: list[Any] = [
        notebook_id,
        None,
        [2, None, [1], [1, None, None, None, None, None, None, None, None, None, [1, 3]]],
        None,
        0,
        [[None, None, []]],
    ]
    return json.dumps(payload)


def make_add_url_payload(url: str, notebook_id: str) -> str:
    """Build the JSON params for the ``izAoDd`` add-URL-source RPC.

    Parameters
    ----------
    url:
        The URL to ingest as a source.
    notebook_id:
        The UUID of the target notebook.

    Returns
    -------
    str
        JSON-serialised positional parameter array.
    """
    payload: list[Any] = [
        [[[None, None, [url], None, None, 1]]],
        notebook_id,
        [58],
    ]
    return json.dumps(payload)


def make_add_text_payload(title: str, content: str, notebook_id: str = "") -> str:
    """Build the JSON params for the add-pasted-text RPC.

    Parameters
    ----------
    title:
        Display title for the pasted text source.
    content:
        The text content to ingest.
    notebook_id:
        Optional target notebook UUID.

    Returns
    -------
    str
        JSON-serialised positional parameter array.
    """
    if notebook_id:
        payload: list[Any] = [
            notebook_id,
            content,
            [1, None, None, None, None, None, 1],
            None,
            title,
            None,
            [2, None, [1], [1, None, None, None, None, None, None, None, None, None, [1, 3]]],
        ]
    else:
        payload = [None, [title, content], None, 2]
    return json.dumps(payload)


def make_add_drive_payload(
    doc_id: str, mime_type: str, title: str, notebook_id: str
) -> str:
    """Build the JSON params for the ``izAoDd`` add-Google-Drive-source RPC.

    Parameters
    ----------
    doc_id:
        The Google Drive file ID.
    mime_type:
        MIME type of the Drive document.
    title:
        Display title for the source.
    notebook_id:
        The UUID of the target notebook.

    Returns
    -------
    str
        JSON-serialised positional parameter array.
    """
    payload: list[Any] = [
        [[[[doc_id, mime_type, 1, title]]]],
        notebook_id,
        [58],
    ]
    return json.dumps(payload)


def make_register_upload_payload(filename: str, notebook_id: str) -> str:
    """Build the JSON params for the ``o4cbdc`` Scotty upload-intent RPC.

    Parameters
    ----------
    filename:
        The local filename being uploaded.
    notebook_id:
        The UUID of the target notebook.

    Returns
    -------
    str
        JSON-serialised positional parameter array.
    """
    payload: list[Any] = [[[filename]], notebook_id, [58]]
    return json.dumps(payload)


def make_delete_source_payload(source_id: str) -> str:
    """Build the JSON params for the source-deletion RPC.

    Parameters
    ----------
    source_id:
        The opaque source identifier to delete.

    Returns
    -------
    str
        JSON-serialised positional parameter array.
    """
    payload: list[Any] = [[source_id]]
    return json.dumps(payload)


def make_create_note_payload(title: str, content: str, notebook_id: str) -> str:
    """Build the JSON params for the ``CYK0Xb`` create-note RPC.

    Parameters
    ----------
    title:
        Display title for the note.
    content:
        The text content of the note.
    notebook_id:
        The UUID of the target notebook.

    Returns
    -------
    str
        JSON-serialised positional parameter array.
    """
    payload: list[Any] = [notebook_id, title, content]
    return json.dumps(payload)


def make_delete_note_payload(note_id: str, notebook_id: str = "") -> str:
    """Build the JSON params for the ``tGMBJ`` delete-note RPC.

    Parameters
    ----------
    note_id:
        The UUID of the note to delete.
    notebook_id:
        Optional target notebook UUID.

    Returns
    -------
    str
        JSON-serialised positional parameter array.
    """
    if notebook_id:
        payload: list[Any] = [[[note_id]], notebook_id, [58]]
    else:
        payload = [[[note_id]], [58]]
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# GenerateFreeFormStreamed query params builder
# ---------------------------------------------------------------------------


def _nest_source_ids(source_ids: list[str], depth: int) -> list[Any]:
    """Recursively wrap source IDs in nested lists to the required depth."""
    if depth == 0:
        return list(source_ids)
    return [_nest_source_ids([sid], depth - 1) for sid in source_ids]


def make_query_params(
    sources: list[str],
    question: str,
    notebook_id: str,
    session_id: str | None = None,
    message_id: str | None = None,
    history: list[tuple[str, str]] | None = None,
) -> str:
    """Build the JSON params for the ``GenerateFreeFormStreamed`` query RPC.

    Constructs the full nested parameter array required by the streaming
    query endpoint, including triple-nested source IDs, newest-first
    conversation history pairs, and required context options.

    Parameters
    ----------
    sources:
        List of source IDs to restrict the query to.  Pass an empty list to
        query all sources.
    question:
        The natural-language question to ask.
    notebook_id:
        The UUID of the target notebook.
    session_id:
        The server-assigned conversation session UUID from a prior turn
        (``hPTbtc``), or ``None`` for a new conversation.
    message_id:
        Optional client-generated UUID.
    history:
        Prior conversation turns as ``(answer, query)`` pairs in
        **newest-first** order.

    Returns
    -------
    str
        JSON-serialised parameter array for the ``f.req`` form field.
    """
    # Triple-nested source IDs: [[[[source_id]]]] per source.
    nested_sources = _nest_source_ids(sources, depth=2)

    # Conversation history: alternating [answer, null, 2], [query, null, 1]
    # newest-first.
    history_entries: list[Any] = []
    if history:
        for answer, query in history:
            history_entries.append([answer, None, 2])
            history_entries.append([query, None, 1])

    params: list[Any] = [
        nested_sources,           # [0]  sources: triple-nested
        question,                 # [1]  user query string  (index 48 in wire)
        history_entries,          # [2]  conversation history (must be list [], not None)
        [2, None, [1], [1, None, None, None, None, None, None, None, None, None, [1, 3]]],  # [3]  context options
        session_id,               # [4]  server conversation UUID or null
        message_id,               # [5]  client message UUID
        None,                     # [6]  reserved
        notebook_id,              # [7]  target notebook UUID
        1,                        # [8]  origin=QUERY_ORIGIN_CHAT_TEXT_BOX
    ]
    return json.dumps(params)
