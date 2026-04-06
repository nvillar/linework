"""Scene engine and renderer tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw

from linework.render.png import render_text_object
from linework.storage.session import (
    apply_batch,
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


def nonwhite_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    """Return the bounding box of non-white pixels."""
    blank = Image.new("RGB", image.size, (255, 255, 255))
    return ImageChops.difference(image.convert("RGB"), blank).getbbox()


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
        payload={"x": 20, "y": 70, "width": 80, "height": 40, "text": "hello", "size": 24},
    )

    with Image.open(session_path / "render" / "latest.png") as rendered:
        blank = Image.new("RGBA", rendered.size, (255, 255, 255, 255))
        difference = ImageChops.difference(rendered.convert("RGB"), blank.convert("RGB"))
        assert difference.getbbox() is not None


def test_draw_polygon_renders_filled_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    apply_mutation(
        session_path,
        op="draw.polygon",
        payload={
            "points": [[20, 80], [100, 20], [160, 100]],
            "fill": "#FF66CC",
            "stroke": "#AA2277",
        },
    )

    scene = read_scene_snapshot(session_path)
    assert scene.objects[0]["type"] == "polygon"
    assert scene.objects[0]["fill"] == "#FF66CC"

    with Image.open(session_path / "render" / "latest.png") as rendered:
        assert rendered.getpixel((95, 60)) == (255, 102, 204, 255)


def test_draw_circle_stores_ellipse_geometry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    result = apply_mutation(
        session_path,
        op="draw.circle",
        payload={"x": 40, "y": 30, "radius": 20, "fill": "#FF0000"},
    )

    assert result.op == "draw.circle"
    scene = read_scene_snapshot(session_path)
    assert scene.objects[0]["type"] == "ellipse"
    assert scene.objects[0]["x"] == 40.0
    assert scene.objects[0]["width"] == 40.0
    assert scene.objects[0]["height"] == 40.0

    with Image.open(session_path / "render" / "latest.png") as rendered:
        assert rendered.getpixel((60, 50)) == (255, 0, 0, 255)


def test_translucent_rectangles_are_composited_in_stacking_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    apply_batch(
        session_path,
        operations=[
            {
                "op": "draw.rect",
                "payload": {
                    "x": 10,
                    "y": 10,
                    "width": 80,
                    "height": 60,
                    "fill": "#FF000080",
                    "stroke": "#00000000",
                },
            },
            {
                "op": "draw.rect",
                "payload": {
                    "x": 40,
                    "y": 30,
                    "width": 80,
                    "height": 60,
                    "fill": "#0000FF80",
                    "stroke": "#00000000",
                },
            },
        ],
    )

    with Image.open(session_path / "render" / "latest.png") as rendered:
        assert rendered.getpixel((20, 20)) == (255, 127, 127, 255)
        assert rendered.getpixel((100, 80)) == (127, 127, 255, 255)
        assert rendered.getpixel((60, 50)) == (127, 63, 191, 255)


def test_translucent_text_is_composited_over_existing_scene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    apply_batch(
        session_path,
        operations=[
            {
                "op": "draw.rect",
                "payload": {
                    "x": 0,
                    "y": 0,
                    "width": 200,
                    "height": 160,
                    "fill": "#FF000080",
                    "stroke": "#00000000",
                },
            },
            {
                "op": "draw.text",
                "payload": {
                    "x": 20,
                    "y": 20,
                    "width": 80,
                    "height": 40,
                    "text": "Hi",
                    "size": 24,
                    "fill": "#00000080",
                },
            },
        ],
    )

    text_layer = Image.new("RGBA", (200, 160), (0, 0, 0, 0))
    render_text_object(
        draw=ImageDraw.Draw(text_layer),
        object_data={
            "x": 20,
            "y": 20,
            "width": 80,
            "height": 40,
            "text": "Hi",
            "size": 24,
            "fill": "#00000080",
        },
    )
    sample = next(
        (
            (x, y)
            for y in range(text_layer.height)
            for x in range(text_layer.width)
            if text_layer.getpixel((x, y))[3] > 0
        ),
        None,
    )
    assert sample is not None

    expected = Image.new("RGBA", (200, 160), (255, 255, 255, 255))
    rect_layer = Image.new("RGBA", (200, 160), (0, 0, 0, 0))
    ImageDraw.Draw(rect_layer).rectangle(
        (0, 0, 200, 160),
        fill=(255, 0, 0, 128),
        outline=(0, 0, 0, 0),
        width=2,
    )
    expected.alpha_composite(rect_layer)
    expected.alpha_composite(text_layer)
    rect_only = Image.new("RGBA", (200, 160), (255, 255, 255, 255))
    rect_only.alpha_composite(rect_layer)

    with Image.open(session_path / "render" / "latest.png") as rendered:
        assert rendered.getpixel(sample) == expected.getpixel(sample)
        assert rendered.getpixel(sample) != rect_only.getpixel(sample)
        assert rendered.getpixel(sample)[3] == 255


def test_draw_arrow_renders_with_requested_head_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    apply_mutation(
        session_path,
        op="draw.arrow",
        payload={
            "x1": 20,
            "y1": 80,
            "x2": 160,
            "y2": 80,
            "stroke": "#0000FF",
            "stroke_width": 4,
            "arrowhead": "both",
            "arrow_size": 18,
        },
    )

    scene = read_scene_snapshot(session_path)
    assert scene.objects[0]["type"] == "arrow"
    assert scene.objects[0]["arrow_size"] == 18.0

    with Image.open(session_path / "render" / "latest.png") as rendered:
        assert rendered.getpixel((90, 80)) == (0, 0, 255, 255)
        assert rendered.getpixel((20, 80)) == (0, 0, 255, 255)
        assert rendered.getpixel((160, 80)) == (0, 0, 255, 255)
        assert rendered.getpixel((148, 84)) == (0, 0, 255, 255)


def test_edit_and_delete_support_unique_label_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    apply_mutation(
        session_path,
        op="draw.rect",
        payload={"x": 10, "y": 10, "width": 50, "height": 40, "label": "box"},
    )
    apply_mutation(
        session_path,
        op="edit.rect",
        payload={"label": "box", "fill": "#00FF00"},
    )

    scene = read_scene_snapshot(session_path)
    assert scene.objects[0]["fill"] == "#00FF00"

    apply_mutation(session_path, op="delete", payload={"label": "box"})
    assert read_scene_snapshot(session_path).objects == []


def test_label_selection_rejects_ambiguous_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config
    from linework.core.errors import CommandValidationError

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    apply_mutation(
        session_path,
        op="draw.rect",
        payload={"x": 10, "y": 10, "width": 50, "height": 40, "label": "box"},
    )
    apply_mutation(
        session_path,
        op="draw.rect",
        payload={"x": 70, "y": 10, "width": 50, "height": 40, "label": "box"},
    )

    with pytest.raises(CommandValidationError, match="label is ambiguous: box"):
        apply_mutation(session_path, op="delete", payload={"label": "box"})


def test_undo_after_batch_removes_the_whole_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    apply_batch(
        session_path,
        operations=[
            {
                "op": "draw.rect",
                "payload": {"x": 10, "y": 10, "width": 50, "height": 40},
            },
            {
                "op": "draw.text",
                "payload": {
                    "x": 20,
                    "y": 60,
                    "width": 80,
                    "height": 30,
                    "text": "hello",
                    "size": 16,
                },
            },
        ],
    )
    apply_mutation(session_path, op="undo")

    assert read_scene_snapshot(session_path).objects == []


def test_undo_inside_batch_only_removes_the_last_batch_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    apply_batch(
        session_path,
        operations=[
            {
                "op": "draw.rect",
                "payload": {"x": 10, "y": 10, "width": 50, "height": 40},
            },
            {
                "op": "draw.text",
                "payload": {
                    "x": 20,
                    "y": 60,
                    "width": 80,
                    "height": 30,
                    "text": "hello",
                    "size": 16,
                },
            },
            {"op": "undo", "payload": {}},
        ],
    )

    scene = read_scene_snapshot(session_path)
    assert len(scene.objects) == 1
    assert scene.objects[0]["type"] == "rect"


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


def test_text_box_defaults_center_text_in_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    apply_mutation(
        session_path,
        op="draw.text",
        payload={"x": 40, "y": 20, "width": 120, "height": 60, "text": "Center", "size": 24},
    )

    scene = read_scene_snapshot(session_path)
    assert scene.objects[0]["align"] == "center"
    assert scene.objects[0]["valign"] == "middle"

    with Image.open(session_path / "render" / "latest.png") as rendered:
        bbox = nonwhite_bbox(rendered)
        assert bbox is not None
        center_x = (bbox[0] + bbox[2]) / 2.0
        center_y = (bbox[1] + bbox[3]) / 2.0
        assert abs(center_x - 100.0) <= 4.0
        assert abs(center_y - 50.0) <= 4.0


def test_text_box_wraps_and_preserves_center_alignment_when_overflowing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linework import config

    monkeypatch.setattr(config, "linework_home", lambda: tmp_path / "linework-home")
    session_path = create_test_session(tmp_path)

    apply_mutation(
        session_path,
        op="draw.text",
        payload={
            "x": 20,
            "y": 50,
            "width": 80,
            "height": 50,
            "text": "wrap this text into multiple rendered lines",
            "size": 20,
            "padding": 5,
        },
    )

    scene = read_scene_snapshot(session_path)
    assert scene.objects[0]["width"] == 80.0
    assert scene.objects[0]["height"] == 50.0
    assert scene.objects[0]["padding"] == 5.0

    with Image.open(session_path / "render" / "latest.png") as rendered:
        bbox = nonwhite_bbox(rendered)
        assert bbox is not None
        assert bbox[2] - bbox[0] <= 90
        assert bbox[3] - bbox[1] > 40
        center_x = (bbox[0] + bbox[2]) / 2.0
        center_y = (bbox[1] + bbox[3]) / 2.0
        assert abs(center_x - 60.0) <= 4.0
        assert abs(center_y - 75.0) <= 4.0


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
