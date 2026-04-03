# Mural Specification

Status: authoritative working specification

This document is the source of truth for the `mural` project until code exists and a user-facing `README.md` can be written to match the actual implementation.

`README.md` must not be written until the code exists and the examples in the README can be executed against the repository as implemented.

## 1. Purpose

`mural` is an agent-first CLI tool for quickly drawing and sketching visual ideas.

It is intended to serve as "MS Paint for agents":

- It must support fast, non-interactive, scriptable drawing from the command line.
- It must support a headless workflow suitable for automated agent loops.
- It must optionally open a minimal live watcher window so a user can see drawing progress.
- It must produce portable session artifacts that can be exported, shared, inspected, and passed into a vision model by external tooling.

The MVP is a retained-scene sketch tool, not a full paint program and not a full diagramming system.

## 2. Product Principles

The implementation must follow these principles:

- Agent-first: the CLI must be easy for an agent to discover and use correctly.
- Non-interactive: the tool must never rely on interactive prompts.
- Self-describing: `mural` invoked with no arguments must print a rich bootstrap guide and exit.
- Explicit state: commands must target an explicit session path. There is no implicit "current session" for normal operations.
- Portable artifacts: session directories must be self-contained and copyable.
- Deterministic behavior: the same session state and command log must re-render the same PNG output on a supported platform.
- Small, composable surface area: the CLI must have a compact set of verbs and a consistent object model.

## 3. Technology and Packaging

### 3.1 Language and runtime

- The implementation language is Python.
- Python environments, dependencies, and execution must always be managed with `uv`.
- Do not use bare `pip`, `python -m pip`, ad hoc virtualenv activation, or direct Python execution when a `uv` equivalent exists.

Normative examples:

```bash
uv add pillow
uv add --dev pytest ruff mypy
uv run pytest
uv run ruff check .
uv run python -m mural
```

### 3.2 Installation target

The package must be installable as a tool from GitHub using `uv tool install`, in the form:

```bash
uv tool install git+https://github.com/nvillar/mural
```

That implies:

- a standard `pyproject.toml`
- a console script entry point named `mural`
- a `src/` layout

### 3.3 GUI stack

The MVP watcher window must use the Python standard library GUI stack:

- `tkinter`
- `ttk`

Rationale:

- minimal dependency footprint
- cross-platform support
- sufficient for a read-only PNG watcher

The watcher must degrade cleanly with a clear error if the active Python build lacks `tkinter`.

### 3.4 Rendering stack

The MVP raster renderer must use `Pillow`.

### 3.5 Font strategy

The MVP must bundle exactly one redistributable default font file with the package so that text rendering is predictable across platforms and regression tests can rely on deterministic output.

The bundled font becomes part of the rendering contract for the MVP.

## 4. Development Process

### 4.1 Spec authority

- This `SPEC.md` file is the authoritative definition of the project until replaced or amended by explicit subsequent decisions.
- When implementation questions arise, code should follow this spec unless the spec is intentionally updated first.

### 4.2 GitHub Issues and Milestones

Implementation must be tracked in GitHub using:

- Milestones for major phases
- Issues for concrete implementation slices

There must be no informal hidden plan outside the repo and GitHub tracking. The implementation process should be visible through issues and milestones.

Each milestone should represent a major delivery stage, for example:

1. Repository bootstrap and packaging
2. Session model and core scene engine
3. Rendering, draw/edit/delete/undo/export/inspect
4. JSONL batch interface and asset handling
5. Watcher window
6. Hardening, test harness, and installability

Each slice issue should contain, at minimum:

- Goal
- Scope
- Out of scope
- Dependencies
- Acceptance criteria
- Validation steps

An issue should not be closed until:

- code is merged
- tests for the slice exist
- relevant quality checks pass

### 4.3 README policy

- Do not create `README.md` until code exists.
- The first README must describe the actual implemented CLI and actual install/run commands.
- Placeholder or aspirational README text is explicitly disallowed.

### 4.4 Quality gates

Every implementation slice must preserve a green local quality bar run through `uv`.

