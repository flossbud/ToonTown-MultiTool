"""GhostCursorOverlay / GhostCursorController offscreen tests."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from PySide6.QtCore import QObject, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeService(QObject):
    ghost_pointer_event = Signal(object)
    ghost_clear = Signal()


class StubSettings:
    def __init__(self, values=None):
        self._d = dict(values or {})
        self._listeners = []

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value):
        self._d[key] = value
        for fn in list(self._listeners):
            fn(key, value)

    def on_change(self, fn):
        self._listeners.append(fn)


@pytest.fixture
def rig(qapp):
    from tabs.multitoon._ghost_cursors import GhostCursorController
    svc = FakeService()
    settings = StubSettings()
    ctl = GhostCursorController(svc, settings)
    yield svc, settings, ctl
    ctl._hide_all()
    for ov in ctl._overlays.values():
        ov.deleteLater()


def test_event_shows_overlay_at_hotspot_offset(rig):
    svc, _, ctl = rig
    svc.ghost_pointer_event.emit(("motion", [(1, 200, 300)]))
    ov = ctl._overlays[1]
    assert ov.isVisible()
    assert (ov.x(), ov.y()) == (199, 297)  # (x-1, y-3): fingertip hotspot


def test_each_slot_maps_to_its_toon_asset():
    from tabs.multitoon import _ghost_cursors as gc
    assert gc._cursor_path(0).endswith(
        os.path.join("assets", "cursors", "toon1.png"))
    assert gc._cursor_path(3).endswith(
        os.path.join("assets", "cursors", "toon4.png"))
    assert os.path.isfile(gc._cursor_path(0))  # assets are tracked/on disk


def test_idle_timer_armed_and_idle_fades(rig):
    svc, _, ctl = rig
    svc.ghost_pointer_event.emit(("motion", [(0, 50, 50)]))
    t = ctl._timers[0]
    assert t.isActive()
    assert t.interval() == 1500
    ctl._on_idle(0)
    ov = ctl._overlays[0]
    assert ov._fade.state() == QPropertyAnimation.State.Running
    ov._fade.stop()
    ov.hide()


def test_clear_hides_instantly_and_stops_timers(rig):
    svc, _, ctl = rig
    svc.ghost_pointer_event.emit(("motion", [(0, 50, 50), (1, 60, 60)]))
    svc.ghost_clear.emit()
    assert all(not ov.isVisible() for ov in ctl._overlays.values())
    assert all(not t.isActive() for t in ctl._timers.values())


def test_setting_off_hides_and_gates_live(rig):
    from utils.settings_keys import GHOST_CURSORS_ENABLED
    svc, settings, ctl = rig
    svc.ghost_pointer_event.emit(("motion", [(0, 50, 50)]))
    settings.set(GHOST_CURSORS_ENABLED, False)
    assert not ctl._overlays[0].isVisible()
    svc.ghost_pointer_event.emit(("motion", [(0, 70, 70)]))
    assert not ctl._overlays[0].isVisible()
    settings.set(GHOST_CURSORS_ENABLED, True)
    svc.ghost_pointer_event.emit(("motion", [(0, 80, 80)]))
    assert ctl._overlays[0].isVisible()


def test_persisted_off_respected_at_build(qapp):
    from tabs.multitoon._ghost_cursors import GhostCursorController
    from utils.settings_keys import GHOST_CURSORS_ENABLED
    svc = FakeService()
    ctl = GhostCursorController(
        svc, StubSettings({GHOST_CURSORS_ENABLED: False}))
    svc.ghost_pointer_event.emit(("motion", [(0, 50, 50)]))
    assert ctl._overlays == {}


def test_platform_support_matrix():
    from tabs.multitoon._ghost_cursors import GhostCursorController
    assert GhostCursorController._platform_unsupported("wayland")
    assert GhostCursorController._platform_unsupported("xcb") is None
    assert GhostCursorController._platform_unsupported("windows") is None
    assert GhostCursorController._platform_unsupported("offscreen") is None


def test_missing_asset_disables_quietly(rig, monkeypatch):
    svc, _, ctl = rig
    from tabs.multitoon import _ghost_cursors as gc
    monkeypatch.setattr(gc, "_cursor_path",
                        lambda slot: "/nonexistent/toon.png")
    svc.ghost_pointer_event.emit(("motion", [(2, 50, 50)]))
    assert ctl._disabled_reason
    assert 2 not in ctl._overlays
    svc.ghost_pointer_event.emit(("motion", [(2, 60, 60)]))  # no crash
    assert 2 not in ctl._overlays


def test_overlay_flags_input_transparent(rig):
    svc, _, ctl = rig
    svc.ghost_pointer_event.emit(("motion", [(3, 10, 10)]))
    fl = ctl._overlays[3].windowFlags()
    assert fl & Qt.WindowTransparentForInput
    assert fl & Qt.WindowStaysOnTopHint
    assert fl & Qt.FramelessWindowHint
    assert fl & Qt.WindowDoesNotAcceptFocus


def test_overlay_wids_cached_after_create(rig):
    svc, _, ctl = rig
    assert ctl.overlay_wids() == frozenset()
    svc.ghost_pointer_event.emit(("motion", [(0, 10, 10)]))
    wids = ctl.overlay_wids()
    assert len(wids) == 1
    assert all(isinstance(w, str) for w in wids)


def test_show_at_during_inflight_fade_keeps_overlay_visible(rig):
    """Pin the fade-cancel path: a mid-flight QPropertyAnimation.stop() must
    NOT emit finished->hide (verified on PySide6 6.10; a refactor to e.g.
    setCurrentTime(duration) would regress this into an unmap/map flicker
    at event rate)."""
    from PySide6.QtCore import QPropertyAnimation
    svc, _, ctl = rig
    svc.ghost_pointer_event.emit(("motion", [(0, 50, 50)]))
    ov = ctl._overlays[0]
    ov.fade_out()
    ov._fade.setCurrentTime(75)  # genuinely mid-flight
    assert ov._fade.state() == QPropertyAnimation.State.Running
    ov.show_at(80, 80)
    assert ov.isVisible()
    assert ov.windowOpacity() == 1.0
    assert ov._fade.state() == QPropertyAnimation.State.Stopped
