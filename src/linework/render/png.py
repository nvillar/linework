"""PNG rendering helpers."""

from __future__ import annotations

import math
from importlib import resources
from pathlib import Path
from typing import cast

from PIL import Image, ImageColor, ImageDraw, ImageFont

from linework.constants import (
    DEFAULT_ARROWHEAD,
    DEFAULT_TEXT_ALIGN,
    DEFAULT_TEXT_PADDING,
    DEFAULT_TEXT_VALIGN,
)
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
    for object_data in scene.objects:
        if not bool(object_data.get("visible", True)):
            continue
        render_object(image=image, object_data=object_data, session_path=session_path)

    image.save(output_path, format="PNG")


def render_object(
    *,
    image: Image.Image,
    object_data: dict[str, object],
    session_path: Path,
) -> None:
    """Render one scene object."""
    object_type = str(object_data["type"])

    if object_type == "image":
        render_image_object(image=image, object_data=object_data, session_path=session_path)
        return

    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    render_drawn_object(draw=draw, object_data=object_data)
    image.alpha_composite(layer)


def render_drawn_object(*, draw: ImageDraw.ImageDraw, object_data: dict[str, object]) -> None:
    """Render one non-image object to a transparent layer."""
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

    if object_type == "arrow":
        render_arrow(draw=draw, object_data=object_data)
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

    if object_type == "polygon":
        points = points_value(object_data)
        draw.polygon(
            points,
            outline=get_color(object_data.get("stroke"), default="#000000"),
            fill=get_optional_color(object_data.get("fill")),
            width=int(round(number_or_default(object_data, "stroke_width", 2.0))),
        )
        return

    if object_type == "text":
        render_text_object(draw=draw, object_data=object_data)
        return

    raise ValueError(f"unsupported non-image object type: {object_type}")


def render_image_object(
    *,
    image: Image.Image,
    object_data: dict[str, object],
    session_path: Path,
) -> None:
    """Render one image object onto the scene."""
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


def load_default_text_font(size: float) -> ImageFont.FreeTypeFont:
    """Load the package-bundled default text font."""
    normalized_size = max(1, int(round(size)))
    with resources.as_file(_DEFAULT_FONT_RESOURCE) as font_path:
        return ImageFont.truetype(str(font_path), size=normalized_size)


def render_arrow(*, draw: ImageDraw.ImageDraw, object_data: dict[str, object]) -> None:
    """Render an arrow with optional start/end arrowheads."""
    start = (number_value(object_data, "x1"), number_value(object_data, "y1"))
    end = (number_value(object_data, "x2"), number_value(object_data, "y2"))
    stroke = get_color(object_data.get("stroke"), default="#000000")
    stroke_width = max(1, int(round(number_or_default(object_data, "stroke_width", 2.0))))
    arrowhead = string_or_default(object_data, "arrowhead", DEFAULT_ARROWHEAD)
    arrow_size = number_or_none(object_data, "arrow_size")

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    line_length = math.hypot(dx, dy)
    if line_length == 0:
        radius = max(1.0, stroke_width / 2.0)
        draw.ellipse(
            (
                start[0] - radius,
                start[1] - radius,
                start[0] + radius,
                start[1] + radius,
            ),
            fill=stroke,
        )
        return

    unit_x = dx / line_length
    unit_y = dy / line_length
    head_length = resolve_arrow_head_length(
        arrow_size=arrow_size,
        stroke_width=stroke_width,
        line_length=line_length,
        arrowhead=arrowhead,
    )
    half_width = max(stroke_width * 0.75, head_length * 0.45)

    line_start = start
    line_end = end
    if arrowhead in {"start", "both"}:
        line_start = (start[0] + unit_x * head_length, start[1] + unit_y * head_length)
    if arrowhead in {"end", "both"}:
        line_end = (end[0] - unit_x * head_length, end[1] - unit_y * head_length)

    draw.line([line_start, line_end], fill=stroke, width=stroke_width)

    if arrowhead in {"start", "both"}:
        draw.polygon(
            arrowhead_polygon(
                tip=start,
                interior_direction=(unit_x, unit_y),
                head_length=head_length,
                half_width=half_width,
            ),
            fill=stroke,
        )
    if arrowhead in {"end", "both"}:
        draw.polygon(
            arrowhead_polygon(
                tip=end,
                interior_direction=(-unit_x, -unit_y),
                head_length=head_length,
                half_width=half_width,
            ),
            fill=stroke,
        )


def resolve_arrow_head_length(
    *,
    arrow_size: float | None,
    stroke_width: int,
    line_length: float,
    arrowhead: str,
) -> float:
    """Resolve an arrowhead size in pixels with overlap-safe clamping."""
    requested = arrow_size if arrow_size is not None else stroke_width * 4.0
    max_fraction = 0.3 if arrowhead == "both" else 0.45
    return max(1.0, min(requested, line_length * max_fraction))


def arrowhead_polygon(
    *,
    tip: tuple[float, float],
    interior_direction: tuple[float, float],
    head_length: float,
    half_width: float,
) -> list[tuple[float, float]]:
    """Build a filled triangle for an arrowhead."""
    base_center = (
        tip[0] + interior_direction[0] * head_length,
        tip[1] + interior_direction[1] * head_length,
    )
    perpendicular = (-interior_direction[1], interior_direction[0])
    return [
        tip,
        (
            base_center[0] + perpendicular[0] * half_width,
            base_center[1] + perpendicular[1] * half_width,
        ),
        (
            base_center[0] - perpendicular[0] * half_width,
            base_center[1] - perpendicular[1] * half_width,
        ),
    ]


