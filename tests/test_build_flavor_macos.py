"""macOS config-dir + bundle-id flavor logic (sys.platform-pinned)."""
import importlib
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest


@pytest.fixture
def bf(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("TTMT_CONFIG_DIR", raising=False)
    monkeypatch.delenv("TTMT_BETA", raising=False)
    import utils.build_flavor as m
    importlib.reload(m)
    yield m
    monkeypatch.setattr(sys, "platform", sys.platform)
    importlib.reload(m)


def test_macos_config_dir_stable(bf, monkeypatch):
    monkeypatch.setattr(bf, "is_beta", lambda: False)
    expected = os.path.expanduser("~/Library/Application Support/toontown_multitool")
    assert bf.config_dir() == expected


def test_macos_config_dir_beta(bf, monkeypatch):
    monkeypatch.setattr(bf, "is_beta", lambda: True)
    expected = os.path.expanduser("~/Library/Application Support/toontown_multitool_beta")
    assert bf.config_dir() == expected


def test_macos_config_dir_env_override_wins(bf, monkeypatch):
    monkeypatch.setenv("TTMT_CONFIG_DIR", "/tmp/ttmt_probe")
    assert bf.config_dir() == "/tmp/ttmt_probe"


def test_bundle_id_stable_and_beta(bf, monkeypatch):
    monkeypatch.setattr(bf, "is_beta", lambda: False)
    assert bf.bundle_id() == "io.github.flossbud.ToonTownMultiTool"
    monkeypatch.setattr(bf, "is_beta", lambda: True)
    assert bf.bundle_id() == "io.github.flossbud.ToonTownMultiTool.beta"
