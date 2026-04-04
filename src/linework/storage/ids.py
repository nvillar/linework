"""Identifier helpers for sessions and scene objects."""

from __future__ import annotations

import re
from datetime import UTC, datetime

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def iso_timestamp(value: datetime) -> str:
    """Format a timestamp using a stable UTC wire format."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_slug(name: str | None) -> str:
    """Normalize a name into a filesystem-safe slug."""
    if name is None:
        return "session"

    normalized = _NON_ALNUM.sub("-", name.strip().lower()).strip("-")
    return normalized or "session"


def build_session_id(created_at: datetime, slug: str) -> str:
    """Build a session identifier from timestamp and slug."""
    timestamp = created_at.astimezone(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{slug}"


def format_object_id(index: int) -> str:
    """Format an object identifier."""
    return f"obj_{index:06d}"


def format_operation_id(index: int) -> str:
    """Format an operation identifier."""
    return f"op_{index:06d}"


def format_batch_id(index: int) -> str:
    """Format a batch identifier."""
    return f"batch_{index:06d}"
