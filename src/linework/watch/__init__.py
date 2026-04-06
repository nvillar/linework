"""Watcher UI layer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from linework.storage.session import read_session_metadata

DEFAULT_INTERVAL_MS = 250
RenderSignature = tuple[int, int]

_VISIBILITY_CHECK_INTERVAL_MS = 50
_VISIBILITY_CHECK_MAX_WAIT_MS = 2000


class WatchError(RuntimeError):
    """Base error for watcher operations."""


class WatchUnavailableError(WatchError):
    """Raised when the active environment cannot open the watcher UI."""


class RetryableWatchError(WatchError):
    """Raised when a render read should be retried on the next poll."""


@dataclass(frozen=True)
class WatchTarget:
    """Resolved session artifacts consumed by the watcher."""

    session_path: Path
    session_id: str
    latest_render: Path
    canvas_width: int
    canvas_height: int


@dataclass(frozen=True)
class Toolkit:
    """Lazy-loaded GUI toolkit modules."""

    tk: Any
    ttk: Any
    image_tk: Any


def load_toolkit() -> Toolkit:
    """Load the standard-library GUI stack on demand."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as exc:
        raise WatchUnavailableError(
            "tkinter is unavailable in the active Python environment"
        ) from exc

    try:
        from PIL import ImageTk
    except ImportError as exc:
        raise WatchUnavailableError(
            "ImageTk is unavailable in the active Python environment"
        ) from exc

    return Toolkit(tk=tk, ttk=ttk, image_tk=ImageTk)


def validate_interval_ms(interval_ms: int) -> int:
    """Require a positive polling interval."""
    if interval_ms <= 0:
        raise WatchError("interval_ms must be positive")
    return interval_ms


def read_watch_target(session_path: str | Path) -> WatchTarget:
    """Resolve watcher metadata for an existing session."""
    resolved = Path(session_path).expanduser().resolve()
    metadata = read_session_metadata(resolved)
    return WatchTarget(
        session_path=resolved,
        session_id=metadata.session_id,
        latest_render=resolved / metadata.paths.latest_render,
        canvas_width=metadata.canvas.width,
        canvas_height=metadata.canvas.height,
    )


def compute_initial_window_size(
    *,
    canvas_width: int,
    canvas_height: int,
    screen_width: int,
    screen_height: int,
) -> tuple[int, int]:
    """Choose the initial watcher window size."""
    return (
        max(1, min(canvas_width, screen_width)),
        max(1, min(canvas_height, screen_height)),
    )


def scale_to_fit(
    *,
    content_width: int,
    content_height: int,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int]:
    """Scale content to fit inside a frame while preserving aspect ratio."""
    if content_width <= 0 or content_height <= 0:
        raise WatchError("content dimensions must be positive")
    if frame_width <= 0 or frame_height <= 0:
        return content_width, content_height

    scale = min(frame_width / content_width, frame_height / content_height)
    return (
        max(1, int(content_width * scale)),
        max(1, int(content_height * scale)),
    )


def _read_render_signature(render_path: Path) -> RenderSignature:
    """Read the signature used to detect render changes."""
    stat = render_path.stat()
    return stat.st_mtime_ns, stat.st_size


def load_render_image(
    render_path: Path,
    *,
    previous_signature: RenderSignature | None,
) -> tuple[RenderSignature, Image.Image | None]:
    """Load the latest render when it has changed."""
    try:
        before = _read_render_signature(render_path)
        if previous_signature == before:
            return before, None

        with Image.open(render_path) as image:
            rendered = image.convert("RGBA").copy()

        after = _read_render_signature(render_path)
    except (FileNotFoundError, OSError, UnidentifiedImageError) as exc:
        raise RetryableWatchError(f"unable to read render: {render_path}") from exc

    if before != after:
        raise RetryableWatchError("render changed during read")

    return after, rendered


