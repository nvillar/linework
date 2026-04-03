"""Command-line interface for mural."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from mural.bootstrap import BOOTSTRAP_TEXT
from mural.core.errors import SceneEngineError
from mural.storage.lock import SessionLockedError
from mural.storage.models import MutationResult
from mural.storage.session import (
    SessionError,
    apply_batch,
    apply_imported_image,
    apply_mutation,
    create_session,
    export_session,
    inspect_session,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="mural",
        description="Agent-first CLI sketch tool.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the installed mural version and exit.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- new ---
    new_parser = subparsers.add_parser("new", help="Create a new mural session.")
    new_parser.add_argument("--session", help="Explicit session directory path.")
    new_parser.add_argument("--name", help="Human-readable session name.")
    new_parser.add_argument("--width", type=int, default=1200, help="Canvas width in pixels.")
    new_parser.add_argument("--height", type=int, default=800, help="Canvas height in pixels.")
    new_parser.add_argument(
        "--background",
        default="#FFFFFF",
        help="Canvas background color in #RRGGBB or #RRGGBBAA form.",
    )
    new_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    # --- run ---
    run_parser = subparsers.add_parser("run", help="Apply JSONL operations (primary interface).")
    run_parser.add_argument("--session", required=True, help="Session directory path.")
    run_parser.add_argument("--file", help="Read JSONL from a file instead of stdin.")
    run_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    # --- inspect ---
    inspect_parser = subparsers.add_parser("inspect", help="Read current scene state.")
    inspect_parser.add_argument("--session", required=True, help="Session directory path.")
    inspect_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    # --- export ---
    export_parser = subparsers.add_parser("export", help="Export PNG to a path.")
    export_parser.add_argument("--session", required=True, help="Session directory path.")
    export_parser.add_argument("--out", required=True, help="Output PNG path.")
    export_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    # --- draw ---
    draw_parser = subparsers.add_parser("draw", help="Create a single object (convenience).")
    draw_subparsers = draw_parser.add_subparsers(dest="draw_type", required=True)
    _add_draw_line_parser(draw_subparsers)
    _add_draw_rect_like_parser(draw_subparsers, name="rect")
    _add_draw_rect_like_parser(draw_subparsers, name="ellipse")
    _add_draw_polyline_parser(draw_subparsers)
    _add_draw_text_parser(draw_subparsers)
    _add_draw_image_parser(draw_subparsers)

    # --- edit ---
    edit_parser = subparsers.add_parser("edit", help="Modify a single object (convenience).")
    edit_subparsers = edit_parser.add_subparsers(dest="edit_type", required=True)
    _add_edit_line_parser(edit_subparsers)
    _add_edit_rect_like_parser(edit_subparsers, name="rect")
    _add_edit_rect_like_parser(edit_subparsers, name="ellipse")
    _add_edit_polyline_parser(edit_subparsers)
    _add_edit_text_parser(edit_subparsers)
    _add_edit_image_parser(edit_subparsers)

    # --- delete ---
    delete_parser = subparsers.add_parser("delete", help="Delete a single object.")
    _add_session_argument(delete_parser)
    delete_parser.add_argument("--id", required=True, help="Stable object identifier.")
    _add_json_argument(delete_parser)

    # --- undo ---
    undo_parser = subparsers.add_parser("undo", help="Undo the most recent mutation.")
    _add_session_argument(undo_parser)
    _add_json_argument(undo_parser)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the top-level CLI."""
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if len(effective_argv) == 0:
        print(BOOTSTRAP_TEXT)
        return 0

    parser = build_parser()
    args = parser.parse_args(effective_argv)

    if args.version:
        from mural import __version__

        print(__version__)
        return 0

    if args.command == "new":
        return cmd_new(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "inspect":
        return cmd_inspect(args)
    if args.command == "export":
        return cmd_export(args)
    if args.command == "draw":
        return cmd_draw(args)
    if args.command == "edit":
        return cmd_edit(args)
    if args.command == "delete":
        return cmd_delete(args)
    if args.command == "undo":
        return cmd_undo(args)

    parser.print_help()
    return 0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _error(message: str, *, use_json: bool) -> int:
    """Print an error and return exit code 1."""
    if use_json:
        print(json.dumps({"error": message}))
    else:
        print(f"error: {message}", file=sys.stderr)
    return 1


def _add_session_argument(parser: argparse.ArgumentParser) -> None:
    """Add the required session flag to a parser."""
    parser.add_argument("--session", required=True, help="Session directory path.")


def _add_json_argument(parser: argparse.ArgumentParser) -> None:
    """Add the shared JSON output flag to a parser."""
    parser.add_argument("--json", action="store_true", help="Print JSON output.")


def _add_label_argument(parser: argparse.ArgumentParser) -> None:
    """Add the optional label flag."""
    parser.add_argument("--label", help="Optional object label.")


def _add_visible_argument(parser: argparse.ArgumentParser) -> None:
    """Add the optional visible flag."""
    parser.add_argument(
        "--visible",
        type=_parse_bool,
        help="Set object visibility (`true` or `false`).",
    )


def _add_stroke_argument(parser: argparse.ArgumentParser) -> None:
    """Add the optional stroke color flag."""
    parser.add_argument("--stroke", help="Stroke color in #RRGGBB or #RRGGBBAA form.")


def _add_fill_argument(parser: argparse.ArgumentParser) -> None:
    """Add the optional fill color flag."""
    parser.add_argument("--fill", help="Fill color in #RRGGBB or #RRGGBBAA form.")


def _add_stroke_width_argument(parser: argparse.ArgumentParser) -> None:
    """Add the optional stroke width flag."""
    parser.add_argument("--stroke-width", type=float, help="Stroke width in pixels.")


def _add_edit_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add shared optional fields for edit commands."""
    _add_session_argument(parser)
    parser.add_argument("--id", required=True, help="Stable object identifier.")
    _add_label_argument(parser)
    _add_visible_argument(parser)
    _add_json_argument(parser)


def _add_line_geometry(parser: argparse.ArgumentParser, *, required: bool) -> None:
    """Add line endpoint arguments."""
    parser.add_argument("--x1", type=float, required=required, help="Start x coordinate.")
    parser.add_argument("--y1", type=float, required=required, help="Start y coordinate.")
    parser.add_argument("--x2", type=float, required=required, help="End x coordinate.")
    parser.add_argument("--y2", type=float, required=required, help="End y coordinate.")


def _add_rect_like_geometry(parser: argparse.ArgumentParser, *, required: bool) -> None:
    """Add rectangle or ellipse geometry arguments."""
    parser.add_argument("--x", type=float, required=required, help="Top-left x coordinate.")
    parser.add_argument("--y", type=float, required=required, help="Top-left y coordinate.")
    parser.add_argument("--width", type=float, required=required, help="Width in pixels.")
    parser.add_argument("--height", type=float, required=required, help="Height in pixels.")


def _add_text_geometry(parser: argparse.ArgumentParser, *, required: bool) -> None:
    """Add text geometry arguments."""
    parser.add_argument("--x", type=float, required=required, help="Text anchor x coordinate.")
    parser.add_argument("--y", type=float, required=required, help="Text anchor y coordinate.")
    parser.add_argument("--text", required=required, help="Text content.")


def _add_polyline_points(parser: argparse.ArgumentParser, *, required: bool) -> None:
    """Add repeated polyline point arguments."""
    parser.add_argument(
        "--point",
        dest="points",
        action="append",
        required=required,
        type=_parse_point,
        metavar="X,Y",
        help="Polyline point; repeat the flag to add more points.",
    )


def _parse_bool(value: str) -> bool:
    """Parse a CLI boolean flag value."""
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise argparse.ArgumentTypeError("value must be `true` or `false`")


def _parse_point(value: str) -> list[float]:
    """Parse a ``X,Y`` point."""
    x_text, separator, y_text = value.partition(",")
    if separator != ",":
        raise argparse.ArgumentTypeError("point must be in X,Y form")
    try:
        x = float(x_text.strip())
        y = float(y_text.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("point coordinates must be numeric") from exc
    return [x, y]


def _add_draw_line_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``mural draw line`` parser."""
    parser = subparsers.add_parser("line", help="Draw a line.")
    _add_session_argument(parser)
    _add_line_geometry(parser, required=True)
    _add_label_argument(parser)
    _add_visible_argument(parser)
    _add_stroke_argument(parser)
    _add_stroke_width_argument(parser)
    _add_json_argument(parser)


def _add_draw_rect_like_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser], *, name: str
) -> None:
    """Add a draw parser for rect-like objects."""
    parser = subparsers.add_parser(name, help=f"Draw a {name}.")
    _add_session_argument(parser)
    _add_rect_like_geometry(parser, required=True)
    _add_label_argument(parser)
    _add_visible_argument(parser)
    _add_stroke_argument(parser)
    _add_fill_argument(parser)
    _add_stroke_width_argument(parser)
    _add_json_argument(parser)