def render_text_object(*, draw: ImageDraw.ImageDraw, object_data: dict[str, object]) -> None:
    """Render a text object inside its layout box."""
    font = load_default_text_font(number_or_default(object_data, "size", 16.0))
    spacing = default_line_spacing(font)
    align = string_or_default(object_data, "align", DEFAULT_TEXT_ALIGN)
    valign = string_or_default(object_data, "valign", DEFAULT_TEXT_VALIGN)
    padding = number_or_default(object_data, "padding", DEFAULT_TEXT_PADDING)
    text = string_value(object_data, "text")
    inner_box = text_inner_box(object_data, padding=padding)
    rendered_text = wrap_text_to_width(text, font=font, max_width=inner_box[2])
    text_bbox = measure_text_block_bbox(
        draw=draw,
        text=rendered_text,
        font=font,
        align=align,
        spacing=spacing,
    )
    position = text_box_origin(
        text_bbox=text_bbox,
        inner_box=inner_box,
        align=align,
        valign=valign,
    )
    fill = get_color(object_data.get("fill"), default="#000000")
    draw.multiline_text(
        position,
        rendered_text,
        font=font,
        fill=fill,
        align=align,
        spacing=spacing,
    )


def default_line_spacing(font: ImageFont.FreeTypeFont) -> int:
    """Return a modest default spacing for wrapped text lines."""
    return max(4, int(round(font.size * 0.2)))


def wrap_text_to_width(
    text: str,
    *,
    font: ImageFont.FreeTypeFont,
    max_width: float | None,
) -> str:
    """Wrap text to a maximum rendered width using font metrics."""
    if max_width is None:
        return text

    wrapped_lines: list[str] = []
    for paragraph in text.splitlines():
        if paragraph.strip() == "":
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(wrap_paragraph(paragraph, font=font, max_width=max_width))
    return "\n".join(wrapped_lines)


def wrap_paragraph(
    paragraph: str,
    *,
    font: ImageFont.FreeTypeFont,
    max_width: float,
) -> list[str]:
    """Wrap one paragraph to a maximum width."""
    words = paragraph.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if text_length(candidate, font=font) <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)
            current = ""

        if text_length(word, font=font) <= max_width:
            current = word
            continue

        chunks = split_long_word(word, font=font, max_width=max_width)
        lines.extend(chunks[:-1])
        current = chunks[-1]

    if current:
        lines.append(current)
    return lines


def split_long_word(word: str, *, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    """Split one oversized token into smaller rendered-width-safe chunks."""
    chunks: list[str] = []
    current = ""
    for character in word:
        candidate = f"{current}{character}"
        if current and text_length(candidate, font=font) > max_width:
            chunks.append(current)
            current = character
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def text_inner_box(
    object_data: dict[str, object],
    *,
    padding: float,
) -> tuple[float, float, float, float]:
    """Return the padded text box as left, top, width, height."""
    x = number_value(object_data, "x") + padding
    y = number_value(object_data, "y") + padding
    width = max(1.0, number_value(object_data, "width") - padding * 2.0)
    height = max(1.0, number_value(object_data, "height") - padding * 2.0)
    return (x, y, width, height)


def measure_text_block_bbox(
    *,
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    align: str,
    spacing: int,
) -> tuple[float, float, float, float]:
    """Measure the rendered text block."""
    return draw.multiline_textbbox((0, 0), text, font=font, align=align, spacing=spacing)


def text_box_origin(
    *,
    text_bbox: tuple[float, float, float, float],
    inner_box: tuple[float, float, float, float],
    align: str,
    valign: str,
) -> tuple[float, float]:
    """Place a measured text block inside the padded layout box.

    If the rendered text block is larger than the padded box, preserve the
    requested alignment and allow visible overflow rather than clamping.
    """
    inner_x, inner_y, inner_width, inner_height = inner_box
    block_width = text_bbox[2] - text_bbox[0]
    block_height = text_bbox[3] - text_bbox[1]

    if align == "left":
        block_x = inner_x
    elif align == "right":
        block_x = inner_x + inner_width - block_width
    else:
        block_x = inner_x + (inner_width - block_width) / 2.0

    if valign == "top":
        block_y = inner_y
    elif valign == "bottom":
        block_y = inner_y + inner_height - block_height
    else:
        block_y = inner_y + (inner_height - block_height) / 2.0

    return (block_x - text_bbox[0], block_y - text_bbox[1])


def text_length(text: str, *, font: ImageFont.FreeTypeFont) -> float:
    """Measure the rendered width of one line of text."""
    return float(font.getlength(text))


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


def number_or_none(object_data: dict[str, object], field: str) -> float | None:
    """Read an optional numeric object field."""
    value = object_data.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be numeric")
    return float(value)


def string_value(object_data: dict[str, object], field: str) -> str:
    """Read a string object field."""
    value = object_data.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def string_or_default(object_data: dict[str, object], field: str, default: str) -> str:
    """Read a string object field with a default."""
    value = object_data.get(field, default)
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
