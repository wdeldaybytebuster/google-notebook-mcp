"""Allowlist Seed Wizard — Phase 2 User-In-The-Loop Allowlist Population.

Connects to a running broker daemon, calls list_notebooks, presents the
discovered notebooks to the user in a readable numbered list, and writes
the selected IDs to the allowlist.json configuration.

Usage (via CLI):
    gemini-notebook-mcp allowlist seed
    python -m mcp_gateway.allowlist_wizard
"""

from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
from pathlib import Path
from typing import Any, cast

from mcp_gateway.broker.allowlist import (
    AllowlistConfig,
    DEFAULT_ALLOWLIST_PATH,
    add_notebook,
    load_allowlist,
    save_allowlist,
)

IPC_FRAME_FORMAT = ">I"
DEFAULT_SOCKET_PATH = os.environ.get(
    "MCP_BROKER_SOCKET", "/tmp/notebooklm-mcp-broker.sock"
)


# ---------------------------------------------------------------------------
# IPC helpers
# ---------------------------------------------------------------------------


async def _send_recv(
    socket_path: str, command: dict[str, Any]
) -> dict[str, Any]:
    """Sends one IPC command to the broker and reads the response."""
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
    except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
        return {
            "ok": False,
            "error": {
                "code": "BROKER_UNREACHABLE",
                "message": (
                    f"Could not connect to broker at {socket_path!r}.\n"
                    "Make sure the broker daemon is running:\n"
                    "  gemini-notebook-mcp serve\n"
                    "  (or gemini-notebook-mcp launch)\n"
                    f"Detail: {exc}"
                ),
                "retryable": True,
            },
        }

    try:
        payload = json.dumps(command).encode("utf-8")
        writer.write(struct.pack(IPC_FRAME_FORMAT, len(payload)) + payload)
        await writer.drain()

        len_bytes = await reader.readexactly(4)
        (resp_len,) = struct.unpack(IPC_FRAME_FORMAT, len_bytes)
        resp_bytes = await reader.readexactly(resp_len)
        resp_obj = json.loads(resp_bytes.decode("utf-8"))
        if isinstance(resp_obj, dict):
            return cast(dict[str, Any], resp_obj)
        return {"ok": False, "error": {"code": "INVALID_RESPONSE", "message": "Expected dict"}}
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------


async def run_seed_wizard(
    socket_path: str = DEFAULT_SOCKET_PATH,
    allowlist_path: Path | None = None,
) -> int:
    """Interactive allowlist seed wizard.

    1. Calls list_notebooks via broker IPC.
    2. Displays discovered notebooks as a numbered list.
    3. Prompts the user to enter the numbers of notebooks to allowlist.
    4. Writes the selection to allowlist.json.
    """
    target_path = allowlist_path or DEFAULT_ALLOWLIST_PATH

    print("\n" + "=" * 60, file=sys.stderr)
    print("  Gemini Notebook MCP — Allowlist Seed Wizard", file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)
    print("[*] Querying broker for your visible notebooks...\n", file=sys.stderr)

    result = await _send_recv(socket_path, {"action": "list_notebooks"})

    if not result.get("ok"):
        err = result.get("error", {})
        print(
            f"[!] Failed to list notebooks: {err.get('message', result)}\n"
            "    Ensure Chrome is open, the extension is active, and you are\n"
            "    signed in to notebook.google.com.",
            file=sys.stderr,
        )
        return 1

    notebooks: list[dict[str, Any]] = cast(
        list[dict[str, Any]], result.get("notebooks", [])
    )

    if not notebooks:
        print(
            "[!] No notebooks were returned by the broker.\n"
            "    This usually means the allowlist in allowlist.json is empty\n"
            "    (deny-all policy) and the broker filtered all results.\n\n"
            "    For initial seeding, temporarily add an empty allowlist\n"
            "    so list_notebooks can discover all your notebooks. Then\n"
            "    re-run this wizard.\n\n"
            "    Hint: Delete or clear the 'notebooks' array in:\n"
            f"    {target_path}\n"
            "    and restart the broker before running this wizard.",
            file=sys.stderr,
        )
        return 1

    print(
        "The following notebooks were discovered in your Google account:\n",
        file=sys.stderr,
    )
    for i, nb in enumerate(notebooks, start=1):
        print(f"  [{i:2d}] {nb.get('title', '(untitled)')}", file=sys.stderr)
        print(f"       ID: {nb.get('id', '')}", file=sys.stderr)

    print(
        "\n"
        "Please select the notebooks to add to this project's secure allowlist.\n"
        "Enter the numbers separated by spaces or commas (e.g. 1 3 5), or 'all':\n",
        file=sys.stderr,
    )

    try:
        raw = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[!] Aborted by user.", file=sys.stderr)
        return 1

    if not raw:
        print("[!] No selection made. Allowlist unchanged.", file=sys.stderr)
        return 0

    selected_indices: list[int] = []
    if raw.lower() == "all":
        selected_indices = list(range(len(notebooks)))
    else:
        tokens = raw.replace(",", " ").split()
        for token in tokens:
            try:
                idx = int(token) - 1
                if 0 <= idx < len(notebooks):
                    selected_indices.append(idx)
                else:
                    print(
                        f"[!] Skipping out-of-range selection: {token}", file=sys.stderr
                    )
            except ValueError:
                print(f"[!] Skipping non-numeric token: {token!r}", file=sys.stderr)

    if not selected_indices:
        print("[!] No valid selections. Allowlist unchanged.", file=sys.stderr)
        return 0

    selected = [notebooks[i] for i in selected_indices]

    # Load or create the allowlist
    try:
        config = load_allowlist(target_path)
    except FileNotFoundError:
        config = AllowlistConfig(
            version=1,
            provider_mode="browser",
            accounts=[],
            notebooks=[],
        )

    for nb in selected:
        config = add_notebook(config, str(nb["id"]))

    save_allowlist(config, target_path)

    print("\n[*] Allowlist updated successfully!\n", file=sys.stderr)
    print(f"    File: {target_path}", file=sys.stderr)
    print(f"    Allowlisted notebooks ({len(config.notebooks)} total):\n", file=sys.stderr)
    for nb_id in config.notebooks:
        # Try to find the title for display
        title = next(
            (n.get("title", "") for n in notebooks if n.get("id") == nb_id),
            "(external)",
        )
        print(f"      • {title} [{nb_id}]", file=sys.stderr)

    print(
        "\n[*] MCP tools are now active for the selected notebooks.\n"
        "    Restart the broker daemon to pick up the new allowlist.\n",
        file=sys.stderr,
    )
    return 0


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="gemini-notebook-mcp-allowlist",
        description="Interactive allowlist seed wizard for the Gemini Notebook MCP Bridge.",
    )
    parser.add_argument(
        "--socket-path",
        default=DEFAULT_SOCKET_PATH,
        help=f"Broker IPC socket path (default: {DEFAULT_SOCKET_PATH})",
    )
    parser.add_argument(
        "--allowlist-path",
        type=Path,
        default=None,
        help=f"Path to allowlist.json (default: {DEFAULT_ALLOWLIST_PATH})",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(
        run_seed_wizard(
            socket_path=args.socket_path,
            allowlist_path=args.allowlist_path,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
