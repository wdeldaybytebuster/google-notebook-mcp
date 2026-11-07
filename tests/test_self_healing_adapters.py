"""Comprehensive tests for Phase 11: Zero-Friction Upstream Drift & Self-Healing Auto-Update Engine.

Covers:
- INVARIANT 1: Cryptographic Signature Pre-Check (Ed25519 on raw bytes before JSON parse)
- INVARIANT 2: Air-Gapped Vault Immutability (~/.config/notebooklm-mcp-bridge/ read-only)
- INVARIANT 3: Strict Path Traversal & Symlink Guard
- INVARIANT 4: State Persistence Across Restarts (1h cooldown, max 3 checks / 24h, quarantined hashes)
- INVARIANT 5: Prototype Pollution & DOM Selector Sanitization
- INVARIANT 6: Immutable Snapshot Execution via CompiledWireSpec
- INVARIANT 7: Triple Fallback Resilience (Dynamic Active -> LKG -> Bundled Default)
- INVARIANT 8: Synthetic Canary Validation & Atomic LKG Rollback Engine
- INVARIANT 9: Strict Test Scope Guard (Only Test Notebook 3e3c08b5-7e5c-4189-9923-81933a256f54)
"""

from __future__ import annotations

import json
from pathlib import Path
import stat
from typing import Any
import pytest

from cryptography.hazmat.primitives.asymmetric import ed25519

from mcp_gateway.broker.allowlist import is_notebook_allowed
from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon
from mcp_gateway.broker.update_agent import (
    _PINNED_RELEASE_PUBLIC_KEY,
    SecurityViolation,
    UpdateAgent,
    assert_safe_adapter_path,
    assert_vault_isolated,
    test_canary_parse,
    verify_signature,
)
from mcp_gateway.engine.adapters import (
    AdapterConfig,
    CompiledWireSpec,
    SchemaValidationError,
    compile_wire_spec,
    validate_wire_spec,
)
from mcp_gateway.schemas.error import ALLOWLIST_DENIED

# Production pinned private key for test fixture signing
TEST_PRIVATE_KEY_HEX = "3dc759f019926175920fcf63f22819ff34d907104e1d924894bdb228661721ac"
TEST_NOTEBOOK_ID = "3e3c08b5-7e5c-4189-9923-81933a256f54"
FORBIDDEN_PROD_NOTEBOOK_ID = "b61be5ed-8360-42cb-bdd6-328160a0eb0f"


def sign_payload(payload: bytes, private_key_hex: str = TEST_PRIVATE_KEY_HEX) -> bytes:
    """Signs raw bytes with Ed25519 private key."""
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    return priv.sign(payload)


@pytest.fixture
def test_dirs(tmp_path: Path) -> tuple[Path, Path]:
    adapter_dir = tmp_path / "adapters"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    vault_dir = tmp_path / ".config" / "notebooklm-mcp-bridge"
    vault_dir.mkdir(parents=True, exist_ok=True)
    return adapter_dir, vault_dir


@pytest.fixture
def sample_valid_spec_text() -> str:
    bundled_path = Path(__file__).parent.parent / "src" / "mcp_gateway" / "engine" / "wire_spec.v4.json"
    return bundled_path.read_text(encoding="utf-8")


@pytest.fixture
def rlm_fixture() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "rLM1Ne_canary_fixture.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# INVARIANT 1: Cryptographic Signature Pre-Check
# ---------------------------------------------------------------------------


def test_invariant_1_valid_signature_passes(sample_valid_spec_text: str) -> None:
    raw_bytes = sample_valid_spec_text.encode("utf-8")
    sig = sign_payload(raw_bytes)
    # Must succeed without exception
    verify_signature(raw_bytes, sig, _PINNED_RELEASE_PUBLIC_KEY)


def test_invariant_1_tampered_bytes_rejected_before_json_parse(sample_valid_spec_text: str) -> None:
    raw_bytes = sample_valid_spec_text.encode("utf-8")
    sig = sign_payload(raw_bytes)

    # Tamper with raw bytes (even 1 character change)
    tampered_bytes = raw_bytes + b" "

    with pytest.raises(SecurityViolation, match="signature verification failed"):
        verify_signature(tampered_bytes, sig, _PINNED_RELEASE_PUBLIC_KEY)


