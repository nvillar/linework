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

from linework.bootstrap import (
    BOOTSTRAP_TEXT,
    SCHEMA_DISCOVERY_SUMMARY,
    WORKFLOW_GUIDANCE_SUMMARY,
    format_schema_discovery_commands,
    format_workflow_guidance_commands,
)
from linework.capabilities import schema_manifest, unsupported_command_message
from linework.constants import (
    ARROWHEAD_MODES,
    DEFAULT_CANVAS_BACKGROUND,
    DEFAULT_CANVAS_HEIGHT,
    DEFAULT_CANVAS_WIDTH,
    TEXT_ALIGNS,
    TEXT_VALIGNS,
)
from linework.core.commands import normalize_alias_payload
from linework.core.errors import SceneEngineError
from linework.storage.lock import SessionLockedError
from linework.storage.models import BatchResult, CreatedSession, MutationResult
from linework.storage.session import (
    SessionError,
    apply_batch,
    apply_bulk_delete,
    apply_bulk_edit,
    apply_imported_image,
    apply_mutation,
    count_auto_sessions,
    create_session,
    export_session,
    inspect_session,
    list_sessions,
    prune_sessions,
)
from linework.watch import (
    DEFAULT_INTERVAL_MS,
    WatchError,
    WatchUnavailableError,
    create_session_watcher,
)


class _HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    """CLI help formatter with defaults and preserved example layout."""


_TOP_LEVEL_EPILOG = f"""\
Orientation:
  linework                                      # rich bootstrap guide

Capability discovery:
{format_schema_discovery_commands(indent="  ")}

Workflow choice:
{format_workflow_guidance_commands(indent="  ")}

Golden path:
  Create one session and keep reusing the same --session PATH for iterative changes.
  linework new --name idea-board --json
  linework draw rect --session PATH --x 50 --y 50 --width 200 --height 100 --fill "#E8E8E8" --json
  linework inspect --session PATH --json
  linework edit rect --session PATH --id obj_000001 --fill "#CCE5FF" --json
  linework export --session PATH --output out.png
"""

_NEW_EPILOG = f"""\
Examples:
  linework new --json
  linework new --name idea-board
  linework new --file ops.jsonl --name idea-board
  cat ops.jsonl | linework new --stdin --name idea-board --json
  linework new --width {DEFAULT_CANVAS_WIDTH} --height {DEFAULT_CANVAS_HEIGHT}

After creation, reuse the printed session path for future draw/edit/export
commands instead of creating a new session for each change.

JSON output includes watch_command, watch_recommendation, inspect_command, and
export_command fields. Plaintext output strongly suggests opening a watch and
prints matching next-step hints.
"""

_SCHEMA_EPILOG = f"""\
Capability discovery:
{format_schema_discovery_commands(indent="  ")}
"""

_INSPECT_EPILOG = """\
Examples:
  linework inspect --session PATH
  linework inspect --session PATH --json

Use inspect before edit/delete to discover stable object IDs and tags.
"""

_DRAW_EPILOG = """\
Examples:
  linework draw arrow --session PATH --x1 20 --y1 40 --x2 180 --y2 40
    --arrowhead both --arrow-size 18
  linework draw rect --session PATH --x 50 --y 50 --width 200 --height 100 --fill "#E8E8E8"
  linework draw circle --session PATH --x 240 --y 60 --radius 30 --fill "#FDE68A"
  linework draw polygon --session PATH --point 220,180 --point 300,120 --point 360,210
"""

_EDIT_EPILOG = """\
Examples:
  linework edit arrow --session PATH --id obj_000001 --arrowhead both --arrow-size 18
  linework edit rect --session PATH --id obj_000001 --fill "#CCE5FF"
  linework edit rect --session PATH --tag note-box --fill "#CCE5FF"
  linework edit rect --session PATH --tag-prefix house/ --fill "#CCE5FF"

When --id is omitted, --tag selects the target. Use --id when you need to
change the object's tag.
"""

_DELETE_EPILOG = """\
Examples:
  linework delete --session PATH --id obj_000001
  linework delete --session PATH --tag note-box
  linework delete --session PATH --tag-prefix house/
"""

_UNDO_EPILOG = """\
Examples:
  linework undo --session PATH

Undo reverses the last action. A seeded batch (via `linework new --file/--stdin`)
undoes as one action.
"""

