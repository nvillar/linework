# Linework Specification

This document is the product definition and source of truth for `linework`.

Development workflow, milestone decomposition, and implementation progress are tracked in `DEVELOPMENT.md`.

## 1. Purpose

`linework` is an agent-first CLI tool for quickly drawing and sketching visual ideas.

It is intended to serve as "MS Paint for agents":

- It must support fast, non-interactive, scriptable drawing from the command line.
- It must support a headless workflow suitable for automated agent loops.
- It must optionally open a minimal live watcher window so a user can see drawing progress.
- It must produce portable session artifacts that can be exported, shared, inspected, and passed into a vision model by external tooling.

The MVP is a retained-scene sketch tool, not a full paint program and not a full diagramming system.

## 2. Product Principles

The implementation must follow these principles:

- Agent-first: the primary interface is JSONL batch mode; every design decision must favor automated callers.
- Non-interactive: the tool must never rely on interactive prompts.
- Self-describing: `linework` invoked with no arguments must print a rich bootstrap guide that teaches the JSONL workflow and exit.
- Explicit state: commands must target an explicit session path. There is no implicit "current session" for normal operations.
- Portable artifacts: session directories must be self-contained and copyable.
- Deterministic behavior: the same session state and command log must re-render the same PNG output on a supported platform.
- Small, composable surface area: the CLI must have a compact set of verbs and a consistent object model.

## 3. Technology and Packaging

### 3.1 Language and runtime

- The implementation language is Python.
- Python environments, dependencies, and execution must always be managed with `uv`.
- Local development must use a project-local, `uv`-managed virtual environment at `.venv/`.
- The system Python interpreter must never be used directly for `linework` development, tooling, tests, or execution.

### 3.2 Installation target

The package must be installable as a tool from GitHub using `uv tool install`, in the form:

```bash
uv tool install --no-cache --reinstall-package linework git+https://github.com/nvillar/linework.git
```

That implies:

- a standard `pyproject.toml`
- a console script entry point named `linework`
- a `src/` layout

### 3.3 GUI stack

The MVP watcher window must use the Python standard library GUI stack:

- `tkinter`
- `ttk`

The watcher must degrade cleanly with a clear error if the active Python build lacks `tkinter`.

### 3.4 Rendering stack

The MVP raster renderer must use `Pillow`.

### 3.5 Font strategy

The MVP must bundle exactly one redistributable default font file with the package so that text rendering is predictable across platforms and regression tests can rely on deterministic output.

The bundled font becomes part of the rendering contract for the MVP.

## 4. Target MVP Scope

### 4.1 In scope

- Session-oriented CLI
- Explicit session paths
- Rich no-argument bootstrap output
- Standard help system
- Tiered capability discovery via `linework schema` (overview), `linework schema OP` (one-op detail), and `linework schema --json` (full manifest)
- Human-readable default output
- `--json` machine-readable output with structured errors
- Single-canvas sessions
- Retained scene model
- Canonical append-only command log
- Derived scene snapshot
- Auto-rendered latest PNG
- PNG export
- Draw primitives:
  - line
  - arrow
  - rectangle
  - ellipse
  - circle convenience alias
  - polyline
  - polygon
  - text
  - image placement
- Text anchor and wrapping controls
- Object mutation by stable ID or unique live label
- Object labels as metadata
- Object visibility
- Delete
- Whole-action undo
- JSONL batch mode as the primary agent interface
- One-shot batch export via `linework run --out`
- Read-only watcher window
- Session portability
- Single-writer locking

### 4.2 Explicitly out of scope for the MVP

- Built-in vision API integration
- SVG export
- PDF export
- Rich brushes
- Bucket fill tool
- Eraser tool
- Layers
- Grouping
- Rich text
- Z-order editing commands
- Multi-canvas or multi-page sessions
- Interactive prompts
- In-window editing
- Dedicated `replay` command
- Dedicated `history` command

### 4.3 Future directions

Deferred ideas that remain explicitly out of scope for the current release:

