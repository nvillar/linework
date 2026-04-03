"""Object normalization and validation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from PIL import Image

from linework.constants import HEX_COLOR
from linework.core.errors import CommandValidationError

ObjectDict = dict[str, object]


def build_object(
    *,
    command: str,
    payload: Mapping[str, object],
    object_id: str,
    session_path: Path,
) -> ObjectDict:
    """Build a normalized scene object from a draw command payload."""
    if command == "draw.line":
        return _build_line(payload=payload, object_id=object_id)
    if command == "draw.rect":
        return _build_rect(payload=payload, object_id=object_id)
    if command == "draw.ellipse":
        return _build_ellipse(payload=payload, object_id=object_id)
    if command == "draw.polyline":
        return _build_polyline(payload=payload, object_id=object_id)
    if command == "draw.text":
        return _build_text(payload=payload, object_id=object_id)
    if command == "draw.image":
        return _build_image(payload=payload, object_id=object_id, session_path=session_path)

    raise CommandValidationError(f"unsupported draw command: {command}")


def apply_edit(
    *,
    existing: Mapping[str, object],
    payload: Mapping[str, object],
    session_path: Path,
) -> ObjectDict:
    """Apply an edit payload to an existing scene object."""
    object_type = require_string(existing.get("type"), field="type")
    current = dict(existing)

    if "label" in payload:
        current["label"] = require_optional_string(payload.get("label"), field="label")
    if "visible" in payload:
        current["visible"] = require_bool(payload.get("visible"), field="visible")

    if object_type in {"line", "rect", "ellipse", "polyline"}:
        if "stroke" in payload:
            current["stroke"] = normalize_color(payload.get("stroke"), field="stroke")
        if "stroke_width" in payload:
            current["stroke_width"] = require_positive_number(
                payload.get("stroke_width"),
                field="stroke_width",
            )

    if object_type in {"rect", "ellipse"} and "fill" in payload:
        current["fill"] = normalize_optional_color(payload.get("fill"), field="fill")

    if object_type == "text":
        if "fill" in payload:
            current["fill"] = normalize_optional_color(payload.get("fill"), field="fill")
        if "size" in payload:
            current["size"] = require_positive_number(payload.get("size"), field="size")
        if "text" in payload:
            current["text"] = require_string(payload.get("text"), field="text")
        if "x" in payload:
            current["x"] = require_number(payload.get("x"), field="x")
        if "y" in payload:
            current["y"] = require_number(payload.get("y"), field="y")

    if object_type == "line":
        for field in ("x1", "y1", "x2", "y2"):
            if field in payload:
                current[field] = require_number(payload.get(field), field=field)

    if object_type in {"rect", "ellipse", "image"}:
        for field in ("x", "y"):
            if field in payload:
                current[field] = require_number(payload.get(field), field=field)
        for field in ("width", "height"):
            if field in payload:
                current[field] = require_positive_number(payload.get(field), field=field)

    if object_type == "polyline" and "points" in payload:
        current["points"] = normalize_points(payload.get("points"))

    if object_type == "image":
        if "asset_path" in payload or "source_path" in payload:
            raise CommandValidationError("image source replacement is not supported")

    return validate_existing_object(current, session_path=session_path)


def validate_existing_object(
    existing: Mapping[str, object],
    *,
    session_path: Path,
) -> ObjectDict:
    """Validate and normalize a stored scene object."""
    object_id = require_string(existing.get("id"), field="id")
    object_type = require_string(existing.get("type"), field="type")

    draw_command = f"draw.{object_type}"
    payload = dict(existing)
    payload.pop("id", None)
    payload.pop("type", None)
    return build_object(
        command=draw_command,
        payload=payload,
        object_id=object_id,
        session_path=session_path,
    )


def require_number(value: object, *, field: str) -> float:
    """Normalize a numeric field to float."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CommandValidationError(f"{field} must be a number")
    return float(value)


def require_positive_number(value: object, *, field: str) -> float:
    """Normalize a strictly positive numeric field to float."""
    number = require_number(value, field=field)
    if number <= 0:
        raise CommandValidationError(f"{field} must be positive")
    return number


