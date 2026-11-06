#!/usr/bin/env python3
"""Zero-friction CLI entry point for Chrome Native Messaging Host registration.

Invoked directly from the Extension Popup Setup Mode:
    python3 setup_native_host.py --extension-id <CURRENT_EXTENSION_ID>
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

_src_root = str(Path(__file__).resolve().parent / "src")
if _src_root not in sys.path:
    sys.path.insert(0, _src_root)

from mcp_gateway.host.installer import install_manifest  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="setup_native_host.py",
        description="Register the Gemini Notebook MCP Chrome Native Messaging Host manifest.",
    )
    parser.add_argument(
        "--extension-id",
        required=True,
        help="32-character Chrome Extension ID shown in the extension popup.",
    )
    parser.add_argument(
        "--browser",
        default="google-chrome",
        help="Target browser family (default: google-chrome).",
    )
    args = parser.parse_args(argv)

    ext_id = str(args.extension_id).strip()
    native_host_script = Path(__file__).resolve().parent / "src" / "mcp_gateway" / "host" / "native_host.py"
    try:
        manifest_paths = install_manifest(
            host_path=native_host_script,
            extension_id=ext_id,
            browser=str(args.browser),
        )
        for manifest_path in manifest_paths:
            print(f"[+] Native Messaging Host registered at: {manifest_path}")
        print(f"[+] Bound to extension origin: chrome-extension://{ext_id}/")
        return 0
    except Exception as exc:
        print(f"[!] Failed to register Native Messaging Host: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
