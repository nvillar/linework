"""Tests for milestone 5: convenience CLI commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
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
    )


def create_cli_session(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Create a test session through the CLI."""
    linework_home = tmp_path / "linework-home"
    session_path = tmp_path / "cli-session"
    env = {"LINEWORK_HOME": str(linework_home)}

    result = run_cli("new", "--session", str(session_path), env=env)
    assert result.returncode == 0
    return session_path, env


def read_scene(session_path: Path) -> dict[str, object]:
    """Read a scene snapshot from disk."""
    return json.loads((session_path / "scene.json").read_text(encoding="utf-8"))


def test_draw_help_lists_delivered_primitives_only() -> None:
    result = run_cli("draw", "--help")

    assert result.returncode == 0
    for primitive in (
        "line",
        "arrow",
        "rect",
        "ellipse",
        "circle",
        "polyline",
        "polygon",
        "text",
        "image",
    ):
        assert primitive in result.stdout
    assert "Examples:" in result.stdout
    assert result.stderr == ""


def test_edit_help_lists_delivered_primitives_only() -> None:
    result = run_cli("edit", "--help")

    assert result.returncode == 0
    for primitive in (
        "line",
        "arrow",
        "rect",
        "ellipse",
        "circle",
        "polyline",
        "polygon",
        "text",
        "image",
    ):
        assert primitive in result.stdout
    assert "When --id is omitted" in result.stdout
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


