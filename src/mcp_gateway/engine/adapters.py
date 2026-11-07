"""Decoupled Dynamic Schema and Wire Adapter Engine for Google Notebook MCP.

Implements:
- INVARIANT 5: DOM Selector Prototype Pollution Sanitization
- INVARIANT 6: Immutable Snapshot Execution via frozen CompiledWireSpec
- INVARIANT 7: Triple Fallback Resilience (Dynamic Active -> LKG -> Bundled Default)
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import re
import threading
from typing import Any

import jsonschema  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Invariant 5: Strict alphanumeric + underscore/dollar identifier pattern
SAFE_IDENTIFIER_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_$]{1,64}$")
FORBIDDEN_IDENTIFIERS: frozenset[str] = frozenset({"__proto__", "constructor", "prototype"})

DEFAULT_ADAPTER_DIR: Path = (
    Path.home() / ".local" / "share" / "notebooklm-mcp-bridge" / "adapters"
)


class SchemaValidationError(ValueError):
    """Raised when a wire spec fails structural schema or security validation."""


@dataclass(frozen=True)
class CompiledWireSpec:
    """An immutable, frozen snapshot of the active wire specification.

    Enforces INVARIANT 6: In-flight operations hold a reference to this snapshot,
    completely decoupling active RPC execution from concurrent hot-reloads.
    """

    schema_version: str
    min_broker_version: str
    spec_hash: str
    rpc_descriptors: dict[str, Any]
    dom_selectors: dict[str, str]
    raw_spec: dict[str, Any]

    def get_rpc_id(self, rpc_name: str, default: str = "") -> str:
        """Resolves the upstream batchexecute method ID for an RPC operation."""
        desc = self.rpc_descriptors.get(rpc_name)
        if isinstance(desc, dict) and "method_id" in desc:
            return str(desc["method_id"])
        return default

    def get_row_index(self, rpc_name: str, row_name: str, default: int = 0) -> int:
        """Resolves the positional array row index for nested response fields."""
        desc = self.rpc_descriptors.get(rpc_name)
        if isinstance(desc, dict) and "rows" in desc:
            rows = desc["rows"]
            if isinstance(rows, dict) and row_name in rows:
                row_info = rows[row_name]
                if isinstance(row_info, dict) and "row_index" in row_info:
                    return int(row_info["row_index"])
        return default

    def get_dom_selector(self, selector_name: str, default: str = "") -> str:
        """Resolves the safe DOM extraction target variable."""
        return self.dom_selectors.get(selector_name, default)


def validate_wire_spec(spec: dict[str, Any], schema_path: Path | None = None) -> None:
    """Validates a wire specification against schema and security invariants.

    Enforces:
    - JSON Schema compliance (additionalProperties: false)
    - INVARIANT 5: Prohibits prototype pollution keys and invalid selector patterns.
    """
    if schema_path is None:
        schema_path = Path(__file__).parent / "wire_spec.schema.json"

    if not schema_path.exists():
        raise SchemaValidationError(f"Wire spec schema not found: {schema_path}")

    schema_data = json.loads(schema_path.read_text(encoding="utf-8"))

    try:
        jsonschema.validate(instance=spec, schema=schema_data)
    except jsonschema.ValidationError as err:
        raise SchemaValidationError(f"Wire spec failed schema validation: {err.message}") from err

    # INVARIANT 5: Explicit prototype pollution & DOM selector sanitization
    dom_selectors = spec.get("dom_selectors", {})
    if not isinstance(dom_selectors, dict):
        raise SchemaValidationError("dom_selectors must be a dictionary")

    for key, value in dom_selectors.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise SchemaValidationError(f"dom_selectors key and value must be strings: {key}={value}")

        if key in FORBIDDEN_IDENTIFIERS or value in FORBIDDEN_IDENTIFIERS:
            raise SchemaValidationError(
                f"Forbidden prototype pollution identifier in dom_selectors: {key}={value}"
            )

        if not SAFE_IDENTIFIER_PATTERN.match(key):
            raise SchemaValidationError(f"Invalid DOM selector key: {key}")

        if not SAFE_IDENTIFIER_PATTERN.match(value):
            raise SchemaValidationError(f"Invalid DOM selector value: {value}")


def compile_wire_spec(raw_json_str: str, schema_path: Path | None = None) -> CompiledWireSpec:
    """Parses, validates, and compiles raw JSON string into a CompiledWireSpec."""
    spec_hash = hashlib.sha256(raw_json_str.encode("utf-8")).hexdigest()
    try:
        spec_dict = json.loads(raw_json_str)
    except json.JSONDecodeError as err:
        raise SchemaValidationError(f"Malformed JSON in wire spec: {err}") from err

    validate_wire_spec(spec_dict, schema_path=schema_path)

    return CompiledWireSpec(
        schema_version=str(spec_dict["$schema_version"]),
        min_broker_version=str(spec_dict["min_broker_version"]),
        spec_hash=spec_hash,
        rpc_descriptors=spec_dict["rpc_descriptors"],
        dom_selectors=spec_dict["dom_selectors"],
        raw_spec=spec_dict,
    )


class AdapterConfig:
    """Singleton managing active wire adapter specifications with triple fallback.

    Enforces INVARIANT 7:
    Triple Fallback: Dynamic Active -> Last Known Good (LKG) -> Package-Bundled Default.
    """

    _instance: AdapterConfig | None = None
    _singleton_lock: threading.Lock = threading.Lock()

    def __init__(self, adapter_dir: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._adapter_dir = adapter_dir or DEFAULT_ADAPTER_DIR
        self._schema_path = Path(__file__).parent / "wire_spec.schema.json"
        self._bundled_spec_path = Path(__file__).parent / "wire_spec.v4.json"
        self._current_spec: CompiledWireSpec = self._resolve_triple_fallback()

    @classmethod
    def get_instance(cls, adapter_dir: Path | None = None) -> AdapterConfig:
        """Retrieves or initializes the process-wide AdapterConfig singleton."""
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls(adapter_dir=adapter_dir)
            elif adapter_dir is not None and cls._instance._adapter_dir != adapter_dir:
                cls._instance.set_adapter_dir(adapter_dir)
            return cls._instance

    @classmethod
    def get_current_spec(cls) -> CompiledWireSpec:
        """Direct accessor to get the current snapshot from the singleton."""
        return cls.get_instance().get_spec()

    def set_adapter_dir(self, adapter_dir: Path) -> None:
        """Updates the adapter directory and triggers fallback resolution."""
        with self._lock:
            self._adapter_dir = adapter_dir
            self._current_spec = self._resolve_triple_fallback()

    def get_spec(self) -> CompiledWireSpec:
        """Returns the current immutable CompiledWireSpec snapshot."""
        with self._lock:
            return self._current_spec

    @property
    def dynamic_spec_path(self) -> Path:
        return self._adapter_dir / "wire_spec.v4.json"

    @property
    def lkg_spec_path(self) -> Path:
        return self._adapter_dir / "wire_spec.v4.lkg.json"

    @property
    def bundled_spec_path(self) -> Path:
        return self._bundled_spec_path

    def _resolve_triple_fallback(self) -> CompiledWireSpec:
        """Resolves spec following Dynamic Active -> LKG -> Bundled Default.

        Guarantees that a missing, corrupt, or invalid dynamic or LKG file
        will cleanly fall back to the bundled default without unhandled exceptions.
        """
        # Level 1: Dynamic Active
        if self.dynamic_spec_path.exists():
            try:
                raw_text = self.dynamic_spec_path.read_text(encoding="utf-8")
                spec = compile_wire_spec(raw_text, schema_path=self._schema_path)
                logger.info("Loaded active dynamic wire spec from %s", self.dynamic_spec_path)
                return spec
            except Exception as exc:
                logger.warning("Failed loading dynamic spec (%s), falling back to LKG: %s", self.dynamic_spec_path, exc)

        # Level 2: Last Known Good (LKG)
        if self.lkg_spec_path.exists():
            try:
                raw_text = self.lkg_spec_path.read_text(encoding="utf-8")
                spec = compile_wire_spec(raw_text, schema_path=self._schema_path)
                logger.info("Loaded LKG wire spec from %s", self.lkg_spec_path)
                return spec
            except Exception as exc:
                logger.warning("Failed loading LKG spec (%s), falling back to bundled default: %s", self.lkg_spec_path, exc)

        # Level 3: Package-Bundled Static Default
        try:
            raw_text = self._bundled_spec_path.read_text(encoding="utf-8")
            spec = compile_wire_spec(raw_text, schema_path=self._schema_path)
            logger.info("Loaded bundled default wire spec from %s", self._bundled_spec_path)
            return spec
        except Exception as exc:
            logger.critical("Bundled wire spec corrupted! %s", exc)
            raise RuntimeError(f"Package bundled wire spec is corrupted: {exc}") from exc

    def reload(self, spec_path: Path | None = None) -> CompiledWireSpec:
        """Thread-safely reloads the wire spec.

        If spec_path is provided, loads and validates from that path.
        Otherwise re-resolves the triple fallback.
        """
        with self._lock:
            if spec_path is not None:
                raw_text = spec_path.read_text(encoding="utf-8")
                new_spec = compile_wire_spec(raw_text, schema_path=self._schema_path)
                self._current_spec = new_spec
            else:
                self._current_spec = self._resolve_triple_fallback()
            return self._current_spec

    def reload_from_bytes(self, raw_bytes: bytes) -> CompiledWireSpec:
        """Compiles from raw bytes and swaps current spec."""
        with self._lock:
            raw_text = raw_bytes.decode("utf-8")
            new_spec = compile_wire_spec(raw_text, schema_path=self._schema_path)
            self._current_spec = new_spec
            return self._current_spec

    def reset_to_bundled(self) -> CompiledWireSpec:
        """Resets active spec back to the bundled package default."""
        with self._lock:
            raw_text = self._bundled_spec_path.read_text(encoding="utf-8")
            self._current_spec = compile_wire_spec(raw_text, schema_path=self._schema_path)
            return self._current_spec
