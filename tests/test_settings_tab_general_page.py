"""Tests for the General category page (Appearance + Updates panels)."""

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings_manager():
    class _Stub:
        def __init__(self):
            self._d = {}
            self._listeners = []

        def get(self, key, default=None):
            return self._d.get(key, default)

        def set(self, key, value):
            self._d[key] = value
            for fn in list(self._listeners):
                fn(key, value)

        def on_change(self, fn):
            self._listeners.append(fn)

    return _Stub()


def test_general_page_has_two_panels(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    page = tab.pages["general"]
    # The page's panel layout has the micro label, two v2 cards, and a stretch.
    from utils.widgets.card_surface import CardSurface
    cards = page.findChildren(CardSurface)
    titles = [c.title_label.text() for c in cards]
    assert "Appearance & behavior" in titles
    assert "Updates" in titles


def test_general_page_appearance_dropdown_changes_theme(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    # The Appearance control is now a SegmentedPill (System/Light/Dark).
    from utils.widgets.pill_controls import SegmentedPill
    assert isinstance(tab._theme_segment, SegmentedPill)
    # Selecting index 1 (Light) should persist "light".
    tab._theme_segment.index_changed.emit(1)
    assert settings_manager.get("theme") == "light"


def test_general_page_reduce_motion_tri_state(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    # On: explicit=True, reduce_motion=True
    tab._rm_segment.index_changed.emit(1)
    assert settings_manager.get("reduce_motion_set_explicitly") is True
    assert settings_manager.get("reduce_motion") is True
    # Off: explicit=True, reduce_motion=False
    tab._rm_segment.index_changed.emit(2)
    assert settings_manager.get("reduce_motion_set_explicitly") is True
    assert settings_manager.get("reduce_motion") is False
    # System default: explicit=False, reduce_motion=False
    tab._rm_segment.index_changed.emit(0)
    assert settings_manager.get("reduce_motion_set_explicitly") is False
    assert settings_manager.get("reduce_motion") is False


def test_general_page_updates_toggle_persists(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab, Switch
    tab = SettingsTab(settings_manager)
    field = _find_field(tab, "general", "Check for updates on startup")
    sw = field.control_widget
    assert isinstance(sw, Switch)
    sw.setChecked(True)
    assert settings_manager.get("check_for_updates_at_startup") is True


def test_general_page_check_now_button_shows_disabled_state(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    field = _find_field(tab, "general", "Check for updates now")
    from PySide6.QtWidgets import QPushButton
    btn = field.control_widget
    assert isinstance(btn, QPushButton)
    # When set_update_checker has been called, clicking should disable + relabel.

    class _Checker:
        def __init__(self):
            self.calls = []

        def check_async(self, manual=False):
            self.calls.append(manual)

        # Signals expected by set_update_checker — we provide stubs that
        # match the real connect targets but never emit.
        class _Sig:
            def connect(self, _fn):
                pass

        update_available = _Sig()
        no_update = _Sig()
        check_failed = _Sig()

    checker = _Checker()
    tab.set_update_checker(checker)
    btn.click()
    assert checker.calls == [True]
    assert btn.isEnabled() is False
    assert btn.text() == "Checking..."


# ── helper ────────────────────────────────────────────────────────────────


def _find_field(tab, page_key, label):
    from utils.widgets.inset_row import InsetRow
    page = tab.pages[page_key]
    for f in page.findChildren(InsetRow):
        if f.label_widget.text() == label:
            return f
    return None
