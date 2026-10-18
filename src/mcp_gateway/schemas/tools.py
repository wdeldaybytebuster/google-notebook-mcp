"""Closed JSON Schema definitions and metadata for the 5 MCP tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LIST_NOTEBOOKS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "page_size": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "default": 20,
        },
        "cursor": {
            "type": "string",
        },
    },
}

GET_NOTEBOOK_METADATA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["notebook_id"],
    "properties": {
        "notebook_id": {
            "type": "string",
            "minLength": 1,
        },
    },
}

LIST_SOURCES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["notebook_id"],
    "properties": {
        "notebook_id": {
            "type": "string",
        },
        "page_size": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
        },
        "cursor": {
            "type": "string",
        },
    },
}

QUERY_NOTEBOOK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["notebook_id", "question", "request_key"],
    "properties": {
        "notebook_id": {
            "type": "string",
        },
        "question": {
            "type": "string",
            "minLength": 1,
            "maxLength": 2000,
        },
        "request_key": {
            "type": "string",
            "minLength": 1,
        },
        "source_ids": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
        "timeout_seconds": {
            "type": "integer",
            "minimum": 10,
            "maximum": 900,
            "default": 600,
        },
    },
}

ADD_SOURCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["notebook_id", "idempotency_key", "source"],
    "properties": {
        "notebook_id": {
            "type": "string",
        },
        "idempotency_key": {
            "type": "string",
        },
        "wait_until_ready": {
            "type": "boolean",
            "default": False,
        },
        "source": {
            "type": "object",
            "additionalProperties": False,
            "required": ["type"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["text", "url", "youtube", "drive", "file"],
                },
                "url": {
                    "type": "string",
                },
                "title": {
                    "type": "string",
                },
                "content": {
                    "type": "string",
                },
                "doc_id": {
                    "type": "string",
                },
                "mime_type": {
                    "type": "string",
                },
            },
        },
    },
}

TOOL_ANNOTATIONS: dict[str, dict[str, bool]] = {
    "list_notebooks": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "get_notebook_metadata": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "list_sources": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "query_notebook": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    },
    "add_source": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    },
    "select_notebook": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "create_note": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    },
    "list_notes": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "delete_note": {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
    },
}

CREATE_NOTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["notebook_id", "content", "idempotency_key"],
    "properties": {
        "notebook_id": {
            "type": "string",
            "minLength": 1,
        },
        "title": {
            "type": "string",
            "maxLength": 255,
        },
        "content": {
            "type": "string",
            "minLength": 1,
        },
        "idempotency_key": {
            "type": "string",
            "minLength": 1,
        },
    },
}

LIST_NOTES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["notebook_id"],
    "properties": {
        "notebook_id": {
            "type": "string",
            "minLength": 1,
        },
        "page_size": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "default": 20,
        },
        "cursor": {
            "type": "string",
        },
    },
}

DELETE_NOTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["notebook_id", "note_id", "idempotency_key"],
    "properties": {
        "notebook_id": {
            "type": "string",
            "minLength": 1,
        },
        "note_id": {
            "type": "string",
            "minLength": 1,
        },
        "idempotency_key": {
            "type": "string",
            "minLength": 1,
        },
    },
}

SELECT_NOTEBOOK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "notebook_id": {
            "type": "string",
            "minLength": 1,
        },
        "title": {
            "type": "string",
            "minLength": 1,
        },
        "save_for_project": {
            "type": "boolean",
            "default": True,
            "description": "If true, saves this selection to .notebook_mcp.json in the current project root so future chats remember it.",
        },
    },
    "anyOf": [
        {"required": ["notebook_id"]},
        {"required": ["title"]},
    ],
}

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "list_notebooks": LIST_NOTEBOOKS_SCHEMA,
    "select_notebook": SELECT_NOTEBOOK_SCHEMA,
    "get_notebook_metadata": GET_NOTEBOOK_METADATA_SCHEMA,
    "list_sources": LIST_SOURCES_SCHEMA,
    "query_notebook": QUERY_NOTEBOOK_SCHEMA,
    "add_source": ADD_SOURCE_SCHEMA,
    "create_note": CREATE_NOTE_SCHEMA,
    "list_notes": LIST_NOTES_SCHEMA,
    "delete_note": DELETE_NOTE_SCHEMA,
}


def validate_tool_args(tool_name: str, args: dict[str, Any]) -> str | None:
    """Validates arguments against the closed JSON Schema for the specified tool.

    Returns None if valid, or an error message string if validation fails.
    """
    schema = TOOL_SCHEMAS.get(tool_name)
    if schema is None:
        return f"Unknown tool name: {tool_name!r}."
    try:
        import jsonschema  # type: ignore[import-untyped]

        jsonschema.validate(instance=args, schema=schema)
        return None
    except jsonschema.ValidationError as exc:
        return f"Schema validation failed for {tool_name}: {exc.message}"


# ---------------------------------------------------------------------------
# Pydantic v2 Closed Schemas (extra="forbid")
# ---------------------------------------------------------------------------


class ListNotebooksInput(BaseModel):
    """Pydantic schema for list_notebooks."""

    model_config = ConfigDict(extra="forbid")

    page_size: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None


class GetNotebookMetadataInput(BaseModel):
    """Pydantic schema for get_notebook_metadata."""

    model_config = ConfigDict(extra="forbid")

    notebook_id: str = Field(min_length=1)


class ListSourcesInput(BaseModel):
    """Pydantic schema for list_sources."""

    model_config = ConfigDict(extra="forbid")

    notebook_id: str = Field(min_length=1)
    page_size: int | None = Field(default=None, ge=1, le=100)
    cursor: str | None = None


class QueryNotebookInput(BaseModel):
    """Pydantic schema for query_notebook."""

    model_config = ConfigDict(extra="forbid")

    notebook_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=2000)
    request_key: str = Field(min_length=1)
    source_ids: list[str] | None = None
    timeout_seconds: int = Field(default=600, ge=10, le=900)


class SourceSpec(BaseModel):
    """Polymorphic source specification."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["text", "url", "youtube", "drive", "file"]
    url: str | None = None
    title: str | None = None
    content: str | None = None
    doc_id: str | None = None
    mime_type: str | None = None


