"""Tests for milestone 4: core agent loop (run, inspect, export, --json errors)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from linework.storage.session import apply_batch, create_session, export_session, inspect_session


def run_cli(
    *args: str, env: dict[str, str] | None = None, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the linework CLI in a subprocess."""
    command_env = os.environ.copy()
    if env is not None:
        command_env.update(env)

    cli_args = list(args)
    if cli_args[:1] == ["new"] and "--headless" not in cli_args and "--help" not in cli_args:
        cli_args.append("--headless")

    return subprocess.run(
        [sys.executable, "-m", "linework", *cli_args],
        check=False,
        capture_output=True,
        text=True,
        env=command_env,
        input=stdin,
    )


def make_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a small test session and return its path."""
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = tmp_path / "test-session"
    create_session(
        session=str(session_path),
        name=None,
        width=200,
        height=160,
        background="#FFFFFF",
    )
    return session_path


# ---------------------------------------------------------------------------
# linework run (API level)
# ---------------------------------------------------------------------------


class TestApplyBatch:
    def test_batch_applies_multiple_operations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_path = make_session(tmp_path, monkeypatch)
        result = apply_batch(
            session_path,
            operations=[
                {
                    "op": "draw.rect",
                    "payload": {"x": 10, "y": 10, "width": 50, "height": 40, "fill": "#FF0000"},
                },
                {
                    "op": "draw.text",
                    "payload": {"x": 20, "y": 60, "text": "hello", "size": 16},
                },
            ],
        )
        assert result.applied == 2
        assert result.failed is None
        assert len(result.results) == 2
        assert result.results[0]["op"] == "draw.rect"
        assert result.results[0]["object_id"] == "obj_000001"
        assert result.results[1]["op"] == "draw.text"
        assert result.results[1]["object_id"] == "obj_000002"
        assert result.scene_object_count == 2

    def test_batch_stops_on_first_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_path = make_session(tmp_path, monkeypatch)
        result = apply_batch(
            session_path,
            operations=[
                {
                    "op": "draw.rect",
                    "payload": {"x": 10, "y": 10, "width": 50, "height": 40},
                },
                {
                    "op": "draw.rect",
                    "payload": {"x": 10, "y": 10, "width": -1, "height": 40},
                },
                {
                    "op": "draw.line",
                    "payload": {"x1": 0, "y1": 0, "x2": 50, "y2": 50},
                },
            ],
        )
        assert result.applied == 1
        assert result.failed is not None
        assert result.failed["op"] == "draw.rect"
        assert "positive" in result.failed["error"]
        assert result.scene_object_count == 1

    def test_batch_empty_input(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        session_path = make_session(tmp_path, monkeypatch)
        result = apply_batch(session_path, operations=[])
        assert result.applied == 0
        assert result.failed is None

    def test_batch_renders_once_at_end(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_path = make_session(tmp_path, monkeypatch)
        apply_batch(
            session_path,
            operations=[
                {
                    "op": "draw.rect",
                    "payload": {"x": 10, "y": 10, "width": 80, "height": 60, "fill": "#0000FF"},
                },
            ],
        )
        with Image.open(session_path / "render" / "latest.png") as img:
            assert img.getpixel((30, 30)) == (0, 0, 255, 255)

    def test_batch_large_input(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        session_path = make_session(tmp_path, monkeypatch)
        operations = [
            {
                "op": "draw.rect",
                "payload": {
                    "x": 2 * index,
                    "y": 2 * index,
                    "width": 10,
                    "height": 8,
                    "label": f"box-{index}",
                },
            }
            for index in range(40)
        ]

        result = apply_batch(session_path, operations=operations)

        assert result.applied == 40
        assert result.failed is None
        assert len(result.results) == 40
        assert result.scene_object_count == 40

    def test_batch_supports_label_based_edit_and_delete(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_path = make_session(tmp_path, monkeypatch)
        apply_batch(
            session_path,
            operations=[
                {
                    "op": "draw.rect",
                    "payload": {
                        "x": 10,
                        "y": 10,
                        "width": 50,
                        "height": 40,
                        "label": "box",
                    },
                },
            ],
        )

        edit_result = apply_batch(
            session_path,
            operations=[
                {
                    "op": "edit.rect",
                    "payload": {"label": "box", "fill": "#00FF00"},
                },
            ],
        )
        assert edit_result.applied == 1
        assert inspect_session(session_path).objects[0]["fill"] == "#00FF00"

        delete_result = apply_batch(
            session_path,
            operations=[
                {
                    "op": "delete",
                    "payload": {"label": "box"},
                },
            ],
        )
        assert delete_result.applied == 1
        assert inspect_session(session_path).objects == []

    def test_batch_undo_within_batch_only_removes_last_batch_operation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_path = make_session(tmp_path, monkeypatch)
        result = apply_batch(
            session_path,
            operations=[
                {
                    "op": "draw.rect",
                    "payload": {"x": 10, "y": 10, "width": 50, "height": 40},
                },
                {
                    "op": "draw.text",
                    "payload": {"x": 20, "y": 60, "text": "hello", "size": 16},
                },
                {"op": "undo", "payload": {}},
            ],
        )

        assert result.applied == 3
        assert result.failed is None
        inspected = inspect_session(session_path)
        assert inspected.object_count == 1
        assert inspected.objects[0]["type"] == "rect"

    def test_batch_unsupported_command_suggests_valid_ops(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_path = make_session(tmp_path, monkeypatch)
        result = apply_batch(
            session_path,
            operations=[
                {
                    "op": "draw.oval",
                    "payload": {"x": 10, "y": 10, "width": 50, "height": 40},
                }
            ],
        )

        assert result.applied == 0
        assert result.failed is not None
        assert result.failed["op"] == "draw.oval"
        assert "did you mean draw.ellipse?" in result.failed["error"]
        assert "valid draw ops:" in result.failed["error"]
        assert "draw.arrow" in result.failed["error"]
        assert "draw.circle" in result.failed["error"]


# ---------------------------------------------------------------------------
# linework inspect (API level)
# ---------------------------------------------------------------------------


class TestInspectSession:
    def test_inspect_empty_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        session_path = make_session(tmp_path, monkeypatch)
        result = inspect_session(session_path)
        assert result.object_count == 0
        assert result.objects == []
        assert result.session_id == "test-session"
        assert result.canvas.width == 200

    def test_inspect_after_mutations(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        session_path = make_session(tmp_path, monkeypatch)
        apply_batch(
            session_path,
            operations=[
                {
                    "op": "draw.rect",
                    "payload": {
                        "x": 5,
                        "y": 5,
                        "width": 20,
                        "height": 10,
                        "label": "box",
                    },
                },
            ],
        )
        result = inspect_session(session_path)
        assert result.object_count == 1
        assert result.objects[0]["type"] == "rect"
        assert result.objects[0]["label"] == "box"


# ---------------------------------------------------------------------------
# linework export (API level)
# ---------------------------------------------------------------------------


class TestExportSession:
    def test_export_copies_render(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        session_path = make_session(tmp_path, monkeypatch)
        out = tmp_path / "output" / "exported.png"
        result_path = export_session(session_path, out=str(out))
        assert Path(result_path).is_file()
        with Image.open(result_path) as img:
            assert img.size == (200, 160)


# ---------------------------------------------------------------------------
# CLI integration: linework run
# ---------------------------------------------------------------------------


class TestRunCLI:
    def test_run_from_stdin_json(self, tmp_path: Path) -> None:
        linework_home = tmp_path / "linework-home"
        session_path = tmp_path / "cli-session"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"LINEWORK_HOME": str(linework_home)},
        )
        jsonl = (
            '{"op":"draw.rect","payload":{"x":10,"y":10,"width":50,"height":30}}\n'
            '{"op":"draw.text","payload":{"x":20,"y":60,"text":"hi","size":14}}\n'
        )
        result = run_cli(
            "run",
            "--session",
            str(session_path),
            "--json",
            env={"LINEWORK_HOME": str(linework_home)},
            stdin=jsonl,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["applied"] == 2
        assert payload["failed"] is None
        assert len(payload["results"]) == 2
        assert payload["results"][0]["object_id"] == "obj_000001"

    def test_run_partial_failure_json(self, tmp_path: Path) -> None:
        linework_home = tmp_path / "linework-home"
        session_path = tmp_path / "cli-session"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"LINEWORK_HOME": str(linework_home)},
        )
        jsonl = (
            '{"op":"draw.rect","payload":{"x":10,"y":10,"width":50,"height":30}}\n'
            '{"op":"bad.op","payload":{}}\n'
        )
        result = run_cli(
            "run",
            "--session",
            str(session_path),
            "--json",
            env={"LINEWORK_HOME": str(linework_home)},
            stdin=jsonl,
        )
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload["applied"] == 1
        assert payload["failed"] is not None
        assert payload["failed"]["op"] == "bad.op"

    def test_run_without_session_can_export_one_shot_png(self, tmp_path: Path) -> None:
        linework_home = tmp_path / "linework-home"
        out_path = tmp_path / "one-shot.png"
        result = run_cli(
            "run",
            "--out",
            str(out_path),
            "--json",
            env={"LINEWORK_HOME": str(linework_home)},
            stdin='{"op":"draw.circle","payload":{"x":20,"y":20,"radius":24,"fill":"#FF0000"}}\n',
        )

        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["applied"] == 1
        assert payload["exported_path"] == str(out_path.resolve())
        assert "session_path" not in payload
        assert "latest_render" not in payload
        assert out_path.is_file()
        with Image.open(out_path) as exported:
            assert exported.getpixel((40, 40)) == (255, 0, 0, 255)

    def test_run_without_session_can_override_one_shot_canvas(self, tmp_path: Path) -> None:
        linework_home = tmp_path / "linework-home"
        out_path = tmp_path / "one-shot-background.png"
        result = run_cli(
            "run",
            "--out",
            str(out_path),
            "--width",
            "320",
            "--height",
            "200",
            "--background",
            "#111827",
            "--json",
            env={"LINEWORK_HOME": str(linework_home)},
            stdin='{"op":"draw.circle","payload":{"x":20,"y":20,"radius":24,"fill":"#FF0000"}}\n',
        )

        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["applied"] == 1
        assert payload["exported_path"] == str(out_path.resolve())
        with Image.open(out_path) as exported:
            assert exported.size == (320, 200)
            assert exported.getpixel((5, 5)) == (17, 24, 39, 255)
            assert exported.getpixel((40, 40)) == (255, 0, 0, 255)

    def test_run_requires_session_or_out_json_error(self, tmp_path: Path) -> None:
        result = run_cli(
            "run",
            "--json",
            env={"LINEWORK_HOME": str(tmp_path / "linework-home")},
            stdin='{"op":"draw.rect","payload":{"x":10,"y":10,"width":50,"height":30}}\n',
        )

        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload == {"error": "either --session or --out must be provided"}

    def test_run_from_file(self, tmp_path: Path) -> None:
        linework_home = tmp_path / "linework-home"
        session_path = tmp_path / "cli-session"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"LINEWORK_HOME": str(linework_home)},
        )
        jsonl_file = tmp_path / "ops.jsonl"
        jsonl_file.write_text(
            '{"op":"draw.line","payload":{"x1":0,"y1":0,"x2":100,"y2":100}}\n',
            encoding="utf-8",
        )
        result = run_cli(
            "run",
            "--session",
            str(session_path),
            "--file",
            str(jsonl_file),
            "--json",
            env={"LINEWORK_HOME": str(linework_home)},
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["applied"] == 1


# ---------------------------------------------------------------------------
# CLI integration: linework inspect
# ---------------------------------------------------------------------------


class TestInspectCLI:
    def test_inspect_json(self, tmp_path: Path) -> None:
        linework_home = tmp_path / "linework-home"
        session_path = tmp_path / "cli-session"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"LINEWORK_HOME": str(linework_home)},
        )
        result = run_cli(
            "inspect",
            "--session",
            str(session_path),
            "--json",
            env={"LINEWORK_HOME": str(linework_home)},
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["session_id"] == "cli-session"
        assert payload["object_count"] == 0
        assert payload["canvas"]["width"] == 800
        assert "latest_render" in payload

    def test_inspect_human_readable(self, tmp_path: Path) -> None:
        linework_home = tmp_path / "linework-home"
        session_path = tmp_path / "cli-session"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"LINEWORK_HOME": str(linework_home)},
        )
        result = run_cli(
            "inspect",
            "--session",
            str(session_path),
            env={"LINEWORK_HOME": str(linework_home)},
        )
        assert result.returncode == 0
        assert "Session: cli-session" in result.stdout
        assert "Canvas: 800x800" in result.stdout

    def test_inspect_missing_session_json_error(self, tmp_path: Path) -> None:
        linework_home = tmp_path / "linework-home"
        result = run_cli(
            "inspect",
            "--session",
            str(tmp_path / "nonexistent"),
            "--json",
            env={"LINEWORK_HOME": str(linework_home)},
        )
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert set(payload) == {"error"}


# ---------------------------------------------------------------------------
# CLI integration: linework export
# ---------------------------------------------------------------------------


class TestExportCLI:
    def test_export_json(self, tmp_path: Path) -> None:
        linework_home = tmp_path / "linework-home"
        session_path = tmp_path / "cli-session"
        out_path = tmp_path / "exported.png"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"LINEWORK_HOME": str(linework_home)},
        )
        result = run_cli(
            "export",
            "--session",
            str(session_path),
            "--out",
            str(out_path),
            "--json",
            env={"LINEWORK_HOME": str(linework_home)},
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert Path(payload["exported_path"]).is_file()


# ---------------------------------------------------------------------------
# --json error contract
# ---------------------------------------------------------------------------


class TestJsonErrorContract:
    def test_new_invalid_background_json_error(self, tmp_path: Path) -> None:
        result = run_cli(
            "new",
            "--session",
            str(tmp_path / "bad"),
            "--background",
            "red",
            "--json",
            env={"LINEWORK_HOME": str(tmp_path / "linework-home")},
        )
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert set(payload) == {"error"}
        assert "background" in payload["error"]
        assert result.stderr == ""

    def test_run_bad_jsonl_json_error(self, tmp_path: Path) -> None:
        linework_home = tmp_path / "linework-home"
        session_path = tmp_path / "cli-session"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"LINEWORK_HOME": str(linework_home)},
        )
        result = run_cli(
            "run",
            "--session",
            str(session_path),
            "--json",
            env={"LINEWORK_HOME": str(linework_home)},
            stdin="not valid json\n",
        )
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert set(payload) == {"error"}

    def test_run_rejects_one_shot_canvas_options_with_session_json_error(
        self, tmp_path: Path
    ) -> None:
        linework_home = tmp_path / "linework-home"
        session_path = tmp_path / "cli-session"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"LINEWORK_HOME": str(linework_home)},
        )
        result = run_cli(
            "run",
            "--session",
            str(session_path),
            "--width",
            "320",
            "--height",
            "200",
            "--background",
            "#111827",
            "--json",
            env={"LINEWORK_HOME": str(linework_home)},
            stdin='{"op":"undo","payload":{}}\n',
        )

        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert set(payload) == {"error"}
        assert "--background" in payload["error"]
        assert "--width" in payload["error"]
        assert "--height" in payload["error"]
        assert result.stderr == ""