def test_invariant_1_invalid_signature_length_rejected() -> None:
    with pytest.raises(SecurityViolation, match="Invalid signature length"):
        verify_signature(b"dummy payload", b"short_sig", _PINNED_RELEASE_PUBLIC_KEY)


def test_invariant_1_unparseable_json_with_bad_signature_fails_at_signature() -> None:
    malformed_json_bytes = b"NOT_JSON_AT_ALL {{{[[["
    bad_sig = b"\x00" * 64

    # Signature check MUST fail before any json.loads() or schema parsing is attempted
    with pytest.raises(SecurityViolation, match="signature verification failed"):
        verify_signature(malformed_json_bytes, bad_sig, _PINNED_RELEASE_PUBLIC_KEY)


# ---------------------------------------------------------------------------
# INVARIANT 2: Air-Gapped Vault Immutability
# ---------------------------------------------------------------------------


def test_invariant_2_vault_immutability(test_dirs: tuple[Path, Path]) -> None:
    adapter_dir, vault_dir = test_dirs

    # Attempting to write into user vault directly raises SecurityViolation
    vault_target = vault_dir / "wire_spec.v4.json"
    with pytest.raises(SecurityViolation, match="Air-Gapped Vault Immutability"):
        assert_vault_isolated(vault_target, vault_dir)

    # Subdirectories in vault also rejected
    sub_vault_target = vault_dir / "adapters" / "wire_spec.v4.json"
    with pytest.raises(SecurityViolation, match="Air-Gapped Vault Immutability"):
        assert_vault_isolated(sub_vault_target, vault_dir)

    # Safe path in adapter_dir passes
    safe_path = adapter_dir / "wire_spec.v4.json"
    assert_vault_isolated(safe_path, vault_dir)


# ---------------------------------------------------------------------------
# INVARIANT 3: Strict Path Traversal & Symlink Guard
# ---------------------------------------------------------------------------


def test_invariant_3_path_traversal_rejection(test_dirs: tuple[Path, Path]) -> None:
    adapter_dir, _ = test_dirs

    traversal_path = adapter_dir / ".." / "escaped.json"
    with pytest.raises(SecurityViolation, match="Path traversal '..' prohibited"):
        assert_safe_adapter_path(traversal_path, adapter_dir)

    outside_path = Path("/tmp/outside_spec.json")
    with pytest.raises(SecurityViolation, match="Path traversal attempt detected outside adapter storage"):
        assert_safe_adapter_path(outside_path, adapter_dir)


def test_invariant_3_symlink_rejection(test_dirs: tuple[Path, Path]) -> None:
    adapter_dir, _ = test_dirs

    target_file = adapter_dir / "real_file.json"
    target_file.write_text("{}", encoding="utf-8")

    symlink_file = adapter_dir / "symlink_file.json"
    try:
        symlink_file.symlink_to(target_file)
    except OSError:
        pytest.skip("Symlink creation not supported on this OS/filesystem")

    with pytest.raises(SecurityViolation, match="Symlinks are strictly prohibited"):
        assert_safe_adapter_path(symlink_file, adapter_dir)


# ---------------------------------------------------------------------------
# INVARIANT 4: State Persistence Across Restarts & Rate Limiting
# ---------------------------------------------------------------------------


def test_invariant_4_state_persistence_and_file_mode(test_dirs: tuple[Path, Path]) -> None:
    adapter_dir, vault_dir = test_dirs
    agent = UpdateAgent(adapter_dir=adapter_dir, vault_dir=vault_dir)

    # Verify initial state
    assert agent.state.last_check_timestamp == 0.0
    assert agent.state.checks_in_24h == []
    assert agent.state.quarantined_hashes == []

    # Update state and save
    t_now = 1700000000.0
    agent.record_update_check(now=t_now)
    agent.quarantine_spec_hash("hash_quarantine_001")

    # Verify state file exists and has 0o600 permissions
    state_file = adapter_dir / "adapter_state.json"
    assert state_file.exists()
    mode = stat.S_IMODE(state_file.stat().st_mode)
    assert mode == 0o600

    # Reload fresh agent instance and assert state restored
    fresh_agent = UpdateAgent(adapter_dir=adapter_dir, vault_dir=vault_dir)
    assert fresh_agent.state.last_check_timestamp == t_now
    assert fresh_agent.state.checks_in_24h == [t_now]
    assert "hash_quarantine_001" in fresh_agent.state.quarantined_hashes


