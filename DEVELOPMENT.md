# Linework Development Roadmap

This document tracks milestone status and progress for linework.

`SPEC.md` is the product definition. `.github/copilot-instructions.md` contains all
development rules, workflow processes, and validation requirements.

## Milestones

### Milestone decomposition

1. Repository bootstrap
2. Session and storage core
3. Scene engine and renderer
4. Core agent loop (`run`, `inspect`, `export`, `--json` everywhere)
5. Convenience CLI (`draw`, `edit`, `delete`, `undo` subcommands)
6. Image assets and portability
7. Watcher
8. Hardening and regression harness
9. Polish and test coverage

Milestones 4 and 5 reflect an agent-first delivery order: the JSONL batch interface (`run`), scene reader (`inspect`), and export are the primary agent workflow. The individual draw/edit/delete/undo subcommands are convenience wrappers and follow after.

### Milestone details

#### Milestone 1: Repository bootstrap (complete)

- `pyproject.toml`
- `src/` layout
- `linework` entry point
- dev tooling via `uv`
- base quality commands

#### Milestone 2: Session and storage core (complete)

- session creation
- session directory layout
- `session.json`, `scene.json`, `commands.jsonl`
- ID generation
- lock handling

#### Milestone 3: Scene engine and renderer (complete)

- object schemas
- create/edit/delete/undo semantics
- Pillow renderer
- latest PNG generation

#### Milestone 4: Core agent loop (complete)

- `linework run` (JSONL batch from stdin and `--file`)
- `linework run --json` with per-operation results
- `linework inspect` and `linework inspect --json`
- `linework export --out PATH`
- `--json` error output (structured JSON on stdout, exit non-zero)
- bootstrap text rewrite: teach JSONL workflow as the primary interface
- tests for all new commands

#### Milestone 5: Convenience CLI (complete)

- `linework draw line|rect|ellipse|polyline|text`
- `linework edit line|rect|ellipse|polyline|text`
- `linework delete --id`
- `linework undo`
- `--json` output for all convenience commands (single-operation `run` shape)
- tests for all convenience commands

#### Milestone 6: Image assets and portability (complete)

- `linework draw image --source PATH`
- `linework edit image`
- `--source PATH` import (copy into session `assets/`)
- asset path normalization
- original source metadata
- export validation

#### Milestone 7: Watcher (complete)

- `linework watch`
- `linework new --watch`
- polling loop
- image refresh
- session ID title
- sizing behavior
- graceful `tkinter` degradation
- transient read retry with last-good-image retention

#### Milestone 8: Hardening and regression harness (complete)

- CLI integration tests for all commands
- render regression fixtures
- bundled font (SPEC §3.5)
- watcher logic tests
- packaging validation
- `uv tool install` validation

#### Milestone 9: Polish and test coverage (complete)

- default canvas now `800x800`
- `polygon` primitive for filled closed shapes
- label-based selection for `delete` and `edit.*` when IDs are omitted
- batch-aware undo (`linework run` undoes as one action)
- normalized `--json` error envelope in `new --watch` failure path
- refactored `apply_batch()` to remove duplicated scene-derivation branches
- expanded JSON error, batch edge case, and CLI validation coverage
- refreshed bootstrap text, subcommand help, and polygon regression fixtures

### Current implementation status

Completed milestones: 1, 2, 3, 4, 5, 6, 7, 8, 9.

Current user-facing command surface:

- `linework` (no-arg bootstrap)
- `linework --version`
- `linework new`
- `linework run` (JSONL batch — primary agent interface)
- `linework inspect`
- `linework export`
- `linework watch`
- `linework draw line|rect|ellipse|polyline|polygon|text|image`
- `linework edit line|rect|ellipse|polyline|polygon|text|image`
- `linework delete`
- `linework undo`

Internal engine capabilities:

- append-only mutation engine for `draw.line`, `draw.rect`, `draw.ellipse`, `draw.polyline`, `draw.polygon`, `draw.text`, `draw.image`, `edit.*`, `delete`, `undo`
- JSONL batch execution with single-render-at-end semantics
- batch-aware undo grouping for `linework run`
- scene replay from command history
- PNG rendering for all supported primitives
- label-based selection for edit/delete with disambiguation on collisions
- bundled Noto Sans default font for deterministic text rendering
- session-local asset import/copy for image convenience commands
- read-only watcher window with lazy `tkinter` loading and polling refresh
- fixture-based regression harness for blank, shapes, polygon, text, image, undo/edit/delete, and batch cases
- automated packaging/build validation plus isolated `uv tool install` validation
- structured `--json` output and `--json` error output for all mutation commands (`linework watch` is display-only and does not use `--json`)
- richer bootstrap text and subcommand help with an inspect → edit/delete golden path

Implementation notes:

- text rendering uses a bundled Noto Sans font shipped in `src/linework/assets/`
- image rendering and export now validate session-local assets; image source replacement remains out of scope
- `linework new` now defaults to an `800x800` canvas
- `new --watch --json` keeps creating the session, but returns an error-only JSON envelope on watcher startup failure
- `linework edit` can select by label when `--id` is omitted; use `--id` when relabeling
- watcher reads `render/latest.png` without taking the writer lock and keeps the last good image on transient read mismatches

Next milestone: **TBD.**
