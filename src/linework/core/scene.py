"""Scene mutation and replay helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from linework.core.errors import CommandValidationError, ObjectNotFoundError
from linework.core.objects import ObjectDict, apply_edit, build_object
from linework.storage.models import Canvas, CommandRecord, SceneSnapshot


def derive_scene(
    *,
    canvas: Canvas,
    commands: Iterable[CommandRecord],
    session_path: Path,
    session_id: str,
) -> SceneSnapshot:
    """Derive the current scene snapshot from command history."""
    effective_commands = resolve_effective_commands(commands)
    objects: list[ObjectDict] = []

    for command in effective_commands:
        objects = apply_effective_command(
            objects=objects,
            command=command,
            session_path=session_path,
        )

    return SceneSnapshot(
        schema_version=1,
        session_id=session_id,
        canvas=canvas,
        objects=objects,
    )


def resolve_effective_commands(commands: Iterable[CommandRecord]) -> list[CommandRecord]:
    """Collapse append-only history into the effective command list."""
    effective: list[CommandRecord] = []
    for command in commands:
        if command.op == "undo":
            if not effective:
                raise CommandValidationError("nothing to undo")
            effective.pop()
            continue
        effective.append(command)
    return effective


def apply_effective_command(
    *,
    objects: list[ObjectDict],
    command: CommandRecord,
    session_path: Path,
) -> list[ObjectDict]:
    """Apply a single non-undo command to the current object list."""
    if command.op.startswith("draw."):
        new_object = build_object(
            command=command.op,
            payload=command.payload,
            object_id=require_object_id(command.payload),
            session_path=session_path,
        )
        return [*objects, new_object]

    if command.op.startswith("edit."):
        target_id = require_object_id(command.payload)
        return edit_object(
            objects=objects,
            command_op=command.op,
            target_id=target_id,
            payload=command.payload,
            session_path=session_path,
        )

    if command.op == "delete":
        target_id = require_object_id(command.payload)
        return delete_object(objects=objects, target_id=target_id)

    raise CommandValidationError(f"unsupported command: {command.op}")


def edit_object(
    *,
    objects: list[ObjectDict],
    command_op: str,
    target_id: str,
    payload: Mapping[str, object],
    session_path: Path,
) -> list[ObjectDict]:
    """Apply an edit command to the target object."""
    updated: list[ObjectDict] = []
    found = False

    for existing in objects:
        if existing["id"] != target_id:
            updated.append(dict(existing))
            continue

        existing_type = str(existing["type"])
        expected_command = f"edit.{existing_type}"
        if command_op != expected_command:
            raise CommandValidationError(
                f"object {target_id} is type '{existing_type}', not compatible with '{command_op}'"
            )
        updated.append(apply_edit(existing=existing, payload=payload, session_path=session_path))
        found = True

    if not found:
        raise ObjectNotFoundError(f"object not found: {target_id}")

    return updated


def delete_object(*, objects: list[ObjectDict], target_id: str) -> list[ObjectDict]:
    """Delete an object by id from the scene."""
    remaining = [dict(existing) for existing in objects if existing["id"] != target_id]
    if len(remaining) == len(objects):
        raise ObjectNotFoundError(f"object not found: {target_id}")
    return remaining


def require_object_id(payload: Mapping[str, object]) -> str:
    """Require an object id from a payload."""
    object_id = payload.get("id")
    if not isinstance(object_id, str):
        raise CommandValidationError("id must be a string")
    return object_id
