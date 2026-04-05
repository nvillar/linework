"""Supported-operation metadata and schema manifest helpers."""

from __future__ import annotations

import difflib
from copy import deepcopy

from linework.constants import (
    ARROWHEAD_MODES,
    DEFAULT_ARROWHEAD,
    DEFAULT_CANVAS_BACKGROUND,
    DEFAULT_CANVAS_HEIGHT,
    DEFAULT_CANVAS_WIDTH,
    DEFAULT_TEXT_ANCHOR,
    TEXT_ANCHORS,
)

_MISSING = object()


def _field(
    field_type: str,
    *,
    default: object = _MISSING,
    enum: tuple[str, ...] | None = None,
    description: str | None = None,
) -> dict[str, object]:
    field: dict[str, object] = {"type": field_type}
    if default is not _MISSING:
        field["default"] = default
    if enum is not None:
        field["enum"] = list(enum)
    if description is not None:
        field["description"] = description
    return field


def _example(op: str, payload: dict[str, object]) -> dict[str, object]:
    return {"op": op, "payload": payload}


def _selector_spec(*, allow_label_only_note: str) -> dict[str, object]:
    return {
        "one_of": ["id", "label"],
        "fields": {
            "id": _field("string"),
            "label": _field("string", description=allow_label_only_note),
        },
    }


_LABEL_FIELD = _field("string|null")
_VISIBLE_FIELD = _field("boolean", default=True)
_COLOR_DESCRIPTION = "#RRGGBB or #RRGGBBAA; alpha-composited in stacking order"
_STROKE_FIELD = _field("color", default="#000000", description=_COLOR_DESCRIPTION)
_FILL_FIELD = _field("color|null", description=_COLOR_DESCRIPTION)
_STROKE_WIDTH_FIELD = _field("positive-number", default=2.0)
_TEXT_SIZE_FIELD = _field("positive-number", default=16.0)
_TEXT_ANCHOR_FIELD = _field(
    "string",
    default=DEFAULT_TEXT_ANCHOR,
    enum=TEXT_ANCHORS,
)
_TEXT_MAX_WIDTH_FIELD = _field("positive-number|null")
_ARROWHEAD_FIELD = _field(
    "string",
    default=DEFAULT_ARROWHEAD,
    enum=ARROWHEAD_MODES,
)
_ARROW_SIZE_FIELD = _field(
    "positive-number|null",
    description="Arrowhead size in pixels. When omitted, defaults to 4× stroke_width.",
)
_POINTS_FIELD = _field("points")

_DRAW_SELECTOR_NOTE = "Use inspect to discover stable IDs before editing."
_EDIT_SELECTOR_NOTE = "Must be a unique live label when id is omitted."
_DELETE_SELECTOR_NOTE = "Must be a unique live label when id is omitted."

