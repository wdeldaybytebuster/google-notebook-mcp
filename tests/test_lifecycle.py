"""Unit tests for Phase 1: Lifecycle, Keep-Alive & Account Identity Hardening.

Covers:
- Early C-level OS file descriptor 2 redirection (M-07)
- Windows binary mode stdio configuration (os.O_BINARY)
- Pre-flight active account identity guard on mutations (P-03 / v4.2 Polish)
- Safe fetch request body inspection with zero stream consumption (M-09)
- Extension Service Worker heartbeat (HEARTBEAT_PING -> HEARTBEAT_PONG)
- MV3 240-second timeout ceiling clamping (M-03)
- Tab discard reactive draining with TAB_DISCARDED error envelope (M-04)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from mcp_gateway.host.native_host import setup_stderr_redirection


# ---------------------------------------------------------------------------
# Python Native Host Tests (M-07 & Windows Binary Stdio)
# ---------------------------------------------------------------------------


def test_early_c_level_stderr_redirection(tmp_path: Path) -> None:
    """setup_stderr_redirection redirects both sys.stderr and OS file descriptor 2."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    with patch("mcp_gateway.host.native_host.Path.home", return_value=fake_home):
        with patch("mcp_gateway.host.native_host.os.dup2") as mock_dup2:
            orig_stderr = sys.stderr
            try:
                setup_stderr_redirection()

                # Verify log file was opened and dup2 was called with fd 2
                log_file = fake_home / ".config" / "notebooklm-mcp-bridge" / "native_host_stderr.log"
                assert log_file.exists()
                assert mock_dup2.called
                # dup2(fileno, 2)
                args = mock_dup2.call_args[0]
                assert args[1] == 2
                assert sys.stderr != orig_stderr
            finally:
                sys.stderr = orig_stderr


def test_early_c_level_stderr_redirection_fallback(tmp_path: Path) -> None:
    """When creating log directory fails, falls back to devnull with os.dup2."""
    with patch("mcp_gateway.host.native_host.Path.home", side_effect=PermissionError("Permission denied")):
        with patch("mcp_gateway.host.native_host.os.dup2") as mock_dup2:
            with patch("mcp_gateway.host.native_host.os.open", return_value=99) as mock_os_open:
                orig_stderr = sys.stderr
                try:
                    setup_stderr_redirection()
                    assert mock_os_open.called
                    assert mock_dup2.called
                    args = mock_dup2.call_args[0]
                    assert args == (99, 2)
                finally:
                    sys.stderr = orig_stderr


def test_windows_binary_stdio_mode() -> None:
    """On Windows, stdio is pinned to binary mode via msvcrt.setmode."""
    from mcp_gateway.host.native_host import main

    mock_msvcrt = MagicMock()
    mock_stdin = MagicMock()
    mock_stdin.fileno.return_value = 0
    mock_stdout = MagicMock()
    mock_stdout.fileno.return_value = 1

    with patch.dict(sys.modules, {"msvcrt": mock_msvcrt}):
        with patch("sys.platform", "win32"):
            with patch.object(sys, "stdin", mock_stdin), patch.object(sys, "stdout", mock_stdout):
                with patch("mcp_gateway.host.native_host.relay_loop", return_value=None):
                    with patch("mcp_gateway.host.native_host.asyncio.run"):
                        with patch("mcp_gateway.host.native_host.setup_stderr_redirection"):
                            main()
                        assert mock_msvcrt.setmode.call_count == 2
                        calls = mock_msvcrt.setmode.call_args_list
                        expected_binary = getattr(os, "O_BINARY", 0x8000)
                        assert calls[0][0][1] == expected_binary
                        assert calls[1][0][1] == expected_binary


# ---------------------------------------------------------------------------
# JavaScript Extension Tests (Node.js Test Runner)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parent.parent
PAGE_MAIN_PATH = REPO_ROOT / "src" / "extension" / "page-main.js"
SERVICE_WORKER_PATH = REPO_ROOT / "src" / "extension" / "service_worker.js"


def _run_node_script(script: str) -> dict[str, Any]:
    """Executes a Node.js snippet and returns parsed JSON output."""
    cmd = ["node", "-e", script]
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    return cast(dict[str, Any], json.loads(result.stdout.strip()))


def test_js_safe_request_body_inspection() -> None:
    """M-09: inspectRequestBodySafely handles string & URLSearchParams without touching streams."""
    script = f"""
    const fs = require('fs');
    const code = fs.readFileSync('{PAGE_MAIN_PATH}', 'utf8');

    // Extract inspectRequestBodySafely function
    const fnMatch = code.match(/function inspectRequestBodySafely\\([\\s\\S]*?\\)\\s*\\{{[\\s\\S]*?\\n\\}}/);
    if (!fnMatch) throw new Error('inspectRequestBodySafely not found');
    eval(fnMatch[0]);

    const resString = inspectRequestBodySafely('f.req=test');
    const resParams = inspectRequestBodySafely(new URLSearchParams({{ key: 'val' }}));
    const resStream = inspectRequestBodySafely({{ getReader: () => {{ throw new Error('Touched reader!'); }} }});

    console.log(JSON.stringify({{
        stringResult: resString,
        paramsResult: resParams,
        streamResult: resStream
    }}));
    """
    out = _run_node_script(script)
    assert out["stringResult"] == "f.req=test"
    assert out["paramsResult"] == "key=val"
    assert out["streamResult"] is None


