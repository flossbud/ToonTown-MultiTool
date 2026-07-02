"""A visually hidden card shell must contribute NO accent glow.

The pinwheel's _GlowLayer is a single sibling widget painted BEHIND the four
cells, fed by _refresh_glow() with one halo spec per LIT (active) cell. The
float overlay hides cells via setVisible(False) with retained size (the
Hide-Cards toggle and the empty-cell occupancy hide), which does not touch
the sibling layer - so the spec build itself must skip hidden shells, or a
lit card's accent halo keeps painting over bare desktop (live bug,
2026-07-02: hide cards after toon data loads -> pink/green glow persists).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
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
    def get_active_window(self): return None


def _build_tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    tab.resize(1000, 800)
    for _ in range(3):
        qapp.processEvents()
    return tab


def test_refresh_glow_skips_hidden_shells(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    compact = tab._compact
    cell = compact._card_slots[0]
    cell["active"] = True
    cell["accent"] = QColor("#ff64c8")

    compact._refresh_glow()
    assert len(compact._glow._cards) == 1        # lit + visible -> one halo

    cell["cell"].setVisible(False)               # the overlay's visual hide
    compact._refresh_glow()
    assert compact._glow._cards == []            # hidden shell -> NO halo

    cell["cell"].setVisible(True)
    compact._refresh_glow()
    assert len(compact._glow._cards) == 1        # restored on re-show
