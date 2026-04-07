"""Packaging and installability validation tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

from PIL import Image, ImageChops

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess for packaging validation."""
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        input=stdin,
        cwd=cwd,
        env=env,
    )


def test_built_distributions_include_bundled_font(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    cache_dir = tmp_path / "uv-cache"
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = str(cache_dir)

    result = _run(
        ["uv", "build", "--out-dir", str(dist_dir)],
        cwd=PROJECT_ROOT,
        env=env,
    )
    assert result.returncode == 0, result.stderr

    wheel_path = next(dist_dir.glob("linework-*.whl"))
    with zipfile.ZipFile(wheel_path) as archive:
        wheel_names = archive.namelist()

    wheel_fonts = [
        name
        for name in wheel_names
        if name.startswith("linework/assets/") and name.endswith(".ttf")
    ]
    assert wheel_fonts == ["linework/assets/NotoSans-Regular.ttf"]
    assert "linework/assets/NotoSans-OFL.txt" in wheel_names

    sdist_path = next(dist_dir.glob("linework-*.tar.gz"))
    with tarfile.open(sdist_path, "r:gz") as archive:
        sdist_names = archive.getnames()

    assert any(name.endswith("src/linework/assets/NotoSans-Regular.ttf") for name in sdist_names)
    assert any(name.endswith("src/linework/assets/NotoSans-OFL.txt") for name in sdist_names)


def test_uv_tool_install_from_project_runs_installed_cli(tmp_path: Path) -> None:
    home_dir = tmp_path / "tool-home"
    cache_dir = tmp_path / "uv-cache"
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    if sys.platform == "win32":
        env["USERPROFILE"] = str(home_dir)
        env["APPDATA"] = str(home_dir / "AppData" / "Roaming")
    env["UV_CACHE_DIR"] = str(cache_dir)
    env["LINEWORK_HOME"] = str(tmp_path / "linework-home")

    install_result = _run(
        ["uv", "tool", "install", "--python", sys.executable, "--force", str(PROJECT_ROOT)],
        env=env,
    )
    assert install_result.returncode == 0, install_result.stderr

    binary_name = "linework.exe" if sys.platform == "win32" else "linework"
    binary_path = home_dir / ".local" / "bin" / binary_name
    assert binary_path.is_file()

    version_result = _run([str(binary_path), "--version"], env=env)
    assert version_result.returncode == 0
    assert version_result.stdout.strip().startswith("0.")

    session_path = tmp_path / "installed-session"
    jsonl_file = tmp_path / "draw.jsonl"
    jsonl_file.write_text(
        '{"op":"draw.text","payload":'
        '{"x":12,"y":16,"width":72,"height":36,"text":"pkg","size":18}}\n',
        encoding="utf-8",
    )
    new_result = _run(
        [
            str(binary_path),
            "new",
            "--session",
            str(session_path),
            "--file",
            str(jsonl_file),
            "--json",
        ],
        env=env,
    )
    assert new_result.returncode == 0, new_result.stderr
    new_payload = json.loads(new_result.stdout)
    assert new_payload["session_path"] == str(session_path)

    with Image.open(session_path / "render" / "latest.png") as rendered:
        blank = Image.new("RGBA", rendered.size, (255, 255, 255, 255))
        difference = ImageChops.difference(rendered.convert("RGB"), blank.convert("RGB"))
        assert difference.getbbox() is not None


def test_installed_watch_impl_survives_stdin_devnull(tmp_path: Path) -> None:
    """The installed _watch-impl can load tkinter even when stdin is /dev/null.

    Agent harnesses (e.g. OpenCode) redirect stdin to /dev/null for every
    command they spawn.  On macOS with python-build-standalone, this breaks
    Tcl 9's ``dladdr()``-based ``init.tcl`` discovery when the Python binary
    is a venv symlink.  ``_ensure_tcl_library()`` must fix this transparently.
    """
    home_dir = tmp_path / "tool-home"
    cache_dir = tmp_path / "uv-cache"
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    if sys.platform == "win32":
        env["USERPROFILE"] = str(home_dir)
        env["APPDATA"] = str(home_dir / "AppData" / "Roaming")
    env["UV_CACHE_DIR"] = str(cache_dir)
    env["LINEWORK_HOME"] = str(tmp_path / "linework-home")
    env.pop("TCL_LIBRARY", None)

    install_result = _run(
        ["uv", "tool", "install", "--python", sys.executable, "--force", str(PROJECT_ROOT)],
        env=env,
    )
    assert install_result.returncode == 0, install_result.stderr

    # Resolve the venv python that the installed tool uses.  We invoke the
    # binary directly rather than through the entry-point script, because
    # pytest tmpdir paths often exceed macOS's 127-byte shebang limit.
    venv_python = str(
        home_dir / ".local" / "share" / "uv" / "tools" / "linework" / "bin" / "python"
    )
    assert Path(venv_python).exists(), f"venv python not found: {venv_python}"

    # Run a minimal tkinter import via the venv python with stdin closed.
    # This mimics the agent-harness environment that triggered the bug.
    result = _run(
        [
            venv_python,
            "-c",
            (
                "from linework.watch import load_toolkit; "
                "tk = load_toolkit(); "
                "r = tk.tk.Tk(); r.withdraw(); "
                'print("tcl_ok:", r.tk.eval("info library")); '
                "r.destroy()"
            ),
        ],
        env=env,
        stdin="",  # stdin closed immediately — same as /dev/null
    )
    assert result.returncode == 0, (
        f"load_toolkit() failed with stdin closed (agent-harness scenario):\n{result.stderr}"
    )
    assert "tcl_ok:" in result.stdout
