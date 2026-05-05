"""Integration test verifying TTMT_BETA=1 flips all the user-visible bits
to their beta values without touching imports beyond build_flavor."""

import os

import pytest


def test_beta_env_isolates_config_dir(monkeypatch):
    monkeypatch.setenv("TTMT_BETA", "1")
    from utils import build_flavor
    assert "_beta" in build_flavor.config_dir_name()
    assert build_flavor.config_dir() != os.path.expanduser("~/.config/toontown_multitool")


def test_beta_env_isolates_keyring_service(monkeypatch):
    monkeypatch.setenv("TTMT_BETA", "1")
    from utils import build_flavor
    assert build_flavor.keyring_service() != "toontown_multitool"


def test_beta_env_changes_window_title(monkeypatch):
    monkeypatch.setenv("TTMT_BETA", "1")
    from utils import build_flavor
    assert "BETA" in build_flavor.window_title()


def test_unset_env_keeps_stable_defaults(monkeypatch):
    monkeypatch.delenv("TTMT_BETA", raising=False)
    from utils import build_flavor
    assert build_flavor.config_dir_name() == "toontown_multitool"
    assert build_flavor.keyring_service() == "toontown_multitool"
    assert build_flavor.window_title() == "ToonTown MultiTool"
    assert build_flavor.app_name() == "ToonTown MultiTool"