_WATCHER_STARTUP_TIMEOUT_S = 5.0
_WINDOWS_DETACHED_WATCHER_MESSAGE = (
    "cannot open watcher window: this process does not have access to the "
    "interactive desktop (detached or noninteractive context)"
)


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
            "Agent-first CLI sketch tool. "
            f"{SCHEMA_DISCOVERY_SUMMARY} "
            f"{WORKFLOW_GUIDANCE_SUMMARY} Use `inspect` to read the scene back, "
            "and `watch` for a read-only window."
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
        help="Print a capability overview, one-op reference, or full/filtered JSON manifest.",
        description=(
            "Print a compact, human-readable capability summary for fast orientation "
            "or a machine-readable JSON manifest with exact supported operations, "
            "payload fields, selectors, enums, and defaults. "
            f"{SCHEMA_DISCOVERY_SUMMARY}"
        ),
        epilog=_SCHEMA_EPILOG,
        formatter_class=_HelpFormatter,
    )
    schema_parser.add_argument("--json", action="store_true", help="Print JSON output.")
    schema_parser.add_argument(
        "operation",
        nargs="?",
        help="Optional operation name, for example draw.arrow or delete.",
    )

    # --- new ---
    new_parser = subparsers.add_parser(
        "new",
        help="Create a new linework session.",
        description=(
            "Create a new session directory with a blank render, or seed it from "
            "an initial JSONL batch via --file or --stdin. The default canvas is "
            f"{DEFAULT_CANVAS_WIDTH}x{DEFAULT_CANVAS_HEIGHT} with a "
            f"{DEFAULT_CANVAS_BACKGROUND} background. Reuse the created session "
            "path for iterative changes instead of creating a fresh session for "
            "every edit."
        ),
        epilog=_NEW_EPILOG,
        formatter_class=_HelpFormatter,
    )
    new_parser.add_argument(
        "--session",
        help="Explicit session directory path for the persistent session you will reuse.",
    )
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
        help="Canvas background color in #RRGGBB or #RRGGBBAA form. Quote the value in shells.",
    )
    new_batch_group = new_parser.add_mutually_exclusive_group()
    new_batch_group.add_argument(
        "--file",
        help="Read an initial JSONL batch from a file after creating the session.",
    )
    new_batch_group.add_argument(
        "--stdin",
        action="store_true",
        help="Read an initial JSONL batch from stdin after creating the session.",
    )
    new_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    # --- sessions ---
    sessions_parser = subparsers.add_parser(
        "sessions",
        help="List sessions or clean up old ones.",
        description=(
            "List sessions in the default sessions directory, or prune old ones. "
            "Use --prune to delete sessions older than 7 days (or a custom "
            "threshold via --older-than)."
        ),
        epilog=(
            "Examples:\n"
            "  linework sessions\n"
            "  linework sessions --prune\n"
            "  linework sessions --prune --older-than 1d\n"
        ),
        formatter_class=_HelpFormatter,
    )
    sessions_parser.add_argument(
        "--prune",
        action="store_true",
        help="Delete sessions older than the threshold.",
    )
    sessions_parser.add_argument(
        "--older-than",
        default="7d",
        help="Age threshold for pruning, e.g. 1d, 3d, 14d. (default: 7d)",
    )
    sessions_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    # --- inspect ---
    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Read current scene state.",
        description="Read the current scene state and object table for a session.",
        epilog=_INSPECT_EPILOG,
        formatter_class=_HelpFormatter,
    )
    inspect_parser.add_argument("--session", required=True, help="Session directory path.")
    inspect_parser.add_argument(
        "--tag-prefix",
        help="Show only objects whose tag starts with this prefix.",
    )
    inspect_parser.add_argument(
        "--type",
        dest="type_filter",
        help="Show only objects of this type (e.g. rect, text, arrow).",
    )
    inspect_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    # --- export ---
    export_parser = subparsers.add_parser(
        "export",
        help="Export PNG to a path.",
        description="Render the current scene to a PNG at a user-chosen path.",
        epilog="Example:\n  linework export --session PATH --output out.png\n",
        formatter_class=_HelpFormatter,
    )
    export_parser.add_argument(
        "--session",
        required=True,
        help="Existing session directory path to export from.",
    )
    export_parser.add_argument("--output", required=True, help="Output PNG path.")
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
    watch_impl_parser = subparsers.add_parser("_watch-impl", help=argparse.SUPPRESS)
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
            "Modify one existing object. Use `inspect` first to discover object IDs and tags."
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
        help="Delete objects by ID, tag, or tag prefix.",
        description=(
            "Delete one object by stable ID or unique live tag, "
            "or delete all objects matching a tag prefix."
        ),
        epilog=_DELETE_EPILOG,
        formatter_class=_HelpFormatter,
    )
    _add_session_argument(delete_parser)
    delete_parser.add_argument("--id", help="Stable object identifier.")
    delete_parser.add_argument(
        "--tag",
        help="Unique live object tag to delete when --id is omitted.",
    )
    delete_parser.add_argument(
        "--tag-prefix",
        help="Delete all objects whose tag starts with this prefix.",
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
    if len(effective_argv) == 0 or effective_argv == ["--help"] or effective_argv == ["-h"]:
        print(BOOTSTRAP_TEXT)
        return 0

    if "--points" in effective_argv:
        print(
            "error: unknown flag --points. Did you mean --point X,Y? "
            "Use --point multiple times to add points: --point 10,20 --point 30,40",
            file=sys.stderr,
        )
        return 1

    parser = build_parser()
    args = parser.parse_args(effective_argv)

    if args.version:
        from linework import __version__
        from linework.update_check import check_for_update

        print(__version__)
        hint = check_for_update(__version__)
        if hint:
            print(hint)
        return 0

    if args.command == "schema":
        return cmd_schema(args)
    if args.command == "new":
        return cmd_new(args)
    if args.command == "sessions":
        return cmd_sessions(args)
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
    parser.add_argument(
        "--session",
        required=True,
        help="Existing session directory path. Reuse the same path for iterative changes.",
    )


def _add_json_argument(parser: argparse.ArgumentParser) -> None:
    """Add the shared JSON output flag to a parser."""
    parser.add_argument("--json", action="store_true", help="Print JSON output.")


def _add_tag_argument(parser: argparse.ArgumentParser) -> None:
    """Add the optional hidden tag flag."""
    parser.add_argument(
        "--tag",
        help=(
            "Optional object tag for later selection. Use /-separated prefixes "
            "(e.g. house/wall) to group related objects for filtering and bulk operations."
        ),
    )


def _add_visible_argument(parser: argparse.ArgumentParser) -> None:
    """Add the optional visible flag."""
    parser.add_argument(
        "--visible",
        type=_parse_bool,
        help="Set object visibility (`true` or `false`).",
    )


def _add_stroke_argument(parser: argparse.ArgumentParser) -> None:
    """Add the optional stroke color flag."""
    parser.add_argument(
        "--stroke",
        help="Stroke color in #RRGGBB or #RRGGBBAA form. Quote the value in shells.",
    )


def _add_fill_argument(parser: argparse.ArgumentParser) -> None:
    """Add the optional fill color flag."""
    parser.add_argument(
        "--fill",
        help="Fill color in #RRGGBB or #RRGGBBAA form. Quote the value in shells.",
    )


def _add_stroke_width_argument(parser: argparse.ArgumentParser) -> None:
    """Add the optional stroke width flag."""
    parser.add_argument("--stroke-width", type=float, help="Stroke width in pixels.")


def _add_edit_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add shared optional fields for edit commands."""
    _add_session_argument(parser)
    parser.add_argument(
        "--id",
        help="Stable object identifier. When omitted, --tag selects the target object.",
    )
    parser.add_argument(
        "--tag",
        help="When --id is provided, set the hidden object tag. When --id is omitted, "
        "select the target by its unique live tag.",
    )
    parser.add_argument(
        "--tag-prefix",
        help="Edit all objects of this type whose tag starts with this prefix.",
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
    parser.add_argument("--x", type=float, required=required, help="Top-left x of the text box.")
    parser.add_argument("--y", type=float, required=required, help="Top-left y of the text box.")
    parser.add_argument("--width", type=float, required=required, help="Text box width in pixels.")
    parser.add_argument(
        "--height",
        type=float,
        required=required,
        help="Text box height in pixels.",
    )
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


def _add_position_delta_geometry(parser: argparse.ArgumentParser) -> None:
    """Add optional relative coordinate offsets for objects with x/y."""
    parser.add_argument("--dx", type=float, help="Relative x offset (alternative to --x).")
    parser.add_argument("--dy", type=float, help="Relative y offset (alternative to --y).")


def _add_line_delta_geometry(parser: argparse.ArgumentParser) -> None:
    """Add optional relative coordinate offsets for line/arrow endpoints."""
    parser.add_argument("--dx1", type=float, help="Relative start-x offset (alternative to --x1).")
    parser.add_argument("--dy1", type=float, help="Relative start-y offset (alternative to --y1).")
    parser.add_argument("--dx2", type=float, help="Relative end-x offset (alternative to --x2).")
    parser.add_argument("--dy2", type=float, help="Relative end-y offset (alternative to --y2).")


def _add_text_layout_arguments(parser: argparse.ArgumentParser) -> None:
    """Add optional boxed-text layout flags."""
    parser.add_argument(
        "--align",
        choices=TEXT_ALIGNS,
        help="Horizontal alignment inside the text box.",
    )
    parser.add_argument(
        "--valign",
        choices=TEXT_VALIGNS,
        help="Vertical alignment inside the text box.",
    )
    parser.add_argument(
        "--padding",
        type=float,
        help="Inner padding in pixels.",
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
    _add_tag_argument(parser)
    _add_visible_argument(parser)
    _add_stroke_argument(parser)
    _add_stroke_width_argument(parser)
    _add_json_argument(parser)


def _add_draw_arrow_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``linework draw arrow`` parser."""
    parser = subparsers.add_parser("arrow", help="Draw an arrow.", formatter_class=_HelpFormatter)
    _add_session_argument(parser)
    _add_line_geometry(parser, required=True)
    _add_tag_argument(parser)
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
    _add_tag_argument(parser)
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
    _add_tag_argument(parser)
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
    _add_tag_argument(parser)
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
    _add_tag_argument(parser)
    _add_visible_argument(parser)
    _add_stroke_argument(parser)
    _add_fill_argument(parser)
    _add_stroke_width_argument(parser)
    _add_json_argument(parser)


def _add_draw_text_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``linework draw text`` parser."""
    parser = subparsers.add_parser(
        "text",
        help="Draw boxed text.",
        formatter_class=_HelpFormatter,
    )
    _add_session_argument(parser)
    _add_text_geometry(parser, required=True)
    parser.add_argument("--size", type=float, help="Text size in pixels.")
    _add_text_layout_arguments(parser)
    _add_tag_argument(parser)
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
    _add_tag_argument(parser)
    _add_visible_argument(parser)
    _add_json_argument(parser)


def _add_edit_line_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``linework edit line`` parser."""
    parser = subparsers.add_parser("line", help="Edit a line.", formatter_class=_HelpFormatter)
    _add_edit_common_arguments(parser)
    _add_line_geometry(parser, required=False)
    _add_line_delta_geometry(parser)
    _add_stroke_argument(parser)
    _add_stroke_width_argument(parser)


def _add_edit_arrow_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``linework edit arrow`` parser."""
    parser = subparsers.add_parser("arrow", help="Edit an arrow.", formatter_class=_HelpFormatter)
    _add_edit_common_arguments(parser)
    _add_line_geometry(parser, required=False)
    _add_line_delta_geometry(parser)
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
    _add_position_delta_geometry(parser)
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
    _add_position_delta_geometry(parser)
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
        help="Edit boxed text.",
        formatter_class=_HelpFormatter,
    )
    _add_edit_common_arguments(parser)
    _add_text_geometry(parser, required=False)
    _add_position_delta_geometry(parser)
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
    _add_position_delta_geometry(parser)


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
        _include_optional_values(payload, args, "tag", "visible", "stroke", "stroke_width")
        return payload

    if draw_type == "arrow":
        payload = {"x1": args.x1, "y1": args.y1, "x2": args.x2, "y2": args.y2}
        _include_optional_values(
            payload,
            args,
            "tag",
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
            "tag",
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
            "tag",
            "visible",
            "stroke",
            "fill",
            "stroke_width",
        )
        return payload

    if draw_type == "polyline":
        payload = {"points": args.points}
        _include_optional_values(payload, args, "tag", "visible", "stroke", "stroke_width")
        return payload

    if draw_type == "polygon":
        payload = {"points": args.points}
        _include_optional_values(
            payload,
            args,
            "tag",
            "visible",
            "stroke",
            "fill",
            "stroke_width",
        )
        return payload

    if draw_type == "text":
        payload = {
            "x": args.x,
            "y": args.y,
            "width": args.width,
            "height": args.height,
            "text": args.text,
        }
        _include_optional_values(
            payload,
            args,
            "size",
            "align",
            "valign",
            "padding",
            "tag",
            "visible",
            "fill",
        )
        return payload

    if draw_type == "image":
        payload = {"x": args.x, "y": args.y}
        _include_optional_values(payload, args, "width", "height", "tag", "visible")
        return payload

    raise ValueError(f"unsupported draw type: {draw_type}")


def _build_edit_payload(args: argparse.Namespace) -> dict[str, object]:
    """Build a convenience edit payload from CLI arguments."""
    payload: dict[str, object] = {}
    if args.id is not None:
        payload["id"] = args.id
    elif args.tag is not None:
        payload["tag"] = args.tag
    else:
        raise ValueError("id or tag must be provided for edit")
    edit_type = args.edit_type

    if edit_type == "line":
        _include_optional_values(
            payload,
            args,
            "x1",
            "y1",
            "x2",
            "y2",
            "dx1",
            "dy1",
            "dx2",
            "dy2",
            "tag",
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
            "dx1",
            "dy1",
            "dx2",
            "dy2",
            "tag",
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
            "dx",
            "dy",
            "width",
            "height",
            "tag",
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
            "dx",
            "dy",
            "radius",
            "tag",
            "visible",
            "stroke",
            "fill",
            "stroke_width",
        )
    elif edit_type == "polyline":
        _include_optional_values(
            payload,
            args,
            "tag",
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
            "tag",
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
            "dx",
            "dy",
            "width",
            "height",
            "text",
            "size",
            "align",
            "valign",
            "padding",
            "tag",
            "visible",
            "fill",
        )
    elif edit_type == "image":
        _include_optional_values(
            payload,
            args,
            "x",
            "y",
            "dx",
            "dy",
            "width",
            "height",
            "tag",
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
    if args.tag is not None:
        return {"tag": args.tag}
    raise ValueError("id or tag must be provided for delete")


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


def _emit_created_session_result(result: CreatedSession, *, use_json: bool) -> None:
    """Emit output for a newly created session."""
    if use_json:
        print(json.dumps(result.to_dict(), indent=2))
        return

    print(f"Created session: {result.session_id}")
    print(f"Session path: {result.session_path}")
    print(f"Canvas: {result.canvas.width}x{result.canvas.height}")
    print(f"Latest render: {result.latest_render}")


_SESSION_CLEANUP_THRESHOLD = 10


def _new_output_payload(
    created: CreatedSession,
    *,
    batch_result: BatchResult | None = None,
    cleanup_hint: str | None = None,
) -> dict[str, object]:
    """Serialize new-session output with optional initial-batch metadata."""
    payload = created.to_dict()
    payload["watch_command"] = f"linework watch --session {created.session_path}"
    payload["watch_recommendation"] = "Open a watch for the user now so they can follow along live."
    payload["inspect_command"] = f"linework inspect --session {created.session_path}"
    payload["export_command"] = f"linework export --session {created.session_path} --output out.png"
    payload["reuse_session_hint"] = (
        "Reuse this session path for iterative draw/edit/delete/export "
        "commands instead of creating a new session."
    )
    if cleanup_hint is not None:
        payload["cleanup_hint"] = cleanup_hint
    if batch_result is not None:
        payload.update(
            {
                "applied": batch_result.applied,
                "failed": batch_result.failed,
                "results": batch_result.results,
                "scene_object_count": batch_result.scene_object_count,
            }
        )
    return payload


def _emit_new_session_result(
    *,
    created: CreatedSession,
    use_json: bool,
    batch_result: BatchResult | None = None,
    cleanup_hint: str | None = None,
) -> int:
    """Emit output for a new session, optionally seeded from an initial batch."""
    if use_json:
        payload = _new_output_payload(created, batch_result=batch_result, cleanup_hint=cleanup_hint)
        print(json.dumps(payload, indent=2))
        return 1 if batch_result is not None and batch_result.failed is not None else 0

    _emit_created_session_result(created, use_json=False)
    if batch_result is not None:
        print(f"Applied {batch_result.applied} operation(s)")
        if batch_result.failed:
            print(f"Failed: {batch_result.failed['op']}: {batch_result.failed['error']}")
        print(f"Objects: {batch_result.scene_object_count}")
    print("Recommended next step: open a watch for the user now so they can follow along live.")
    print(f"  linework watch --session {created.session_path}")
    print("Reuse this session path for iterative changes:")
    print(f"  linework draw rect --session {created.session_path} --x 50 --y 50 ... --json")
    print(f"  linework inspect --session {created.session_path} --json")
    print(f"  linework export --session {created.session_path} --output out.png")
    if cleanup_hint is not None:
        print(f"Note: {cleanup_hint}")
    return 1 if batch_result is not None and batch_result.failed is not None else 0


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


def _schema_field_names(spec: object, key: str) -> str:
    """Return a comma-separated list of field names for a schema section."""
    assert isinstance(spec, dict)
    fields = spec.get(key, {})
    assert isinstance(fields, dict)
    return ", ".join(str(name) for name in fields)


def _schema_operation_spec(manifest: dict[str, object], operation: str) -> dict[str, object] | None:
    """Return the schema entry for one operation if it exists."""
    ops = manifest["ops"]
    assert isinstance(ops, dict)
    spec = ops.get(operation)
    if not isinstance(spec, dict):
        return None
    return spec


def _schema_section_fields(spec: dict[str, object], key: str) -> dict[str, object]:
    """Return the named field section from an operation schema."""
    fields = spec.get(key, {})
    assert isinstance(fields, dict)
    return fields


def _schema_value_text(value: object) -> str:
    """Render a compact human-readable representation for schema values."""
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _schema_field_summary(field: object) -> str:
    """Render one field definition as a compact plain-text summary."""
    assert isinstance(field, dict)
    field_type = field.get("type")
    assert isinstance(field_type, str)

    details: list[str] = []
    if "default" in field:
        details.append(f"default: {_schema_value_text(field['default'])}")

    enum = field.get("enum")
    if isinstance(enum, list) and enum:
        details.append("enum: " + ", ".join(_schema_value_text(item) for item in enum))

    description = field.get("description")
    if isinstance(description, str):
        details.append(description)

    if not details:
        return field_type
    return f"{field_type} ({'; '.join(details)})"


def _schema_print_field_block(title: str, fields: dict[str, object]) -> None:
    """Print a titled block of field definitions."""
    print(title)
    if not fields:
        print("  none")
        return

    for name, field in fields.items():
        print(f"  {name}: {_schema_field_summary(field)}")


def _schema_field_default(fields: dict[str, object], name: str) -> object:
    """Return the default value for a named field."""
    field = fields[name]
    assert isinstance(field, dict)
    return field["default"]


def _schema_print_operation(operation: str, spec: dict[str, object]) -> None:
    """Print a detailed plain-text reference for one operation."""
    print(f"Operation: {operation}")

    description = spec.get("description")
    if isinstance(description, str):
        print(f"Description: {description}")

    category = spec.get("category")
    if isinstance(category, str):
        print(f"Category: {category}")

    stored_object_type = spec.get("stored_object_type")
    if isinstance(stored_object_type, str):
        print(f"Stored object type: {stored_object_type}")

    selector = spec.get("selector")
    if isinstance(selector, dict):
        print()
        print("Selector:")
        one_of = selector.get("one_of")
        if isinstance(one_of, list) and one_of:
            print("  one of: " + ", ".join(str(item) for item in one_of))
        selector_fields = selector.get("fields")
        if isinstance(selector_fields, dict):
            for name, field in selector_fields.items():
                print(f"  {name}: {_schema_field_summary(field)}")

    payload = spec.get("payload")
    if isinstance(payload, dict):
        required = _schema_section_fields(payload, "required")
        optional = _schema_section_fields(payload, "optional")
    else:
        required = _schema_section_fields(spec, "required")
        optional = _schema_section_fields(spec, "optional")

    if required or optional or not isinstance(selector, dict):
        print()
        if required or not optional:
            _schema_print_field_block("Required fields:", required)
        if optional:
            print()
            _schema_print_field_block("Optional fields:", optional)

    example = spec.get("example")
    if isinstance(example, dict):
        print()
        print("Example:")
        print("  " + json.dumps(example))


def _schema_type_summary_lines(manifest: dict[str, object]) -> list[str]:
    """Return compact one-line summaries for draw object types."""
    ops = manifest["ops"]
    assert isinstance(ops, dict)

    lines: list[str] = []
    for op, spec in ops.items():
        if not isinstance(op, str) or not op.startswith("draw."):
            continue
        object_type = op.split(".", 1)[1]
        required = _schema_field_names(spec, "required")
        optional = _schema_field_names(spec, "optional")
        lines.append(f"  {object_type:<8} draw {required} | optional {optional}")
    return lines


def cmd_schema(args: argparse.Namespace) -> int:
    """Handle ``linework schema``."""
    manifest = schema_manifest()
    if args.operation is not None:
        spec = _schema_operation_spec(manifest, args.operation)
        if spec is None:
            return _error(unsupported_command_message(args.operation), use_json=args.json)

        if args.json:
            print(
                json.dumps(
                    {
                        "schema_version": manifest["schema_version"],
                        "canvas_defaults": manifest["canvas_defaults"],
                        "ops": {args.operation: spec},
                    },
                    indent=2,
                )
            )
            return 0

        _schema_print_operation(args.operation, spec)
        return 0

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
    print()
    print("Compact overview:")
    print("  Start here for a quick capability map.")
    print("  Use the capability-discovery flow below for overview, one-op detail,")
    print("  exact JSON as needed, and the full manifest.")
    print()
    print("Types:")
    for line in _schema_type_summary_lines(manifest):
        print(line)
    print()
    line_spec = _schema_operation_spec(manifest, "draw.line")
    text_spec = _schema_operation_spec(manifest, "draw.text")
    assert line_spec is not None
    assert text_spec is not None
    line_optional = _schema_section_fields(line_spec, "optional")
    text_optional = _schema_section_fields(text_spec, "optional")
    print("Shared defaults:")
    print(
        "  visible="
        f"{_schema_value_text(_schema_field_default(line_optional, 'visible'))}, "
        "stroke="
        f"{_schema_value_text(_schema_field_default(line_optional, 'stroke'))}, "
        "stroke_width="
        f"{_schema_value_text(_schema_field_default(line_optional, 'stroke_width'))}"
    )
    print(
        "  text: size="
        f"{_schema_value_text(_schema_field_default(text_optional, 'size'))}, "
        "fill="
        f"{_schema_value_text(_schema_field_default(text_optional, 'fill'))}, "
        "align="
        f"{_schema_value_text(_schema_field_default(text_optional, 'align'))}, "
        "valign="
        f"{_schema_value_text(_schema_field_default(text_optional, 'valign'))}, "
        "padding="
        f"{_schema_value_text(_schema_field_default(text_optional, 'padding'))}"
    )
    print()
    print("Rules:")
    print("  draw.<type>  listed draw fields are required; optional fields remain optional")
    print(
        "  edit.<type>  selector(id or unique live tag) required; "
        "CLI convenience also supports --tag-prefix bulk edit"
    )
    print(
        "  delete       selector(id or unique live tag); "
        "CLI convenience also supports --tag-prefix bulk delete"
    )
    print("  undo         no payload")
    print()
    print("Special values:")
    print(
        "  colors: #RRGGBB or #RRGGBBAA "
        "(alpha-composited in stacking order; quote in shell commands)"
    )
    print(f"  arrowhead: {', '.join(ARROWHEAD_MODES)} (default: {ARROWHEAD_MODES[0]})")
    print(f"  align: {', '.join(TEXT_ALIGNS)} (default: center)")
    print(f"  valign: {', '.join(TEXT_VALIGNS)} (default: middle)")
    print()
    print("Capability discovery:")
    print(format_schema_discovery_commands(indent="  "))
    print()
    print("Notes:")
    print(
        "  use `linework inspect --session PATH --json` to discover IDs and tags before edit/delete"
    )
    print("  convenience edit/delete also accept `--tag-prefix PREFIX` for bulk actions")
    print("  `tag` is hidden selector metadata, not visible diagram text")
    print("  create one session, then keep reusing the same `--session PATH` as you iterate")
    print("  `draw.circle` / `edit.circle` are convenience aliases stored as ellipses")
    print("  `edit.image` changes placement/size only; `asset_path` is fixed after creation")
    return 0


# ---------------------------------------------------------------------------
# linework new
# ---------------------------------------------------------------------------


def cmd_new(args: argparse.Namespace) -> int:
    """Handle ``linework new``."""
    try:
        initial_batch: list[dict[str, object]] | None = None
        if args.file is not None:
            initial_batch = _read_jsonl(args.file)
        elif args.stdin:
            initial_batch = _read_jsonl(None)
    except (OSError, ValueError) as exc:
        return _error(str(exc), use_json=args.json)

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

    batch_result: BatchResult | None = None
    if initial_batch is not None:
        try:
            batch_result = apply_batch(result.session_path, operations=initial_batch)
        except (OSError, SessionError, SessionLockedError, SceneEngineError) as exc:
            return _error(str(exc), use_json=args.json)

    cleanup_hint = _check_session_cleanup_hint()

    return _emit_new_session_result(
        created=result,
        use_json=args.json,
        batch_result=batch_result,
        cleanup_hint=cleanup_hint,
    )


def _check_session_cleanup_hint() -> str | None:
    """Return a cleanup hint if there are many existing auto-created sessions."""
    try:
        session_count = count_auto_sessions()
    except OSError:
        return None
    if session_count >= _SESSION_CLEANUP_THRESHOLD:
        return (
            f"{session_count} existing sessions in the default sessions directory. "
            "Consider asking the user about running "
            "`linework sessions --prune` to clean up old sessions."
        )
    return None


# ---------------------------------------------------------------------------
# linework sessions
# ---------------------------------------------------------------------------


def _parse_older_than(value: str) -> int:
    """Parse an --older-than value like '7d' into days."""
    value = value.strip().lower()
    if value.endswith("d"):
        try:
            return int(value[:-1])
        except ValueError:
            pass
    try:
        return int(value)
    except ValueError:
        raise ValueError(
            f"invalid --older-than value: {value!r}. Use a number followed by 'd', e.g. 7d"
        ) from None


def cmd_sessions(args: argparse.Namespace) -> int:
    """Handle ``linework sessions``."""
    if args.prune:
        try:
            days = _parse_older_than(args.older_than)
        except ValueError as exc:
            return _error(str(exc), use_json=args.json)

        try:
            removed = prune_sessions(older_than_days=days)
        except OSError as exc:
            return _error(str(exc), use_json=args.json)

        if args.json:
            print(json.dumps({"pruned": len(removed), "removed": removed, "older_than_days": days}))
        else:
            if removed:
                print(f"Pruned {len(removed)} session(s) older than {days} day(s):")
                for name in removed:
                    print(f"  {name}")
            else:
                print(f"No sessions older than {days} day(s) to prune.")
        return 0

    try:
        sessions = list_sessions()
    except OSError as exc:
        return _error(str(exc), use_json=args.json)

    if args.json:
        print(json.dumps({"sessions": sessions, "count": len(sessions)}))
        return 0

    if not sessions:
        print("No sessions found.")
        return 0

    print(f"{'Name':<40} {'Age':>8}  {'Objects':>7}  Path")
    print(f"{'─' * 40} {'─' * 8}  {'─' * 7}  {'─' * 30}")
    for s in sessions:
        print(f"{s['name']:<40} {s['age']:>8}  {s['objects']:>7}  {s['path']}")
    print(f"\n{len(sessions)} session(s) total.")
    return 0


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


_INSPECT_FILTER_THRESHOLD = 30
_INSPECT_TAGGING_THRESHOLD = 50


def _tag_prefix_summary(
    objects: list[dict[str, object]],
) -> dict[str, dict[str, int]]:
    """Build a summary of object counts grouped by tag prefix and type.

    Tags are split on the first ``/``. Objects without tags are counted under
    the empty string key.  Returns an empty dict when no objects have tags.

    Each prefix maps to a dict of ``{type: count}``, e.g.
    ``{"house/": {"rect": 6, "polygon": 1}, "": {"line": 2}}``.
    """
    counts: dict[str, dict[str, int]] = {}
    has_any_tag = False
    for obj in objects:
        tag = obj.get("tag")
        obj_type = str(obj.get("type", "unknown"))
        if isinstance(tag, str) and tag:
            has_any_tag = True
            slash = tag.find("/")
            prefix = tag[: slash + 1] if slash >= 0 else tag
        else:
            prefix = ""
        type_counts = counts.setdefault(prefix, {})
        type_counts[obj_type] = type_counts.get(obj_type, 0) + 1
    return counts if has_any_tag else {}


def _filter_objects(
    objects: list[dict[str, object]],
    *,
    tag_prefix: str | None,
    type_filter: str | None,
) -> list[dict[str, object]]:
    """Filter inspect objects by tag prefix and/or type."""
    filtered = objects
    if tag_prefix is not None:
        filtered = [
            obj
            for obj in filtered
            if isinstance(obj.get("tag"), str) and str(obj["tag"]).startswith(tag_prefix)
        ]
    if type_filter is not None:
        filtered = [obj for obj in filtered if str(obj.get("type", "")) == type_filter]
    return filtered


def _inspect_hints(
    *,
    total: int,
    shown: int,
    tagged_count: int,
    is_filtered: bool,
    tag_prefix: str | None,
    session: str,
) -> list[str]:
    """Build contextual nudge strings for inspect output."""
    hints: list[str] = []
    if is_filtered and shown > 1 and tag_prefix is not None:
        hints.append(
            f"To delete all {shown} matching objects: "
            f"linework delete --session {session} --tag-prefix {tag_prefix}"
        )
        hints.append(
            f"To bulk-edit matching objects (scoped by type): "
            f'linework edit TYPE --session {session} --tag-prefix {tag_prefix} --fill "#RRGGBB"'
        )
    if not is_filtered and total > _INSPECT_FILTER_THRESHOLD:
        hints.append(
            "Tip: use --tag-prefix PREFIX to filter, or --type TYPE to show only one object type."
        )
    if total > _INSPECT_TAGGING_THRESHOLD and tagged_count < total // 2:
        hints.append(
            f"Tip: only {tagged_count} of {total} objects have tags. "
            "Consistent tags (e.g. sky/cloud-1, ground/tree-2) enable "
            "--tag-prefix filtering and bulk operations."
        )
    return hints


def cmd_inspect(args: argparse.Namespace) -> int:
    """Handle ``linework inspect``."""
    try:
        result = inspect_session(args.session)
    except (OSError, SessionError) as exc:
        return _error(str(exc), use_json=args.json)

    tag_prefix: str | None = getattr(args, "tag_prefix", None)
    type_filter: str | None = getattr(args, "type_filter", None)
    is_filtered = tag_prefix is not None or type_filter is not None

    all_objects = result.objects or []
    total = len(all_objects)
    tagged_count = sum(1 for obj in all_objects if obj.get("tag"))

    if is_filtered:
        shown_objects = _filter_objects(all_objects, tag_prefix=tag_prefix, type_filter=type_filter)
    else:
        shown_objects = all_objects
    shown = len(shown_objects)

    hints = _inspect_hints(
        total=total,
        shown=shown,
        tagged_count=tagged_count,
        is_filtered=is_filtered,
        tag_prefix=tag_prefix,
        session=args.session,
    )

    prefix_summary = _tag_prefix_summary(all_objects)

    if args.json:
        payload = result.to_dict()
        if is_filtered:
            payload["objects"] = shown_objects
            payload["object_count"] = shown
            payload["total_object_count"] = total
        if prefix_summary:
            payload["tag_prefixes"] = prefix_summary
        if hints:
            payload["hints"] = hints
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Session: {result.session_id}")
    print(f"Path: {result.session_path}")
    print(f"Canvas: {result.canvas.width}x{result.canvas.height}")
    print(f"Background: {result.canvas.background}")
    if is_filtered:
        print(f"Objects: {shown} of {total} (filtered)")
    else:
        print(f"Objects: {result.object_count}")
    print(f"Latest render: {result.latest_render}")

    if prefix_summary:
        named_parts: list[str] = []
        for prefix, type_counts in prefix_summary.items():
            if not prefix:
                continue
            total_count = sum(type_counts.values())
            type_detail = ", ".join(f"{c} {t}" for t, c in type_counts.items())
            named_parts.append(f"{prefix} ({total_count}: {type_detail})")
        untagged_counts = prefix_summary.get("", {})
        untagged_total = sum(untagged_counts.values())
        parts = named_parts + ([f"{untagged_total} untagged"] if untagged_total else [])
        print(f"Tag groups: {', '.join(parts)}")

    if shown_objects:
        print()
        print(f"{'ID':<14} {'Type':<10} {'Tag':<16} {'Vis':>3}  Geometry")
        print(f"{'─' * 14} {'─' * 10} {'─' * 16} {'─' * 3}  {'─' * 30}")
        for obj in shown_objects:
            obj_id = str(obj.get("id", ""))
            obj_type = str(obj.get("type", ""))
            tag = str(obj.get("tag", "")) if obj.get("tag") else ""
            visible = "yes" if obj.get("visible", True) else "no"
            geometry = _format_geometry(obj)
            print(f"{obj_id:<14} {obj_type:<10} {tag:<16} {visible:>3}  {geometry}")

    for hint in hints:
        print(f"\n{hint}")

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
        align = str(obj.get("align", "center"))
        valign = str(obj.get("valign", "middle"))
        padding = obj.get("padding")
        padding_text = ""
        if isinstance(padding, int | float) and padding != 0:
            padding_text = f", pad={padding}"
        return (
            f"({obj.get('x')},{obj.get('y')}) {obj.get('width')}×{obj.get('height')} "
            f'"{truncated}" [{align}/{valign}{padding_text}]'
        )
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
        exported_path = export_session(args.session, output=args.output)
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
    except (OSError, SessionError) as exc:
        return _error(str(exc), use_json=False)
    except WatchUnavailableError as exc:
        print(
            f"Watcher unavailable in this environment: {exc}",
            file=sys.stderr,
        )
        print(
            "The watcher requires a graphical desktop session. "
            "Ask the user to run this command in their terminal:",
            file=sys.stderr,
        )
        print(
            f"linework watch --session {args.session}",
            file=sys.stderr,
        )
        return 1
    except WatchError as exc:
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
            error_kind="unavailable" if isinstance(exc, WatchUnavailableError) else None,
        )
        return _error(str(exc), use_json=False)

    if args.startup_status:
        visibility_confirmed = False

        def _on_visible() -> None:
            nonlocal visibility_confirmed
            visibility_confirmed = True
            _write_watcher_startup_status(args.startup_status, status="ready")

        watcher.run(on_visible=_on_visible)

        if not visibility_confirmed:
            reason = (
                "watcher window was created but never became visible; "
                "the environment may lack GUI display access"
            )
            _write_watcher_startup_status(
                args.startup_status,
                status="error",
                error=reason,
                error_kind="unavailable",
            )
            return _error(reason, use_json=False)
    else:
        watcher.run()

    return 0


def _write_watcher_startup_status(
    status_path: str | None,
    *,
    status: str,
    error: str | None = None,
    error_kind: str | None = None,
) -> None:
    """Write the detached watcher startup status for the parent process."""
    if status_path is None:
        return

    path = Path(status_path)
    temp_path = path.with_name(f"{path.name}.tmp")
    payload: dict[str, str] = {"status": status}
    if error is not None:
        payload["error"] = error
    if error_kind is not None:
        payload["error_kind"] = error_kind
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
    for key in ("status", "error", "error_kind"):
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
            if payload.get("error_kind") == "unavailable":
                raise WatchUnavailableError(error)
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


def _windows_user_object_name(handle: int, *, object_type: str) -> str:
    """Read the Win32 object name for a window-station or desktop handle."""
    import ctypes

    UOI_NAME = 2

    win_dll = getattr(ctypes, "WinDLL")
    user32 = win_dll("user32", use_last_error=True)
    get_user_object_information = user32.GetUserObjectInformationW
    get_user_object_information.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    get_user_object_information.restype = ctypes.c_bool

    needed = ctypes.c_uint32()
    get_user_object_information(handle, UOI_NAME, None, 0, ctypes.byref(needed))
    if needed.value == 0:
        raise WatchUnavailableError(f"unable to inspect Windows {object_type} name")

    wchar_size = ctypes.sizeof(ctypes.c_wchar)
    char_count = max(1, (needed.value + wchar_size - 1) // wchar_size)
    buffer = ctypes.create_unicode_buffer(char_count)
    if not get_user_object_information(
        handle,
        UOI_NAME,
        buffer,
        ctypes.sizeof(buffer),
        ctypes.byref(needed),
    ):
        raise WatchUnavailableError(f"unable to inspect Windows {object_type} name")

    name = buffer.value
    if not name:
        raise WatchUnavailableError(f"unable to inspect Windows {object_type} name")
    return name


def _current_windows_window_station_name() -> str:
    """Return the current process window-station name."""
    import ctypes

    win_dll = getattr(ctypes, "WinDLL")
    user32 = win_dll("user32", use_last_error=True)
    get_process_window_station = user32.GetProcessWindowStation
    get_process_window_station.argtypes = []
    get_process_window_station.restype = ctypes.c_void_p

    handle = get_process_window_station()
    if not handle:
        raise WatchUnavailableError("unable to inspect current Windows window station")
    return _windows_user_object_name(handle, object_type="window station")


def _current_windows_thread_desktop_name() -> str:
    """Return the current thread desktop name."""
    import ctypes

    win_dll = getattr(ctypes, "WinDLL")
    user32 = win_dll("user32", use_last_error=True)
    kernel32 = win_dll("kernel32", use_last_error=True)
    get_thread_desktop = user32.GetThreadDesktop
    get_thread_desktop.argtypes = [ctypes.c_uint32]
    get_thread_desktop.restype = ctypes.c_void_p
    get_current_thread_id = kernel32.GetCurrentThreadId
    get_current_thread_id.argtypes = []
    get_current_thread_id.restype = ctypes.c_uint32

    handle = get_thread_desktop(get_current_thread_id())
    if not handle:
        raise WatchUnavailableError("unable to inspect current Windows desktop")
    return _windows_user_object_name(handle, object_type="desktop")


def _input_windows_desktop_name() -> str:
    """Return the active input desktop name."""
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
        raise WatchUnavailableError("watcher requires an interactive Windows desktop session")

    try:
        return _windows_user_object_name(desktop, object_type="desktop")
    finally:
        close_desktop(desktop)


def _ensure_windows_interactive_desktop() -> None:
    """Fail clearly when watcher launch has no access to an interactive desktop."""
    if _current_windows_window_station_name() != "WinSta0":
        raise WatchUnavailableError(_WINDOWS_DETACHED_WATCHER_MESSAGE)

    current_desktop = _current_windows_thread_desktop_name()
    input_desktop = _input_windows_desktop_name()
    if current_desktop != input_desktop:
        raise WatchUnavailableError(_WINDOWS_DETACHED_WATCHER_MESSAGE)


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
            # Tcl resource discovery when stdin is redirected.  See
            # _ensure_tcl_library() in linework/watch/__init__.py for the
            # full explanation of the venv-symlink + stdin=/dev/null bug.
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
    tag_prefix: str | None = getattr(args, "tag_prefix", None)
    if tag_prefix is not None:
        return _cmd_bulk_edit(args, tag_prefix=tag_prefix)
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


def _cmd_bulk_edit(args: argparse.Namespace, *, tag_prefix: str) -> int:
    """Handle ``linework edit TYPE --tag-prefix``."""
    # Build edit payload without the selector (id/tag) — bulk edit supplies IDs internally.
    edit_payload: dict[str, object] = {}
    edit_type = args.edit_type

    if edit_type in {"line", "arrow"}:
        _include_optional_values(
            edit_payload,
            args,
            "x1",
            "y1",
            "x2",
            "y2",
            "dx1",
            "dy1",
            "dx2",
            "dy2",
            "stroke",
            "stroke_width",
            "visible",
        )
        if edit_type == "arrow":
            _include_optional_values(edit_payload, args, "arrowhead", "arrow_size")
    elif edit_type in {"rect", "ellipse"}:
        _include_optional_values(
            edit_payload,
            args,
            "x",
            "y",
            "dx",
            "dy",
            "width",
            "height",
            "stroke",
            "fill",
            "stroke_width",
            "visible",
        )
    elif edit_type == "circle":
        _include_optional_values(
            edit_payload,
            args,
            "x",
            "y",
            "dx",
            "dy",
            "radius",
            "stroke",
            "fill",
            "stroke_width",
            "visible",
        )
        edit_payload = normalize_alias_payload(op="edit.circle", payload=edit_payload)
    elif edit_type == "polyline":
        _include_optional_values(edit_payload, args, "stroke", "stroke_width", "visible")
        if getattr(args, "points", None) is not None:
            edit_payload["points"] = args.points
    elif edit_type == "polygon":
        _include_optional_values(
            edit_payload,
            args,
            "stroke",
            "fill",
            "stroke_width",
            "visible",
        )
        if getattr(args, "points", None) is not None:
            edit_payload["points"] = args.points
    elif edit_type == "text":
        _include_optional_values(
            edit_payload,
            args,
            "x",
            "y",
            "dx",
            "dy",
            "width",
            "height",
            "text",
            "size",
            "align",
            "valign",
            "padding",
            "fill",
            "visible",
        )
    elif edit_type == "image":
        _include_optional_values(
            edit_payload,
            args,
            "x",
            "y",
            "dx",
            "dy",
            "width",
            "height",
            "visible",
        )

    if not edit_payload:
        return _error("at least one field must be provided for bulk edit", use_json=args.json)

    # Map circle type to stored ellipse type for matching.
    stored_type = "ellipse" if edit_type == "circle" else edit_type

    # Pre-inspect to count skipped objects for transparent reporting.
    try:
        inspect_result = inspect_session(args.session)
    except (OSError, SessionError) as exc:
        return _error(str(exc), use_json=args.json)

    prefix_objects = [
        obj
        for obj in (inspect_result.objects or [])
        if isinstance(obj.get("tag"), str) and str(obj["tag"]).startswith(tag_prefix)
    ]
    total_in_prefix = len(prefix_objects)
    skipped_types: dict[str, int] = {}
    for obj in prefix_objects:
        obj_type = str(obj.get("type", ""))
        if obj_type != stored_type:
            skipped_types[obj_type] = skipped_types.get(obj_type, 0) + 1

    try:
        result = apply_bulk_edit(
            args.session,
            tag_prefix=tag_prefix,
            object_type=stored_type,
            edit_payload=edit_payload,
        )
    except (OSError, SessionError, SessionLockedError, SceneEngineError) as exc:
        return _error(str(exc), use_json=args.json)

    if args.json:
        payload: dict[str, object] = {
            "applied": result.applied,
            "failed": result.failed,
            "results": result.results,
            "session_path": result.session_path,
            "scene_object_count": result.scene_object_count,
            "latest_render": result.latest_render,
            "tag_prefix": tag_prefix,
            "total_in_prefix": total_in_prefix,
        }
        if skipped_types:
            payload["skipped_types"] = skipped_types
        print(json.dumps(payload, indent=2))
        return 1 if result.failed is not None else 0

    if result.applied == 0:
        print(f"No {edit_type} objects found matching tag prefix '{tag_prefix}'")
    else:
        skipped_total = sum(skipped_types.values())
        skipped_msg = ""
        if skipped_total:
            type_list = ", ".join(f"{v} {k}" for k, v in skipped_types.items())
            skipped_msg = f" Skipped {skipped_total} non-{edit_type} object(s) ({type_list})."
        print(
            f"Edited {result.applied} {edit_type} object(s) matching tag prefix "
            f"'{tag_prefix}'.{skipped_msg} "
            "Undo will reverse all as one action."
        )
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    """Handle ``linework delete``."""
    tag_prefix: str | None = getattr(args, "tag_prefix", None)
    if tag_prefix is not None:
        return _cmd_bulk_delete(args, tag_prefix=tag_prefix)
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


def _cmd_bulk_delete(args: argparse.Namespace, *, tag_prefix: str) -> int:
    """Handle ``linework delete --tag-prefix``."""
    try:
        result = apply_bulk_delete(args.session, tag_prefix=tag_prefix)
    except (OSError, SessionError, SessionLockedError, SceneEngineError) as exc:
        return _error(str(exc), use_json=args.json)

    if args.json:
        payload = {
            "applied": result.applied,
            "failed": result.failed,
            "results": result.results,
            "session_path": result.session_path,
            "scene_object_count": result.scene_object_count,
            "latest_render": result.latest_render,
            "tag_prefix": tag_prefix,
        }
        print(json.dumps(payload, indent=2))
        return 1 if result.failed is not None else 0

    if result.applied == 0:
        print(f"No objects found matching tag prefix '{tag_prefix}'")
    else:
        print(
            f"Deleted {result.applied} object(s) matching tag prefix '{tag_prefix}'. "
            "Undo will restore all as one action."
        )
    return 0


def cmd_undo(args: argparse.Namespace) -> int:
    """Handle ``linework undo``."""
    return _apply_single_operation(
        session=args.session,
        op="undo",
        payload=None,
        use_json=args.json,
        summary=_undo_summary,
    )