- canvas resize / fit-to-contents
- grouping / hierarchical edits
- auto-layout helpers
- higher-level composite objects
- themes / reusable styles

## 5. Architecture Overview

The system is composed of five layers:

1. CLI layer
2. Core session and scene engine
3. Raster renderer
4. Session storage and artifact management
5. Optional watcher UI

Source layout:

```text
src/linework/
  cli.py
  __main__.py
  constants.py
  config.py
  bootstrap.py
  core/
  render/
  storage/
  watch/
  assets/
tests/
```

The core engine must remain usable without the watcher.

The watcher must consume session artifacts generated by the core system rather than introducing a second source of truth.

## 6. Session Model

### 6.1 Session operating model

`linework` uses a stateful session CLI model.

- A session is the unit of persistence.
- A session corresponds to exactly one canvas.
- Commands operate on an explicit session path.
- A session is stored as a directory.

### 6.2 Session path rules

- Normal commands must target a session via `--session PATH`.
- `PATH` points to a session directory, not a single file.
- There is no implicit current session for normal commands.
- `linework new` is the only command that may create a new session directory automatically.

### 6.3 Default session creation location

If `linework new` is called without `--session PATH`, it must create the session under:

```text
~/.linework/sessions/
```

using the naming convention:

```text
YYYYMMDD-HHMMSS-slug
```

where `slug` comes from `--name` when provided, or a generated default slug when omitted.

If `--name` is omitted, the default slug is `session`.

When `--name` is provided, the slug used in the session directory name must be normalized to a filesystem-safe lowercase hyphenated form.

When `linework new` is given an explicit `--session PATH` and `--name` is omitted, the stored session `name` must default to the basename of the session directory.

When `linework new` auto-creates a session path and `--name` is omitted, the stored session `name` must default to `session`.

The basename of the session directory is the human-facing short session ID. The canonical handle remains the full path.

### 6.4 Internal home directory

`~/.linework/` is reserved for machine-local runtime state such as:

- session auto-creation root
- watcher coordination state
- lock files
- caches
- temporary runtime artifacts

Machine-local runtime state must not be stored inside a portable session directory.

The default machine-local home root is `~/.linework/`. The home root may be overridden via the `LINEWORK_HOME` environment variable for testing or constrained environments.

### 6.5 Portability

A session directory must be a portable, self-contained artifact.

It must be possible to copy a session directory to another machine or location and still have:

- the command log
- the scene snapshot
- the latest render
- imported assets
- session metadata

continue to function without dependence on the original source machine.

## 7. Session Directory Layout

Each session directory must use this layout:

```text
<session>/
  session.json
  scene.json
  commands.jsonl
  assets/
  render/
    latest.png
```

Additional runtime-only files must not be written into the session directory.

### 7.1 `session.json`

`session.json` stores session metadata. It must include at least:

- `schema_version`
- `session_id`
- `name`
- `created_at`
- `updated_at`
- `canvas`
- `paths`

Normative structure:

```json
{
  "schema_version": 1,
  "session_id": "20260403-101530-idea-board",
  "name": "idea-board",
  "created_at": "2026-04-03T17:15:30Z",
  "updated_at": "2026-04-03T17:16:02Z",
  "canvas": {
    "width": 800,
    "height": 800,
    "background": "#FFFFFF"
  },
  "paths": {
    "scene": "scene.json",
    "commands": "commands.jsonl",
    "latest_render": "render/latest.png",
    "assets_dir": "assets"
  }
}
```

### 7.2 `scene.json`

`scene.json` stores the current derived scene snapshot.

- The command log is canonical.
- The scene snapshot exists for fast inspect/render/watch operations.
- The scene snapshot can always be rebuilt from the command log.

Normative structure:

```json
{
  "schema_version": 1,
  "session_id": "20260403-101530-idea-board",
  "canvas": {
    "width": 800,
    "height": 800,
    "background": "#FFFFFF"
  },
  "objects": []
}
```

`objects` must be ordered in creation order, which is also the rendering stack order from back to front.

