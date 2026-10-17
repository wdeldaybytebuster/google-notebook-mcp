"""SQLite-backed mutation journal state machine.

Enforces deterministic mutation states (prepared -> sent -> confirmed/rejected/unknown),
idempotency via deterministic HMAC-SHA256 request keys, and conservative
reconciliation where ambiguous requests are never replayed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import random
import sqlite3
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class MutationState(str, Enum):
    PREPARED = "prepared"
    SENT = "sent"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class OperationType(str, Enum):
    ADD_SOURCE = "add_source"
    QUERY_NOTEBOOK = "query_notebook"
    CREATE_NOTE = "create_note"
    DELETE_NOTE = "delete_note"


_LEGAL_TRANSITIONS: dict[MutationState, set[MutationState]] = {
    MutationState.PREPARED: {MutationState.SENT, MutationState.REJECTED},
    MutationState.SENT: {
        MutationState.CONFIRMED,
        MutationState.REJECTED,
        MutationState.UNKNOWN,
    },
    MutationState.CONFIRMED: set(),
    MutationState.REJECTED: set(),
    MutationState.UNKNOWN: {MutationState.CONFIRMED, MutationState.REJECTED},
}


@dataclass(frozen=True)
class MutationRecord:
    id: int
    request_key: str
    notebook_id: str
    operation_type: OperationType
    payload_hash: str
    state: MutationState
    assigned_source_id: str | None
    created_at: str
    updated_at: str


def compute_payload_hash(args: dict[str, Any], capability_secret: bytes) -> str:
    """Computes a deterministic HMAC-SHA256 digest of canonicalized JSON arguments."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(capability_secret, canonical, hashlib.sha256).hexdigest()


