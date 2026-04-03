"""Session creation and storage helpers."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from mural.config import sessions_root
from mural.render.png import render_blank_canvas
from mural.storage.ids import build_session_id, iso_timestamp, normalize_slug, utc_now
from mural.storage.lock import writer_lock
from mural.storage.models import (
    Canvas,
    CreatedSession,
    SceneSnapshot,
    SessionMetadata,
    SessionPaths,
)

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")


class SessionError(RuntimeError):
    """Base error for session operations."""


class SessionAlreadyExistsError(SessionError):
    """Raised when a session directory already exists."""


class SessionValidationError(SessionError):
    """Raised when provided session input is invalid."""


def resolve_session_path(
    session: str | None,
    name: str | None,
    *,
    created_at: datetime,
) -> Path:
    """Resolve the target session path for creation."""
    if session is not None:
        return Path(session).expanduser().resolve()

    slug = normalize_slug(name)
    session_id = build_session_id(created_at, slug)
    return sessions_root() / session_id


def create_session(
    *,
    session: str | None,
    name: str | None,
    width: int,
    height: int,
    background: str,
) -> CreatedSession:
    """Create a new blank session on disk."""
    validate_canvas(width=width, height=height, background=background)

    created_at = utc_now()
    session_path = resolve_session_path(session, name, created_at=created_at)
    with writer_lock(session_path):
        if session_path.exists():
            raise SessionAlreadyExistsError(f"session already exists: {session_path}")

        session_id = session_path.name
        session_name = resolve_session_name(
            session_path=session_path,
            name=name,
            explicit_session=session is not None,
        )
        canvas = Canvas(width=width, height=height, background=background.upper())
        metadata = SessionMetadata(
            schema_version=1,
            session_id=session_id,
            name=session_name,
            created_at=iso_timestamp(created_at),
            updated_at=iso_timestamp(created_at),
            canvas=canvas,
            paths=SessionPaths(),
        )
        scene = SceneSnapshot(
            schema_version=1,
            session_id=session_id,
            canvas=canvas,
            objects=[],
        )

        parent = session_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{session_path.name}.tmp-",
                dir=parent,
            )
        )

        try:
            initialize_session_directory(temp_dir, metadata, scene)
            temp_dir.replace(session_path)
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    latest_render = session_path / metadata.paths.latest_render
    return CreatedSession(
        session_path=str(session_path),
        session_id=session_id,
        name=session_name,
        canvas=canvas,
        latest_render=str(latest_render),
    )


def initialize_session_directory(
    session_path: Path,
    metadata: SessionMetadata,
    scene: SceneSnapshot,
) -> None:
    """Initialize the on-disk files for a session."""
    (session_path / metadata.paths.assets_dir).mkdir()
    (session_path / "render").mkdir()

    write_json(session_path / "session.json", metadata.to_dict())
    write_json(session_path / "scene.json", scene.to_dict())
    (session_path / "commands.jsonl").write_text("", encoding="utf-8")
    render_blank_canvas(metadata.canvas, session_path / metadata.paths.latest_render)


def resolve_session_name(
    *,
    session_path: Path,
    name: str | None,
    explicit_session: bool,
) -> str:
    """Resolve the stored session name."""
    if name is not None:
        stripped = name.strip()
        if stripped:
            return stripped
    if explicit_session:
        return session_path.name if session_path.name else "session"
    return "session"


def validate_canvas(*, width: int, height: int, background: str) -> None:
    """Validate canvas input."""
    if width <= 0:
        raise SessionValidationError("width must be positive")
    if height <= 0:
        raise SessionValidationError("height must be positive")
    if not _HEX_COLOR.fullmatch(background):
        raise SessionValidationError("background must be #RRGGBB or #RRGGBBAA")


def write_json(path: Path, payload: dict[str, object]) -> None:
    """Write JSON with stable formatting."""
    path.write_text(f"{json.dumps(payload, indent=2)}\n", encoding="utf-8")
