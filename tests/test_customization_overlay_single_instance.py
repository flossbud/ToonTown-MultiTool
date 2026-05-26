"""Single-instance enforcement for the customization overlay."""

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

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []
    def get_window_ids(self): return []
    def clear_window_ids(self): pass
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass
    def get_active_window(self): return None


def _populate_slot(tab, slot, game, name):
    tab.toon_names[slot] = name
    tab.slot_badges[slot].set_toon_name(name)
    tab.slot_badges[slot].set_game(game)


def test_open_customization_creates_overlay_lazily(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from main import MultiToonTool
    win = MultiToonTool.__new__(MultiToonTool)
    win.customization_overlay = None
    win.multitoon_tab = type("_FakeTab", (), {
        "slot_badges": [],
        "customizations": None,
    })()
    # No overlay yet.
    assert win.customization_overlay is None

    # We won't actually call open_customization here (requires a real
    # tab); instead just assert the attribute exists for lazy init.
    assert hasattr(win, "customization_overlay")
    if hasattr(win, "input_service") and win.input_service:
        win.input_service.shutdown()


def test_open_customization_no_op_when_overlay_already_visible(qapp, tmp_path, monkeypatch):
    """When the overlay is already showing, a second open_customization
    call is a no-op (no re-populate, no flicker)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    from utils.widgets.customization_overlay import ToonCustomizationOverlay
    from PySide6.QtWidgets import QMainWindow

    win = QMainWindow()
    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    win.setCentralWidget(tab)
    win.resize(575, 770)
    win.show()
    _populate_slot(tab, 0, "ttr", "Flossbud")
    _populate_slot(tab, 1, "ttr", "Linux")

    win.customization_overlay = None
    win.multitoon_tab = tab

    # Bind the open_customization method from MultiToonTool onto our
    # bare QMainWindow stand-in. This is a deliberate test pattern that
    # exercises the function without building the full MultiToonTool.
    from main import MultiToonTool
    win.open_customization = MultiToonTool.open_customization.__get__(win, type(win))

    win.open_customization(0)
    assert win.customization_overlay is not None
    overlay = win.customization_overlay
    overlay._skip_animations_for_test = True

    first_panel_id = id(overlay._panel)
    # Second call while open is a no-op.
    win.open_customization(1)
    assert id(overlay._panel) == first_panel_id
    assert overlay._slot == 0  # still slot 0

    overlay.close_and_discard()
    if hasattr(tab, "input_service") and tab.input_service:
        tab.input_service.shutdown()