class SessionWatcherApp:
    """Minimal polling watcher window for a linework session."""

    def __init__(self, *, target: WatchTarget, interval_ms: int) -> None:
        self._target = target
        self._interval_ms = validate_interval_ms(interval_ms)
        self._toolkit = load_toolkit()
        self._root = self._create_root()
        self._image_label = self._create_layout()
        self._render_signature: RenderSignature | None = None
        self._current_image: Image.Image | None = None
        self._photo_image: Any | None = None

    def _create_root(self) -> Any:
        """Create and configure the top-level watcher window."""
        try:
            root = self._toolkit.tk.Tk()
        except self._toolkit.tk.TclError as exc:
            raise WatchUnavailableError(
                f"watcher UI is unavailable in this environment: {exc}"
            ) from exc

        root.title(f"linework watch - {self._target.session_id}")
        initial_width, initial_height = compute_initial_window_size(
            canvas_width=self._target.canvas_width,
            canvas_height=self._target.canvas_height,
            screen_width=int(root.winfo_screenwidth()),
            screen_height=int(root.winfo_screenheight()),
        )
        root.geometry(f"{initial_width}x{initial_height}")
        root.minsize(1, 1)
        root.bind("<Configure>", self._on_configure)
        return root

    def _create_layout(self) -> Any:
        """Create the image-only watcher layout."""
        frame = self._toolkit.ttk.Frame(self._root)
        frame.pack(fill=self._toolkit.tk.BOTH, expand=True)
        image_label = self._toolkit.ttk.Label(frame)
        image_label.pack(fill=self._toolkit.tk.BOTH, expand=True)
        return image_label

    def run(self, *, on_visible: Callable[[], None] | None = None) -> None:
        """Run the watcher until the window closes.

        If *on_visible* is provided it is called from the event loop once
        the window is confirmed visible on screen.  If the window does not
        become visible within :data:`_VISIBILITY_CHECK_MAX_WAIT_MS`, the
        watcher window is closed.
        """
        if on_visible is not None:
            self._root.after(0, lambda: self._check_visibility(on_visible, elapsed_ms=0))
        self._root.after(0, self._poll)
        self._root.mainloop()

    def _check_visibility(
        self,
        callback: Callable[[], None],
        *,
        elapsed_ms: int,
    ) -> None:
        """Confirm the window is visible or close it after a timeout."""
        if not bool(self._root.winfo_exists()):
            return
        if bool(self._root.winfo_viewable()):
            callback()
            return
        if elapsed_ms >= _VISIBILITY_CHECK_MAX_WAIT_MS:
            self._root.destroy()
            return
        self._root.after(
            _VISIBILITY_CHECK_INTERVAL_MS,
            lambda: self._check_visibility(
                callback,
                elapsed_ms=elapsed_ms + _VISIBILITY_CHECK_INTERVAL_MS,
            ),
        )

    def _poll(self) -> None:
        """Poll for render changes and update the display."""
        if not bool(self._root.winfo_exists()):
            return

        try:
            signature, image = load_render_image(
                self._target.latest_render,
                previous_signature=self._render_signature,
            )
        except RetryableWatchError:
            self._schedule_next_poll()
            return

        self._render_signature = signature
        if image is not None:
            self._current_image = image
            self._refresh_display()

        self._schedule_next_poll()

    def _schedule_next_poll(self) -> None:
        """Schedule the next watcher refresh."""
        if bool(self._root.winfo_exists()):
            self._root.after(self._interval_ms, self._poll)

    def _on_configure(self, event: Any) -> None:
        """Refresh the displayed image when the window size changes."""
        if getattr(event, "widget", None) is self._root:
            self._refresh_display()

    def _refresh_display(self) -> None:
        """Render the latest image into the current window size."""
        if self._current_image is None or not bool(self._root.winfo_exists()):
            return

        frame_width = int(self._image_label.winfo_width())
        frame_height = int(self._image_label.winfo_height())
        if frame_width <= 1 or frame_height <= 1:
            frame_width = int(self._root.winfo_width())
            frame_height = int(self._root.winfo_height())

        scaled_width, scaled_height = scale_to_fit(
            content_width=self._current_image.width,
            content_height=self._current_image.height,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        display_image = self._current_image.resize(
            (scaled_width, scaled_height),
            Image.Resampling.LANCZOS,
        )
        self._photo_image = self._toolkit.image_tk.PhotoImage(display_image)
        self._image_label.configure(image=self._photo_image)


def create_session_watcher(
    session_path: str | Path,
    *,
    interval_ms: int = DEFAULT_INTERVAL_MS,
) -> SessionWatcherApp:
    """Create a watcher app for an existing session."""
    target = read_watch_target(session_path)
    return SessionWatcherApp(target=target, interval_ms=interval_ms)


def watch_session(session_path: str | Path, *, interval_ms: int = DEFAULT_INTERVAL_MS) -> None:
    """Open a foreground watcher window for an existing session."""
    create_session_watcher(session_path, interval_ms=interval_ms).run()


__all__ = [
    "DEFAULT_INTERVAL_MS",
    "RetryableWatchError",
    "SessionWatcherApp",
    "Toolkit",
    "WatchError",
    "WatchTarget",
    "WatchUnavailableError",
    "_VISIBILITY_CHECK_INTERVAL_MS",
    "_VISIBILITY_CHECK_MAX_WAIT_MS",
    "compute_initial_window_size",
    "create_session_watcher",
    "load_render_image",
    "load_toolkit",
    "read_watch_target",
    "scale_to_fit",
    "validate_interval_ms",
    "watch_session",
]
