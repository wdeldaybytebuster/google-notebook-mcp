"""Zero-Friction Upstream Drift & Self-Healing Auto-Update Engine (Phase 11).

Implements:
- INVARIANT 1: Cryptographic Signature Pre-Check via Ed25519 on raw bytes
- INVARIANT 2: Air-Gapped Vault Immutability (~/.config/notebooklm-mcp-bridge/ read-only)
- INVARIANT 3: Strict Path Traversal & Symlink Guard
- INVARIANT 4: State Persistence Across Restarts (1h cooldown, max 3 checks / 24h, quarantined hashes)
- INVARIANT 8: Synthetic Canary Validation & Atomic LKG Rollback Engine (10-min health window, 3-failure threshold)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import logging
import os
from pathlib import Path
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from mcp_gateway.engine.adapters import (
    DEFAULT_ADAPTER_DIR,
    AdapterConfig,
    CompiledWireSpec,
    compile_wire_spec,
)

logger = logging.getLogger(__name__)

# Production pinned 32-byte Ed25519 public key
_PINNED_RELEASE_PUBLIC_KEY: bytes = bytes.fromhex(
    "d89c7c1f937a234a9a30faac5e97f183ff618ffd23b2158d5243e883d25d83cb"
)

DEFAULT_USER_VAULT_DIR: Path = Path.home() / ".config" / "notebooklm-mcp-bridge"
HEALTH_WINDOW_SECONDS: float = 600.0  # 10 minutes
COOLDOWN_SECONDS: float = 3600.0      # 1 hour
MAX_CHECKS_IN_24H: int = 3
FAILURE_THRESHOLD_ROLLBACK: int = 3


class SecurityViolation(Exception):
    """Raised when an operation violates security boundaries or path isolation."""


@dataclass
class AdapterState:
    """Persistent state across gateway restarts.

    Enforces INVARIANT 4.
    """

    last_check_timestamp: float = 0.0
    checks_in_24h: list[float] = field(default_factory=list)
    quarantined_hashes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdapterState:
        return cls(
            last_check_timestamp=float(data.get("last_check_timestamp", 0.0)),
            checks_in_24h=[float(t) for t in data.get("checks_in_24h", [])],
            quarantined_hashes=[str(h) for h in data.get("quarantined_hashes", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def verify_signature(
    raw_spec_bytes: bytes,
    signature_bytes: bytes,
    public_key_bytes: bytes = _PINNED_RELEASE_PUBLIC_KEY,
) -> None:
    """Validates Ed25519 signature on raw, un-parsed bytes.

    Enforces INVARIANT 1: MUST be called BEFORE json.loads() or schema parsing.
    """
    if not isinstance(raw_spec_bytes, bytes) or not isinstance(signature_bytes, bytes):
        raise SecurityViolation("Payload and signature must be raw bytes")

    if len(signature_bytes) != 64:
        raise SecurityViolation(f"Invalid signature length: {len(signature_bytes)} (expected 64 bytes)")

    try:
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(signature_bytes, raw_spec_bytes)
    except InvalidSignature as err:
        raise SecurityViolation("Cryptographic signature verification failed") from err
    except Exception as exc:
        raise SecurityViolation(f"Cryptographic verification error: {exc}") from exc


def assert_vault_isolated(target_path: Path, vault_dir: Path | None = None) -> None:
    """Enforces INVARIANT 2: User Vault is strictly immutable and air-gapped."""
    vault = (vault_dir or DEFAULT_USER_VAULT_DIR).resolve()
    resolved = target_path.resolve()

    if resolved == vault or vault in resolved.parents:
        raise SecurityViolation(
            f"Air-Gapped Vault Immutability: write operation targeting user vault is prohibited: {target_path}"
        )


def assert_safe_adapter_path(target_path: Path, adapter_dir: Path) -> Path:
    """Enforces INVARIANT 3: Strict path traversal and symlink rejection."""
    # Symlink check
    if target_path.is_symlink():
        raise SecurityViolation(f"Symlinks are strictly prohibited in adapter storage: {target_path}")

    # Relative path traversal check
    if ".." in target_path.parts:
        raise SecurityViolation(f"Path traversal '..' prohibited: {target_path}")

    resolved_dir = adapter_dir.resolve()
    resolved_target = target_path.resolve()

    # Verify target parent is within adapter directory
    if resolved_target.parent != resolved_dir and resolved_dir not in resolved_target.parents:
        raise SecurityViolation(
            f"Path traversal attempt detected outside adapter storage: {target_path} -> {resolved_target}"
        )

    return target_path


def test_canary_parse(
    spec: CompiledWireSpec,
    rLM1Ne_fixture: dict[str, Any] | None = None,
    query_fixture: dict[str, Any] | None = None,
) -> bool:
    """Enforces INVARIANT 8: Synthetic canary validation against fixtures.

    Validates that a candidate spec correctly resolves method IDs and array offsets
    against known good synthetic responses before promotion.
    """
    # 1. Verify get_notebook_metadata method_id and row indices
    rpc_id = spec.get_rpc_id("get_notebook_metadata")
    if not rpc_id or not isinstance(rpc_id, str):
        raise ValueError("Canary failed: get_notebook_metadata method_id missing")

    notes_index = spec.get_row_index("get_notebook_metadata", "user_notes", 17)
    artifacts_index = spec.get_row_index("get_notebook_metadata", "artifacts", 18)

    if notes_index < 0 or artifacts_index < 0:
        raise ValueError("Canary failed: row indices must be non-negative integers")

    # If fixture provided, test simulated extraction
    if rLM1Ne_fixture is not None:
        data = rLM1Ne_fixture.get("data")
        if not isinstance(data, list) or len(data) == 0 or not isinstance(data[0], list):
            raise ValueError("Canary failed: invalid rLM1Ne fixture structure")
        container = data[0]
        if len(container) <= notes_index or not isinstance(container[notes_index], list):
            raise ValueError(f"Canary failed: user_notes index {notes_index} out of bounds or not an array")
        if len(container) <= artifacts_index or not isinstance(container[artifacts_index], list):
            raise ValueError(f"Canary failed: artifacts index {artifacts_index} out of bounds or not an array")

    # 2. Verify list_notebooks method_id
    list_rpc = spec.get_rpc_id("list_notebooks")
    if not list_rpc or not isinstance(list_rpc, str):
        raise ValueError("Canary failed: list_notebooks method_id missing")

    # 3. Verify query_stream descriptor
    query_desc = spec.rpc_descriptors.get("query_stream", {})
    if not isinstance(query_desc, dict) or not query_desc.get("endpoint_url"):
        raise ValueError("Canary failed: query_stream endpoint_url missing")

    return True


# Tell pytest not to collect test_canary_parse as a test
test_canary_parse.__test__ = False  # type: ignore[attr-defined]


class UpdateAgent:
    """Manages adapter updates, cryptographic gating, rate limiting, and atomic self-healing."""

    def __init__(
        self,
        adapter_dir: Path | None = None,
        vault_dir: Path | None = None,
        public_key_bytes: bytes = _PINNED_RELEASE_PUBLIC_KEY,
    ) -> None:
        self.adapter_dir = (adapter_dir or DEFAULT_ADAPTER_DIR).resolve()
        self.vault_dir = (vault_dir or DEFAULT_USER_VAULT_DIR).resolve()
        self.public_key_bytes = public_key_bytes
        self.adapter_config = AdapterConfig.get_instance(self.adapter_dir)

        # Ensure adapter directory exists with 0o700 permissions
        self.adapter_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.adapter_dir, 0o700)
        except OSError:
            pass

        self.state_file_path = self.adapter_dir / "adapter_state.json"
        self.state = self.load_state()

        # Health window state
        self._active_health_window_until: float = 0.0
        self._consecutive_failures: int = 0
        self._candidate_spec_hash: str | None = None

    def load_state(self) -> AdapterState:
        """Loads persistent state from adapter_state.json (Invariant 4)."""
        if self.state_file_path.exists():
            try:
                raw = json.loads(self.state_file_path.read_text(encoding="utf-8"))
                return AdapterState.from_dict(raw)
            except Exception as exc:
                logger.warning("Could not read adapter_state.json, creating fresh: %s", exc)
        return AdapterState()

    def save_state(self) -> None:
        """Atomically persists state to adapter_state.json with 0o600 permissions."""
        assert_vault_isolated(self.state_file_path, self.vault_dir)
        assert_safe_adapter_path(self.state_file_path, self.adapter_dir)

        tmp_path = self.adapter_dir / f"adapter_state.json.tmp_{os.getpid()}_{time.time()}"
        data = json.dumps(self.state.to_dict(), indent=2)

        # Write tmp file with 0o600 permissions
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(data)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise

        os.replace(tmp_path, self.state_file_path)

    def can_check_update(self, now: float | None = None) -> tuple[bool, str]:
        """Enforces INVARIANT 4: 1-hour cooldown & max 3 checks per 24 hours."""
        current_time = time.time() if now is None else now

        # Cooldown check: 1 hour minimum
        time_since_last = current_time - self.state.last_check_timestamp
        if time_since_last < COOLDOWN_SECONDS:
            remaining = int(COOLDOWN_SECONDS - time_since_last)
            return False, f"Rate limited: 1-hour cooldown active ({remaining}s remaining)"

        # Rate limit check: max 3 checks per 24 hours
        active_checks = [t for t in self.state.checks_in_24h if (current_time - t) < 86400.0]
        if len(active_checks) >= MAX_CHECKS_IN_24H:
            return False, f"Rate limited: maximum {MAX_CHECKS_IN_24H} checks per 24 hours exceeded"

        return True, ""

    def record_update_check(self, now: float | None = None) -> None:
        """Records an update check attempt and persists state."""
        current_time = time.time() if now is None else now
        self.state.last_check_timestamp = current_time
        self.state.checks_in_24h = [
            t for t in self.state.checks_in_24h if (current_time - t) < 86400.0
        ]
        self.state.checks_in_24h.append(current_time)
        self.save_state()

    def quarantine_spec_hash(self, spec_hash: str) -> None:
        """Adds a broken spec hash to quarantine and persists state."""
        if spec_hash and spec_hash not in self.state.quarantined_hashes:
            self.state.quarantined_hashes.append(spec_hash)
            self.save_state()
            logger.warning("Quarantined wire spec hash: %s", spec_hash)

    def promote_candidate_spec(
        self,
        raw_spec_bytes: bytes,
        signature_bytes: bytes,
        rLM1Ne_fixture: dict[str, Any] | None = None,
        query_fixture: dict[str, Any] | None = None,
    ) -> CompiledWireSpec:
        """Promotes a signed candidate adapter spec to active after strict verification.

        Verification pipeline:
        1. INVARIANT 1: Ed25519 signature verified on raw bytes BEFORE parsing
        2. Quarantine check: Candidate hash is not in quarantined list
        3. INVARIANTS 2 & 3: Path isolation & symlink assertions
        4. Schema & INVARIANT 5: JSON Schema & prototype pollution sanitization
        5. INVARIANT 8: Synthetic canary validation against test fixtures
        6. Atomic promotion: LKG backup -> active write (0o600) -> memory swap -> 10m health window
        """
        # 1. INVARIANT 1: Cryptographic signature pre-check on raw bytes
        verify_signature(raw_spec_bytes, signature_bytes, self.public_key_bytes)

        # 2. Quarantine check
        spec_hash = hashlib.sha256(raw_spec_bytes).hexdigest()
        if spec_hash in self.state.quarantined_hashes:
            raise ValueError(f"Candidate spec is quarantined (hash: {spec_hash})")

        # 3. Compile and validate schema & prototype pollution (Invariant 5)
        raw_text = raw_spec_bytes.decode("utf-8")
        compiled_spec = compile_wire_spec(raw_text)

        # 4. INVARIANT 8: Synthetic canary validation
        test_canary_parse(compiled_spec, rLM1Ne_fixture=rLM1Ne_fixture, query_fixture=query_fixture)

        # 5. Assert paths
        dynamic_path = self.adapter_dir / "wire_spec.v4.json"
        lkg_path = self.adapter_dir / "wire_spec.v4.lkg.json"
        assert_vault_isolated(dynamic_path, self.vault_dir)
        assert_vault_isolated(lkg_path, self.vault_dir)
        assert_safe_adapter_path(dynamic_path, self.adapter_dir)
        assert_safe_adapter_path(lkg_path, self.adapter_dir)

        # 6. Atomic promotion:
        # Step A: If dynamic_path currently exists, backup to LKG atomically
        if dynamic_path.exists():
            current_bytes = dynamic_path.read_bytes()
            tmp_lkg = self.adapter_dir / f"wire_spec.v4.lkg.json.tmp_{os.getpid()}"
            fd = os.open(tmp_lkg, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with open(fd, "wb") as f:
                f.write(current_bytes)
            os.replace(tmp_lkg, lkg_path)

        # Step B: Write candidate to active dynamic_path atomically
        tmp_dynamic = self.adapter_dir / f"wire_spec.v4.json.tmp_{os.getpid()}"
        fd = os.open(tmp_dynamic, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with open(fd, "wb") as f:
            f.write(raw_spec_bytes)
        os.replace(tmp_dynamic, dynamic_path)

        # Step C: Write signature
        sig_path = self.adapter_dir / "wire_spec.v4.json.sig"
        tmp_sig = self.adapter_dir / f"wire_spec.v4.json.sig.tmp_{os.getpid()}"
        fd_sig = os.open(tmp_sig, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with open(fd_sig, "wb") as f:
            f.write(signature_bytes)
        os.replace(tmp_sig, sig_path)

        # Step D: Reload in-memory adapter config
        active_spec = self.adapter_config.reload(dynamic_path)

        # Step E: Establish 10-minute active health window (Invariant 8)
        self._active_health_window_until = time.time() + HEALTH_WINDOW_SECONDS
        self._consecutive_failures = 0
        self._candidate_spec_hash = spec_hash
        logger.info(
            "Promoted candidate spec %s to active. Health window open for %ds",
            spec_hash[:8],
            int(HEALTH_WINDOW_SECONDS),
        )

        return active_spec

    def record_rpc_failure(self) -> bool:
        """Records an RPC failure and triggers self-healing rollback if threshold reached.

        Enforces INVARIANT 8: Auto-reverts to wire_spec.v4.lkg.json on 3 consecutive failures
        during the 10-minute active health window.
        """
        now = time.time()
        if now <= self._active_health_window_until:
            self._consecutive_failures += 1
            logger.warning(
                "Health window failure %d/%d for spec %s",
                self._consecutive_failures,
                FAILURE_THRESHOLD_ROLLBACK,
                self._candidate_spec_hash,
            )
            if self._consecutive_failures >= FAILURE_THRESHOLD_ROLLBACK:
                logger.error(
                    "Failure threshold reached (%d failures). Triggering atomic LKG rollback!",
                    self._consecutive_failures,
                )
                self.rollback_to_lkg()
                return True
        return False

    def record_rpc_success(self) -> None:
        """Resets consecutive failure counter on successful RPC."""
        self._consecutive_failures = 0

    def rollback_to_lkg(self) -> CompiledWireSpec:
        """Performs atomic rollback to Last Known Good (LKG) or bundled default."""
        # 1. Quarantine current broken spec hash
        if self._candidate_spec_hash:
            self.quarantine_spec_hash(self._candidate_spec_hash)

        dynamic_path = self.adapter_dir / "wire_spec.v4.json"

        # Remove broken dynamic spec file
        try:
            dynamic_path.unlink(missing_ok=True)
            (self.adapter_dir / "wire_spec.v4.json.sig").unlink(missing_ok=True)
        except OSError:
            pass

        # 2. Reset health window
        self._active_health_window_until = 0.0
        self._consecutive_failures = 0
        self._candidate_spec_hash = None

        # 3. Reload AdapterConfig (resolves to LKG if valid, or bundled default)
        reverted_spec = self.adapter_config.reload()
        logger.info("Rolled back to wire spec hash: %s", reverted_spec.spec_hash[:8])
        return reverted_spec
