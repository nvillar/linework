# Mural Development Roadmap

This document tracks milestone status and progress for mural.

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

Milestones 4 and 5 reflect an agent-first delivery order: the JSONL batch interface (`run`), scene reader (`inspect`), and export are the primary agent workflow. The individual draw/edit/delete/undo subcommands are convenience wrappers and follow after.

### Milestone details

#### Milestone 1: Repository bootstrap (complete)

- `pyproject.toml`
- `src/` layout
- `mural` entry point
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

- `mural run` (JSONL batch from stdin and `--file`)
- `mural run --json` with per-operation results
- `mural inspect` and `mural inspect --json`
- `mural export --out PATH`
- `--json` error output (structured JSON on stdout, exit non-zero)
- bootstrap text rewrite: teach JSONL workflow as the primary interface
- tests for all new commands

#### Milestone 5: Convenience CLI (complete)

- `mural draw line|rect|ellipse|polyline|text`
- `mural edit line|rect|ellipse|polyline|text`
- `mural delete --id`
- `mural undo`
- `--json` output for all convenience commands (single-operation `run` shape)
- tests for all convenience commands

#### Milestone 6: Image assets and portability (complete)

- `mural draw image --source PATH`
- `mural edit image`
- `--source PATH` import (copy into session `assets/`)
- asset path normalization
- original source metadata
- export validation

#### Milestone 7: Watcher

- `mural watch`
- `mural new --watch`
- polling loop
- image refresh
- session ID title
- sizing behavior
- graceful `tkinter` degradation

#### Milestone 8: Hardening and regression harness

- CLI integration tests for all commands
- render regression fixtures
- bundled font (SPEC §3.5)
- watcher logic tests
- packaging validation
- `uv tool install` validation

### Current implementation status

Completed milestones: 1, 2, 3, 4, 5, 6.

Current user-facing command surface:

- `mural` (no-arg bootstrap)
- `mural --version`
- `mural new`
- `mural run` (JSONL batch — primary agent interface)
- `mural inspect`
- `mural export`
- `mural draw line|rect|ellipse|polyline|text|image`
- `mural edit line|rect|ellipse|polyline|text|image`
- `mural delete`
- `mural undo`

Internal engine capabilities:

- append-only mutation engine for `draw.line`, `draw.rect`, `draw.ellipse`, `draw.polyline`, `draw.text`, `draw.image`, `edit.*`, `delete`, `undo`
- JSONL batch execution with single-render-at-end semantics
- scene replay from command history
- PNG rendering for all supported primitives
- session-local asset import/copy for image convenience commands
- structured `--json` output and `--json` error output for all commands

Implementation notes:

- text rendering uses Pillow's default font; the bundled-font requirement (SPEC §3.5) is deferred to milestone 8
- image rendering and export now validate session-local assets; image source replacement remains out of scope
- watcher behavior and `mural new --watch` are deferred to milestone 7

Next milestone: **7 — Watcher**.