def _add_draw_polyline_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the ``mural draw polyline`` parser."""
    parser = subparsers.add_parser("polyline", help="Draw a polyline.")
    _add_session_argument(parser)
    _add_polyline_points(parser, required=True)
    _add_label_argument(parser)
    _add_visible_argument(parser)
    _add_stroke_argument(parser)
    _add_stroke_width_argument(parser)
    _add_json_argument(parser)


def _add_draw_text_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``mural draw text`` parser."""
    parser = subparsers.add_parser("text", help="Draw a text label.")
    _add_session_argument(parser)
    _add_text_geometry(parser, required=True)
    parser.add_argument("--size", type=float, help="Text size in pixels.")
    _add_label_argument(parser)
    _add_visible_argument(parser)
    _add_fill_argument(parser)
    _add_json_argument(parser)


def _add_draw_image_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``mural draw image`` parser."""
    parser = subparsers.add_parser("image", help="Draw an imported image.")
    _add_session_argument(parser)
    parser.add_argument("--source", required=True, help="Path to the source image file.")
    parser.add_argument("--x", type=float, required=True, help="Top-left x coordinate.")
    parser.add_argument("--y", type=float, required=True, help="Top-left y coordinate.")
    parser.add_argument("--width", type=float, help="Width in pixels.")
    parser.add_argument("--height", type=float, help="Height in pixels.")
    _add_label_argument(parser)
    _add_visible_argument(parser)
    _add_json_argument(parser)


def _add_edit_line_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``mural edit line`` parser."""
    parser = subparsers.add_parser("line", help="Edit a line.")
    _add_edit_common_arguments(parser)
    _add_line_geometry(parser, required=False)
    _add_stroke_argument(parser)
    _add_stroke_width_argument(parser)


