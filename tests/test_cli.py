"""CLI bootstrap tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from linework.bootstrap import BOOTSTRAP_TEXT
from linework.config import locks_root
from linework.storage.ids import format_object_id, format_operation_id
from linework.storage.lock import SessionLockedError, writer_lock
from linework.storage.session import create_session
from linework.watch import DEFAULT_INTERVAL_MS, WatchError, WatchUnavailableError


def run_cli(
    *args: str,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the linework CLI in a subprocess."""
    command_env = os.environ.copy()
    if env is not None:
        command_env.update(env)

    return subprocess.run(
        [sys.executable, "-m", "linework", *args],
        check=False,
        capture_output=True,
        text=True,
        env=command_env,
        input=stdin,
    )


def test_main_without_args_prints_bootstrap(capsys: pytest.CaptureFixture[str]) -> None:
    from linework.cli import main

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


def test_bootstrap_text_mentions_schema_and_new_shapes() -> None:
    assert "linework schema --json" in BOOTSTRAP_TEXT
    assert "linework schema draw.arrow" in BOOTSTRAP_TEXT
    assert "linework schema" in BOOTSTRAP_TEXT
    assert "compact capability overview" in BOOTSTRAP_TEXT
    assert "full manifest" in BOOTSTRAP_TEXT
    assert "Golden path:" in BOOTSTRAP_TEXT
    assert '"draw.polygon"' in BOOTSTRAP_TEXT
    assert '"draw.arrow"' in BOOTSTRAP_TEXT
    assert '"draw.circle"' in BOOTSTRAP_TEXT
    assert "inspect --session PATH --json" in BOOTSTRAP_TEXT


def test_version_flag_prints_package_version() -> None:
    result = run_cli("--version")

    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert lines[0].startswith("0.")
    assert result.stderr == ""


def test_top_level_help_includes_golden_path() -> None:
    result = run_cli("--help")

    assert result.returncode == 0
    assert "Golden path:" in result.stdout
    assert "compact capability overview" in result.stdout
    assert "linework schema draw.arrow" in result.stdout
    assert "linework schema --json" in result.stdout
    assert "full manifest" in result.stdout
    assert "linework schema" in result.stdout
    assert "linework draw rect --session PATH" in result.stdout
    assert "linework watch --session PATH" in result.stdout
    assert "_watch-impl" not in result.stdout
    assert result.stderr == ""


def test_new_help_advertises_watch_command() -> None:
    result = run_cli("new", "--help")

    assert result.returncode == 0
    assert "watch_command" in result.stdout
    assert "watch_recommendation" in result.stdout
    assert "inspect_command" in result.stdout
    assert "reuse the printed session path" in result.stdout
    assert "--json" in result.stdout
    assert "800x800" in result.stdout
    assert result.stderr == ""


def test_watch_help_lists_interval_flag() -> None:
    result = run_cli("watch", "--help")

    assert result.returncode == 0
    assert "--session" in result.stdout
    assert "--interval-ms" in result.stdout
    assert "read-only watcher window" in result.stdout
    assert result.stderr == ""


def test_schema_command_outputs_compact_overview() -> None:
    result = run_cli("schema")

    assert result.returncode == 0
    assert "Compact overview:" in result.stdout
    assert "Use the capability-discovery flow below for overview, one-op detail," in result.stdout
    assert "Shared defaults:" in result.stdout
    assert "Capability discovery:" in result.stdout
    assert "visible=true, stroke=#000000, stroke_width=2.0" in result.stdout
    assert (
        "text: size=16.0, fill=#000000, align=center, valign=middle, padding=0.0" in result.stdout
    )
    assert "linework schema draw.arrow" in result.stdout
    assert "linework schema --json" in result.stdout
    assert "full manifest" in result.stdout
    assert "draw x1, y1, x2, y2 | optional tag, visible, stroke, stroke_width" in result.stdout
    assert "arrowhead: end, start, both, none (default: end)" in result.stdout
    assert (
        "colors: #RRGGBB or #RRGGBBAA (alpha-composited in stacking order; quote in shell commands)"
        in result.stdout
    )
    assert "hidden selector metadata" in result.stdout
    assert (
        "`edit.image` changes placement/size only; `asset_path` is fixed after creation"
        in result.stdout
    )
    assert result.stderr == ""