### 7.3 `commands.jsonl`

`commands.jsonl` is the canonical append-only mutation log.

Each line is a JSON object representing one mutating operation.

Each entry must include at least:

- `schema_version`
- `op_id`
- `timestamp`
- `op`
- `payload`

Entries created by `linework run` may additionally include `batch_id`. All
successful operations from one batch share the same `batch_id` so a later
`undo` can reverse the whole batch as one action.

Normative structure:

```json
{"schema_version":1,"op_id":"op_000001","timestamp":"2026-04-03T17:15:30Z","op":"draw.rect","payload":{"id":"obj_000001","x":80.0,"y":120.0,"width":300.0,"height":180.0,"stroke":"#000000","fill":"#EEEEEE","stroke_width":2.0,"visible":true,"label":"api-box"}}
```

`undo` must be recorded as an append-only operation, not as an in-place deletion or rewrite of history.

### 7.4 Identifier conventions

The MVP uses simple sequential string identifiers within a session:

- session short ID: basename of the session directory, for example `20260403-101530-idea-board`
- object IDs: `obj_000001`, `obj_000002`, ...
- operation IDs: `op_000001`, `op_000002`, ...

Object IDs and operation IDs must be unique within a session.

## 8. Output Model

### 8.1 Default output

Commands must print human-readable output by default.

### 8.2 JSON output

All commands that return structured results must support `--json`.

When `--json` is used:

- stdout must contain exactly one JSON object
- no non-JSON output may appear on stdout

### 8.3 JSON error output

When a command fails in `--json` mode:

- stdout must contain a JSON error object
- the command must exit non-zero

Normative error structure:

```json
{"error": "object not found: obj_000099"}
```

When a command fails in default (non-JSON) mode:

- stderr must contain a human-readable error message
- the command must exit non-zero

### 8.4 Atomicity

Single mutating commands must be atomic:

- validate input
- apply the mutation
- update session state
- render the latest PNG
- return success

If any part of a single mutating command fails:

- the command must exit non-zero
- the session must remain unchanged

For `linework run` batch mode:

- operations apply sequentially
- processing stops at the first failure
- prior successful operations remain committed
- the command exits non-zero on failure

## 9. Command Surface

The MVP CLI has two tiers of commands:

**Core commands** (the agent loop):

- `linework` — bootstrap guide
- `linework --version` — print the installed version and check for updates
- `linework schema` — capability overview, one-op detail, or full JSON manifest
- `linework new` — create a session, optionally seeded from JSONL
- `linework run` — batch operations via JSONL or disposable one-shot export
- `linework inspect` — read current session state
- `linework export` — export PNG to a specified path
- `linework watch` — open a read-only watcher window

**Convenience commands** (single-operation shortcuts):

- `linework draw` — create a single object
- `linework edit` — modify a single object
- `linework delete` — delete a single object
- `linework undo` — undo the most recent operation

The convenience commands are thin wrappers. Every operation they perform is also available through `linework run`.

### 9.1 `linework`

Invoking `linework` with no arguments must print a rich bootstrap guide and exit successfully.

`linework --version` must print the installed package version and exit successfully. It should perform a best-effort update check against the remote repository; if a newer release tag exists, it prints a platform-appropriate `uv tool install` command that the user can copy and paste. The suggested command must force a fresh rebuild and pin the Git URL to the latest release tag so the installed tool picks up the correct tag-derived version. The check must fail silently on network errors or timeouts.

The bootstrap output must explain:

- what `linework` is
- the recommended discovery flow: `linework schema` for a quick overview, `linework schema OP` for one-operation detail, and `linework schema --json` for the full reference
- the session model
- the recommended workflow split: `linework new` for persistent watched sessions, `linework run --out` for disposable headless exports
- the JSONL batch workflow as the primary interface
- the default canvas size and background
- how `linework new --file/--stdin` can seed a watched session from an initial batch
- the inspect → edit/delete workflow for discovering IDs and labels
- the core commands
- an end-to-end agent example from session creation through JSONL batch to rendered PNG
- how to discover more help

