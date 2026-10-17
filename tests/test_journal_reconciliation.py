from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
import pytest

from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon
from mcp_gateway.schemas.error import (
    MUTATION_UNKNOWN,
    REQUEST_KEY_CONFLICT,
)
from mcp_gateway.storage.journal import (
    MutationJournal,
    MutationRecord,
    MutationState,
    OperationType,
)


@pytest.fixture
def allowlist_file(tmp_path: Path) -> Path:
    p = tmp_path / "allowlist.json"
    p.write_text(
        '{"version": 1, "provider_mode": "browser", "accounts": [], "notebooks": ["nb-recon-001"]}',
        encoding="utf-8",
    )
    return p


from mcp_gateway.broker.session import SessionState


@pytest.fixture
def broker(tmp_path: Path, allowlist_file: Path) -> BrokerDaemon:
    cfg = BrokerConfig(
        socket_path=str(tmp_path / "recon_test.sock"),
        allowlist_path=allowlist_file,
        journal_db_path=tmp_path / "journal_recon.db",
    )
    b = BrokerDaemon(cfg)
    b.session_lock.locked_notebook_id = "nb-recon-001"
    b.session_lock.state = SessionState.ACTIVE_DISPATCH
    return b


@pytest.mark.asyncio
async def test_mutation_freeze_in_unknown_on_disconnect(broker: BrokerDaemon) -> None:
    # When companion is not connected, dispatching add_source fails with AUTH_REQUIRED or timeout.
    # To simulate IPC timeout during transmission after SENT:
    key = "idem-timeout-1"
    nb_id = "nb-recon-001"
    command = {
        "action": "add_source",
        "notebook_id": nb_id,
        "idempotency_key": key,
        "source": {"type": "text", "title": "Timeout Doc", "content": "Body text"},
    }

    # Prepare and transition to SENT
    broker.journal.prepare(
        request_key=key,
        notebook_id=nb_id,
        operation_type=OperationType.ADD_SOURCE,
        args=command,
        capability_secret=broker.config.capability_secret,
    )
    broker.journal.transition(key, MutationState.SENT)

    record_sent = broker.journal.get(key)
    assert record_sent is not None
    assert record_sent.state == MutationState.SENT

    # Simulate timeout / ambiguous disconnect: state freezes in UNKNOWN
    broker.journal.transition(key, MutationState.UNKNOWN, detail="Socket disconnected mid-flight")
    record_unknown = broker.journal.get(key)
    assert record_unknown is not None
    assert record_unknown.state == MutationState.UNKNOWN


@pytest.mark.asyncio
async def test_auto_replay_blocked_with_request_key_conflict(broker: BrokerDaemon) -> None:
    key = "idem-block-replay-2"
    nb_id = "nb-recon-001"
    command = {
        "action": "add_source",
        "notebook_id": nb_id,
        "idempotency_key": key,
        "source": {"type": "text", "title": "Replay Doc", "content": "Body text"},
    }

    # Set up mutation record in UNKNOWN state
    broker.journal.prepare(
        request_key=key,
        notebook_id=nb_id,
        operation_type=OperationType.ADD_SOURCE,
        args=command,
        capability_secret=broker.config.capability_secret,
    )
    broker.journal.transition(key, MutationState.SENT)
    broker.journal.transition(key, MutationState.UNKNOWN)

    # Attempt to dispatch identical mutation again
    result = await broker.dispatch(command)
    assert result["ok"] is False
    assert result["error"]["code"] == REQUEST_KEY_CONFLICT
    assert "reconciliation required" in result["error"]["message"].lower()

    # Verify journal state remains frozen in UNKNOWN
    record = broker.journal.get(key)
    assert record is not None
    assert record.state == MutationState.UNKNOWN


@pytest.mark.asyncio
async def test_active_reconciliation_flow(broker: BrokerDaemon) -> None:
    key = "idem-reconcile-3"
    nb_id = "nb-recon-001"
    command = {
        "action": "add_source",
        "notebook_id": nb_id,
        "idempotency_key": key,
        "source": {"type": "text", "title": "Reconciled Doc", "content": "Sample content"},
    }

    # Mutation started, transitioned to SENT, then timed out into UNKNOWN
    broker.journal.prepare(
        request_key=key,
        notebook_id=nb_id,
        operation_type=OperationType.ADD_SOURCE,
        args=command,
        capability_secret=broker.config.capability_secret,
    )
    broker.journal.transition(key, MutationState.SENT)
    broker.journal.transition(key, MutationState.UNKNOWN, detail="Gateway timeout awaiting ACK")

    # Simulate active reconciliation inspection via rLM1Ne metadata:
    # Server inspection discovers that the source was successfully created on upstream
    server_discovered_source_id = "src-recovered-7788"

    # Reconcile mutation
    reconciled = broker.journal.reconcile(
        request_key=key,
        confirmed=True,
        assigned_source_id=server_discovered_source_id,
        detail="Reconciled via active rLM1Ne metadata inspection",
    )
    assert reconciled.state == MutationState.CONFIRMED
    assert reconciled.assigned_source_id == server_discovered_source_id

    # Calling add_source again now returns the cached confirmed result without duplicate mutation
    replay_res = await broker.dispatch(command)
    assert replay_res["ok"] is True
    assert replay_res["source_id"] == server_discovered_source_id
    assert replay_res.get("cached") is True
