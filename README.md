# Linework

Linework is an agent-first CLI sketch tool — think "MS Paint for agents." It
lets an AI agent (or a human) create, edit, and export simple drawings entirely
from the command line, with no interactive prompts and no GUI required for
drawing.

Every drawing lives in a portable **session directory**. The primary interface is
**JSONL batch mode** (`linework run`), designed for automated agent loops. A
read-only **watcher window** lets a human observe drawing progress in real time.

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** — Python package and project manager.
- **An agent with terminal access** — or a regular terminal for manual use.

## Install

```bash
uv tool install git+https://github.com/nvillar/linework.git
```

This installs the `linework` command globally.

## Quick start

```bash
# Create a session and open a live watcher
linework new --name demo --watch

# In another terminal, draw into it
SESSION=~/.linework/sessions/<session-id>
linework draw rect --session "$SESSION" --x 50 --y 50 --width 200 --height 100 --fill "#E8E8E8"
linework draw polygon --session "$SESSION" --point 300,50 --point 400,10 --point 400,90 --fill "#FF6666"

# Inspect what's on the canvas
linework inspect --session "$SESSION"

# Export a PNG
linework export --session "$SESSION" --out diagram.png
```

Run `linework` with no arguments for the full bootstrap guide, including the
JSONL batch reference and the golden-path workflow.

## Giving an agent access

Add something like this to your agent's system prompt:

> You have access to the `linework` CLI for creating drawings and diagrams. Run
> `linework` with no arguments to learn how it works.

The no-argument bootstrap output teaches the agent everything it needs: the
session model, JSONL batch format, available primitives, and the
inspect → edit/delete workflow.

## License

Proprietary.
