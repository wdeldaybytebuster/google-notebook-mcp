"""Cross-platform installer for Chrome Native Messaging Host manifest.

Supports:
- Linux (~/.config/google-chrome/NativeMessagingHosts/ & ~/.config/chromium/)
- macOS (~/Library/Application Support/Google/Chrome/NativeMessagingHosts/)
- Windows (HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\<host_name>)
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sys
from typing import Any, Callable

HOST_NAME = "com.mcp.gemini.broker"
DEFAULT_DESCRIPTION = "Google Gemini Notebook MCP Native Messaging Host"


def get_default_host_script_path() -> Path:
    """Returns the default absolute path to native_host.py."""
    return Path(__file__).resolve().parent / "native_host.py"


def get_target_manifest_directories(platform_name: str | None = None) -> list[Path]:
    """Returns candidate directories for native messaging manifests on the specified platform."""
    plat = (platform_name or sys.platform).lower()
    home = Path.home()

    if plat.startswith("linux"):
        return [
            home / ".config" / "google-chrome" / "NativeMessagingHosts",
            home / ".config" / "google-chrome-beta" / "NativeMessagingHosts",
            home / ".config" / "chromium" / "NativeMessagingHosts",
        ]
    elif plat == "darwin":
        return [
            home / "Library" / "Application Support" / "Google" / "Chrome" / "NativeMessagingHosts",
            home / "Library" / "Application Support" / "Chromium" / "NativeMessagingHosts",
        ]
    elif plat in ("win32", "windows"):
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return [base / HOST_NAME]
    else:
        return [home / ".config" / "NativeMessagingHosts"]


def generate_manifest(
    extension_id: str,
    host_path: Path | None = None,
    host_name: str = HOST_NAME,
    description: str = DEFAULT_DESCRIPTION,
) -> dict[str, Any]:
    """Generates the Native Messaging Host JSON manifest dict."""
    target_path = host_path or get_default_host_script_path()
    return {
        "name": host_name,
        "description": description,
        "path": str(target_path.resolve()),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }


def write_manifest_file(manifest: dict[str, Any], dest_path: Path) -> Path:
    """Writes the manifest JSON with secure 0o600 permissions."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(manifest, indent=2) + "\n"
    dest_path.write_text(content, encoding="utf-8")
    try:
        os.chmod(dest_path, 0o600)
    except OSError:
        pass
    return dest_path


def register_windows_registry(
    manifest_path: Path,
    host_name: str = HOST_NAME,
    registry_writer: Callable[[str, str], None] | None = None,
) -> None:
    """Registers the manifest path in Windows Registry (HKCU)."""
    reg_key_path = rf"Software\Google\Chrome\NativeMessagingHosts\{host_name}"

    if registry_writer is not None:
        registry_writer(reg_key_path, str(manifest_path.resolve()))
        return

    try:
        winreg = sys.modules.get("winreg") or __import__("winreg")
        create_key = getattr(winreg, "CreateKey")
        set_value = getattr(winreg, "SetValueEx")
        hkey_cu = getattr(winreg, "HKEY_CURRENT_USER")
        reg_sz = getattr(winreg, "REG_SZ")
        with create_key(hkey_cu, reg_key_path) as key:
            set_value(key, "", 0, reg_sz, str(manifest_path.resolve()))
    except Exception:
        pass


def unregister_windows_registry(
    host_name: str = HOST_NAME,
    registry_deleter: Callable[[str], None] | None = None,
) -> None:
    """Removes the registry key from Windows Registry (HKCU)."""
    reg_key_path = rf"Software\Google\Chrome\NativeMessagingHosts\{host_name}"

    if registry_deleter is not None:
        registry_deleter(reg_key_path)
        return

    try:
        winreg = sys.modules.get("winreg") or __import__("winreg")
        delete_key = getattr(winreg, "DeleteKey")
        hkey_cu = getattr(winreg, "HKEY_CURRENT_USER")
        delete_key(hkey_cu, reg_key_path)
    except Exception:
        pass


def install_manifest(
    extension_id: str,
    host_path: Path | None = None,
    platform_name: str | None = None,
    custom_target_dirs: list[Path] | None = None,
    host_name: str = HOST_NAME,
    registry_writer: Callable[[str, str], None] | None = None,
) -> list[Path]:
    """Installs the Native Messaging manifest to platform-appropriate locations.

    Returns list of paths where manifest files were written.
    """
    plat = (platform_name or sys.platform).lower()
    manifest = generate_manifest(
        extension_id=extension_id,
        host_path=host_path,
        host_name=host_name,
    )
    targets = custom_target_dirs or get_target_manifest_directories(platform_name=plat)
    installed_paths: list[Path] = []

    for target_dir in targets:
        dest = target_dir / f"{host_name}.json"
        written = write_manifest_file(manifest, dest)
        installed_paths.append(written)

    if plat in ("win32", "windows") and installed_paths:
        register_windows_registry(
            installed_paths[0],
            host_name=host_name,
            registry_writer=registry_writer,
        )

    return installed_paths


def uninstall_manifest(
    platform_name: str | None = None,
    custom_target_dirs: list[Path] | None = None,
    host_name: str = HOST_NAME,
    registry_deleter: Callable[[str], None] | None = None,
) -> list[Path]:
    """Uninstalls the manifest files and registry entries.

    Returns list of removed manifest paths.
    """
    plat = (platform_name or sys.platform).lower()
    targets = custom_target_dirs or get_target_manifest_directories(platform_name=plat)
    removed_paths: list[Path] = []

    for target_dir in targets:
        dest = target_dir / f"{host_name}.json"
        if dest.exists():
            try:
                dest.unlink()
                removed_paths.append(dest)
            except OSError:
                pass

    if plat in ("win32", "windows"):
        unregister_windows_registry(
            host_name=host_name,
            registry_deleter=registry_deleter,
        )

    return removed_paths


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for installing or uninstalling native host manifests."""
    parser = argparse.ArgumentParser(description="Install Native Messaging Host manifest for Chrome.")
    parser.add_argument("--extension-id", required=False, help="Chrome Extension ID shown in chrome://extensions")
    parser.add_argument("--host-path", type=Path, default=None, help="Path to native_host.py")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall existing manifests")
    parser.add_argument("--target-dir", type=Path, default=None, help="Custom directory override")
    parser.add_argument("--browser-config-dir", type=Path, default=None, help="Browser configuration directory (e.g. ~/.config/google-chrome-beta)")

    args = parser.parse_args(argv)

    if args.browser_config_dir:
        custom_dirs: list[Path] | None = [args.browser_config_dir / "NativeMessagingHosts"]
    elif args.target_dir:
        custom_dirs = [args.target_dir]
    else:
        custom_dirs = None

    if args.uninstall:
        removed = uninstall_manifest(custom_target_dirs=custom_dirs)
        for p in removed:
            print(f"Removed: {p}")
        print("Manifest uninstalled successfully.")
        return 0

    if not args.extension_id:
        parser.error("--extension-id is required when installing.")

    installed = install_manifest(
        extension_id=args.extension_id,
        host_path=args.host_path,
        custom_target_dirs=custom_dirs,
    )
    for p in installed:
        print(f"Installed: {p}")
    print("Native Messaging Host registered successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
