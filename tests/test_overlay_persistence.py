"""Tests for transparent-mode group persistence (Task 6.1): the pure
anchor-clamp/monitor helpers + the controller save/restore round-trip.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest \
        tests/test_overlay_persistence.py -q
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from utils.overlay.persistence import (
    KEY_ANCHOR, KEY_SCALE, KEY_MONITOR,
    clamp_anchor_to_screens, clamp_anchor_to_envelope, monitor_for_anchor,
    load_overlay_state, save_overlay_state,
)


class _DictSettings:
    def __init__(self, d=None):
        self._d = dict(d or {})

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value):
        self._d[key] = value


# Two side-by-side 1920x1080 monitors: DP-1 at x=0, DP-2 at x=1920.
TWO = [("DP-1", 0, 0, 1919, 1079), ("DP-2", 1920, 0, 3839, 1079)]
ONE = [("DP-1", 0, 0, 1919, 1079)]


# --- pure clamp/monitor helpers -------------------------------------------
def test_clamp_keeps_anchor_on_its_saved_monitor():
    assert clamp_anchor_to_screens((1000, 500), "DP-1", TWO) == (1000, 500)
    assert clamp_anchor_to_screens((2500, 500), "DP-2", TWO) == (2500, 500)


def test_clamp_pulls_off_edge_anchor_into_its_monitor():
    # Saved on DP-2 but drifted left of it -> clamp to DP-2's left edge.
    assert clamp_anchor_to_screens((1000, 500), "DP-2", TWO) == (1920, 500)


def test_clamp_recenters_when_saved_monitor_is_gone():
    # Saved on DP-2 (x>=1920) but only DP-1 remains -> recenter on DP-1.
    out = clamp_anchor_to_screens((2500, 500), "DP-2", ONE)
    assert out == ((0 + 1919) // 2, (0 + 1079) // 2)


def test_clamp_keeps_anchor_that_still_lands_on_some_screen():
    # Saved monitor name unknown, but the anchor is within DP-1 -> keep it.
    assert clamp_anchor_to_screens((500, 500), "GONE", TWO) == (500, 500)


def test_clamp_no_screens_returns_anchor_unchanged():
    assert clamp_anchor_to_screens((10, 20), "DP-1", []) == (10, 20)


def test_monitor_for_anchor():
    assert monitor_for_anchor((500, 500), TWO) == "DP-1"
    assert monitor_for_anchor((2500, 500), TWO) == "DP-2"
    assert monitor_for_anchor((9999, 9999), TWO) == "DP-1"  # off-screen -> first
    assert monitor_for_anchor((0, 0), []) is None


# --- parking envelope clamp (off-screen drag) ------------------------------
def test_envelope_keeps_interior_anchor():
    assert clamp_anchor_to_envelope((1000, 500), TWO, 50) == (1000, 500)


def test_envelope_keeps_anchor_within_the_margin_band():
    # 30px below DP-1's bottom edge (1079); margin 50 -> still inside inflated rect.
    assert clamp_anchor_to_envelope((1000, 1109), TWO, 50) == (1000, 1109)


def test_envelope_clamps_past_bottom_to_edge_plus_margin():
    # Far below the bottom -> y clamped to 1079 + 50; x within band, unchanged.
    assert clamp_anchor_to_envelope((1000, 1600), TWO, 50) == (1000, 1129)


def test_envelope_clamps_past_corner_on_both_axes():
    # Far past DP-1's top-left -> clamp both axes to (0-50, 0-50).
    assert clamp_anchor_to_envelope((-500, -500), TWO, 50) == (-50, -50)


def test_envelope_seam_between_adjacent_monitors_is_interior():
    # x=1920 is DP-2's left edge and within DP-1's inflated right (1919+50) -> kept.
    assert clamp_anchor_to_envelope((1920, 500), TWO, 50) == (1920, 500)


def test_envelope_snaps_far_off_to_nearest_monitor():
    # Far right of DP-2 -> x clamped to 3839 + 50; nearest candidate wins.
    assert clamp_anchor_to_envelope((9000, 500), TWO, 50) == (3889, 500)


def test_envelope_no_screens_returns_anchor_unchanged():
    assert clamp_anchor_to_envelope((10, 20), [], 50) == (10, 20)


def test_envelope_margin_scales_the_reach():
    assert clamp_anchor_to_envelope((1000, 1200), TWO, 50) == (1000, 1129)
    assert clamp_anchor_to_envelope((1000, 1200), TWO, 200) == (1000, 1200)


# --- settings load/save ----------------------------------------------------
def test_load_defaults_when_empty():
    anchor, scale, monitor = load_overlay_state(_DictSettings())
    assert anchor is None and scale == 1.0 and monitor is None


def test_save_then_load_round_trips():
    s = _DictSettings()
    save_overlay_state(s, (1234, 567), 1.5, "DP-2")
    assert s.get(KEY_ANCHOR) == [1234, 567]
    assert s.get(KEY_SCALE) == 1.5
    assert s.get(KEY_MONITOR) == "DP-2"
    anchor, scale, monitor = load_overlay_state(s)
    assert anchor == (1234, 567) and scale == 1.5 and monitor == "DP-2"


def test_load_clamps_out_of_range_scale():
    s = _DictSettings({KEY_SCALE: 9.0})
    _a, scale, _m = load_overlay_state(s)
    assert scale == 1.75  # clamped to SCALE_MAX


def test_load_ignores_malformed_anchor():
    s = _DictSettings({KEY_ANCHOR: "not-a-pair"})
    anchor, _s, _m = load_overlay_state(s)
    assert anchor is None


# --- controller round-trip (with stub settings) ---------------------------
def _ctl(settings):
    from utils.overlay.backend import NoOpOverlayBackend
    from utils.overlay.group_controller import OverlayGroupController

    class _Win:
        def showMinimized(self):
            pass

        def showNormal(self):
            pass

    return OverlayGroupController(_Win(), backend=NoOpOverlayBackend(), settings=settings)


def test_controller_saves_anchor_and_scale_on_move_and_scale(qapp):
    s = _DictSettings()
    ctl = _ctl(s)
    ctl._active = True            # bypass enter() (no surfaces needed for the save path)
    ctl.set_scale_by_notches(-2)  # changes scale -> schedules a save
    ctl.move_group(40, 25)        # changes anchor -> schedules a save
    ctl.flush_pending_save()      # write synchronously

    assert s.get(KEY_SCALE) == ctl._scale
    assert s.get(KEY_ANCHOR) == [ctl._anchor[0], ctl._anchor[1]]
    assert s.get(KEY_MONITOR) is not None  # the (offscreen) screen the anchor sits on


def test_move_group_clamps_anchor_to_parking_envelope(qapp):
    from PySide6.QtGui import QGuiApplication
    from utils.overlay.card_metrics import CardMetrics
    s = _DictSettings()
    ctl = _ctl(s)
    ctl._active = True
    g = QGuiApplication.primaryScreen().geometry()
    ctl._anchor = (g.center().x(), g.bottom())
    ctl.move_group(0, 100000)  # slam far past the bottom edge
    margin = int(CardMetrics(ctl._scale).emblem // 4)
    assert ctl._anchor[1] == g.bottom() + margin   # clamped to edge + margin
    assert ctl._anchor[0] == g.center().x()        # x within band -> unchanged
    # the mirror onto states uses the CLAMPED value
    if ctl._states:
        assert all(st.anchor == ctl._anchor for st in ctl._states)


def test_move_group_keeps_cluster_rigid_when_clamped(qapp):
    # Relative offsets between every surface rect must be identical before and
    # after a clamped move: the cluster shifts as a UNIT, never compresses. Guards
    # against ever reintroducing per-window positioning/clamping.
    from PySide6.QtGui import QGuiApplication
    s = _DictSettings()
    ctl = _ctl(s)
    ctl._active = True
    g = QGuiApplication.primaryScreen().geometry()
    ctl._anchor = (g.center().x(), g.center().y())
    before = ctl._compute_rects()
    em0 = before["emblem"]
    rel_before = {k: (before[k].x() - em0.x(), before[k].y() - em0.y())
                  for k in (0, 1, 2, 3)}
    ctl.move_group(0, 100000)  # past the bottom edge -> anchor clamped
    after = ctl._compute_rects()
    em1 = after["emblem"]
    rel_after = {k: (after[k].x() - em1.x(), after[k].y() - em1.y())
                 for k in (0, 1, 2, 3)}
    assert rel_after == rel_before, "cluster must shift as a unit, never compress"
    assert em1.y() < g.center().y() + 100000, "the move must actually be clamped"


def test_controller_restores_persisted_scale_and_clamped_anchor(qapp):
    # Pre-seed a saved state on the current (offscreen) monitor.
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    name = screen.name()
    g = screen.geometry()
    inside = (g.left() + 10, g.top() + 10)
    s = _DictSettings({KEY_ANCHOR: list(inside), KEY_SCALE: 1.5, KEY_MONITOR: name})

    ctl = _ctl(s)
    ctl._load_persisted_state()
    assert ctl._scale == 1.5
    assert ctl._anchor == inside  # on a visible monitor -> kept


def test_controller_recenters_when_saved_monitor_gone(qapp):
    s = _DictSettings({
        KEY_ANCHOR: [999999, 999999],  # far off any real/offscreen screen
        KEY_SCALE: 0.75,
        KEY_MONITOR: "NONEXISTENT-DISPLAY",
    })
    ctl = _ctl(s)
    ctl._load_persisted_state()
    assert ctl._scale == 0.75
    # Recentered onto a currently-visible screen (not the bogus saved coords).
    assert ctl._anchor != (999999, 999999)


class _StubSurface:
    def prepare_initial_state(self): pass
    def set_overlay_geometry(self, rect): pass
    def show(self): pass
    def hide(self): pass
    def apply_shape(self, path, dpr): pass
    def raise_(self): pass
    def release(self): return None
    def close(self): pass
    def deleteLater(self): pass
    def devicePixelRatio(self): return 1.0


def _stub_factory(state):
    return _StubSurface()


def test_enter_keeps_a_loaded_origin_anchor(qapp):
    """A saved anchor of (0,0) is a VALID origin point - enter() must NOT mistake
    it for the no-QApplication sentinel and overwrite it with the default anchor.
    """
    from PySide6.QtGui import QGuiApplication
    from utils.overlay.backend import NoOpOverlayBackend
    from utils.overlay.group_controller import OverlayGroupController

    class _Win:
        def showMinimized(self): pass
        def showNormal(self): pass

    name = QGuiApplication.primaryScreen().name()
    s = _DictSettings({KEY_ANCHOR: [0, 0], KEY_SCALE: 1.0, KEY_MONITOR: name})
    ctl = OverlayGroupController(
        _Win(), backend=NoOpOverlayBackend(), surface_factory=_stub_factory, settings=s
    )
    # The clamp keeps (0,0) iff the (offscreen) screen includes the origin.
    expected = clamp_anchor_to_screens((0, 0), name, ctl._screens())
    assert ctl.enter() is True
    assert ctl._anchor == expected, "a loaded anchor must survive enter()"
    ctl.leave()
