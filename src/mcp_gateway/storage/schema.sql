-- SQLite Schema for Mutation Journal
-- Enforces WAL mode and foreign key integrity.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS mutation_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_key TEXT NOT NULL UNIQUE,
    notebook_id TEXT NOT NULL,
    operation_type TEXT NOT NULL CHECK(operation_type IN ('add_source', 'query_notebook')),
    payload_hash TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'prepared' CHECK(state IN ('prepared', 'sent', 'confirmed', 'rejected', 'unknown')),
    assigned_source_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS mutation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mutation_id INTEGER NOT NULL REFERENCES mutation_journal(id),
    event_type TEXT NOT NULL,
    old_state TEXT,
    new_state TEXT,
    detail TEXT,
    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mutation_journal_request_key ON mutation_journal(request_key);
CREATE INDEX IF NOT EXISTS idx_mutation_events_mutation_id ON mutation_events(mutation_id);
