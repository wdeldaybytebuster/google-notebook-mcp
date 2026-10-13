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