### 9.2 `linework schema`

Read-only capability discovery for humans and agents.

Behavior:

- requires no session
- default output prints a compact reference card with canvas defaults, object types, high-level field names, shared defaults, operation rules, and the recommended discovery flow
- passing `OP` prints a detailed reference for one operation
- `--json` prints a machine-readable manifest for exact field lookup and external tooling; with `OP`, it filters the manifest to that operation

The JSON manifest must include:

- canvas defaults
- every supported operation
- required and optional payload fields
- selector rules for edit/delete operations
- enum values and defaults where applicable

Flags:

- `[OP]`
- `--json`

### 9.3 `linework new`

Creates a new session.

Behavior:

- If `--session PATH` is given, create the session there.
- Otherwise create it under `~/.linework/sessions/`.
- `--file PATH` or `--stdin` applies an initial JSONL batch immediately after session creation.
- Print the session path and short session ID.
- Render the initial blank PNG immediately.
- By default, watcher launch is best-effort; session creation still succeeds if the watcher cannot start.

Required semantics:

- default canvas size: `800x800`
- default background: `#FFFFFF`
- the watcher opens automatically after session creation unless `--headless` is passed
- when `--file` or `--stdin` is used, the watcher still opens by default after seeding unless `--headless` is passed
- when `--json` is used with `--file` or `--stdin`, output includes the created-session fields plus batch result fields (`applied`, `failed`, `results`, `scene_object_count`)

Flags:

- `--session PATH`
- `--name TEXT`
- `--width INT`
- `--height INT`
- `--background #RRGGBB`
- `--headless`
- `--file PATH`
- `--stdin`
- `--json`

### 9.4 `linework run`

The primary mutation interface. Applies a batch of JSONL operations to an existing session, or exports a one-shot batch result with `--out`.

Behavior:

- requires `--session PATH` or `--out PATH`
- reads JSONL from stdin by default
- supports `--file PATH` to read from a file
- supports `--out PATH` to export the rendered result after the batch
- supports `--width INT` and `--height INT` to size the temporary canvas when used with `--out` and without `--session`
- supports `--background #RRGGBB[AA]` to customize the temporary canvas when used with `--out` and without `--session`
- applies operations sequentially
- stops on first failure
- prior successful operations remain committed
- renders `render/latest.png` once after the last successful operation in the batch
- a later `undo` reverses the successful portion of that batch as one action
- when `--session` is omitted and `--out` is provided, `linework` must create a temporary default session, apply the batch, export the PNG, and then delete that temporary session; `--width`, `--height`, and `--background` customize that temporary session
- `--width`, `--height`, and `--background` must be rejected when `--session` is provided
- for persistent sessions and watcher-first workflows, users should prefer `linework new` followed by `linework run --session`, or seed the session directly with `linework new --file/--stdin`

Each input line must be a JSON object with `op` and `payload` fields:

```json
{"op":"draw.rect","payload":{"x":80,"y":120,"width":300,"height":180,"fill":"#EEEEEE","label":"api-box"}}
{"op":"draw.arrow","payload":{"x1":400,"y1":210,"x2":620,"y2":210,"stroke":"#333333","stroke_width":3,"arrowhead":"end","arrow_size":18}}
{"op":"draw.text","payload":{"x":100,"y":160,"text":"API flow","size":28,"anchor":"center","max_width":220,"fill":"#000000"}}
```

Object IDs may be omitted from draw operations; `linework` will generate sequential IDs and include them in the results.

Flags:

- `--session PATH`
- `--file PATH`
- `--out PATH`
- `--background #RRGGBB[AA]`
- `--width INT`
- `--height INT`
- `--json`

#### `linework run --json` output

On success (all operations applied):

```json
{
  "applied": 2,
  "failed": null,
  "results": [
    {"op_id": "op_000001", "op": "draw.rect", "object_id": "obj_000001"},
    {"op_id": "op_000002", "op": "draw.text", "object_id": "obj_000002"}
  ],
  "session_path": "/path/to/session",
  "scene_object_count": 2,
  "latest_render": "/path/to/session/render/latest.png"
}
```

