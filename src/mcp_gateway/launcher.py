"""Dedicated Browser Launcher — Phase 1 Zero-Friction Onboarding.

Launches a dedicated Chrome instance with the Gemini Notebook MCP extension
pre-loaded using ``--load-extension`` and ``--user-data-dir`` CLI flags.

Security invariants:
- Zero credential export: no cookies or tokens are written outside the browser profile.
- All session credentials remain inside Chrome's native network stack.
- The launcher only acts as a process supervisor; it never reads Chrome's cookie store.

Usage:
    python -m mcp_gateway.launcher [--extension-dir PATH] [--profile-dir PATH]
                                   [--start-broker] [--skip-auth-check]
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHROME_BETA_CANDIDATES = [
    "/usr/bin/google-chrome-beta",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/usr/local/bin/google-chrome-beta",
    "/usr/local/bin/google-chrome",
]
if sys.platform == "darwin":
    CHROME_BETA_CANDIDATES = [
        "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]

NOTEBOOK_URL = "https://notebook.google.com/"
AUTH_POLL_INTERVAL_S = 2.0
AUTH_POLL_TIMEOUT_S = 300.0  # 5 minutes for user to sign in
CDP_STARTUP_TIMEOUT_S = 10.0
CDP_PORT = 9222

DEFAULT_PROFILE_DIR = Path.home() / ".config" / "notebooklm-mcp-bridge" / "chrome-profile"
DEFAULT_EXTENSION_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "extension"

# ---------------------------------------------------------------------------
# Chrome discovery
# ---------------------------------------------------------------------------


def find_chrome_binary() -> Optional[str]:
    """Returns the first usable Chrome binary found on this system."""
    for candidate in CHROME_BETA_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    import shutil
    for name in ("google-chrome-beta", "google-chrome", "chromium-browser", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


# ---------------------------------------------------------------------------
# CDP auth check
# ---------------------------------------------------------------------------


async def _cdp_check_auth(cdp_port: int, timeout_s: float) -> bool:
    """Queries Chrome DevTools JSON endpoint to detect a signed-in session.

    Returns True if notebook.google.com is open and NOT redirected to accounts.google.com.
    Returns False if unauthenticated or Chrome is not yet reachable.
    """
    import urllib.request

    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{cdp_port}/json/version", timeout=2
            ) as resp:
                if resp.status == 200:
                    break
        except Exception:
            await asyncio.sleep(0.5)
    else:
        return False

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{cdp_port}/json/list", timeout=5
        ) as resp:
            pages = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False

    for page in pages:
        url = page.get("url", "")
        if "notebook.google.com" in url or "notebooklm.google.com" in url:
            if "accounts.google.com" not in url:
                return True
            return False

    return False


# ---------------------------------------------------------------------------
# Browser Launcher
# ---------------------------------------------------------------------------


class DedicatedBrowserLauncher:
    """Manages the lifecycle of a dedicated Chrome instance for the MCP bridge.

    Responsibilities:
    1. Locate the Chrome binary (prefers Chrome Beta to preserve DBSC).
    2. Launch Chrome with --load-extension and --user-data-dir so the extension
       is automatically active without user intervention.
    3. Detect unauthenticated state and prompt the user to sign in.
    4. Optionally start the broker daemon once authentication is confirmed.
    5. Forward SIGINT/SIGTERM to child processes for clean shutdown.
    """

    def __init__(
        self,
        extension_dir: Optional[Path] = None,
        profile_dir: Optional[Path] = None,
        cdp_port: int = CDP_PORT,
        start_broker: bool = True,
        skip_auth_check: bool = False,
    ) -> None:
        self.extension_dir = (extension_dir or DEFAULT_EXTENSION_DIR).resolve()
        self.profile_dir = (profile_dir or DEFAULT_PROFILE_DIR).resolve()
        self.cdp_port = cdp_port
        self.start_broker = start_broker
        self.skip_auth_check = skip_auth_check

        self._chrome_proc: Optional[asyncio.subprocess.Process] = None
        self._broker_proc: Optional[asyncio.subprocess.Process] = None

    def _build_chrome_args(self) -> list[str]:
        chrome_bin = os.environ.get("CHROME_BINARY") or find_chrome_binary()
        if not chrome_bin:
            raise RuntimeError(
                "Could not locate a Chrome or Chromium binary.\n"
                "Install Google Chrome Beta or set CHROME_BINARY=/path/to/chrome."
            )

        self.profile_dir.mkdir(parents=True, exist_ok=True)

        return [
            chrome_bin,
            f"--user-data-dir={self.profile_dir}",
            f"--load-extension={self.extension_dir}",
            f"--remote-debugging-port={self.cdp_port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
            NOTEBOOK_URL,
        ]

    async def launch(self) -> None:
        """Full launch sequence: Chrome -> auth check -> optional broker start."""

        chrome_args = self._build_chrome_args()

        print(
            f"\n[launcher] Starting dedicated Chrome instance...\n"
            f"           Binary : {chrome_args[0]}\n"
            f"           Profile: {self.profile_dir}\n"
            f"           Ext    : {self.extension_dir}\n",
            file=sys.stderr,
        )

        self._chrome_proc = await asyncio.create_subprocess_exec(
            *chrome_args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        print(
            f"[launcher] Chrome launched (PID {self._chrome_proc.pid}). "
            "Navigating to notebook.google.com...",
            file=sys.stderr,
        )

        if not self.skip_auth_check:
            await self._ensure_authenticated()

        if self.start_broker:
            await self._launch_broker()

        print(
            "\n[launcher] Browser companion is ready. "
            "You may now start an MCP client session.\n"
            "           Press Ctrl+C to shut down.\n",
            file=sys.stderr,
        )

        try:
            await self._chrome_proc.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown()

    async def _ensure_authenticated(self) -> None:
        """Detects unauthenticated state and prompts the user to sign in."""

        print("[launcher] Checking authentication status...", file=sys.stderr)

        is_auth = await _cdp_check_auth(self.cdp_port, timeout_s=CDP_STARTUP_TIMEOUT_S)

        if is_auth:
            print("[launcher] Session authenticated. Continuing.", file=sys.stderr)
            return

        print(
            "\n" + "=" * 60 + "\n"
            "  Waiting for Google Sign-In and browser pairing...\n\n"
            "  Chrome has opened https://notebook.google.com.\n"
            "  Please sign in with your Google account in that window.\n"
            "  This launcher will proceed automatically once you are\n"
            "  signed in. (Timeout: 5 minutes)\n"
            + "=" * 60 + "\n",
            file=sys.stderr,
        )

        deadline = time.monotonic() + AUTH_POLL_TIMEOUT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(AUTH_POLL_INTERVAL_S)
            is_auth = await _cdp_check_auth(self.cdp_port, timeout_s=3.0)
            if is_auth:
                print(
                    "\n[launcher] Sign-in detected! Session is now authenticated.",
                    file=sys.stderr,
                )
                return

        raise RuntimeError(
            "Authentication timeout: user did not sign in within "
            f"{int(AUTH_POLL_TIMEOUT_S)}s. Restart the launcher and try again."
        )

    async def _launch_broker(self) -> None:
        """Starts the shared broker daemon as a child process."""

        broker_cmd = [sys.executable, "-m", "mcp_gateway.cli", "serve"]
        env = os.environ.copy()
        env.setdefault("UV_THREADPOOL_SIZE", "3")

        print(f"[launcher] Starting broker daemon: {' '.join(broker_cmd)}", file=sys.stderr)
        self._broker_proc = await asyncio.create_subprocess_exec(
            *broker_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        await asyncio.sleep(2.0)

        if self._broker_proc.returncode is not None:
            stderr_out = b""
            if self._broker_proc.stderr:
                stderr_out = await self._broker_proc.stderr.read()
            raise RuntimeError(
                f"Broker daemon exited immediately (code {self._broker_proc.returncode}).\n"
                + stderr_out.decode("utf-8", errors="replace")
            )

        print(
            f"[launcher] Broker daemon running (PID {self._broker_proc.pid}).",
            file=sys.stderr,
        )

    async def _shutdown(self) -> None:
        """Gracefully terminates broker and Chrome sub-processes."""
        for proc in (self._broker_proc, self._chrome_proc):
            if proc is not None and proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except (asyncio.TimeoutError, ProcessLookupError):
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="gemini-notebook-mcp-launcher",
        description=(
            "Zero-configuration launcher for the Gemini Notebook MCP Bridge.\n\n"
            "Opens a dedicated Chrome instance with the companion extension pre-loaded,\n"
            "prompts for Google Sign-In if unauthenticated, and optionally starts the\n"
            "background broker daemon."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--extension-dir",
        type=Path,
        default=None,
        help="Path to the unpacked Manifest V3 extension directory (default: src/extension/)",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=None,
        help=(
            "Path to the dedicated Chrome user data directory "
            "(default: ~/.config/notebooklm-mcp-bridge/chrome-profile)"
        ),
    )
    parser.add_argument(
        "--cdp-port",
        type=int,
        default=CDP_PORT,
        help=f"Chrome remote debugging port (default: {CDP_PORT})",
    )
    parser.add_argument(
        "--no-broker",
        action="store_true",
        default=False,
        help="Do not automatically start the broker daemon",
    )
    parser.add_argument(
        "--skip-auth-check",
        action="store_true",
        default=False,
        help="Skip Google authentication check and proceed immediately",
    )

    args = parser.parse_args()

    launcher = DedicatedBrowserLauncher(
        extension_dir=args.extension_dir,
        profile_dir=args.profile_dir,
        cdp_port=args.cdp_port,
        start_broker=not args.no_broker,
        skip_auth_check=args.skip_auth_check,
    )

    loop = asyncio.new_event_loop()
    main_task: Optional[asyncio.Task[None]] = None

    def _on_signal() -> None:
        print("\n[launcher] Shutdown signal received.", file=sys.stderr)
        if main_task and not main_task.done():
            main_task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except (NotImplementedError, RuntimeError):
            pass

    try:
        main_task = loop.create_task(launcher.launch())
        loop.run_until_complete(main_task)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    except RuntimeError as exc:
        print(f"\n[launcher] Fatal: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        loop.close()


if __name__ == "__main__":
    main()
