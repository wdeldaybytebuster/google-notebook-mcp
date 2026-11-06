from __future__ import annotations

from pathlib import Path
import pytest

from mcp_gateway.storage.journal import (
    MutationJournal,
    MutationState,
    OperationType,
    compute_payload_hash,
)


@pytest.fixture
def journal(tmp_path: Path) -> MutationJournal:
    db_path = tmp_path / "journal.db"
    return MutationJournal(db_path)


@pytest.fixture
def secret() -> bytes:
    return b"test_capability_secret_32bytes_!!"


def test_prepare_creates_record(journal: MutationJournal, secret: bytes) -> None:
    args = {"title": "Test Doc", "content": "Hello"}
    record = journal.prepare(
        request_key="req-101",
        notebook_id="nb-001",
        operation_type=OperationType.ADD_SOURCE,
        args=args,
        capability_secret=secret,
    )

    assert record.id > 0
    assert record.request_key == "req-101"
    assert record.notebook_id == "nb-001"
    assert record.operation_type == OperationType.ADD_SOURCE
    assert record.state == MutationState.PREPARED
    assert record.assigned_source_id is None
    assert record.payload_hash == compute_payload_hash(args, secret)


def test_idempotent_prepare(journal: MutationJournal, secret: bytes) -> None:
    args = {"title": "Test Doc", "content": "Hello"}
    rec1 = journal.prepare(
        request_key="req-idempotent",
        notebook_id="nb-001",
        operation_type=OperationType.ADD_SOURCE,
        args=args,
        capability_secret=secret,
    )
    rec2 = journal.prepare(
        request_key="req-idempotent",
        notebook_id="nb-001",
        operation_type=OperationType.ADD_SOURCE,
        args=args,
        capability_secret=secret,
    )

    assert rec1.id == rec2.id
    assert rec1.request_key == rec2.request_key
    assert rec1.state == rec2.state


def test_transition_prepared_to_sent(journal: MutationJournal, secret: bytes) -> None:
    journal.prepare(
        request_key="req-trans-1",
        notebook_id="nb-001",
        operation_type=OperationType.ADD_SOURCE,
        args={"foo": "bar"},
        capability_secret=secret,
    )

    updated = journal.transition("req-trans-1", MutationState.SENT)
    assert updated.state == MutationState.SENT


def test_transition_sent_to_confirmed(journal: MutationJournal, secret: bytes) -> None:
    journal.prepare(
        request_key="req-trans-2",
        notebook_id="nb-001",
        operation_type=OperationType.ADD_SOURCE,
        args={"foo": "bar"},
        capability_secret=secret,
    )
    journal.transition("req-trans-2", MutationState.SENT)

    confirmed = journal.transition(
        "req-trans-2",
        MutationState.CONFIRMED,
        assigned_source_id="src-999",
    )
    assert confirmed.state == MutationState.CONFIRMED
    assert confirmed.assigned_source_id == "src-999"


def test_transition_sent_to_unknown(journal: MutationJournal, secret: bytes) -> None:
    journal.prepare(
        request_key="req-trans-3",
        notebook_id="nb-001",
        operation_type=OperationType.ADD_SOURCE,
        args={"foo": "bar"},
        capability_secret=secret,
    )
    journal.transition("req-trans-3", MutationState.SENT)
    unknown = journal.transition("req-trans-3", MutationState.UNKNOWN)
    assert unknown.state == MutationState.UNKNOWN

    # Must NEVER be automatically replayed: transitioning from UNKNOWN to SENT must raise ValueError.
    with pytest.raises(ValueError, match="Illegal mutation transition"):
        journal.transition("req-trans-3", MutationState.SENT)


def test_sent_cannot_go_to_prepared(journal: MutationJournal, secret: bytes) -> None:
    journal.prepare(
        request_key="req-trans-4",
        notebook_id="nb-001",
        operation_type=OperationType.ADD_SOURCE,
        args={"foo": "bar"},
        capability_secret=secret,
    )
    journal.transition("req-trans-4", MutationState.SENT)

    with pytest.raises(ValueError, match="Illegal mutation transition"):
        journal.transition("req-trans-4", MutationState.PREPARED)


