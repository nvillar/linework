# Mural Development Workflow

Status: required implementation process

This document defines how `mural` is developed and tracked.

`SPEC.md` is the product definition.
`DEVELOPMENT.md` is the implementation workflow.

## 1. Core rules

- Use Python.
- Use `uv` for environments, dependencies, tooling, and execution.
- Use a project-local `.venv/` managed by `uv`.
- Do not use the system Python interpreter directly for development.
- Do not create `README.md` until the code exists and the examples are real.
- Track major work in GitHub Milestones and concrete work in GitHub Issues.

## 2. Milestone workflow

Before implementation starts for a milestone:

- create or confirm the GitHub Milestone exists
- create the milestone tracking Issue
- ensure the Issue has:
  - Goal
  - Scope
  - Out of scope
  - Dependencies
  - Acceptance criteria
  - Validation steps

During implementation:

- keep the milestone Issue current
- keep `SPEC.md` aligned with any intentional product-definition changes
- use small, reviewable commits
- run development commands through `uv`

After implementation is complete for a milestone:

- run the full project validation suite
- perform a final code review
- review `SPEC.md` for consistency and freshness
- update `SPEC.md` so it reflects the code as the current source of truth
- remove stale transitional language and historical artifacts from `SPEC.md`
- update the milestone Issue if needed to reflect the delivered result
- close the milestone Issue
- commit all milestone code and documentation changes
- push the commits to the remote repository

## 3. Required validation commands

Run all commands through `uv`.

Normative baseline:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Milestones must not be considered complete until this suite is green, plus any milestone-specific validation defined in the Issue.

## 4. GitHub tracking model

The intended milestone set is:

1. Repository bootstrap
2. Session and storage core
3. Scene engine and renderer
4. CLI surface
5. Image assets and portability
6. Watcher
7. Hardening and regression harness

Slice Issues should be attached to the appropriate Milestone.

No milestone should proceed without visible GitHub tracking.

## 5. Environment notes

In restricted or sandboxed environments, it is acceptable to keep `uv` state local to the repo, for example:

```bash
export UV_CACHE_DIR=.uv-cache
export UV_PYTHON_INSTALL_DIR=.uv-python
```

For local testing or constrained environments, `MURAL_HOME` may also be set to override the default machine-local `~/.mural` root.

These are environment workarounds for development tooling. They do not change the runtime or packaging requirements of `mural`.
