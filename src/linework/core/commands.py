"""Command record helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from linework.core.errors import CommandValidationError, ObjectNotFoundError
from linework.core.objects import build_object
from linework.storage.ids import (
    format_batch_id,
    format_object_id,
    format_operation_id,
    iso_timestamp,
    utc_now,
)
from linework.storage.models import CommandRecord

_BATCH_ID = re.compile(r"^batch_(\d{6})$")
_OBJECT_ID = re.compile(r"^obj_(\d{6})$")

_DRAW_COMMANDS = {
    "draw.line",
    "draw.rect",
    "draw.ellipse",
    "draw.polyline",
    "draw.polygon",
    "draw.text",
    "draw.image",
}
_EDIT_COMMANDS = {
    "edit.line",
    "edit.rect",
    "edit.ellipse",
    "edit.polyline",
    "edit.polygon",
    "edit.text",
    "edit.image",
}


def next_object_id(commands: list[CommandRecord]) -> str:
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


def next_batch_id(commands: list[CommandRecord]) -> str:
    """Return the next batch identifier based on command history."""
    max_index = 0
    for command in commands:
        if command.batch_id is None:
            continue
        match = _BATCH_ID.fullmatch(command.batch_id)
        if match is None:
            continue
        max_index = max(max_index, int(match.group(1)))
    return format_batch_id(max_index + 1)


def _resolve_live_objects(commands: list[CommandRecord]) -> dict[str, dict[str, str | None]]:
    """Build a map of live objects from effective commands."""
    from linework.core.scene import resolve_effective_commands

    effective = resolve_effective_commands(commands)
    live: dict[str, dict[str, str | None]] = {}
    for cmd in effective:
        if cmd.op.startswith("draw."):
            obj_id = cmd.payload.get("id")
            if isinstance(obj_id, str):
                label = cmd.payload.get("label")
                live[obj_id] = {
                    "type": cmd.op.removeprefix("draw."),
                    "label": label if isinstance(label, str) else None,
                }
        elif cmd.op.startswith("edit."):
            obj_id = cmd.payload.get("id")
            if isinstance(obj_id, str) and obj_id in live and "label" in cmd.payload:
                label = cmd.payload.get("label")
                live[obj_id]["label"] = label if isinstance(label, str) else None
        elif cmd.op == "delete":
            obj_id = cmd.payload.get("id")
            if isinstance(obj_id, str):
                live.pop(obj_id, None)
    return live


def normalize_command(
    *,
    op: str,
    payload: Mapping[str, object] | None,
    existing_commands: list[CommandRecord],
    session_path: Path,
    batch_id: str | None = None,
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
        object_id = _resolve_target_object_id(
            normalized_payload=normalized_payload,
            existing_commands=existing_commands,
            for_delete=False,
        )
        _validate_target_object(existing_commands, object_id, op)
    elif op == "delete":
        object_id = _resolve_target_object_id(
            normalized_payload=normalized_payload,
            existing_commands=existing_commands,
            for_delete=True,
        )
        normalized_payload = {"id": object_id}
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
        batch_id=batch_id,
    )


def _validate_target_object(
    existing_commands: list[CommandRecord],
    object_id: str,
    edit_op: str,
) -> None:
    """Validate that the target object exists and matches the edit command type."""
    live = _resolve_live_objects(existing_commands)
    if object_id not in live:
        raise ObjectNotFoundError(f"object not found: {object_id}")
    expected_type = edit_op.removeprefix("edit.")
    actual_type = str(live[object_id]["type"])
    if actual_type != expected_type:
        raise CommandValidationError(
            f"object {object_id} is type '{actual_type}', not compatible with '{edit_op}'"
        )


def _resolve_target_object_id(
    *,
    normalized_payload: dict[str, object],
    existing_commands: list[CommandRecord],
    for_delete: bool,
) -> str:
    """Resolve a target object by id or unique live label."""
    object_id = normalized_payload.get("id")
    if object_id is not None and not isinstance(object_id, str):
        raise CommandValidationError("id must be a string")
    if isinstance(object_id, str):
        return object_id

    selector_label = normalized_payload.get("label")
    if selector_label is None:
        if for_delete:
            raise CommandValidationError("id or label must be provided for delete")
        raise CommandValidationError("id or label must be provided for edit commands")
    if not isinstance(selector_label, str):
        raise CommandValidationError("label must be a string")

    resolved_id = _resolve_unique_object_id_by_label(
        existing_commands=existing_commands,
        label=selector_label,
    )
    normalized_payload["id"] = resolved_id
    normalized_payload.pop("label", None)
    return resolved_id


def _resolve_unique_object_id_by_label(
    *,
    existing_commands: list[CommandRecord],
    label: str,
) -> str:
    """Resolve one live object id from a unique label."""
    live = _resolve_live_objects(existing_commands)
    matches = [object_id for object_id, info in live.items() if info.get("label") == label]
    if not matches:
        raise ObjectNotFoundError(f"object not found for label: {label}")
    if len(matches) > 1:
        raise CommandValidationError(f"label is ambiguous: {label}")
    return matches[0]