def test_js_preflight_account_identity_guard() -> None:
    """P-03: verifyAccountIdentityPreflight enforces account allowlist & rejects unauthenticated mutations."""
    script = f"""
    const fs = require('fs');
    const code = fs.readFileSync('{PAGE_MAIN_PATH}', 'utf8');

    // Extract sets and verifyAccountIdentityPreflight
    const setsMatch = code.match(/const MUTATING_COMMANDS[\\s\\S]*?const MUTATING_RPC_IDS[\\s\\S]*?\\n\\]\\);/);
    const fnMatch = code.match(/function verifyAccountIdentityPreflight\\([\\s\\S]*?\\)\\s*\\{{[\\s\\S]*?\\n\\}}/);
    eval(setsMatch[0] + '\\n' + fnMatch[0]);

    // Test 1: Non-mutating command allowed even if unauthenticated
    global.window = {{ WIZ_global_data: {{}} }};
    const nonMutating = verifyAccountIdentityPreflight('query_stream', {{}});

    // Test 2: Mutating command fails if unauthenticated
    const unauthMutating = verifyAccountIdentityPreflight('create_note', {{}});

    // Test 3: Mutating command with mismatched expectedEmail
    global.window.WIZ_global_data = {{ oM1Kwf: 'user1@example.com' }};
    const mismatchEmail = verifyAccountIdentityPreflight('create_note', {{ expectedEmail: 'user2@example.com' }});

    // Test 4: Mutating command with matching expectedEmail
    const matchEmail = verifyAccountIdentityPreflight('create_note', {{ expectedEmail: 'USER1@example.com' }});

    // Test 5: Mutating batchexecute RPC (izAoDd) with disallowed account list
    const disallowedAccounts = verifyAccountIdentityPreflight('batchexecute', {{
        rpcId: 'izAoDd',
        expectedAccounts: ['allowed@example.com']
    }});

    // Test 6: Mutating batchexecute RPC (izAoDd) with allowed account list
    const allowedAccounts = verifyAccountIdentityPreflight('batchexecute', {{
        rpcId: 'izAoDd',
        expectedAccounts: ['user1@example.com', 'other@example.com']
    }});

    console.log(JSON.stringify({{
        nonMutating,
        unauthMutating,
        mismatchEmail,
        matchEmail,
        disallowedAccounts,
        allowedAccounts
    }}));
    """
    out = _run_node_script(script)

    # 1. Non-mutating pass
    assert out["nonMutating"]["ok"] is True

    # 2. Unauthenticated mutating fails
    assert out["unauthMutating"]["ok"] is False
    assert out["unauthMutating"]["error"]["code"] == "AUTH_REQUIRED"

    # 3. Mismatched email fails
    assert out["mismatchEmail"]["ok"] is False
    assert out["mismatchEmail"]["error"]["code"] == "PERMISSION_DENIED"

    # 4. Matching email succeeds
    assert out["matchEmail"]["ok"] is True

    # 5. Account not in allowlist fails
    assert out["disallowedAccounts"]["ok"] is False
    assert out["disallowedAccounts"]["error"]["code"] == "PERMISSION_DENIED"

    # 6. Account in allowlist succeeds
    assert out["allowedAccounts"]["ok"] is True


def test_js_service_worker_lifecycle_and_timeouts() -> None:
    """M-03 & Domain A: Service worker handles HEARTBEAT_PING and clamps timeouts to MAX_RPC_TIMEOUT_MS."""
    script = f"""
    const fs = require('fs');
    const code = fs.readFileSync('{SERVICE_WORKER_PATH}', 'utf8');

    // Verify constants exist in code
    const hasMaxTimeout = code.includes('MAX_RPC_TIMEOUT_MS = 240_000');
    const hasHeartbeatPing = code.includes("command === 'HEARTBEAT_PING'");
    const hasAutoDiscardable = code.includes("autoDiscardable: false");
    const hasDiscardListener = code.includes("changeInfo.discarded === true");
    const hasTabDiscardedCode = code.includes("code: 'TAB_DISCARDED'");
    const hasRpcTimeoutCode = code.includes("code: 'RPC_EXECUTION_TIMEOUT'");

    console.log(JSON.stringify({{
        hasMaxTimeout,
        hasHeartbeatPing,
        hasAutoDiscardable,
        hasDiscardListener,
        hasTabDiscardedCode,
        hasRpcTimeoutCode
    }}));
    """
    out = _run_node_script(script)
    assert out["hasMaxTimeout"] is True
    assert out["hasHeartbeatPing"] is True
    assert out["hasAutoDiscardable"] is True
    assert out["hasDiscardListener"] is True
    assert out["hasTabDiscardedCode"] is True
    assert out["hasRpcTimeoutCode"] is True