When `--out` is provided, the result must additionally include:

```json
{"exported_path": "/path/to/output.png"}
```

When `linework run` is used in temporary one-shot mode (`--out` without
`--session`), the JSON payload must omit `session_path` and `latest_render`
because the temporary session is deleted after export.

On partial failure (some operations applied, then one failed):

```json
{
  "applied": 1,
  "failed": {"op": "draw.rect", "error": "width must be positive"},
  "results": [
    {"op_id": "op_000001", "op": "draw.rect", "object_id": "obj_000001"}
  ],
  "session_path": "/path/to/session",
  "scene_object_count": 1,
  "latest_render": "/path/to/session/render/latest.png"
}
```

The `results` array always contains one entry per successfully applied operation, in order. Each entry includes the assigned `op_id` and `object_id` (when applicable). This allows callers that omit IDs to discover the generated IDs.

### 9.5 `linework inspect`

Shows the current session state. This is the agent's "read" interface for understanding what is on the canvas.

Default human-readable output must include:

- session path
- short session ID
- canvas size
- background
- object count
- latest render path
- a compact object table

The object table must include:

- object ID
- type
- optional label
- visibility
- key geometry summary

`linework inspect --json` must return:

```json
{
  "session_path": "/path/to/session",
  "session_id": "20260403-101530-idea-board",
  "canvas": {"width": 800, "height": 800, "background": "#FFFFFF"},
  "object_count": 2,
  "latest_render": "/path/to/session/render/latest.png",
  "objects": [
    {"id": "obj_000001", "type": "rect", "visible": true, "label": "api-box", "x": 80.0, "y": 120.0, "width": 300.0, "height": 180.0},
    {"id": "obj_000002", "type": "text", "visible": true, "x": 100.0, "y": 160.0, "text": "API flow", "size": 28.0}
  ]
}
```

Flags:

- `--session PATH`
- `--json`

### 9.6 `linework export`

Exports the current scene to a user-specified PNG path.

Behavior:

- `--out PATH` is required
- export may copy or re-render from current state
- the command must print the final exported path

Flags:

- `--session PATH`
- `--out PATH`
- `--json`

### 9.7 `linework watch`

Opens a read-only watcher window for an existing session.

Behavior:

- requires `--session PATH`
- polls the session on a default interval of `250` milliseconds
- supports `--interval-ms`
- shows only the image
- uses the short session ID in the window title
- scales the image to fit the window
- chooses an initial window size that targets 1:1 canvas display when possible and otherwise caps to screen size

The watcher must not mutate session state.

### 9.8 `linework draw`

Convenience command for creating a single new object.

Primitive subcommands:

- `linework draw line`
- `linework draw arrow`
- `linework draw rect`
- `linework draw ellipse`
- `linework draw circle`
- `linework draw polyline`
- `linework draw polygon`
- `linework draw text`
- `linework draw image`

### 9.9 `linework edit`

Convenience command for modifying a single existing object by stable ID or
unique live label.

Primitive subcommands:

- `linework edit line`
- `linework edit arrow`
- `linework edit rect`
- `linework edit ellipse`
- `linework edit circle`
- `linework edit polyline`
- `linework edit polygon`
- `linework edit text`
- `linework edit image`

All edit commands must support partial updates. Only provided fields are changed.

Edits must not change stacking order.

### 9.10 `linework delete`

Convenience command for deleting a single object by stable object ID or unique
live label.

Behavior:

- requires `--session PATH`
- requires `--id OBJ_ID` or `--label LABEL`
- removes the object from current scene state
- preserves recoverability through command history and undo

### 9.11 `linework undo`

Convenience command for undoing the most recent action.

Behavior:

- whole-action undo
- a successful `linework run` batch undoes as one action
- implemented through append-only history semantics
- updates `scene.json`
- re-renders `render/latest.png`

### 9.12 Convenience command parameter contract