def test_sent_cannot_replay(journal: MutationJournal, secret: bytes) -> None:
    journal.prepare(
        request_key="req-trans-5",
        notebook_id="nb-001",
        operation_type=OperationType.ADD_SOURCE,
        args={"foo": "bar"},
        capability_secret=secret,
    )
    journal.transition("req-trans-5", MutationState.SENT)

    with pytest.raises(ValueError, match="Illegal mutation transition"):
        journal.transition("req-trans-5", MutationState.SENT)


def test_payload_hash_deterministic(secret: bytes) -> None:
    args_a = {"b": 2, "a": 1, "nested": {"y": 20, "x": 10}}
    args_b = {"nested": {"x": 10, "y": 20}, "a": 1, "b": 2}
    hash_a = compute_payload_hash(args_a, secret)
    hash_b = compute_payload_hash(args_b, secret)
    assert hash_a == hash_b


def test_payload_hash_secret_dependent() -> None:
    args = {"test": 123}
    secret_1 = b"secret_one_32_bytes_long_exact!!"
    secret_2 = b"secret_two_32_bytes_long_exact!!"
    assert compute_payload_hash(args, secret_1) != compute_payload_hash(args, secret_2)


def test_sql_injection_in_request_key(journal: MutationJournal, secret: bytes) -> None:
    malicious_key = "'; DROP TABLE mutation_journal; --"
    record = journal.prepare(
        request_key=malicious_key,
        notebook_id="nb-001",
        operation_type=OperationType.ADD_SOURCE,
        args={"safe": True},
        capability_secret=secret,
    )

    assert record.request_key == malicious_key
    fetched = journal.get(malicious_key)
    assert fetched is not None
    assert fetched.id == record.id


def test_list_by_notebook(journal: MutationJournal, secret: bytes) -> None:
    journal.prepare("req-a", "nb-target", OperationType.ADD_SOURCE, {}, secret)
    journal.prepare("req-b", "nb-other", OperationType.ADD_SOURCE, {}, secret)
    journal.prepare("req-c", "nb-target", OperationType.QUERY_NOTEBOOK, {}, secret)

    results = journal.list_by_notebook("nb-target")
    assert len(results) == 2
    assert [r.request_key for r in results] == ["req-a", "req-c"]


def test_dedicated_query_cache_stores_and_replays_without_polluting_mutation_journal(
    journal: MutationJournal,
) -> None:
    import json

    payload_str = json.dumps({
        "answer": "DBSC binds cookies to hardware TPM keys.",
        "citations": [
            {
                "source_id": "src-1",
                "text_snippet": "hardware TPM keys",
                "start_char": 20,
                "end_char": 37,
            }
        ],
    })

    journal.put_query_cache(
        cache_key="req-query-cache-1",
        notebook_id="nb-001",
        query_text="What is DBSC?",
        response_payload=payload_str,
    )

    cached = journal.get_query_cache("req-query-cache-1")
    assert cached is not None
    assert cached["cache_key"] == "req-query-cache-1"
    assert cached["notebook_id"] == "nb-001"
    assert cached["query_text"] == "What is DBSC?"
    assert json.loads(cached["response_payload"])["answer"] == "DBSC binds cookies to hardware TPM keys."
    assert journal.get_query_cache("non-existent-key") is None

    # Verify mutation_journal schema was NOT polluted with response_json
    cols = [
        str(row[1])
        for row in journal._conn.execute("PRAGMA table_info(mutation_journal);").fetchall()
    ]
    assert "response_json" not in cols


