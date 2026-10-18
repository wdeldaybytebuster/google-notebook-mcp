#!/usr/bin/env python3
"""Zero-Friction Cross-Platform Installer & Onboarding Orchestrator.

Google Gemini Notebook (NotebookLM) MCP Gateway (`gemini-notebook-mcp`)
=======================================================================
Enforces all project architectural and security invariants (AGENTS.md):
1. Zero Credential Export: All authentication stays inside the browser's
   hardware-TPM / DBSC network stack. No cookies or tokens touch disk or IPC.
2. Controlled Python Execution: Pure Python 3.11+ standard-library orchestrator
   (no raw `.sh` scripts) with a built-in RFC 6455 WebSocket client for CDP so
   it runs before or after virtualenv setup.
3. Edge Resource Governance: Enforces UV_THREADPOOL_SIZE=3, OMP_NUM_THREADS=3,
   NODE_OPTIONS="--max-old-space-size=1024 --max-semi-space-size=128", and RLIMIT_NOFILE=65536.
4. Automated 6-Stage Onboarding:
   - Stage 1: OS Default Browser Detection & 6-Browser Registry Fallback Prompt
              (with Crostini Garcon Bridge rejection & Sommelier Wayland guards)
   - Stage 2: Native Messaging Host Manifest Registration (Global + Sandbox + WinReg)
              with baked socket path & resource caps into native host launcher
   - Stage 3: Broker Daemon Startup (with stale socket unlinking & SingletonLock cleanup)
              and Dedicated Browser Launch
   - Stage 4: Automated MV3 Extension Injection (`--load-extension` + CDP
              `Extensions.loadUnpacked` for Chrome 137+ + Guided UI Fallback)
              with forced re-handshake on dynamic extension ID drift
   - Stage 5: Resilient Google Sign-In Detection & `WIZ_global_data` Hydration Poll
   - Stage 6: Dual-Channel Notebook Discovery (`wXbhsf` live wire payload) &
              Interactive Allowlist Seeding with `.notebook_mcp.json` binding
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 1. Constants & Platform IPC Path Resolution
# ---------------------------------------------------------------------------

NATIVE_HOST_NAME = "com.mcp.gemini.broker"
CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
NOTEBOOK_URL = "https://notebook.google.com/"
CONFIG_DIR = Path.home() / ".config" / "notebooklm-mcp-bridge"
PROFILE_DIR = CONFIG_DIR / "chrome-profile"
ALLOWLIST_PATH = CONFIG_DIR / "allowlist.json"


def resolve_ipc_socket_path() -> Path:
    """Resolve the canonical cross-platform Broker IPC socket path.

    Matches mcp_gateway.transport.paths.get_default_ipc_path() logic:
    1. MCP_BROKER_SOCKET or NOTEBOOKLM_MCP_SOCKET environment variable
    2. Windows: \\\\.\\pipe\\notebooklm-mcp-broker
    3. macOS: ~/Library/Application Support/notebooklm-mcp/broker.sock
    4. Linux: $XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock (fallback: ~/.config/notebooklm-mcp-bridge/broker.sock)
    """
    env_override = os.environ.get("MCP_BROKER_SOCKET") or os.environ.get("NOTEBOOKLM_MCP_SOCKET")
    if env_override:
        return Path(env_override)

    sys_name = platform.system()
    if sys_name == "Windows":
        return Path(r"\\.\pipe\notebooklm-mcp-broker")
    elif sys_name == "Darwin":
        base_dir = Path.home() / "Library" / "Application Support" / "notebooklm-mcp"
    else:
        xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
        if xdg_runtime:
            base_dir = Path(xdg_runtime) / "notebooklm-mcp"
        else:
            base_dir = CONFIG_DIR

    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(base_dir, 0o700)
    except OSError:
        pass

    return base_dir / "broker.sock"


@dataclass(frozen=True)
class BrowserSpec:
    """Metadata for a supported Chromium-family browser."""

    key: str
    display_name: str
    linux_bins: tuple[str, ...]
    macos_app: str
    windows_rel_paths: tuple[str, ...]
    linux_nm_dir: str
    macos_nm_dir: str
    windows_reg_key: str
    desktop_ids: tuple[str, ...]


SUPPORTED_BROWSERS: tuple[BrowserSpec, ...] = (
    BrowserSpec(
        key="google-chrome-beta",
        display_name="Google Chrome Beta (Recommended for Linux / ChromeOS Crostini)",
        linux_bins=(
            "/usr/bin/google-chrome-beta",
            "/opt/google/chrome-beta/chrome",
            "google-chrome-beta",
        ),
        macos_app="/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
        windows_rel_paths=(r"Google\Chrome Beta\Application\chrome.exe",),
        linux_nm_dir=".config/google-chrome-beta/NativeMessagingHosts",
        macos_nm_dir="Library/Application Support/Google/Chrome Beta/NativeMessagingHosts",
        windows_reg_key=r"Software\Google\Chrome Beta\NativeMessagingHosts",
        desktop_ids=("google-chrome-beta.desktop",),
    ),
    BrowserSpec(
        key="google-chrome",
        display_name="Google Chrome (Stable)",
        linux_bins=(
            "/usr/bin/google-chrome-stable",
            "/usr/bin/google-chrome",
            "/opt/google/chrome/chrome",
            "google-chrome",
        ),
        macos_app="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        windows_rel_paths=(r"Google\Chrome\Application\chrome.exe",),
        linux_nm_dir=".config/google-chrome/NativeMessagingHosts",
        macos_nm_dir="Library/Application Support/Google/Chrome/NativeMessagingHosts",
        windows_reg_key=r"Software\Google\Chrome\NativeMessagingHosts",
        desktop_ids=("google-chrome.desktop", "com.google.Chrome.desktop"),
    ),
    BrowserSpec(
        key="chromium",
        display_name="Chromium",
        linux_bins=(
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "chromium",
            "chromium-browser",
        ),
        macos_app="/Applications/Chromium.app/Contents/MacOS/Chromium",
        windows_rel_paths=(r"Chromium\Application\chrome.exe",),
        linux_nm_dir=".config/chromium/NativeMessagingHosts",
        macos_nm_dir="Library/Application Support/Chromium/NativeMessagingHosts",
        windows_reg_key=r"Software\Chromium\NativeMessagingHosts",
        desktop_ids=("chromium.desktop", "org.chromium.Chromium.desktop"),
    ),
    BrowserSpec(
        key="brave",
        display_name="Brave Browser",
        linux_bins=(
            "/usr/bin/brave-browser",
            "/usr/bin/brave",
            "brave-browser",
            "brave",
        ),
        macos_app="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        windows_rel_paths=(r"BraveSoftware\Brave-Browser\Application\brave.exe",),
        linux_nm_dir=".config/BraveSoftware/Brave-Browser/NativeMessagingHosts",
        macos_nm_dir="Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts",
        windows_reg_key=r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
        desktop_ids=("brave-browser.desktop", "com.brave.Browser.desktop"),
    ),
    BrowserSpec(
        key="edge",
        display_name="Microsoft Edge (Stable)",
        linux_bins=(
            "/usr/bin/microsoft-edge-stable",
            "/usr/bin/microsoft-edge",
            "microsoft-edge",
        ),
        macos_app="/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        windows_rel_paths=(r"Microsoft\Edge\Application\msedge.exe",),
        linux_nm_dir=".config/microsoft-edge/NativeMessagingHosts",
        macos_nm_dir="Library/Application Support/Microsoft Edge/NativeMessagingHosts",
        windows_reg_key=r"Software\Microsoft\Edge\NativeMessagingHosts",
        desktop_ids=("microsoft-edge.desktop", "com.microsoft.Edge.desktop"),
    ),
    BrowserSpec(
        key="edge-beta",
        display_name="Microsoft Edge Beta",
        linux_bins=(
            "/usr/bin/microsoft-edge-beta",
            "microsoft-edge-beta",
        ),
        macos_app="/Applications/Microsoft Edge Beta.app/Contents/MacOS/Microsoft Edge Beta",
        windows_rel_paths=(r"Microsoft\Edge Beta\Application\msedge.exe",),
        linux_nm_dir=".config/microsoft-edge-beta/NativeMessagingHosts",
        macos_nm_dir="Library/Application Support/Microsoft Edge Beta/NativeMessagingHosts",
        windows_reg_key=r"Software\Microsoft\Edge Beta\NativeMessagingHosts",
        desktop_ids=("microsoft-edge-beta.desktop",),
    ),
)


def enforce_edge_governance() -> None:
    """Apply strict thread, heap, core-affinity, and file-descriptor bounds (ADR-008)."""
    os.environ.setdefault("UV_THREADPOOL_SIZE", "3")
    os.environ.setdefault("OMP_NUM_THREADS", "3")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "3")
    os.environ.setdefault("MKL_NUM_THREADS", "3")
    node_opts = os.environ.get("NODE_OPTIONS", "")
    if "--max-old-space-size" not in node_opts:
        os.environ["NODE_OPTIONS"] = (
            f"{node_opts} --max-old-space-size=1024 --max-semi-space-size=128".strip()
        )

    if platform.system() != "Windows":
        # Restrict CPU affinity to cores 0-5 on Linux with > 6 cores
        if hasattr(os, "sched_setaffinity") and hasattr(os, "sched_getaffinity"):
            try:
                available_cores = os.sched_getaffinity(0)
                if len(available_cores) > 6:
                    target_cores = set(range(min(6, os.cpu_count() or 6)))
                    os.sched_setaffinity(0, target_cores)
            except (OSError, ValueError, AttributeError):
                pass

        try:
            import resource

            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            target = min(65536, hard) if hard != resource.RLIM_INFINITY else 65536
            if soft < target:
                resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 2. Hardened RFC 6455 Localhost WebSocket Client (for CDP)
# ---------------------------------------------------------------------------


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes from sock or raise EOFError."""
    buf = bytearray()
    while len(buf) < n:
        part = sock.recv(n - len(buf))
        if not part:
            raise EOFError("Socket closed while reading WebSocket frame")
        buf.extend(part)
    return bytes(buf)


