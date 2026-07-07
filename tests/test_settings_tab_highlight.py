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


def test_highlight_keep_alive_group_repeated_calls_are_safe(qapp, settings_manager):
    """Rapid re-invocation (e.g. the user clicking the Launch-tab help
    affordance twice) must not raise. The attention pulse is now a painted
    border animation living on the Keep-Alive card (CardSurface.pulse_highlight),
    so there is no shared QGraphicsEffect a prior finish handler could tear
    down out from under a fresh pulse -- the failure the old strength-anim
    guard prevented is impossible by construction here."""
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    tab.highlight_keep_alive_group()
    tab.highlight_keep_alive_group()  # must not raise
    card = tab._keep_alive_panel
    # When motion is enabled the pulse stores its QVariantAnimation on the
    # card; under reduced motion (some CI) pulse_highlight no-ops, so only
    # assert the animation attribute when it was actually created.
    if hasattr(card, "_pulse_anim"):
        assert card._pulse_anim is not None
