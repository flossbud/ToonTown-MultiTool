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


def test_highlight_keep_alive_group_stops_prior_pulse(qapp, settings_manager):
    """A second call while the first pulse is still running must stop the
    prior animation. Without this guard, the prior animation's finished
    handler would fire setGraphicsEffect(None) on the new effect, killing
    the new pulse before the user sees it."""
    from tabs.settings_tab import SettingsTab
    from PySide6.QtCore import QPropertyAnimation
    tab = SettingsTab(settings_manager)
    tab.highlight_keep_alive_group()
    first = tab._keepalive_highlight_anim
    assert first.state() == QPropertyAnimation.Running
    tab.highlight_keep_alive_group()
    # The prior animation must have been stopped (or be in a non-Running state).
    assert first.state() != QPropertyAnimation.Running
    # And a fresh animation is now running.
    assert tab._keepalive_highlight_anim is not first
    assert tab._keepalive_highlight_anim.state() == QPropertyAnimation.Running
