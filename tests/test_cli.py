"""CLI bootstrap tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from mural.bootstrap import BOOTSTRAP_TEXT
from mural.config import locks_root
from mural.storage.ids import format_object_id, format_operation_id
from mural.storage.lock import SessionLockedError, writer_lock
from mural.storage.session import create_session
from mural.watch import DEFAULT_INTERVAL_MS, WatchUnavailableError


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the mural CLI in a subprocess."""
    command_env = os.environ.copy()
    if env is not None:
        command_env.update(env)

    return subprocess.run(
        [sys.executable, "-m", "mural", *args],
        check=False,
        capture_output=True,
        text=True,
        env=command_env,
    )


def test_main_without_args_prints_bootstrap(capsys: pytest.CaptureFixture[str]) -> None:
    from mural.cli import main

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == f"{BOOTSTRAP_TEXT}\n"
    assert captured.err == ""


def test_module_entry_point_prints_bootstrap() -> None:
    result = run_cli()

    assert result.returncode == 0
    assert result.stdout == f"{BOOTSTRAP_TEXT}\n"
    assert result.stderr == ""


def test_version_flag_prints_package_version() -> None:
    result = run_cli("--version")

    assert result.returncode == 0
    assert result.stdout.strip() == "0.1.0"
    assert result.stderr == ""


def test_new_help_advertises_watch_flag() -> None:
    result = run_cli("new", "--help")

    assert result.returncode == 0
    assert "--watch" in result.stdout
    assert "--json" in result.stdout
    assert result.stderr == ""


def test_watch_help_lists_interval_flag() -> None:
    result = run_cli("watch", "--help")

    assert result.returncode == 0
    assert "--session" in result.stdout
    assert "--interval-ms" in result.stdout
    assert result.stderr == ""


def test_new_uses_explicit_session_path(tmp_path: Path) -> None:
    session_path = tmp_path / "explicit-session"
    result = run_cli(
        "new",
        "--session",
        str(session_path),
        env={"MURAL_HOME": str(tmp_path / "mural-home")},
    )

    assert result.returncode == 0
    assert f"Session path: {session_path}" in result.stdout
    assert result.stderr == ""

    session_json = json.loads((session_path / "session.json").read_text(encoding="utf-8"))
    scene_json = json.loads((session_path / "scene.json").read_text(encoding="utf-8"))

    assert session_json["session_id"] == "explicit-session"
    assert session_json["name"] == "explicit-session"
    assert scene_json["objects"] == []
    assert (session_path / "commands.jsonl").read_text(encoding="utf-8") == ""
    assert (session_path / "assets").is_dir()
    assert (session_path / "render" / "latest.png").is_file()

    with Image.open(session_path / "render" / "latest.png") as image:
        assert image.size == (1200, 800)


def test_new_without_session_uses_mural_home(tmp_path: Path) -> None:
    mural_home = tmp_path / "mural-home"
    result = run_cli("new", "--json", env={"MURAL_HOME": str(mural_home)})

    assert result.returncode == 0
    assert result.stderr == ""

    payload = json.loads(result.stdout)
    session_path = Path(payload["session_path"])

    assert session_path.parent == mural_home / "sessions"
    assert session_path.name.endswith("-session")
    assert payload["session_id"] == session_path.name
    assert payload["name"] == "session"
    assert Path(payload["latest_render"]).is_file()

    session_json = json.loads((session_path / "session.json").read_text(encoding="utf-8"))
    expected_prefix = (
        session_json["created_at"].replace("-", "").replace(":", "").replace("T", "-")[:15]
    )
    assert session_json["session_id"].startswith(expected_prefix)


