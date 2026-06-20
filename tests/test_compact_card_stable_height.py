"""The compact card height must NOT depend on whether the laff/bean stats are
shown. Otherwise a card sized while data is absent (e.g. entering transparent
mode before the toon-data API responds) is too short, and when the stats appear
the content clips. Reserving the stats row's space (retainSizeWhenHidden) keeps
the card a consistent size regardless of data.

Run:
  TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest \
      tests/test_compact_card_stable_height.py -q
"""
from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(sys.argv)


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)
    cell_assignment_changed = Signal(list)
    window_geometry_updated = Signal()
    active_window_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []
        self.slot_cells = [0, 1, 2, 3]

    def get_window_ids(self): return list(self.ttr_window_ids)
    def get_active_window(self): return None
    def clear_window_ids(self): self.ttr_window_ids = []
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass
    def count_for_game(self, g): return 0
    def get_window_geometry(self, wid): return None


def _make_tab(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("TTMT_NO_VENV_REEXEC", "1")
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    import tabs.launch_tab
    tabs.launch_tab.discover_cc_installs = lambda *a, **k: []
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    return MultitoonTab(settings_manager=SettingsManager(),
                        window_manager=_FakeWindowManager())


def test_card_height_independent_of_stats_visibility(qt_app, monkeypatch, tmp_path):
    tab = _make_tab(monkeypatch, tmp_path)
    qt_app.processEvents()
    c = tab._compact
    tab._stack.setCurrentWidget(c)
    tab.show()
    for _ in range(6):
        qt_app.processEvents()

    def toggle(visible):
        for i in range(4):
            for lbl in (tab.laff_labels[i], tab.bean_labels[i]):
                lbl.setText(" 137/137")
                lbl.setVisible(visible)
        for _ in range(4):
            qt_app.processEvents()

    toggle(False)
    hidden_h = c.card_size()[1]
    toggle(True)
    shown_h = c.card_size()[1]

    assert hidden_h == shown_h, (
        f"card height must not depend on stats visibility "
        f"(hidden={hidden_h}, shown={shown_h}); reserve the stats-row space"
    )