_OPERATION_SCHEMAS: dict[str, dict[str, object]] = {
    "draw.line": {
        "category": "draw",
        "stored_object_type": "line",
        "description": "Create a line.",
        "required": {
            "x1": _field("number"),
            "y1": _field("number"),
            "x2": _field("number"),
            "y2": _field("number"),
        },
        "optional": {
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "stroke": _STROKE_FIELD,
            "stroke_width": _STROKE_WIDTH_FIELD,
        },
        "example": _example(
            "draw.line",
            {"x1": 0, "y1": 0, "x2": 120, "y2": 80, "stroke": "#1F2937"},
        ),
    },
    "draw.arrow": {
        "category": "draw",
        "stored_object_type": "arrow",
        "description": "Create an arrow.",
        "required": {
            "x1": _field("number"),
            "y1": _field("number"),
            "x2": _field("number"),
            "y2": _field("number"),
        },
        "optional": {
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "stroke": _STROKE_FIELD,
            "stroke_width": _STROKE_WIDTH_FIELD,
            "arrowhead": _ARROWHEAD_FIELD,
            "arrow_size": _ARROW_SIZE_FIELD,
        },
        "example": _example(
            "draw.arrow",
            {
                "x1": 20,
                "y1": 40,
                "x2": 160,
                "y2": 40,
                "arrowhead": "end",
                "arrow_size": 18,
            },
        ),
    },
    "draw.rect": {
        "category": "draw",
        "stored_object_type": "rect",
        "description": "Create a rectangle.",
        "required": {
            "x": _field("number"),
            "y": _field("number"),
            "width": _field("positive-number"),
            "height": _field("positive-number"),
        },
        "optional": {
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "stroke": _STROKE_FIELD,
            "fill": _FILL_FIELD,
            "stroke_width": _STROKE_WIDTH_FIELD,
        },
        "example": _example(
            "draw.rect",
            {"x": 40, "y": 40, "width": 140, "height": 80, "fill": "#FDE68A"},
        ),
    },
    "draw.ellipse": {
        "category": "draw",
        "stored_object_type": "ellipse",
        "description": "Create an ellipse.",
        "required": {
            "x": _field("number"),
            "y": _field("number"),
            "width": _field("positive-number"),
            "height": _field("positive-number"),
        },
        "optional": {
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "stroke": _STROKE_FIELD,
            "fill": _FILL_FIELD,
            "stroke_width": _STROKE_WIDTH_FIELD,
        },
        "example": _example(
            "draw.ellipse",
            {"x": 200, "y": 40, "width": 100, "height": 70, "fill": "#BFDBFE"},
        ),
    },
    "draw.circle": {
        "category": "draw",
        "stored_object_type": "ellipse",
        "description": "Create a circle convenience alias stored as an ellipse.",
        "required": {
            "x": _field("number", description="Top-left x of the circle bounds."),
            "y": _field("number", description="Top-left y of the circle bounds."),
            "radius": _field("positive-number"),
        },
        "optional": {
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "stroke": _STROKE_FIELD,
            "fill": _FILL_FIELD,
            "stroke_width": _STROKE_WIDTH_FIELD,
        },
        "example": _example(
            "draw.circle",
            {"x": 320, "y": 40, "radius": 30, "fill": "#86EFAC"},
        ),
    },
    "draw.polyline": {
        "category": "draw",
        "stored_object_type": "polyline",
        "description": "Create an open polyline.",
        "required": {"points": _POINTS_FIELD},
        "optional": {
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "stroke": _STROKE_FIELD,
            "stroke_width": _STROKE_WIDTH_FIELD,
        },
        "example": _example(
            "draw.polyline",
            {"points": [[20, 120], [60, 90], [110, 140], [160, 110]]},
        ),
    },
    "draw.polygon": {
        "category": "draw",
        "stored_object_type": "polygon",
        "description": "Create a closed polygon.",
        "required": {"points": _POINTS_FIELD},
        "optional": {
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "stroke": _STROKE_FIELD,
            "fill": _FILL_FIELD,
            "stroke_width": _STROKE_WIDTH_FIELD,
        },
        "example": _example(
            "draw.polygon",
            {"points": [[220, 180], [300, 120], [360, 210]], "fill": "#FF6666"},
        ),
    },
    "draw.text": {
        "category": "draw",
        "stored_object_type": "text",
        "description": "Create a text label.",
        "required": {
            "x": _field("number"),
            "y": _field("number"),
            "text": _field("string"),
        },
        "optional": {
            "size": _TEXT_SIZE_FIELD,
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "fill": _field(
                "color|null",
                default="#000000",
                description=_COLOR_DESCRIPTION,
            ),
            "anchor": _TEXT_ANCHOR_FIELD,
            "max_width": _TEXT_MAX_WIDTH_FIELD,
        },
        "example": _example(
            "draw.text",
            {
                "x": 60,
                "y": 220,
                "text": "Review queue",
                "anchor": "center",
                "max_width": 140,
            },
        ),
    },
    "draw.image": {
        "category": "draw",
        "stored_object_type": "image",
        "description": "Create an image object from a session-local asset.",
        "required": {
            "x": _field("number"),
            "y": _field("number"),
            "asset_path": _field("string"),
        },
        "optional": {
            "width": _field("positive-number"),
            "height": _field("positive-number"),
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
        },
        "example": _example(
            "draw.image",
            {"x": 420, "y": 40, "asset_path": "assets/reference.png"},
        ),
    },
    "edit.line": {
        "category": "edit",
        "stored_object_type": "line",
        "description": "Edit a line.",
        "selector": _selector_spec(allow_label_only_note=_EDIT_SELECTOR_NOTE),
        "optional": {
            "x1": _field("number"),
            "y1": _field("number"),
            "x2": _field("number"),
            "y2": _field("number"),
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "stroke": _STROKE_FIELD,
            "stroke_width": _STROKE_WIDTH_FIELD,
        },
        "example": _example("edit.line", {"id": "obj_000001", "stroke": "#DC2626"}),
    },
    "edit.arrow": {
        "category": "edit",
        "stored_object_type": "arrow",
        "description": "Edit an arrow.",
        "selector": _selector_spec(allow_label_only_note=_EDIT_SELECTOR_NOTE),
        "optional": {
            "x1": _field("number"),
            "y1": _field("number"),
            "x2": _field("number"),
            "y2": _field("number"),
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "stroke": _STROKE_FIELD,
            "stroke_width": _STROKE_WIDTH_FIELD,
            "arrowhead": _ARROWHEAD_FIELD,
            "arrow_size": _ARROW_SIZE_FIELD,
        },
        "example": _example("edit.arrow", {"id": "obj_000001", "arrowhead": "both"}),
    },
    "edit.rect": {
        "category": "edit",
        "stored_object_type": "rect",
        "description": "Edit a rectangle.",
        "selector": _selector_spec(allow_label_only_note=_EDIT_SELECTOR_NOTE),
        "optional": {
            "x": _field("number"),
            "y": _field("number"),
            "width": _field("positive-number"),
            "height": _field("positive-number"),
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "stroke": _STROKE_FIELD,
            "fill": _FILL_FIELD,
            "stroke_width": _STROKE_WIDTH_FIELD,
        },
        "example": _example("edit.rect", {"id": "obj_000001", "fill": "#CCE5FF"}),
    },
    "edit.ellipse": {
        "category": "edit",
        "stored_object_type": "ellipse",
        "description": "Edit an ellipse.",
        "selector": _selector_spec(allow_label_only_note=_EDIT_SELECTOR_NOTE),
        "optional": {
            "x": _field("number"),
            "y": _field("number"),
            "width": _field("positive-number"),
            "height": _field("positive-number"),
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "stroke": _STROKE_FIELD,
            "fill": _FILL_FIELD,
            "stroke_width": _STROKE_WIDTH_FIELD,
        },
        "example": _example("edit.ellipse", {"id": "obj_000001", "width": 120}),
    },
    "edit.circle": {
        "category": "edit",
        "stored_object_type": "ellipse",
        "description": "Edit a circle convenience alias stored as an ellipse.",
        "selector": _selector_spec(allow_label_only_note=_EDIT_SELECTOR_NOTE),
        "optional": {
            "x": _field("number", description="Top-left x of the circle bounds."),
            "y": _field("number", description="Top-left y of the circle bounds."),
            "radius": _field("positive-number"),
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "stroke": _STROKE_FIELD,
            "fill": _FILL_FIELD,
            "stroke_width": _STROKE_WIDTH_FIELD,
        },
        "example": _example("edit.circle", {"id": "obj_000001", "radius": 24}),
    },
    "edit.polyline": {
        "category": "edit",
        "stored_object_type": "polyline",
        "description": "Edit a polyline.",
        "selector": _selector_spec(allow_label_only_note=_EDIT_SELECTOR_NOTE),
        "optional": {
            "points": _POINTS_FIELD,
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "stroke": _STROKE_FIELD,
            "stroke_width": _STROKE_WIDTH_FIELD,
        },
        "example": _example("edit.polyline", {"id": "obj_000001", "points": [[0, 0], [10, 20]]}),
    },
    "edit.polygon": {
        "category": "edit",
        "stored_object_type": "polygon",
        "description": "Edit a polygon.",
        "selector": _selector_spec(allow_label_only_note=_EDIT_SELECTOR_NOTE),
        "optional": {
            "points": _POINTS_FIELD,
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "stroke": _STROKE_FIELD,
            "fill": _FILL_FIELD,
            "stroke_width": _STROKE_WIDTH_FIELD,
        },
        "example": _example("edit.polygon", {"id": "obj_000001", "fill": "#FCA5A5"}),
    },
    "edit.text": {
        "category": "edit",
        "stored_object_type": "text",
        "description": "Edit a text object.",
        "selector": _selector_spec(allow_label_only_note=_EDIT_SELECTOR_NOTE),
        "optional": {
            "x": _field("number"),
            "y": _field("number"),
            "text": _field("string"),
            "size": _TEXT_SIZE_FIELD,
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
            "fill": _field("color|null"),
            "anchor": _TEXT_ANCHOR_FIELD,
            "max_width": _TEXT_MAX_WIDTH_FIELD,
        },
        "example": _example("edit.text", {"id": "obj_000001", "anchor": "right"}),
    },
    "edit.image": {
        "category": "edit",
        "stored_object_type": "image",
        "description": "Edit image placement.",
        "selector": _selector_spec(allow_label_only_note=_EDIT_SELECTOR_NOTE),
        "optional": {
            "x": _field("number"),
            "y": _field("number"),
            "width": _field("positive-number"),
            "height": _field("positive-number"),
            "label": _LABEL_FIELD,
            "visible": _VISIBLE_FIELD,
        },
        "example": _example("edit.image", {"id": "obj_000001", "width": 80}),
    },
    "delete": {
        "category": "mutation",
        "description": "Delete one object by id or unique live label.",
        "selector": _selector_spec(allow_label_only_note=_DELETE_SELECTOR_NOTE),
        "example": _example("delete", {"label": "box"}),
    },
    "undo": {
        "category": "mutation",
        "description": "Undo the most recent action.",
        "payload": {"required": {}, "optional": {}},
        "example": _example("undo", {}),
    },
}

