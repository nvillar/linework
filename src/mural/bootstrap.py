"""Bootstrap help text for the top-level CLI."""

BOOTSTRAP_TEXT = """\
mural: agent-first CLI sketch tool

Mural is a non-interactive, session-based drawing tool. Every drawing lives in
an explicit session directory. JSONL batch operations are the primary interface,
with convenience commands for common single-object edits.

Quick start:
  mural new --json                          # create a session
  mural new --watch                         # create a session and open the watcher
  mural run --session PATH --json < ops.jsonl  # draw via JSONL batch
  mural draw rect --session PATH --x 50 --y 50 --width 200 --height 100 --json
  mural draw image --session PATH --source ./diagram.png --x 40 --y 30 --json
  mural watch --session PATH                # open the read-only watcher
  mural inspect --session PATH --json       # read the scene back
  mural export --session PATH --out out.png # get the PNG

JSONL format (pipe to mural run --session PATH --json):
  {"op":"draw.rect","payload":{"x":50,"y":50,"width":200,"height":100,"fill":"#E8E8E8","label":"box"}}
  {"op":"draw.text","payload":{"x":80,"y":90,"text":"Hello","size":20,"fill":"#000000"}}
  {"op":"draw.line","payload":{"x1":0,"y1":0,"x2":200,"y2":100,"stroke":"#333333"}}
  {"op":"edit.rect","payload":{"id":"obj_000001","fill":"#CCCCCC"}}
  {"op":"delete","payload":{"id":"obj_000002"}}
  {"op":"undo","payload":{}}

Primitives: line, rect, ellipse, polyline, text, image
Operations: draw.*, edit.*, delete, undo
IDs are auto-assigned if omitted from draw operations.

Commands:
  mural new          Create a new session
  mural run          Apply JSONL operations (primary interface)
  mural inspect      Read current scene state
  mural export       Export PNG to a path
  mural watch        Open a read-only watcher window
  mural draw         Draw a single object (line, rect, ellipse, polyline, text, image)
  mural edit         Edit a single object (line, rect, ellipse, polyline, text, image)
  mural delete       Delete a single object (convenience)
  mural undo         Undo last operation (convenience)

Mutation commands accept --json and --session PATH.

Help:
  mural --help
  mural run --help
  mural new --help
"""