class AddSourceInput(BaseModel):
    """Pydantic schema for add_source."""

    model_config = ConfigDict(extra="forbid")

    notebook_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    source: SourceSpec
    wait_until_ready: bool = False


class SelectNotebookInput(BaseModel):
    """Pydantic schema for select_notebook."""

    model_config = ConfigDict(extra="forbid")

    notebook_id: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)
    save_for_project: bool = Field(default=True)

    @model_validator(mode="after")
    def check_at_least_one_identifier(self) -> SelectNotebookInput:
        if not self.notebook_id and not self.title:
            raise ValueError("Must provide either 'notebook_id' or 'title'.")
        return self


class CreateNoteInput(BaseModel):
    """Pydantic schema for create_note."""

    model_config = ConfigDict(extra="forbid")

    notebook_id: str = Field(min_length=1)
    title: str = Field(default="Untitled Note", min_length=1, max_length=255)
    content: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


class ListNotesInput(BaseModel):
    """Pydantic schema for list_notes."""

    model_config = ConfigDict(extra="forbid")

    notebook_id: str = Field(min_length=1)
    page_size: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None


class DeleteNoteInput(BaseModel):
    """Pydantic schema for delete_note."""

    model_config = ConfigDict(extra="forbid")

    notebook_id: str = Field(min_length=1)
    note_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


PYDANTIC_TOOL_MODELS: dict[str, type[BaseModel]] = {
    "list_notebooks": ListNotebooksInput,
    "get_notebook_metadata": GetNotebookMetadataInput,
    "list_sources": ListSourcesInput,
    "query_notebook": QueryNotebookInput,
    "add_source": AddSourceInput,
    "select_notebook": SelectNotebookInput,
    "create_note": CreateNoteInput,
    "list_notes": ListNotesInput,
    "delete_note": DeleteNoteInput,
}

