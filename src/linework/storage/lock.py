"""Single-writer session lock helpers."""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from linework.config import locks_root


class SessionLockedError(RuntimeError):
    """Raised when a session writer lock is already held."""


def _locked_session_message(session_path: Path, *, pid: int | None = None) -> str:
    """Return a user-facing single-writer guidance message."""
    owner = f" by another writer (pid {pid})" if pid is not None else " by another writer"
    return (
        f"session is locked{owner}: {session_path}. "
        "Only one writer may modify a session at a time. "
        "Wait for the other command to finish, then reuse the same session path."
    )


def lock_path_for_session(session_path: Path) -> Path:
    """Return the machine-local lock path for a session."""
    session_key = str(session_path.expanduser().resolve()).encode("utf-8")
    digest = hashlib.sha256(session_key).hexdigest()[:16]
    return locks_root() / f"{digest}.lock"


def _is_pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is still running.

    On Windows, ``os.kill(pid, 0)`` sends ``CTRL_C_EVENT`` (whose value is 0)
    instead of probing for existence, so we use the Win32 API directly.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _is_pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack permission to signal it.
        return True
    return True


def _is_pid_alive_windows(pid: int) -> bool:
    """Check process existence on Windows via OpenProcess."""
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def _try_reclaim_stale_lock(lock_path: Path, session_path: Path) -> None:
    """Remove a lock file if the owning process is no longer alive."""
    try:
        content = lock_path.read_text(encoding="utf-8").strip()
        pid = int(content)
    except (OSError, ValueError):
        # Unreadable or malformed lock file — treat as stale.
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
        return

    if _is_pid_alive(pid):
        raise SessionLockedError(_locked_session_message(session_path, pid=pid))

    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


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
    except FileExistsError:
        _try_reclaim_stale_lock(lock_path, session_path)
        # Retry after reclaim.
        try:
            file_descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as error:
            raise SessionLockedError(_locked_session_message(session_path)) from error

    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        yield lock_path
    finally:
        lock_path.unlink(missing_ok=True)