def cdp_ws_call(
    ws_url: str,
    method: str,
    params: dict[str, Any] | None = None,
    timeout: float = 12.0,
    request_id: int = 1,
) -> dict[str, Any]:
    """Execute a single JSON-RPC call over local CDP WebSocket using stdlib only.

    Hardened per RFC 6455:
    - 4-byte random client frame masking
    - Continuation frame accumulation (FIN == 0 + opcode 0x0)
    - Automated masked Pong (0x8A) reply echoing Ping payload (RFC 6455 §5.5.3)
    - Skips unrequested CDP asynchronous events and awaits matching request_id
    """
    parsed = urllib.parse.urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9222
    path = parsed.path or "/"

    raw_key = base64.b64encode(os.urandom(16)).decode("ascii")
    handshake = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {raw_key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )

    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(handshake.encode("ascii"))
        header_buf = b""
        while b"\r\n\r\n" not in header_buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("CDP WebSocket closed during handshake")
            header_buf += chunk

        # Send masked JSON-RPC request frame
        payload_bytes = json.dumps(
            {"id": request_id, "method": method, "params": params or {}}
        ).encode("utf-8")
        mask_key = os.urandom(4)
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload_bytes))

        frame = bytearray([0x81])  # FIN=1, Text frame (0x1)
        length = len(payload_bytes)
        if length < 126:
            frame.append(0x80 | length)
        elif length < 65536:
            frame.append(0x80 | 126)
            frame.extend(struct.pack(">H", length))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack(">Q", length))
        frame.extend(mask_key)
        frame.extend(masked)
        sock.sendall(frame)

        # Receive frames with continuation assembly
        msg_buf = bytearray()
        while True:
            first_two = _recv_exact(sock, 2)
            fin = bool(first_two[0] & 0x80)
            opcode = first_two[0] & 0x0F
            is_masked = bool(first_two[1] & 0x80)
            pay_len = first_two[1] & 0x7F

            if pay_len == 126:
                pay_len = struct.unpack(">H", _recv_exact(sock, 2))[0]
            elif pay_len == 127:
                pay_len = struct.unpack(">Q", _recv_exact(sock, 8))[0]

            srv_mask = _recv_exact(sock, 4) if is_masked else b""
            data = _recv_exact(sock, pay_len)
            if is_masked:
                data = bytes(b ^ srv_mask[i % 4] for i, b in enumerate(data))

            # Opcode 0x8: Close
            if opcode == 0x8:
                raise RuntimeError("CDP WebSocket connection closed by browser")

            # Opcode 0x9: Ping -> Respond with masked Pong echoing data (RFC 6455 §5.5.3)
            if opcode == 0x9:
                pong_mask = os.urandom(4)
                pong_masked = bytes(b ^ pong_mask[i % 4] for i, b in enumerate(data))
                pong_frame = bytearray([0x8A])
                p_len = len(data)
                if p_len < 126:
                    pong_frame.append(0x80 | p_len)
                elif p_len < 65536:
                    pong_frame.append(0x80 | 126)
                    pong_frame.extend(struct.pack(">H", p_len))
                else:
                    pong_frame.append(0x80 | 127)
                    pong_frame.extend(struct.pack(">Q", p_len))
                pong_frame.extend(pong_mask)
                pong_frame.extend(pong_masked)
                sock.sendall(pong_frame)
                continue

            # Opcode 0x1: Initial Text frame or Opcode 0x0: Continuation frame
            if opcode in (0x1, 0x0):
                msg_buf.extend(data)
                if fin:
                    full_text = msg_buf.decode("utf-8", errors="replace")
                    msg_buf.clear()
                    try:
                        msg = json.loads(full_text)
                    except Exception:
                        continue
                    # Check if matching our request ID
                    if isinstance(msg, dict) and msg.get("id") == request_id:
                        return msg
                continue


