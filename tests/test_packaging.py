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
    env["UV_CACHE_DIR"] = str(cache_dir)
    env["LINEWORK_HOME"] = str(tmp_path / "linework-home")

    install_result = _run(
        ["uv", "tool", "install", "--python", sys.executable, "--force", str(PROJECT_ROOT)],
        env=env,
    )
    assert install_result.returncode == 0, install_result.stderr

    binary_path = home_dir / ".local" / "bin" / "linework"
    assert binary_path.is_file()

    version_result = _run([str(binary_path), "--version"], env=env)
    assert version_result.returncode == 0
    assert version_result.stdout.strip() == "0.1.0"

    session_path = tmp_path / "installed-session"
    new_result = _run(
        [str(binary_path), "new", "--session", str(session_path), "--json"],
        env=env,
    )
    assert new_result.returncode == 0, new_result.stderr
    new_payload = json.loads(new_result.stdout)
    assert new_payload["session_path"] == str(session_path)

    run_result = _run(
        [str(binary_path), "run", "--session", str(session_path), "--json"],
        env=env,
        stdin='{"op":"draw.text","payload":{"x":12,"y":16,"text":"pkg","size":18}}\n',
    )
    assert run_result.returncode == 0, run_result.stderr

    with Image.open(session_path / "render" / "latest.png") as rendered:
        blank = Image.new("RGBA", rendered.size, (255, 255, 255, 255))
        difference = ImageChops.difference(rendered.convert("RGB"), blank.convert("RGB"))
        assert difference.getbbox() is not None
