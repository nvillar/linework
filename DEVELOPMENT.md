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
10. Agent UX improvements
11. Alpha compositing and transparency correctness
12. Box-based text layout
13. Agent usability cleanup

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
- `linework export --output PATH`
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
- watcher launch from `linework new`
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
- tag-based selection for `delete` and `edit.*` when IDs are omitted
- batch-aware undo (`linework run` undoes as one action)
- `linework new` watcher startup behavior refinements
- refactored `apply_batch()` to remove duplicated scene-derivation branches
- expanded JSON error, batch edge case, and CLI validation coverage
- refreshed bootstrap text, subcommand help, and polygon regression fixtures

#### Milestone 10: Agent UX improvements (complete)

- smarter unsupported-command errors with suggestions and valid-op lists
- tiered `linework schema` discovery: compact overview, `linework schema OP` one-op detail, and `linework schema --json` full manifest
- consistent discovery guidance across no-arg bootstrap, `--help`, and `linework schema`
- `draw.circle` / `edit.circle` convenience aliases stored as ellipses
- `linework run --output` one-shot temporary-session export flow
- `arrow` primitive with configurable `arrowhead` and optional `arrow_size`
- initial text alignment and wrapping support (later redesigned in Milestone 12)
- new agent UX regression fixture plus expanded CLI/render coverage

#### Milestone 11: Alpha compositing and transparency correctness (complete)

- per-object RGBA compositing for renderer-drawn objects in stacking order
- correct blending for overlapping translucent primitives and text
- targeted scene-engine coverage for transparency overlap behavior
- spec and roadmap updates clarifying the delivered alpha-rendering contract

#### Milestone 12: Box-based text layout (complete)

- redesigned `draw.text` / `edit.text` around explicit text boxes (`x`, `y`, `width`, `height`)
- replaced point anchoring with box-internal `align`, `valign`, and optional `padding`
- centered boxed text by default for diagram/image labeling
- wrapping now derives from the padded inner box width
- expanded CLI/render/regression coverage for boxed placement and multiline layout
- refreshed bootstrap, schema/help output, SPEC, and roadmap text to teach the new model

#### Milestone 13: Agent usability cleanup (complete)

- renamed hidden selector metadata from `label` to `tag` across CLI, JSONL, inspect output, schema, docs, tests, and stored scene objects
- removed the ambiguous `draw.label` / `edit.label` aliases
- replaced `--out` with `--output` for `linework run` and `linework export`
- rewrote locked/existing-session failures to steer agents toward reusing one session or batching changes
- updated bootstrap/help/new-session output to teach the persistent single-session workflow explicitly
- allowed `linework new --session PATH` to initialize inside a pre-created empty directory
- quoted shell-facing color examples and added shell guidance around `#RRGGBB[AA]` values

#### Milestone 14: Simplify session workflow (complete)

- removed `linework run` command entirely; agents use `new --file/--stdin` for batch seeding and convenience commands for iterative changes
- added `linework sessions` for listing sessions and `--prune` for cleaning up old ones
- added session-count cleanup nudge to `linework new` output when ≥10 sessions exist
- updated bootstrap/help/schema/docs to teach the draw/edit/delete convenience workflow as the primary interface

### Current implementation status

Completed milestones: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14.

Current user-facing command surface:

- `linework` (no-arg bootstrap)
- `linework --version` (with best-effort update check)
- `linework schema [OP]` (compact overview, one-op detail, or `--json` manifest)
- `linework new` (persistent session creation, optionally seeded from JSONL)
- `linework sessions` (list sessions or clean up old ones with `--prune`)
- `linework inspect`
- `linework export`
- `linework watch`
- `linework draw line|arrow|rect|ellipse|circle|polyline|polygon|text|image`
- `linework edit line|arrow|rect|ellipse|circle|polyline|polygon|text|image`
- `linework delete`
- `linework undo`

Internal engine capabilities:

