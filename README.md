# Linework

Linework is a simple sketching tool that can be used by any agent
that has access to a command-line session.

An agent can draw shapes, place text, build diagrams, and export PNGs from
the command line. Because linework keeps the underlying objects, you can ask the
agent to tweak things (*make the red box wider, change the background, relabel
that arrow*) and it edits in place instead of regenerating from scratch.

The agent can work in the background, or can open a read-only **watcher
window** to show the drawing come together in real time.

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** — Python package and project manager.
- An **agent with terminal access** (e.g. Copilot, Claude, Codex, or VS Code).

## Install

```bash
uv tool install git+https://github.com/nvillar/linework.git
```

## Quick start

Give your agent a prompt like this:

> You have access to the `linework` CLI for creating drawings and diagrams.
> Run `linework` with no arguments to learn how it works. Start by creating a
> session with `--watch` so I can see what you draw, then draw a self-portrait.

The agent will read the built-in bootstrap guide, create a session, open the
watcher window on your screen, and start drawing. 

## Under the hood

Every drawing lives in a portable **session directory**. The primary interface is
**JSONL batch mode**, designed for automated agent loops. Here's what the agent
is doing behind the scenes:

```bash
# Create a session with a live watcher
linework new --name demo --watch

# Draw via JSONL batch (in another terminal)
cat <<'EOF' | linework run --session PATH --json
{"op":"draw.rect","payload":{"x":50,"y":50,"width":200,"height":100,"fill":"#E8E8E8","label":"box"}}
{"op":"draw.polygon","payload":{"points":[[300,50],[400,10],[400,90]],"fill":"#FF6666"}}
{"op":"draw.text","payload":{"x":70,"y":85,"text":"Hello","size":20}}
EOF

# Read back what's on the canvas
linework inspect --session PATH --json

# Export a PNG
linework export --session PATH --out diagram.png
```

Run `linework` with no arguments for the full reference.
