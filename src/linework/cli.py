"""Command-line interface for linework."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from linework.bootstrap import BOOTSTRAP_TEXT
from linework.capabilities import OTHER_OPERATIONS, operations_for_namespace, schema_manifest
from linework.constants import (
    ARROWHEAD_MODES,
    DEFAULT_CANVAS_BACKGROUND,
    DEFAULT_CANVAS_HEIGHT,
    DEFAULT_CANVAS_WIDTH,
    TEXT_ANCHORS,
)
from linework.core.errors import SceneEngineError
from linework.storage.lock import SessionLockedError
from linework.storage.models import BatchResult, CreatedSession, MutationResult
from linework.storage.session import (
    SessionError,
    apply_batch,
    apply_imported_image,
    apply_mutation,
    create_session,
    export_session,
    inspect_session,
)
from linework.watch import DEFAULT_INTERVAL_MS, WatchError, create_session_watcher


class _HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    """CLI help formatter with defaults and preserved example layout."""


_TOP_LEVEL_EPILOG = """\
Golden path:
  linework                                      # orientation and JSONL reference
  linework schema --json
  linework new --name idea-board --json
  linework run --session PATH --json < ops.jsonl
  linework inspect --session PATH --json
  linework edit rect --session PATH --id obj_000001 --fill #CCE5FF --json
  linework watch --session PATH
  linework export --session PATH --out out.png
"""

_NEW_EPILOG = f"""\
Examples:
  linework new --json
  linework new --name idea-board --watch
  linework new --width {DEFAULT_CANVAS_WIDTH} --height {DEFAULT_CANVAS_HEIGHT}
"""

_RUN_EPILOG = """\
Examples:
  linework run --session PATH --json < ops.jsonl
  linework run --session PATH --file ops.jsonl
  linework run --file ops.jsonl --out out.png

JSONL input:
  {"op":"draw.rect","payload":{"x":50,"y":50,"width":200,"height":100}}
  {"op":"draw.arrow","payload":{"x1":20,"y1":40,"x2":160,"y2":40,"arrowhead":"both","arrow_size":18}}
  {"op":"draw.circle","payload":{"x":40,"y":40,"radius":30}}
  {"op":"draw.polygon","payload":{"points":[[220,180],[300,120],[360,210]],"fill":"#FF6666"}}
  {"op":"delete","payload":{"label":"note-box"}}

Provide --out without --session to use a temporary throwaway session that is
exported and then deleted.
"""

_SCHEMA_EPILOG = """\
Examples:
  linework schema
  linework schema --json
"""

_INSPECT_EPILOG = """\
Examples:
  linework inspect --session PATH
  linework inspect --session PATH --json

Use inspect before edit/delete to discover stable object IDs and labels.
"""

_DRAW_EPILOG = """\
Examples:
  linework draw arrow --session PATH --x1 20 --y1 40 --x2 180 --y2 40
    --arrowhead both --arrow-size 18
  linework draw rect --session PATH --x 50 --y 50 --width 200 --height 100 --fill #E8E8E8
  linework draw circle --session PATH --x 240 --y 60 --radius 30 --fill #FDE68A
  linework draw polygon --session PATH --point 220,180 --point 300,120 --point 360,210
"""

_EDIT_EPILOG = """\
Examples:
  linework edit arrow --session PATH --id obj_000001 --arrowhead both --arrow-size 18
  linework edit rect --session PATH --id obj_000001 --fill #CCE5FF
  linework edit rect --session PATH --label note-box --fill #CCE5FF

When --id is omitted, --label selects the target. Use --id when you need to
change the object's label.
"""

_DELETE_EPILOG = """\
Examples:
  linework delete --session PATH --id obj_000001
  linework delete --session PATH --label note-box
"""

_UNDO_EPILOG = """\
Examples:
  linework undo --session PATH

