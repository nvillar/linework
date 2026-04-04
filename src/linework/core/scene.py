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
    effective_actions: list[tuple[str | None, list[CommandRecord]]] = []
    for command in commands:
        if command.op == "undo":
            _apply_undo(effective_actions=effective_actions, undo_batch_id=command.batch_id)
            continue
        _append_effective_command(effective_actions=effective_actions, command=command)
    return [item for _, commands_in_action in effective_actions for item in commands_in_action]


def _append_effective_command(
    *,
    effective_actions: list[tuple[str | None, list[CommandRecord]]],
    command: CommandRecord,
) -> None:
    """Append a non-undo command to the effective action stack."""
    if (
        command.batch_id is not None
        and effective_actions
        and effective_actions[-1][0] == command.batch_id
    ):
        effective_actions[-1][1].append(command)
        return
    effective_actions.append((command.batch_id, [command]))


def _apply_undo(
    *,
    effective_actions: list[tuple[str | None, list[CommandRecord]]],
    undo_batch_id: str | None,
) -> None:
    """Apply one undo command to the effective action stack."""
    if not effective_actions:
        raise CommandValidationError("nothing to undo")

    top_batch_id, top_commands = effective_actions[-1]
    if undo_batch_id is not None and top_batch_id == undo_batch_id:
        top_commands.pop()
        if not top_commands:
            effective_actions.pop()
        return

    effective_actions.pop()


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
