"""Command-line interface for mural."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from mural.bootstrap import BOOTSTRAP_TEXT


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the top-level CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from mural import __version__

        print(__version__)
        return 0

    if argv is None:
        print(BOOTSTRAP_TEXT)
        return 0

    if len(argv) == 0:
        print(BOOTSTRAP_TEXT)
        return 0

    parser.print_help()
    return 0
