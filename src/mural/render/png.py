"""PNG rendering helpers."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageColor

from mural.storage.models import Canvas


def render_blank_canvas(canvas: Canvas, output_path: Path) -> None:
    """Render a blank canvas PNG."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new(
        "RGBA",
        (canvas.width, canvas.height),
        ImageColor.getcolor(canvas.background, "RGBA"),
    )
    image.save(output_path, format="PNG")