def test_invariant_4_cooldown_and_24h_rate_limit(test_dirs: tuple[Path, Path]) -> None:
    adapter_dir, vault_dir = test_dirs
    agent = UpdateAgent(adapter_dir=adapter_dir, vault_dir=vault_dir)

    start_time = 100000.0
    # First check allowed
    ok, _ = agent.can_check_update(now=start_time)
    assert ok is True
    agent.record_update_check(now=start_time)

    # Immediate second check rejected due to 1-hour cooldown
    ok, reason = agent.can_check_update(now=start_time + 300.0)  # 5 min later
    assert ok is False
    assert "1-hour cooldown active" in reason

    # After 1 hour (3601s later), second check allowed
    t2 = start_time + 3601.0
    ok, _ = agent.can_check_update(now=t2)
    assert ok is True
    agent.record_update_check(now=t2)

    # After another 1 hour (7202s later), third check allowed
    t3 = start_time + 7202.0
    ok, _ = agent.can_check_update(now=t3)
    assert ok is True
    agent.record_update_check(now=t3)

    # Fourth check within 24h rejected even if cooldown elapsed (max 3 checks in 24h)
    t4 = start_time + 10803.0
    ok, reason = agent.can_check_update(now=t4)
    assert ok is False
    assert "maximum 3 checks per 24 hours exceeded" in reason

    # 24 hours after start_time + 1s, window slides and check allowed again
    t5 = start_time + 86401.0
    ok, _ = agent.can_check_update(now=t5)
    assert ok is True


# ---------------------------------------------------------------------------
# INVARIANT 5: Prototype Pollution & DOM Selector Sanitization
# ---------------------------------------------------------------------------


def test_invariant_5_prototype_pollution_rejection(sample_valid_spec_text: str) -> None:
    # Injecting __proto__ in dom_selectors keys must fail
    spec_proto_key = json.loads(sample_valid_spec_text)
    spec_proto_key["dom_selectors"]["__proto__"] = "polluted"
    with pytest.raises(SchemaValidationError, match="Forbidden prototype pollution"):
        validate_wire_spec(spec_proto_key)

    # Injecting constructor in dom_selectors values must fail
    spec_constructor_val = json.loads(sample_valid_spec_text)
    spec_constructor_val["dom_selectors"]["custom_key"] = "constructor"
    with pytest.raises(SchemaValidationError, match="Forbidden prototype pollution"):
        validate_wire_spec(spec_constructor_val)

    # Injecting prototype in dom_selectors values must fail
    spec_prototype_val = json.loads(sample_valid_spec_text)
    spec_prototype_val["dom_selectors"]["prototype"] = "some_val"
    with pytest.raises(SchemaValidationError, match="Forbidden prototype pollution"):
        validate_wire_spec(spec_prototype_val)

    # Invalid regex (e.g. script tags, special characters) must fail
    spec_bad_pattern = json.loads(sample_valid_spec_text)
    spec_bad_pattern["dom_selectors"]["bad key with spaces"] = "valid_val"
    with pytest.raises(SchemaValidationError):
        validate_wire_spec(spec_bad_pattern)


# ---------------------------------------------------------------------------
# INVARIANT 6: Immutable Snapshot Execution via CompiledWireSpec
# ---------------------------------------------------------------------------


def test_invariant_6_immutable_snapshot_execution(test_dirs: tuple[Path, Path], sample_valid_spec_text: str) -> None:
    adapter_dir, _ = test_dirs
    adapter_config = AdapterConfig.get_instance(adapter_dir)

    # Obtain snapshot 1
    snapshot_1 = adapter_config.get_spec()
    assert isinstance(snapshot_1, CompiledWireSpec)
    original_rpc = snapshot_1.get_rpc_id("list_notebooks")
    assert original_rpc == "wXbhsf"

    # Mutate spec file on disk and reload
    modified_spec_dict = json.loads(sample_valid_spec_text)
    modified_spec_dict["rpc_descriptors"]["list_notebooks"]["method_id"] = "MODIFIED_RPC"
    adapter_dir_spec = adapter_dir / "wire_spec.v4.json"
    adapter_dir_spec.write_text(json.dumps(modified_spec_dict), encoding="utf-8")

    snapshot_2 = adapter_config.reload(adapter_dir_spec)

    # Snapshot 2 reflects updated spec
    assert snapshot_2.get_rpc_id("list_notebooks") == "MODIFIED_RPC"

    # Critical: Snapshot 1 remains completely frozen and unmodified
    assert snapshot_1.get_rpc_id("list_notebooks") == "wXbhsf"
    assert snapshot_1 is not snapshot_2


