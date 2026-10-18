"""Unified CLI entrypoint for Gemini Notebook MCP Gateway.

Subcommands:
- mcp: Run short-lived stdio MCP facade (spawned per client)
- serve: Run persistent shared broker daemon on Unix domain socket
- install: Install or uninstall Chrome Native Messaging Host manifests
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import sys
from typing import Sequence

# Enforce threadpool constraints early before runtime threadpool spinup
os.environ["UV_THREADPOOL_SIZE"] = "3"


def enforce_resource_limits() -> None:
    """Configures threadpool, CPU affinity, memory defaults, and file descriptor limits."""
    # Enforce hardware protection environment defaults
    os.environ.setdefault("UV_THREADPOOL_SIZE", "3")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "3")
    os.environ.setdefault("OMP_NUM_THREADS", "3")
    os.environ.setdefault("MKL_NUM_THREADS", "3")
    os.environ.setdefault(
        "NODE_OPTIONS", "--max-old-space-size=1024 --max-semi-space-size=128"
    )

    if sys.platform == "win32":
        return

    # Restrict CPU affinity to cores 0-5 on Linux systems with > 6 cores
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
        target = min(65536, hard)
        if soft < target:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
    except (ImportError, ValueError, OSError, AttributeError):
        pass


def run_mcp(socket_path: str | None = None) -> int:
    """Runs the MCP stdio facade."""
    enforce_resource_limits()
    if sys.platform == "win32":
        import msvcrt

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)   # type: ignore[attr-defined]
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)  # type: ignore[attr-defined]

    from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon, McpFacade

    cfg_kwargs: dict[str, str] = {}
    if socket_path:
        cfg_kwargs["socket_path"] = socket_path

    config = BrokerConfig(**cfg_kwargs)  # type: ignore[arg-type]
    broker = BrokerDaemon(config)
    facade = McpFacade(broker)
    facade.serve_stdio()
    return 0


def run_serve(
    socket_path: str | None = None,
    allowlist_path: Path | None = None,
    journal_db_path: Path | None = None,
) -> int:
    """Runs the shared persistent BrokerDaemon."""
    from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon
    from mcp_gateway.transport import get_default_ipc_path

    enforce_resource_limits()

    config = BrokerConfig(
        socket_path=socket_path or os.environ.get("MCP_BROKER_SOCKET", get_default_ipc_path()),
        allowlist_path=allowlist_path,
        journal_db_path=journal_db_path,
    )
    broker = BrokerDaemon(config)

    async def _serve() -> None:
        await broker.start()
        print(f"[broker] Listening on {config.socket_path}", file=sys.stderr)
        print("[broker] Press Ctrl+C to stop.", file=sys.stderr)
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await broker.stop()

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass
    return 0


def run_install(argv: Sequence[str]) -> int:
    """Delegates to Native Messaging Host installer."""
    from mcp_gateway.host.installer import main as installer_main

    return installer_main(list(argv))


def run_launch(
    extension_dir: Path | None = None,
    profile_dir: Path | None = None,
    cdp_port: int = 9222,
    no_broker: bool = False,
    skip_auth_check: bool = False,
) -> int:
    """Runs the Phase 1 dedicated browser launcher (zero-friction onboarding)."""
    from mcp_gateway.launcher import DedicatedBrowserLauncher
    import signal

    launcher = DedicatedBrowserLauncher(
        extension_dir=extension_dir,
        profile_dir=profile_dir,
        cdp_port=cdp_port,
        start_broker=not no_broker,
        skip_auth_check=skip_auth_check,
    )

    loop = asyncio.new_event_loop()
    main_task: asyncio.Task[None] | None = None

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
        return 1
    finally:
        loop.close()
    return 0


def run_allowlist_seed(
    socket_path: str | None = None,
    allowlist_path: Path | None = None,
) -> int:
    """Runs the Phase 2 interactive allowlist seed wizard."""
    from mcp_gateway.allowlist_wizard import run_seed_wizard
    from mcp_gateway.transport import get_default_ipc_path
    import os

    _socket = socket_path or os.environ.get(
        "MCP_BROKER_SOCKET", get_default_ipc_path()
    )
    return asyncio.run(run_seed_wizard(socket_path=_socket, allowlist_path=allowlist_path))


def run_onboard(
    project_dir: Path | None = None,
    browser: str | None = None,
    non_interactive: bool = False,
) -> int:
    """Runs the unified zero-friction onboarding orchestrator."""
    import importlib.util

    root = (project_dir or Path.cwd()).resolve()
    script = root / "install_and_onboard.py"
    if not script.exists():
        candidate = Path(__file__).resolve().parent.parent.parent / "install_and_onboard.py"
        if candidate.exists():
            script = candidate

    if script.exists():
        spec = importlib.util.spec_from_file_location("install_and_onboard", script)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return int(
                mod.run_onboarding(
                    project_root=root,
                    preferred_browser=browser,
                    non_interactive=non_interactive,
                )
            )
    print(f"[!] Error: Could not locate install_and_onboard.py in {root}", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gemini-notebook-mcp",
        description="Gemini Notebook MCP Gateway CLI",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Subcommand: mcp
    mcp_parser = subparsers.add_parser("mcp", help="Run MCP stdio facade")
    mcp_parser.add_argument(
        "--socket-path",
        default=None,
        help="Path to broker IPC socket or named pipe",
    )

    # Subcommand: serve
    serve_parser = subparsers.add_parser("serve", help="Run background broker daemon")
    serve_parser.add_argument(
        "--socket-path",
        default=None,
        help="Path to broker IPC socket or named pipe",
    )
    serve_parser.add_argument(
        "--allowlist",
        type=Path,
        default=None,
        help="Path to allowlist.json configuration",
    )
    serve_parser.add_argument(
        "--journal-db",
        type=Path,
        default=None,
        help="Path to journal SQLite database",
    )

    # Subcommand: install
    install_parser = subparsers.add_parser(
        "install",
        help="Install Native Messaging Host manifest for Chrome",
    )
    install_parser.add_argument(
        "--extension-id",
        required=False,
        help="Chrome Extension ID shown in chrome://extensions",
    )
    install_parser.add_argument(
        "--host-path",
        type=Path,
        default=None,
        help="Path to native_host.py",
    )
    install_parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Uninstall existing manifests",
    )
    install_parser.add_argument(
        "--target-dir",
        type=Path,
        default=None,
        help="Custom manifest directory override",
    )
    install_parser.add_argument(
        "--browser-config-dir",
        type=Path,
        default=None,
        help="Browser configuration directory (e.g. ~/.config/google-chrome-beta)",
    )

    # Subcommand: launch (Phase 1 Zero-Friction Onboarding)
    launch_parser = subparsers.add_parser(
        "launch",
        help=(
            "Launch a dedicated Chrome instance with the extension pre-loaded, "
            "handle Google Sign-In, and optionally start the broker daemon."
        ),
    )
    launch_parser.add_argument(
        "--extension-dir",
        type=Path,
        default=None,
        help="Path to unpacked extension directory (default: src/extension/)",
    )
    launch_parser.add_argument(
        "--profile-dir",
        type=Path,
        default=None,
        help="Dedicated Chrome profile directory (default: ~/.config/notebooklm-mcp-bridge/chrome-profile)",
    )
    launch_parser.add_argument(
        "--cdp-port",
        type=int,
        default=9222,
        help="Chrome remote debugging port (default: 9222)",
    )
    launch_parser.add_argument(
        "--no-broker",
        action="store_true",
        default=False,
        help="Do not automatically start the broker daemon",
    )
    launch_parser.add_argument(
        "--skip-auth-check",
        action="store_true",
        default=False,
        help="Skip Google authentication check and proceed immediately",
    )

    # Subcommand: allowlist
    al_parser = subparsers.add_parser(
        "allowlist",
        help="Manage the notebook allowlist (Phase 2 User-In-The-Loop authorization)",
    )
    al_sub = al_parser.add_subparsers(dest="al_action", required=True)
    seed_parser = al_sub.add_parser(
        "seed",
        help=(
            "Interactive wizard: list_notebooks → prompt user → write allowlist.json. "
            "Must run AFTER: gemini-notebook-mcp launch (or serve + Chrome open)."
        ),
    )
    seed_parser.add_argument(
        "--socket-path",
        default=None,
        help="Broker IPC socket or named pipe path",
    )
    seed_parser.add_argument(
        "--allowlist-path",
        type=Path,
        default=None,
        help="Path to allowlist.json (default: ~/.config/notebooklm-mcp-bridge/allowlist.json)",
    )

    # Subcommand: onboard
    onboard_parser = subparsers.add_parser(
        "onboard",
        help="Run the zero-friction cross-platform onboarding orchestrator",
    )
    onboard_parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Path to project repository root (default: current directory)",
    )
    onboard_parser.add_argument(
        "--browser",
        type=str,
        default=None,
        help="Explicitly select a supported browser key (e.g. google-chrome-beta)",
    )
    onboard_parser.add_argument(
        "--non-interactive",
        action="store_true",
        default=False,
        help="Run without interactive terminal prompts",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "mcp":
        return run_mcp(socket_path=args.socket_path)
    elif args.subcommand == "serve":
        return run_serve(
            socket_path=args.socket_path,
            allowlist_path=args.allowlist,
            journal_db_path=args.journal_db,
        )
    elif args.subcommand == "install":
        install_args: list[str] = []
        if args.uninstall:
            install_args.append("--uninstall")
        if args.extension_id:
            install_args.extend(["--extension-id", args.extension_id])
        if args.host_path:
            install_args.extend(["--host-path", str(args.host_path)])
        if args.target_dir:
            install_args.extend(["--target-dir", str(args.target_dir)])
        if args.browser_config_dir:
            install_args.extend(["--browser-config-dir", str(args.browser_config_dir)])
        return run_install(install_args)
    elif args.subcommand == "launch":
        return run_launch(
            extension_dir=args.extension_dir,
            profile_dir=args.profile_dir,
            cdp_port=args.cdp_port,
            no_broker=args.no_broker,
            skip_auth_check=args.skip_auth_check,
        )
    elif args.subcommand == "allowlist":
        if args.al_action == "seed":
            return run_allowlist_seed(
                socket_path=args.socket_path,
                allowlist_path=args.allowlist_path,
            )
        parser.print_help(sys.stderr)
        return 1
    elif args.subcommand == "onboard":
        return run_onboard(
            project_dir=args.project_dir,
            browser=args.browser,
            non_interactive=args.non_interactive,
        )
    else:
        parser.print_help(sys.stderr)
        return 1


def main_onboard() -> None:
    """CLI script entrypoint for gemini-notebook-mcp-onboard."""
    sys.exit(main(["onboard", *sys.argv[1:]]))


if __name__ == "__main__":
    sys.exit(main())
