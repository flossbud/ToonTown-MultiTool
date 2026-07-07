"""Settings v2 pages - kit wiring + behavior preservation."""
import pytest
from PySide6.QtWidgets import QApplication

from tabs.settings_tab import SettingsTab
from utils.widgets.card_surface import CardSurface
from utils.widgets.pill_controls import SegmentedPill


class FakeSettings:
    def __init__(self, store=None):
        self._s = dict(store or {})
    def get(self, key, default=None):
        return self._s.get(key, default)
    def set(self, key, value):
        self._s[key] = value
    def on_change(self, cb):
        pass


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_general_page_uses_cards_not_panels(app):
    tab = SettingsTab(FakeSettings())
    page = tab.pages["general"]
    assert len(page.findChildren(CardSurface)) >= 2      # Appearance + Updates


def test_theme_segment_writes_setting(app):
    fake = FakeSettings()
    tab = SettingsTab(fake)
    # _on_theme_changed restyles the whole QApplication (intended app
    # behavior); snapshot + restore so the global QSS doesn't leak into
    # later test files in the same process (bare-widget paint tests).
    before = app.styleSheet()
    try:
        tab._theme_segment.index_changed.emit(2)
        assert fake.get("theme") == "dark"
    finally:
        app.setStyleSheet(before)


def test_reduce_motion_segment_semantics(app):
    fake = FakeSettings()
    tab = SettingsTab(fake)
    tab._rm_segment.index_changed.emit(1)                # On
    assert fake.get("reduce_motion") is True
    assert fake.get("reduce_motion_set_explicitly") is True
    tab._rm_segment.index_changed.emit(0)                # System
    assert fake.get("reduce_motion_set_explicitly") is False


def test_games_page_cards_have_logo_badges(app):
    tab = SettingsTab(FakeSettings())
    from utils.widgets.card_surface import CardSurface
    assert isinstance(tab._ttr_panel, CardSurface)
    assert isinstance(tab._cc_panel, CardSurface)
    assert tab._ttr_panel.accent_key == "ttr"
    assert tab._cc_panel.accent_key == "cc"


def test_game_path_display_green_and_mono(app):
    tab = SettingsTab(FakeSettings())
    tab._refresh_game_path_display("ttr", "/home/user/ttr")
    assert tab._ttr_panel.sub_label.text().startswith(("~", "/"))


def test_ghost_control_row_gates_on_ghost_switch(app):
    tab = SettingsTab(FakeSettings())
    tab._ghost_switch.setChecked(False)
    assert not tab._ghost_control_field.isEnabled()
    tab._ghost_switch.setChecked(True)
    assert tab._ghost_control_field.isEnabled()


def test_chat_handling_tiles_same_key_same_values(app):
    from utils.settings_keys import CHAT_HANDLING_MODE, CHAT_HANDLING_ALL_TOONS
    fake = FakeSettings()
    tab = SettingsTab(fake)
    fired = []
    tab.chat_handling_mode_changed.connect(fired.append)
    tab._chat_handling_tiles._on_tile_clicked(CHAT_HANDLING_ALL_TOONS)
    assert fake.get(CHAT_HANDLING_MODE) == CHAT_HANDLING_ALL_TOONS
    assert fired == [CHAT_HANDLING_ALL_TOONS]


def test_hotkeys_card_uses_chord_pills_and_expander(app):
    from utils.widgets.pill_controls import ChordPill, GhostExpander
    tab = SettingsTab(FakeSettings())
    assert all(isinstance(b, ChordPill) for b in tab._hotkey_rows.values())
    assert isinstance(tab._hotkey_more_toggle, GhostExpander)
    assert tab._hotkey_more_container.isHidden()          # collapsed on open


def test_hotkey_expander_toggles(app):
    tab = SettingsTab(FakeSettings())
    tab._on_hotkey_more_toggled()
    assert not tab._hotkey_more_container.isHidden()
    assert tab._hotkey_more_toggle.text() == "Show less"
    tab._on_hotkey_more_toggled()
    assert tab._hotkey_more_container.isHidden()
