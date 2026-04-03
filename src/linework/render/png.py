"""PNG rendering helpers."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import cast

from PIL import Image, ImageColor, ImageDraw, ImageFont

from linework.core.objects import resolve_asset_path
from linework.storage.models import Canvas, SceneSnapshot

_DEFAULT_FONT_RESOURCE = resources.files("linework.assets").joinpath("NotoSans-Regular.ttf")


def render_blank_canvas(canvas: Canvas, output_path: Path) -> None:
    """Render a blank canvas PNG."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new(
        "RGBA",
        (canvas.width, canvas.height),
        ImageColor.getcolor(canvas.background, "RGBA"),
    )
    image.save(output_path, format="PNG")


def render_scene(scene: SceneSnapshot, output_path: Path, *, session_path: Path) -> None:
    """Render a complete scene PNG."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new(
        "RGBA",
        (scene.canvas.width, scene.canvas.height),
        ImageColor.getcolor(scene.canvas.background, "RGBA"),
    )
    draw = ImageDraw.Draw(image)

    for object_data in scene.objects:
        if not bool(object_data.get("visible", True)):
            continue
        render_object(draw=draw, image=image, object_data=object_data, session_path=session_path)

    image.save(output_path, format="PNG")


def render_object(
    *,
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    object_data: dict[str, object],
    session_path: Path,
) -> None:
    """Render one scene object."""
    object_type = str(object_data["type"])

    if object_type == "line":
        draw.line(
            [
                (number_value(object_data, "x1"), number_value(object_data, "y1")),
                (number_value(object_data, "x2"), number_value(object_data, "y2")),
            ],
            fill=get_color(object_data.get("stroke"), default="#000000"),
            width=int(round(number_or_default(object_data, "stroke_width", 2.0))),
        )
        return

    if object_type == "rect":
        draw.rectangle(
            bounds_tuple(object_data),
            outline=get_color(object_data.get("stroke"), default="#000000"),
            fill=get_optional_color(object_data.get("fill")),
            width=int(round(number_or_default(object_data, "stroke_width", 2.0))),
        )
        return

    if object_type == "ellipse":
        draw.ellipse(
            bounds_tuple(object_data),
            outline=get_color(object_data.get("stroke"), default="#000000"),
            fill=get_optional_color(object_data.get("fill")),
            width=int(round(number_or_default(object_data, "stroke_width", 2.0))),
        )
        return

    if object_type == "polyline":
        points = points_value(object_data)
        draw.line(
            points,
            fill=get_color(object_data.get("stroke"), default="#000000"),
            width=int(round(number_or_default(object_data, "stroke_width", 2.0))),
        )
        return

    if object_type == "text":
        font = load_default_text_font(number_or_default(object_data, "size", 16.0))
        draw.text(
            (number_value(object_data, "x"), number_value(object_data, "y")),
            string_value(object_data, "text"),
            font=font,
            fill=get_color(object_data.get("fill"), default="#000000"),
        )
        return

    if object_type == "image":
        asset_path = resolve_asset_path(
            session_path=session_path,
            asset_path=str(object_data["asset_path"]),
        )
        with Image.open(asset_path) as opened_image:
            pasted = opened_image.convert("RGBA")
            size = (
                int(round(number_value(object_data, "width"))),
                int(round(number_value(object_data, "height"))),
            )
            if pasted.size != size:
                pasted = pasted.resize(size)
            image.alpha_composite(
                pasted,
                (
                    int(round(number_value(object_data, "x"))),
                    int(round(number_value(object_data, "y"))),
                ),
            )
        return

    raise ValueError(f"unsupported object type: {object_type}")


def load_default_text_font(size: float) -> ImageFont.FreeTypeFont:
    """Load the package-bundled default text font."""
    normalized_size = max(1, int(round(size)))
    with resources.as_file(_DEFAULT_FONT_RESOURCE) as font_path:
        return ImageFont.truetype(str(font_path), size=normalized_size)


def bounds_tuple(object_data: dict[str, object]) -> tuple[float, float, float, float]:
    """Return a bounding box tuple for rectangle-like objects."""
    x = number_value(object_data, "x")
    y = number_value(object_data, "y")
    width = number_value(object_data, "width")
    height = number_value(object_data, "height")
    return (x, y, x + width, y + height)


def get_color(value: object, *, default: str) -> tuple[int, int, int, int]:
    """Resolve a required RGBA color."""
    if not isinstance(value, str):
        value = default
    rgba = ImageColor.getcolor(value, "RGBA")
    return cast(tuple[int, int, int, int], rgba)


def get_optional_color(value: object) -> tuple[int, int, int, int] | None:
    """Resolve an optional RGBA color."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    rgba = ImageColor.getcolor(value, "RGBA")
    return cast(tuple[int, int, int, int], rgba)


def number_value(object_data: dict[str, object], field: str) -> float:
    """Read a numeric object field."""
    value = object_data.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be numeric")
    return float(value)


def number_or_default(object_data: dict[str, object], field: str, default: float) -> float:
    """Read a numeric object field with a default."""
    value = object_data.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be numeric")
    return float(value)


def string_value(object_data: dict[str, object], field: str) -> str:
    """Read a string object field."""
    value = object_data.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def points_value(object_data: dict[str, object]) -> list[tuple[float, float]]:
    """Read a polyline points list."""
    raw_points = object_data.get("points")
    if not isinstance(raw_points, list):
        raise ValueError("points must be a list")

    points: list[tuple[float, float]] = []
    for index, point in enumerate(raw_points):
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError(f"points[{index}] must be a two-item list")
        x = point[0]
        y = point[1]
        if isinstance(x, bool) or not isinstance(x, int | float):
            raise ValueError(f"points[{index}][0] must be numeric")
        if isinstance(y, bool) or not isinstance(y, int | float):
            raise ValueError(f"points[{index}][1] must be numeric")
        points.append((float(x), float(y)))
    return points
