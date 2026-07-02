"""Glove echo over the float cards: offscreen tests.

The stacking problem itself (confined ghost windows sit BELOW the dock-layer
cluster, so a glove vanishes under a card) is WM behavior and cannot run
offscreen; these tests cover the compositing machinery around it: the
GhostEchoLayer's fail-closed clip painting, the GhostCursorController's
sink mirroring (confined mode only, never raising), and the
ClusterOverlayController's echo lifecycle + painted-content clip geometry.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
        PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
        ./venv/bin/python -m pytest tests/test_ghost_echo.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("TTMT_NO_RADIAL_ANIM", "1")
os.environ.setdefault("TTMT_NO_OVERLAY_SCALE_ANIM", "1")

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, Signal
from PySide6.QtGui import QColor, QImage, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from tabs.multitoon import _ghost_cursors as gc
from utils.overlay.ghost_echo import GhostEchoLayer

# The cluster harness (stub provider/window/surface + geometry constants) is
# shared with the cluster-controller suite so the provider contract has a
# single source of truth.
from tests.test_cluster_controller import (
    _make, _win_pt, _EMBLEM_CX, _EMBLEM_CY,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _pm(size=32, color="#ff0000"):
    pm = QPixmap(size, size)
    pm.fill(QColor(color))
    return pm


def _render(widget) -> QImage:
    img = QImage(widget.width(), widget.height(),
                 QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    widget.render(img)
    return img


def _alpha_at(img: QImage, x: int, y: int) -> int:
    return (img.pixel(x, y) >> 24) & 0xFF


def _rect_clip(x, y, w, h) -> QPainterPath:
    path = QPainterPath()
    path.addRect(float(x), float(y), float(w), float(h))
    return path


@pytest.fixture
def layer(qapp):
    holder = QWidget()
    holder.resize(200, 200)
    lay = GhostEchoLayer(holder)
    lay.setGeometry(0, 0, 200, 200)
    yield lay
    holder.deleteLater()


# -- GhostEchoLayer: fail-closed clip painting --------------------------------

def test_no_clip_draws_nothing(layer):
    layer.show_slot(0, QPoint(50, 50), _pm())
    img = _render(layer)
    assert _alpha_at(img, 60, 60) == 0      # fail closed: no clip, no echo


def test_draws_inside_clip_only(layer):
    layer.set_clip(_rect_clip(40, 40, 26, 160))   # clip ends at x=66
    layer.show_slot(0, QPoint(50, 50), _pm())     # sprite spans x 50..82
    img = _render(layer)
    assert _alpha_at(img, 60, 60) > 0        # inside the clip
    assert _alpha_at(img, 70, 60) == 0       # sprite pixel past the clip edge


def test_sprite_fully_outside_clip_invisible(layer):
    layer.set_clip(_rect_clip(0, 0, 40, 40))
    layer.show_slot(0, QPoint(100, 100), _pm())
    img = _render(layer)
    assert _alpha_at(img, 110, 110) == 0


def test_empty_clip_draws_nothing(layer):
    layer.set_clip(QPainterPath())
    layer.show_slot(0, QPoint(50, 50), _pm())
    img = _render(layer)
    assert _alpha_at(img, 60, 60) == 0


def test_hide_slot_and_clear(layer):
    layer.set_clip(_rect_clip(0, 0, 200, 200))
    layer.show_slot(0, QPoint(20, 20), _pm())
    layer.show_slot(1, QPoint(120, 120), _pm())
    layer.hide_slot(0)
    img = _render(layer)
    assert _alpha_at(img, 30, 30) == 0
    assert _alpha_at(img, 130, 130) > 0
    layer.clear()
    img = _render(layer)
    assert _alpha_at(img, 130, 130) == 0


def test_fade_dims_then_show_cancels(layer):
    layer.set_clip(_rect_clip(0, 0, 200, 200))
    layer.show_slot(0, QPoint(20, 20), _pm())
    layer.fade_slot(0, 10_000)                    # long fade: never completes here
    assert layer._slots[0]["fade"] is not None
    layer._on_fade_value(0, 0.5)                  # deterministic mid-fade frame
    img = _render(layer)
    mid = _alpha_at(img, 30, 30)
    assert 0 < mid < 255
    layer.show_slot(0, QPoint(20, 20), _pm())     # fresh event cancels the fade
    assert layer._slots[0]["fade"] is None
    assert layer._slots[0]["opacity"] == 1.0


def test_fade_completion_drops_slot(qapp, layer):
    layer.set_clip(_rect_clip(0, 0, 200, 200))
    layer.show_slot(0, QPoint(20, 20), _pm())
    layer.fade_slot(0, 0)                         # zero duration: finishes at start
    qapp.processEvents()
    assert 0 not in layer._slots


# -- GhostCursorController: sink mirroring ------------------------------------

class RecordingSink:
    def __init__(self):
        self.calls = []

    def ghost_echo_shown(self, slot, x, y, pixmap):
        self.calls.append(("shown", slot, x, y, pixmap))

    def ghost_echo_fading(self, slot, duration_ms):
        self.calls.append(("fading", slot, duration_ms))

    def ghost_echo_hidden(self, slot):
        self.calls.append(("hidden", slot))

    def ghost_echo_cleared(self):
        self.calls.append(("cleared",))


class RaisingSink:
    def __getattr__(self, name):
        def boom(*_a, **_k):
            raise RuntimeError("sink boom")
        return boom


class FakeService(QObject):
    ghost_pointer_event = Signal(object)
    ghost_clear = Signal()


@pytest.fixture
def confined_ctl(qapp, monkeypatch):
    monkeypatch.setattr(gc, "_confinement_reason", lambda: None)
    monkeypatch.setattr(gc.x11_transient, "confine", lambda *_a: True)
    svc = FakeService()
    ctl = gc.GhostCursorController(
        svc, None,
        slot_window_resolver=lambda slot: "777" if slot == 1 else None)
    assert ctl._confined is True
    yield svc, ctl
    ctl._hide_all()
    for ov in ctl._overlays.values():
        ov.deleteLater()


def test_pointer_event_mirrors_shown_with_hotspot(confined_ctl):
    svc, ctl = confined_ctl
    sink = RecordingSink()
    ctl.set_echo_sink(sink)
    svc.ghost_pointer_event.emit(("motion", [(1, 101, 103)]))
    ov = ctl._overlays[1]
    # top-left = logical point minus the glove hotspot, same as the window move
    assert sink.calls == [("shown", 1, 100, 100, ov._pixmap)]
    assert (ov.x(), ov.y()) == (100, 100)


def test_echo_stamp_names_state(qapp, confined_ctl, capsys):
    _svc, ctl = confined_ctl
    ctl.set_echo_sink(RecordingSink())
    out = capsys.readouterr().out
    assert "[GhostCursors] card echo: armed (confined mode)" in out


def test_idle_mirrors_fading(confined_ctl):
    svc, ctl = confined_ctl
    sink = RecordingSink()
    ctl.set_echo_sink(sink)
    svc.ghost_pointer_event.emit(("motion", [(1, 101, 103)]))
    ctl._on_idle(1)
    assert sink.calls[-1] == ("fading", 1, gc.FADE_MS)


def test_focus_suppression_mirrors_hidden(confined_ctl):
    svc, ctl = confined_ctl
    sink = RecordingSink()
    ctl.set_echo_sink(sink)
    svc.ghost_pointer_event.emit(("motion", [(1, 101, 103)]))
    ctl.set_focused_window("777")
    assert sink.calls[-1] == ("hidden", 1)


def test_hide_all_mirrors_cleared(confined_ctl):
    svc, ctl = confined_ctl
    sink = RecordingSink()
    ctl.set_echo_sink(sink)
    svc.ghost_pointer_event.emit(("motion", [(1, 101, 103)]))
    svc.ghost_clear.emit()
    assert sink.calls[-1] == ("cleared",)


def test_unconfined_controller_never_mirrors(qapp):
    # offscreen default: unconfined float (already renders over the cards)
    ctl = gc.GhostCursorController(None, None)
    assert ctl._confined is False
    sink = RecordingSink()
    ctl.set_echo_sink(sink)
    ctl._on_pointer_event(("motion", [(0, 101, 103)]))
    ctl._on_idle(0)
    ctl._hide_all()
    assert sink.calls == []
    for ov in ctl._overlays.values():
        ov.deleteLater()


def test_raising_sink_never_breaks_ghosts(confined_ctl):
    svc, ctl = confined_ctl
    ctl.set_echo_sink(RaisingSink())
    svc.ghost_pointer_event.emit(("motion", [(1, 101, 103)]))
    ov = ctl._overlays[1]
    assert ov.isVisible()                    # the glove itself is unaffected
    ctl._on_idle(1)
    ctl._hide_all()                          # none of these may raise


# -- ClusterOverlayController: echo lifecycle + clip geometry -----------------

def test_sink_is_noop_while_framed(qapp):
    ctrl, _provider, _window, _created = _make()
    ctrl.ghost_echo_shown(0, 10, 10, _pm())   # must not create or crash
    ctrl.ghost_echo_fading(0, 150)
    ctrl.ghost_echo_hidden(0)
    ctrl.ghost_echo_cleared()
    assert ctrl._ghost_echo is None


def test_shown_creates_echo_and_converts_to_window_coords(qapp):
    anchor = (1000, 700)
    ctrl, _provider, _window, created = _make(anchor=anchor)
    assert ctrl.enter() is True
    pm = _pm()
    ctrl.ghost_echo_shown(2, 1010, 690, pm)
    echo = ctrl._ghost_echo
    assert echo is not None
    surface = created[0]
    assert echo.parent() is surface
    assert echo.geometry() == surface.rect()
    win = ctrl._compute_window_rect()
    assert echo._slots[2]["pos"] == QPoint(1010 - win.x(), 690 - win.y())
    ctrl.leave()


def test_clip_covers_cards_and_emblem_not_gaps(qapp):
    ctrl, _provider, _window, _created = _make(anchor=(1000, 700))
    assert ctrl.enter() is True
    ctrl.ghost_echo_shown(0, 1000, 700, _pm())
    clip = ctrl._ghost_echo._clip
    assert clip is not None and not clip.isEmpty()
    # Host-local probes mapped through the same transform as the clip:
    # (40, 120) sits inside card 0's painted body, clear of the emblem disc
    # and the concave carve; the emblem center is inside the disc; (200, 75)
    # is the gap between the left and right columns.
    assert clip.contains(QPointF(*_win_pt(40, 120)))
    assert clip.contains(QPointF(*_win_pt(_EMBLEM_CX, _EMBLEM_CY)))
    assert not clip.contains(QPointF(*_win_pt(200, 75)))
    ctrl.leave()


def test_clip_drops_hidden_cells(qapp):
    ctrl, _provider, _window, _created = _make(anchor=(1000, 700))
    assert ctrl.enter() is True
    ctrl.ghost_echo_shown(0, 1000, 700, _pm())
    probe = QPointF(*_win_pt(40, 120))            # inside card 0's body
    assert ctrl._ghost_echo._clip.contains(probe)
    ctrl._visible_cells = {1, 2, 3}               # card 0 dropped
    ctrl._apply_exact_input_shape()               # refreshes the echo clip too
    assert not ctrl._ghost_echo._clip.contains(probe)
    ctrl.leave()


def test_scale_gesture_hides_echo_until_settle(qapp):
    ctrl, _provider, _window, _created = _make(anchor=(1000, 700))
    assert ctrl.enter() is True
    ctrl.ghost_echo_shown(0, 1000, 700, _pm())
    echo = ctrl._ghost_echo
    assert not echo.isHidden()
    ctrl._enter_broad_phase(ctrl._compute_window_rect())
    assert echo.isHidden()                        # clip would lag the tween
    ctrl._settle_input()
    assert not echo.isHidden()
    ctrl.leave()


def test_leave_drops_echo_reference(qapp):
    ctrl, _provider, _window, _created = _make(anchor=(1000, 700))
    assert ctrl.enter() is True
    ctrl.ghost_echo_shown(0, 1000, 700, _pm())
    assert ctrl._ghost_echo is not None
    ctrl.leave()
    assert ctrl._ghost_echo is None


def test_fading_hidden_cleared_delegate_to_layer(qapp):
    ctrl, _provider, _window, _created = _make(anchor=(1000, 700))
    assert ctrl.enter() is True
    ctrl.ghost_echo_shown(0, 1000, 700, _pm())
    ctrl.ghost_echo_shown(1, 1020, 720, _pm())
    ctrl.ghost_echo_hidden(0)
    assert 0 not in ctrl._ghost_echo._slots
    ctrl.ghost_echo_fading(1, 10_000)
    assert ctrl._ghost_echo._slots[1]["fade"] is not None
    ctrl.ghost_echo_cleared()
    assert ctrl._ghost_echo._slots == {}
    ctrl.leave()