def test_schema_command_outputs_machine_readable_manifest() -> None:
    result = run_cli("schema", "--json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["canvas_defaults"] == {
        "width": 800,
        "height": 800,
        "background": "#FFFFFF",
    }
    assert payload["color_format"] == {
        "syntax": "#RRGGBB or #RRGGBBAA",
        "compositing": (
            "source-over alpha; translucent objects blend with"
            " earlier scene content in creation order"
        ),
    }
    assert payload["ops"]["draw.arrow"]["optional"]["arrow_size"]["type"] == "positive-number|null"
    assert payload["ops"]["draw.circle"]["required"]["radius"]["type"] == "positive-number"
    assert payload["ops"]["draw.text"]["required"]["width"]["type"] == "positive-number"
    assert payload["ops"]["draw.text"]["optional"]["align"]["enum"] == [
        "left",
        "center",
        "right",
    ]
    assert payload["ops"]["draw.text"]["optional"]["valign"]["enum"] == [
        "top",
        "middle",
        "bottom",
    ]
    assert result.stderr == ""


def test_schema_command_outputs_single_operation_overview() -> None:
    result = run_cli("schema", "draw.arrow")

    assert result.returncode == 0
    assert "Operation: draw.arrow" in result.stdout
    assert "Description: Create an arrow." in result.stdout
    assert "Required fields:" in result.stdout
    assert "x1: number" in result.stdout
    assert "arrowhead: string (default: end; enum: end, start, both, none)" in result.stdout
    assert '"op": "draw.arrow"' in result.stdout
    assert result.stderr == ""


def test_schema_command_outputs_single_operation_manifest() -> None:
    result = run_cli("schema", "--json", "draw.arrow")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert sorted(payload["ops"]) == ["draw.arrow"]
    assert payload["ops"]["draw.arrow"]["optional"]["arrowhead"]["default"] == "end"
    assert result.stderr == ""


def test_schema_command_rejects_unknown_operation() -> None:
    result = run_cli("schema", "draw.square")

    assert result.returncode == 1
    assert result.stdout == ""
    assert "did you mean draw.rect?" in result.stderr