def _add_edit_rect_like_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser], *, name: str
) -> None:
    """Add an edit parser for rect-like objects."""
    parser = subparsers.add_parser(name, help=f"Edit a {name}.")
    _add_edit_common_arguments(parser)
    _add_rect_like_geometry(parser, required=False)
    _add_stroke_argument(parser)
    _add_fill_argument(parser)
    _add_stroke_width_argument(parser)


def _add_edit_polyline_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the ``mural edit polyline`` parser."""
    parser = subparsers.add_parser("polyline", help="Edit a polyline.")
    _add_edit_common_arguments(parser)
    _add_polyline_points(parser, required=False)
    _add_stroke_argument(parser)
    _add_stroke_width_argument(parser)


def _add_edit_text_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``mural edit text`` parser."""
    parser = subparsers.add_parser("text", help="Edit a text object.")
    _add_edit_common_arguments(parser)
    _add_text_geometry(parser, required=False)
    parser.add_argument("--size", type=float, help="Text size in pixels.")
    _add_fill_argument(parser)


def _add_edit_image_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``mural edit image`` parser."""
    parser = subparsers.add_parser("image", help="Edit an image object.")
    _add_edit_common_arguments(parser)
    _add_rect_like_geometry(parser, required=False)


def _include_optional_values(
    payload: dict[str, object],
    args: argparse.Namespace,
    *field_names: str,
) -> None:
    """Copy namespace values into a payload when they were provided."""
    for field_name in field_names:
        value = getattr(args, field_name)
        if value is not None:
            payload[field_name] = value


def _build_draw_payload(args: argparse.Namespace) -> dict[str, object]:
    """Build a convenience draw payload from CLI arguments."""
    draw_type = args.draw_type
    if draw_type == "line":
        payload = {"x1": args.x1, "y1": args.y1, "x2": args.x2, "y2": args.y2}
        _include_optional_values(payload, args, "label", "visible", "stroke", "stroke_width")
        return payload

    if draw_type in {"rect", "ellipse"}:
        payload = {
            "x": args.x,
            "y": args.y,
            "width": args.width,
            "height": args.height,
        }
        _include_optional_values(
            payload,
            args,
            "label",
            "visible",
            "stroke",
            "fill",
            "stroke_width",
        )
        return payload

    if draw_type == "polyline":
        payload = {"points": args.points}
        _include_optional_values(payload, args, "label", "visible", "stroke", "stroke_width")
        return payload

    if draw_type == "text":
        payload = {"x": args.x, "y": args.y, "text": args.text}
        _include_optional_values(payload, args, "size", "label", "visible", "fill")
        return payload

    if draw_type == "image":
        payload = {"x": args.x, "y": args.y}
        _include_optional_values(payload, args, "width", "height", "label", "visible")
        return payload

    raise ValueError(f"unsupported draw type: {draw_type}")


def _build_edit_payload(args: argparse.Namespace) -> dict[str, object]:
    """Build a convenience edit payload from CLI arguments."""
    payload: dict[str, object] = {"id": args.id}
    edit_type = args.edit_type

    if edit_type == "line":
        _include_optional_values(
            payload,
            args,
            "x1",
            "y1",
            "x2",
            "y2",
            "label",
            "visible",
            "stroke",
            "stroke_width",
        )
    elif edit_type in {"rect", "ellipse"}:
        _include_optional_values(
            payload,
            args,
            "x",
            "y",
            "width",
            "height",
            "label",
            "visible",
            "stroke",
            "fill",
            "stroke_width",
        )
    elif edit_type == "polyline":
        _include_optional_values(
            payload,
            args,
            "label",
            "visible",
            "stroke",
            "stroke_width",
        )
        if args.points is not None:
            payload["points"] = args.points
    elif edit_type == "text":
        _include_optional_values(
            payload,
            args,
            "x",
            "y",
            "text",
            "size",
            "label",
            "visible",
            "fill",
        )
    elif edit_type == "image":
        _include_optional_values(
            payload,
            args,
            "x",
            "y",
            "width",
            "height",
            "label",
            "visible",
        )
    else:
        raise ValueError(f"unsupported edit type: {edit_type}")

    if len(payload) == 1:
        raise ValueError("at least one field must be provided for edit")
    return payload


def _single_operation_payload(result: MutationResult) -> dict[str, object]:
    """Serialize a convenience command result in the single-op run shape."""
    return {
        "applied": 1,
        "failed": None,
        "results": [
            {
                "op_id": result.op_id,
                "op": result.op,
                "object_id": result.object_id,
            }
        ],
        "session_path": result.session_path,
        "scene_object_count": result.scene_object_count,
        "latest_render": result.latest_render,
    }


def _apply_single_operation(
    *,
    session: str,
    op: str,
    payload: dict[str, object] | None,
    use_json: bool,
    summary: Callable[[MutationResult], str],
) -> int:
    """Apply one mutating operation and print its output."""
    try:
        result = apply_mutation(session, op=op, payload=payload)
    except (OSError, SessionError, SessionLockedError, SceneEngineError) as exc:
        return _error(str(exc), use_json=use_json)
    return _emit_single_operation_result(result=result, use_json=use_json, summary=summary)


def _emit_single_operation_result(
    *,
    result: MutationResult,
    use_json: bool,
    summary: Callable[[MutationResult], str],
) -> int:
    """Emit output for a single-operation result."""
    if use_json:
        print(json.dumps(_single_operation_payload(result), indent=2))
        return 0

    print(summary(result))
    print(f"Operation ID: {result.op_id}")
    print(f"Objects: {result.scene_object_count}")
    print(f"Latest render: {result.latest_render}")
    return 0


def _draw_summary(result: MutationResult) -> str:
    """Format human-readable output for draw commands."""
    object_type = result.op.removeprefix("draw.")
    return f"Created {object_type}: {result.object_id}"


def _edit_summary(result: MutationResult) -> str:
    """Format human-readable output for edit commands."""
    object_type = result.op.removeprefix("edit.")
    return f"Updated {object_type}: {result.object_id}"


def _delete_summary(result: MutationResult) -> str:
    """Format human-readable output for delete."""
    return f"Deleted object: {result.object_id}"


def _undo_summary(result: MutationResult) -> str:
    """Format human-readable output for undo."""
    return "Undid last command"


# ---------------------------------------------------------------------------
# mural new
# ---------------------------------------------------------------------------


def cmd_new(args: argparse.Namespace) -> int:
    """Handle ``mural new``."""
    try:
        result = create_session(
            session=args.session,
            name=args.name,
            width=args.width,
            height=args.height,
            background=args.background,
        )
    except (OSError, SessionError, SessionLockedError) as exc:
        return _error(str(exc), use_json=args.json)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    print(f"Created session: {result.session_id}")
    print(f"Session path: {result.session_path}")
    print(f"Canvas: {result.canvas.width}x{result.canvas.height}")
    print(f"Latest render: {result.latest_render}")
    return 0


# ---------------------------------------------------------------------------
# mural run
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    """Handle ``mural run``."""
    try:
        operations = _read_jsonl(args.file)
    except (OSError, ValueError) as exc:
        return _error(str(exc), use_json=args.json)

    try:
        result = apply_batch(args.session, operations=operations)
    except (OSError, SessionError, SessionLockedError, SceneEngineError) as exc:
        return _error(str(exc), use_json=args.json)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"Applied {result.applied} operation(s)")
        if result.failed:
            print(f"Failed: {result.failed['op']}: {result.failed['error']}")
        print(f"Objects: {result.scene_object_count}")
        print(f"Latest render: {result.latest_render}")

    return 1 if result.failed is not None else 0


def _read_jsonl(file_path: str | None) -> list[dict[str, object]]:
    """Read JSONL operations from a file or stdin."""
    if file_path is not None:
        text = Path(file_path).expanduser().resolve().read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    operations: list[dict[str, object]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {line_number}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"line {line_number} must be a JSON object")
        operations.append(parsed)
    return operations


# ---------------------------------------------------------------------------
# mural inspect
# ---------------------------------------------------------------------------


def cmd_inspect(args: argparse.Namespace) -> int:
    """Handle ``mural inspect``."""
    try:
        result = inspect_session(args.session)
    except (OSError, SessionError) as exc:
        return _error(str(exc), use_json=args.json)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    print(f"Session: {result.session_id}")
    print(f"Path: {result.session_path}")
    print(f"Canvas: {result.canvas.width}x{result.canvas.height}")
    print(f"Background: {result.canvas.background}")
    print(f"Objects: {result.object_count}")
    print(f"Latest render: {result.latest_render}")

    if result.objects:
        print()
        print(f"{'ID':<14} {'Type':<10} {'Label':<16} {'Vis':>3}  Geometry")
        print(f"{'─' * 14} {'─' * 10} {'─' * 16} {'─' * 3}  {'─' * 30}")
        for obj in result.objects:
            obj_id = str(obj.get("id", ""))
            obj_type = str(obj.get("type", ""))
            label = str(obj.get("label", "")) if obj.get("label") else ""
            visible = "yes" if obj.get("visible", True) else "no"
            geometry = _format_geometry(obj)
            print(f"{obj_id:<14} {obj_type:<10} {label:<16} {visible:>3}  {geometry}")

    return 0


def _format_geometry(obj: dict[str, object]) -> str:
    """Format a compact geometry summary for inspect output."""
    obj_type = str(obj.get("type", ""))
    if obj_type == "line":
        return f"({obj.get('x1')},{obj.get('y1')})→({obj.get('x2')},{obj.get('y2')})"
    if obj_type in {"rect", "ellipse", "image"}:
        return f"({obj.get('x')},{obj.get('y')}) {obj.get('width')}×{obj.get('height')}"
    if obj_type == "text":
        text = str(obj.get("text", ""))
        truncated = text[:20] + "…" if len(text) > 20 else text
        return f'({obj.get("x")},{obj.get("y")}) "{truncated}"'
    if obj_type == "polyline":
        points = obj.get("points")
        count = len(points) if isinstance(points, list) else 0
        return f"{count} points"
    return ""


# ---------------------------------------------------------------------------
# mural export
# ---------------------------------------------------------------------------


def cmd_export(args: argparse.Namespace) -> int:
    """Handle ``mural export``."""
    try:
        exported_path = export_session(args.session, out=args.out)
    except (OSError, SessionError) as exc:
        return _error(str(exc), use_json=args.json)

    if args.json:
        print(json.dumps({"exported_path": exported_path}))
        return 0

    print(f"Exported: {exported_path}")
    return 0


# ---------------------------------------------------------------------------
# Convenience commands
# ---------------------------------------------------------------------------


def cmd_draw(args: argparse.Namespace) -> int:
    """Handle ``mural draw``."""
    try:
        payload = _build_draw_payload(args)
    except ValueError as exc:
        return _error(str(exc), use_json=args.json)

    if args.draw_type == "image":
        try:
            result = apply_imported_image(args.session, source=args.source, payload=payload)
        except (OSError, SessionError, SessionLockedError, SceneEngineError) as exc:
            return _error(str(exc), use_json=args.json)
        return _emit_single_operation_result(
            result=result,
            use_json=args.json,
            summary=_draw_summary,
        )

    return _apply_single_operation(
        session=args.session,
        op=f"draw.{args.draw_type}",
        payload=payload,
        use_json=args.json,
        summary=_draw_summary,
    )


def cmd_edit(args: argparse.Namespace) -> int:
    """Handle ``mural edit``."""
    try:
        payload = _build_edit_payload(args)
    except ValueError as exc:
        return _error(str(exc), use_json=args.json)
    return _apply_single_operation(
        session=args.session,
        op=f"edit.{args.edit_type}",
        payload=payload,
        use_json=args.json,
        summary=_edit_summary,
    )


def cmd_delete(args: argparse.Namespace) -> int:
    """Handle ``mural delete``."""
    return _apply_single_operation(
        session=args.session,
        op="delete",
        payload={"id": args.id},
        use_json=args.json,
        summary=_delete_summary,
    )


def cmd_undo(args: argparse.Namespace) -> int:
    """Handle ``mural undo``."""
    return _apply_single_operation(
        session=args.session,
        op="undo",
        payload=None,
        use_json=args.json,
        summary=_undo_summary,
    )
