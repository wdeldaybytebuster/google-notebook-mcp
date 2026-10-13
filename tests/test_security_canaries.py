from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
import pytest

from mcp_gateway.broker.allowlist import AllowlistConfig
from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon, McpFacade
from mcp_gateway.broker.secret_scrubber import assert_clean, scrub, scrub_dict
from mcp_gateway.schemas.error import (
    ALLOWLIST_DENIED,
    INVALID_ARGUMENT,
)
from mcp_gateway.storage.journal import (
    MutationJournal,
    MutationState,
    OperationType,
    compute_payload_hash,
)
import mcp.types as types


@pytest.fixture
def allowlist_file(tmp_path: Path) -> Path:
    p = tmp_path / "allowlist.json"
    p.write_text(
        json.dumps({
            "version": 1,
            "provider_mode": "browser",
            "accounts": ["tester@gmail.com"],
            "notebooks": ["nb-allowed-safe"],
        }),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def broker(tmp_path: Path, allowlist_file: Path) -> BrokerDaemon:
    cfg = BrokerConfig(
        socket_path=str(tmp_path / "canary_test.sock"),
        allowlist_path=allowlist_file,
        journal_db_path=tmp_path / "journal_canary.db",
    )
    return BrokerDaemon(cfg)


@pytest.fixture
def facade(broker: BrokerDaemon) -> McpFacade:
    return McpFacade(broker)


def test_token_leakage_defense_synthetic_canaries() -> None:
    canary_tokens = [
        "SID=canary_session_cookie_secret_12345",
        "HSID=canary_hsid_cookie_67890",
        "SSID=canary_ssid_cookie_abcde",
        "__Secure-1PSID=canary_secure_psid_fghij",
        "SAPISID=canary_sapisid_klmno",
        "SNlM0e=canary_csrf_token_secret_xyz",
        "Bearer ya29.canary_google_oauth_bearer_token_9999",
        "ya29.canary_bare_oauth_token_8888",
    ]

    for canary in canary_tokens:
        dirty_message = f"Error during RPC call: Upstream failed with token {canary} and headers."
        cleaned = scrub(dirty_message)

        # Assert canary string is completely absent
        assert canary not in cleaned
        assert "[REDACTED]" in cleaned

        # assert_clean raises on dirty string
        with pytest.raises(ValueError, match=r"\[SECRET DETECTED\]"):
            assert_clean(dirty_message)

        # assert_clean passes on scrubbed string
        assert_clean(cleaned)


def test_token_leakage_nested_data_scrubbing() -> None:
    nested_response = {
        "status": "error",
        "upstream_frame": {
            "error_detail": "Auth failure: Bearer ya29.canary_token_leaked_here",
            "cookies": ["SID=canary_cookie_val_1", "clean_key=clean_val"],
        },
        "wiz_data": 'window.WIZ_global_data = {SNlM0e: "canary_wiz_token"};',
    }

    sanitized = scrub_dict(nested_response)
    serialized = json.dumps(sanitized)

    assert "canary_token_leaked_here" not in serialized
    assert "canary_cookie_val_1" not in serialized
    assert "canary_wiz_token" not in serialized
    assert_clean(serialized)


@pytest.mark.asyncio
async def test_allowlist_enforcement_blocks_ipc(facade: McpFacade, broker: BrokerDaemon) -> None:
    call_entry = facade.server._request_handlers.get("tools/call")
    assert call_entry is not None

    # Call with non-allowlisted notebook ID
    forbidden_uuid = "00000000-0000-0000-0000-000000000000"
    req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(
            name="get_notebook_metadata",
            arguments={"notebook_id": forbidden_uuid},
        ),
    )

    res = await call_entry.handler(cast(Any, None), req)
    assert isinstance(res, types.CallToolResult)
    assert res.is_error is True
    assert len(res.content) == 1
    item = res.content[0]
    assert isinstance(item, types.TextContent)
    payload = json.loads(item.text)

    assert payload["ok"] is False
    assert payload["error"]["code"] == ALLOWLIST_DENIED
    # Verify companion writer was never called
    assert broker._active_companion_writer is None


@pytest.mark.asyncio
async def test_closed_schema_fuzzing_rejects_extra_properties(facade: McpFacade) -> None:
    call_entry = facade.server._request_handlers.get("tools/call")
    assert call_entry is not None

    fuzz_test_cases: list[tuple[str, dict[str, Any]]] = [
        (
            "list_notebooks",
            {"page_size": 10, "malicious_injected_prop": "evil_payload"},
        ),
        (
            "get_notebook_metadata",
            {"notebook_id": "nb-allowed-safe", "extra_attack_field": 123},
        ),
        (
            "list_sources",
            {"notebook_id": "nb-allowed-safe", "unauthorized_flag": True},
        ),
        (
            "query_notebook",
            {
                "notebook_id": "nb-allowed-safe",
                "question": "Hello",
                "request_key": "req-1",
                "backdoor_param": "forbidden",
            },
        ),
        (
            "add_source",
            {
                "notebook_id": "nb-allowed-safe",
                "idempotency_key": "idem-1",
                "source": {"type": "text", "content": "hi", "unauthorized_source_field": "bad"},
            },
        ),
    ]

    for tool_name, bad_arguments in fuzz_test_cases:
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name=tool_name,
                arguments=bad_arguments,
            ),
        )
        res = await call_entry.handler(cast(Any, None), req)
        assert isinstance(res, types.CallToolResult)
        assert res.is_error is True, f"Tool {tool_name} failed to reject unauthorized properties"
        content_item = res.content[0]
        assert isinstance(content_item, types.TextContent)
        body = json.loads(content_item.text)
        assert body["ok"] is False
        assert body["error"]["code"] == INVALID_ARGUMENT
        assert "Schema validation failed" in body["error"]["message"]


def test_secret_keystore_containment_zero_google_credentials(tmp_path: Path) -> None:
    db_file = tmp_path / "containment_test.db"
    journal = MutationJournal(db_file)
    cap_secret = b"local_pairing_secret_key_32bytes"

    # Write a mutation record
    args = {"notebook_id": "nb-1", "title": "My Note", "question": "What is AI?"}
    record = journal.prepare(
        request_key="req-containment-1",
        notebook_id="nb-1",
        operation_type=OperationType.ADD_SOURCE,
        args=args,
        capability_secret=cap_secret,
    )
    journal.transition("req-containment-1", MutationState.SENT)
    journal.transition("req-containment-1", MutationState.CONFIRMED, assigned_source_id="src-99")
    journal.close()

    # Read all raw bytes in the SQLite database file
    db_bytes = db_file.read_bytes()

    # Assert NO Google tokens or cookie identifiers exist in the binary file
    google_signatures = [
        b"SID=",
        b"HSID=",
        b"SSID=",
        b"__Secure-1PSID",
        b"SAPISID",
        b"SNlM0e",
        b"FdrFJe",
        b"ya29.",
    ]
    for sig in google_signatures:
        assert sig not in db_bytes, f"Found forbidden secret signature {sig!r} on disk!"

    # Only HMAC hash is stored
    expected_hash = compute_payload_hash(args, cap_secret).encode("ascii")
    assert expected_hash in db_bytes