# ---------------------------------------------------------------------------
# INVARIANT 7: Triple Fallback Resilience
# ---------------------------------------------------------------------------


def test_invariant_7_triple_fallback_resolution(test_dirs: tuple[Path, Path], sample_valid_spec_text: str) -> None:
    adapter_dir, _ = test_dirs
    adapter_config = AdapterConfig.get_instance(adapter_dir)

    # 1. Active dynamic spec present
    spec_dynamic = json.loads(sample_valid_spec_text)
    spec_dynamic["rpc_descriptors"]["list_notebooks"]["method_id"] = "DYNAMIC_LEVEL1"
    (adapter_dir / "wire_spec.v4.json").write_text(json.dumps(spec_dynamic), encoding="utf-8")

    # 2. LKG spec present
    spec_lkg = json.loads(sample_valid_spec_text)
    spec_lkg["rpc_descriptors"]["list_notebooks"]["method_id"] = "LKG_LEVEL2"
    (adapter_dir / "wire_spec.v4.lkg.json").write_text(json.dumps(spec_lkg), encoding="utf-8")

    # Resolves to Level 1 (Dynamic)
    resolved = adapter_config.reload()
    assert resolved.get_rpc_id("list_notebooks") == "DYNAMIC_LEVEL1"

    # Corrupt Level 1 (write bad JSON) -> Falls back cleanly to Level 2 (LKG)
    (adapter_dir / "wire_spec.v4.json").write_text("CORRUPTED_JSON_[[[", encoding="utf-8")
    resolved_fallback_lkg = adapter_config.reload()
    assert resolved_fallback_lkg.get_rpc_id("list_notebooks") == "LKG_LEVEL2"

    # Corrupt Level 2 (write bad JSON) -> Falls back cleanly to Level 3 (Bundled Default)
    (adapter_dir / "wire_spec.v4.lkg.json").write_text("CORRUPTED_LKG_###", encoding="utf-8")
    resolved_bundled = adapter_config.reload()
    assert resolved_bundled.get_rpc_id("list_notebooks") == "wXbhsf"


# ---------------------------------------------------------------------------
# INVARIANT 8: Synthetic Canary Validation & Atomic LKG Rollback Engine
# ---------------------------------------------------------------------------


def test_invariant_8_synthetic_canary_validation(sample_valid_spec_text: str, rlm_fixture: dict[str, Any]) -> None:
    valid_spec = compile_wire_spec(sample_valid_spec_text)
    # Canary validation passes on valid spec
    assert test_canary_parse(valid_spec, rLM1Ne_fixture=rlm_fixture) is True

    # Broken spec missing user_notes row index fails canary
    broken_spec_dict = json.loads(sample_valid_spec_text)
    broken_spec_dict["rpc_descriptors"]["get_notebook_metadata"]["rows"]["user_notes"]["row_index"] = 9999
    broken_spec = compile_wire_spec(json.dumps(broken_spec_dict))

    with pytest.raises(ValueError, match="Canary failed"):
        test_canary_parse(broken_spec, rLM1Ne_fixture=rlm_fixture)


