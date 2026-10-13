from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
import pytest

from mcp_gateway.host.installer import (
    HOST_NAME,
    generate_manifest,
    get_target_manifest_directories,
    install_manifest,
    main,
    uninstall_manifest,
    write_manifest_file,
)


def test_generate_manifest() -> None:
    ext_id = "abcdefghijklmnopabcdefghijklmnop"
    custom_host = Path("/opt/mcp/native_host.py")
    manifest = generate_manifest(extension_id=ext_id, host_path=custom_host)

    assert manifest["name"] == HOST_NAME
    assert manifest["type"] == "stdio"
    assert manifest["path"] == str(custom_host.resolve())
    assert manifest["allowed_origins"] == [f"chrome-extension://{ext_id}/"]


def test_get_target_directories_cross_platform() -> None:
    linux_dirs = get_target_manifest_directories("linux")
    assert any("google-chrome" in str(d) for d in linux_dirs)
    assert any("chromium" in str(d) for d in linux_dirs)

    darwin_dirs = get_target_manifest_directories("darwin")
    assert any("Library" in str(d) for d in darwin_dirs)

    windows_dirs = get_target_manifest_directories("win32")
    assert any(HOST_NAME in str(d) for d in windows_dirs)


def test_install_manifest_posix(tmp_path: Path) -> None:
    target_1 = tmp_path / "chrome"
    target_2 = tmp_path / "chromium"
    ext_id = "test_extension_id_12345"
    custom_host = tmp_path / "host.py"
    custom_host.touch()

    installed = install_manifest(
        extension_id=ext_id,
        host_path=custom_host,
        platform_name="linux",
        custom_target_dirs=[target_1, target_2],
    )

    assert len(installed) == 2
    for p in installed:
        assert p.exists()
        assert p.name == f"{HOST_NAME}.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["allowed_origins"] == [f"chrome-extension://{ext_id}/"]
        # Verify file permissions mode (POSIX 0o600)
        mode = oct(p.stat().st_mode & 0o777)
        assert mode == oct(0o600)


def test_install_and_uninstall_windows_mock_registry(tmp_path: Path) -> None:
    target = tmp_path / "win_target"
    ext_id = "windows_extension_id"
    custom_host = tmp_path / "host.py"
    custom_host.touch()

    registry_calls: list[tuple[str, str]] = []

    def mock_reg_writer(key: str, val: str) -> None:
        registry_calls.append((key, val))

    installed = install_manifest(
        extension_id=ext_id,
        host_path=custom_host,
        platform_name="win32",
        custom_target_dirs=[target],
        registry_writer=mock_reg_writer,
    )

    assert len(installed) == 1
    assert len(registry_calls) == 1
    assert HOST_NAME in registry_calls[0][0]
    assert registry_calls[0][1] == str(installed[0].resolve())

    # Now uninstall
    deleted_reg_keys: list[str] = []

    def mock_reg_deleter(key: str) -> None:
        deleted_reg_keys.append(key)

    removed = uninstall_manifest(
        platform_name="win32",
        custom_target_dirs=[target],
        registry_deleter=mock_reg_deleter,
    )

    assert len(removed) == 1
    assert not installed[0].exists()
    assert len(deleted_reg_keys) == 1


def test_installer_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target_dir = tmp_path / "custom_native_hosts"
    ext_id = "cli_extension_test_id"

    # Test install
    code = main([
        "--extension-id",
        ext_id,
        "--target-dir",
        str(target_dir),
    ])
    assert code == 0
    manifest_file = target_dir / f"{HOST_NAME}.json"
    assert manifest_file.exists()

    # Test uninstall
    code_uninst = main([
        "--uninstall",
        "--target-dir",
        str(target_dir),
    ])
    assert code_uninst == 0
    assert not manifest_file.exists()


def test_installer_browser_config_dir(tmp_path: Path) -> None:
    browser_dir = tmp_path / "google-chrome-beta"
    ext_id = "beta_extension_test_id"

    code = main([
        "--extension-id",
        ext_id,
        "--browser-config-dir",
        str(browser_dir),
    ])
    assert code == 0
    manifest_file = browser_dir / "NativeMessagingHosts" / f"{HOST_NAME}.json"
    assert manifest_file.exists()

