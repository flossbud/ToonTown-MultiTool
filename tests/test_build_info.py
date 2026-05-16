import importlib
import sys

import pytest

import utils.build_info as bi


def _reload():
    importlib.reload(bi)
    return bi


@pytest.fixture(autouse=True)
def _reset_build_info_cache():
    import utils.build_info as _bi
    _bi._reset_cache_for_tests()
    yield
    _bi._reset_cache_for_tests()


def test_uses_embedded_when_present(monkeypatch):
    # Inject a fake _build_info module.
    fake = type(sys)("utils._build_info")
    fake.BUILD_NUMBER = 458
    fake.BUILD_SHA = "97279d7"
    fake.BUILD_DATE = "20260516"
    monkeypatch.setitem(sys.modules, "utils._build_info", fake)
    mod = _reload()
    assert mod.build_number() == 458
    assert mod.build_sha() == "97279d7"
    assert mod.build_date() == "20260516"


def test_falls_back_to_git_when_module_missing(monkeypatch):
    monkeypatch.delitem(sys.modules, "utils._build_info", raising=False)

    def fake_run(cmd, *args, **kwargs):
        from subprocess import CompletedProcess
        if cmd[:3] == ["git", "rev-list", "--count"]:
            return CompletedProcess(cmd, 0, stdout="412\n", stderr="")
        if cmd[:3] == ["git", "rev-parse", "--short"]:
            return CompletedProcess(cmd, 0, stdout="abc1234\n", stderr="")
        raise AssertionError(f"unexpected cmd: {cmd}")

    # Block the import so the loader takes the git-fallback path even on
    # machines where a real utils/_build_info.py exists alongside this test.
    real_import = __import__

    def blocked_import(name, *a, **kw):
        if name == "utils._build_info":
            raise ImportError("blocked for test")
        return real_import(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    monkeypatch.setattr("subprocess.run", fake_run)
    mod = _reload()
    assert mod.build_number() == 412
    assert mod.build_sha() == "abc1234"


def test_safe_fallback_when_git_missing(monkeypatch):
    monkeypatch.delitem(sys.modules, "utils._build_info", raising=False)
    real_import = __import__

    def blocked_import(name, *a, **kw):
        if name == "utils._build_info":
            raise ImportError("blocked for test")
        return real_import(name, *a, **kw)

    def boom(cmd, *a, **kw):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr("builtins.__import__", blocked_import)
    monkeypatch.setattr("subprocess.run", boom)
    mod = _reload()
    assert mod.build_number() == 0
    assert mod.build_sha() == "unknown"


def test_version_string_format(monkeypatch):
    from utils import version
    monkeypatch.setattr(version, "APP_VERSION", "2.3.0-a")
    fake = type(sys)("utils._build_info")
    fake.BUILD_NUMBER = 458
    fake.BUILD_SHA = "97279d7"
    fake.BUILD_DATE = "20260516"
    monkeypatch.setitem(sys.modules, "utils._build_info", fake)
    mod = _reload()
    assert mod.version_string() == "2.3.0-a (build 458, 97279d7)"
