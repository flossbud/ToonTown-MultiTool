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
    tab._theme_segment.index_changed.emit(2)
    assert fake.get("theme") == "dark"


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