DRAW_OPERATIONS = frozenset(op for op in _OPERATION_SCHEMAS if op.startswith("draw."))
EDIT_OPERATIONS = frozenset(op for op in _OPERATION_SCHEMAS if op.startswith("edit."))
OTHER_OPERATIONS = frozenset(
    op for op in _OPERATION_SCHEMAS if op not in DRAW_OPERATIONS | EDIT_OPERATIONS
)

_MANUAL_SUGGESTIONS = {
    "draw.box": "draw.rect",
    "edit.box": "edit.rect",
    "draw.square": "draw.rect",
    "edit.square": "edit.rect",
    "draw.oval": "draw.ellipse",
    "edit.oval": "edit.ellipse",
    "draw.star": "draw.polygon",
    "edit.star": "edit.polygon",
    "draw.connector": "draw.arrow",
    "edit.connector": "edit.arrow",
    "draw.label": "draw.text",
    "edit.label": "edit.text",
}


def supported_operations() -> tuple[str, ...]:
    """Return every supported operation in stable order."""
    return tuple(sorted(_OPERATION_SCHEMAS))


def operations_for_namespace(namespace: str | None) -> tuple[str, ...]:
    """Return supported operations for a draw/edit namespace or all operations."""
    if namespace == "draw":
        return tuple(sorted(DRAW_OPERATIONS))
    if namespace == "edit":
        return tuple(sorted(EDIT_OPERATIONS))
    return supported_operations()


