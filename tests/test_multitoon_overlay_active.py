"""set_overlay_active flips the overlay flag and keeps the keep-alive bar timer
running while the (minimized) main window would otherwise stop it.

Run:
  TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest \
      tests/test_multitoon_overlay_active.py -q
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


def test_set_overlay_active_runs_bar_timer_then_stops(qt_app, monkeypatch, tmp_path):
    tab = _make_tab(monkeypatch, tmp_path)
    qt_app.processEvents()
    # A toon has keep-alive running, but the tab is not shown (isVisible False),
    # so without overlay-awareness the bar timer would be stopped.
    tab.keep_alive_enabled[0] = True
    assert tab._overlay_active is False

    tab.set_overlay_active(True)
    assert tab._overlay_active is True
    assert tab._bar_timer.isActive() is True

    tab.set_overlay_active(False)
    assert tab._overlay_active is False
    # tab is not the visible/current page -> off-page gating stops the timer.
    assert tab._bar_timer.isActive() is False


def test_emblem_backing_disc_pins_dark_in_overlay(qt_app, monkeypatch, tmp_path):
    """Float mode must not inherit the light theme's bg_app backing disc -
    it painted a white ring around the floating emblem (live, 2026-07-07).
    Windowed mode keeps the theme color so the card cutouts blend."""
    from PySide6.QtGui import QColor
    from utils.theme_manager import get_theme_colors
    tab = _make_tab(monkeypatch, tmp_path)
    qt_app.processEvents()
    emblem = tab._compact._emblem
    assert emblem is not None
    tab.settings_manager.set("theme", "light")
    tab._compact._refresh_emblem()
    light_bg = QColor(get_theme_colors(False)["bg_app"])
    dark_bg = QColor(get_theme_colors(True)["bg_app"])
    assert emblem._bg_app == light_bg          # windowed: follows the theme
    tab.set_overlay_active(True)
    assert emblem._bg_app == dark_bg           # floating: pinned dark
    tab.set_overlay_active(False)
    assert emblem._bg_app == light_bg          # back to windowed: theme again
