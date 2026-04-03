"""Command-line interface for mural."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from mural.bootstrap import BOOTSTRAP_TEXT
from mural.storage.lock import SessionLockedError
from mural.storage.session import SessionError, create_session


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
    new_parser.add_argument(
        "--watch",
        action="store_true",
        help="Open a watcher after creating the session.",
    )
    new_parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output for the created session.",
    )
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
        return run_new(args)

    parser.print_help()
    return 0


def run_new(args: argparse.Namespace) -> int:
    """Handle `mural new`."""
    if args.watch:
        print("error: --watch is not implemented yet", file=sys.stderr)
        return 2

    try:
        created_session = create_session(
            session=args.session,
            name=args.name,
            width=args.width,
            height=args.height,
            background=args.background,
        )
    except (OSError, SessionError, SessionLockedError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(created_session.to_dict(), indent=2))
        return 0

    print(f"Created session: {created_session.session_id}")
    print(f"Session path: {created_session.session_path}")
    print(f"Canvas: {created_session.canvas.width}x{created_session.canvas.height}")
    print(f"Latest render: {created_session.latest_render}")
    return 0