Undo reverses the last action. A successful `linework run` batch undoes as one
action.
"""

_WATCHER_STARTUP_TIMEOUT_S = 5.0


class _WatchedProcess(Protocol):
    """Minimal process interface used during watcher startup."""

    pid: int

    def poll(self) -> int | None:
        """Return None while still running, else the exit code."""


class _WindowsProcess:
    """Poll a Windows process by PID without holding a live subprocess handle."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self) -> int | None:
        """Return None while the process is still active, else its exit code."""
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        SYNCHRONIZE = 0x00100000
        STILL_ACTIVE = 259

        win_dll = getattr(ctypes, "WinDLL")
        kernel32 = win_dll("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        open_process.restype = ctypes.c_void_p
        get_exit_code = kernel32.GetExitCodeProcess
        get_exit_code.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        get_exit_code.restype = ctypes.c_bool
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_bool

        handle = open_process(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, self.pid)
        if not handle:
            return 1

        try:
            exit_code = ctypes.c_uint32()
            if not get_exit_code(handle, ctypes.byref(exit_code)):
                return 1
            if exit_code.value == STILL_ACTIVE:
                return None
            return int(exit_code.value)
        finally:
            close_handle(handle)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="linework",
        description=(
            "Agent-first CLI sketch tool. Use `linework schema --json` to discover "
            "supported ops, `linework run` for JSONL batches, `inspect` to read the "
            "scene back, and `watch` for a read-only window."
        ),
        epilog=_TOP_LEVEL_EPILOG,
        formatter_class=_HelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the installed linework version and exit.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- schema ---
    schema_parser = subparsers.add_parser(
        "schema",
        help="Print supported operations and payload schema.",
        description=(
            "Print a human-readable capability summary or a machine-readable JSON "
            "manifest describing supported operations, payload fields, and defaults."
        ),
        epilog=_SCHEMA_EPILOG,
        formatter_class=_HelpFormatter,
    )
    schema_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    # --- new ---
    new_parser = subparsers.add_parser(
        "new",
        help="Create a new linework session.",
        description=(
            "Create a new session directory with a blank render. The default canvas "
            f"is {DEFAULT_CANVAS_WIDTH}x{DEFAULT_CANVAS_HEIGHT} with a "
            f"{DEFAULT_CANVAS_BACKGROUND} background."
        ),
        epilog=_NEW_EPILOG,
        formatter_class=_HelpFormatter,
    )
    new_parser.add_argument("--session", help="Explicit session directory path.")
    new_parser.add_argument("--name", help="Human-readable session name.")
    new_parser.add_argument(
        "--width",
        type=int,
        default=DEFAULT_CANVAS_WIDTH,
        help="Canvas width in pixels.",
    )
    new_parser.add_argument(
        "--height",
        type=int,
        default=DEFAULT_CANVAS_HEIGHT,
        help="Canvas height in pixels.",
    )
    new_parser.add_argument(
        "--background",
        default=DEFAULT_CANVAS_BACKGROUND,
        help="Canvas background color in #RRGGBB or #RRGGBBAA form.",
    )
    new_parser.add_argument(
        "--watch",
        action="store_true",
        help="Open the watcher after session creation.",
    )
    new_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    # --- run ---
    run_parser = subparsers.add_parser(
        "run",
        help="Apply JSONL operations (primary interface).",
        description=(
            "Apply JSONL operations to an existing session, or export a one-shot "
            "throwaway batch with --out. Operations run in order, stop on first "
            "failure, and render once at the end."
        ),
        epilog=_RUN_EPILOG,
        formatter_class=_HelpFormatter,
    )
    run_parser.add_argument("--session", help="Session directory path.")
    run_parser.add_argument("--file", help="Read JSONL from a file instead of stdin.")
    run_parser.add_argument(
        "--out",
        help=(
            "Optional PNG export path. When used without --session, linework creates "
            "a temporary session, exports the result, and deletes the session."
        ),
    )
    run_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    # --- inspect ---
    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Read current scene state.",
        description="Read the current scene state and object table for a session.",
        epilog=_INSPECT_EPILOG,
        formatter_class=_HelpFormatter,
    )
    inspect_parser.add_argument("--session", required=True, help="Session directory path.")
    inspect_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    # --- export ---
    export_parser = subparsers.add_parser(
        "export",
        help="Export PNG to a path.",
        description="Render the current scene to a PNG at a user-chosen path.",
        epilog="Example:\n  linework export --session PATH --out out.png\n",
        formatter_class=_HelpFormatter,
    )
    export_parser.add_argument("--session", required=True, help="Session directory path.")
    export_parser.add_argument("--out", required=True, help="Output PNG path.")
    export_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    # --- watch ---
    watch_parser = subparsers.add_parser(
        "watch",
        help="Open a read-only watcher window.",
        description=(
            "Open a read-only watcher window for an existing session. The watcher "
            "polls render/latest.png and never mutates session state."
        ),
        epilog="Example:\n  linework watch --session PATH --interval-ms 250\n",
        formatter_class=_HelpFormatter,
    )
    _add_session_argument(watch_parser)
    watch_parser.add_argument(
        "--interval-ms",
        type=int,
        default=DEFAULT_INTERVAL_MS,
        help=f"Polling interval in milliseconds (default: {DEFAULT_INTERVAL_MS}).",
    )

    # --- _watch-impl (hidden, used by detached watcher) ---
    watch_impl_parser = subparsers.add_parser("_watch-impl")
    watch_impl_parser.add_argument("--session", required=True)
    watch_impl_parser.add_argument("--interval-ms", type=int, default=DEFAULT_INTERVAL_MS)
    watch_impl_parser.add_argument("--startup-status")

    # --- draw ---
    draw_parser = subparsers.add_parser(
        "draw",
        help="Create a single object (convenience).",
        description="Create one object without writing JSONL by hand.",
        epilog=_DRAW_EPILOG,
        formatter_class=_HelpFormatter,
    )
    draw_subparsers = draw_parser.add_subparsers(dest="draw_type", required=True)
    _add_draw_line_parser(draw_subparsers)
    _add_draw_arrow_parser(draw_subparsers)
    _add_draw_rect_like_parser(draw_subparsers, name="rect")
    _add_draw_rect_like_parser(draw_subparsers, name="ellipse")
    _add_draw_circle_parser(draw_subparsers)
    _add_draw_polyline_parser(draw_subparsers)
    _add_draw_polygon_parser(draw_subparsers)
    _add_draw_text_parser(draw_subparsers)
    _add_draw_image_parser(draw_subparsers)

    # --- edit ---
    edit_parser = subparsers.add_parser(
        "edit",
        help="Modify a single object (convenience).",
        description=(
            "Modify one existing object. Use `inspect` first to discover object IDs and labels."
        ),
        epilog=_EDIT_EPILOG,
        formatter_class=_HelpFormatter,
    )
    edit_subparsers = edit_parser.add_subparsers(dest="edit_type", required=True)
    _add_edit_line_parser(edit_subparsers)
    _add_edit_arrow_parser(edit_subparsers)
    _add_edit_rect_like_parser(edit_subparsers, name="rect")
    _add_edit_rect_like_parser(edit_subparsers, name="ellipse")
    _add_edit_circle_parser(edit_subparsers)
    _add_edit_polyline_parser(edit_subparsers)
    _add_edit_polygon_parser(edit_subparsers)
    _add_edit_text_parser(edit_subparsers)
    _add_edit_image_parser(edit_subparsers)

    # --- delete ---
    delete_parser = subparsers.add_parser(
        "delete",
        help="Delete a single object.",
        description="Delete one object by stable ID or unique live label.",
        epilog=_DELETE_EPILOG,
        formatter_class=_HelpFormatter,
    )
    _add_session_argument(delete_parser)
    delete_parser.add_argument("--id", help="Stable object identifier.")
    delete_parser.add_argument(
        "--label",
        help="Unique live object label to delete when --id is omitted.",
    )
    _add_json_argument(delete_parser)

    # --- undo ---
    undo_parser = subparsers.add_parser(
        "undo",
        help="Undo the most recent action.",
        description="Undo the most recent action for a session.",
        epilog=_UNDO_EPILOG,
        formatter_class=_HelpFormatter,
    )
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
        from linework import __version__

        print(__version__)
        return 0

    if args.command == "schema":
        return cmd_schema(args)
    if args.command == "new":
        return cmd_new(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "inspect":
        return cmd_inspect(args)
    if args.command == "export":
        return cmd_export(args)
    if args.command == "watch":
        return cmd_watch(args)
    if args.command == "_watch-impl":
        return _cmd_watch_impl(args)
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
    parser.add_argument(
        "--id",
        help="Stable object identifier. When omitted, --label selects the target object.",
    )
    parser.add_argument(
        "--label",
        help="When --id is provided, set the object label. When --id is omitted, "
        "select the target by its unique live label.",
    )
    _add_visible_argument(parser)
    _add_json_argument(parser)


def _add_line_geometry(parser: argparse.ArgumentParser, *, required: bool) -> None:
    """Add line endpoint arguments."""
    parser.add_argument("--x1", type=float, required=required, help="Start x coordinate.")
    parser.add_argument("--y1", type=float, required=required, help="Start y coordinate.")
    parser.add_argument("--x2", type=float, required=required, help="End x coordinate.")
    parser.add_argument("--y2", type=float, required=required, help="End y coordinate.")


def _add_circle_geometry(parser: argparse.ArgumentParser, *, required: bool) -> None:
    """Add circle geometry arguments."""
    parser.add_argument("--x", type=float, required=required, help="Top-left x coordinate.")
    parser.add_argument("--y", type=float, required=required, help="Top-left y coordinate.")
    parser.add_argument("--radius", type=float, required=required, help="Radius in pixels.")


def _add_rect_like_geometry(parser: argparse.ArgumentParser, *, required: bool) -> None:
    """Add rectangle or ellipse geometry arguments."""
    parser.add_argument("--x", type=float, required=required, help="Top-left x coordinate.")
    parser.add_argument("--y", type=float, required=required, help="Top-left y coordinate.")
    parser.add_argument("--width", type=float, required=required, help="Width in pixels.")
    parser.add_argument("--height", type=float, required=required, help="Height in pixels.")


def _add_text_geometry(parser: argparse.ArgumentParser, *, required: bool) -> None:
    """Add text geometry arguments."""
    parser.add_argument("--x", type=float, required=required, help="Text x coordinate.")
    parser.add_argument("--y", type=float, required=required, help="Text y coordinate.")
    parser.add_argument("--text", required=required, help="Text content.")


def _add_arrowhead_argument(parser: argparse.ArgumentParser) -> None:
    """Add the optional arrowhead mode flag."""
    parser.add_argument(
        "--arrowhead",
        choices=ARROWHEAD_MODES,
        help="Arrowhead placement.",
    )


def _add_arrow_size_argument(parser: argparse.ArgumentParser) -> None:
    """Add the optional arrowhead size flag."""
    parser.add_argument(
        "--arrow-size",
        type=float,
        dest="arrow_size",
        help="Arrowhead size in pixels.",
    )


def _add_text_layout_arguments(parser: argparse.ArgumentParser) -> None:
    """Add optional text alignment and wrapping flags."""
    parser.add_argument(
        "--anchor",
        choices=TEXT_ANCHORS,
        help="Horizontal anchor for the text position.",
    )
    parser.add_argument(
        "--max-width",
        type=float,
        dest="max_width",
        help="Wrap text to this maximum rendered width in pixels.",
    )


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
    """Add the ``linework draw line`` parser."""
    parser = subparsers.add_parser("line", help="Draw a line.", formatter_class=_HelpFormatter)
    _add_session_argument(parser)
    _add_line_geometry(parser, required=True)
    _add_label_argument(parser)
    _add_visible_argument(parser)
    _add_stroke_argument(parser)
    _add_stroke_width_argument(parser)
    _add_json_argument(parser)


def _add_draw_arrow_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``linework draw arrow`` parser."""
    parser = subparsers.add_parser("arrow", help="Draw an arrow.", formatter_class=_HelpFormatter)
    _add_session_argument(parser)
    _add_line_geometry(parser, required=True)
    _add_label_argument(parser)
    _add_visible_argument(parser)
    _add_stroke_argument(parser)
    _add_stroke_width_argument(parser)
    _add_arrowhead_argument(parser)
    _add_arrow_size_argument(parser)
    _add_json_argument(parser)


def _add_draw_rect_like_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser], *, name: str
) -> None:
    """Add a draw parser for rect-like objects."""
    article = "an" if name == "ellipse" else "a"
    parser = subparsers.add_parser(
        name,
        help=f"Draw {article} {name}.",
        formatter_class=_HelpFormatter,
    )
    _add_session_argument(parser)
    _add_rect_like_geometry(parser, required=True)
    _add_label_argument(parser)
    _add_visible_argument(parser)
    _add_stroke_argument(parser)
    _add_fill_argument(parser)
    _add_stroke_width_argument(parser)
    _add_json_argument(parser)


def _add_draw_circle_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the ``linework draw circle`` parser."""
    parser = subparsers.add_parser("circle", help="Draw a circle.", formatter_class=_HelpFormatter)
    _add_session_argument(parser)
    _add_circle_geometry(parser, required=True)
    _add_label_argument(parser)
    _add_visible_argument(parser)
    _add_stroke_argument(parser)
    _add_fill_argument(parser)
    _add_stroke_width_argument(parser)
    _add_json_argument(parser)


def _add_draw_polyline_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the ``linework draw polyline`` parser."""
    parser = subparsers.add_parser(
        "polyline",
        help="Draw a polyline.",
        formatter_class=_HelpFormatter,
    )
    _add_session_argument(parser)
    _add_polyline_points(parser, required=True)
    _add_label_argument(parser)
    _add_visible_argument(parser)
    _add_stroke_argument(parser)
    _add_stroke_width_argument(parser)
    _add_json_argument(parser)


def _add_draw_polygon_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the ``linework draw polygon`` parser."""
    parser = subparsers.add_parser(
        "polygon",
        help="Draw a filled polygon.",
        formatter_class=_HelpFormatter,
    )
    _add_session_argument(parser)
    _add_polyline_points(parser, required=True)
    _add_label_argument(parser)
    _add_visible_argument(parser)
    _add_stroke_argument(parser)
    _add_fill_argument(parser)
    _add_stroke_width_argument(parser)
    _add_json_argument(parser)


def _add_draw_text_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``linework draw text`` parser."""
    parser = subparsers.add_parser(
        "text",
        help="Draw a text label.",
        formatter_class=_HelpFormatter,
    )
    _add_session_argument(parser)
    _add_text_geometry(parser, required=True)
    parser.add_argument("--size", type=float, help="Text size in pixels.")
    _add_text_layout_arguments(parser)
    _add_label_argument(parser)
    _add_visible_argument(parser)
    _add_fill_argument(parser)
    _add_json_argument(parser)


def _add_draw_image_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``linework draw image`` parser."""
    parser = subparsers.add_parser(
        "image",
        help="Draw an imported image.",
        formatter_class=_HelpFormatter,
    )
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
    """Add the ``linework edit line`` parser."""
    parser = subparsers.add_parser("line", help="Edit a line.", formatter_class=_HelpFormatter)
    _add_edit_common_arguments(parser)
    _add_line_geometry(parser, required=False)
    _add_stroke_argument(parser)
    _add_stroke_width_argument(parser)


def _add_edit_arrow_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``linework edit arrow`` parser."""
    parser = subparsers.add_parser("arrow", help="Edit an arrow.", formatter_class=_HelpFormatter)
    _add_edit_common_arguments(parser)
    _add_line_geometry(parser, required=False)
    _add_stroke_argument(parser)
    _add_stroke_width_argument(parser)
    _add_arrowhead_argument(parser)
    _add_arrow_size_argument(parser)


def _add_edit_rect_like_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser], *, name: str
) -> None:
    """Add an edit parser for rect-like objects."""
    article = "an" if name == "ellipse" else "a"
    parser = subparsers.add_parser(
        name,
        help=f"Edit {article} {name}.",
        formatter_class=_HelpFormatter,
    )
    _add_edit_common_arguments(parser)
    _add_rect_like_geometry(parser, required=False)
    _add_stroke_argument(parser)
    _add_fill_argument(parser)
    _add_stroke_width_argument(parser)


def _add_edit_circle_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the ``linework edit circle`` parser."""
    parser = subparsers.add_parser("circle", help="Edit a circle.", formatter_class=_HelpFormatter)
    _add_edit_common_arguments(parser)
    _add_circle_geometry(parser, required=False)
    _add_stroke_argument(parser)
    _add_fill_argument(parser)
    _add_stroke_width_argument(parser)


def _add_edit_polyline_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the ``linework edit polyline`` parser."""
    parser = subparsers.add_parser(
        "polyline",
        help="Edit a polyline.",
        formatter_class=_HelpFormatter,
    )
    _add_edit_common_arguments(parser)
    _add_polyline_points(parser, required=False)
    _add_stroke_argument(parser)
    _add_stroke_width_argument(parser)


def _add_edit_polygon_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the ``linework edit polygon`` parser."""
    parser = subparsers.add_parser(
        "polygon",
        help="Edit a polygon.",
        formatter_class=_HelpFormatter,
    )
    _add_edit_common_arguments(parser)
    _add_polyline_points(parser, required=False)
    _add_stroke_argument(parser)
    _add_fill_argument(parser)
    _add_stroke_width_argument(parser)


def _add_edit_text_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``linework edit text`` parser."""
    parser = subparsers.add_parser(
        "text",
        help="Edit a text object.",
        formatter_class=_HelpFormatter,
    )
    _add_edit_common_arguments(parser)
    _add_text_geometry(parser, required=False)
    parser.add_argument("--size", type=float, help="Text size in pixels.")
    _add_text_layout_arguments(parser)
    _add_fill_argument(parser)


def _add_edit_image_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``linework edit image`` parser."""
    parser = subparsers.add_parser(
        "image",
        help="Edit an image object.",
        formatter_class=_HelpFormatter,
    )
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

    if draw_type == "arrow":
        payload = {"x1": args.x1, "y1": args.y1, "x2": args.x2, "y2": args.y2}
        _include_optional_values(
            payload,
            args,
            "label",
            "visible",
            "stroke",
            "stroke_width",
            "arrowhead",
            "arrow_size",
        )
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

    if draw_type == "circle":
        payload = {"x": args.x, "y": args.y, "radius": args.radius}
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

    if draw_type == "polygon":
        payload = {"points": args.points}
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

    if draw_type == "text":
        payload = {"x": args.x, "y": args.y, "text": args.text}
        _include_optional_values(
            payload,
            args,
            "size",
            "anchor",
            "max_width",
            "label",
            "visible",
            "fill",
        )
        return payload

    if draw_type == "image":
        payload = {"x": args.x, "y": args.y}
        _include_optional_values(payload, args, "width", "height", "label", "visible")
        return payload

    raise ValueError(f"unsupported draw type: {draw_type}")


def _build_edit_payload(args: argparse.Namespace) -> dict[str, object]:
    """Build a convenience edit payload from CLI arguments."""
    payload: dict[str, object] = {}
    if args.id is not None:
        payload["id"] = args.id
    elif args.label is not None:
        payload["label"] = args.label
    else:
        raise ValueError("id or label must be provided for edit")
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
    elif edit_type == "arrow":
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
            "arrowhead",
            "arrow_size",
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
    elif edit_type == "circle":
        _include_optional_values(
            payload,
            args,
            "x",
            "y",
            "radius",
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
    elif edit_type == "polygon":
        _include_optional_values(
            payload,
            args,
            "label",
            "visible",
            "stroke",
            "fill",
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
            "anchor",
            "max_width",
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


def _build_delete_payload(args: argparse.Namespace) -> dict[str, object]:
    """Build a convenience delete payload from CLI arguments."""
    if args.id is not None:
        return {"id": args.id}
    if args.label is not None:
        return {"label": args.label}
    raise ValueError("id or label must be provided for delete")


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


def _batch_output_payload(
    result: BatchResult,
    *,
    exported_path: str | None = None,
    temporary_session: bool = False,
) -> dict[str, object]:
    """Serialize a batch result with optional export metadata."""
    payload: dict[str, object] = {
        "applied": result.applied,
        "failed": result.failed,
        "results": result.results,
        "scene_object_count": result.scene_object_count,
    }
    if not temporary_session:
        payload["session_path"] = result.session_path
        payload["latest_render"] = result.latest_render
    if exported_path is not None:
        payload["exported_path"] = exported_path
    return payload


def _emit_created_session_result(result: CreatedSession, *, use_json: bool) -> None:
    """Emit output for a newly created session."""
    if use_json:
        print(json.dumps(result.to_dict(), indent=2))
        return

    print(f"Created session: {result.session_id}")
    print(f"Session path: {result.session_path}")
    print(f"Canvas: {result.canvas.width}x{result.canvas.height}")
    print(f"Latest render: {result.latest_render}")


def _emit_batch_result(
    *,
    result: BatchResult,
    use_json: bool,
    exported_path: str | None = None,
    temporary_session: bool = False,
) -> int:
    """Emit output for a batch result with optional export metadata."""
    payload = _batch_output_payload(
        result,
        exported_path=exported_path,
        temporary_session=temporary_session,
    )
    if use_json:
        print(json.dumps(payload, indent=2))
        return 1 if result.failed is not None else 0

    print(f"Applied {result.applied} operation(s)")
    if result.failed:
        print(f"Failed: {result.failed['op']}: {result.failed['error']}")
    print(f"Objects: {result.scene_object_count}")
    if not temporary_session:
        print(f"Latest render: {result.latest_render}")
    if exported_path is not None:
        print(f"Exported: {exported_path}")
    return 1 if result.failed is not None else 0


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
    return "Undid last action"


# ---------------------------------------------------------------------------
# linework schema
# ---------------------------------------------------------------------------


def cmd_schema(args: argparse.Namespace) -> int:
    """Handle ``linework schema``."""
    manifest = schema_manifest()
    if args.json:
        print(json.dumps(manifest, indent=2))
        return 0

    canvas_defaults = manifest["canvas_defaults"]
    assert isinstance(canvas_defaults, dict)
    print(
        "Canvas defaults: "
        f"{canvas_defaults['width']}x{canvas_defaults['height']} "
        f"background {canvas_defaults['background']}"
    )
    print(f"Draw ops: {', '.join(operations_for_namespace('draw'))}")
    print(f"Edit ops: {', '.join(operations_for_namespace('edit'))}")
    print(f"Other ops: {', '.join(sorted(OTHER_OPERATIONS))}")
    print("Use `linework schema --json` for machine-readable payload fields and defaults.")
    return 0


# ---------------------------------------------------------------------------
# linework new
# ---------------------------------------------------------------------------


def cmd_new(args: argparse.Namespace) -> int:
    """Handle ``linework new``."""
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

    if args.watch:
        try:
            pid = _launch_detached_watcher(
                result.session_path,
                interval_ms=DEFAULT_INTERVAL_MS,
            )
        except (OSError, SessionError, WatchError) as exc:
            if args.json:
                return _error(
                    f"{exc}; session created at {result.session_path}",
                    use_json=True,
                )
            else:
                _emit_created_session_result(result, use_json=False)
                return _error(str(exc), use_json=False)
        _emit_created_session_result(result, use_json=args.json)
        if not args.json:
            print(f"Watcher opened (pid {pid})")
        return 0

    _emit_created_session_result(result, use_json=args.json)
    return 0


# ---------------------------------------------------------------------------
# linework run
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    """Handle ``linework run``."""
    try:
        operations = _read_jsonl(args.file)
    except (OSError, ValueError) as exc:
        return _error(str(exc), use_json=args.json)

    if args.session is None and args.out is None:
        return _error("either --session or --out must be provided", use_json=args.json)

    try:
        if args.session is not None:
            result = apply_batch(args.session, operations=operations)
            exported_path = export_session(args.session, out=args.out) if args.out else None
            return _emit_batch_result(
                result=result,
                use_json=args.json,
                exported_path=exported_path,
            )

        with tempfile.TemporaryDirectory(prefix="linework-run-") as temp_dir:
            temp_session = Path(temp_dir) / "session"
            created = create_session(
                session=str(temp_session),
                name="one-shot",
                width=DEFAULT_CANVAS_WIDTH,
                height=DEFAULT_CANVAS_HEIGHT,
                background=DEFAULT_CANVAS_BACKGROUND,
            )
            result = apply_batch(created.session_path, operations=operations)
            exported_path = export_session(created.session_path, out=args.out)
            return _emit_batch_result(
                result=result,
                use_json=args.json,
                exported_path=exported_path,
                temporary_session=True,
            )
    except (OSError, SessionError, SessionLockedError, SceneEngineError) as exc:
        return _error(str(exc), use_json=args.json)


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
# linework inspect
# ---------------------------------------------------------------------------


def cmd_inspect(args: argparse.Namespace) -> int:
    """Handle ``linework inspect``."""
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
    if obj_type == "arrow":
        arrowhead = str(obj.get("arrowhead", "end"))
        arrow_size = obj.get("arrow_size")
        size_text = f", size={arrow_size}" if isinstance(arrow_size, int | float) else ""
        return (
            f"({obj.get('x1')},{obj.get('y1')})→({obj.get('x2')},{obj.get('y2')}) "
            f"[{arrowhead}{size_text}]"
        )
    if obj_type in {"rect", "ellipse", "image"}:
        return f"({obj.get('x')},{obj.get('y')}) {obj.get('width')}×{obj.get('height')}"
    if obj_type == "text":
        text = str(obj.get("text", ""))
        truncated = text[:20] + "…" if len(text) > 20 else text
        anchor = str(obj.get("anchor", "left"))
        max_width = obj.get("max_width")
        width_text = f" ≤{max_width}" if isinstance(max_width, int | float) else ""
        return f'({obj.get("x")},{obj.get("y")}) "{truncated}" [{anchor}{width_text}]'
    if obj_type == "polyline":
        points = obj.get("points")
        count = len(points) if isinstance(points, list) else 0
        return f"{count} points"
    if obj_type == "polygon":
        points = obj.get("points")
        count = len(points) if isinstance(points, list) else 0
        return f"{count} points (closed)"
    return ""


# ---------------------------------------------------------------------------
# linework export
# ---------------------------------------------------------------------------


def cmd_export(args: argparse.Namespace) -> int:
    """Handle ``linework export``."""
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
# linework watch
# ---------------------------------------------------------------------------


def cmd_watch(args: argparse.Namespace) -> int:
    """Handle ``linework watch`` by launching a detached watcher process."""
    try:
        pid = _launch_detached_watcher(args.session, interval_ms=args.interval_ms)
    except (OSError, SessionError, WatchError) as exc:
        return _error(str(exc), use_json=False)
    print(f"Watcher opened (pid {pid})")
    return 0


def _cmd_watch_impl(args: argparse.Namespace) -> int:
    """Hidden command: run the watcher in the foreground (used by detached launcher)."""
    try:
        watcher = create_session_watcher(args.session, interval_ms=args.interval_ms)
    except (OSError, SessionError, WatchError) as exc:
        _write_watcher_startup_status(
            args.startup_status,
            status="error",
            error=str(exc),
        )
        return _error(str(exc), use_json=False)
    _write_watcher_startup_status(args.startup_status, status="ready")
    watcher.run()
    return 0


def _write_watcher_startup_status(
    status_path: str | None,
    *,
    status: str,
    error: str | None = None,
) -> None:
    """Write the detached watcher startup status for the parent process."""
    if status_path is None:
        return

    path = Path(status_path)
    temp_path = path.with_name(f"{path.name}.tmp")
    payload: dict[str, str] = {"status": status}
    if error is not None:
        payload["error"] = error
    temp_path.write_text(json.dumps(payload), encoding="utf-8")
    temp_path.replace(path)


def _read_watcher_startup_status(status_path: Path) -> dict[str, str] | None:
    """Read a watcher startup status file once it contains valid JSON."""
    if not status_path.is_file():
        return None

    text = status_path.read_text(encoding="utf-8").strip()
    if not text:
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        raise WatchError("watcher returned invalid startup status")

    normalized: dict[str, str] = {}
    for key in ("status", "error"):
        value = payload.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise WatchError("watcher returned invalid startup status")
        normalized[key] = value
    return normalized


def _await_watcher_startup(process: _WatchedProcess, status_path: Path) -> None:
    """Wait for the detached watcher child to confirm startup or fail."""
    deadline = time.monotonic() + _WATCHER_STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        payload = _read_watcher_startup_status(status_path)
        if payload is not None:
            if payload.get("status") == "ready":
                return
            error = payload.get("error", "watcher failed to start")
            raise WatchError(error)

        exit_code = process.poll()
        if exit_code is not None:
            raise WatchError(
                f"watcher process exited before confirming startup (exit code {exit_code})"
            )
        time.sleep(0.05)

    exit_code = process.poll()
    if exit_code is not None:
        raise WatchError(f"watcher process exited during startup (exit code {exit_code})")
    raise WatchError(
        f"watcher did not confirm startup within {_WATCHER_STARTUP_TIMEOUT_S:g} seconds"
    )


def _watch_impl_command() -> list[str]:
    """Build the command used to re-invoke linework for the hidden watcher child."""
    if sys.platform == "win32":
        return [_windows_gui_python_executable(), "-m", "linework", "_watch-impl"]

    argv0 = sys.argv[0] if sys.argv else ""
    if argv0.endswith("__main__.py") or not argv0:
        return [sys.executable, "-m", "linework", "_watch-impl"]

    if "/" in argv0 or "\\" in argv0:
        executable = str(Path(argv0).expanduser().resolve())
    else:
        executable = shutil.which(argv0) or argv0
    return [executable, "_watch-impl"]


def _windows_gui_python_executable() -> str:
    """Prefer pythonw.exe for watcher children on Windows when available."""
    executable = sys.executable
    lower = executable.lower()
    if lower.endswith("\\python.exe") or lower.endswith("/python.exe"):
        pythonw = f"{executable[:-10]}pythonw.exe"
        if Path(pythonw).is_file():
            return pythonw
    return executable


def _escape_powershell_string(value: str) -> str:
    """Escape a value for use inside a single-quoted PowerShell string literal."""
    return value.replace("'", "''")


def _ensure_windows_interactive_desktop() -> None:
    """Fail clearly when watcher launch has no access to an interactive desktop."""
    import ctypes

    DESKTOP_READOBJECTS = 0x0001

    win_dll = getattr(ctypes, "WinDLL")
    user32 = win_dll("user32", use_last_error=True)
    open_input_desktop = user32.OpenInputDesktop
    open_input_desktop.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    open_input_desktop.restype = ctypes.c_void_p
    close_desktop = user32.CloseDesktop
    close_desktop.argtypes = [ctypes.c_void_p]
    close_desktop.restype = ctypes.c_bool

    desktop = open_input_desktop(0, False, DESKTOP_READOBJECTS)
    if not desktop:
        raise WatchError("watcher requires an interactive Windows desktop session")

    close_desktop(desktop)


def _launch_detached_watcher_windows(cmd: Sequence[str]) -> _WatchedProcess:
    """Launch the watcher through PowerShell Start-Process on Windows."""
    _ensure_windows_interactive_desktop()
    if not cmd:
        raise WatchError("watcher launch command is empty")

    file_path = _escape_powershell_string(str(cmd[0]))
    argument_list = ", ".join(f"'{_escape_powershell_string(str(arg))}'" for arg in cmd[1:])
    script = (
        f"$proc = Start-Process -FilePath '{file_path}' "
        f"-ArgumentList @({argument_list}) -PassThru; "
        "[Console]::Out.Write($proc.Id)"
    )

    last_error: OSError | None = None
    for launcher in ("powershell.exe", "pwsh.exe"):
        try:
            result = subprocess.run(
                [
                    launcher,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            last_error = exc
            continue

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or str(result.returncode)
            raise WatchError(f"unable to start watcher via {launcher}: {message}")

        pid_text = result.stdout.strip()
        try:
            pid = int(pid_text)
        except ValueError as exc:
            raise WatchError(
                f"unable to determine watcher pid from {launcher}: {pid_text or 'no output'}"
            ) from exc
        return _WindowsProcess(pid)

    if last_error is not None:
        raise WatchError("unable to find PowerShell to launch watcher") from last_error
    raise WatchError("unable to launch watcher on Windows")


def _launch_detached_watcher_posix(cmd: Sequence[str]) -> _WatchedProcess:
    """Launch the watcher as a detached child on Unix-like platforms."""
    devnull = open("/dev/null", "w")  # noqa: SIM115
    process = subprocess.Popen(
        list(cmd),
        stdout=devnull,
        stderr=devnull,
        close_fds=True,
        start_new_session=True,
    )
    devnull.close()
    return process


def _launch_detached_watcher(
    session: str,
    *,
    interval_ms: int = DEFAULT_INTERVAL_MS,
) -> int:
    """Spawn a fully detached watcher subprocess that survives the parent shell.

    Validates the session exists before spawning. Returns the child PID.
    """
    from linework.storage.session import read_session_metadata

    resolved = Path(session).expanduser().resolve()
    read_session_metadata(resolved)
    with tempfile.TemporaryDirectory(prefix="linework-watch-startup-") as temp_dir:
        status_path = Path(temp_dir) / "startup.json"
        cmd = _watch_impl_command() + [
            "--session",
            str(resolved),
            "--interval-ms",
            str(interval_ms),
            "--startup-status",
            str(status_path),
        ]

        if sys.platform == "win32":
            process = _launch_detached_watcher_windows(cmd)
        else:
            # Use file-based /dev/null rather than subprocess.DEVNULL.
            # On macOS, subprocess.DEVNULL can interfere with tkinter's
            # Tcl resource discovery when stdin is redirected.
            process = _launch_detached_watcher_posix(cmd)

        _await_watcher_startup(process, status_path)
        return process.pid


# ---------------------------------------------------------------------------
# Convenience commands
# ---------------------------------------------------------------------------


def cmd_draw(args: argparse.Namespace) -> int:
    """Handle ``linework draw``."""
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
    """Handle ``linework edit``."""
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
    """Handle ``linework delete``."""
    try:
        payload = _build_delete_payload(args)
    except ValueError as exc:
        return _error(str(exc), use_json=args.json)
    return _apply_single_operation(
        session=args.session,
        op="delete",
        payload=payload,
        use_json=args.json,
        summary=_delete_summary,
    )


def cmd_undo(args: argparse.Namespace) -> int:
    """Handle ``linework undo``."""
    return _apply_single_operation(
        session=args.session,
        op="undo",
        payload=None,
        use_json=args.json,
        summary=_undo_summary,
    )
