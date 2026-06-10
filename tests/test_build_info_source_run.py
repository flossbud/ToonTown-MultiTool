"""is_source_run + repo-root cwd for the git fallback."""
import subprocess
import sys

import pytest

from utils import build_info


@pytest.fixture(autouse=True)
def _fresh_cache():
    """Reset before AND after every test: build_info caches process-wide
    and other suites in the same session import it too."""
    build_info._reset_cache_for_tests()
    yield
    build_info._reset_cache_for_tests()


@pytest.fixture(autouse=True)
def _no_embedded_build_info(monkeypatch):
    """A stale locally-built utils/_build_info.py must not flip these
    tests: a None entry in sys.modules makes the import raise ImportError
    (same guard idea as tests/test_build_info.py)."""
    monkeypatch.setitem(sys.modules, "utils._build_info", None)


def test_is_source_run_true_without_embedded_build_info():
    # With the embedded module blocked, the git fallback path runs and
    # flags a source run.
    assert build_info.is_source_run() is True


def test_is_source_run_false_with_embedded_build_info(monkeypatch):
    monkeypatch.setattr(
        build_info, "_load",
        lambda: {"number": 458, "sha": "abc", "date": "", "source": False})
    assert build_info.is_source_run() is False


def test_git_fallback_uses_repo_root_cwd(monkeypatch, tmp_path):
    seen = {}

    def fake_run(args, **kwargs):
        seen["cwd"] = kwargs.get("cwd")

        class R:
            returncode = 0
            stdout = "42\n"

        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)  # prove the cwd is pinned, not inherited
    build_info.build_number()
    # Never compare against a hardcoded directory name: worktrees and
    # review clones have other names. The contract is "the module's own
    # repo root", whatever it is called.
    assert seen["cwd"] == build_info._REPO_ROOT
