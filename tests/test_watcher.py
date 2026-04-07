"""Tests for watcher helpers and non-interactive watch logic."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from linework.storage.lock import writer_lock
from linework.storage.session import create_session
from linework.watch import (
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


def test_compute_initial_window_size_preserves_canvas_when_it_fits() -> None:
    assert compute_initial_window_size(
        canvas_width=400,
        canvas_height=300,
        screen_width=900,
        screen_height=700,
    ) == (400, 300)


def test_scale_to_fit_preserves_aspect_ratio() -> None:
    assert scale_to_fit(
        content_width=1200,
        content_height=800,
        frame_width=300,
        frame_height=300,
    ) == (300, 200)


def test_scale_to_fit_falls_back_to_original_size_for_non_positive_frame() -> None:
    assert scale_to_fit(
        content_width=120,
        content_height=80,
        frame_width=0,
        frame_height=200,
    ) == (120, 80)


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
    import linework.watch as watch_module

    render_path = tmp_path / "latest.png"
    Image.new("RGBA", (12, 8), (0, 255, 0, 255)).save(render_path, format="PNG")

    signatures = iter([(1, 10), (2, 10)])

    def fake_signature(path: Path) -> tuple[int, int]:
        assert path == render_path
        return next(signatures)

    monkeypatch.setattr(watch_module, "_read_render_signature", fake_signature)

    with pytest.raises(RetryableWatchError, match="render changed during read"):
        load_render_image(render_path, previous_signature=None)


def test_load_render_image_retries_when_render_is_missing(tmp_path: Path) -> None:
    with pytest.raises(RetryableWatchError, match="unable to read render"):
        load_render_image(tmp_path / "missing.png", previous_signature=None)


# ---------------------------------------------------------------------------
# _ensure_tcl_library tests
# ---------------------------------------------------------------------------


def test_ensure_tcl_library_sets_env_when_init_tcl_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TCL_LIBRARY is set when init.tcl exists next to the real Python binary."""
    import os

    from linework.watch import _ensure_tcl_library

    # Build a fake Python install layout: prefix/lib/tcl9.0/init.tcl
    fake_prefix = tmp_path / "python-install"
    tcl_dir = fake_prefix / "lib" / "tcl9.0"
    tcl_dir.mkdir(parents=True)
    (tcl_dir / "init.tcl").write_text("# stub")
    fake_exe = fake_prefix / "bin" / "python3.12"
    fake_exe.parent.mkdir(parents=True)
    fake_exe.write_text("# stub")

    monkeypatch.delenv("TCL_LIBRARY", raising=False)
    monkeypatch.setattr(os.path, "realpath", lambda _path: str(fake_exe))

    _ensure_tcl_library()

    assert os.environ.get("TCL_LIBRARY") == str(tcl_dir)


def test_ensure_tcl_library_is_noop_when_already_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TCL_LIBRARY is not overwritten when it is already set."""
    import os

    from linework.watch import _ensure_tcl_library

    monkeypatch.setenv("TCL_LIBRARY", "/custom/tcl")
    _ensure_tcl_library()
    assert os.environ["TCL_LIBRARY"] == "/custom/tcl"


def test_ensure_tcl_library_is_noop_when_no_tcl_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TCL_LIBRARY is not set when no tcl*/init.tcl exists."""
    import os

    from linework.watch import _ensure_tcl_library

    fake_prefix = tmp_path / "python-install"
    lib_dir = fake_prefix / "lib"
    lib_dir.mkdir(parents=True)
    fake_exe = fake_prefix / "bin" / "python3.12"
    fake_exe.parent.mkdir(parents=True)
    fake_exe.write_text("# stub")

    monkeypatch.delenv("TCL_LIBRARY", raising=False)
    monkeypatch.setattr(os.path, "realpath", lambda _path: str(fake_exe))

    _ensure_tcl_library()

    assert os.environ.get("TCL_LIBRARY") is None


# ---------------------------------------------------------------------------
# Visibility confirmation tests
# ---------------------------------------------------------------------------


def test_check_visibility_calls_callback_when_viewable() -> None:
    """on_visible callback is invoked when the window is viewable."""
    from linework.watch import SessionWatcherApp

    called = False

    class FakeRoot:
        """Minimal stub for tkinter.Tk used only by _check_visibility."""

        def winfo_exists(self) -> bool:
            return True

        def winfo_viewable(self) -> bool:
            return True

        def after(self, ms: int, func: object) -> None:
            pass

    watcher = object.__new__(SessionWatcherApp)
    watcher._root = FakeRoot()

    def on_visible() -> None:
        nonlocal called
        called = True

    watcher._check_visibility(on_visible, elapsed_ms=0)
    assert called


def test_check_visibility_destroys_window_on_timeout() -> None:
    """The window is destroyed when visibility is never achieved."""
    from linework.watch import _VISIBILITY_CHECK_MAX_WAIT_MS, SessionWatcherApp

    destroyed = False

    class FakeRoot:
        def winfo_exists(self) -> bool:
            return True

        def winfo_viewable(self) -> bool:
            return False

        def after(self, ms: int, func: object) -> None:
            pass

        def destroy(self) -> None:
            nonlocal destroyed
            destroyed = True

    watcher = object.__new__(SessionWatcherApp)
    watcher._root = FakeRoot()

    watcher._check_visibility(lambda: None, elapsed_ms=_VISIBILITY_CHECK_MAX_WAIT_MS)
    assert destroyed


def test_check_visibility_retries_when_not_yet_viewable() -> None:
    """A retry is scheduled when the window exists but is not yet viewable."""
    from linework.watch import _VISIBILITY_CHECK_INTERVAL_MS, SessionWatcherApp

    scheduled: list[tuple[int, object]] = []

    class FakeRoot:
        def winfo_exists(self) -> bool:
            return True

        def winfo_viewable(self) -> bool:
            return False

        def after(self, ms: int, func: object) -> None:
            scheduled.append((ms, func))

        def destroy(self) -> None:
            pass

    watcher = object.__new__(SessionWatcherApp)
    watcher._root = FakeRoot()

    watcher._check_visibility(lambda: None, elapsed_ms=0)

    assert len(scheduled) == 1
    assert scheduled[0][0] == _VISIBILITY_CHECK_INTERVAL_MS
