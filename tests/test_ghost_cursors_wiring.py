"""MultitoonTab wiring: ghost cursor controller + resolver guard."""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)
    window_geometry_updated = Signal()
    active_window_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []
        self.window_ids = []
        self.window_games = {}
        self.geoms = {}

    def get_window_ids(self): return list(self.window_ids)
    def get_window_geometry(self, wid): return self.geoms.get(wid)
    def get_active_window(self): return None
    def clear_window_ids(self): pass
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass


@pytest.fixture
def multitoon_tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager

    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    try:
        yield tab
    finally:
        # Non-daemon service threads hang pytest if left running.
        tab.input_service.shutdown()
        if tab.click_sync_service is not None:
            tab.click_sync_service.shutdown()
        if tab._click_sync_backend is not None:
            tab._click_sync_backend.disconnect()


def test_controller_constructed_and_listening(multitoon_tab):
    tab = multitoon_tab
    assert tab.ghost_cursor_controller is not None
    tab.click_sync_service.ghost_pointer_event.emit(
        ("motion", [(1, 200, 300)]))
    ov = tab.ghost_cursor_controller._overlays[1]
    assert ov.isVisible()
    assert (ov.x(), ov.y()) == (199, 297)
    tab.click_sync_service.ghost_clear.emit()
    assert not ov.isVisible()


@pytest.mark.skipif(sys.platform != "linux", reason="X11 resolver path (darwin uses active_source_window)")
def test_resolver_treats_own_overlay_as_lookup_failure(multitoon_tab, monkeypatch):
    tab = multitoon_tab
    tab.window_manager.geoms["0x1"] = (0, 0, 100, 100)
    from utils import x11_discovery as x11d
    monkeypatch.setattr(x11d, "toplevel_at_point", lambda x, y: "0xdead")
    monkeypatch.setattr(tab.ghost_cursor_controller, "overlay_wids",
                        lambda: frozenset({"0xdead"}))
    resolver = tab.click_sync_service._source_resolver
    # Our own overlay under the point -> rect fallback finds the member.
    assert resolver(50, 50, ["0x1"]) == "0x1"


@pytest.mark.skipif(sys.platform != "linux", reason="X11 resolver path (darwin uses active_source_window)")
def test_resolver_still_ignores_true_foreign_toplevels(multitoon_tab, monkeypatch):
    tab = multitoon_tab
    tab.window_manager.geoms["0x1"] = (0, 0, 100, 100)
    from utils import x11_discovery as x11d
    monkeypatch.setattr(x11d, "toplevel_at_point", lambda x, y: "0xdead")
    monkeypatch.setattr(x11d, "toplevel_ancestor", lambda wid: wid)
    resolver = tab.click_sync_service._source_resolver
    # A clean foreign-window hit must STILL be ignored (no rect fallback).
    assert resolver(50, 50, ["0x1"]) is None


def test_focus_suppression_wired_to_window_manager(multitoon_tab):
    tab = multitoon_tab
    wm = tab.window_manager
    wm.window_ids = ["0x1", "0x2"]
    wm.window_games = {"0x1": "ttr", "0x2": "ttr"}
    # Ghost appears on slot 1, then its window gains focus -> hidden.
    tab.click_sync_service.ghost_pointer_event.emit(
        ("motion", [(1, 200, 300)]))
    ov = tab.ghost_cursor_controller._overlays[1]
    assert ov.isVisible()
    wm.active_window_changed.emit("0x2")     # slot 1's wid
    assert not ov.isVisible()
    # Suppressed while focused; renders again once focus moves away.
    tab.click_sync_service.ghost_pointer_event.emit(
        ("motion", [(1, 210, 310)]))
    assert not ov.isVisible()
    wm.active_window_changed.emit("0x1")
    tab.click_sync_service.ghost_pointer_event.emit(
        ("motion", [(1, 220, 320)]))
    assert ov.isVisible()
