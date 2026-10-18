"""Unit and integration tests for install_and_onboard.py orchestrator."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import threading
import urllib.parse
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
import pytest

import install_and_onboard as onboard


# ---------------------------------------------------------------------------
# Test 1: Resource Governance & Path Resolution
# ---------------------------------------------------------------------------


def test_enforce_edge_governance() -> None:
    onboard.enforce_edge_governance()
    assert os.environ.get("UV_THREADPOOL_SIZE") == "3"
    assert os.environ.get("OMP_NUM_THREADS") == "3"
    assert "NODE_OPTIONS" in os.environ
    assert "--max-old-space-size=1024" in os.environ["NODE_OPTIONS"]


def test_resolve_ipc_socket_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # 1. Env override via MCP_BROKER_SOCKET
    custom_sock = tmp_path / "custom.sock"
    monkeypatch.setenv("MCP_BROKER_SOCKET", str(custom_sock))
    assert onboard.resolve_ipc_socket_path() == custom_sock

    monkeypatch.delenv("MCP_BROKER_SOCKET", raising=False)
    # 2. Env override via NOTEBOOKLM_MCP_SOCKET
    monkeypatch.setenv("NOTEBOOKLM_MCP_SOCKET", str(custom_sock))
    assert onboard.resolve_ipc_socket_path() == custom_sock

    monkeypatch.delenv("NOTEBOOKLM_MCP_SOCKET", raising=False)
    # 3. Linux with XDG_RUNTIME_DIR
    xdg_dir = tmp_path / "xdg"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(xdg_dir))
    with patch("platform.system", return_value="Linux"):
        resolved = onboard.resolve_ipc_socket_path()
        assert resolved == xdg_dir / "notebooklm-mcp" / "broker.sock"


# ---------------------------------------------------------------------------
# Test 2: Extension ID Computation & Native Messaging Manifests
# ---------------------------------------------------------------------------


def test_compute_chromium_extension_id() -> None:
    data = b"/tmp/sample/path"
    ext_id = onboard.compute_chromium_extension_id(data)
    assert len(ext_id) == 32
    assert all("a" <= ch <= "p" for ch in ext_id)


def test_get_candidate_extension_ids(tmp_path: Path) -> None:
    ext_dir = tmp_path / "ext"
    ext_dir.mkdir()
    manifest_file = ext_dir / "manifest.json"
    manifest_file.write_text(json.dumps({"manifest_version": 3, "name": "Test"}), encoding="utf-8")

    candidates = onboard.get_candidate_extension_ids(ext_dir)
    assert len(candidates) >= 1
    assert all(len(cid) == 32 and all("a" <= ch <= "p" for ch in cid) for cid in candidates)


def test_write_native_host_manifests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    profile_dir = config_dir / "chrome-profile"
    monkeypatch.setattr(onboard, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(onboard, "PROFILE_DIR", profile_dir)

    project_root = tmp_path / "proj"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    host_script = project_root / "src" / "mcp_gateway" / "host" / "native_host.py"
    host_script.parent.mkdir(parents=True)
    host_script.write_text("# dummy host", encoding="utf-8")

    spec = onboard.SUPPORTED_BROWSERS[0]
    sock_path = tmp_path / "broker.sock"

    written = onboard.write_native_host_manifests(
        project_root=project_root,
        native_host_script=host_script,
        extension_ids=["abcdefghijklmnopabcdefghijklmnop"],
        selected_spec=spec,
        resolved_socket_path=sock_path,
    )

    assert len(written) >= 1
    for manifest_path in written:
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["name"] == onboard.NATIVE_HOST_NAME
        assert data["allowed_origins"] == ["chrome-extension://abcdefghijklmnopabcdefghijklmnop/"]

    launcher_path = config_dir / "native_host_launcher.py"
    if launcher_path.exists():
        content = launcher_path.read_text(encoding="utf-8")
        assert str(sock_path.resolve()) in content
        assert "MCP_BROKER_SOCKET" in content
        assert "UV_THREADPOOL_SIZE" in content


# ---------------------------------------------------------------------------
# Test 3: Browser Discovery, Garcon Rejection & Sommelier Flags
# ---------------------------------------------------------------------------


def test_garcon_detection_and_rejection() -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="garcon-url-handler.desktop\n")
        assert onboard.detect_os_default_browser() == "garcon-url-handler.desktop"

    # Verify interactive selector handles garcon and filters it out
    fake_browser = Path("/usr/bin/google-chrome-beta")
    installed = [(onboard.SUPPORTED_BROWSERS[0], fake_browser)]

    with patch("builtins.input", return_value="1"):
        spec, path = onboard.select_browser_interactively(installed, non_interactive=False)
        assert spec.key == "google-chrome-beta"
        assert path == fake_browser


def test_select_browser_non_interactive() -> None:
    fake_browser = Path("/usr/bin/google-chrome-beta")
    installed = [(onboard.SUPPORTED_BROWSERS[0], fake_browser)]
    spec, path = onboard.select_browser_interactively(installed, non_interactive=True)
    assert spec.key == "google-chrome-beta"
    assert path == fake_browser


# ---------------------------------------------------------------------------
# Test 4: Stale Socket Unlinking & SingletonLock Cleanup
# ---------------------------------------------------------------------------


def test_is_socket_live_unlinks_stale(tmp_path: Path) -> None:
    stale_sock = tmp_path / "stale.sock"
    stale_sock.touch()
    assert stale_sock.exists()

    # When connect fails with ConnectionRefusedError, is_socket_live unlinks it
    assert onboard.is_socket_live(stale_sock) is False
    assert not stale_sock.exists()


def test_cleanup_stale_singleton_locks(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    lock_file = profile_dir / "SingletonLock"
    socket_file = profile_dir / "SingletonSocket"
    cookie_file = profile_dir / "SingletonCookie"
    lock_file.touch()
    socket_file.touch()
    cookie_file.touch()

    with patch("install_and_onboard.cdp_get_json", return_value=None):
        onboard.cleanup_stale_singleton_locks(profile_dir)
        assert not lock_file.exists()
        assert not socket_file.exists()
        assert not cookie_file.exists()


# ---------------------------------------------------------------------------
# Test 5: Hardened RFC 6455 stdlib WebSocket Client
# ---------------------------------------------------------------------------


def test_cdp_ws_call_fragmentation_and_ping_pong() -> None:
    """Test stdlib WebSocket client handles continuation frames, masking, and ping/pong."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    def _mock_cdp_server() -> None:
        client, _ = server_sock.accept()
        try:
            # 1. Handshake
            req = b""
            while b"\r\n\r\n" not in req:
                chunk = client.recv(1024)
                if not chunk:
                    return
                req += chunk

            sec_key = ""
            for line in req.decode("ascii", errors="replace").splitlines():
                if line.lower().startswith("sec-websocket-key:"):
                    sec_key = line.split(":", 1)[1].strip()

            accept_key = base64.b64encode(
                hashlib.sha1((sec_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
            ).decode("ascii")

            resp = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept_key}\r\n\r\n"
            )
            client.sendall(resp.encode("ascii"))

            # 2. Read client request frame
            header = client.recv(2)
            is_masked = bool(header[1] & 0x80)
            pay_len = header[1] & 0x7F
            assert is_masked
            mask = client.recv(4)
            payload = client.recv(pay_len)
            unmasked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            req_json = json.loads(unmasked.decode("utf-8"))
            req_id = req_json.get("id")

            # 3. Send Ping frame (0x9) to client to test Pong response
            ping_data = b"keepalive-probe"
            client.sendall(bytearray([0x89, len(ping_data)]) + ping_data)

            # Read client's Pong frame (0x8A)
            pong_head = client.recv(2)
            assert pong_head[0] == 0x8A
            pong_masked = bool(pong_head[1] & 0x80)
            assert pong_masked
            pong_len = pong_head[1] & 0x7F
            pong_mask = client.recv(4)
            pong_data = client.recv(pong_len)
            pong_unmasked = bytes(b ^ pong_mask[i % 4] for i, b in enumerate(pong_data))
            assert pong_unmasked == ping_data

            # 4. Send asynchronous CDP event frame (Target.targetCreated) that should be skipped
            async_event = json.dumps({"method": "Target.targetCreated", "params": {"targetId": "xyz"}}).encode("utf-8")
            client.sendall(bytearray([0x81, len(async_event)]) + async_event)

            # 5. Send matching RPC response fragmented across two frames:
            # Frame 1: FIN=0, opcode=0x1
            # Frame 2: FIN=1, opcode=0x0 (continuation)
            full_reply = json.dumps({"id": req_id, "result": {"success": True, "value": 42}}).encode("utf-8")
            half = len(full_reply) // 2
            part1 = full_reply[:half]
            part2 = full_reply[half:]

            client.sendall(bytearray([0x01, len(part1)]) + part1)
            client.sendall(bytearray([0x80, len(part2)]) + part2)

        finally:
            client.close()
            server_sock.close()

    thread = threading.Thread(target=_mock_cdp_server, daemon=True)
    thread.start()

    ws_url = f"ws://127.0.0.1:{port}/devtools/browser/test"
    result = onboard.cdp_ws_call(ws_url, "Test.method", {"foo": "bar"}, timeout=5.0, request_id=42)

    thread.join(timeout=2.0)
    assert result.get("id") == 42
    assert result.get("result", {}).get("success") is True
    assert result.get("result", {}).get("value") == 42


