"""Runtime configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path


def mural_home() -> Path:
    """Return the machine-local mural home directory."""
    configured_home = os.environ.get("MURAL_HOME")
    if configured_home:
        return Path(configured_home).expanduser().resolve()
    return (Path.home() / ".mural").resolve()


def sessions_root() -> Path:
    """Return the root directory for auto-created sessions."""
    return mural_home() / "sessions"


def locks_root() -> Path:
    """Return the root directory for writer locks."""
    return mural_home() / "locks"