def test_new_normalizes_slug_from_name(tmp_path: Path) -> None:
    mural_home = tmp_path / "mural-home"
    result = run_cli(
        "new",
        "--name",
        "Idea Board 01",
        "--json",
        env={"MURAL_HOME": str(mural_home)},
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["session_id"].endswith("-idea-board-01")
    assert payload["name"] == "Idea Board 01"


def test_new_rejects_existing_session_path(tmp_path: Path) -> None:
    session_path = tmp_path / "duplicate-session"
    session_path.mkdir()

    result = run_cli(
        "new",
        "--session",
        str(session_path),
        env={"MURAL_HOME": str(tmp_path / "mural-home")},
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "session already exists" in result.stderr


def test_new_rejects_invalid_background(tmp_path: Path) -> None:
    session_path = tmp_path / "bad-background"
    result = run_cli(
        "new",
        "--session",
        str(session_path),
        "--background",
        "red",
        env={"MURAL_HOME": str(tmp_path / "mural-home")},
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "background must be" in result.stderr


def test_watch_launches_watcher_with_requested_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mural import cli

    session_path = tmp_path / "watch-session"
    create_session(
        session=str(session_path),
        name=None,
        width=1200,
        height=800,
        background="#FFFFFF",
    )

    captured: dict[str, object] = {}

    def fake_watch_session(session: str, *, interval_ms: int) -> None:
        captured["session"] = session
        captured["interval_ms"] = interval_ms

    monkeypatch.setattr(cli, "watch_session", fake_watch_session)

    exit_code = cli.main(
        ["watch", "--session", str(session_path), "--interval-ms", str(DEFAULT_INTERVAL_MS + 50)]
    )

    assert exit_code == 0
    assert captured == {
        "session": str(session_path),
        "interval_ms": DEFAULT_INTERVAL_MS + 50,
    }


def test_new_watch_creates_session_before_launching_watcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from mural import cli

    session_path = tmp_path / "watched-session"
    seen: dict[str, object] = {}

    class FakeWatcher:
        def run(self) -> None:
            seen["ran"] = True

    def fake_create_session_watcher(session: str, *, interval_ms: int) -> FakeWatcher:
        watched_path = Path(session)
        seen["session"] = watched_path
        seen["interval_ms"] = interval_ms
        seen["session_exists"] = watched_path.is_dir()
        seen["latest_render_exists"] = (watched_path / "render" / "latest.png").is_file()
        return FakeWatcher()

    monkeypatch.setattr(cli, "create_session_watcher", fake_create_session_watcher)

    exit_code = cli.main(["new", "--session", str(session_path), "--watch"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert seen == {
        "session": session_path,
        "interval_ms": DEFAULT_INTERVAL_MS,
        "session_exists": True,
        "latest_render_exists": True,
        "ran": True,
    }
    assert f"Session path: {session_path}" in captured.out
    assert captured.err == ""


def test_new_watch_json_reports_session_when_watcher_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from mural import cli

    session_path = tmp_path / "watched-session"

    def fake_create_session_watcher(session: str, *, interval_ms: int) -> object:
        raise WatchUnavailableError("tkinter is unavailable in the active Python environment")

    monkeypatch.setattr(cli, "create_session_watcher", fake_create_session_watcher)

    exit_code = cli.main(["new", "--session", str(session_path), "--watch", "--json"])
    captured = capsys.readouterr()

    assert exit_code == 1
    payload = json.loads(captured.out)
    assert payload["error"] == "tkinter is unavailable in the active Python environment"
    assert payload["session_path"] == str(session_path)
    assert payload["session_id"] == "watched-session"
    assert Path(payload["latest_render"]).is_file()
    assert captured.err == ""


def test_new_watch_json_emits_session_before_watcher_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from mural import cli

    session_path = tmp_path / "watched-session"
    seen: dict[str, object] = {}

    class FakeWatcher:
        def run(self) -> None:
            payload = json.loads(capsys.readouterr().out)
            seen["payload"] = payload

    def fake_create_session_watcher(session: str, *, interval_ms: int) -> FakeWatcher:
        seen["session"] = session
        seen["interval_ms"] = interval_ms
        return FakeWatcher()

    monkeypatch.setattr(cli, "create_session_watcher", fake_create_session_watcher)

    exit_code = cli.main(["new", "--session", str(session_path), "--watch", "--json"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert seen["session"] == str(session_path)
    assert seen["interval_ms"] == DEFAULT_INTERVAL_MS
    payload = seen["payload"]
    assert isinstance(payload, dict)
    assert payload["session_path"] == str(session_path)
    assert payload["session_id"] == "watched-session"
    assert captured.out == ""
    assert captured.err == ""


def test_writer_lock_blocks_overlapping_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mural import config

    monkeypatch.setattr(config, "mural_home", lambda: tmp_path / "mural-home")
    session_path = tmp_path / "locked-session"

    with writer_lock(session_path):
        assert locks_root().is_dir()
        try:
            with writer_lock(session_path):
                raise AssertionError("nested lock acquisition should fail")
        except SessionLockedError:
            pass


def test_id_formatters_are_stable() -> None:
    assert format_object_id(1) == "obj_000001"
    assert format_operation_id(12) == "op_000012"
