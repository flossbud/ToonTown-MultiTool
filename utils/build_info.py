"""Loader for build identity. CI builds write utils/_build_info.py with
embedded constants; source runs fall back to live git commands. Both
paths cache the result process-wide so we don't shell out repeatedly.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]


_cached: Optional[dict] = None


def _load() -> dict:
    global _cached
    if _cached is not None:
        return _cached
    try:
        from utils import _build_info as _bi
        _cached = {
            "number": int(getattr(_bi, "BUILD_NUMBER", 0)),
            "sha": str(getattr(_bi, "BUILD_SHA", "unknown")),
            "date": str(getattr(_bi, "BUILD_DATE", "")),
            "source": False,
        }
        return _cached
    except ImportError:
        pass

    number = 0
    sha = "unknown"
    try:
        r = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=_REPO_ROOT,
        )
        if r.returncode == 0:
            number = int(r.stdout.strip())
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=_REPO_ROOT,
        )
        if r.returncode == 0:
            sha = r.stdout.strip() or "unknown"
    except (FileNotFoundError, ValueError, subprocess.SubprocessError):
        pass

    _cached = {"number": number, "sha": sha, "date": "", "source": True}
    return _cached


def build_number() -> int:
    return _load()["number"]


def build_sha() -> str:
    return _load()["sha"]


def build_date() -> str:
    return _load()["date"]


def is_source_run() -> bool:
    """True when running from a source checkout (no CI-embedded
    utils/_build_info.py). Gates the git-aware update-banner adjudication;
    packaged builds never enter that path."""
    return bool(_load()["source"])


def version_string() -> str:
    from utils.version import APP_VERSION
    return f"{APP_VERSION} (build {build_number()}, {build_sha()})"


def _reset_cache_for_tests() -> None:
    """Test-only hook: clear the module-level cache so the next call
    re-reads the environment. Not part of the public API."""
    global _cached
    _cached = None