def require_string(value: object, *, field: str) -> str:
    """Normalize a required string field."""
    if not isinstance(value, str):
        raise CommandValidationError(f"{field} must be a string")
    return value


def require_optional_string(value: object, *, field: str) -> str | None:
    """Normalize an optional string field."""
    if value is None:
        return None
    return require_string(value, field=field)


def require_bool(value: object, *, field: str) -> bool:
    """Normalize a required boolean field."""
    if not isinstance(value, bool):
        raise CommandValidationError(f"{field} must be a boolean")
    return value


def normalize_color(value: object, *, field: str) -> str:
    """Normalize a required hex color."""
    text = require_string(value, field=field).upper()
    if not HEX_COLOR.fullmatch(text):
        raise CommandValidationError(f"{field} must be #RRGGBB or #RRGGBBAA")
    return text


def normalize_optional_color(value: object, *, field: str) -> str | None:
    """Normalize an optional hex color."""
    if value is None:
        return None
    return normalize_color(value, field=field)


def normalize_points(value: object) -> list[list[float]]:
    """Normalize a polyline points payload."""
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise CommandValidationError("points must be a sequence")

    normalized: list[list[float]] = []
    for index, point in enumerate(value):
        if not isinstance(point, Sequence) or isinstance(point, str | bytes) or len(point) != 2:
            raise CommandValidationError(f"points[{index}] must be a two-item sequence")
        x = require_number(point[0], field=f"points[{index}][0]")
        y = require_number(point[1], field=f"points[{index}][1]")
        normalized.append([x, y])

    if len(normalized) < 2:
        raise CommandValidationError("points must contain at least two points")

    return normalized


def normalize_common_fields(
    payload: Mapping[str, object],
    *,
    object_id: str,
    object_type: str,
) -> ObjectDict:
    """Normalize common object fields."""
    object_data: ObjectDict = {
        "id": object_id,
        "type": object_type,
        "visible": require_bool(payload.get("visible", True), field="visible"),
    }
    label = require_optional_string(payload.get("label"), field="label")
    if label is not None:
        object_data["label"] = label
    return object_data


def _build_line(*, payload: Mapping[str, object], object_id: str) -> ObjectDict:
    object_data = normalize_common_fields(payload, object_id=object_id, object_type="line")
    object_data.update(
        {
            "x1": require_number(payload.get("x1"), field="x1"),
            "y1": require_number(payload.get("y1"), field="y1"),
            "x2": require_number(payload.get("x2"), field="x2"),
            "y2": require_number(payload.get("y2"), field="y2"),
            "stroke": normalize_color(payload.get("stroke", "#000000"), field="stroke"),
            "stroke_width": require_positive_number(
                payload.get("stroke_width", 2.0),
                field="stroke_width",
            ),
        }
    )
    return object_data


def _build_rect(*, payload: Mapping[str, object], object_id: str) -> ObjectDict:
    object_data = normalize_common_fields(payload, object_id=object_id, object_type="rect")
    object_data.update(
        {
            "x": require_number(payload.get("x"), field="x"),
            "y": require_number(payload.get("y"), field="y"),
            "width": require_positive_number(payload.get("width"), field="width"),
            "height": require_positive_number(payload.get("height"), field="height"),
            "stroke": normalize_color(payload.get("stroke", "#000000"), field="stroke"),
            "stroke_width": require_positive_number(
                payload.get("stroke_width", 2.0),
                field="stroke_width",
            ),
        }
    )
    fill = normalize_optional_color(payload.get("fill"), field="fill")
    if fill is not None:
        object_data["fill"] = fill
    return object_data


def _build_ellipse(*, payload: Mapping[str, object], object_id: str) -> ObjectDict:
    object_data = normalize_common_fields(payload, object_id=object_id, object_type="ellipse")
    object_data.update(
        {
            "x": require_number(payload.get("x"), field="x"),
            "y": require_number(payload.get("y"), field="y"),
            "width": require_positive_number(payload.get("width"), field="width"),
            "height": require_positive_number(payload.get("height"), field="height"),
            "stroke": normalize_color(payload.get("stroke", "#000000"), field="stroke"),
            "stroke_width": require_positive_number(
                payload.get("stroke_width", 2.0),
                field="stroke_width",
            ),
        }
    )
    fill = normalize_optional_color(payload.get("fill"), field="fill")
    if fill is not None:
        object_data["fill"] = fill
    return object_data


