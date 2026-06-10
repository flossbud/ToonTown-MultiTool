"""is_source_run + repo-root cwd for the git fallback."""
import subprocess

from utils import build_info


def test_is_source_run_true_without_embedded_build_info(monkeypatch):
    # In a source checkout utils/_build_info.py does not exist, so the
    # fallback path runs and flags a source run.
    build_info._reset_cache_for_tests()
    assert build_info.is_source_run() is True


def test_is_source_run_false_with_embedded_build_info(monkeypatch):
    build_info._reset_cache_for_tests()
    monkeypatch.setattr(
        build_info, "_load",
        lambda: {"number": 458, "sha": "abc", "date": "", "source": False})
    assert build_info.is_source_run() is False


def test_git_fallback_uses_repo_root_cwd(monkeypatch):
    build_info._reset_cache_for_tests()
    seen = {}

    def fake_run(args, **kwargs):
        seen["cwd"] = kwargs.get("cwd")

        class R:
            returncode = 0
            stdout = "42\n"

        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    build_info.build_number()
    assert seen["cwd"] is not None
    assert str(seen["cwd"]).endswith("ToonTownMultiTool-v2")
    build_info._reset_cache_for_tests()
