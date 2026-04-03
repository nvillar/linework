"""Bootstrap help text for the top-level CLI."""

BOOTSTRAP_TEXT = """\
mural: sketch and paint ideas for agents

Mural is a non-interactive, session-based CLI for creating quick visual artifacts.
Every drawing lives in an explicit session directory and renders to a PNG preview.

Currently implemented:
  mural
  mural --version
  mural new

Core workflow today:
  1. Create a session: mural new --name idea
  2. Use the printed session path or JSON output as the handle for later commands
  3. Inspect the generated session files and latest PNG in the session directory

Current command surface:
  mural new

Examples:
  mural new --name idea
  mural new --session ./idea-session --width 1600 --height 900
  mural new --name idea --background #F5F5F5
  mural new --json

Help:
  mural --help
  mural new --help

Status:
  Milestones 1, 2, and 3 are complete.
  User-facing commands currently implemented: mural, mural --version, mural new.
  Draw, edit, export, inspect, batch, and watcher commands are not implemented yet.
"""
