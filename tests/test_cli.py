"""Unit tests for mcp_gateway.cli unified CLI entrypoint."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from mcp_gateway.cli import build_parser, enforce_resource_limits, main


def test_build_parser_subcommands() -> None:
    parser = build_parser()
    # Test mcp subparser
    mcp_args = parser.parse_args(["mcp"])
    assert mcp_args.subcommand == "mcp"
    assert mcp_args.socket_path is None

    # Test serve subparser
    serve_args = parser.parse_args(["serve", "--socket-path", "/tmp/custom.sock", "--allowlist", "allow.json"])
    assert serve_args.subcommand == "serve"
    assert serve_args.socket_path == "/tmp/custom.sock"
    assert serve_args.allowlist == Path("allow.json")

    # Test install subparser
    install_args = parser.parse_args(["install", "--extension-id", "abcdefghijklmnop", "--uninstall"])
    assert install_args.subcommand == "install"
    assert install_args.extension_id == "abcdefghijklmnop"
    assert install_args.uninstall is True


def test_main_mcp_dispatch() -> None:
    with patch("mcp_gateway.cli.run_mcp", return_value=0) as mock_mcp:
        ret = main(["mcp", "--socket-path", "/tmp/test.sock"])
        assert ret == 0
        mock_mcp.assert_called_once_with(socket_path="/tmp/test.sock")


def test_main_serve_dispatch() -> None:
    with patch("mcp_gateway.cli.run_serve", return_value=0) as mock_serve:
        ret = main(["serve", "--socket-path", "/tmp/test.sock", "--allowlist", "allow.json"])
        assert ret == 0
        mock_serve.assert_called_once_with(
            socket_path="/tmp/test.sock",
            allowlist_path=Path("allow.json"),
            journal_db_path=None,
        )


def test_main_install_dispatch() -> None:
    with patch("mcp_gateway.cli.run_install", return_value=0) as mock_install:
        ret = main(["install", "--extension-id", "abcdef", "--uninstall"])
        assert ret == 0
        mock_install.assert_called_once_with(["--uninstall", "--extension-id", "abcdef"])


def test_main_launch_dispatch() -> None:
    with patch("mcp_gateway.cli.run_launch", return_value=0) as mock_launch:
        ret = main(["launch", "--cdp-port", "9333", "--no-broker", "--skip-auth-check"])
        assert ret == 0
        mock_launch.assert_called_once_with(
            extension_dir=None,
            profile_dir=None,
            cdp_port=9333,
            no_broker=True,
            skip_auth_check=True,
        )


def test_main_allowlist_seed_dispatch() -> None:
    with patch("mcp_gateway.cli.run_allowlist_seed", return_value=0) as mock_seed:
        ret = main(["allowlist", "seed", "--socket-path", "/tmp/custom.sock"])
        assert ret == 0
        mock_seed.assert_called_once_with(
            socket_path="/tmp/custom.sock",
            allowlist_path=None,
        )


def test_main_no_args_exits() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_enforce_resource_limits_executes() -> None:
    # Must execute safely across platforms without raising
    enforce_resource_limits()

