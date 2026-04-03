"""Session and scene data models."""

from __future__ import annotations

from dataclasses import dataclass


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