class MutationJournal:
    """Manages transactional persistence and state transitions for notebook mutations."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout = 30000;")
        self._run_migrations()
        self._apply_schema()

    def _apply_schema(self) -> None:
        schema_file = Path(__file__).parent / "schema.sql"
        schema_sql = schema_file.read_text(encoding="utf-8")
        with self._conn:
            self._conn.executescript(schema_sql)

    def _run_migrations(self) -> None:
        """Executes atomic schema migrations guarded by PRAGMA user_version (M-08)."""
        cursor = self._conn.execute("PRAGMA user_version;")
        row = cursor.fetchone()
        current_version = int(row[0]) if row else 0

        if current_version < 2:
            tbl_check = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='mutation_journal';"
            ).fetchone()
            if tbl_check is not None:
                migration_sql = """
                PRAGMA foreign_keys = OFF;
                BEGIN IMMEDIATE TRANSACTION;

                CREATE TABLE IF NOT EXISTS mutation_journal_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_key TEXT NOT NULL UNIQUE,
                    notebook_id TEXT NOT NULL,
                    operation_type TEXT NOT NULL CHECK(operation_type IN ('add_source', 'query_notebook', 'create_note', 'delete_note')),
                    payload_hash TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'prepared' CHECK(state IN ('prepared', 'sent', 'confirmed', 'rejected', 'unknown')),
                    assigned_source_id TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );

                INSERT INTO mutation_journal_v2 (
                    id, request_key, notebook_id, operation_type, payload_hash, state, assigned_source_id, created_at, updated_at
                )
                SELECT id, request_key, notebook_id, operation_type, payload_hash, state, assigned_source_id, created_at, updated_at
                FROM mutation_journal;

                DROP TABLE mutation_journal;
                ALTER TABLE mutation_journal_v2 RENAME TO mutation_journal;

                CREATE UNIQUE INDEX IF NOT EXISTS idx_mutation_journal_request_key ON mutation_journal(request_key);
                PRAGMA user_version = 2;
                COMMIT;
                PRAGMA foreign_keys = ON;
                """
                self._conn.executescript(migration_sql)
            else:
                with self._conn:
                    self._conn.execute("PRAGMA user_version = 2;")

    def close(self) -> None:
        self._conn.close()

    def _row_to_record(self, row: sqlite3.Row) -> MutationRecord:
        return MutationRecord(
            id=int(row["id"]),
            request_key=str(row["request_key"]),
            notebook_id=str(row["notebook_id"]),
            operation_type=OperationType(row["operation_type"]),
            payload_hash=str(row["payload_hash"]),
            state=MutationState(row["state"]),
            assigned_source_id=row["assigned_source_id"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _execute_with_busy_retry(
        self,
        fn: Callable[[], T],
        max_retries: int = 3,
        base_delay: float = 0.05,
    ) -> T:
        """Executes a database write transaction with jittered exponential backoff on busy locks."""
        for attempt in range(max_retries):
            try:
                return fn()
            except sqlite3.OperationalError as exc:
                if ("locked" in str(exc).lower() or "busy" in str(exc).lower()) and attempt < max_retries - 1:
                    sleep_time = random.uniform(base_delay, base_delay * (2 ** attempt))
                    time.sleep(sleep_time)
                else:
                    raise
        raise sqlite3.OperationalError("Database is locked after maximum retries")

    def prepare(
        self,
        request_key: str,
        notebook_id: str,
        operation_type: OperationType,
        args: dict[str, Any],
        capability_secret: bytes,
    ) -> MutationRecord:
        """Prepares a mutation record. Returns existing record if already prepared/sent/confirmed."""
        payload_hash = compute_payload_hash(args, capability_secret)

        def _do_prepare() -> MutationRecord:
            with self._conn:
                cursor = self._conn.execute(
                    "SELECT * FROM mutation_journal WHERE request_key = ?",
                    (request_key,),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    record = self._row_to_record(existing)
                    if record.state == MutationState.REJECTED:
                        raise ValueError(
                            f"Mutation with request_key {request_key!r} was previously rejected."
                        )
                    return record

                cursor = self._conn.execute(
                    """
                    INSERT INTO mutation_journal (
                        request_key, notebook_id, operation_type, payload_hash, state
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        request_key,
                        notebook_id,
                        operation_type.value,
                        payload_hash,
                        MutationState.PREPARED.value,
                    ),
                )
                mutation_id = cursor.lastrowid
                if mutation_id is None:
                    raise RuntimeError("Failed to retrieve lastrowid after journal insert.")

                self._conn.execute(
                    """
                    INSERT INTO mutation_events (
                        mutation_id, event_type, old_state, new_state, detail
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        mutation_id,
                        "prepare",
                        None,
                        MutationState.PREPARED.value,
                        "Mutation prepared",
                    ),
                )

                cursor = self._conn.execute(
                    "SELECT * FROM mutation_journal WHERE id = ?",
                    (mutation_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("Failed to read back newly created mutation record.")
                return self._row_to_record(row)

        return self._execute_with_busy_retry(_do_prepare)

    def transition(
        self,
        request_key: str,
        new_state: MutationState,
        assigned_source_id: str | None = None,
        detail: str | None = None,
    ) -> MutationRecord:
        """Transitions a mutation record to a new state, enforcing legal state machine paths."""
        def _do_transition() -> MutationRecord:
            with self._conn:
                cursor = self._conn.execute(
                    "SELECT * FROM mutation_journal WHERE request_key = ?",
                    (request_key,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(f"Mutation record not found for request_key {request_key!r}")

                current_record = self._row_to_record(row)
                legal_targets = _LEGAL_TRANSITIONS.get(current_record.state, set())

                if new_state not in legal_targets:
                    raise ValueError(
                        f"Illegal mutation transition from {current_record.state.value!r} "
                        f"to {new_state.value!r} for request_key {request_key!r}"
                    )

                updated_source_id = (
                    assigned_source_id
                    if assigned_source_id is not None
                    else current_record.assigned_source_id
                )

                self._conn.execute(
                    """
                    UPDATE mutation_journal
                    SET state = ?,
                        assigned_source_id = ?,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (new_state.value, updated_source_id, current_record.id),
                )

                self._conn.execute(
                    """
                    INSERT INTO mutation_events (
                        mutation_id, event_type, old_state, new_state, detail
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        current_record.id,
                        "transition",
                        current_record.state.value,
                        new_state.value,
                        detail or f"State transitioned to {new_state.value}",
                    ),
                )

                cursor = self._conn.execute(
                    "SELECT * FROM mutation_journal WHERE id = ?",
                    (current_record.id,),
                )
                updated_row = cursor.fetchone()
                if updated_row is None:
                    raise RuntimeError("Failed to read back updated mutation record.")
                return self._row_to_record(updated_row)

        return self._execute_with_busy_retry(_do_transition)

    def get(self, request_key: str) -> MutationRecord | None:
        """Retrieves a mutation record by request_key, or None if absent."""
        cursor = self._conn.execute(
            "SELECT * FROM mutation_journal WHERE request_key = ?",
            (request_key,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_by_notebook(self, notebook_id: str) -> list[MutationRecord]:
        """Lists all mutations recorded for a given notebook ID, ordered by creation."""
        cursor = self._conn.execute(
            "SELECT * FROM mutation_journal WHERE notebook_id = ? ORDER BY id ASC",
            (notebook_id,),
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def reconcile(
        self,
        request_key: str,
        confirmed: bool,
        assigned_source_id: str | None = None,
        detail: str | None = None,
    ) -> MutationRecord:
        """Reconciles an UNKNOWN mutation to CONFIRMED or REJECTED."""
        target_state = MutationState.CONFIRMED if confirmed else MutationState.REJECTED
        return self.transition(
            request_key,
            target_state,
            assigned_source_id=assigned_source_id,
            detail=detail or f"Reconciled to {target_state.value}",
        )