def test_watch_missing_session_reports_plain_error(tmp_path: Path) -> None:
    result = run_cli(
        "watch",
        "--session",
        str(tmp_path / "missing-session"),
        env={"LINEWORK_HOME": str(tmp_path / "linework-home")},
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "session does not exist" in result.stderr


def test_new_uses_explicit_session_path(tmp_path: Path) -> None:
    session_path = tmp_path / "explicit-session"
    result = run_cli(
        "new",
        "--session",
        str(session_path),
        env={"LINEWORK_HOME": str(tmp_path / "linework-home")},
    )

    assert result.returncode == 0
    assert f"Session path: {session_path}" in result.stdout
    assert f"linework draw rect --session {session_path}" in result.stdout
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
        assert image.size == (800, 800)


def test_new_can_seed_session_from_stdin(tmp_path: Path) -> None:
    session_path = tmp_path / "seeded-session"
    result = run_cli(
        "new",
        "--session",
        str(session_path),
        "--stdin",
        "--json",
        env={"LINEWORK_HOME": str(tmp_path / "linework-home")},
        stdin='{"op":"draw.rect","payload":{"x":10,"y":10,"width":40,"height":20,"fill":"#FF0000"}}\n',
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["session_path"] == str(session_path)
    assert payload["applied"] == 1
    assert payload["scene_object_count"] == 1
    scene_json = json.loads((session_path / "scene.json").read_text(encoding="utf-8"))
    assert len(scene_json["objects"]) == 1


def test_new_can_seed_session_from_file(tmp_path: Path) -> None:
    session_path = tmp_path / "seeded-session-file"
    ops_path = tmp_path / "ops.jsonl"
    ops_path.write_text(
        '{"op":"draw.circle","payload":{"x":20,"y":20,"radius":16,"fill":"#00FF00"}}\n',
        encoding="utf-8",
    )
    result = run_cli(
        "new",
        "--session",
        str(session_path),
        "--file",
        str(ops_path),
        "--json",
        env={"LINEWORK_HOME": str(tmp_path / "linework-home")},
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["applied"] == 1
    scene_json = json.loads((session_path / "scene.json").read_text(encoding="utf-8"))
    assert len(scene_json["objects"]) == 1


def test_new_rejects_file_and_stdin_together(tmp_path: Path) -> None:
    ops_path = tmp_path / "ops.jsonl"
    ops_path.write_text("", encoding="utf-8")
    result = run_cli(
        "new",
        "--session",
        str(tmp_path / "mixed-session"),
        "--file",
        str(ops_path),
        "--stdin",
        env={"LINEWORK_HOME": str(tmp_path / "linework-home")},
    )

    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr


def test_new_without_session_uses_linework_home(tmp_path: Path) -> None:
    linework_home = tmp_path / "linework-home"
    result = run_cli("new", "--json", env={"LINEWORK_HOME": str(linework_home)})

    assert result.returncode == 0
    assert result.stderr == ""

    payload = json.loads(result.stdout)
    session_path = Path(payload["session_path"])

    assert session_path.parent == linework_home / "sessions"
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
    linework_home = tmp_path / "linework-home"
    result = run_cli(
        "new",
        "--name",
        "Idea Board 01",
        "--json",
        env={"LINEWORK_HOME": str(linework_home)},
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["session_id"].endswith("-idea-board-01")
    assert payload["name"] == "Idea Board 01"


def test_new_rejects_existing_session_path(tmp_path: Path) -> None:
    session_path = tmp_path / "duplicate-session"
    session_path.mkdir()
    (session_path / "keep.txt").write_text("existing", encoding="utf-8")

    result = run_cli(
        "new",
        "--session",
        str(session_path),
        env={"LINEWORK_HOME": str(tmp_path / "linework-home")},
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "session already exists" in result.stderr
    assert "Reuse this same session" in result.stderr


def test_new_allows_precreated_empty_session_directory(tmp_path: Path) -> None:
    session_path = tmp_path / "prepared-session"
    session_path.mkdir()

    result = run_cli(
        "new",
        "--session",
        str(session_path),
        "--json",
        env={"LINEWORK_HOME": str(tmp_path / "linework-home")},
    )

    assert result.returncode == 0
    assert result.stderr == ""

    payload = json.loads(result.stdout)
    assert payload["session_path"] == str(session_path.resolve())
    assert (session_path / "session.json").is_file()
    assert (session_path / "scene.json").is_file()
    assert (session_path / "commands.jsonl").is_file()
    assert (session_path / "render" / "latest.png").is_file()


def test_new_rejects_invalid_background(tmp_path: Path) -> None:
    session_path = tmp_path / "bad-background"
    result = run_cli(
        "new",
        "--session",
        str(session_path),
        "--background",
        "red",
        env={"LINEWORK_HOME": str(tmp_path / "linework-home")},
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "background must be" in result.stderr


def test_watch_launches_detached_watcher_with_requested_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from linework import cli

    session_path = tmp_path / "watch-session"
    create_session(
        session=str(session_path),
        name=None,
        width=1200,
        height=800,
        background="#FFFFFF",
    )

    captured: dict[str, object] = {}

    def fake_launch(session: str, *, interval_ms: int) -> int:
        captured["session"] = session
        captured["interval_ms"] = interval_ms
        return 99999

    monkeypatch.setattr(cli, "_launch_detached_watcher", fake_launch)

    exit_code = cli.main(
        ["watch", "--session", str(session_path), "--interval-ms", str(DEFAULT_INTERVAL_MS + 50)]
    )
    out = capsys.readouterr()

    assert exit_code == 0
    assert captured == {
        "session": str(session_path),
        "interval_ms": DEFAULT_INTERVAL_MS + 50,
    }
    assert "pid 99999" in out.out


def test_new_json_includes_watch_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from linework import cli

    session_path = tmp_path / "watched-session"

    exit_code = cli.main(["new", "--session", str(session_path), "--json"])
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["session_path"] == str(session_path)
    assert payload["watch_command"] == f"linework watch --session {session_path}"
    assert (
        payload["watch_recommendation"]
        == "Open a watch for the user now so they can follow along live."
    )
    assert payload["inspect_command"] == f"linework inspect --session {session_path}"
    assert payload["export_command"] == f"linework export --session {session_path} --output out.png"
    assert "run_command" not in payload
    assert captured.err == ""


def test_new_plaintext_includes_watch_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from linework import cli

    session_path = tmp_path / "watched-session"

    exit_code = cli.main(["new", "--session", str(session_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert (
        "Recommended next step: open a watch for the user now so they can follow along live."
    ) in captured.out
    assert f"  linework watch --session {session_path}" in captured.out
    assert "Reuse this session path for iterative changes:" in captured.out
    assert captured.err == ""


def test_watch_impl_confirms_visibility_before_reporting_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Callable

    from linework import cli

    status_path = tmp_path / "startup.json"
    seen: dict[str, object] = {}

    class FakeWatcher:
        def run(self, *, on_visible: Callable[[], None] | None = None) -> None:
            seen["ran"] = True
            # Simulate the window becoming visible inside mainloop.
            if on_visible is not None:
                seen["on_visible_called"] = True
                on_visible()

    def fake_create_session_watcher(session: str, *, interval_ms: int) -> FakeWatcher:
        seen["session"] = session
        seen["interval_ms"] = interval_ms
        return FakeWatcher()

    monkeypatch.setattr(cli, "create_session_watcher", fake_create_session_watcher)

    exit_code = cli.main(
        [
            "_watch-impl",
            "--session",
            str(tmp_path / "session"),
            "--interval-ms",
            "375",
            "--startup-status",
            str(status_path),
        ]
    )

    assert exit_code == 0
    assert json.loads(status_path.read_text(encoding="utf-8")) == {"status": "ready"}
    assert seen == {
        "session": str(tmp_path / "session"),
        "interval_ms": 375,
        "ran": True,
        "on_visible_called": True,
    }


def test_watch_impl_reports_error_when_window_not_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from collections.abc import Callable

    from linework import cli

    status_path = tmp_path / "startup.json"

    class FakeWatcher:
        def run(self, *, on_visible: Callable[[], None] | None = None) -> None:
            # Simulate the window never becoming visible: don't call on_visible.
            pass

    def fake_create_session_watcher(session: str, *, interval_ms: int) -> FakeWatcher:
        return FakeWatcher()

    monkeypatch.setattr(cli, "create_session_watcher", fake_create_session_watcher)

    exit_code = cli.main(
        [
            "_watch-impl",
            "--session",
            str(tmp_path / "session"),
            "--startup-status",
            str(status_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "error"
    assert status["error_kind"] == "unavailable"
    assert "never became visible" in status["error"]
    assert "never became visible" in captured.err


def test_watch_impl_writes_error_status_when_startup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from linework import cli

    status_path = tmp_path / "startup.json"

    def fake_create_session_watcher(session: str, *, interval_ms: int) -> object:
        raise WatchUnavailableError("tkinter is unavailable in the active Python environment")

    monkeypatch.setattr(cli, "create_session_watcher", fake_create_session_watcher)

    exit_code = cli.main(
        [
            "_watch-impl",
            "--session",
            str(tmp_path / "session"),
            "--startup-status",
            str(status_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert json.loads(status_path.read_text(encoding="utf-8")) == {
        "status": "error",
        "error": "tkinter is unavailable in the active Python environment",
        "error_kind": "unavailable",
    }
    assert "tkinter is unavailable in the active Python environment" in captured.err


def test_watch_emits_hint_when_watcher_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from linework import cli

    session_path = tmp_path / "watch-session"
    create_session(
        session=str(session_path),
        name=None,
        width=800,
        height=800,
        background="#FFFFFF",
    )

    def fake_launch(session: str, *, interval_ms: int) -> int:
        raise WatchUnavailableError("tkinter is unavailable in the active Python environment")

    monkeypatch.setattr(cli, "_launch_detached_watcher", fake_launch)

    exit_code = cli.main(["watch", "--session", str(session_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Watcher unavailable" in captured.err
    assert "tkinter is unavailable in the active Python environment" in captured.err
    assert f"linework watch --session {session_path}" in captured.err
    assert captured.out == ""


def test_watch_reports_detached_windows_launch_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from linework import cli

    session_path = tmp_path / "watch-session"
    create_session(
        session=str(session_path),
        name=None,
        width=800,
        height=800,
        background="#FFFFFF",
    )

    def fake_launch(session: str, *, interval_ms: int) -> int:
        raise WatchUnavailableError(
            "cannot open watcher window: this process does not have access to the "
            "interactive desktop (detached or noninteractive context)"
        )

    monkeypatch.setattr(cli, "_launch_detached_watcher", fake_launch)

    exit_code = cli.main(["watch", "--session", str(session_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Watcher unavailable" in captured.err
    assert "does not have access to the interactive desktop" in captured.err
    assert f"linework watch --session {session_path}" in captured.err
    assert captured.out == ""


def test_watch_preserves_generic_startup_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from linework import cli

    session_path = tmp_path / "watch-session"
    create_session(
        session=str(session_path),
        name=None,
        width=800,
        height=800,
        background="#FFFFFF",
    )

    def fake_launch(session: str, *, interval_ms: int) -> int:
        raise WatchError("watcher startup failed")

    monkeypatch.setattr(cli, "_launch_detached_watcher", fake_launch)

    exit_code = cli.main(["watch", "--session", str(session_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "watcher startup failed" in captured.err
    assert "Watcher unavailable" not in captured.err
    assert captured.out == ""


def test_launch_detached_watcher_waits_for_ready_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import cli

    session_path = tmp_path / "watch-session"
    create_session(
        session=str(session_path),
        name=None,
        width=800,
        height=800,
        background="#FFFFFF",
    )

    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 32100

        def poll(self) -> int | None:
            return None

    def fake_launcher(cmd: object) -> FakeProcess:
        captured["cmd"] = list(cmd)  # type: ignore[arg-type]
        cmd_list: list[str] = captured["cmd"]  # type: ignore[assignment]
        status_path = Path(cmd_list[cmd_list.index("--startup-status") + 1])
        status_path.write_text(json.dumps({"status": "ready"}), encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr(cli, "_launch_detached_watcher_windows", fake_launcher)
    monkeypatch.setattr(cli, "_launch_detached_watcher_posix", fake_launcher)

    pid = cli._launch_detached_watcher(str(session_path), interval_ms=410)

    cmd: list[str] = captured["cmd"]  # type: ignore[assignment]
    assert pid == 32100
    watch_idx = cmd.index("_watch-impl")
    assert cmd[watch_idx:] == [
        "_watch-impl",
        "--session",
        str(session_path.resolve()),
        "--interval-ms",
        "410",
        "--startup-status",
        cmd[-1],
    ]
    assert Path(cmd[-1]).name == "startup.json"


def test_launch_detached_watcher_raises_startup_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import cli

    session_path = tmp_path / "watch-session"
    create_session(
        session=str(session_path),
        name=None,
        width=800,
        height=800,
        background="#FFFFFF",
    )

    class FakeProcess:
        pid = 32101

        def poll(self) -> int | None:
            return None

    def fake_launcher(cmd: object) -> FakeProcess:
        cmd_list = list(cmd)  # type: ignore[arg-type]
        status_path = Path(cmd_list[cmd_list.index("--startup-status") + 1])
        status_path.write_text(
            json.dumps({"status": "error", "error": "watcher startup failed"}),
            encoding="utf-8",
        )
        return FakeProcess()

    monkeypatch.setattr(cli, "_launch_detached_watcher_windows", fake_launcher)
    monkeypatch.setattr(cli, "_launch_detached_watcher_posix", fake_launcher)

    with pytest.raises(WatchError, match="watcher startup failed"):
        cli._launch_detached_watcher(str(session_path))


def test_launch_detached_watcher_preserves_unavailable_startup_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import cli

    session_path = tmp_path / "watch-session"
    create_session(
        session=str(session_path),
        name=None,
        width=800,
        height=800,
        background="#FFFFFF",
    )

    class FakeProcess:
        pid = 32103

        def poll(self) -> int | None:
            return None

    def fake_launcher(cmd: object) -> FakeProcess:
        cmd_list = list(cmd)  # type: ignore[arg-type]
        status_path = Path(cmd_list[cmd_list.index("--startup-status") + 1])
        status_path.write_text(
            json.dumps(
                {
                    "status": "error",
                    "error": "watcher requires an interactive Windows desktop session",
                    "error_kind": "unavailable",
                }
            ),
            encoding="utf-8",
        )
        return FakeProcess()

    monkeypatch.setattr(cli, "_launch_detached_watcher_windows", fake_launcher)
    monkeypatch.setattr(cli, "_launch_detached_watcher_posix", fake_launcher)

    with pytest.raises(WatchUnavailableError, match="interactive Windows desktop session"):
        cli._launch_detached_watcher(str(session_path))


def test_launch_detached_watcher_errors_when_child_exits_before_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import cli

    session_path = tmp_path / "watch-session"
    create_session(
        session=str(session_path),
        name=None,
        width=800,
        height=800,
        background="#FFFFFF",
    )

    class FakeProcess:
        pid = 32102

        def poll(self) -> int | None:
            return 7

    monkeypatch.setattr(cli, "_launch_detached_watcher_windows", lambda cmd: FakeProcess())
    monkeypatch.setattr(cli, "_launch_detached_watcher_posix", lambda cmd: FakeProcess())

    with pytest.raises(WatchError, match="exit code 7"):
        cli._launch_detached_watcher(str(session_path))


def test_watch_impl_command_prefers_pythonw_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    from linework import cli

    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.sys, "executable", r"C:\Python312\python.exe")
    monkeypatch.setattr(cli.Path, "is_file", lambda self: str(self).endswith("pythonw.exe"))

    assert cli._watch_impl_command() == [
        r"C:\Python312\pythonw.exe",
        "-m",
        "linework",
        "_watch-impl",
    ]


def test_launch_detached_watcher_windows_uses_powershell_start_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from linework import cli

    captured: dict[str, object] = {}

    def fake_desktop_check() -> None:
        captured["desktop_checked"] = True

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="41000", stderr="")

    monkeypatch.setattr(cli, "_ensure_windows_interactive_desktop", fake_desktop_check)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    process = cli._launch_detached_watcher_windows(
        [r"C:\Python312\pythonw.exe", "-m", "linework", "_watch-impl", "--session", r"C:\tmp\s"]
    )

    assert process.pid == 41000
    assert captured["desktop_checked"] is True
    command = captured["command"]
    kwargs = captured["kwargs"]
    assert command[:6] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
    ]
    assert "Start-Process" in str(command[6])
    assert "-PassThru" in str(command[6])
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True


def test_launch_detached_watcher_windows_requires_interactive_desktop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from linework import cli

    def fake_desktop_check() -> None:
        raise WatchError("watcher requires an interactive Windows desktop session")

    monkeypatch.setattr(cli, "_ensure_windows_interactive_desktop", fake_desktop_check)

    with pytest.raises(WatchError, match="interactive Windows desktop session"):
        cli._launch_detached_watcher_windows(["pythonw.exe", "-m", "linework", "_watch-impl"])


def test_windows_interactive_desktop_requires_winsta0(monkeypatch: pytest.MonkeyPatch) -> None:
    from linework import cli

    monkeypatch.setattr(cli, "_current_windows_window_station_name", lambda: "Service-0x0-3e7$")
    monkeypatch.setattr(cli, "_current_windows_thread_desktop_name", lambda: "Default")
    monkeypatch.setattr(cli, "_input_windows_desktop_name", lambda: "Default")

    with pytest.raises(
        WatchUnavailableError,
        match="does not have access to the interactive desktop",
    ):
        cli._ensure_windows_interactive_desktop()


def test_windows_interactive_desktop_requires_active_input_desktop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from linework import cli

    monkeypatch.setattr(cli, "_current_windows_window_station_name", lambda: "WinSta0")
    monkeypatch.setattr(cli, "_current_windows_thread_desktop_name", lambda: "Detached")
    monkeypatch.setattr(cli, "_input_windows_desktop_name", lambda: "Default")

    with pytest.raises(
        WatchUnavailableError,
        match="does not have access to the interactive desktop",
    ):
        cli._ensure_windows_interactive_desktop()


def test_windows_interactive_desktop_passes_on_winsta0_with_matching_desktop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from linework import cli

    monkeypatch.setattr(cli, "_current_windows_window_station_name", lambda: "WinSta0")
    monkeypatch.setattr(cli, "_current_windows_thread_desktop_name", lambda: "Default")
    monkeypatch.setattr(cli, "_input_windows_desktop_name", lambda: "Default")

    cli._ensure_windows_interactive_desktop()  # should not raise


def test_launch_detached_watcher_uses_windows_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import cli

    session_path = tmp_path / "watch-session"
    create_session(
        session=str(session_path),
        name=None,
        width=800,
        height=800,
        background="#FFFFFF",
    )

    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 41001

        def poll(self) -> int | None:
            return None

    def fake_windows_launcher(cmd: list[str]) -> FakeProcess:
        captured["cmd"] = cmd
        return FakeProcess()

    def fake_await(process: object, status_path: Path) -> None:
        captured["pid"] = getattr(process, "pid")
        captured["status_name"] = status_path.name

    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(
        cli,
        "_watch_impl_command",
        lambda: [r"C:\Python312\pythonw.exe", "-m", "linework", "_watch-impl"],
    )
    monkeypatch.setattr(cli, "_launch_detached_watcher_windows", fake_windows_launcher)
    monkeypatch.setattr(cli, "_await_watcher_startup", fake_await)

    pid = cli._launch_detached_watcher(str(session_path), interval_ms=333)

    assert pid == 41001
    assert captured["pid"] == 41001
    assert captured["status_name"] == "startup.json"
    assert captured["cmd"][:7] == [
        r"C:\Python312\pythonw.exe",
        "-m",
        "linework",
        "_watch-impl",
        "--session",
        str(session_path.resolve()),
        "--interval-ms",
    ]
    assert captured["cmd"][7] == "333"
    assert captured["cmd"][8] == "--startup-status"


def test_writer_lock_blocks_overlapping_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
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
