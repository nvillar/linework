"""Scene engine and renderer tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from linework.storage.session import (
    apply_mutation,
    create_session,
    read_commands,
    read_scene_snapshot,
    read_session_metadata,
)


def create_test_session(tmp_path: Path) -> Path:
    """Create a session for scene-engine tests."""
    session_path = tmp_path / "scene-session"
    create_session(
        session=str(session_path),
        name=None,
        width=200,
        height=160,
        background="#FFFFFF",
    )
    return session_path


def test_draw_rect_updates_scene_commands_and_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    result = apply_mutation(
        session_path,
        op="draw.rect",
        payload={
            "x": 20,
            "y": 30,
            "width": 80,
            "height": 40,
            "fill": "#FF0000",
        },
    )

    assert result.op == "draw.rect"
    assert result.op_id == "op_000001"
    assert result.object_id == "obj_000001"
    assert result.scene_object_count == 1

    commands = read_commands(session_path)
    assert len(commands) == 1
    assert commands[0].payload["id"] == "obj_000001"

    scene = read_scene_snapshot(session_path)
    assert len(scene.objects) == 1
    assert scene.objects[0]["type"] == "rect"
    assert scene.objects[0]["fill"] == "#FF0000"

    metadata = read_session_metadata(session_path)
    assert metadata.updated_at == commands[0].timestamp

    with Image.open(session_path / "render" / "latest.png") as image:
        assert image.getpixel((40, 50)) == (255, 0, 0, 255)


def test_edit_delete_undo_preserve_append_only_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    apply_mutation(
        session_path,
        op="draw.rect",
        payload={"x": 10, "y": 10, "width": 50, "height": 40, "fill": "#00FF00"},
    )
    apply_mutation(
        session_path,
        op="edit.rect",
        payload={"id": "obj_000001", "x": 30, "fill": "#0000FF"},
    )
    apply_mutation(session_path, op="delete", payload={"id": "obj_000001"})
    apply_mutation(session_path, op="undo")

    commands = read_commands(session_path)
    assert [command.op for command in commands] == [
        "draw.rect",
        "edit.rect",
        "delete",
        "undo",
    ]

    scene = read_scene_snapshot(session_path)
    assert len(scene.objects) == 1
    assert scene.objects[0]["id"] == "obj_000001"
    assert scene.objects[0]["x"] == 30.0
    assert scene.objects[0]["fill"] == "#0000FF"


def test_undo_without_history_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    from linework.core.errors import CommandValidationError

    try:
        apply_mutation(session_path, op="undo")
    except CommandValidationError as error:
        assert "nothing to undo" in str(error)
    else:
        raise AssertionError("undo without history should fail")


def test_object_ids_are_not_reused_after_undo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    apply_mutation(
        session_path,
        op="draw.rect",
        payload={"x": 10, "y": 10, "width": 50, "height": 40},
    )
    apply_mutation(session_path, op="undo")
    result = apply_mutation(
        session_path,
        op="draw.line",
        payload={"x1": 0, "y1": 0, "x2": 50, "y2": 50},
    )

    assert result.object_id == "obj_000002"


def test_renderer_supports_multiple_primitives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    apply_mutation(
        session_path,
        op="draw.line",
        payload={"x1": 0, "y1": 0, "x2": 120, "y2": 80},
    )
    apply_mutation(
        session_path,
        op="draw.ellipse",
        payload={"x": 60, "y": 20, "width": 70, "height": 50, "fill": "#00FF00"},
    )
    apply_mutation(
        session_path,
        op="draw.polyline",
        payload={"points": [[10, 120], [40, 100], [80, 130], [120, 90]]},
    )
    apply_mutation(
        session_path,
        op="draw.text",
        payload={"x": 20, "y": 70, "text": "hello", "size": 24},
    )

    with Image.open(session_path / "render" / "latest.png") as rendered:
        blank = Image.new("RGBA", rendered.size, (255, 255, 255, 255))
        difference = ImageChops.difference(rendered.convert("RGB"), blank.convert("RGB"))
        assert difference.getbbox() is not None


def test_draw_image_uses_session_local_asset_and_natural_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)
    asset_path = session_path / "assets" / "sample.png"

    image = Image.new("RGBA", (12, 8), (0, 0, 255, 255))
    image.save(asset_path, format="PNG")

    apply_mutation(
        session_path,
        op="draw.image",
        payload={"x": 30, "y": 40, "asset_path": "assets/sample.png"},
    )

    scene = read_scene_snapshot(session_path)
    image_object = scene.objects[0]
    assert image_object["width"] == 12.0
    assert image_object["height"] == 8.0

    with Image.open(session_path / "render" / "latest.png") as rendered:
        assert rendered.getpixel((32, 42)) == (0, 0, 255, 255)


def test_draw_image_normalizes_stored_asset_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)
    asset_path = session_path / "assets" / "sample.png"

    image = Image.new("RGBA", (4, 4), (255, 0, 255, 255))
    image.save(asset_path, format="PNG")

    apply_mutation(
        session_path,
        op="draw.image",
        payload={"x": 10, "y": 12, "asset_path": "./assets/../assets/sample.png"},
    )

    scene = read_scene_snapshot(session_path)
    assert scene.objects[0]["asset_path"] == "assets/sample.png"


def test_commands_jsonl_is_valid_jsonl_after_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    apply_mutation(
        session_path,
        op="draw.rect",
        payload={"x": 1, "y": 2, "width": 3, "height": 4},
    )
    apply_mutation(
        session_path,
        op="edit.rect",
        payload={"id": "obj_000001", "x": 8},
    )

    lines = (session_path / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    payloads = [json.loads(line) for line in lines]
    assert [payload["op"] for payload in payloads] == ["draw.rect", "edit.rect"]
