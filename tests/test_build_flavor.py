"""Tests for utils.build_flavor — the single source of truth for build flavor.

The Arch ttmt-beta package's launcher sets TTMT_BETA=1; everything else
unsets it. Helper functions read the env on each call so tests can flip
the flag with monkeypatch without an importlib.reload dance.
"""

import os
import sys

import pytest


def test_is_beta_false_when_env_unset(monkeypatch):
    monkeypatch.delenv("TTMT_BETA", raising=False)
    from utils import build_flavor
    assert build_flavor.is_beta() is False


def test_is_beta_true_when_env_set(monkeypatch):
    monkeypatch.setenv("TTMT_BETA", "1")
    from utils import build_flavor
    assert build_flavor.is_beta() is True


def test_is_beta_false_when_env_empty(monkeypatch):
    monkeypatch.setenv("TTMT_BETA", "")
    from utils import build_flavor
    assert build_flavor.is_beta() is False


def test_config_dir_name_stable(monkeypatch):
    monkeypatch.delenv("TTMT_BETA", raising=False)
    from utils import build_flavor
    assert build_flavor.config_dir_name() == "toontown_multitool"


def test_config_dir_name_beta(monkeypatch):
    monkeypatch.setenv("TTMT_BETA", "1")
    from utils import build_flavor
    assert build_flavor.config_dir_name() == "toontown_multitool_beta"


def test_config_dir_stable(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("TTMT_BETA", raising=False)
    from utils import build_flavor
    assert build_flavor.config_dir().endswith("/.config/toontown_multitool")


def test_config_dir_beta(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("TTMT_BETA", "1")
    from utils import build_flavor
    assert build_flavor.config_dir().endswith("/.config/toontown_multitool_beta")


def test_keyring_service_stable(monkeypatch):
    monkeypatch.delenv("TTMT_BETA", raising=False)
    from utils import build_flavor
    assert build_flavor.keyring_service() == "toontown_multitool"


def test_keyring_service_beta(monkeypatch):
    monkeypatch.setenv("TTMT_BETA", "1")
    from utils import build_flavor
    assert build_flavor.keyring_service() == "ttmt-beta"


def test_window_title_stable(monkeypatch):
    monkeypatch.delenv("TTMT_BETA", raising=False)
    from utils import build_flavor
    assert build_flavor.window_title() == "ToonTown MultiTool"


def test_window_title_beta(monkeypatch):
    monkeypatch.setenv("TTMT_BETA", "1")
    from utils import build_flavor
    assert build_flavor.window_title() == "ToonTown MultiTool BETA"


def test_app_name_stable(monkeypatch):
    monkeypatch.delenv("TTMT_BETA", raising=False)
    from utils import build_flavor
    assert build_flavor.app_name() == "ToonTown MultiTool"


def test_app_name_beta(monkeypatch):
    monkeypatch.setenv("TTMT_BETA", "1")
    from utils import build_flavor
    assert build_flavor.app_name() == "ToonTown MultiTool BETA"


def test_is_beta_via_sentinel_file(tmp_path, monkeypatch):
    """When .beta_flavor sentinel sits next to sys.executable, is_beta() returns True."""
    monkeypatch.delenv("TTMT_BETA", raising=False)
    sentinel_dir = tmp_path / "app"
    sentinel_dir.mkdir()
    (sentinel_dir / ".beta_flavor").write_text("")
    from utils import build_flavor
    monkeypatch.setattr(
        build_flavor, "_beta_sentinel_path",
        lambda: str(sentinel_dir / ".beta_flavor"),
    )
    assert build_flavor.is_beta() is True


def test_is_beta_false_when_sentinel_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("TTMT_BETA", raising=False)
    from utils import build_flavor
    monkeypatch.setattr(
        build_flavor, "_beta_sentinel_path",
        lambda: str(tmp_path / "nonexistent"),
    )
    assert build_flavor.is_beta() is False


def test_is_beta_env_var_wins_over_missing_sentinel(tmp_path, monkeypatch):
    """If env var is set, the sentinel check never runs (short-circuit)."""
    monkeypatch.setenv("TTMT_BETA", "1")
    from utils import build_flavor
    monkeypatch.setattr(
        build_flavor, "_beta_sentinel_path",
        lambda: str(tmp_path / "nonexistent"),
    )
    assert build_flavor.is_beta() is True


def test_is_beta_sentinel_path_uses_sys_executable_dir():
    """The production helper resolves the path relative to the running EXE."""
    import os, sys
    from utils import build_flavor
    expected = os.path.join(os.path.dirname(sys.executable), ".beta_flavor")
    assert build_flavor._beta_sentinel_path() == expected
