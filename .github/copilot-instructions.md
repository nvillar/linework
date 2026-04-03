# Copilot Instructions for Linework

This document is the authoritative guide for agents working on linework. It contains
all development rules, workflow processes, and validation requirements.

`SPEC.md` is the product definition. `DEVELOPMENT.md` is the milestone roadmap and
status diary. This file governs *how* work is done.

---

## 1. Core rules

- Use Python.
- Use `uv` for environments, dependencies, tooling, and execution.
- Use a project-local `.venv/` managed by `uv`.
- Do not use the system Python interpreter directly for development.
- Do not create `README.md` until the code exists and the examples are real.
- Track major work in GitHub Milestones and concrete work in GitHub Issues.

## 2. Python and environment rules

These rules are **non-negotiable**. They apply in every context: the repository,
`/tmp`, integration test helpers, one-off checks — everywhere.

### Never use the system Python

The system Python is likely a different version (e.g., 3.13) than the project
requires (3.12). Running `python`, `python3`, or `pip` directly uses the system
interpreter, which produces wrong test results and pollutes the system
site-packages with project-specific libraries.

`uv run` is the way to avoid this. It resolves the correct Python version and
project dependencies automatically. Use it for every Python invocation:

```bash
# CORRECT — always
uv run pytest
uv run python -c "print('hello')"
uv run mypy src
uv run ruff check .

# WRONG — uses the system Python
python -m pytest
python3 tests/test_foo.py
python -c "import linework"
pip install somepackage
```

Do **not** invoke `python`, `python3`, `pip`, or `pip3` directly — not in the
repo, not in `/tmp`, not in a subprocess, not for anything.

### Environment and dependency management

```bash
uv sync                       # install/update dependencies
uv run pytest                 # run tests
uv run ruff check .           # lint
uv run ruff format --check .  # format check
uv run mypy src               # type check
```

### Project-local `.venv/` only

The project uses a `.venv/` managed by `uv` at the repository root. Do not create,
activate, or reference any other virtual environment for project work.

## 3. Working in /tmp or other directories

If you need a temporary directory (e.g., for integration tests, scratch work, or
isolated test runs), you **must** follow these rules:

1. Use `/tmp/linework/` as the dedicated temporary directory (not `/tmp/` directly).
2. Create a `uv`-managed `.venv` there so that `uv run` resolves to the correct
   Python version instead of falling back to the system interpreter.
3. Use `uv run` for all Python execution, same as in the repository.

```bash
mkdir -p /tmp/linework
cd /tmp/linework
uv venv .venv --python 3.12
uv run python -c "print('ready')"   # uses project Python 3.12
uv run pytest                        # uses project Python 3.12
```

4. Clean up `/tmp/linework/` when done if appropriate.

## 4. Milestone workflow

Before implementation starts for a milestone:

1. Create or confirm the GitHub Milestone exists.
2. Create the milestone tracking Issue.
3. Ensure the Issue has:
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

1. Run the full project validation suite.
2. Perform a final code review.
3. Review `SPEC.md` for consistency and freshness.
4. Update `SPEC.md` so it reflects the code as the current source of truth.
5. Remove stale transitional language and historical artifacts from `SPEC.md`.
6. Update `DEVELOPMENT.md` to reflect the new current status.
7. Update the milestone Issue so it reflects the delivered result.
8. Commit all milestone code and documentation changes.
9. Push the commits to the remote repository.
10. Confirm the repository is in a clean state with no uncommitted changes.
11. Close the milestone Issue only after the commit, push, and clean-state checks are complete.

## 5. Required validation commands

Run all commands through `uv`.

Normative baseline:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Milestones must not be considered complete until this suite is green, plus any
milestone-specific validation defined in the Issue.

## 6. Environment notes

In restricted or sandboxed environments, it is acceptable to keep `uv` state local
to the repo, for example:

```bash
export UV_CACHE_DIR=.uv-cache
export UV_PYTHON_INSTALL_DIR=.uv-python
```

For local testing or constrained environments, `LINEWORK_HOME` may also be set to
override the default machine-local `~/.linework` root.

These are environment workarounds for development tooling. They do not change the
runtime or packaging requirements of `linework`.

## 7. Agent interaction guidelines

### Multiple-choice questions

When presenting the user with a multiple-choice question, always note which option
you recommend and include a brief explanation of why. This helps the user make an
informed decision quickly.

### Read DEVELOPMENT.md for context

Before starting any task, read `DEVELOPMENT.md` to understand the current milestone
status, what has been completed, and what is in progress. This prevents duplicate
work and ensures changes align with the project roadmap.