The project must include and use:

- `pytest` for tests
- `ruff` for linting and formatting
- `mypy` for static typing checks

Normative command set:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

## 5. MVP Scope

### 5.1 In scope

- Session-oriented CLI
- Explicit session paths
- Rich no-argument bootstrap output
- Standard help system
- Human-readable default output
- `--json` machine-readable output
- Single-canvas sessions
- Retained scene model
- Canonical append-only command log
- Derived scene snapshot
- Auto-rendered latest PNG
- PNG export
- Draw primitives:
  - line
  - rectangle
  - ellipse
  - polyline
  - text
  - image placement
- Object mutation by stable ID
- Object labels as metadata
- Object visibility
- Delete
- Whole-command undo
- JSONL batch mode
- Read-only watcher window
- Session portability
- Single-writer locking

### 5.2 Explicitly out of scope for the MVP

- Built-in vision API integration
- SVG export
- PDF export
- Rich brushes
- Bucket fill tool
- Eraser tool
- Arrowheads or connector semantics
- Layers
- Grouping
- Rich text
- Text wrapping and alignment controls
- Z-order editing commands
- Multi-canvas or multi-page sessions
- Interactive prompts
- In-window editing
- Dedicated `replay` command
- Dedicated `history` command
- README before the code exists

## 6. Architecture Overview

The system is composed of five layers:

1. CLI layer
2. Core session and scene engine
3. Raster renderer
4. Session storage and artifact management
5. Optional watcher UI

Recommended source layout:

```text
src/mural/
  cli.py
  __main__.py
  core/
  render/
  storage/
  watch/
  assets/
tests/
```

The core engine must remain usable without the watcher.

The watcher must consume session artifacts generated by the core system rather than introducing a second source of truth.

## 7. Session Model

### 7.1 Session operating model

`mural` uses a stateful session CLI model.

- A session is the unit of persistence.
- A session corresponds to exactly one canvas.
- Commands operate on an explicit session path.
- A session is stored as a directory.

### 7.2 Session path rules

- Normal commands must target a session via `--session PATH`.
- `PATH` points to a session directory, not a single file.
- There is no implicit current session for normal commands.
- `mural new` is the only command that may create a new session directory automatically.

### 7.3 Default session creation location

If `mural new` is called without `--session PATH`, it must create the session under:

```text
~/.mural/sessions/
```

using the naming convention:

```text
YYYYMMDD-HHMMSS-slug
```

where `slug` comes from `--name` when provided, or a generated default slug when omitted.

If `--name` is omitted, the default slug is `session`.

The basename of the session directory is the human-facing short session ID. The canonical handle remains the full path.

### 7.4 Internal home directory

`~/.mural/` is reserved for machine-local runtime state such as:

- session auto-creation root
- watcher coordination state
- lock files
- caches
- temporary runtime artifacts

Machine-local runtime state must not be stored inside a portable session directory.

### 7.5 Portability

A session directory must be a portable, self-contained artifact.

It must be possible to copy a session directory to another machine or location and still have:

- the command log
- the scene snapshot
- the latest render
- imported assets
- session metadata

continue to function without dependence on the original source machine.

## 8. Session Directory Layout

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

### 8.1 `session.json`

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
    "width": 1200,
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

