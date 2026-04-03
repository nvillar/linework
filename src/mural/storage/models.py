"""Session and scene data models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class Canvas:
    """Canvas metadata stored with a session."""

    width: int
    height: int
    background: str

    def to_dict(self) -> dict[str, object]:
        """Serialize the canvas metadata."""
        return {
            "width": self.width,
            "height": self.height,
            "background": self.background,
        }


@dataclass(frozen=True)
class SessionPaths:
    """Relative paths stored in session metadata."""

    scene: str = "scene.json"
    commands: str = "commands.jsonl"
    latest_render: str = "render/latest.png"
    assets_dir: str = "assets"

    def to_dict(self) -> dict[str, str]:
        """Serialize relative session paths."""
        return {
            "scene": self.scene,
            "commands": self.commands,
            "latest_render": self.latest_render,
            "assets_dir": self.assets_dir,
        }


@dataclass(frozen=True)
class SessionMetadata:
    """Top-level session metadata."""

    schema_version: int
    session_id: str
    name: str
    created_at: str
    updated_at: str
    canvas: Canvas
    paths: SessionPaths

    def to_dict(self) -> dict[str, object]:
        """Serialize session metadata."""
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "canvas": self.canvas.to_dict(),
            "paths": self.paths.to_dict(),
        }


@dataclass(frozen=True)
class SceneSnapshot:
    """Current derived scene state."""

    schema_version: int
    session_id: str
    canvas: Canvas
    objects: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        """Serialize the scene snapshot."""
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "canvas": self.canvas.to_dict(),
            "objects": self.objects,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> SceneSnapshot:
        """Deserialize a scene snapshot."""
        canvas_payload = require_mapping(payload.get("canvas"), field="canvas")
        return cls(
            schema_version=require_int(payload.get("schema_version"), field="schema_version"),
            session_id=require_str(payload.get("session_id"), field="session_id"),
            canvas=Canvas(
                width=require_int(canvas_payload.get("width"), field="canvas.width"),
                height=require_int(canvas_payload.get("height"), field="canvas.height"),
                background=require_str(canvas_payload.get("background"), field="canvas.background"),
            ),
            objects=require_object_list(payload.get("objects"), field="objects"),
        )


@dataclass(frozen=True)
class CreatedSession:
    """Created-session result returned to the CLI."""

    session_path: str
    session_id: str
    name: str
    canvas: Canvas
    latest_render: str

    def to_dict(self) -> dict[str, object]:
        """Serialize created-session output."""
        return {
            "session_path": self.session_path,
            "session_id": self.session_id,
            "name": self.name,
            "canvas": self.canvas.to_dict(),
            "latest_render": self.latest_render,
        }


@dataclass(frozen=True)
class CommandRecord:
    """Canonical append-only command record."""

    schema_version: int
    op_id: str
    timestamp: str
    op: str
    payload: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        """Serialize the command record."""
        return {
            "schema_version": self.schema_version,
            "op_id": self.op_id,
            "timestamp": self.timestamp,
            "op": self.op,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> CommandRecord:
        """Deserialize a command record."""
        return cls(
            schema_version=require_int(payload.get("schema_version"), field="schema_version"),
            op_id=require_str(payload.get("op_id"), field="op_id"),
            timestamp=require_str(payload.get("timestamp"), field="timestamp"),
            op=require_str(payload.get("op"), field="op"),
            payload=require_mapping(payload.get("payload"), field="payload"),
        )


@dataclass(frozen=True)
class MutationResult:
    """Result of applying a mutating command to a session."""

    op_id: str
    op: str
    object_id: str | None
    session_path: str
    scene_object_count: int
    latest_render: str

    def to_dict(self) -> dict[str, object]:
        """Serialize a mutation result."""
        return {
            "op_id": self.op_id,
            "op": self.op,
            "object_id": self.object_id,
            "session_path": self.session_path,
            "scene_object_count": self.scene_object_count,
            "latest_render": self.latest_render,
        }


def require_int(value: object, *, field: str) -> int:
    """Require an integer field."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def require_str(value: object, *, field: str) -> str:
    """Require a string field."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def require_mapping(value: object, *, field: str) -> dict[str, object]:
    """Require a mapping-like dictionary field."""
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return cast(dict[str, object], value)


def require_object_list(value: object, *, field: str) -> list[dict[str, object]]:
    """Require a list of object dictionaries."""
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")

    normalized: list[dict[str, object]] = []
    for index, item in enumerate(value):
        normalized.append(require_mapping(item, field=f"{field}[{index}]"))
    return normalized