The convenience primitive commands must use these parameter names:

- `linework draw line --session PATH --x1 N --y1 N --x2 N --y2 N`
- `linework draw arrow --session PATH --x1 N --y1 N --x2 N --y2 N`
- `linework draw rect --session PATH --x N --y N --width N --height N`
- `linework draw ellipse --session PATH --x N --y N --width N --height N`
- `linework draw circle --session PATH --x N --y N --radius N`
- `linework draw polyline --session PATH --point X,Y --point X,Y ...`
- `linework draw polygon --session PATH --point X,Y --point X,Y --point X,Y ...`
- `linework draw text --session PATH --x N --y N --text STRING`
- `linework draw image --session PATH --source PATH --x N --y N`

Create commands may also accept:

- `--label STRING`
- `--visible true|false`
- applicable style flags such as `--stroke`, `--fill`, `--stroke-width`, `--size`, `--arrowhead`, `--arrow-size`, `--anchor`, and `--max-width`

Edit commands must use the same field names and additionally require:

- `--id OBJ_ID`, or
- a unique live `label` selector when `id` is omitted

When `linework edit` omits `id`, the `label` field acts as the selector rather
than a metadata update. Callers must use `id` when they need to change the
object's label.

`linework edit image` may update geometry, label, visibility, and other common editable fields, but image source replacement is not required in the MVP.

All convenience commands support `--json` for structured output, following the same output contract as a single-operation `linework run --json` call.

## 10. Object Model

### 10.1 Common object fields

Every object in `scene.json` must include:

- `id`
- `type`
- `visible`
- `label` optional

Objects may also include common style fields where applicable:

- `stroke`
- `fill`
- `stroke_width`

Default object semantics:

- `visible` defaults to `true`
- `stroke` defaults to `#000000` when applicable
- `fill` defaults to absent or null when not supplied
- `stroke_width` defaults to `2.0` when applicable

### 10.2 Labels

Labels are optional human-oriented metadata.

- Labels may be set during create or edit.
- `delete` may target a unique live label instead of an ID.
- `edit.*` may target a unique live label when `id` is omitted.
- If multiple live objects share a label, label-based selection must fail and
  require `id` for disambiguation.

### 10.3 Coordinates and units

- Coordinate system origin is top-left.
- Units are pixels.
- CLI examples may use integers.
- Internal geometry must allow floats.

### 10.4 Colors

The only supported color formats in the MVP are:

- `#RRGGBB`
- `#RRGGBBAA`

Named colors and other color syntaxes are out of scope.

### 10.5 Bounds

Objects may extend beyond the canvas bounds.

The renderer clips to the canvas.

Objects must not be auto-clamped or auto-rejected merely for being partially or fully out of bounds.

### 10.6 Stacking

- Creation order defines stacking order.
- Earlier objects are behind later objects.
- Edits do not change stacking order.
- There are no explicit z-order commands in the MVP.

## 11. Primitive Definitions

### 11.1 Line

Type: `line`

Geometry fields:

- `x1`
- `y1`
- `x2`
- `y2`

Style fields:

- `stroke`
- `stroke_width`

### 11.2 Arrow

Type: `arrow`

Geometry fields:

- `x1`
- `y1`
- `x2`
- `y2`

Style and arrow fields:

- `stroke`
- `stroke_width`
- `arrowhead` with values `end`, `start`, `both`, `none`
- `arrow_size` optional positive number in pixels

### 11.3 Rectangle

Type: `rect`

Geometry fields:

- `x`
- `y`
- `width`
- `height`

Style fields:

- `stroke`
- `fill`
- `stroke_width`

### 11.4 Ellipse

Type: `ellipse`

Geometry fields:

- `x`
- `y`
- `width`
- `height`

Style fields:

- `stroke`
- `fill`
- `stroke_width`

Circle convenience alias behavior:

- `draw.circle` and `edit.circle` are user-facing aliases stored as `ellipse`
  objects
- the alias uses `x`, `y`, and `radius`
- `radius` maps to equal `width` and `height`