### 8.2 `scene.json`

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
    "width": 1200,
    "height": 800,
    "background": "#FFFFFF"
  },
  "objects": []
}
```

`objects` must be ordered in creation order, which is also the rendering stack order from back to front.

### 8.3 `commands.jsonl`

`commands.jsonl` is the canonical append-only mutation log.

Each line is a JSON object representing one mutating operation.

Each entry must include at least:

- `schema_version`
- `op_id`
- `timestamp`
- `op`
- `payload`

Normative structure:

```json
{"schema_version":1,"op_id":"op_000001","timestamp":"2026-04-03T17:15:30Z","op":"draw.rect","payload":{"id":"obj_000001","x":80.0,"y":120.0,"width":300.0,"height":180.0,"stroke":"#000000","fill":"#EEEEEE","stroke_width":2.0,"visible":true,"label":"api-box"}}
```

`undo` must be recorded as an append-only operation, not as an in-place deletion or rewrite of history.

### 8.4 Identifier conventions

The MVP uses simple sequential string identifiers within a session:

- session short ID: basename of the session directory, for example `20260403-101530-idea-board`
- object IDs: `obj_000001`, `obj_000002`, ...
- operation IDs: `op_000001`, `op_000002`, ...

Object IDs and operation IDs must be unique within a session.

## 9. Output Model

### 9.1 Default output

Commands must print human-readable output by default.

### 9.2 JSON output

Commands that return structured results must support `--json`.

When `--json` is used:

- stdout must contain JSON only
- stderr must contain diagnostics and errors only

### 9.3 Error handling

Single mutating commands must be atomic:

- validate input
- apply the mutation
- update session state
- render the latest PNG
- return success

If any part of a single mutating command fails:

- the command must exit non-zero
- the session must remain unchanged

For `mural run` batch mode:

- operations apply sequentially
- processing stops at the first failure
- prior successful operations remain committed
- the command exits non-zero on failure

## 10. Command Surface

The MVP CLI must include exactly these top-level commands:

- `mural`
- `mural new`
- `mural inspect`
- `mural export`
- `mural watch`
- `mural undo`
- `mural delete`
- `mural run`
- `mural draw`
- `mural edit`

### 10.1 `mural`

Invoking `mural` with no arguments must print a rich bootstrap guide and exit successfully.

The bootstrap output must explain:

- what `mural` is
- the session model
- the core workflow
- the main commands
- several concrete examples
- how to discover more help

### 10.2 `mural new`

Creates a new session.

Behavior:

- If `--session PATH` is given, create the session there.
- Otherwise create it under `~/.mural/sessions/`.
- Print the session path and short session ID.
- Render the initial blank PNG immediately.

Required semantics:

- default canvas size: `1200x800`
- default background: `#FFFFFF`
- `--watch` is supported and opens the watcher after session creation

Recommended flags:

- `--session PATH`
- `--name TEXT`
- `--width INT`
- `--height INT`
- `--background #RRGGBB`
- `--watch`
- `--json`

### 10.3 `mural inspect`

Shows the current session state.

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

`mural inspect --json` must return:

- session summary
- current object list

It must not return the full command history in the MVP.

### 10.4 `mural export`

Exports the current scene to a user-specified PNG path.

Behavior:

- `--out PATH` is required
- export may copy or re-render from current state
- the command must print the final exported path

### 10.5 `mural watch`

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

### 10.6 `mural undo`

Undoes the most recent mutating command for the session.

Behavior:

- whole-command undo only
- implemented through append-only history semantics
- updates `scene.json`
- re-renders `render/latest.png`

### 10.7 `mural delete`

Deletes an object from the current scene by stable object ID.

Behavior:

- requires `--session PATH`
- requires `--id OBJ_ID`
- removes the object from current scene state
- preserves recoverability through command history and undo

### 10.8 `mural run`

Applies a batch of JSONL operations to an existing session.

Behavior:

- requires `--session PATH`
- reads JSONL from stdin by default
- supports `--file PATH`
- applies operations sequentially
- stops on first failure
- keeps prior successful operations committed
- renders `render/latest.png` once after the last successful operation in the batch

### 10.9 `mural draw`

Creates new objects.

Primitive subcommands:

- `mural draw line`
- `mural draw rect`
- `mural draw ellipse`
- `mural draw polyline`
- `mural draw text`
- `mural draw image`

### 10.10 `mural edit`

Modifies existing objects by stable ID.

Primitive subcommands:

- `mural edit line`
- `mural edit rect`
- `mural edit ellipse`
- `mural edit polyline`
- `mural edit text`
- `mural edit image`

All edit commands must support partial updates. Only provided fields are changed.

Edits must not change stacking order.

### 10.11 Primitive CLI parameter contract

The MVP primitive commands must use these parameter names:

