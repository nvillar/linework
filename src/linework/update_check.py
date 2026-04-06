"""Best-effort update check against the remote repository."""

from __future__ import annotations

import re
import subprocess
import sys

_REPO_URL = "https://github.com/nvillar/linework.git"
_TAG_PATTERN = re.compile(r"refs/tags/v([\d.]+)$")
_TIMEOUT_S = 5


def _parse_latest_tag(ls_remote_output: str) -> str | None:
    """Extract the highest semver tag from ``git ls-remote --tags`` output."""
    from packaging.version import Version

    best: Version | None = None
    for line in ls_remote_output.splitlines():
        match = _TAG_PATTERN.search(line)
        if match:
            candidate = Version(match.group(1))
            if best is None or candidate > best:
                best = candidate
    return str(best) if best is not None else None


def _update_command(version: str) -> str:
    """Return the platform-appropriate command for installing a tagged release.

    ``--no-cache`` and ``--reinstall-package`` force a fresh rebuild so the
    Git-installed tool picks up the tag-derived version from ``hatch-vcs``.
    """
    source = f"git+{_REPO_URL}@v{version}"
    if sys.platform == "win32":
        return f"uv tool install --no-cache --reinstall-package linework --link-mode copy {source}"
    return f"uv tool install --no-cache --reinstall-package linework {source}"  # type: ignore[unreachable]


def check_for_update(current_version: str) -> str | None:
    """Return an update hint if a newer release tag exists, else ``None``.

    This is best-effort: network errors, missing ``git``, or missing
    ``packaging`` all return ``None`` silently.
    """
    try:
        from packaging.version import Version

        result = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", _REPO_URL],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
        )
        if result.returncode != 0:
            return None

        latest = _parse_latest_tag(result.stdout)
        if latest is None:
            return None

        if Version(latest) > Version(current_version):
            return f"Update available: {current_version} → {latest}\n{_update_command(latest)}"
    except Exception:  # noqa: BLE001
        pass
    return None