def stored_object_type_for_op(op: str) -> str | None:
    """Return the stored object type for a draw/edit operation."""
    spec = _OPERATION_SCHEMAS.get(op)
    if spec is None:
        return None
    object_type = spec.get("stored_object_type")
    return object_type if isinstance(object_type, str) else None


def suggest_operation(op: str) -> str | None:
    """Return a best-effort suggestion for an unsupported operation."""
    manual = _MANUAL_SUGGESTIONS.get(op)
    if manual is not None:
        return manual
    matches = difflib.get_close_matches(op, supported_operations(), n=1, cutoff=0.5)
    if matches:
        return matches[0]
    return None


def unsupported_command_message(op: str) -> str:
    """Build a descriptive unsupported-command error message."""
    namespace = op.split(".", 1)[0] if "." in op else None
    valid_ops = operations_for_namespace(namespace if namespace in {"draw", "edit"} else None)
    scope = f"valid {namespace} ops" if namespace in {"draw", "edit"} else "valid ops"
    parts = [f"unsupported command: {op}"]
    suggestion = suggest_operation(op)
    if suggestion is not None:
        parts.append(f"did you mean {suggestion}?")
    parts.append(f"{scope}: {', '.join(valid_ops)}")
    return "; ".join(parts)


def schema_manifest() -> dict[str, object]:
    """Return a machine-readable manifest of supported operations."""
    return {
        "schema_version": 2,
        "canvas_defaults": {
            "width": DEFAULT_CANVAS_WIDTH,
            "height": DEFAULT_CANVAS_HEIGHT,
            "background": DEFAULT_CANVAS_BACKGROUND,
        },
        "color_format": {
            "syntax": "#RRGGBB or #RRGGBBAA",
            "compositing": (
                "source-over alpha; translucent objects blend with"
                " earlier scene content in creation order"
            ),
        },
        "ops": deepcopy(_OPERATION_SCHEMAS),
    }
