"""Tests for the Settings Hotkeys card - capture rows, steal prompt,
launch-slot pickers, and provider failure badges."""

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


@pytest.fixture
def settings_tab(qapp, settings_manager):
    from tabs.settings_tab import SettingsTab
    return SettingsTab(settings_manager)


def test_hotkeys_card_lists_every_action(settings_tab):
    from utils.hotkey_actions import ACTIONS
    assert set(settings_tab._hotkey_rows) == {a.id for a in ACTIONS}
    # defaulted actions show their chord, unbound show Not set
    assert settings_tab._hotkey_rows["app.refresh"].text() == "F5"
    assert settings_tab._hotkey_rows["overlay.toggle_cards"].text() == "Not set"


def test_binding_persists_and_conflict_prompts_steal(settings_tab, monkeypatch):
    from utils.settings_keys import HOTKEY_BINDINGS
    from PySide6.QtWidgets import QMessageBox
    tab = settings_tab
    tab._on_hotkey_chord("overlay.toggle_cards", "ctrl+alt+h")
    assert tab.settings_manager.get(HOTKEY_BINDINGS)["overlay.toggle_cards"] == "ctrl+alt+h"
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    tab._on_hotkey_chord("clicksync.toggle", "ctrl+alt+h")
    stored = tab.settings_manager.get(HOTKEY_BINDINGS)
    assert stored["clicksync.toggle"] == "ctrl+alt+h"
    assert stored["overlay.toggle_cards"] is None
    assert tab._hotkey_rows["overlay.toggle_cards"].text() == "Not set"


def test_conflict_decline_keeps_both(settings_tab, monkeypatch):
    from utils.settings_keys import HOTKEY_BINDINGS
    from PySide6.QtWidgets import QMessageBox
    tab = settings_tab
    tab._on_hotkey_chord("overlay.toggle_cards", "ctrl+alt+h")
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.No))
    tab._on_hotkey_chord("clicksync.toggle", "ctrl+alt+h")
    stored = tab.settings_manager.get(HOTKEY_BINDINGS)
    assert stored["overlay.toggle_cards"] == "ctrl+alt+h"
    assert stored.get("clicksync.toggle") is None or "clicksync.toggle" not in stored
    assert tab._hotkey_rows["clicksync.toggle"].text() == "Not set"


def test_default_conflict_is_detected(settings_tab, monkeypatch):
    # Stealing a DEFAULT binding (F5 = app.refresh, never explicitly stored)
    from utils.settings_keys import HOTKEY_BINDINGS
    from PySide6.QtWidgets import QMessageBox
    tab = settings_tab
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    tab._on_hotkey_chord("overlay.toggle_cards", "F5")
    stored = tab.settings_manager.get(HOTKEY_BINDINGS)
    assert stored["overlay.toggle_cards"] == "F5"
    assert stored["app.refresh"] is None          # default explicitly cleared
    assert tab._hotkey_rows["app.refresh"].text() == "Not set"


def test_clear_stores_explicit_null(settings_tab):
    from utils.settings_keys import HOTKEY_BINDINGS
    settings_tab._on_hotkey_chord("app.refresh", None)
    assert settings_tab.settings_manager.get(HOTKEY_BINDINGS)["app.refresh"] is None


def test_launch_slot_picker_persists_account(settings_tab):
    from utils.settings_keys import HOTKEY_LAUNCH_SLOTS
    settings_tab.set_hotkey_accounts_provider(
        lambda: [("acct-1", "ttr", "Duke"), ("acct-2", "cc", "Mata")])
    settings_tab._rebuild_hotkey_slot_rows()
    settings_tab._on_hotkey_slot_selected("2", "acct-2")
    assert settings_tab.settings_manager.get(HOTKEY_LAUNCH_SLOTS)["2"] == "acct-2"


def test_hotkey_status_badges_failures_and_respects_capture(settings_tab):
    tab = settings_tab
    tab.set_hotkey_status({"app.refresh": "in use by another application"})
    assert "in use" in tab._hotkey_rows["app.refresh"].text()
    # badge clears when failures go away
    tab.set_hotkey_status({})
    assert tab._hotkey_rows["app.refresh"].text() == "F5"
    # a capturing row is never touched by a status push
    btn = tab._hotkey_rows["app.refresh"]
    btn.begin_capture()
    tab.set_hotkey_status({"app.refresh": "in use by another application"})
    assert "Press a chord" in btn.text()
    # simulate capture end via Esc; the pending status re-applies
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    btn.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    tab._refresh_hotkey_status()
    assert "in use" in btn.text()


def test_click_sync_switch_tracks_external_flip(settings_tab):
    from utils.settings_keys import CLICK_SYNC_ENABLED
    sw = settings_tab._click_sync_switch
    settings_tab.settings_manager.set(CLICK_SYNC_ENABLED, True)
    assert sw.isChecked() is True
