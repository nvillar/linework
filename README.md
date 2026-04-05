# `linework`

`linework` is a simple sketching tool for agents that allows them to draw 
shapes, place text, build diagrams, and export PNGs from the command line. 

`linework` keeps the underlying drawing objects, allowing an agent to
tweak things (*make the red box wider, change the background, relabel
that arrow*), editing the shapes in place instead of regenerating the image 
from scratch.

When the agent starts a `linework` session, it can open a read-only **watcher
window** to show the drawing come together in real time. The agent can also use
`linework` as a background process with no graphical interface.

![screenshot of an agent using linework to make a chart and a picture](screenshot.png)

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** — Python package and project manager.
- An **agent with terminal access** (e.g. Copilot, Claude, Codex, or VS Code).

## Install or update

On Windows:
```bash
uv tool install --no-cache --reinstall-package linework --link-mode copy git+https://github.com/nvillar/linework.git
```

On macOS:
```bash
uv tool install --no-cache --reinstall-package linework git+https://github.com/nvillar/linework.git
```
Or point your agent to this page and ask it to install `linework`.

## Quick start

Give your agent a prompt like this:

```
Use the linework CLI to draw a self-portrait, and open a watch for me to follow along. 
```

Or, more explicitly: 

```
You have access to the `linework` CLI for creating drawings and diagrams.
Run `linework` with no arguments to learn how it works.
Start by creating a session, then draw a self-portrait.
Open a watch for me to follow your progress.
```

The agent will read the built-in bootstrap guide, create a session, and start
drawing. If you want to watch it work, ask it to open the watcher — or run
`linework watch --session PATH` yourself.

For iterative work, steer it toward `linework new` and `linework watch`.
For a throwaway file with no watcher, steer it toward `linework run --out`.

The agent might take some time to first explore the tool, learn how it works, 
and finally put together a drawing. Making changes should be much faster, and
you can watch the drawing update on the watcher window.

If the agent supports memory, you can ask it to remember about the tool and how
to use it to avoid having to learn it every time.

## Tip: Visual feedback

 If your agent supports image understanding, a useful pattern is to have it view 
 the rendered PNG to verify the result visually. By viewing it, the 
 agent can catch alignment, spacing, and readability issues that aren't obvious from 
 object coordinates alone and correct them with follow-up edits.

```
 After drawing, view the latest render to check how it looks. If anything is off
 — alignment, spacing, overlap — fix it.
```

## Under the hood

Every drawing lives in a portable **session directory** when you want to keep
iterating. The primary interface is **JSONL batch mode**, designed for automated
agent loops. Use `linework new` for persistent sessions, `linework watch` to
open a live display, and `linework run --out` for disposable headless exports.
Here are the main patterns behind the scenes:

```bash
# Create a session
linework new --name demo

# Open a watcher so the user can see changes live
linework watch --session PATH

# Or create and seed a session from an existing JSONL batch
linework new --name demo --file ops.jsonl

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

# Or do a disposable one-shot export with a temporary canvas
linework run --file ops.jsonl --out diagram.png --width 1200 --height 800 --background "#111827"
```

The **watcher window** runs as its own process, so it stays open while the agent works across multiple commands.

Run `linework` with no arguments for the full reference.