- append-only mutation engine for `draw.line`, `draw.arrow`, `draw.rect`, `draw.ellipse`, `draw.circle`, `draw.polyline`, `draw.polygon`, `draw.text`, `draw.image`, `edit.*`, `delete`, `undo`
- tiered schema discovery: compact overview, per-operation detail, and full JSON manifest
- JSONL batch execution with single-render-at-end semantics (via `linework new --file/--stdin`)
- batch-aware undo grouping for seeded batches
- watched session seeding via `linework new --file` / `linework new --stdin`
- session listing and age-based pruning via `linework sessions`
- scene replay from command history
- PNG rendering for all supported primitives with per-object alpha compositing for renderer-drawn objects
- arrow rendering with configurable arrowhead placement and size
- boxed text layout with default centered placement, optional box-internal alignment, padding, and width-based wrapping
- tag-based selection for edit/delete with disambiguation on collisions
- bundled Noto Sans default font for deterministic text rendering
- session-local asset import/copy for image convenience commands
- read-only watcher window with lazy `tkinter` loading and polling refresh
- fixture-based regression harness for blank, shapes, polygon, text, image, agent UX, undo/edit/delete, and batch cases
- automated packaging/build validation plus isolated `uv tool install` validation
- structured `--json` output and `--json` error output for all mutation commands (`linework watch` is display-only and does not use `--json`)
- best-effort update check on `linework --version` with platform-aware, tag-pinned update command

Implementation notes:

- text rendering uses a bundled Noto Sans font shipped in `src/linework/assets/`
- image rendering and export now validate session-local assets; image source replacement remains out of scope
- `linework new` now defaults to an `800x800` canvas
- no-arg `linework`, `linework --help`, and `linework schema` now give consistent discovery advice: quick overview first, one-operation detail as needed, and `linework schema --json` as the full reference
- `draw.circle` / `edit.circle` accept `x`, `y`, and `radius`, but the stored scene object type remains `ellipse`
- workflow guidance now consistently recommends creating one persistent session with `linework new`, reusing that same `--session PATH` for all draw/edit/delete/inspect/export work, and using `linework watch` for live display
- `linework new` output always includes exact next-step hints for reusing the created session (`watch_command`, `watch_recommendation`, `inspect_command`, `export_command`); it strongly recommends opening a watch for the user after creation; `--file` / `--stdin` seed the session from an initial batch; a cleanup hint appears when ≥10 sessions exist
- `draw.arrow` / `edit.arrow` support `arrowhead` (`end`, `start`, `both`, `none`) and optional pixel-sized `arrow_size`
- text objects now use explicit layout boxes with `align`, `valign`, and optional `padding`; wrapping uses the padded inner box width
- renderer-drawn objects now render through per-object RGBA layers and are alpha-composited in creation order; image objects continue to use explicit `alpha_composite`
- `linework edit` can select by tag when `--id` is omitted; use `--id` when retagging
- watcher reads `render/latest.png` without taking the writer lock and keeps the last good image on transient read mismatches
- `linework watch` now preserves unavailable-environment reasons and, on Windows, rejects detached/noninteractive GUI contexts before reporting success
- watcher startup handshake confirms the window is visible on screen (via `winfo_viewable`) before signalling "ready" to the parent; if the window never becomes visible, the child reports failure and the parent relays a clear error
- watcher `load_toolkit()` proactively resolves `TCL_LIBRARY` from the real Python binary when Tcl 9's built-in `init.tcl` discovery would fail (works around a `python-build-standalone` / venv-symlink / stdin-redirect interaction on macOS that breaks `dladdr()`-based discovery)
- version is derived from git tags via `hatch-vcs`; there is no hardcoded version string (see copilot-instructions §6)
- `linework --version` checks the remote repo for newer tags via `git ls-remote` (5s timeout, best-effort); shows a platform-aware `uv tool install --no-cache --reinstall-package linework git+...@vX.Y.Z` command if an update is available
- Windows: `_is_pid_alive` uses Win32 `OpenProcess` API instead of `os.kill(pid, 0)` (which sends `CTRL_C_EVENT` on Windows)

Next milestone: **TBD.** Deferred future directions are canvas resize / fit-to-contents, grouping, auto-layout, higher-level composites, and themes / reusable styles.
