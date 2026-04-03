"""Tests for watcher helpers and non-interactive watch logic."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from mural.storage.lock import writer_lock
from mural.storage.session import create_session
from mural.watch import (
    RetryableWatchError,
    WatchError,
    compute_initial_window_size,
    load_render_image,
    read_watch_target,
    scale_to_fit,
    validate_interval_ms,
)


def create_watch_session(tmp_path: Path) -> Path:
    """Create a session fixture for watcher tests."""
    session_path = tmp_path / "watch-session"
    create_session(
        session=str(session_path),
        name=None,
        width=1200,
        height=800,
        background="#FFFFFF",
    )
    return session_path


def test_read_watch_target_is_lock_free(tmp_path: Path) -> None:
    session_path = create_watch_session(tmp_path)

    with writer_lock(session_path):
        target = read_watch_target(session_path)

    assert target.session_path == session_path
    assert target.session_id == "watch-session"
    assert target.latest_render == session_path / "render" / "latest.png"


def test_validate_interval_requires_positive() -> None:
    assert validate_interval_ms(250) == 250
    with pytest.raises(WatchError, match="interval_ms must be positive"):
        validate_interval_ms(0)


def test_compute_initial_window_size_caps_to_screen() -> None:
    assert compute_initial_window_size(
        canvas_width=1200,
        canvas_height=800,
        screen_width=900,
        screen_height=700,
    ) == (900, 700)


def test_scale_to_fit_preserves_aspect_ratio() -> None:
    assert scale_to_fit(
        content_width=1200,
        content_height=800,
        frame_width=300,
        frame_height=300,
    ) == (300, 200)


def test_load_render_image_skips_unchanged_render(tmp_path: Path) -> None:
    render_path = tmp_path / "latest.png"
    Image.new("RGBA", (12, 8), (255, 0, 0, 255)).save(render_path, format="PNG")

    signature, image = load_render_image(render_path, previous_signature=None)
    assert image is not None
    assert image.size == (12, 8)

    second_signature, second_image = load_render_image(render_path, previous_signature=signature)
    assert second_signature == signature
    assert second_image is None


def test_load_render_image_retries_when_render_changes_mid_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mural.watch as watch_module

    render_path = tmp_path / "latest.png"
    Image.new("RGBA", (12, 8), (0, 255, 0, 255)).save(render_path, format="PNG")

    signatures = iter([(1, 10), (2, 10)])

    def fake_signature(path: Path) -> tuple[int, int]:
        assert path == render_path
        return next(signatures)

    monkeypatch.setattr(watch_module, "_read_render_signature", fake_signature)

    with pytest.raises(RetryableWatchError, match="render changed during read"):
        load_render_image(render_path, previous_signature=None)