# ---------------------------------------------------------------------------
# Test 6: Google Sign-In Hydration Poller
# ---------------------------------------------------------------------------


def test_wait_for_notebook_login_resilient(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def mock_cdp_get_json(endpoint: str, timeout: float = 2.5) -> Any:
        nonlocal calls
        calls += 1
        if endpoint == "/json/list":
            if calls < 2:
                # User in accounts.google.com sign-in flow
                return [{"type": "page", "url": "https://accounts.google.com/signin/v2"}]
            # Notebook page active
            return [
                {
                    "type": "page",
                    "url": "https://notebook.google.com/",
                    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/page/1",
                }
            ]
        return None

    monkeypatch.setattr(onboard, "cdp_get_json", mock_cdp_get_json)

    def mock_cdp_ws_call(ws_url: str, method: str, params: Any = None, **kwargs: Any) -> dict[str, Any]:
        return {
            "result": {
                "result": {
                    "value": {
                        "hasCsrf": True,
                        "email": "user@example.com",
                        "hasSession": True,
                        "url": "https://notebook.google.com/",
                    }
                }
            }
        }

    monkeypatch.setattr(onboard, "cdp_ws_call", mock_cdp_ws_call)

    info = onboard.wait_for_notebook_login(timeout_seconds=5)
    assert info["email"] == "user@example.com"
    assert urllib.parse.urlparse(info["url"]).hostname == "notebook.google.com"


# ---------------------------------------------------------------------------
# Test 7: Allowlist & Project Default Notebook (.notebook_mcp.json)
# ---------------------------------------------------------------------------


def test_save_project_default_notebook(tmp_path: Path) -> None:
    conf_file = onboard.save_project_default_notebook(tmp_path, "uuid-1234", "My Research Project")
    assert conf_file.exists()
    data = json.loads(conf_file.read_text(encoding="utf-8"))
    assert data["notebook_id"] == "uuid-1234"
    assert data["title"] == "My Research Project"
    assert "updated_at" in data


def test_interactive_allowlist_seeding_single_notebook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    allowlist_path = config_dir / "allowlist.json"
    monkeypatch.setattr(onboard, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(onboard, "ALLOWLIST_PATH", allowlist_path)

    discovered = [{"id": "nb-single", "title": "Single Notebook"}]

    # Single notebook non-interactive
    cfg = onboard.interactive_allowlist_seeding(
        discovered=discovered,
        active_email="user@domain.com",
        project_root=tmp_path,
        non_interactive=True,
    )

    assert "nb-single" in cfg["notebooks"]
    assert "user@domain.com" in cfg["accounts"]
    assert cfg["provider_mode"] == "browser"

    # Project default should be automatically written for single notebook
    proj_conf = tmp_path / ".notebook_mcp.json"
    assert proj_conf.exists()
    pdata = json.loads(proj_conf.read_text(encoding="utf-8"))
    assert pdata["notebook_id"] == "nb-single"


def test_interactive_allowlist_seeding_multiple_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    allowlist_path = config_dir / "allowlist.json"
    monkeypatch.setattr(onboard, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(onboard, "ALLOWLIST_PATH", allowlist_path)

    discovered = [
        {"id": "nb-1", "title": "First Notebook"},
        {"id": "nb-2", "title": "Second Notebook"},
    ]

    # Select both notebooks ("all"), then choose default as [2]
    inputs = iter(["all", "2"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    cfg = onboard.interactive_allowlist_seeding(
        discovered=discovered,
        active_email="admin@example.com",
        project_root=tmp_path,
        non_interactive=False,
    )

    assert set(cfg["notebooks"]) == {"nb-1", "nb-2"}
    assert "admin@example.com" in cfg["accounts"]

    proj_conf = tmp_path / ".notebook_mcp.json"
    assert proj_conf.exists()
    pdata = json.loads(proj_conf.read_text(encoding="utf-8"))
    assert pdata["notebook_id"] == "nb-2"