# ---------------------------------------------------------------------------
# 3. Default Browser Detection & 6-Browser Registry Discovery
# ---------------------------------------------------------------------------


def find_installed_browsers() -> list[tuple[BrowserSpec, Path]]:
    """Return all installed compatible browsers from the 6-browser registry."""
    sys_name = platform.system()
    installed: list[tuple[BrowserSpec, Path]] = []

    for spec in SUPPORTED_BROWSERS:
        if sys_name == "Linux":
            for candidate in spec.linux_bins:
                resolved = (
                    shutil.which(candidate)
                    if not candidate.startswith("/")
                    else (candidate if os.access(candidate, os.X_OK) else None)
                )
                if resolved:
                    path_obj = Path(resolved).resolve()
                    if "garcon" in str(path_obj).lower():
                        continue
                    installed.append((spec, path_obj))
                    break
        elif sys_name == "Darwin":
            app_path = Path(spec.macos_app)
            if app_path.exists() and os.access(app_path, os.X_OK):
                installed.append((spec, app_path))
        elif sys_name == "Windows":
            roots = [
                os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                os.environ.get("LOCALAPPDATA", ""),
            ]
            for root in roots:
                if not root:
                    continue
                for rel in spec.windows_rel_paths:
                    candidate_path = Path(root) / rel
                    if candidate_path.exists():
                        installed.append((spec, candidate_path))
                        break
                else:
                    continue
                break

    return installed


def detect_os_default_browser() -> str | None:
    """Detect the operating system's current default web browser identifier."""
    sys_name = platform.system()
    try:
        if sys_name == "Linux":
            res = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
            env_browser = os.environ.get("BROWSER")
            if env_browser:
                return env_browser.strip()
        elif sys_name == "Darwin":
            res = subprocess.run(
                [
                    "defaults",
                    "read",
                    "com.apple.LaunchServices/com.apple.launchservices.secure",
                    "LSHandlers",
                ],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
            if res.returncode == 0 and res.stdout:
                return res.stdout.lower()
        elif sys_name == "Windows":
            import winreg  # type: ignore[import-not-found]

            key_path = (
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
            )
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:  # type: ignore[attr-defined]
                prog_id, _ = winreg.QueryValueEx(key, "ProgId")  # type: ignore[attr-defined]
                return str(prog_id)
    except Exception:
        pass
    return None


def select_browser_interactively(
    installed: list[tuple[BrowserSpec, Path]],
    preferred_key: str | None = None,
    non_interactive: bool = False,
) -> tuple[BrowserSpec, Path]:
    """Match OS default browser or ask the user to choose from available browsers."""
    if not installed:
        print("\n[!] ERROR: No compatible Chromium-family browser was found on this system.")
        print(
            "    Supported browsers: Google Chrome Beta, Google Chrome, Chromium, Brave, Microsoft Edge."
        )
        print("    On Debian/Ubuntu/Crostini, install Chrome Beta or Chromium:")
        print("      sudo apt-get update && sudo apt-get install -y chromium")
        sys.exit(1)

    if preferred_key:
        for spec, path in installed:
            if spec.key == preferred_key:
                print(f"[+] Using explicitly requested browser: {spec.display_name} ({path})")
                return spec, path

    os_default = detect_os_default_browser()
    print(f"[*] Detected OS default browser setting: {os_default or 'Unknown / Unset'}")

    is_garcon = bool(
        os_default and ("garcon" in os_default.lower() or "host" in os_default.lower())
    )
    if is_garcon:
        print("    [!] Note: OS default browser points to the ChromeOS Garcon host bridge.")
        print(
            "        The MCP gateway requires a container-local browser to bind the local Unix socket."
        )

    if os_default and not is_garcon:
        os_def_lower = os_default.lower()
        for spec, path in installed:
            if (
                any(did.lower() in os_def_lower for did in spec.desktop_ids)
                or spec.key in os_def_lower
            ):
                print(f"[+] Default browser is compatible: {spec.display_name} ({path})")
                return spec, path

    if len(installed) == 1 and non_interactive:
        spec, path = installed[0]
        print(f"[+] Auto-selected sole compatible browser: {spec.display_name} ({path})")
        return spec, path

    print("\n=========================================================================")
    if not os_default or is_garcon:
        print(" Your default browser cannot be used directly for local Native Messaging.")
    else:
        print(f" Your default browser ('{os_default}') is not in the compatible MV3 list.")
    print(" Please select which installed compatible browser to use with the project:")
    print("=========================================================================")

    for idx, (spec, path) in enumerate(installed, start=1):
        rec = " [RECOMMENDED]" if idx == 1 else ""
        print(f"  [{idx}] {spec.display_name}{rec}")
        print(f"      Binary: {path}")

    if non_interactive:
        spec, path = installed[0]
        print(f"[+] Non-interactive mode: selecting [1] {spec.display_name}")
        return spec, path

    while True:
        choice = input(f"\nEnter choice [1-{len(installed)}] (default: 1): ").strip()
        if not choice:
            return installed[0]
        if choice.isdigit() and 1 <= int(choice) <= len(installed):
            return installed[int(choice) - 1]
        print(
            f"  [!] Invalid selection '{choice}'. Please enter a number between 1 and {len(installed)}."
        )


# ---------------------------------------------------------------------------
# 4. Extension ID Calculation & Native Messaging Host Registration
# ---------------------------------------------------------------------------


def compute_chromium_extension_id(data: bytes) -> str:
    """Compute Chrome's 32-character a-p extension ID from public key or path bytes."""
    digest = hashlib.sha256(data).hexdigest()[:32]
    return "".join(chr(ord("a") + int(ch, 16)) for ch in digest)


def get_candidate_extension_ids(extension_dir: Path) -> list[str]:
    """Derive deterministic candidate extension IDs from manifest key and path."""
    candidates: list[str] = []
    manifest_path = extension_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest.get("key"), str):
                der_bytes = base64.b64decode(manifest["key"])
                candidates.append(compute_chromium_extension_id(der_bytes))
        except Exception:
            pass

    resolved_str = str(extension_dir.resolve())
    candidates.append(compute_chromium_extension_id(resolved_str.encode("utf-8")))
    return list(dict.fromkeys(candidates))


