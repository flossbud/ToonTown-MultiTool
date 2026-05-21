import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self):
        return []

    def clear_window_ids(self):
        pass

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass


def _make_tab(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_NO_VENV_REEXEC", "1")
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager

    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    tab.set_layout_mode("full")
    for _ in range(5):
        qapp.processEvents()
    return tab


def _visible_to_card(widget, card):
    """Check whether widget is configured to show within its card subtree.

    QWidget.isVisible() returns False for any widget whose top-level window
    has never been shown (as in offscreen tests). isVisibleTo(ancestor)
    checks the show/hide state relative to a given ancestor, which is what
    we care about here.
    """
    return widget.isVisibleTo(card)


def test_cc_chip_row_hidden_when_no_playground(qapp, monkeypatch, tmp_path):
    tab = _make_tab(qapp, monkeypatch, tmp_path)
    card = tab._full._cards[0]
    card.set_cc_mode(playground=None, zone_name=None)
    # Chip row exists but is hidden
    assert card._cc_chip_row_container is not None
    assert not _visible_to_card(card._cc_chip_row_container, card)


def test_cc_chip_row_visible_with_playground_only(qapp, monkeypatch, tmp_path):
    tab = _make_tab(qapp, monkeypatch, tmp_path)
    card = tab._full._cards[0]
    card.set_active(True)
    card.set_cc_mode(playground="Toontown Central", zone_name=None)
    assert _visible_to_card(card._cc_chip_row_container, card)
    assert _visible_to_card(card._cc_playground_chip, card)
    assert "Toontown Central" in card._cc_playground_chip.text()
    # No zone chip
    assert not _visible_to_card(card._cc_zone_chip, card)


def test_cc_chip_row_visible_with_playground_and_zone(qapp, monkeypatch, tmp_path):
    tab = _make_tab(qapp, monkeypatch, tmp_path)
    card = tab._full._cards[0]
    card.set_active(True)
    card.set_cc_mode(playground="Toontown Central", zone_name="Loopy Lane")
    assert _visible_to_card(card._cc_chip_row_container, card)
    assert _visible_to_card(card._cc_playground_chip, card)
    assert _visible_to_card(card._cc_zone_chip, card)
    assert card._cc_zone_chip.text() == "Loopy Lane"
