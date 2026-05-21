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
    # Compact is the default layout mode
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


def test_compact_cc_subtitle_hidden_when_no_data(qapp, monkeypatch, tmp_path):
    tab = _make_tab(qapp, monkeypatch, tmp_path)
    # Subtitle widget exists but text is empty and it is hidden by default
    sub = tab._compact_cc_subtitles[0]
    assert sub.text() == ""
    card = tab.toon_cards[0]
    assert not _visible_to_card(sub, card)


def test_set_compact_cc_subtitle_shows_label(qapp, monkeypatch, tmp_path):
    tab = _make_tab(qapp, monkeypatch, tmp_path)
    tab.set_compact_cc_subtitle(0, "Toontown Central", "Loopy Lane")
    sub = tab._compact_cc_subtitles[0]
    card = tab.toon_cards[0]
    assert _visible_to_card(sub, card)
    assert "Toontown Central" in sub.text()
    assert "Loopy Lane" in sub.text()


def test_set_compact_cc_subtitle_playground_only(qapp, monkeypatch, tmp_path):
    tab = _make_tab(qapp, monkeypatch, tmp_path)
    tab.set_compact_cc_subtitle(0, "Toontown Central", None)
    sub = tab._compact_cc_subtitles[0]
    card = tab.toon_cards[0]
    assert _visible_to_card(sub, card)
    assert "Toontown Central" in sub.text()
    assert "\xb7" not in sub.text()  # middle dot (·)


def test_clear_compact_cc_subtitle_hides_it(qapp, monkeypatch, tmp_path):
    tab = _make_tab(qapp, monkeypatch, tmp_path)
    tab.set_compact_cc_subtitle(0, "Toontown Central", "Loopy Lane")
    tab.set_compact_cc_subtitle(0, None, None)
    sub = tab._compact_cc_subtitles[0]
    card = tab.toon_cards[0]
    assert not _visible_to_card(sub, card)
