"""Tests for milestone 4: core agent loop (run, inspect, export, --json errors)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from mural.storage.session import apply_batch, create_session, export_session, inspect_session


def run_cli(
    *args: str, env: dict[str, str] | None = None, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
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
        input=stdin,
    )


def make_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a small test session and return its path."""
    from mural import config

    monkeypatch.setattr(config, "mural_home", lambda: tmp_path / "mural-home")
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
# mural run (API level)
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


# ---------------------------------------------------------------------------
# mural inspect (API level)
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
# mural export (API level)
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
# CLI integration: mural run
# ---------------------------------------------------------------------------


class TestRunCLI:
    def test_run_from_stdin_json(self, tmp_path: Path) -> None:
        mural_home = tmp_path / "mural-home"
        session_path = tmp_path / "cli-session"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"MURAL_HOME": str(mural_home)},
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
            env={"MURAL_HOME": str(mural_home)},
            stdin=jsonl,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["applied"] == 2
        assert payload["failed"] is None
        assert len(payload["results"]) == 2
        assert payload["results"][0]["object_id"] == "obj_000001"

    def test_run_partial_failure_json(self, tmp_path: Path) -> None:
        mural_home = tmp_path / "mural-home"
        session_path = tmp_path / "cli-session"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"MURAL_HOME": str(mural_home)},
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
            env={"MURAL_HOME": str(mural_home)},
            stdin=jsonl,
        )
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload["applied"] == 1
        assert payload["failed"] is not None
        assert payload["failed"]["op"] == "bad.op"

    def test_run_from_file(self, tmp_path: Path) -> None:
        mural_home = tmp_path / "mural-home"
        session_path = tmp_path / "cli-session"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"MURAL_HOME": str(mural_home)},
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
            env={"MURAL_HOME": str(mural_home)},
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["applied"] == 1


# ---------------------------------------------------------------------------
# CLI integration: mural inspect
# ---------------------------------------------------------------------------


class TestInspectCLI:
    def test_inspect_json(self, tmp_path: Path) -> None:
        mural_home = tmp_path / "mural-home"
        session_path = tmp_path / "cli-session"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"MURAL_HOME": str(mural_home)},
        )
        result = run_cli(
            "inspect",
            "--session",
            str(session_path),
            "--json",
            env={"MURAL_HOME": str(mural_home)},
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["session_id"] == "cli-session"
        assert payload["object_count"] == 0
        assert payload["canvas"]["width"] == 1200
        assert "latest_render" in payload

    def test_inspect_human_readable(self, tmp_path: Path) -> None:
        mural_home = tmp_path / "mural-home"
        session_path = tmp_path / "cli-session"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"MURAL_HOME": str(mural_home)},
        )
        result = run_cli(
            "inspect",
            "--session",
            str(session_path),
            env={"MURAL_HOME": str(mural_home)},
        )
        assert result.returncode == 0
        assert "Session: cli-session" in result.stdout
        assert "Canvas: 1200x800" in result.stdout

    def test_inspect_missing_session_json_error(self, tmp_path: Path) -> None:
        mural_home = tmp_path / "mural-home"
        result = run_cli(
            "inspect",
            "--session",
            str(tmp_path / "nonexistent"),
            "--json",
            env={"MURAL_HOME": str(mural_home)},
        )
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert "error" in payload


# ---------------------------------------------------------------------------
# CLI integration: mural export
# ---------------------------------------------------------------------------


class TestExportCLI:
    def test_export_json(self, tmp_path: Path) -> None:
        mural_home = tmp_path / "mural-home"
        session_path = tmp_path / "cli-session"
        out_path = tmp_path / "exported.png"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"MURAL_HOME": str(mural_home)},
        )
        result = run_cli(
            "export",
            "--session",
            str(session_path),
            "--out",
            str(out_path),
            "--json",
            env={"MURAL_HOME": str(mural_home)},
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
            env={"MURAL_HOME": str(tmp_path / "mural-home")},
        )
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert "error" in payload
        assert "background" in payload["error"]
        assert result.stderr == ""

    def test_run_bad_jsonl_json_error(self, tmp_path: Path) -> None:
        mural_home = tmp_path / "mural-home"
        session_path = tmp_path / "cli-session"
        run_cli(
            "new",
            "--session",
            str(session_path),
            env={"MURAL_HOME": str(mural_home)},
        )
        result = run_cli(
            "run",
            "--session",
            str(session_path),
            "--json",
            env={"MURAL_HOME": str(mural_home)},
            stdin="not valid json\n",
        )
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert "error" in payload
