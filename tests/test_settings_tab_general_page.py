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
    # The page's panel layout has the title, subtitle, two panels, and a stretch.
    from tabs.settings_tab import SettingsPanel
    panels = page.findChildren(SettingsPanel)
    titles = [p.title_label.text() for p in panels]
    assert "Appearance & behavior" in titles
    assert "Updates" in titles


def test_general_page_appearance_dropdown_changes_theme(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    # Find the Appearance dropdown by traversing field labels.
    field = _find_field(tab, "general", "Appearance")
    assert field is not None
    # Combobox is the control widget.
    from PySide6.QtWidgets import QComboBox
    assert isinstance(field.control_widget, QComboBox)
    # Setting index 1 (Light) should persist "light".
    field.control_widget.setCurrentIndex(1)
    assert settings_manager.get("theme") == "light"


def test_general_page_reduce_motion_tri_state(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    field = _find_field(tab, "general", "Reduce motion")
    # On: explicit=True, reduce_motion=True
    field.control_widget.setCurrentIndex(1)
    assert settings_manager.get("reduce_motion_set_explicitly") is True
    assert settings_manager.get("reduce_motion") is True
    # Off: explicit=True, reduce_motion=False
    field.control_widget.setCurrentIndex(2)
    assert settings_manager.get("reduce_motion_set_explicitly") is True
    assert settings_manager.get("reduce_motion") is False
    # System default: explicit=False, reduce_motion=False
    field.control_widget.setCurrentIndex(0)
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
    from tabs.settings_tab import SettingsField
    page = tab.pages[page_key]
    for f in page.findChildren(SettingsField):
        if f.label_widget.text() == label:
            return f
    return None