### 11.5 Polyline

Type: `polyline`

This single primitive covers both polylines and freehand-style strokes.

Geometry field:

- `points`

Point representation:

```json
[[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]]
```

CLI point input:

- repeated `--point x,y` flags

Style fields:

- `stroke`
- `stroke_width`

### 11.6 Polygon

Type: `polygon`

Geometry field:

- `points`

Point representation:

```json
[[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]]
```

CLI point input:

- repeated `--point x,y` flags

Polygon behavior:

- the path closes automatically
- at least three points are required

Style fields:

- `stroke`
- `fill`
- `stroke_width`

### 11.7 Text

Type: `text`

Geometry and content fields:

- `x`
- `y`
- `text`
- `size`
- `anchor`
- `max_width` optional

Style field:

- `fill`

Text behavior:

- `anchor` controls horizontal alignment with values `left`, `center`, `right`
- `max_width` enables basic word wrapping based on rendered font metrics
- no rich text

### 11.8 Image

Type: `image`

Geometry fields:

- `x`
- `y`
- `width`
- `height`

Asset fields:

- `asset_path`
- `source_path` optional metadata

Behavior:

- imported images are copied into the session's `assets/` directory
- the scene stores the session-local asset path
- natural image size is the default when width and height are not provided
- if exactly one dimension override is provided, aspect ratio must be preserved automatically

Image asset replacement is not required in the MVP.

## 12. JSONL Batch Interface

`linework run` is the primary agent interface.

It is batch-oriented, not a persistent daemon protocol.

### 12.1 Supported operations

- `draw.line`
- `draw.arrow`
- `draw.rect`
- `draw.ellipse`
- `draw.circle`
- `draw.polyline`
- `draw.polygon`
- `draw.text`
- `draw.image`
- `edit.line`
- `edit.arrow`
- `edit.rect`
- `edit.ellipse`
- `edit.circle`
- `edit.polyline`
- `edit.polygon`
- `edit.text`
- `edit.image`
- `delete`
- `undo`

### 12.2 Input format

Each input line is a JSON object with `op` and `payload` fields:

```json
{"op":"draw.rect","payload":{"x":80.0,"y":120.0,"width":300.0,"height":180.0,"stroke":"#000000","fill":"#EEEEEE","stroke_width":2.0,"label":"api-box"}}
{"op":"draw.arrow","payload":{"x1":340.0,"y1":210.0,"x2":520.0,"y2":210.0,"stroke":"#333333","stroke_width":3.0,"arrowhead":"both","arrow_size":18.0}}
{"op":"draw.circle","payload":{"x":560.0,"y":120.0,"radius":28.0,"fill":"#BFDBFE"}}
{"op":"draw.polygon","payload":{"points":[[380.0,120.0],[520.0,60.0],[620.0,160.0]],"fill":"#FF6666","stroke":"#AA3333","label":"roof"}}
{"op":"draw.text","payload":{"x":100.0,"y":160.0,"text":"API flow","size":28.0,"anchor":"center","max_width":240.0,"fill":"#000000"}}
{"op":"edit.rect","payload":{"id":"obj_000001","fill":"#CCCCCC"}}
{"op":"delete","payload":{"label":"api-box"}}
{"op":"undo","payload":{}}
```

If callers omit object IDs for draw operations, `linework` generates sequential
IDs. The assigned IDs are returned in the results and recorded in the canonical
command log. `delete` may target a unique live label instead of an ID. For
`edit.*`, omitting `id` makes the `label` field act as the selector.

### 12.3 Output format

See §9.4 for the full `linework run --json` output specification.

### 12.4 End-to-end agent example

