"""CC mode propagation: when set_compact_cc_subtitle is called on a slot
in full mode, the shared _compact_cc_subtitles[i] label updates to show
the playground / zone string and becomes visible. When called with
playground=None, the label hides.

After the full=compact-clone refactor, full mode uses the same
_compact_cc_subtitles widget that compact uses, so this is a single
behavior test that exercises the shared widget."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

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

    def get_window_ids(self): return []
    def clear_window_ids(self): pass
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass


def _make_tab(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
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


def test_cc_subtitle_hidden_when_no_playground(qapp, monkeypatch, tmp_path):
    tab = _make_tab(qapp, monkeypatch, tmp_path)
    tab.set_compact_cc_subtitle(0, playground=None, zone_name=None)
    subtitle = tab._compact_cc_subtitles[0]
    assert not subtitle.isVisibleTo(tab._full._card_slots[0]["card"])


def test_cc_subtitle_visible_with_playground_only(qapp, monkeypatch, tmp_path):
    tab = _make_tab(qapp, monkeypatch, tmp_path)
    tab.set_compact_cc_subtitle(0, playground="Toontown Central", zone_name=None)
    subtitle = tab._compact_cc_subtitles[0]
    assert subtitle.isVisibleTo(tab._full._card_slots[0]["card"])
    assert "Toontown Central" in subtitle.text()


def test_cc_subtitle_visible_with_playground_and_zone(qapp, monkeypatch, tmp_path):
    tab = _make_tab(qapp, monkeypatch, tmp_path)
    tab.set_compact_cc_subtitle(
        0, playground="Toontown Central", zone_name="Loopy Lane"
    )
    subtitle = tab._compact_cc_subtitles[0]
    assert subtitle.isVisibleTo(tab._full._card_slots[0]["card"])
    assert "Toontown Central" in subtitle.text()
    assert "Loopy Lane" in subtitle.text()
