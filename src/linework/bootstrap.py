"""Bootstrap help text for the top-level CLI."""

from linework.constants import (
    DEFAULT_CANVAS_BACKGROUND,
    DEFAULT_CANVAS_HEIGHT,
    DEFAULT_CANVAS_WIDTH,
)

_DEFAULTS_LINE = (
    f"Defaults: canvas {DEFAULT_CANVAS_WIDTH}x{DEFAULT_CANVAS_HEIGHT}, "
    f"background {DEFAULT_CANVAS_BACKGROUND}. The watcher is read-only."
)

BOOTSTRAP_TEXT = f"""\
linework: agent-first CLI sketch tool

Linework is a non-interactive, session-based drawing tool for fast sketches.
Every drawing lives in an explicit session directory. JSONL batch operations are
the primary interface, with convenience commands for common single-object edits.
{_DEFAULTS_LINE}

Golden path:
  1. Discover the command surface
     linework schema --json

  2. Create a session
     linework new --name idea-board --json

  3. Draw via JSONL batch (primary interface)
     linework run --session PATH --json < ops.jsonl

  4. Inspect the scene to discover IDs and labels before editing
     linework inspect --session PATH --json

  5. Edit or delete one object
     linework edit rect --session PATH --id obj_000001 --fill #CCE5FF --json
      linework delete --session PATH --label note-box --json

  6. Watch or export
      linework watch --session PATH
      linework export --session PATH --out out.png
      linework run --file ops.jsonl --out out.png

JSONL reference (pipe to linework run --session PATH --json):
  {{"op":"draw.line","payload":{{"x1":0,"y1":0,"x2":200,"y2":100}}}}
  {{"op":"draw.arrow","payload":{{"x1":20,"y1":140,"x2":180,"y2":140,"arrowhead":"both","arrow_size":18}}}}
  {{"op":"draw.rect","payload":{{"x":50,"y":50,"width":200,"height":100,"fill":"#E8E8E8","label":"box"}}}}
  {{"op":"draw.ellipse","payload":{{"x":280,"y":50,"width":120,"height":80,"fill":"#D9F2E6"}}}}
  {{"op":"draw.circle","payload":{{"x":430,"y":50,"radius":35,"fill":"#FDE68A"}}}}
  {{"op":"draw.polyline","payload":{{"points":[[20,180],[80,150],[140,210]],"stroke":"#333333"}}}}
  {{"op":"draw.polygon","payload":{{"points":[[220,180],[300,120],[360,210]],"fill":"#FF6666"}}}}
  {{"op":"draw.text","payload":{{"x":80,"y":90,"text":"Hello","anchor":"center","max_width":160}}}}
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
  linework schema       Print supported operations and payload schema
  linework new          Create a new session
  linework run          Apply JSONL operations (primary interface)
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
