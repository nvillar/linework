"""Bootstrap help text for the top-level CLI."""

from __future__ import annotations

from linework.constants import (
    DEFAULT_CANVAS_BACKGROUND,
    DEFAULT_CANVAS_HEIGHT,
    DEFAULT_CANVAS_WIDTH,
)

_DEFAULTS_LINE = (
    f"Defaults: canvas {DEFAULT_CANVAS_WIDTH}x{DEFAULT_CANVAS_HEIGHT}, "
    f"background {DEFAULT_CANVAS_BACKGROUND}."
)

SCHEMA_DISCOVERY_SUMMARY = (
    "Start with `linework schema` for a compact capability overview. "
    "Use `linework schema OP` to dig into one operation as needed. "
    "Use `linework schema --json [OP]` for exact JSON field metadata, or "
    "`linework schema --json` for the full manifest."
)

WORKFLOW_GUIDANCE_SUMMARY = (
    "Use `linework new` for persistent sessions. "
    "Use `linework watch` to open a live watcher for the user. "
    "Use `linework run --out` for disposable headless exports."
)

_SCHEMA_DISCOVERY_COMMANDS = (
    ("linework schema", "quick overview"),
    ("linework schema draw.arrow", "detailed one-op reference"),
    ("linework schema --json draw.arrow", "exact JSON for one op"),
    ("linework schema --json", "full manifest"),
)

_WORKFLOW_GUIDANCE_COMMANDS = (
    ("linework new --name idea-board", "persistent session"),
    ("linework watch --session PATH", "open a live watcher for the user"),
    ("linework new --stdin --name idea-board", "create a session from an initial batch"),
    ("linework run --file ops.jsonl --out out.png", "disposable one-shot export"),
)


def format_schema_discovery_commands(*, indent: str = "") -> str:
    """Return aligned capability-discovery commands for help text."""
    command_width = max(len(command) for command, _ in _SCHEMA_DISCOVERY_COMMANDS)
    return "\n".join(
        f"{indent}{command:<{command_width}}  # {description}"
        for command, description in _SCHEMA_DISCOVERY_COMMANDS
    )


def format_workflow_guidance_commands(*, indent: str = "") -> str:
    """Return aligned workflow-choice commands for help text."""
    command_width = max(len(command) for command, _ in _WORKFLOW_GUIDANCE_COMMANDS)
    return "\n".join(
        f"{indent}{command:<{command_width}}  # {description}"
        for command, description in _WORKFLOW_GUIDANCE_COMMANDS
    )


BOOTSTRAP_TEXT = f"""\
linework: agent-first CLI sketch tool

Linework is a non-interactive, session-based drawing tool for fast sketches.
Every drawing lives in an explicit session directory. JSONL batch operations are
the primary interface, with convenience commands for common single-object edits.
{_DEFAULTS_LINE}
{SCHEMA_DISCOVERY_SUMMARY}
{WORKFLOW_GUIDANCE_SUMMARY}

Golden path:
  1. Discover capabilities
{format_schema_discovery_commands(indent="     ")}

  2. Pick a workflow
{format_workflow_guidance_commands(indent="     ")}

  3. Create a session
     linework new --name idea-board --json

  4. Open a watcher for the user (if they want to see it live)
      linework watch --session PATH

  5. Draw via JSONL batch (primary interface)
      linework run --session PATH --json < ops.jsonl

  6. Inspect the scene to discover IDs and labels before editing
      linework inspect --session PATH --json

  7. Edit or delete one object
      linework edit rect --session PATH --id obj_000001 --fill #CCE5FF --json
      linework delete --session PATH --label note-box --json

  8. Export
      linework export --session PATH --out out.png
      linework run --file ops.jsonl --out out.png --width 1200 --height 800

JSONL reference (pipe to linework run --session PATH --json):
  {{"op":"draw.line","payload":{{"x1":0,"y1":0,"x2":200,"y2":100}}}}
  {{"op":"draw.arrow","payload":{{"x1":20,"y1":140,"x2":180,"y2":140,"arrowhead":"both","arrow_size":18}}}}
  {{"op":"draw.rect","payload":{{"x":50,"y":50,"width":200,"height":100,"fill":"#E8E8E8","label":"box"}}}}
  {{"op":"draw.ellipse","payload":{{"x":280,"y":50,"width":120,"height":80,"fill":"#D9F2E6"}}}}
  {{"op":"draw.circle","payload":{{"x":430,"y":50,"radius":35,"fill":"#FDE68A"}}}}
  {{"op":"draw.polyline","payload":{{"points":[[20,180],[80,150],[140,210]],"stroke":"#333333"}}}}
  {{"op":"draw.polygon","payload":{{"points":[[220,180],[300,120],[360,210]],"fill":"#FF6666"}}}}
  {{"op":"draw.text","payload":{{"x":50,"y":50,"width":200,"height":100,"text":"Hello","size":24}}}}
  {{"op":"draw.image","payload":{{"x":420,"y":40,"asset_path":"assets/reference.png"}}}}
  {{"op":"edit.rect","payload":{{"id":"obj_000001","fill":"#CCCCCC"}}}}
  {{"op":"delete","payload":{{"label":"box"}}}}
  {{"op":"undo","payload":{{}}}}

Primitives: line, arrow, rect, ellipse, circle, polyline, polygon, text, image
Operations: draw.*, edit.*, delete, undo, schema
IDs are auto-assigned if omitted from draw operations. Undo reverses the last
action; a successful `linework run` batch undoes as one action. `draw.circle`
and `edit.circle` are convenience aliases stored as ellipses.

Selection:
  - `inspect` is the read interface for finding object IDs and labels.
  - `edit` and `delete` accept `--id`, and `delete` also accepts a unique label.
  - JSONL `delete` accepts `label` instead of `id`.
  - For `edit`, omitting `id` makes `label` act as the selector, so use `id` when
    you need to relabel an object.

Commands:
  linework schema       Print compact overview, one-op reference, or full manifest
  linework new          Create a new session (optionally seeded from JSONL)
  linework run          Apply JSONL operations or do a one-shot export
  linework inspect      Read current scene state
  linework export       Export PNG to a path
  linework watch        Open a read-only watcher window
  linework draw         Draw a single object (line, arrow, rect, ellipse,
                        circle, polyline, polygon, text, image)
  linework edit         Edit a single object (line, arrow, rect, ellipse,
                        circle, polyline, polygon, text, image)
  linework delete       Delete a single object (convenience)
  linework undo         Undo last operation (convenience)

Mutation commands accept --json and --session PATH.

Help:
  linework --help
  linework run --help
  linework new --help
"""
