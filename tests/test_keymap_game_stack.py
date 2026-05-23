"""Covers the per-game QStackedWidget restructure, _entries_by_game,
signal-binding shift, and per-game header banner."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QStackedWidget, QLabel, QFrame, QPushButton


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSettings:
    def __init__(self):
        self._d = {"ttr_engine_dir": "", "cc_engine_dir": "", "theme": "dark"}
    def get(self, k, default=None):
        return self._d.get(k, default)
    def set(self, k, v):
        self._d[k] = v
    def on_change(self, cb):
        pass


class _FakeCredManager:
    def __init__(self, ttr=0, cc=0):
        self._ttr_count = ttr
        self._cc_count = cc
    def get_accounts_metadata(self, game=None):
        if game == "ttr":
            return [object()] * self._ttr_count
        if game == "cc":
            return [object()] * self._cc_count
        return [object()] * (self._ttr_count + self._cc_count)
    def on_change(self, cb):
        pass


def _make_tab(qapp, monkeypatch, *, ttr=True, cc=True):
    from tabs.keymap_tab import KeymapTab
    from utils.keymap_manager import KeymapManager
    monkeypatch.setattr(KeymapTab, "_ttr_detected", lambda self: ttr)
    monkeypatch.setattr(KeymapTab, "_cc_detected", lambda self: cc)
    return KeymapTab(
        KeymapManager(),
        settings_manager=_FakeSettings(),
        credentials_manager=_FakeCredManager(),
    )


def test_game_stack_exists(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch)
    assert isinstance(tab._game_stack, QStackedWidget)


def test_game_stack_has_two_pages(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch)
    assert tab._game_stack.count() == 2


def test_game_index_map(qapp, monkeypatch):
    from tabs.keymap_tab import _GAME_INDEX
    assert _GAME_INDEX == {"ttr": 0, "cc": 1}


def test_active_page_matches_active_game_ttr(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch, ttr=True, cc=True)
    # Default active when both detected = TTR (per existing logic).
    assert tab._active_game == "ttr"
    assert tab._game_stack.currentIndex() == 0


def test_active_page_matches_active_game_cc_only(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch, ttr=False, cc=True)
    assert tab._active_game == "cc"
    assert tab._game_stack.currentIndex() == 1


def test_per_game_header_label_text_ttr(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch)
    label = tab.findChild(QLabel, "header_label_ttr")
    assert label is not None
    assert label.text() == "ToonTown Rewritten Keysets"


def test_per_game_header_label_text_cc(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch)
    label = tab.findChild(QLabel, "header_label_cc")
    assert label is not None
    assert label.text() == "Corporate Clash Keysets"


def test_per_game_header_label_color_ttr(qapp, monkeypatch):
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)
    tab = _make_tab(qapp, monkeypatch)
    label = tab.findChild(QLabel, "header_label_ttr")
    qss = label.styleSheet()
    assert c["game_pill_ttr"].lower() in qss.lower()


def test_per_game_header_label_color_cc(qapp, monkeypatch):
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)
    tab = _make_tab(qapp, monkeypatch)
    label = tab.findChild(QLabel, "header_label_cc")
    qss = label.styleSheet()
    assert c["game_pill_cc"].lower() in qss.lower()


def test_per_game_header_label_uses_small_heading_style(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch)
    label = tab.findChild(QLabel, "header_label_ttr")
    qss = label.styleSheet()
    assert "font-size: 10px" in qss
    assert "font-weight: 600" in qss
    assert "letter-spacing: 0.8px" in qss


def test_per_game_header_divider_color_ttr(qapp, monkeypatch):
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)
    tab = _make_tab(qapp, monkeypatch)
    div = tab.findChild(QFrame, "header_divider_ttr")
    assert div is not None
    assert div.height() == 2 or div.minimumHeight() == 2
    qss = div.styleSheet()
    assert c["game_pill_ttr"].lower() in qss.lower()


def test_per_game_header_divider_color_cc(qapp, monkeypatch):
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)
    tab = _make_tab(qapp, monkeypatch)
    div = tab.findChild(QFrame, "header_divider_cc")
    assert div is not None
    qss = div.styleSheet()
    assert c["game_pill_cc"].lower() in qss.lower()


def test_entries_by_game_split(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch)
    assert "ttr" in tab._entries_by_game
    assert "cc" in tab._entries_by_game
    # Default keymap has at least one set per game.
    assert len(tab._entries_by_game["ttr"]) >= 1
    assert len(tab._entries_by_game["cc"]) >= 1
    # Lists are independent objects.
    assert tab._entries_by_game["ttr"] is not tab._entries_by_game["cc"]


def test_entries_property_returns_active_game_entries(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch, ttr=True, cc=True)
    # _active_game = "ttr"; _entries should equal _entries_by_game["ttr"]
    assert tab._entries is tab._entries_by_game["ttr"]


def test_add_button_per_page(qapp, monkeypatch):
    tab = _make_tab(qapp, monkeypatch)
    btn_ttr = tab.findChild(QPushButton, "add_btn_ttr")
    btn_cc = tab.findChild(QPushButton, "add_btn_cc")
    assert btn_ttr is not None
    assert btn_cc is not None
    assert btn_ttr is not btn_cc


def test_signal_binding_targets_correct_game(qapp, monkeypatch):
    """The signal-binding-with-game-name shift: a card on the CC page
    that emits name_changed must persist to CC's keymap, not TTR's."""
    tab = _make_tab(qapp, monkeypatch)
    # Find a SetCard on the CC page (index > 0 so it's a renameable one).
    from tabs.keymap_tab import SetCard
    cc_page = tab._game_stack.widget(1)
    cc_cards = cc_page.findChildren(SetCard)
    assert len(cc_cards) >= 1
    cc_card_default = cc_cards[0]
    # Emit name_changed from the CC default-set card.
    cc_card_default.name_changed.emit("Renamed-CC-Default")
    # Active game is TTR; if the binding leaked, the rename would land on TTR's manager state.
    ttr_set = tab.keymap_manager.get_sets("ttr")[0]
    cc_set = tab.keymap_manager.get_sets("cc")[0]
    assert ttr_set["name"] != "Renamed-CC-Default"
    assert cc_set["name"] == "Renamed-CC-Default"