def test_invariant_8_active_health_window_atomic_rollback(
    test_dirs: tuple[Path, Path],
    sample_valid_spec_text: str,
    rlm_fixture: dict[str, Any],
) -> None:
    adapter_dir, vault_dir = test_dirs
    agent = UpdateAgent(adapter_dir=adapter_dir, vault_dir=vault_dir)

    # Establish initial known good state
    initial_spec_dict = json.loads(sample_valid_spec_text)
    initial_spec_dict["rpc_descriptors"]["list_notebooks"]["method_id"] = "INITIAL_GOOD_RPC"
    initial_bytes = json.dumps(initial_spec_dict).encode("utf-8")
    initial_sig = sign_payload(initial_bytes)
    agent.promote_candidate_spec(initial_bytes, initial_sig, rLM1Ne_fixture=rlm_fixture)

    # Promote a new candidate spec
    candidate_spec_dict = json.loads(sample_valid_spec_text)
    candidate_spec_dict["rpc_descriptors"]["list_notebooks"]["method_id"] = "NEW_CANDIDATE_RPC"
    candidate_bytes = json.dumps(candidate_spec_dict).encode("utf-8")
    candidate_sig = sign_payload(candidate_bytes)
    candidate_spec = agent.promote_candidate_spec(candidate_bytes, candidate_sig, rLM1Ne_fixture=rlm_fixture)

    assert candidate_spec.get_rpc_id("list_notebooks") == "NEW_CANDIDATE_RPC"
    # LKG file was created containing the previous initial spec
    assert (adapter_dir / "wire_spec.v4.lkg.json").exists()

    # Simulate 2 RPC failures within health window (threshold is 3)
    rolled_back = agent.record_rpc_failure()
    assert rolled_back is False
    rolled_back = agent.record_rpc_failure()
    assert rolled_back is False

    # 3rd RPC failure triggers atomic rollback to LKG!
    rolled_back = agent.record_rpc_failure()
    assert rolled_back is True

    # Active spec is now restored to INITIAL_GOOD_RPC
    active_spec = agent.adapter_config.get_spec()
    assert active_spec.get_rpc_id("list_notebooks") == "INITIAL_GOOD_RPC"

    # Candidate spec hash was added to quarantine
    assert candidate_spec.spec_hash in agent.state.quarantined_hashes

    # Attempting to re-promote quarantined spec must fail immediately
    with pytest.raises(ValueError, match="is quarantined"):
        agent.promote_candidate_spec(candidate_bytes, candidate_sig, rLM1Ne_fixture=rlm_fixture)


# ---------------------------------------------------------------------------
# INVARIANT 9: Strict Test Scope Guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invariant_9_strict_test_scope_guard(tmp_path: Path) -> None:
    allowlist_file = tmp_path / "allowlist.json"
    allowlist_file.write_text(
        json.dumps({
            "version": 2,
            "provider_mode": "browser",
            "accounts": ["tester@example.com"],
            "notebooks": [TEST_NOTEBOOK_ID],
        }),
        encoding="utf-8",
    )

    cfg = BrokerConfig(
        socket_path=str(tmp_path / "scope_test.sock"),
        allowlist_path=allowlist_file,
        journal_db_path=tmp_path / "scope_journal.db",
        adapter_dir=tmp_path / "adapters",
    )
    broker = BrokerDaemon(cfg)

    # Test Notebook ID: Allowed
    assert is_notebook_allowed(broker.allowlist, TEST_NOTEBOOK_ID) is True

    # Forbidden production notebook: Denied
    assert is_notebook_allowed(broker.allowlist, FORBIDDEN_PROD_NOTEBOOK_ID) is False

    # Attempting to select forbidden production notebook returns ALLOWLIST_DENIED
    res = await broker.dispatch({
        "action": "select_notebook",
        "notebook_id": FORBIDDEN_PROD_NOTEBOOK_ID,
    })
    assert res.get("ok") is False
    assert res.get("error", {}).get("code") == ALLOWLIST_DENIED


@pytest.mark.asyncio
async def test_dynamic_dom_relay_injected_in_companion_payload(tmp_path: Path) -> None:
    allowlist_file = tmp_path / "allowlist.json"
    allowlist_file.write_text(
        json.dumps({
            "version": 2,
            "provider_mode": "browser",
            "accounts": ["tester@example.com"],
            "notebooks": [TEST_NOTEBOOK_ID],
        }),
        encoding="utf-8",
    )

    cfg = BrokerConfig(
        socket_path=str(tmp_path / "dom_test.sock"),
        allowlist_path=allowlist_file,
        journal_db_path=tmp_path / "dom_journal.db",
        adapter_dir=tmp_path / "adapters",
    )
    broker = BrokerDaemon(cfg)

    # Verify dynamic DOM selectors are configured in spec
    spec = broker.adapter_config.get_spec()
    assert spec.get_dom_selector("xsrf_token_variable") == "SNlM0e"
    assert spec.get_dom_selector("wiz_global_email") == "oM1Kwf"
