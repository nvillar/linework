"""CLI bootstrap tests."""

from __future__ import annotations

import subprocess
import sys

from mural.bootstrap import BOOTSTRAP_TEXT


def test_main_without_args_prints_bootstrap(capsys: object) -> None:
    from mural.cli import main

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == f"{BOOTSTRAP_TEXT}\n"
    assert captured.err == ""


def test_module_entry_point_prints_bootstrap() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mural"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == f"{BOOTSTRAP_TEXT}\n"
    assert result.stderr == ""


def test_version_flag_prints_package_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mural", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "0.1.0"
    assert result.stderr == ""
