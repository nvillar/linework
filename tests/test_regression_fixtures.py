"""Regression fixtures for stable scene snapshots and PNG outputs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from linework.storage.models import SceneSnapshot
from linework.storage.session import (
    apply_batch,
    create_session,
    export_session,
    read_scene_snapshot,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "regressions"
FIXTURE_CASES = sorted(path for path in FIXTURES_ROOT.iterdir() if path.is_dir())


def _load_fixture_operations(fixture_path: Path) -> list[dict[str, object]]:
    """Read replayable operations from a fixture command log."""
    commands_path = fixture_path / "commands.jsonl"
    operations: list[dict[str, object]] = []
    for line in commands_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        operations.append(
            {
                "op": payload["op"],
                "payload": payload["payload"],
            }
        )
    return operations


@pytest.mark.parametrize("fixture_path", FIXTURE_CASES, ids=[path.name for path in FIXTURE_CASES])
def test_regression_fixture_replay_matches_expected_scene_and_png(
    tmp_path: Path,
    fixture_path: Path,
) -> None:
    expected_scene = SceneSnapshot.from_dict(
        json.loads((fixture_path / "scene.json").read_text(encoding="utf-8"))
    )
    session_path = tmp_path / fixture_path.name
    create_session(
        session=str(session_path),
        name=None,
        width=expected_scene.canvas.width,
        height=expected_scene.canvas.height,
        background=expected_scene.canvas.background,
    )

    fixture_assets = fixture_path / "assets"
    if fixture_assets.exists():
        shutil.copytree(fixture_assets, session_path / "assets", dirs_exist_ok=True)

    apply_batch(session_path, operations=_load_fixture_operations(fixture_path))

    actual_scene = read_scene_snapshot(session_path)
    assert actual_scene.to_dict() == expected_scene.to_dict()
    assert (session_path / "render" / "latest.png").read_bytes() == (
        fixture_path / "render" / "latest.png"
    ).read_bytes()

    exported_path = tmp_path / f"{fixture_path.name}.png"
    export_session(session_path, out=str(exported_path))
    assert exported_path.read_bytes() == (fixture_path / "render" / "latest.png").read_bytes()
