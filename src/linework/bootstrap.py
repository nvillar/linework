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
    "Use `linework new` once for a persistent session, then keep reusing that "
    "same session path for iterative changes with draw/edit/delete commands. "
    "Use `linework watch` to open a live watcher for the user."
)

_SCHEMA_DISCOVERY_COMMANDS = (
    ("linework schema", "quick overview"),
    ("linework schema draw.arrow", "detailed one-op reference"),
    ("linework schema --json draw.arrow", "exact JSON for one op"),
    ("linework schema --json", "full manifest"),
)

_WORKFLOW_GUIDANCE_COMMANDS = (
    ("linework new --name idea-board", "create one persistent session to reuse"),
    ("linework watch --session PATH", "open a live watcher for the user"),
    ("linework draw rect --session PATH --x 50 --y 50 ...", "draw objects into that session"),
    ("linework inspect --session PATH --json", "read the current scene in that session"),
    ("linework export --session PATH --output out.png", "export from that same session"),
    ("linework new --file ops.jsonl --name idea-board", "create and seed a reusable session"),
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
Every drawing lives in an explicit session directory. Create one session, then
keep using the same --session PATH for all draw/edit/delete/inspect/export work.
{_DEFAULTS_LINE}
{SCHEMA_DISCOVERY_SUMMARY}
{WORKFLOW_GUIDANCE_SUMMARY}

Golden path:
  1. Discover capabilities
{format_schema_discovery_commands(indent="     ")}

  2. Pick a workflow
{format_workflow_guidance_commands(indent="     ")}

  3. Create one session and keep reusing it
      linework new --name idea-board --json

  4. Open a watcher for the user (if they want to see it live)
      linework watch --session PATH

  5. Draw objects into that session
      linework draw rect --session PATH --x 50 --y 50 --width 200 --height 100 --json
      linework draw text --session PATH --x 50 --y 50 --width 200 --height 100 --text "Hello"

  6. Inspect the scene to discover IDs and tags before editing
      linework inspect --session PATH --json

  7. Edit or delete one object
      linework edit rect --session PATH --id obj_000001 --fill "#CCE5FF" --json
      linework delete --session PATH --tag note-box --json

  8. Export from that same session
      linework export --session PATH --output out.png

JSONL reference (for linework new --file ops.jsonl or --stdin):
  {{"op":"draw.line","payload":{{"x1":0,"y1":0,"x2":200,"y2":100}}}}
  {{"op":"draw.arrow","payload":{{"x1":20,"y1":140,"x2":180,"y2":140,"arrowhead":"both","arrow_size":18}}}}
  {{"op":"draw.rect","payload":{{"x":50,"y":50,"width":200,"height":100,"fill":"#E8E8E8","tag":"box"}}}}
  {{"op":"draw.ellipse","payload":{{"x":280,"y":50,"width":120,"height":80,"fill":"#D9F2E6"}}}}
  {{"op":"draw.circle","payload":{{"x":430,"y":50,"radius":35,"fill":"#FDE68A"}}}}
  {{"op":"draw.polyline","payload":{{"points":[[20,180],[80,150],[140,210]],"stroke":"#333333"}}}}
  {{"op":"draw.polygon","payload":{{"points":[[220,180],[300,120],[360,210]],"fill":"#FF6666"}}}}
  {{"op":"draw.text","payload":{{"x":50,"y":50,"width":200,"height":100,"text":"Hello","size":24}}}}
  {{"op":"draw.image","payload":{{"x":420,"y":40,"asset_path":"assets/reference.png"}}}}
  {{"op":"edit.rect","payload":{{"id":"obj_000001","fill":"#CCCCCC"}}}}
  {{"op":"delete","payload":{{"tag":"box"}}}}
  {{"op":"undo","payload":{{}}}}

Primitives: line, arrow, rect, ellipse, circle, polyline, polygon, text, image
Operations: draw.*, edit.*, delete, undo, schema
IDs are auto-assigned if omitted from draw operations. Undo reverses the last
action; a seeded batch (via `linework new --file/--stdin`) undoes as one action.
`draw.circle` and `edit.circle` are convenience aliases stored as ellipses.

Selection:
  - `inspect` is the read interface for finding object IDs and tags.
  - `tag` is hidden selector metadata, not visible diagram text.
  - Use /-separated tag prefixes (e.g. house/wall, house/roof) to group
    related objects for filtering and bulk operations.
  - `edit` and `delete` accept `--id`, and `delete` also accepts a unique tag.
  - JSONL `delete` accepts `tag` instead of `id`.
  - For `edit`, omitting `id` makes `tag` act as the selector, so use `id` when
    you need to retag an object.

Commands:
  linework schema       Print compact overview, one-op reference, or full manifest
  linework new          Create a new session (optionally seeded from JSONL)
  linework sessions     List sessions or clean up old ones
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
  linework new --help
  linework draw rect --help
"""