def write_native_host_manifests(
    project_root: Path,
    native_host_script: Path,
    extension_ids: list[str],
    selected_spec: BrowserSpec,
    resolved_socket_path: Path,
) -> list[Path]:
    """Register `com.mcp.gemini.broker.json` in global browser + isolated sandbox profile.

    Bakes resolved socket path and resource caps into native_host_launcher wrapper
    so Chrome subprocesses inherit configuration without terminal environment variables.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)

    venv_python = project_root / ".venv" / "bin" / "python"
    python_exe = str(venv_python if venv_python.exists() else Path(sys.executable).resolve())

    sock_str = str(resolved_socket_path.resolve())

    if platform.system() == "Windows":
        wrapper_path = CONFIG_DIR / "native_host_launcher.cmd"
        wrapper_content = (
            f"@echo off\r\n"
            f'SET "MCP_BROKER_SOCKET={sock_str}"\r\n'
            f'SET "NOTEBOOKLM_MCP_SOCKET={sock_str}"\r\n'
            f'SET "UV_THREADPOOL_SIZE=3"\r\n'
            f'SET "OMP_NUM_THREADS=3"\r\n'
            f'"{python_exe}" -u "{native_host_script.resolve()}" %*\r\n'
        )
        wrapper_path.write_text(wrapper_content, encoding="utf-8")
    else:
        wrapper_path = CONFIG_DIR / "native_host_launcher.py"
        wrapper_content = (
            f"#!{python_exe}\n"
            "import os, runpy, sys\n"
            f"os.environ.setdefault('MCP_BROKER_SOCKET', {repr(sock_str)})\n"
            f"os.environ.setdefault('NOTEBOOKLM_MCP_SOCKET', {repr(sock_str)})\n"
            "os.environ.setdefault('UV_THREADPOOL_SIZE', '3')\n"
            "os.environ.setdefault('OMP_NUM_THREADS', '3')\n"
            f"sys.path.insert(0, {repr(str((project_root / 'src').resolve()))})\n"
            f"runpy.run_path({repr(str(native_host_script.resolve()))}, run_name='__main__')\n"
        )
        wrapper_path.write_text(wrapper_content, encoding="utf-8")
        os.chmod(wrapper_path, 0o700)

    allowed_origins = [f"chrome-extension://{ext_id}/" for ext_id in extension_ids if ext_id]
    manifest_payload = {
        "name": NATIVE_HOST_NAME,
        "description": "Google Gemini Notebook MCP Native Messaging Bridge",
        "path": str(wrapper_path.resolve()),
        "type": "stdio",
        "allowed_origins": allowed_origins,
    }

    target_dirs: list[Path] = [
        PROFILE_DIR / "NativeMessagingHosts",
        PROFILE_DIR / "Default" / "NativeMessagingHosts",
    ]
    sys_name = platform.system()
    if sys_name == "Linux":
        for spec in SUPPORTED_BROWSERS:
            nm_dir = Path.home() / spec.linux_nm_dir
            if spec.key == selected_spec.key or nm_dir.parent.exists():
                target_dirs.append(nm_dir)
    elif sys_name == "Darwin":
        for spec in SUPPORTED_BROWSERS:
            nm_dir = Path.home() / spec.macos_nm_dir
            if spec.key == selected_spec.key or nm_dir.parent.exists():
                target_dirs.append(nm_dir)

    written_paths: list[Path] = []
    for tdir in dict.fromkeys(target_dirs):
        try:
            tdir.mkdir(parents=True, exist_ok=True)
            manifest_file = tdir / f"{NATIVE_HOST_NAME}.json"
            manifest_file.write_text(
                json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8"
            )
            written_paths.append(manifest_file)
        except Exception as exc:
            print(f"  [!] Warning: Could not write manifest to {tdir}: {exc}")

    # On Windows, register manifest in registry for the browser family
    if sys_name == "Windows" and written_paths:
        manifest_win_path = str(written_paths[0].resolve())
        try:
            import winreg  # type: ignore[import-not-found]

            for spec in SUPPORTED_BROWSERS:
                reg_sub = rf"{spec.windows_reg_key}\{NATIVE_HOST_NAME}"
                try:
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_sub) as key:  # type: ignore[attr-defined]
                        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, manifest_win_path)  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:
            pass

    return written_paths


# ---------------------------------------------------------------------------
# 5. Process Supervisor, Stale Lock Cleaning & CDP Auth Poller
# ---------------------------------------------------------------------------


def cdp_get_json(endpoint: str, timeout: float = 2.5) -> Any:
    """Query `http://127.0.0.1:9222/json...` and return parsed JSON or None."""
    url = f"http://{CDP_HOST}:{CDP_PORT}{endpoint}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def cleanup_stale_singleton_locks(profile_dir: Path) -> None:
    """Unlink stale Singleton symlinks in profile_dir if CDP is unreachable."""
    if cdp_get_json("/json/version") is not None:
        return  # Active browser running, do not touch locks

    for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        lock_path = profile_dir / lock_name
        if lock_path.is_symlink() or lock_path.exists():
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass


def is_socket_live(socket_path: Path) -> bool:
    """Probe if socket_path is listening and responding to connections."""
    if platform.system() == "Windows":
        return socket_path.exists()

    if not socket_path.exists():
        return False

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        sock.connect(str(socket_path))
        sock.close()
        return True
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        try:
            socket_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def ensure_extension_loaded_via_cdp(extension_dir: Path) -> str | None:
    """Confirm extension service worker is active or inject via CDP `Extensions.loadUnpacked`."""
    targets = cdp_get_json("/json") or []
    for t in targets:
        url = str(t.get("url", ""))
        if url.startswith("chrome-extension://") and "service_worker.js" in url:
            ext_id = url.split("/")[2]
            return ext_id

    ver_info = cdp_get_json("/json/version")
    if isinstance(ver_info, dict) and ver_info.get("webSocketDebuggerUrl"):
        ws_url = str(ver_info["webSocketDebuggerUrl"])
        try:
            res = cdp_ws_call(
                ws_url,
                "Extensions.loadUnpacked",
                {"path": str(extension_dir.resolve())},
                timeout=8.0,
            )
            ext_id = res.get("result", {}).get("id")
            if isinstance(ext_id, str) and ext_id:
                print(f"[+] Automatically injected unpacked extension via CDP (ID: {ext_id})")
                return ext_id
        except Exception as exc:
            print(f"  [*] CDP Extensions.loadUnpacked note: {exc}")

    return None


def force_service_worker_reconnect(extension_dir: Path) -> None:
    """Trigger extension re-handshake so service_worker.js connects immediately."""
    ver_info = cdp_get_json("/json/version")
    if isinstance(ver_info, dict) and ver_info.get("webSocketDebuggerUrl"):
        ws_url = str(ver_info["webSocketDebuggerUrl"])
        try:
            cdp_ws_call(
                ws_url,
                "Extensions.loadUnpacked",
                {"path": str(extension_dir.resolve())},
                timeout=4.0,
            )
        except Exception:
            pass


def guide_manual_extension_load_if_needed(extension_dir: Path) -> str | None:
    """Open `chrome://extensions` and guide the user if automated flags were blocked."""
    print("\n=========================================================================")
    print(" ACTION REQUIRED: Enable Companion Extension")
    print("=========================================================================")
    print(" Your browser blocked command-line unpacked extension injection.")
    print(" Opening chrome://extensions for you now. Please complete these 3 clicks:")
    print("   1. Toggle ON 'Developer mode' (top-right corner of chrome://extensions)")
    print("   2. Click 'Load unpacked' (top-left button)")
    print(f"   3. Select this folder: {extension_dir.resolve()}")
    print("=========================================================================")

    try:
        urllib.request.urlopen(
            urllib.request.Request(
                f"http://{CDP_HOST}:{CDP_PORT}/json/new?chrome://extensions", method="PUT"
            ),
            timeout=3.0,
        )
    except Exception:
        pass

    print("[*] Waiting for extension service_worker.js to register...")
    for _ in range(90):
        targets = cdp_get_json("/json") or []
        for t in targets:
            url = str(t.get("url", ""))
            if url.startswith("chrome-extension://") and "service_worker.js" in url:
                ext_id = url.split("/")[2]
                print(f"[+] Companion extension detected! (ID: {ext_id})")
                return ext_id
        time.sleep(2.0)
    return None


def wait_for_notebook_login(timeout_seconds: int = 300) -> dict[str, str]:
    """Verify Google Sign-In state on `notebook.google.com` and extract account email (`oM1Kwf`)."""
    print("\n[*] Checking Google Gemini Notebook authentication state...")
    start = time.time()
    prompted_user = False

    while time.time() - start < timeout_seconds:
        pages = [p for p in (cdp_get_json("/json/list") or []) if p.get("type") == "page"]
        is_signin = any(
            "accounts.google.com" in str(p.get("url", ""))
            and any(
                k in str(p.get("url", ""))
                for k in ("/signin", "/ServiceLogin", "/v3/signin", "/CheckCookie")
            )
            for p in pages
        )
        notebook_pages = [
            p
            for p in pages
            if (
                "notebook.google.com" in str(p.get("url", ""))
                or "notebooklm.google.com" in str(p.get("url", ""))
            )
            and "accounts.google.com" not in str(p.get("url", ""))
        ]

        if not is_signin and notebook_pages:
            target_ws = notebook_pages[0].get("webSocketDebuggerUrl")
            if isinstance(target_ws, str):
                try:
                    eval_res = cdp_ws_call(
                        target_ws,
                        "Runtime.evaluate",
                        {
                            "expression": (
                                "(() => {"
                                "  const w = window.WIZ_global_data || {};"
                                "  return {"
                                "    hasCsrf: Boolean(w.SNlM0e),"
                                "    email: w.oM1Kwf || '',"
                                "    hasSession: Boolean(w.FdrFJe),"
                                "    url: location.href"
                                "  };"
                                "})()"
                            ),
                            "returnByValue": True,
                        },
                        timeout=4.0,
                    )
                    val = eval_res.get("result", {}).get("result", {}).get("value", {})
                    if isinstance(val, dict) and val.get("hasCsrf"):
                        email = str(val.get("email") or "")
                        # If email not yet populated but session confirmed, allow 2 extra ticks
                        if not email and val.get("hasSession"):
                            time.sleep(1.0)
                            continue
                        print(f"[+] Authenticated session verified on {val.get('url')}!")
                        if email:
                            print(f"[+] Active Google Account (oM1Kwf): {email}")
                        return {"email": email, "url": str(val.get("url", NOTEBOOK_URL))}
                except Exception:
                    pass

        if not prompted_user:
            prompted_user = True
            print("\n=========================================================================")
            print(" ACTION REQUIRED: Sign in to Google Gemini Notebook")
            print("=========================================================================")
            print(" A browser window has opened to https://notebook.google.com/")
            print(" Please complete your Google Sign-In (and 2FA/Passkey if prompted).")
            print(" Zero credentials or cookies leave your browser. This installer will")
            print(" automatically detect when your NotebookLM homepage finishes loading.")
            print("=========================================================================")
            if not pages:
                try:
                    urllib.request.urlopen(
                        urllib.request.Request(
                            f"http://{CDP_HOST}:{CDP_PORT}/json/new?{NOTEBOOK_URL}",
                            method="PUT",
                        ),
                        timeout=3.0,
                    )
                except Exception:
                    pass

        time.sleep(2.5)

    raise TimeoutError("Timed out waiting for Google Sign-In on notebook.google.com.")


# ---------------------------------------------------------------------------
# 6. Notebook Discovery (`wXbhsf`) & Interactive Allowlist Seeding
# ---------------------------------------------------------------------------


async def query_broker_ipc(
    socket_path: Path, payload: dict[str, Any], timeout: float = 20.0
) -> dict[str, Any]:
    """Send a big-endian 32-bit length-prefixed command to the local Policy Broker."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(str(socket_path)), timeout=timeout
    )
    try:
        raw = json.dumps(payload).encode("utf-8")
        writer.write(struct.pack(">I", len(raw)) + raw)
        await writer.drain()

        len_bytes = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
        (resp_len,) = struct.unpack(">I", len_bytes)
        resp_bytes = await asyncio.wait_for(reader.readexactly(resp_len), timeout=timeout)
        return dict(json.loads(resp_bytes.decode("utf-8")))
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def discover_notebooks_via_cdp_fallback() -> list[dict[str, str]]:
    """Fallback: query `wXbhsf` in the authenticated tab if broker IPC is unseeded.

    Uses Google's verified live wire payload [null, 1, null, [2]] and parses wrb.fr
    records inside the browser's MAIN world to return a compact [{id, title}] list.
    """
    pages = [p for p in (cdp_get_json("/json/list") or []) if p.get("type") == "page"]
    notebook_pages = [
        p
        for p in pages
        if "notebook.google.com" in str(p.get("url", ""))
        or "notebooklm.google.com" in str(p.get("url", ""))
    ]
    if not notebook_pages or not notebook_pages[0].get("webSocketDebuggerUrl"):
        return []

    ws_url = str(notebook_pages[0]["webSocketDebuggerUrl"])
    js_expr = """
    (async () => {
      const w = window.WIZ_global_data || {};
      const at = w.SNlM0e;
      const fsid = w.FdrFJe || '';
      const bl = w.cfb2h || '';
      const m = location.pathname.match(/\\/u\\/(\\d+)\\//);
      const authuser = m ? m[1] : '0';
      if (!at) return [];
      const u = new URL(location.origin + '/u/' + authuser + '/_/LabsTailwindUi/data/batchexecute');
      u.searchParams.set('rpcids', 'wXbhsf');
      u.searchParams.set('source-path', '/');
      u.searchParams.set('hl', 'en');
      if (fsid) u.searchParams.set('f.sid', fsid);
      if (bl) u.searchParams.set('bl', bl);
      u.searchParams.set('rt', 'c');
      const body = new URLSearchParams();
      // Google live wire payload: [2] is filter enum returning all user notebooks
      body.set('f.req', JSON.stringify([[['wXbhsf', JSON.stringify([null, 1, null, [2]]), null, 'generic']]]));
      body.set('at', at);
      const resp = await fetch(u.toString(), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
          'X-Same-Domain': '1'
        },
        body: body.toString(),
        credentials: 'include'
      });
      const text = await resp.text();
      const notebooks = [];
      for (const line of text.split('\\n')) {
        if (!line.startsWith('[[')) continue;
        try {
          const outer = JSON.parse(line);
          for (const item of outer) {
            if (Array.isArray(item) && item[0] === 'wrb.fr' && item[1] === 'wXbhsf' && typeof item[2] === 'string') {
              const inner = JSON.parse(item[2]);
              const rows = Array.isArray(inner?.[0]) ? inner[0] : [];
              for (const r of rows) {
                if (Array.isArray(r) && typeof r[0] === 'string' && typeof r[2] === 'string') {
                  notebooks.push({ id: r[2], title: r[0] });
                }
              }
            }
          }
        } catch (e) {}
      }
      return notebooks;
    })()
    """
    try:
        res = cdp_ws_call(
            ws_url,
            "Runtime.evaluate",
            {"expression": js_expr, "awaitPromise": True, "returnByValue": True},
            timeout=15.0,
        )
        val = res.get("result", {}).get("result", {}).get("value", [])
        if isinstance(val, list):
            return [
                {"id": str(item["id"]), "title": str(item.get("title") or "Untitled")}
                for item in val
                if isinstance(item, dict) and item.get("id")
            ]
    except Exception:
        pass
    return []


