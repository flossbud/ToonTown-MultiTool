"""Tests for SettingsTab.highlight_keep_alive_group()."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from utils.settings_manager import SettingsManager


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def settings_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return SettingsManager()


def test_highlight_keep_alive_group_method_exists(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    assert hasattr(tab, "highlight_keep_alive_group")
    assert callable(tab.highlight_keep_alive_group)


def test_highlight_keep_alive_group_does_not_raise(qapp, settings_manager):
    """The method must run without exception even when the tab has not been
    shown yet (no parent QScrollArea visible)."""
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    tab.highlight_keep_alive_group()  # should not raise
