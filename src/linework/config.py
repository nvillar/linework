"""Runtime configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path


def linework_home() -> Path:
    """Return the machine-local linework home directory."""
    configured_home = os.environ.get("LINEWORK_HOME")
    if configured_home:
        return Path(configured_home).expanduser().resolve()
    return (Path.home() / ".linework").resolve()


def sessions_root() -> Path:
    """Return the root directory for auto-created sessions."""
    return linework_home() / "sessions"


def locks_root() -> Path:
    """Return the root directory for writer locks."""
    return linework_home() / "locks"