```bash
# 1. Create a session and note the returned session_path
linework new --name idea-board --json

# 2. Reuse that session path in later commands
SESSION=/path/to/session

# 3. Draw a diagram via JSONL batch
cat <<'EOF' | linework run --session "$SESSION" --json
{"op":"draw.rect","payload":{"x":50,"y":50,"width":200,"height":100,"fill":"#E8E8E8","label":"server"}}
{"op":"draw.text","payload":{"x":100,"y":90,"text":"Server","size":20}}
{"op":"draw.rect","payload":{"x":350,"y":50,"width":200,"height":100,"fill":"#E8E8E8","label":"client"}}
{"op":"draw.text","payload":{"x":400,"y":90,"text":"Client","size":20}}
{"op":"draw.line","payload":{"x1":250,"y1":100,"x2":350,"y2":100,"stroke":"#333333","stroke_width":3}}
EOF

# 4. Inspect the result and discover IDs/labels before editing
linework inspect --session "$SESSION" --json

# 5. Export to a shareable PNG
linework export --session "$SESSION" --out ./diagram.png
```

## 13. Rendering Contract

### 13.1 Rendering model

- The source of truth is the command log plus derived scene.
- Rendering is vector/scene-first in concept and rasterized to PNG output.
- The renderer outputs PNG only in the MVP.

### 13.2 Auto-render behavior

After every successful single mutating command:

- update session metadata
- update `scene.json`
- synchronously render `render/latest.png`
- return success

After every successful `linework run` batch:

- render `render/latest.png` once at the end of the batch

### 13.3 Export behavior

`linework export` is the explicit artifact publication step.

- It exports the current scene to a user-specified path.
- It does not replace the role of `render/latest.png`.

### 13.4 Background

The canvas background is a session-level property.

Defaults:

- width: `800`
- height: `800`
- background: `#FFFFFF`

## 14. Watcher Contract

The watcher is a convenience for humans observing progress. It is not part of the mutation engine.

Requirements:

- read-only
- minimal window
- no metadata panel
- image display only
- short session ID in title
- polling refresh model
- default interval of `250` milliseconds with `--interval-ms` override
- fit-to-window display
- initial size targets 1:1 display when possible and otherwise caps to screen bounds

The watcher must read session state produced by the core engine. It must not introduce its own scene model.

## 15. Concurrency and Locking

The MVP uses a single-writer model.

Requirements:

- mutating commands acquire a short-lived session lock
- watcher remains read-safe and does not take the writer lock
- overlapping mutating commands must not corrupt session state

The lock implementation is file-based with PID tracking. Machine-local lock artifacts live under `~/.linework/`, not in the session directory. Stale locks from dead processes are automatically reclaimed.

## 16. Testing and Regression Harness

Testing is part of the implementation, not optional cleanup.

### 16.1 Required testing layers

The test harness must include:

- unit tests for parsing, validation, IDs, paths, and scene mutations
- integration tests for CLI behavior
- renderer tests for object drawing semantics
- regression tests for session evolution and PNG outputs
- watcher logic tests where feasible without requiring manual interaction

### 16.2 Regression strategy

The repo must include test fixtures for stable sessions and expected outputs.

Fixture categories:

- blank session
- simple shapes session
- text session
- agent UX session (arrow, circle, text layout)
- image placement session
- undo/delete/edit session
- batch JSONL session

The renderer regression harness must validate:

- scene snapshot contents
- exported or latest PNG output
- deterministic asset handling

Because the MVP bundles a single font and uses a single renderer stack, image regression tests should be treated as strict artifacts unless a later issue explicitly introduces a tolerance-based comparison.

### 16.3 CLI test expectations

The test harness must validate at least:

- `linework` no-arg bootstrap output
- `linework schema`
- `linework new`
- `linework run` with JSONL input
- `linework run --out`
- `linework inspect`
- `linework export`
- convenience draw, edit, delete, undo commands
- `--json` output behavior for all commands
- `--json` error output behavior
- error exit behavior

## 17. Summary

`linework` is a Python CLI sketch tool for agents.

Its MVP is a session-based, non-interactive, self-describing retained-scene drawing system with:

- explicit session directories
- JSONL batch mode as the primary mutation interface
- append-only command history
- derived scene snapshots
- PNG rendering
- a minimal read-only watcher window
- portable artifacts
- structured JSON output for all commands
