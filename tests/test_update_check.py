"""Tests for the best-effort update check."""

from __future__ import annotations

from unittest.mock import patch

from linework.update_check import _parse_latest_tag, _update_command, check_for_update


def test_parse_latest_tag_picks_highest() -> None:
    output = "aaa\trefs/tags/v0.1.0\nbbb\trefs/tags/v0.2.0\nccc\trefs/tags/v0.1.5\n"
    assert _parse_latest_tag(output) == "0.2.0"


def test_parse_latest_tag_returns_none_for_no_tags() -> None:
    assert _parse_latest_tag("") is None
    assert _parse_latest_tag("aaa\trefs/heads/main\n") is None


def test_update_command_unix() -> None:
    with patch("linework.update_check.sys") as mock_sys:
        mock_sys.platform = "darwin"
        cmd = _update_command()
    assert cmd == "uv tool install git+https://github.com/nvillar/linework.git"
    assert "--link-mode" not in cmd


def test_update_command_windows() -> None:
    with patch("linework.update_check.sys") as mock_sys:
        mock_sys.platform = "win32"
        cmd = _update_command()
    assert "--link-mode copy" in cmd


def test_check_for_update_returns_hint_when_newer() -> None:
    ls_remote_output = "aaa\trefs/tags/v1.0.0\n"
    with patch("linework.update_check.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ls_remote_output
        hint = check_for_update("0.1.0")
    assert hint is not None
    assert "0.1.0" in hint
    assert "1.0.0" in hint
    assert "uv tool install" in hint


def test_check_for_update_returns_none_when_current() -> None:
    ls_remote_output = "aaa\trefs/tags/v0.1.0\n"
    with patch("linework.update_check.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ls_remote_output
        hint = check_for_update("0.1.0")
    assert hint is None


def test_check_for_update_returns_none_when_ahead() -> None:
    ls_remote_output = "aaa\trefs/tags/v0.1.0\n"
    with patch("linework.update_check.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ls_remote_output
        hint = check_for_update("0.2.0")
    assert hint is None


def test_check_for_update_returns_none_on_network_failure() -> None:
    with patch("linework.update_check.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 128
        mock_run.return_value.stdout = ""
        hint = check_for_update("0.1.0")
    assert hint is None


def test_check_for_update_returns_none_on_timeout() -> None:
    import subprocess

    with patch("linework.update_check.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=5)
        hint = check_for_update("0.1.0")
    assert hint is None


def test_check_for_update_handles_dev_version() -> None:
    ls_remote_output = "aaa\trefs/tags/v0.2.0\n"
    with patch("linework.update_check.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ls_remote_output
        hint = check_for_update("0.1.1.dev8")
    assert hint is not None
    assert "0.2.0" in hint
