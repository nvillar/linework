"""Command record helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from mural.core.errors import CommandValidationError
from mural.core.objects import build_object
from mural.storage.ids import format_object_id, format_operation_id, iso_timestamp, utc_now
from mural.storage.models import CommandRecord

_OBJECT_ID = re.compile(r"^obj_(\d{6})$")

_DRAW_COMMANDS = {
    "draw.line",
    "draw.rect",
    "draw.ellipse",
    "draw.polyline",
    "draw.text",
    "draw.image",
}
_EDIT_COMMANDS = {
    "edit.line",
    "edit.rect",
    "edit.ellipse",
    "edit.polyline",
    "edit.text",
    "edit.image",
}


def next_operation_id(commands: Iterable[CommandRecord]) -> str:
    """Return the next operation identifier."""
    return format_operation_id(sum(1 for _ in commands) + 1)


def next_object_id(commands: Iterable[CommandRecord]) -> str:
    """Return the next object identifier based on command history."""
    max_index = 0
    for command in commands:
        object_id = command.payload.get("id")
        if not isinstance(object_id, str):
            continue
        match = _OBJECT_ID.fullmatch(object_id)
        if match is None:
            continue
        max_index = max(max_index, int(match.group(1)))
    return format_object_id(max_index + 1)


def normalize_command(
    *,
    op: str,
    payload: Mapping[str, object] | None,
    existing_commands: list[CommandRecord],
    session_path: Path,
) -> CommandRecord:
    """Normalize a command payload into a canonical command record."""
    normalized_payload = dict(payload or {})

    if op in _DRAW_COMMANDS:
        normalized_payload.setdefault("id", next_object_id(existing_commands))
        build_object(
            command=op,
            payload=normalized_payload,
            object_id=str(normalized_payload["id"]),
            session_path=session_path,
        )
    elif op in _EDIT_COMMANDS:
        object_id = normalized_payload.get("id")
        if not isinstance(object_id, str):
            raise CommandValidationError("id must be provided for edit commands")
    elif op == "delete":
        object_id = normalized_payload.get("id")
        if not isinstance(object_id, str):
            raise CommandValidationError("id must be provided for delete")
    elif op == "undo":
        if normalized_payload:
            raise CommandValidationError("undo does not accept a payload")
    else:
        raise CommandValidationError(f"unsupported command: {op}")

    timestamp = iso_timestamp(utc_now())
    op_id = format_operation_id(len(existing_commands) + 1)
    return CommandRecord(
        schema_version=1,
        op_id=op_id,
        timestamp=timestamp,
        op=op,
        payload=normalized_payload,
    )
