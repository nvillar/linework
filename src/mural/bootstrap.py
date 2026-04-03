"""Bootstrap help text for the top-level CLI."""

BOOTSTRAP_TEXT = """\
mural: sketch and paint ideas for agents

Mural is a non-interactive, session-based CLI for creating quick visual artifacts.
Every drawing lives in an explicit session directory and renders to a PNG preview.

Core workflow:
  1. Create a session: mural new --name idea
  2. Draw or edit objects against that session path
  3. Inspect or export the latest PNG
  4. Optionally open a read-only watcher window

Common commands:
  mural new
  mural inspect
  mural draw rect
  mural edit rect
  mural export
  mural watch
  mural run

Examples:
  mural new --name idea
  mural draw rect --session ~/.mural/sessions/<id> --x 80 --y 120 --width 300 --height 180
  mural export --session ~/.mural/sessions/<id> --out ./idea.png
  mural watch --session ~/.mural/sessions/<id>

Help:
  mural --help
  mural <command> --help

Status:
  Milestone 1 bootstrap is in progress. Core drawing commands are not implemented yet.
"""
