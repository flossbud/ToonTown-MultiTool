"""Mode-switch (compact <-> full) guard while overlay is open."""

from __future__ import annotations

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
    def __init__(self): super().__init__(); self.ttr_window_ids = []
    def get_window_ids(self): return []
    def clear_window_ids(self): pass
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass
    def get_active_window(self): return None


def _open_overlay_on_main(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    from utils.widgets.customization_overlay import ToonCustomizationOverlay
    from PySide6.QtWidgets import QMainWindow
    from main import MultiToonTool

    win = QMainWindow()
    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    win.setCentralWidget(tab)
    win.resize(575, 770)
    win.show()
    tab.toon_names[0] = "Flossbud"
    tab.slot_badges[0].set_toon_name("Flossbud")
    tab.slot_badges[0].set_game("ttr")

    win.customization_overlay = ToonCustomizationOverlay(tab)
    win.customization_overlay._skip_animations_for_test = True
    win.multitoon_tab = tab
    win.customization_overlay.open_for(
        0, "ttr", "Flossbud", tab.customizations, None, None, None,
    )
    win._set_layout_mode = MultiToonTool._set_layout_mode.__get__(win, type(win))
    win._resume_pending_mode_swap = MultiToonTool._resume_pending_mode_swap.__get__(win, type(win))
    # MultiToonTool._set_layout_mode reaches for launch_tab; supply a noop stand-in.
    win.launch_tab = type("_LT", (), {"set_layout_mode": staticmethod(lambda m: None)})()
    return win, tab


def test_mode_swap_with_clean_draft_closes_overlay(qapp, tmp_path, monkeypatch):
    win, tab = _open_overlay_on_main(qapp, tmp_path, monkeypatch)
    # Patch tab.set_layout_mode to track calls.
    calls = []
    orig = tab.set_layout_mode
    def _spy(m):
        calls.append(m)
        orig(m)
    tab.set_layout_mode = _spy

    win._set_layout_mode("full")
    overlay = win.customization_overlay
    assert not overlay.isVisible()
    assert calls == ["full"]
    if hasattr(tab, "input_service") and tab.input_service:
        tab.input_service.shutdown()


def test_mode_swap_with_dirty_draft_shows_confirm(qapp, tmp_path, monkeypatch):
    win, tab = _open_overlay_on_main(qapp, tmp_path, monkeypatch)
    overlay = win.customization_overlay
    overlay._panel.set_body("#56c856")
    calls = []
    tab.set_layout_mode = lambda m: calls.append(m)

    win._set_layout_mode("full")
    # Overlay must still be open with the prompt visible.
    assert overlay.isVisible()
    assert overlay._confirm_prompt.isVisible()
    # Mode swap NOT executed.
    assert calls == []

    # User chooses discard.
    overlay._confirm_prompt.discard_btn.click()
    # Now the deferred swap proceeds.
    assert calls == ["full"]
    if hasattr(tab, "input_service") and tab.input_service:
        tab.input_service.shutdown()


def test_mode_swap_with_dirty_keep_aborts(qapp, tmp_path, monkeypatch):
    win, tab = _open_overlay_on_main(qapp, tmp_path, monkeypatch)
    overlay = win.customization_overlay
    overlay._panel.set_body("#56c856")
    calls = []
    tab.set_layout_mode = lambda m: calls.append(m)

    win._set_layout_mode("full")
    overlay._confirm_prompt.keep_btn.click()
    # Mode swap never happens.
    assert calls == []
    assert overlay.isVisible()
    if hasattr(tab, "input_service") and tab.input_service:
        tab.input_service.shutdown()
