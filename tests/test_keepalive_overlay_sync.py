"""The keep-alive bar phase is a pure function of the monotonic anchor + clock,
identical regardless of overlay mode. This is what makes window<->transparent
switches resume mid-cycle with no jump. Guards against re-anchoring on switch.

Run:
  TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest \
      tests/test_keepalive_overlay_sync.py -q
"""
from __future__ import annotations

import sys
import time

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

    def get_window_ids(self): return []
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


def _progress_of_slot0(tab):
    return tab.ka_progress_bars[0]._progress


def test_progress_identical_across_overlay_mode(qt_app, monkeypatch, tmp_path):
    tab = _make_tab(monkeypatch, tmp_path)
    qt_app.processEvents()
    tab.keep_alive_enabled[0] = True
    # Pin a deterministic mid-cycle anchor (delay default is 60s; 15s in -> 0.25).
    tab._ka_cycle_start = time.monotonic() - 15.0

    # Framed mode tick.
    tab._overlay_active = False
    tab._tick_progress_bars()
    framed = _progress_of_slot0(tab)

    # Switch to overlay WITHOUT touching the anchor; tick again.
    tab._overlay_active = True
    tab._tick_progress_bars()
    overlay = _progress_of_slot0(tab)

    assert framed == pytest.approx(overlay, abs=0.02)
    assert framed > 0.0  # genuinely mid-cycle, not a degenerate 0


def test_set_overlay_active_does_not_reset_anchor(qt_app, monkeypatch, tmp_path):
    tab = _make_tab(monkeypatch, tmp_path)
    qt_app.processEvents()
    tab.keep_alive_enabled[0] = True
    anchor = time.monotonic() - 9.0
    tab._ka_cycle_start = anchor
    tab.set_overlay_active(True)
    assert tab._ka_cycle_start == anchor      # entering overlay must not re-anchor
    tab.set_overlay_active(False)
    assert tab._ka_cycle_start == anchor      # nor leaving it