@pytest.mark.asyncio
async def test_query_notebook_replays_cached_answer_and_citations(tmp_path: Path) -> None:
    import json
    from unittest.mock import AsyncMock, patch
    from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon

    allowlist_p = tmp_path / "allowlist.json"
    allowlist_p.write_text(
        json.dumps({
            "version": 2,
            "provider_mode": "browser",
            "accounts": [],
            "notebooks": {"nb-q1": {"title": "Query NB", "mode": "READ_ONLY"}},
        }),
        encoding="utf-8",
    )
    daemon = BrokerDaemon(
        BrokerConfig(
            socket_path=str(tmp_path / "q.sock"),
            allowlist_path=allowlist_p,
            journal_db_path=tmp_path / "journal.db",
        )
    )
    await daemon.dispatch({"action": "select_notebook", "notebook_id": "nb-q1"})

    fixtures = json.loads(
        (Path(__file__).parent / "fixtures" / "golden_wire_captures.json").read_text(encoding="utf-8")
    )
    stream_body = (
        json.dumps([[fixtures["non_ascii_citation"]["source_text"]]])
        + "\n"
        + bytes.fromhex(fixtures["non_ascii_citation"]["hex"]).decode("utf-8")
        + "\n[null]\n"
    )

    with patch.object(
        daemon,
        "send_to_companion",
        new=AsyncMock(return_value={"ok": True, "body": stream_body}),
    ) as mock_send:
        first = await daemon.dispatch({
            "action": "query_notebook",
            "notebook_id": "nb-q1",
            "question": "How does DBSC work?",
            "request_key": "req-q-replay-1",
        })
        assert first["ok"] is True
        assert len(first["answer"]) > 0
        assert len(first["citations"]) >= 1
        assert mock_send.call_count == 1

        # Second call with same request_key replays from query_cache without touching companion
        replay = await daemon.dispatch({
            "action": "query_notebook",
            "notebook_id": "nb-q1",
            "question": "How does DBSC work?",
            "request_key": "req-q-replay-1",
        })
        assert replay["ok"] is True
        assert replay["cached"] is True
        assert replay["answer"] == first["answer"]
        assert replay["citations"] == first["citations"]
        assert mock_send.call_count == 1
    daemon.journal.close()


def test_compute_payload_hash_strips_transient_keys(secret: bytes) -> None:
    args1 = {"notebook_id": "nb-1", "question": "What is AI?", "session_token": "token-a", "timeout_seconds": 60}
    args2 = {"notebook_id": "nb-1", "question": "What is AI?", "session_token": "token-b", "timeout_seconds": 120}
    assert compute_payload_hash(args1, secret) == compute_payload_hash(args2, secret)


def test_prepare_detects_request_key_conflict_on_mismatched_payload(journal: MutationJournal, secret: bytes) -> None:
    args1 = {"notebook_id": "nb-1", "question": "Query A"}
    args2 = {"notebook_id": "nb-1", "question": "Query B"}
    journal.prepare("req-key-1", "nb-1", OperationType.QUERY_NOTEBOOK, args1, secret)

    with pytest.raises(ValueError, match="Request key conflict"):
        journal.prepare("req-key-1", "nb-1", OperationType.QUERY_NOTEBOOK, args2, secret)


def test_prepare_detects_request_key_conflict_on_mismatched_notebook(journal: MutationJournal, secret: bytes) -> None:
    args = {"notebook_id": "nb-1", "question": "Query A"}
    journal.prepare("req-key-2", "nb-1", OperationType.QUERY_NOTEBOOK, args, secret)

    with pytest.raises(ValueError, match="Request key conflict"):
        journal.prepare("req-key-2", "nb-2", OperationType.QUERY_NOTEBOOK, args, secret)


def test_prepare_detects_request_key_conflict_on_mismatched_operation(journal: MutationJournal, secret: bytes) -> None:
    args = {"notebook_id": "nb-1", "title": "Note Title"}
    journal.prepare("req-key-3", "nb-1", OperationType.CREATE_NOTE, args, secret)

    with pytest.raises(ValueError, match="Request key conflict"):
        journal.prepare("req-key-3", "nb-1", OperationType.DELETE_NOTE, args, secret)