def test_draw_polygon_accepts_points_and_fill(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    result = run_cli(
        "draw",
        "polygon",
        "--session",
        str(session_path),
        "--point",
        "0,0",
        "--point",
        "20,0",
        "--point",
        "10,15",
        "--fill",
        "#FF66CC",
        "--json",
        env=env,
    )

    assert result.returncode == 0
    scene = read_scene(session_path)
    assert scene["objects"][0]["type"] == "polygon"
    assert scene["objects"][0]["points"] == [[0.0, 0.0], [20.0, 0.0], [10.0, 15.0]]
    assert scene["objects"][0]["fill"] == "#FF66CC"


def test_draw_circle_json_creates_ellipse_geometry(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    result = run_cli(
        "draw",
        "circle",
        "--session",
        str(session_path),
        "--x",
        "15",
        "--y",
        "20",
        "--radius",
        "18",
        "--fill",
        "#FF0000",
        "--json",
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["results"] == [
        {"op_id": "op_000001", "op": "draw.circle", "object_id": "obj_000001"}
    ]
    scene = read_scene(session_path)
    assert scene["objects"][0]["type"] == "ellipse"
    assert scene["objects"][0]["x"] == 15.0
    assert scene["objects"][0]["width"] == 36.0
    assert scene["objects"][0]["height"] == 36.0


def test_draw_arrow_accepts_arrowhead_and_size(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    result = run_cli(
        "draw",
        "arrow",
        "--session",
        str(session_path),
        "--x1",
        "10",
        "--y1",
        "40",
        "--x2",
        "120",
        "--y2",
        "40",
        "--arrowhead",
        "both",
        "--arrow-size",
        "18",
        "--json",
        env=env,
    )

    assert result.returncode == 0
    scene = read_scene(session_path)
    assert scene["objects"][0]["type"] == "arrow"
    assert scene["objects"][0]["arrowhead"] == "both"
    assert scene["objects"][0]["arrow_size"] == 18.0


def test_edit_circle_keeps_round_geometry(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    draw_result = run_cli(
        "draw",
        "circle",
        "--session",
        str(session_path),
        "--x",
        "10",
        "--y",
        "10",
        "--radius",
        "15",
        env=env,
    )
    assert draw_result.returncode == 0

    result = run_cli(
        "edit",
        "circle",
        "--session",
        str(session_path),
        "--id",
        "obj_000001",
        "--radius",
        "22",
        "--json",
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["results"] == [
        {"op_id": "op_000002", "op": "edit.circle", "object_id": "obj_000001"}
    ]
    scene = read_scene(session_path)
    assert scene["objects"][0]["width"] == 44.0
    assert scene["objects"][0]["height"] == 44.0


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


def test_draw_text_accepts_box_layout(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    result = run_cli(
        "draw",
        "text",
        "--session",
        str(session_path),
        "--x",
        "100",
        "--y",
        "20",
        "--width",
        "80",
        "--height",
        "60",
        "--text",
        "Wrap this label into multiple lines",
        "--align",
        "left",
        "--valign",
        "top",
        "--padding",
        "6",
        "--json",
        env=env,
    )

    assert result.returncode == 0
    scene = read_scene(session_path)
    assert scene["objects"][0]["width"] == 80.0
    assert scene["objects"][0]["height"] == 60.0
    assert scene["objects"][0]["align"] == "left"
    assert scene["objects"][0]["valign"] == "top"
    assert scene["objects"][0]["padding"] == 6.0


def test_edit_rect_by_tag_updates_unique_object(tmp_path: Path) -> None:
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
        "--tag",
        "box",
        env=env,
    )
    assert draw_result.returncode == 0

    result = run_cli(
        "edit",
        "rect",
        "--session",
        str(session_path),
        "--tag",
        "box",
        "--fill",
        "#00FF00",
        "--json",
        env=env,
    )

    assert result.returncode == 0
    scene = read_scene(session_path)
    assert scene["objects"][0]["fill"] == "#00FF00"
    assert scene["objects"][0]["tag"] == "box"


def test_edit_with_id_can_still_change_tag(tmp_path: Path) -> None:
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
        "--tag",
        "box",
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
        "--tag",
        "renamed-box",
        "--json",
        env=env,
    )

    assert result.returncode == 0
    scene = read_scene(session_path)
    assert scene["objects"][0]["tag"] == "renamed-box"


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
    assert set(payload) == {"error"}
    assert payload["error"] == "at least one field must be provided for edit"
    assert result.stderr == ""


def test_edit_requires_id_or_tag_selector(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    result = run_cli(
        "edit",
        "rect",
        "--session",
        str(session_path),
        "--fill",
        "#00FF00",
        "--json",
        env=env,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert set(payload) == {"error"}
    assert payload["error"] == "id or tag must be provided for edit"
    assert result.stderr == ""


def test_edit_by_tag_rejects_ambiguous_matches(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    for x in ("10", "80"):
        draw_result = run_cli(
            "draw",
            "rect",
            "--session",
            str(session_path),
            "--x",
            x,
            "--y",
            "10",
            "--width",
            "50",
            "--height",
            "30",
            "--tag",
            "box",
            env=env,
        )
        assert draw_result.returncode == 0

    result = run_cli(
        "edit",
        "rect",
        "--session",
        str(session_path),
        "--tag",
        "box",
        "--fill",
        "#00FF00",
        "--json",
        env=env,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert set(payload) == {"error"}
    assert payload["error"] == "tag is ambiguous: box"
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
        "--width",
        "80",
        "--height",
        "30",
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


def test_delete_by_tag_human_readable_output(tmp_path: Path) -> None:
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
        "--width",
        "80",
        "--height",
        "30",
        "--text",
        "hello",
        "--tag",
        "greeting",
        env=env,
    )
    assert draw_result.returncode == 0

    result = run_cli(
        "delete",
        "--session",
        str(session_path),
        "--tag",
        "greeting",
        env=env,
    )

    assert result.returncode == 0
    assert "Deleted object: obj_000001" in result.stdout
    assert read_scene(session_path)["objects"] == []


def test_delete_requires_id_or_tag_selector(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    result = run_cli(
        "delete",
        "--session",
        str(session_path),
        "--json",
        env=env,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert set(payload) == {"error"}
    assert payload["error"] == "id or tag must be provided for delete"
    assert result.stderr == ""


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
    assert set(empty_payload) == {"error"}
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


def test_undo_after_run_batch_removes_the_whole_batch(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)

    run_result = subprocess.run(
        [sys.executable, "-m", "linework", "run", "--session", str(session_path), "--json"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        input=(
            '{"op":"draw.rect","payload":{"x":10,"y":10,"width":50,"height":30}}\n'
            '{"op":"draw.text","payload":{"x":20,"y":60,"width":80,"height":30,"text":"hi","size":14}}\n'
        ),
    )
    assert run_result.returncode == 0

    undo_result = run_cli(
        "undo",
        "--session",
        str(session_path),
        "--json",
        env=env,
    )

    assert undo_result.returncode == 0
    undo_payload = json.loads(undo_result.stdout)
    assert undo_payload["scene_object_count"] == 0
    assert read_scene(session_path)["objects"] == []


def test_draw_image_imports_source_into_session_assets(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)
    source_path = tmp_path / "My Sample.PNG"
    Image.new("RGBA", (12, 8), (0, 0, 255, 255)).save(source_path, format="PNG")

    result = run_cli(
        "draw",
        "image",
        "--session",
        str(session_path),
        "--source",
        str(source_path),
        "--x",
        "30",
        "--y",
        "40",
        "--json",
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["results"] == [
        {"op_id": "op_000001", "op": "draw.image", "object_id": "obj_000001"}
    ]

    scene = read_scene(session_path)
    image_object = scene["objects"][0]
    assert image_object["type"] == "image"
    assert image_object["asset_path"] == "assets/my-sample.png"
    assert image_object["source_path"] == str(source_path.resolve())
    assert image_object["width"] == 12.0
    assert image_object["height"] == 8.0
    assert (session_path / image_object["asset_path"]).is_file()


def test_draw_image_width_only_preserves_aspect_ratio(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)
    source_path = tmp_path / "ratio.png"
    Image.new("RGBA", (20, 10), (0, 255, 0, 255)).save(source_path, format="PNG")

    result = run_cli(
        "draw",
        "image",
        "--session",
        str(session_path),
        "--source",
        str(source_path),
        "--x",
        "5",
        "--y",
        "6",
        "--width",
        "60",
        "--json",
        env=env,
    )

    assert result.returncode == 0
    image_object = read_scene(session_path)["objects"][0]
    assert image_object["width"] == 60.0
    assert image_object["height"] == 30.0


def test_edit_image_updates_geometry_without_replacing_source(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)
    source_path = tmp_path / "editable.png"
    Image.new("RGBA", (10, 6), (255, 0, 0, 255)).save(source_path, format="PNG")

    draw_result = run_cli(
        "draw",
        "image",
        "--session",
        str(session_path),
        "--source",
        str(source_path),
        "--x",
        "2",
        "--y",
        "3",
        env=env,
    )
    assert draw_result.returncode == 0

    result = run_cli(
        "edit",
        "image",
        "--session",
        str(session_path),
        "--id",
        "obj_000001",
        "--x",
        "25",
        "--height",
        "18",
        "--json",
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["results"] == [
        {"op_id": "op_000002", "op": "edit.image", "object_id": "obj_000001"}
    ]
    image_object = read_scene(session_path)["objects"][0]
    assert image_object["x"] == 25.0
    assert image_object["height"] == 18.0
    assert image_object["asset_path"] == "assets/editable.png"


def test_export_succeeds_after_original_image_source_is_removed(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)
    source_path = tmp_path / "portable.png"
    Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(source_path, format="PNG")

    draw_result = run_cli(
        "draw",
        "image",
        "--session",
        str(session_path),
        "--source",
        str(source_path),
        "--x",
        "4",
        "--y",
        "5",
        env=env,
    )
    assert draw_result.returncode == 0

    source_path.unlink()

    out_path = tmp_path / "portable-export.png"
    result = run_cli(
        "export",
        "--session",
        str(session_path),
        "--output",
        str(out_path),
        "--json",
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert Path(payload["exported_path"]).is_file()
    with Image.open(out_path) as exported:
        assert exported.getpixel((5, 6)) == (0, 0, 255, 255)


def test_export_fails_when_session_image_asset_is_missing(tmp_path: Path) -> None:
    session_path, env = create_cli_session(tmp_path)
    source_path = tmp_path / "missing.png"
    Image.new("RGBA", (6, 6), (255, 255, 0, 255)).save(source_path, format="PNG")

    draw_result = run_cli(
        "draw",
        "image",
        "--session",
        str(session_path),
        "--source",
        str(source_path),
        "--x",
        "0",
        "--y",
        "0",
        env=env,
    )
    assert draw_result.returncode == 0

    image_object = read_scene(session_path)["objects"][0]
    (session_path / image_object["asset_path"]).unlink()

    result = run_cli(
        "export",
        "--session",
        str(session_path),
        "--output",
        str(tmp_path / "broken-export.png"),
        "--json",
        env=env,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert set(payload) == {"error"}
    assert payload["error"] == "image asset missing: assets/missing.png"
    assert result.stderr == ""
