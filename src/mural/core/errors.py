"""Core scene and command errors."""

from __future__ import annotations


class SceneEngineError(RuntimeError):
    """Base error for scene and command processing."""


class CommandValidationError(SceneEngineError):
    """Raised when a command payload is invalid."""


class ObjectNotFoundError(SceneEngineError):
    """Raised when an object lookup fails."""
