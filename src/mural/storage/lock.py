"""Single-writer session lock helpers."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from mural.config import locks_root


class SessionLockedError(RuntimeError):
    """Raised when a session writer lock is already held."""


def lock_path_for_session(session_path: Path) -> Path:
    """Return the machine-local lock path for a session."""
    session_key = str(session_path.expanduser().resolve()).encode("utf-8")
    digest = hashlib.sha256(session_key).hexdigest()[:16]
    return locks_root() / f"{digest}.lock"


@contextmanager
def writer_lock(session_path: Path) -> Iterator[Path]:
    """Acquire an exclusive writer lock for a session."""
    lock_path = lock_path_for_session(session_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        file_descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError as error:
        raise SessionLockedError(f"session is locked: {session_path}") from error

    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        yield lock_path
    finally:
        lock_path.unlink(missing_ok=True)
