"""Tests for the Settings Hotkeys card - capture rows, steal prompt,
inline launch-slot pickers, provider failure badges, and the partial
collapse (first category visible + Show more toggle)."""

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

# Platform-dependent refresh default (darwin: bare F5 is the Dictation
# media key on Mac laptops, so the default is a modifier chord there).
from utils.hotkey_actions import action_by_id
_REFRESH = action_by_id("app.refresh").default_chord
_REFRESH_DISPLAY = "+".join(
    p.capitalize() if p in ("ctrl", "alt", "shift", "super")
    else (p.upper() if len(p) == 1 else p)
    for p in _REFRESH.split("+"))



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
    assert settings_tab._hotkey_rows["app.refresh"].text() == _REFRESH_DISPLAY
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
    # Stealing a DEFAULT binding (app.refresh's default chord, never explicitly stored)
    from utils.settings_keys import HOTKEY_BINDINGS
    from PySide6.QtWidgets import QMessageBox
    tab = settings_tab
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    tab._on_hotkey_chord("overlay.toggle_cards", _REFRESH)
    stored = tab.settings_manager.get(HOTKEY_BINDINGS)
    assert stored["overlay.toggle_cards"] == _REFRESH
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


def test_conflict_detects_noncanonical_stored_chord(settings_tab, monkeypatch):
    # A hand-edited store can hold "alt+ctrl+H" for the same chord as
    # "ctrl+alt+h"; the holder scan must canonicalize before comparing.
    from utils.settings_keys import HOTKEY_BINDINGS
    from PySide6.QtWidgets import QMessageBox
    tab = settings_tab
    tab.settings_manager.set(HOTKEY_BINDINGS, {"app.refresh": "alt+ctrl+H"})
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    tab._on_hotkey_chord("overlay.toggle_cards", "ctrl+alt+h")
    stored = tab.settings_manager.get(HOTKEY_BINDINGS)
    assert stored["overlay.toggle_cards"] == "ctrl+alt+h"
    assert stored["app.refresh"] is None
    assert tab._hotkey_rows["app.refresh"].text() == "Not set"


def test_slot_pickers_refresh_on_show(settings_tab):
    from PySide6.QtGui import QShowEvent
    tab = settings_tab
    accounts = [("acct-1", "ttr", "Duke")]
    tab.set_hotkey_accounts_provider(lambda: accounts)
    combo = tab._hotkey_slot_combos["1"]
    assert combo.count() == 2                     # (none) + Duke
    # an account added AFTER the provider was wired appears on next show
    accounts.append(("acct-2", "cc", "Mata"))
    tab.showEvent(QShowEvent())
    items = [combo.itemText(i) for i in range(combo.count())]
    assert "Mata (CC)" in items


def test_hotkey_status_badges_failures_and_respects_capture(settings_tab):
    tab = settings_tab
    tab.set_hotkey_status({"app.refresh": "in use by another application"})
    assert "in use" in tab._hotkey_rows["app.refresh"].text()
    # badge clears when failures go away
    tab.set_hotkey_status({})
    assert tab._hotkey_rows["app.refresh"].text() == _REFRESH_DISPLAY
    # a capturing row is never touched by a status push
    btn = tab._hotkey_rows["app.refresh"]
    btn.begin_capture()
    tab.set_hotkey_status({"app.refresh": "in use by another application"})
    assert "Press a chord" in btn.text()
    # cancelling the capture via Esc re-applies the pending status by
    # itself (the button's on_capture_end hook) - no manual refresh
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    btn.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert "in use" in btn.text()


def test_click_sync_switch_tracks_external_flip(settings_tab):
    from utils.settings_keys import CLICK_SYNC_ENABLED
    sw = settings_tab._click_sync_switch
    settings_tab.settings_manager.set(CLICK_SYNC_ENABLED, True)
    assert sw.isChecked() is True


def test_launch_slot_combo_sits_inline_with_chord_button(settings_tab):
    # The slot-1 account picker and its chord button share one inline
    # container inside the same InsetRow (no separate picker row).
    from utils.widgets.inset_row import InsetRow
    tab = settings_tab
    combo = tab._hotkey_slot_combos["1"]
    button = tab._hotkey_rows["launch.slot_1"]
    assert combo.parentWidget() is button.parentWidget()
    assert isinstance(combo.parentWidget().parentWidget(), InsetRow)


def test_card_partially_collapsed_by_default(settings_tab):
    from utils.hotkey_actions import ACTIONS
    tab = settings_tab
    card = tab._hotkeys_panel
    assert tab._hotkey_more_container.isHidden()
    first_category = ACTIONS[0].category
    visible_ids = [a.id for a in ACTIONS if a.category == first_category]
    hidden_ids = [a.id for a in ACTIONS if a.category != first_category]
    assert len(visible_ids) == 3
    assert len(hidden_ids) == 13
    for aid in visible_ids:
        assert tab._hotkey_rows[aid].isVisibleTo(card)
    for aid in hidden_ids:
        assert not tab._hotkey_rows[aid].isVisibleTo(card)
        # ...because the row sits inside the hidden container
        assert tab._hotkey_rows[aid].isVisibleTo(tab._hotkey_more_container)
    assert tab._hotkey_more_toggle.text() == f"Show {len(hidden_ids)} more..."


def test_show_more_toggle_reveals_and_collapses(settings_tab):
    tab = settings_tab
    tab._hotkey_more_toggle.click()
    assert not tab._hotkey_more_container.isHidden()
    assert tab._hotkey_more_toggle.text() == "Show less"
    tab._hotkey_more_toggle.click()
    assert tab._hotkey_more_container.isHidden()
    assert tab._hotkey_more_toggle.text() == (
        f"Show {tab._hotkey_more_count} more...")


def test_status_badge_applies_to_hidden_rows(settings_tab):
    # A failure badge pushed while the card is collapsed lands on the
    # hidden row's button, so expanding shows it immediately.
    tab = settings_tab
    assert tab._hotkey_more_container.isHidden()      # collapsed default
    tab.set_hotkey_status({"profile.load_1": "in use by another application"})
    btn = tab._hotkey_rows["profile.load_1"]
    assert btn.text().startswith("Ctrl+1")
    assert "in use" in btn.text()
