"""Tests for the standalone Click Sync card on the Features page."""

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")


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


def _features_field(tab, label):
    from utils.widgets.inset_row import InsetRow
    for f in tab.pages["features"].findChildren(InsetRow):
        if f.label_widget.text() == label:
            return f
    return None


def test_features_page_has_pink_click_sync_card(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    from utils.widgets.card_surface import CardSurface
    tab = SettingsTab(settings_manager)
    cards = tab.pages["features"].findChildren(CardSurface)
    pink = [c for c in cards if c.accent_key == "pink"]
    assert len(pink) == 1
    assert pink[0].title_label.text() == "Click Sync"


def test_features_card_order_keep_alive_click_sync_chat(qapp, settings_manager):
    """Cards must appear in spec order: Keep-Alive, Click Sync, Hotkeys,
    Chat Handling. Assert against the actual page layout order (what the
    user sees), not findChildren -- findChildren reflects QObject creation
    order, which can diverge from layout order if an insertWidget index is
    wrong. All four Features cards are v2 CardSurfaces."""
    from tabs.settings_tab import SettingsTab
    from utils.widgets.card_surface import CardSurface
    tab = SettingsTab(settings_manager)
    layout = tab.pages["features"]._panel_layout
    titles = []
    for i in range(layout.count()):
        w = layout.itemAt(i).widget()
        if isinstance(w, CardSurface):
            titles.append(w.title_label.text())
    assert titles == ["Keep-Alive", "Click Sync", "Hotkeys", "Chat Handling"]


def test_click_sync_toggle_lives_inside_the_pink_card(qapp, settings_manager):
    """The toggle must live INSIDE the pink Click Sync card, not merely
    somewhere on the Features page."""
    from tabs.settings_tab import SettingsTab, Switch
    from utils.widgets.card_surface import CardSurface
    from utils.widgets.inset_row import InsetRow
    tab = SettingsTab(settings_manager)
    pink = next(
        c for c in tab.pages["features"].findChildren(CardSurface)
        if c.accent_key == "pink"
    )
    rows = pink.findChildren(InsetRow)
    labels = [r.label_widget.text() for r in rows]
    assert labels == [
        "Enable Click Sync",
        "Show ghost cursors",
        "Ghost cursors can use card controls",
    ]
    assert all(isinstance(r.control_widget, Switch) for r in rows)


def test_click_sync_toggle_default_off(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    field = _features_field(tab, "Enable Click Sync")
    assert field.control_widget.isChecked() is False


def test_click_sync_toggle_reflects_persisted_enabled(qapp, settings_manager):
    """When CLICK_SYNC_ENABLED is already True in settings, the switch must
    render checked on build (spec: initial value reads the stored key)."""
    from tabs.settings_tab import SettingsTab
    from utils.settings_keys import CLICK_SYNC_ENABLED
    settings_manager.set(CLICK_SYNC_ENABLED, True)
    tab = SettingsTab(settings_manager)
    field = _features_field(tab, "Enable Click Sync")
    assert field.control_widget.isChecked() is True


def test_click_sync_toggle_writes_setting(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    from utils.settings_keys import CLICK_SYNC_ENABLED
    tab = SettingsTab(settings_manager)
    field = _features_field(tab, "Enable Click Sync")
    field.control_widget.setChecked(True)
    assert settings_manager.get(CLICK_SYNC_ENABLED) is True
    field.control_widget.setChecked(False)
    assert settings_manager.get(CLICK_SYNC_ENABLED) is False


def test_ttr_games_panel_no_longer_has_click_sync_field(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    from utils.widgets.inset_row import InsetRow
    tab = SettingsTab(settings_manager)
    labels = {
        f.label_widget.text()
        for f in tab.pages["games"].findChildren(InsetRow)
    }
    # Case-insensitive so the guard catches both the old "Click sync (TTR)"
    # label and the new "Click Sync" / "Enable Click Sync" wording.
    assert not any("click sync" in lbl.lower() for lbl in labels)


def test_ghost_cursor_toggle_default_on(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    field = _features_field(tab, "Show ghost cursors")
    assert field is not None
    assert field.control_widget.isChecked() is True


def test_ghost_cursor_toggle_reflects_persisted_off(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    from utils.settings_keys import GHOST_CURSORS_ENABLED
    settings_manager.set(GHOST_CURSORS_ENABLED, False)
    tab = SettingsTab(settings_manager)
    field = _features_field(tab, "Show ghost cursors")
    assert field.control_widget.isChecked() is False


def test_ghost_cursor_toggle_writes_setting(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    from utils.settings_keys import GHOST_CURSORS_ENABLED
    tab = SettingsTab(settings_manager)
    field = _features_field(tab, "Show ghost cursors")
    field.control_widget.setChecked(False)
    assert settings_manager.get(GHOST_CURSORS_ENABLED) is False
    field.control_widget.setChecked(True)
    assert settings_manager.get(GHOST_CURSORS_ENABLED) is True
