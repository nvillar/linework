"""Command-line interface for mural."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from mural.bootstrap import BOOTSTRAP_TEXT
from mural.core.errors import SceneEngineError
from mural.storage.lock import SessionLockedError
from mural.storage.session import (
    SessionError,
    apply_batch,
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
