"""Command record helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from linework.capabilities import (
    DRAW_OPERATIONS,
    EDIT_OPERATIONS,
    stored_object_type_for_op,
    unsupported_command_message,
)
from linework.core.errors import CommandValidationError, ObjectNotFoundError
from linework.core.objects import ObjectDict, apply_edit, build_object, require_positive_number
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


def _resolve_live_objects(
    commands: list[CommandRecord], *, session_path: Path
) -> dict[str, ObjectDict]:
    """Build a map of live objects from effective commands."""
    from linework.core.scene import apply_effective_command, resolve_effective_commands

    effective = resolve_effective_commands(commands)
    objects: list[ObjectDict] = []
    for command in effective:
        objects = apply_effective_command(
            objects=objects,
            command=command,
            session_path=session_path,
        )
    return {
        object_id: object_data
        for object_data in objects
        if isinstance((object_id := object_data.get("id")), str)
    }


def normalize_command(
    *,
    op: str,
    payload: Mapping[str, object] | None,
    existing_commands: list[CommandRecord],
    session_path: Path,
    batch_id: str | None = None,
) -> CommandRecord:
    """Normalize a command payload into a canonical command record."""
    normalized_payload = _normalize_alias_payload(op=op, payload=dict(payload or {}))

    if op in DRAW_OPERATIONS:
        normalized_payload.setdefault("id", next_object_id(existing_commands))
        build_object(
            command=op,
            payload=normalized_payload,
            object_id=str(normalized_payload["id"]),
            session_path=session_path,
        )
    elif op in EDIT_OPERATIONS:
        object_id = _resolve_target_object_id(
            normalized_payload=normalized_payload,
            existing_commands=existing_commands,
            session_path=session_path,
            for_delete=False,
        )
        existing_object = _validate_target_object(
            existing_commands,
            object_id,
            op,
            session_path=session_path,
        )
        apply_edit(existing=existing_object, payload=normalized_payload, session_path=session_path)
    elif op == "delete":
        object_id = _resolve_target_object_id(
            normalized_payload=normalized_payload,
            existing_commands=existing_commands,
            session_path=session_path,
            for_delete=True,
        )
        normalized_payload = {"id": object_id}
    elif op == "undo":
        if normalized_payload:
            raise CommandValidationError("undo does not accept a payload")
    else:
        raise CommandValidationError(unsupported_command_message(op))

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
    *,
    session_path: Path,
) -> ObjectDict:
    """Validate that the target object exists and matches the edit command type."""
    live = _resolve_live_objects(existing_commands, session_path=session_path)
    existing = live.get(object_id)
    if existing is None:
        raise ObjectNotFoundError(f"object not found: {object_id}")
    expected_type = stored_object_type_for_op(edit_op)
    actual_type = str(existing["type"])
    if actual_type != expected_type:
        raise CommandValidationError(
            f"object {object_id} is type '{actual_type}', not compatible with '{edit_op}'"
        )
    return dict(existing)


def _resolve_target_object_id(
    *,
    normalized_payload: dict[str, object],
    existing_commands: list[CommandRecord],
    session_path: Path,
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
        session_path=session_path,
        label=selector_label,
    )
    normalized_payload["id"] = resolved_id
    normalized_payload.pop("label", None)
    return resolved_id


def _resolve_unique_object_id_by_label(
    *,
    existing_commands: list[CommandRecord],
    session_path: Path,
    label: str,
) -> str:
    """Resolve one live object id from a unique label."""
    live = _resolve_live_objects(existing_commands, session_path=session_path)
    matches = [
        object_id for object_id, object_data in live.items() if object_data.get("label") == label
    ]
    if not matches:
        raise ObjectNotFoundError(f"object not found for label: {label}")
    if len(matches) > 1:
        raise CommandValidationError(f"label is ambiguous: {label}")
    return matches[0]


def _normalize_alias_payload(op: str, payload: dict[str, object]) -> dict[str, object]:
    """Normalize convenience alias payloads before validation and storage."""
    if op not in {"draw.circle", "edit.circle"}:
        return payload

    if "radius" in payload:
        radius = require_positive_number(payload.get("radius"), field="radius")
        normalized = dict(payload)
        normalized.pop("radius", None)
        normalized["width"] = radius * 2.0
        normalized["height"] = radius * 2.0
        return normalized

    width = payload.get("width")
    height = payload.get("height")
    if width is None and height is None:
        if op == "draw.circle":
            raise CommandValidationError("radius must be provided for draw.circle")
        return payload

    normalized_width = require_positive_number(width, field="width")
    normalized_height = require_positive_number(height, field="height")
    if normalized_width != normalized_height:
        raise CommandValidationError("circle width and height must match")
    return payload
