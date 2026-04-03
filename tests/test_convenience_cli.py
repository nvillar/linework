"""Tests for milestone 5: convenience CLI commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


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


def create_cli_session(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Create a test session through the CLI."""
    mural_home = tmp_path / "mural-home"
    session_path = tmp_path / "cli-session"
    env = {"MURAL_HOME": str(mural_home)}

    result = run_cli("new", "--session", str(session_path), env=env)
    assert result.returncode == 0
    return session_path, env


def read_scene(session_path: Path) -> dict[str, object]:
    """Read a scene snapshot from disk."""
    return json.loads((session_path / "scene.json").read_text(encoding="utf-8"))


def test_draw_help_lists_delivered_primitives_only() -> None:
    result = run_cli("draw", "--help")

    assert result.returncode == 0
    for primitive in ("line", "rect", "ellipse", "polyline", "text"):
        assert primitive in result.stdout
    assert "image" not in result.stdout
    assert result.stderr == ""


def test_edit_help_lists_delivered_primitives_only() -> None:
    result = run_cli("edit", "--help")

    assert result.returncode == 0
    for primitive in ("line", "rect", "ellipse", "polyline", "text"):
        assert primitive in result.stdout
    assert "image" not in result.stdout
    assert result.stderr == ""


def test_draw_rect_json_matches_single_operation_contract(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    result = run_cli(
        "draw",
        "rect",
        "--session",
        str(session_path),
        "--x",
        "10",
        "--y",
        "20",
        "--width",
        "60",
        "--height",
        "40",
        "--fill",
        "#FF0000",
        "--json",
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["applied"] == 1
    assert payload["failed"] is None
    assert payload["results"] == [
        {"op_id": "op_000001", "op": "draw.rect", "object_id": "obj_000001"}
    ]
    assert payload["scene_object_count"] == 1
    assert payload["session_path"] == str(session_path)
    assert result.stderr == ""

    scene = read_scene(session_path)
    assert scene["objects"][0]["type"] == "rect"
    assert scene["objects"][0]["fill"] == "#FF0000"


def test_draw_polyline_accepts_repeated_points(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    result = run_cli(
        "draw",
        "polyline",
        "--session",
        str(session_path),
        "--point",
        "0,0",
        "--point",
        "10,20",
        "--point",
        "20,10",
        "--json",
        env=env,
    )

    assert result.returncode == 0
    scene = read_scene(session_path)
    assert scene["objects"][0]["points"] == [[0.0, 0.0], [10.0, 20.0], [20.0, 10.0]]


def test_edit_rect_json_updates_existing_object(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    draw_result = run_cli(
        "draw",
        "rect",
        "--session",
        str(session_path),
        "--x",
        "10",
        "--y",
        "10",
        "--width",
        "50",
        "--height",
        "30",
        env=env,
    )
    assert draw_result.returncode == 0

    result = run_cli(
        "edit",
        "rect",
        "--session",
        str(session_path),
        "--id",
        "obj_000001",
        "--x",
        "25",
        "--fill",
        "#00FF00",
        "--json",
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["results"] == [
        {"op_id": "op_000002", "op": "edit.rect", "object_id": "obj_000001"}
    ]
    assert payload["scene_object_count"] == 1

    scene = read_scene(session_path)
    assert scene["objects"][0]["x"] == 25.0
    assert scene["objects"][0]["fill"] == "#00FF00"


def test_edit_requires_at_least_one_field(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    result = run_cli(
        "edit",
        "rect",
        "--session",
        str(session_path),
        "--id",
        "obj_000001",
        "--json",
        env=env,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["error"] == "at least one field must be provided for edit"
    assert result.stderr == ""


def test_delete_human_readable_output(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    draw_result = run_cli(
        "draw",
        "text",
        "--session",
        str(session_path),
        "--x",
        "10",
        "--y",
        "15",
        "--text",
        "hello",
        env=env,
    )
    assert draw_result.returncode == 0

    result = run_cli(
        "delete",
        "--session",
        str(session_path),
        "--id",
        "obj_000001",
        env=env,
    )

    assert result.returncode == 0
    assert "Deleted object: obj_000001" in result.stdout
    assert "Operation ID: op_000002" in result.stdout
    assert "Objects: 0" in result.stdout
    assert result.stderr == ""
    assert read_scene(session_path)["objects"] == []


def test_undo_json_success_and_error_contract(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    empty_result = run_cli(
        "undo",
        "--session",
        str(session_path),
        "--json",
        env=env,
    )
    assert empty_result.returncode == 1
    empty_payload = json.loads(empty_result.stdout)
    assert "nothing to undo" in empty_payload["error"]
    assert empty_result.stderr == ""

    draw_result = run_cli(
        "draw",
        "line",
        "--session",
        str(session_path),
        "--x1",
        "0",
        "--y1",
        "0",
        "--x2",
        "20",
        "--y2",
        "20",
        env=env,
    )
    assert draw_result.returncode == 0

    result = run_cli(
        "undo",
        "--session",
        str(session_path),
        "--json",
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["results"] == [{"op_id": "op_000002", "op": "undo", "object_id": None}]
    assert payload["scene_object_count"] == 0
    assert read_scene(session_path)["objects"] == []
