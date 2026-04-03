"""Session creation and storage helpers."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from mural.config import sessions_root
from mural.core.commands import normalize_command
from mural.core.scene import derive_scene
from mural.render.png import render_blank_canvas, render_scene
from mural.storage.ids import build_session_id, iso_timestamp, normalize_slug, utc_now
from mural.storage.lock import writer_lock
from mural.storage.models import (
    Canvas,
    CommandRecord,
    CreatedSession,
    MutationResult,
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


class SessionNotFoundError(SessionError):
    """Raised when a session directory does not exist."""


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


def apply_mutation(
    session_path: str | Path,
    *,
    op: str,
    payload: dict[str, object] | None = None,
) -> MutationResult:
    """Apply a mutating command to an existing session."""
    resolved_session_path = Path(session_path).expanduser().resolve()

    with writer_lock(resolved_session_path):
        metadata = read_session_metadata(resolved_session_path)
        commands = read_commands(resolved_session_path)
        normalized_command = normalize_command(
            op=op,
            payload=payload,
            existing_commands=commands,
            session_path=resolved_session_path,
        )
        updated_commands = [*commands, normalized_command]
        updated_scene = derive_scene(
            canvas=metadata.canvas,
            commands=updated_commands,
            session_path=resolved_session_path,
            session_id=metadata.session_id,
        )
        updated_metadata = SessionMetadata(
            schema_version=metadata.schema_version,
            session_id=metadata.session_id,
            name=metadata.name,
            created_at=metadata.created_at,
            updated_at=normalized_command.timestamp,
            canvas=metadata.canvas,
            paths=metadata.paths,
        )
        write_mutated_session(
            session_path=resolved_session_path,
            metadata=updated_metadata,
            scene=updated_scene,
            commands=updated_commands,
        )

    object_id = normalized_command.payload.get("id")
    return MutationResult(
        op_id=normalized_command.op_id,
        op=normalized_command.op,
        object_id=object_id if isinstance(object_id, str) else None,
        session_path=str(resolved_session_path),
        scene_object_count=len(updated_scene.objects),
        latest_render=str(resolved_session_path / updated_metadata.paths.latest_render),
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


def read_session_metadata(session_path: Path) -> SessionMetadata:
    """Read session metadata from disk."""
    if not session_path.is_dir():
        raise SessionNotFoundError(f"session does not exist: {session_path}")

    raw = json.loads((session_path / "session.json").read_text(encoding="utf-8"))
    canvas = Canvas(
        width=int(raw["canvas"]["width"]),
        height=int(raw["canvas"]["height"]),
        background=str(raw["canvas"]["background"]),
    )
    paths = SessionPaths(
        scene=str(raw["paths"]["scene"]),
        commands=str(raw["paths"]["commands"]),
        latest_render=str(raw["paths"]["latest_render"]),
        assets_dir=str(raw["paths"]["assets_dir"]),
    )
    return SessionMetadata(
        schema_version=int(raw["schema_version"]),
        session_id=str(raw["session_id"]),
        name=str(raw["name"]),
        created_at=str(raw["created_at"]),
        updated_at=str(raw["updated_at"]),
        canvas=canvas,
        paths=paths,
    )


def read_scene_snapshot(session_path: Path) -> SceneSnapshot:
    """Read the current scene snapshot from disk."""
    if not session_path.is_dir():
        raise SessionNotFoundError(f"session does not exist: {session_path}")
    raw = json.loads((session_path / "scene.json").read_text(encoding="utf-8"))
    return SceneSnapshot.from_dict(raw)


def read_commands(session_path: Path) -> list[CommandRecord]:
    """Read command history from disk."""
    if not session_path.is_dir():
        raise SessionNotFoundError(f"session does not exist: {session_path}")

    commands_path = session_path / "commands.jsonl"
    if not commands_path.is_file():
        raise SessionNotFoundError(f"commands.jsonl is missing: {session_path}")

    lines = commands_path.read_text(encoding="utf-8").splitlines()
    return [CommandRecord.from_dict(json.loads(line)) for line in lines if line.strip()]


def write_mutated_session(
    *,
    session_path: Path,
    metadata: SessionMetadata,
    scene: SceneSnapshot,
    commands: list[CommandRecord],
) -> None:
    """Write updated session state to disk using temp files and atomic replacement."""
    session_path.mkdir(parents=True, exist_ok=True)

    session_tmp = write_temp_text(
        session_path=session_path,
        target_name="session.json",
        content=json.dumps(metadata.to_dict(), indent=2) + "\n",
    )
    scene_tmp = write_temp_text(
        session_path=session_path,
        target_name="scene.json",
        content=json.dumps(scene.to_dict(), indent=2) + "\n",
    )
    commands_tmp = write_temp_text(
        session_path=session_path,
        target_name="commands.jsonl",
        content=serialize_commands(commands),
    )
    render_tmp = write_temp_render(session_path=session_path, metadata=metadata, scene=scene)

    session_tmp.replace(session_path / "session.json")
    scene_tmp.replace(session_path / "scene.json")
    commands_tmp.replace(session_path / "commands.jsonl")
    render_tmp.replace(session_path / metadata.paths.latest_render)


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


def serialize_commands(commands: list[CommandRecord]) -> str:
    """Serialize command history to JSONL."""
    if not commands:
        return ""
    return "\n".join(json.dumps(command.to_dict()) for command in commands) + "\n"


def write_temp_text(*, session_path: Path, target_name: str, content: str) -> Path:
    """Write a temp text file inside the session directory."""
    temporary_path = session_path / f".{target_name}.tmp"
    temporary_path.write_text(content, encoding="utf-8")
    return temporary_path


def write_temp_render(
    *,
    session_path: Path,
    metadata: SessionMetadata,
    scene: SceneSnapshot,
) -> Path:
    """Render a temp PNG file inside the session directory."""
    render_dir = session_path / "render"
    render_dir.mkdir(exist_ok=True)
    temporary_path = render_dir / ".latest.png.tmp"
    render_scene(scene, temporary_path, session_path=session_path)
    return temporary_path