def _build_polyline(*, payload: Mapping[str, object], object_id: str) -> ObjectDict:
    object_data = normalize_common_fields(payload, object_id=object_id, object_type="polyline")
    object_data.update(
        {
            "points": normalize_points(payload.get("points")),
            "stroke": normalize_color(payload.get("stroke", "#000000"), field="stroke"),
            "stroke_width": require_positive_number(
                payload.get("stroke_width", 2.0),
                field="stroke_width",
            ),
        }
    )
    return object_data


def _build_text(*, payload: Mapping[str, object], object_id: str) -> ObjectDict:
    object_data = normalize_common_fields(payload, object_id=object_id, object_type="text")
    object_data.update(
        {
            "x": require_number(payload.get("x"), field="x"),
            "y": require_number(payload.get("y"), field="y"),
            "text": require_string(payload.get("text"), field="text"),
            "size": require_positive_number(payload.get("size", 16.0), field="size"),
        }
    )
    fill = normalize_optional_color(payload.get("fill"), field="fill")
    if fill is not None:
        object_data["fill"] = fill
    return object_data


def _build_image(
    *,
    payload: Mapping[str, object],
    object_id: str,
    session_path: Path,
) -> ObjectDict:
    object_data = normalize_common_fields(payload, object_id=object_id, object_type="image")
    asset_path = require_string(payload.get("asset_path"), field="asset_path")
    normalized_asset_path = normalize_asset_path(session_path=session_path, asset_path=asset_path)
    asset_full_path = session_path.resolve() / Path(normalized_asset_path)
    if not asset_full_path.is_file():
        raise CommandValidationError(f"image asset does not exist: {normalized_asset_path}")

    x = require_number(payload.get("x"), field="x")
    y = require_number(payload.get("y"), field="y")
    width = payload.get("width")
    height = payload.get("height")

    with Image.open(asset_full_path) as image:
        natural_width, natural_height = image.size

    if natural_width <= 0 or natural_height <= 0:
        raise CommandValidationError(
            f"image has invalid dimensions: {natural_width}x{natural_height}"
        )

    normalized_width: float
    normalized_height: float

    if width is None and height is None:
        normalized_width = float(natural_width)
        normalized_height = float(natural_height)
    elif width is not None and height is None:
        normalized_width = require_positive_number(width, field="width")
        normalized_height = normalized_width * natural_height / natural_width
    elif width is None and height is not None:
        normalized_height = require_positive_number(height, field="height")
        normalized_width = normalized_height * natural_width / natural_height
    else:
        normalized_width = require_positive_number(width, field="width")
        normalized_height = require_positive_number(height, field="height")

    object_data.update(
        {
            "x": x,
            "y": y,
            "width": normalized_width,
            "height": normalized_height,
            "asset_path": normalized_asset_path,
        }
    )
    source_path = require_optional_string(payload.get("source_path"), field="source_path")
    if source_path is not None:
        object_data["source_path"] = source_path
    return object_data


def normalize_asset_path(*, session_path: Path, asset_path: str) -> str:
    """Normalize a session-local asset path to a canonical relative POSIX string."""
    candidate = Path(asset_path)
    if candidate.is_absolute():
        raise CommandValidationError(
            f"asset_path must be relative, got absolute path: {asset_path}"
        )

    session_resolved = session_path.resolve()
    resolved = (session_path / candidate).resolve()
    try:
        relative = resolved.relative_to(session_resolved)
    except ValueError:
        raise CommandValidationError(
            f"asset_path must resolve inside the session directory: {asset_path}"
        )
    return relative.as_posix()


def resolve_asset_path(*, session_path: Path, asset_path: str) -> Path:
    """Resolve a session-local image asset path.

    Only relative paths that resolve inside the session directory are accepted.
    """
    normalized_asset_path = normalize_asset_path(session_path=session_path, asset_path=asset_path)
    return session_path.resolve() / Path(normalized_asset_path)
