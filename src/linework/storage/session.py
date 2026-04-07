"""Session creation and storage helpers."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from linework.config import sessions_root
from linework.constants import HEX_COLOR
from linework.core.commands import next_batch_id, normalize_command
from linework.core.errors import SceneEngineError
from linework.core.objects import resolve_asset_path
from linework.core.scene import derive_scene
from linework.render.png import render_blank_canvas, render_scene
from linework.storage.ids import build_session_id, iso_timestamp, normalize_slug, utc_now
from linework.storage.lock import writer_lock
from linework.storage.models import (
    BatchResult,
    Canvas,
    CommandRecord,
    CreatedSession,
    InspectResult,
    MutationResult,
    SceneSnapshot,
    SessionMetadata,
    SessionPaths,
)

_HEX_COLOR = HEX_COLOR


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
    reuse_empty_directory = False
    with writer_lock(session_path):
        if session_path.exists():
            if not session_path.is_dir() or any(session_path.iterdir()):
                raise SessionAlreadyExistsError(
                    f"session already exists: {session_path}. "
                    "Reuse this same session with draw/edit/run/inspect/export by passing "
                    f"--session {session_path}, or choose a different path for `linework new`."
                )
            reuse_empty_directory = True

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
            if reuse_empty_directory:
                session_path.rmdir()
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
        return _commit_mutation(
            session_path=resolved_session_path,
            metadata=metadata,
            commands=commands,
            normalized_command=normalized_command,
        )


def apply_imported_image(
    session_path: str | Path,
    *,
    source: str,
    payload: dict[str, object] | None = None,
) -> MutationResult:
    """Import an external image into the session and create a draw.image command."""
    resolved_session_path = Path(session_path).expanduser().resolve()

    with writer_lock(resolved_session_path):
        metadata = read_session_metadata(resolved_session_path)
        commands = read_commands(resolved_session_path)
        asset_path, source_path, created_asset_copy = _import_image_asset(
            session_path=resolved_session_path,
            assets_dir=metadata.paths.assets_dir,
            source=source,
        )
        command_payload = dict(payload or {})
        command_payload["asset_path"] = asset_path
        command_payload["source_path"] = source_path
        completed = False
        try:
            normalized_command = normalize_command(
                op="draw.image",
                payload=command_payload,
                existing_commands=commands,
                session_path=resolved_session_path,
            )
            result = _commit_mutation(
                session_path=resolved_session_path,
                metadata=metadata,
                commands=commands,
                normalized_command=normalized_command,
            )
            completed = True
            return result
        finally:
            if not completed and created_asset_copy is not None and created_asset_copy.exists():
                created_asset_copy.unlink()


def _commit_mutation(
    *,
    session_path: Path,
    metadata: SessionMetadata,
    commands: list[CommandRecord],
    normalized_command: CommandRecord,
) -> MutationResult:
    """Commit a normalized command to session storage and return its result."""
    updated_commands = [*commands, normalized_command]
    updated_scene = derive_scene(
        canvas=metadata.canvas,
        commands=updated_commands,
        session_path=session_path,
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
        session_path=session_path,
        metadata=updated_metadata,
        scene=updated_scene,
        commands=updated_commands,
    )

    object_id = normalized_command.payload.get("id")
    return MutationResult(
        op_id=normalized_command.op_id,
        op=normalized_command.op,
        object_id=object_id if isinstance(object_id, str) else None,
        session_path=str(session_path),
        scene_object_count=len(updated_scene.objects),
        latest_render=str(session_path / updated_metadata.paths.latest_render),
    )


def _import_image_asset(
    *,
    session_path: Path,
    assets_dir: str,
    source: str,
) -> tuple[str, str, Path | None]:
    """Copy an external image file into the session assets directory."""
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise SessionValidationError(f"image source does not exist: {source_path}")
    _validate_image_file(source_path, error_prefix="invalid image source")

    assets_root = session_path / assets_dir
    assets_root.mkdir(parents=True, exist_ok=True)
    destination = _resolve_import_destination(assets_root=assets_root, source_path=source_path)

    created_asset_copy: Path | None = None
    if not destination.exists() or destination.resolve() != source_path:
        shutil.copy2(source_path, destination)
        created_asset_copy = destination

    asset_path = destination.relative_to(session_path.resolve()).as_posix()
    return asset_path, str(source_path), created_asset_copy


def _resolve_import_destination(*, assets_root: Path, source_path: Path) -> Path:
    """Choose a normalized, collision-safe destination path under assets/."""
    stem = normalize_slug(source_path.stem or "image")
    if stem == "session" and source_path.stem.strip().lower() != "session":
        stem = "image"
    suffix = source_path.suffix.lower()

    candidate = assets_root / f"{stem}{suffix}"
    if candidate.exists() and candidate.resolve() == source_path:
        return candidate

    index = 2
    while candidate.exists():
        candidate = assets_root / f"{stem}-{index}{suffix}"
        if candidate.exists() and candidate.resolve() == source_path:
            return candidate
        index += 1
    return candidate


def _validate_image_file(path: Path, *, error_prefix: str) -> None:
    """Verify that a path contains a readable image."""
    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise SessionValidationError(f"{error_prefix}: {path}") from exc


def _validate_exportable_assets(scene: SceneSnapshot, *, session_path: Path) -> None:
    """Ensure all scene image assets exist and are readable before export."""
    for object_data in scene.objects:
        if object_data.get("type") != "image":
            continue

        asset_path = object_data.get("asset_path")
        if not isinstance(asset_path, str):
            raise SessionValidationError("image asset_path must be a string")

        try:
            asset_full_path = resolve_asset_path(session_path=session_path, asset_path=asset_path)
        except SceneEngineError as exc:
            raise SessionValidationError(str(exc)) from exc

        if not asset_full_path.is_file():
            raise SessionValidationError(f"image asset missing: {asset_path}")

        _validate_image_file(asset_full_path, error_prefix="invalid image asset")


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
    """Write updated session state to disk atomically.

    All files are prepared in a staging directory, then swapped into the
    session directory via individual atomic ``replace()`` calls.  If any
    staging step fails, the session directory is left untouched.
    """
    session_path.mkdir(parents=True, exist_ok=True)
    parent = session_path.parent
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{session_path.name}.mut-", dir=parent))

    try:
        (staging_dir / "render").mkdir()
        write_json(staging_dir / "session.json", metadata.to_dict())
        write_json(staging_dir / "scene.json", scene.to_dict())
        (staging_dir / "commands.jsonl").write_text(serialize_commands(commands), encoding="utf-8")
        render_scene(scene, staging_dir / "render" / "latest.png", session_path=session_path)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    # Swap staged files into the live session directory.
    try:
        (staging_dir / "session.json").replace(session_path / "session.json")
        (staging_dir / "scene.json").replace(session_path / "scene.json")
        (staging_dir / "commands.jsonl").replace(session_path / "commands.jsonl")
        (session_path / "render").mkdir(exist_ok=True)
        (staging_dir / "render" / "latest.png").replace(session_path / metadata.paths.latest_render)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


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


def _derive_scene_snapshot(
    *,
    metadata: SessionMetadata,
    commands: list[CommandRecord],
    session_path: Path,
) -> SceneSnapshot:
    """Derive the current scene snapshot for a command list."""
    return derive_scene(
        canvas=metadata.canvas,
        commands=commands,
        session_path=session_path,
        session_id=metadata.session_id,
    )


def _build_batch_result(
    *,
    metadata: SessionMetadata,
    commands: list[CommandRecord],
    results: list[dict[str, object]],
    failed: dict[str, str] | None,
    session_path: Path,
) -> BatchResult:
    """Build a batch result from the current session state."""
    scene = _derive_scene_snapshot(metadata=metadata, commands=commands, session_path=session_path)
    return BatchResult(
        applied=len(results),
        failed=failed,
        results=results,
        session_path=str(session_path),
        scene_object_count=len(scene.objects),
        latest_render=str(session_path / metadata.paths.latest_render),
    )


def inspect_session(session_path: str | Path) -> InspectResult:
    """Read and return the current session state for inspection."""
    resolved = Path(session_path).expanduser().resolve()
    metadata = read_session_metadata(resolved)
    scene = read_scene_snapshot(resolved)
    return InspectResult(
        session_path=str(resolved),
        session_id=metadata.session_id,
        canvas=metadata.canvas,
        object_count=len(scene.objects),
        latest_render=str(resolved / metadata.paths.latest_render),
        objects=scene.objects,
    )


def export_session(session_path: str | Path, *, output: str) -> str:
    """Export the current scene render to an output path."""
    resolved = Path(session_path).expanduser().resolve()
    scene = read_scene_snapshot(resolved)
    _validate_exportable_assets(scene, session_path=resolved)

    destination = Path(output).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{destination.name}.tmp-",
        suffix=destination.suffix or ".png",
        dir=destination.parent,
        delete=False,
    ) as handle:
        temp_output = Path(handle.name)

    try:
        render_scene(scene, temp_output, session_path=resolved)
        temp_output.replace(destination)
    finally:
        if temp_output.exists():
            temp_output.unlink()
    return str(destination)


def apply_batch(
    session_path: str | Path,
    *,
    operations: list[dict[str, object]],
) -> BatchResult:
    """Apply a batch of JSONL operations to a session.

    Holds the writer lock for the entire batch. Renders once at the end.
    Returns per-operation results and stops on first failure.
    """
    resolved = Path(session_path).expanduser().resolve()
    results: list[dict[str, object]] = []
    failed: dict[str, str] | None = None

    with writer_lock(resolved):
        metadata = read_session_metadata(resolved)
        commands = read_commands(resolved)
        batch_id = next_batch_id(commands)

        for entry in operations:
            op = entry.get("op")
            payload = entry.get("payload")
            if not isinstance(op, str):
                failed = {"op": str(op), "error": "op must be a string"}
                break
            if payload is not None and not isinstance(payload, dict):
                failed = {"op": op, "error": "payload must be a mapping"}
                break

            try:
                normalized = normalize_command(
                    op=op,
                    payload=payload,
                    existing_commands=commands,
                    session_path=resolved,
                    batch_id=batch_id,
                )
            except (OSError, SceneEngineError) as exc:
                failed = {"op": op, "error": str(exc)}
                break

            commands = [*commands, normalized]
            obj_id = normalized.payload.get("id")
            results.append(
                {
                    "op_id": normalized.op_id,
                    "op": normalized.op,
                    "object_id": obj_id if isinstance(obj_id, str) else None,
                }
            )

        if not results:
            return _build_batch_result(
                metadata=metadata,
                commands=commands,
                results=[],
                failed=failed,
                session_path=resolved,
            )

        scene = _derive_scene_snapshot(metadata=metadata, commands=commands, session_path=resolved)
        last_command = commands[-1]
        updated_metadata = SessionMetadata(
            schema_version=metadata.schema_version,
            session_id=metadata.session_id,
            name=metadata.name,
            created_at=metadata.created_at,
            updated_at=last_command.timestamp,
            canvas=metadata.canvas,
            paths=metadata.paths,
        )
        write_mutated_session(
            session_path=resolved,
            metadata=updated_metadata,
            scene=scene,
            commands=commands,
        )

    return BatchResult(
        applied=len(results),
        failed=failed,
        results=results,
        session_path=str(resolved),
        scene_object_count=len(scene.objects),
        latest_render=str(resolved / updated_metadata.paths.latest_render),
    )


# ---------------------------------------------------------------------------
# Session listing and cleanup
# ---------------------------------------------------------------------------


def count_auto_sessions() -> int:
    """Count sessions in the default sessions root."""
    root = sessions_root()
    if not root.is_dir():
        return 0
    return sum(1 for child in root.iterdir() if child.is_dir())


def list_sessions() -> list[dict[str, str]]:
    """List sessions in the default sessions root with metadata."""
    root = sessions_root()
    if not root.is_dir():
        return []

    sessions: list[dict[str, str]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        session_json = child / "session.json"
        scene_json = child / "scene.json"
        name = child.name
        age = _format_session_age(child)
        objects = "?"
        if scene_json.is_file():
            try:
                scene = json.loads(scene_json.read_text(encoding="utf-8"))
                objects = str(len(scene.get("objects", [])))
            except (json.JSONDecodeError, OSError):
                pass
        if session_json.is_file():
            try:
                meta = json.loads(session_json.read_text(encoding="utf-8"))
                name = meta.get("name", child.name)
            except (json.JSONDecodeError, OSError):
                pass
        sessions.append(
            {
                "name": name,
                "age": age,
                "objects": objects,
                "path": str(child),
            }
        )
    return sessions


def prune_sessions(*, older_than_days: int) -> list[str]:
    """Delete sessions older than a threshold. Returns removed session names."""
    root = sessions_root()
    if not root.is_dir():
        return []

    import time

    cutoff = time.time() - older_than_days * 86400
    removed: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        session_json = child / "session.json"
        if not session_json.is_file():
            continue
        try:
            mtime = session_json.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child.name)
    return removed


def _format_session_age(session_dir: Path) -> str:
    """Format session age from its session.json mtime."""
    session_json = session_dir / "session.json"
    if not session_json.is_file():
        return "?"
    try:
        import time

        age_s = time.time() - session_json.stat().st_mtime
    except OSError:
        return "?"
    if age_s < 3600:
        return f"{int(age_s / 60)}m"
    if age_s < 86400:
        return f"{age_s / 3600:.1f}h"
    return f"{age_s / 86400:.1f}d"