- `mural draw line --session PATH --x1 N --y1 N --x2 N --y2 N`
- `mural draw rect --session PATH --x N --y N --width N --height N`
- `mural draw ellipse --session PATH --x N --y N --width N --height N`
- `mural draw polyline --session PATH --point X,Y --point X,Y ...`
- `mural draw text --session PATH --x N --y N --text STRING`
- `mural draw image --session PATH --source PATH --x N --y N`

Create commands may also accept:

- `--label STRING`
- `--visible true|false`
- applicable style flags such as `--stroke`, `--fill`, `--stroke-width`, `--size`

Edit commands must use the same field names and additionally require:

- `--id OBJ_ID`

`mural edit image` may update geometry, label, visibility, and other common editable fields, but image source replacement is not required in the MVP.

## 11. Object Model

### 11.1 Common object fields

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

### 11.2 Labels

Labels are optional human-oriented metadata.

- The LLM may set labels during create or edit.
- Labels are not used as mutation selectors in the MVP.
- Mutating commands target objects by `--id` only.
- Visible label overlays are planned for the future but are not part of the MVP.

### 11.3 Coordinates and units

- Coordinate system origin is top-left.
- Units are pixels.
- CLI examples may use integers.
- Internal geometry must allow floats.

### 11.4 Colors

The only supported color formats in the MVP are:

- `#RRGGBB`
- `#RRGGBBAA`

Named colors and other color syntaxes are out of scope.

### 11.5 Bounds

Objects may extend beyond the canvas bounds.

The renderer clips to the canvas.

Objects must not be auto-clamped or auto-rejected merely for being partially or fully out of bounds.

### 11.6 Stacking

- Creation order defines stacking order.
- Earlier objects are behind later objects.
- Edits do not change stacking order.
- There are no explicit z-order commands in the MVP.

## 12. Primitive Definitions

### 12.1 Line

Type: `line`

Geometry fields:

- `x1`
- `y1`
- `x2`
- `y2`

Style fields:

- `stroke`
- `stroke_width`

### 12.2 Rectangle

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

### 12.3 Ellipse

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

### 12.4 Polyline

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

### 12.5 Text

Type: `text`

Geometry and content fields:

- `x`
- `y`
- `text`
- `size`

Style field:

- `fill`

Text behavior:

- basic text placement only
- no wrapping
- no alignment controls
- no rich text

### 12.6 Image

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

## 13. JSONL Batch Interface

`mural run` exists as the advanced machine interface.

It is batch-oriented, not a persistent daemon protocol.

Supported operation families:

- `draw.line`
- `draw.rect`
- `draw.ellipse`
- `draw.polyline`
- `draw.text`
- `draw.image`
- `edit.line`
- `edit.rect`
- `edit.ellipse`
- `edit.polyline`
- `edit.text`
- `edit.image`
- `delete`
- `undo`

Normative example:

```json
{"op":"draw.rect","payload":{"id":"obj_000001","x":80.0,"y":120.0,"width":300.0,"height":180.0,"stroke":"#000000","fill":"#EEEEEE","stroke_width":2.0,"label":"api-box"}}
{"op":"draw.text","payload":{"id":"obj_000002","x":100.0,"y":160.0,"text":"API flow","size":28.0,"fill":"#000000"}}
```

If external callers omit IDs for create operations, `mural` may generate them; the created IDs must then be returned in command results and recorded in the canonical log.

## 14. Rendering Contract

### 14.1 Rendering model

- The source of truth is the command log plus derived scene.
- Rendering is vector/scene-first in concept and rasterized to PNG output.
- The renderer outputs PNG only in the MVP.

### 14.2 Auto-render behavior

After every successful single mutating command:

- update session metadata
- update `scene.json`
- synchronously render `render/latest.png`
- return success

After every successful `mural run` batch:

- render `render/latest.png` once at the end of the batch

### 14.3 Export behavior

`mural export` is the explicit artifact publication step.

- It exports the current scene to a user-specified path.
- It does not replace the role of `render/latest.png`.

### 14.4 Background

The canvas background is a session-level property.

Defaults:

- width: `1200`
- height: `800`
- background: `#FFFFFF`

## 15. Watcher Contract

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

## 16. Concurrency and Locking

The MVP uses a single-writer model.

Requirements:

- mutating commands acquire a short-lived session lock
- watcher remains read-safe and does not take the writer lock
- overlapping mutating commands must not corrupt session state

The lock implementation may be file-based, but machine-local lock artifacts must live under `~/.mural/`, not in the session directory.

## 17. Testing and Regression Harness

The project must include a test harness from the beginning.

Testing is not optional cleanup after implementation. It is part of the implementation.

### 17.1 Required testing layers

The test harness must include:

- unit tests for parsing, validation, IDs, paths, and scene mutations
- integration tests for CLI behavior
- renderer tests for object drawing semantics
- regression tests for session evolution and PNG outputs
- watcher logic tests where feasible without requiring manual interaction

### 17.2 Regression strategy

The repo must include test fixtures for stable sessions and expected outputs.

Recommended fixture categories:

- blank session
- simple shapes session
- text session
- image placement session
- undo/delete/edit session
- batch JSONL session

The renderer regression harness must validate:

- scene snapshot contents
- exported or latest PNG output
- deterministic asset handling

Because the MVP bundles a single font and uses a single renderer stack, image regression tests should be treated as strict artifacts unless a later issue explicitly introduces a tolerance-based comparison.

### 17.3 CLI test expectations

The test harness must validate at least:

- `mural` no-arg bootstrap output
- `mural new`
- `mural inspect`
- `mural export`
- draw commands
- edit commands
- `mural delete`
- `mural undo`
- `mural run`
- `--json` output behavior
- error exit behavior

### 17.4 Watcher test expectations

The watcher must be designed so that most logic can be tested without manually opening a real interactive window.

Acceptable approach:

- isolate polling, image-loading, and sizing logic from the actual GUI event loop
- cover those parts with automated tests
- add lightweight watcher smoke tests where the platform and CI environment support them

### 17.5 Required developer commands

All development and test commands must run through `uv`.

Normative examples:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

## 18. Implementation Plan

Implementation should proceed in milestones tracked in GitHub.

### Milestone 1: Repository bootstrap

- create `pyproject.toml`
- establish `src/` layout
- wire the `mural` entry point
- add dev tooling via `uv`
- add base quality commands

### Milestone 2: Session and storage core

- session creation
- session directory layout
- `session.json`
- `scene.json`
- `commands.jsonl`
- ID generation
- lock handling

### Milestone 3: Scene engine and renderer

- object schemas
- create/edit/delete/undo semantics
- Pillow renderer
- latest PNG generation

### Milestone 4: CLI surface

- no-arg bootstrap
- `new`
- `inspect`
- `export`
- `draw`
- `edit`
- `delete`
- `undo`
- `run`
- `--json` responses

### Milestone 5: Image assets and portability

- imported image copying
- asset path normalization
- original source metadata
- export validation

### Milestone 6: Watcher

- `watch`
- polling loop
- image refresh
- session ID title
- sizing behavior

### Milestone 7: Hardening and regression harness

- CLI integration tests
- render regression fixtures
- watcher logic tests
- packaging validation
- `uv tool install` validation

## 19. Non-negotiable Rules

- Use Python.
- Use `uv` for Python dependency management and execution.
- Track implementation via GitHub Issues and Milestones.
- Do not write the README until code exists.
- Keep sessions portable and self-contained.
- Keep normal command targeting explicit through `--session PATH`.
- Keep the watcher read-only in the MVP.
- Keep the command log append-only.
- Ship a test harness alongside the code.

## 20. Summary Definition

`mural` is a Python CLI sketch tool for agents.

Its MVP is a session-based, non-interactive, self-describing retained-scene drawing system with:

- explicit session directories
- append-only command history
- derived scene snapshots
- PNG rendering
- a minimal read-only watcher window
- portable artifacts
- `uv`-based development and execution
- GitHub Issue and Milestone tracking
- a built-in regression-oriented test harness

This document defines both the product and the process by which it must be built.