def load_existing_allowlist() -> dict[str, Any]:
    """Load `~/.config/notebooklm-mcp-bridge/allowlist.json` or initialize empty structure."""
    if ALLOWLIST_PATH.exists():
        try:
            data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"version": 1, "provider_mode": "browser", "notebooks": [], "accounts": []}


def save_allowlist_atomic(allowlist_data: dict[str, Any]) -> None:
    """Atomically persist `allowlist.json` with `0o600` owner-only permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=".allowlist-", dir=str(CONFIG_DIR), text=True)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(allowlist_data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(ALLOWLIST_PATH)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def save_project_default_notebook(
    project_root: Path, notebook_id: str, title: str
) -> Path:
    """Persist active notebook into `.notebook_mcp.json` in the project directory."""
    config_path = project_root / ".notebook_mcp.json"
    data = {
        "notebook_id": notebook_id,
        "title": title,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return config_path


def interactive_allowlist_seeding(
    discovered: list[dict[str, str]],
    active_email: str,
    project_root: Path,
    non_interactive: bool = False,
) -> dict[str, Any]:
    """Display discovered notebooks and prompt user to select which ones to allowlist."""
    cfg = load_existing_allowlist()
    existing_ids: set[str] = set()
    raw_existing = cfg.get("notebooks", [])
    if isinstance(raw_existing, list):
        for item in raw_existing:
            if isinstance(item, str):
                existing_ids.add(item)
            elif isinstance(item, dict) and isinstance(item.get("id"), str):
                existing_ids.add(item["id"])

    print("\n=========================================================================")
    print(" STEP 6: Notebook Repository Discovery & Allowlist Seeding")
    print("=========================================================================")
    if discovered:
        print(f" Found {len(discovered)} NotebookLM repositories in your signed-in account:\n")
        for idx, nb in enumerate(discovered, start=1):
            nb_id = nb["id"]
            title = nb.get("title") or "Untitled Notebook"
            badge = " [ALREADY ALLOWLISTED]" if nb_id in existing_ids else ""
            print(f"  [{idx:2d}] {title}")
            print(f"       ID: {nb_id}{badge}")
    else:
        print(" [!] No existing notebooks were returned by the discovery query.")
        print("     You can still paste a Notebook UUID or URL manually below.")

    selected_ids_ordered: list[str] = []
    if non_interactive:
        selected_ids_ordered = [nb["id"] for nb in discovered]
        for existing in existing_ids:
            if existing not in selected_ids_ordered:
                selected_ids_ordered.append(existing)
    else:
        print("\n-------------------------------------------------------------------------")
        print(" Which notebooks would you like to authorize in the MCP Allowlist?")
        print("  * Enter comma-separated numbers (e.g., 1,3)")
        print("  * Type 'all' to authorize all listed notebooks")
        print("  * Paste a Notebook UUID or full https://notebook.google.com/notebook/<ID> URL")
        print("  * Press [Enter] to keep existing allowlist unchanged")
        print("-------------------------------------------------------------------------")
        raw_input_str = input(" Selection: ").strip()

        chosen_ids: list[str] = []
        if raw_input_str.lower() == "all":
            chosen_ids = [nb["id"] for nb in discovered]
        elif raw_input_str:
            for token in raw_input_str.split(","):
                tok = token.strip()
                if not tok:
                    continue
                if tok.isdigit() and 1 <= int(tok) <= len(discovered):
                    chosen_ids.append(discovered[int(tok) - 1]["id"])
                elif "/notebook/" in tok:
                    extracted = tok.split("/notebook/")[-1].split("?")[0].split("/")[0].strip()
                    if extracted:
                        chosen_ids.append(extracted)
                else:
                    chosen_ids.append(tok)

        # Merge with existing
        for cid in chosen_ids:
            if cid not in selected_ids_ordered:
                selected_ids_ordered.append(cid)
        for existing in existing_ids:
            if existing not in selected_ids_ordered:
                selected_ids_ordered.append(existing)

    accounts_list: list[str] = (
        list(cfg.get("accounts", [])) if isinstance(cfg.get("accounts"), list) else []
    )
    if active_email and active_email not in accounts_list:
        accounts_list.append(active_email)

    cfg["version"] = 1
    cfg["provider_mode"] = "browser"
    cfg["notebooks"] = selected_ids_ordered
    cfg["accounts"] = accounts_list
    save_allowlist_atomic(cfg)

    print(f"\n[+] Saved {len(selected_ids_ordered)} authorized notebook(s) to {ALLOWLIST_PATH}")
    if active_email:
        print(f"[+] Bound multi-account isolation guard (`accounts`) to: {active_email}")

    # ADR-011 Project Default Notebook Selection (.notebook_mcp.json)
    if selected_ids_ordered:
        default_nb_id = selected_ids_ordered[0]
        if len(selected_ids_ordered) > 1 and not non_interactive:
            print("\n-------------------------------------------------------------------------")
            print(" Which authorized notebook should be set as the default for this project?")
            for idx, nb_id in enumerate(selected_ids_ordered, start=1):
                nb_title = next(
                    (n["title"] for n in discovered if n["id"] == nb_id),
                    nb_id,
                )
                print(f"  [{idx}] {nb_title} ({nb_id})")
            p_choice = input(f"\n Select default [1-{len(selected_ids_ordered)}] (default: 1): ").strip()
            if p_choice.isdigit() and 1 <= int(p_choice) <= len(selected_ids_ordered):
                default_nb_id = selected_ids_ordered[int(p_choice) - 1]

        target_title = next(
            (n["title"] for n in discovered if n["id"] == default_nb_id),
            "Authorized Notebook",
        )
        proj_conf_path = save_project_default_notebook(
            project_root, default_nb_id, target_title
        )
        print(f"[+] Saved project default notebook target in {proj_conf_path}")

    return cfg


# ---------------------------------------------------------------------------
# 7. Main Orchestration Pipeline
# ---------------------------------------------------------------------------


def run_onboarding(
    project_root: Path | None = None,
    preferred_browser: str | None = None,
    non_interactive: bool = False,
) -> int:
    """Run full 6-stage onboarding orchestrator."""
    enforce_edge_governance()

    root = (project_root or Path.cwd()).resolve()
    extension_dir = root / "src" / "extension"
    native_host_script = root / "src" / "mcp_gateway" / "host" / "native_host.py"
    resolved_socket_path = resolve_ipc_socket_path()

    print("=========================================================================")
    print(" Google Gemini Notebook MCP Gateway — Zero-Friction Installer")
    print("=========================================================================")
    print(f"[*] Project Root : {root}")
    print(f"[*] Config Vault : {CONFIG_DIR}")
    print(f"[*] IPC Socket   : {resolved_socket_path}")

    if not extension_dir.exists() or not native_host_script.exists():
        print(
            f"\n[!] Error: Could not locate 'src/extension' or 'native_host.py' under {root}."
        )
        print("    Run this script from inside the 'Google Notebook MCP' repository root,")
        print("    or pass --project-dir '/path/to/Google Notebook MCP'.")
        return 1

    # Stage 1: Browser detection & selection
    installed_browsers = find_installed_browsers()
    selected_spec, browser_bin = select_browser_interactively(
        installed_browsers,
        preferred_key=preferred_browser,
        non_interactive=non_interactive,
    )

    env_file = root / ".env"
    env_lines: list[str] = []
    if env_file.exists():
        env_lines = [
            line
            for line in env_file.read_text(encoding="utf-8").splitlines()
            if not line.startswith("CHROME_PATH=")
        ]
    env_lines.append(f"CHROME_PATH={browser_bin}")
    env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    print(f"[+] Configured CHROME_PATH={browser_bin} in {env_file}")

    # Stage 2: Manifest registration
    candidate_ids = get_candidate_extension_ids(extension_dir)
    manifest_paths = write_native_host_manifests(
        root, native_host_script, candidate_ids, selected_spec, resolved_socket_path
    )
    print(
        f"[+] Registered Native Messaging Host '{NATIVE_HOST_NAME}' in {len(manifest_paths)} location(s)."
    )

    # Stage 3: Broker daemon & Browser launch
    venv_python = root / ".venv" / "bin" / "python"
    python_exe = str(venv_python if venv_python.exists() else Path(sys.executable).resolve())

    if not is_socket_live(resolved_socket_path):
        print("[*] Starting background Policy & Session Broker daemon...")
        broker_env = os.environ.copy()
        broker_env["PYTHONPATH"] = str(root / "src")
        broker_env["MCP_BROKER_SOCKET"] = str(resolved_socket_path)
        broker_env["NOTEBOOKLM_MCP_SOCKET"] = str(resolved_socket_path)
        broker_env["UV_THREADPOOL_SIZE"] = "3"
        broker_env["OMP_NUM_THREADS"] = "3"

        subprocess.Popen(
            [
                python_exe,
                "-m",
                "mcp_gateway.cli",
                "serve",
                "--socket-path",
                str(resolved_socket_path),
            ],
            cwd=str(root),
            env=broker_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(20):
            if is_socket_live(resolved_socket_path):
                break
            time.sleep(0.25)

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(PROFILE_DIR, 0o700)

    # Clean stale SingletonLocks in profile dir
    cleanup_stale_singleton_locks(PROFILE_DIR)

    if cdp_get_json("/json/version") is None:
        print(f"[*] Launching {selected_spec.display_name} with isolated MCP profile...")
        chrome_cmd = [
            str(browser_bin),
            f"--user-data-dir={PROFILE_DIR}",
            f"--remote-debugging-port={CDP_PORT}",
            "--enable-unsafe-extension-debugging",
            f"--disable-extensions-except={extension_dir}",
            f"--load-extension={extension_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            NOTEBOOK_URL,
        ]

        # Crostini / Sommelier / Container Wayland flags
        if os.environ.get("CHROME_NO_SANDBOX") == "1" or Path("/usr/bin/sommelier").is_file():
            chrome_cmd.insert(1, "--no-sandbox")
            chrome_cmd.insert(2, "--no-zygote")
            chrome_cmd.insert(3, "--disable-dev-shm-usage")

        subprocess.Popen(
            chrome_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(30):
            if cdp_get_json("/json/version") is not None:
                break
            time.sleep(0.5)

    # Stage 4: Extension injection & Dynamic ID Sync
    live_ext_id = ensure_extension_loaded_via_cdp(extension_dir)
    if not live_ext_id and not non_interactive:
        live_ext_id = guide_manual_extension_load_if_needed(extension_dir)

    if live_ext_id and live_ext_id not in candidate_ids:
        candidate_ids.insert(0, live_ext_id)
        write_native_host_manifests(
            root, native_host_script, candidate_ids, selected_spec, resolved_socket_path
        )
        force_service_worker_reconnect(extension_dir)
        print(f"[+] Synchronized Native Messaging manifest with active Extension ID: {live_ext_id}")

    # Stage 5: Sign-in hydration poll
    auth_info = wait_for_notebook_login(timeout_seconds=300)
    active_email = auth_info.get("email", "")

    # Stage 6: Discovery & Allowlist Seeding
    print("\n[*] Querying your NotebookLM inventory (`wXbhsf` RPC)...")
    discovered_notebooks: list[dict[str, str]] = []
    if is_socket_live(resolved_socket_path):
        try:
            resp = asyncio.run(
                query_broker_ipc(resolved_socket_path, {"action": "list_notebooks"}, timeout=12.0)
            )
            raw_nbs = resp.get("notebooks") or resp.get("data", {}).get("notebooks") or []
            if isinstance(raw_nbs, list):
                discovered_notebooks = [
                    {"id": str(n["id"]), "title": str(n.get("title") or "Untitled")}
                    for n in raw_nbs
                    if isinstance(n, dict) and n.get("id")
                ]
        except Exception:
            pass

    if not discovered_notebooks:
        discovered_notebooks = discover_notebooks_via_cdp_fallback()

    interactive_allowlist_seeding(
        discovered_notebooks,
        active_email=active_email,
        project_root=root,
        non_interactive=non_interactive,
    )

    print("\n=========================================================================")
    print(" INSTALLATION & ONBOARDING COMPLETE!")
    print("=========================================================================")
    print(" Connect your AI coding clients (Claude Code, Cursor, Windsurf, Antigravity)")
    print(" using the standard stdio MCP command:")
    print(f'   uv --directory "{root}" run gemini-notebook-mcp mcp')
    print("=========================================================================")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Zero-Friction Installer & Onboarding Wizard for Google Gemini Notebook MCP Gateway"
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="Path to the Google Notebook MCP repository root (default: current directory)",
    )
    parser.add_argument(
        "--browser",
        type=str,
        default=None,
        choices=[b.key for b in SUPPORTED_BROWSERS],
        help="Explicitly select a supported browser key",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run without interactive terminal prompts (auto-selects first compatible browser & all notebooks)",
    )
    args = parser.parse_args()

    return run_onboarding(
        project_root=args.project_dir,
        preferred_browser=args.browser,
        non_interactive=args.non_interactive,
    )


if __name__ == "__main__":
    sys.exit(main())
