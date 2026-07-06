"""Continuous scale gesture (trackpad pinch) on ClusterOverlayController.

The pinch path drives the cluster scale 1:1 with the fingers through three
controller methods (begin/update/end_scale_gesture) beside the untouched
wheel-notch path. Pinned here:

- begin adopts the RENDERED scale (``_view_scale`` after the tween stop) as
  the gesture base - never ``self.scale``, which mid-tween is the tween
  TARGET - enters the broad input phase, and HOLDS it (settle timer stopped).
- update drives the whole-cluster transform directly (no tween), repositions
  the radial/panel top-levels, and never saves or touches the input shape.
- end is the ONE termination path: commit the final scale, settle (exact
  shape + view sync), schedule exactly one debounced save; idempotent.
- Single-writer rule: wheel notches are DROPPED while a gesture is live.
- Force-cancel sites: leave() and the topology settle re-clamp terminate a
  live gesture through the same path (committing the gesture's scale) before
  their own work - the broad shape is never stranded.
- cursor_over_chrome (the gesture-begin gate) is PURE geometry: it answers
  from the LAST-applied EXACT input region in global coords (the broad-phase
  capture rect is never chrome), plus the radial/panel windows while OPEN;
  always False when framed, no app-active test (the overlay is
  nonactivating).

Spec: docs/superpowers/specs/2026-07-05-trackpad-pinch-zoom-design.md
(sections 2.3-2.5).

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
        PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
        ./venv/bin/python -m pytest tests/test_cluster_scale_gesture.py -q
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("TTMT_NO_RADIAL_ANIM", "1")
# Deterministic by default: notches snap the rendered scale synchronously.
# The mid-flight-tween test re-enables the animation via monkeypatch.
os.environ.setdefault("TTMT_NO_OVERLAY_SCALE_ANIM", "1")

from PySide6.QtCore import QAbstractAnimation, QPoint
from PySide6.QtWidgets import QApplication, QWidget

from tests.test_cluster_controller import (   # reuse the recording-stub harness
    _DictSettings, _PIVOT, _RecordingBackend, _StubProvider, _StubSurface,
    _StubWindow, _patch_panel, _patch_radial,
)
from utils.overlay.backend import NoOpOverlayBackend
from utils.overlay.cluster_controller import ClusterOverlayController
from utils.overlay.persistence import KEY_SCALE


class _ScaleRecordingSurface(_StubSurface):
    """_StubSurface that ALSO records every direct whole-cluster transform
    write (``set_cluster_scale``), so the tests can assert the gesture drives
    the transform per update frame (and that the wheel tween path found the
    seam in the mid-flight-anim test)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cluster_scales: list = []

    def set_cluster_scale(self, value):
        self.cluster_scales.append(float(value))


def _make(settings=None, backend=None):
    """Build a controller wired to the scale-recording surface stub. Returns
    (controller, provider, window, created_surfaces)."""
    provider = _StubProvider()
    window = _StubWindow()
    created: list = []

    def factory():
        s = _ScaleRecordingSurface()
        created.append(s)
        return s

    ctrl = ClusterOverlayController(
        window,
        backend=backend if backend is not None else NoOpOverlayBackend(),
        settings=settings,
        surface_factory=factory,
        card_provider=provider,
    )
    return ctrl, provider, window, created


def _settle_timer_inactive(ctrl) -> bool:
    """The broad shape is HELD: the notch path's settle timer must not be
    pending (either never built or explicitly stopped)."""
    return ctrl._settle_timer is None or not ctrl._settle_timer.isActive()


# ---------------------------------------------------------------------------
# begin_scale_gesture
# ---------------------------------------------------------------------------
def test_begin_stops_midflight_anim_and_returns_rendered_base(qapp, monkeypatch):
    """A wheel tween is mid-flight (animation enabled, no event loop turns, so
    the rendered scale lags the notch target). begin must STOP the tween and
    return the last RENDERED frame - never the tween target ``self.scale``."""
    monkeypatch.setenv("TTMT_NO_OVERLAY_SCALE_ANIM", "0")   # tween path live
    ctrl, provider, window, created = _make()
    assert ctrl.enter() is True

    ctrl.set_scale_by_notches(3)                 # target 1.24, tween running
    anim = ctrl._scale_anim
    assert anim is not None
    assert anim.state() == QAbstractAnimation.State.Running
    rendered = ctrl._view_scale
    assert rendered != ctrl.scale                # genuinely mid-tween

    base = ctrl.begin_scale_gesture()

    assert base == rendered                      # rendered frame, NOT the target
    assert anim.state() != QAbstractAnimation.State.Running
    assert ctrl._gesture_active is True
    assert ctrl._scaling_active is True          # broad phase entered (drag locked)
    assert _settle_timer_inactive(ctrl)          # broad HELD: no settle re-arm
    ctrl.leave()


def test_begin_base_is_rendered_frame_when_driven_directly(qapp):
    """Direct-drive variant: with the rendered scale detached from the target
    (as mid-tween), begin returns the rendered snapshot."""
    ctrl, provider, window, created = _make()
    assert ctrl.enter() is True
    ctrl.scale = 1.4            # authoritative target (as if a tween target)
    ctrl._view_scale = 1.12     # last rendered frame

    base = ctrl.begin_scale_gesture()

    assert base == 1.12
    assert ctrl._gesture_active is True
    assert ctrl._scaling_active is True
    assert _settle_timer_inactive(ctrl)
    ctrl.leave()


def test_begin_refused_when_inactive(qapp):
    """Framed controller: begin refuses (None) and arms nothing."""
    ctrl, provider, window, created = _make()

    assert ctrl.begin_scale_gesture() is None

    assert ctrl._gesture_active is False
    assert ctrl._scaling_active is False


def test_begin_refused_while_gesture_already_active(qapp):
    """A second begin while a gesture is live refuses (None) and leaves the
    running gesture untouched."""
    ctrl, provider, window, created = _make()
    assert ctrl.enter() is True
    first = ctrl.begin_scale_gesture()
    assert isinstance(first, float)

    assert ctrl.begin_scale_gesture() is None

    assert ctrl._gesture_active is True          # the live gesture survived
    ctrl.leave()


# ---------------------------------------------------------------------------
# update_scale_gesture
# ---------------------------------------------------------------------------
def test_update_drives_transform_directly_and_repositions(qapp, monkeypatch):
    """One gesture frame: authoritative + rendered scale both track the finger
    value, the surface transform is driven DIRECTLY (no tween), the radial +
    panel reposition exactly as the notch path does - and NOTHING else runs:
    no save scheduled, no input-shape work past begin's broad apply, no
    settle re-arm."""
    backend = _RecordingBackend()
    ctrl, provider, window, created = _make(backend=backend)
    assert ctrl.enter() is True
    surface = created[0]
    assert ctrl.begin_scale_gesture() is not None
    shapes_after_begin = len(backend.shapes)     # broad apply already recorded
    setter_calls_after_begin = len(surface.cluster_scales)

    radial_calls: list = []
    panel_calls: list = []
    save_calls: list = []
    monkeypatch.setattr(ctrl, "_reposition_radial",
                        lambda: radial_calls.append(1))
    monkeypatch.setattr(ctrl, "_reposition_panel",
                        lambda: panel_calls.append(1))
    monkeypatch.setattr(ctrl, "_schedule_save",
                        lambda: save_calls.append(1))

    ctrl.update_scale_gesture(1.5)

    assert ctrl.scale == 1.5                     # authoritative
    assert ctrl._view_scale == 1.5               # rendered, in lockstep
    assert surface.cluster_scales[-1] == 1.5     # transform driven directly
    assert len(surface.cluster_scales) == setter_calls_after_begin + 1
    assert radial_calls == [1]
    assert panel_calls == [1]
    assert save_calls == []                      # no persistence mid-gesture
    assert len(backend.shapes) == shapes_after_begin   # input shape untouched
    assert _settle_timer_inactive(ctrl)          # broad still HELD
    ctrl.leave()


def test_update_noops_without_a_live_gesture(qapp):
    """A stray update (translator race after end/force-cancel) is a no-op."""
    ctrl, provider, window, created = _make()
    assert ctrl.enter() is True
    surface = created[0]
    calls_before = len(surface.cluster_scales)

    ctrl.update_scale_gesture(1.7)

    assert ctrl.scale == 1.0
    assert ctrl._view_scale == 1.0
    assert len(surface.cluster_scales) == calls_before
    ctrl.leave()


# ---------------------------------------------------------------------------
# end_scale_gesture (the single termination path)
# ---------------------------------------------------------------------------
def test_end_settles_exact_shape_and_saves_once_idempotent(qapp, monkeypatch):
    """end commits the final scale, clears the gesture, settles (exact shape,
    rendered scale synced, scaling cleared), and schedules exactly ONE save.
    A second end is a no-op."""
    backend = _RecordingBackend()
    settings = _DictSettings()
    ctrl, provider, window, created = _make(settings=settings, backend=backend)
    assert ctrl.enter() is True
    backend.shapes.clear()                       # drop the enter-time exact shape

    save_calls: list = []
    orig_schedule = ctrl._schedule_save

    def _spy_schedule():
        save_calls.append(1)
        orig_schedule()

    monkeypatch.setattr(ctrl, "_schedule_save", _spy_schedule)

    assert ctrl.begin_scale_gesture() is not None
    assert len(backend.shapes) == 1              # the broad apply
    ctrl.update_scale_gesture(1.4)

    ctrl.end_scale_gesture(1.44)

    assert ctrl.scale == 1.44
    assert ctrl._view_scale == 1.44              # _settle_input synced the render
    assert ctrl._gesture_active is False
    assert ctrl._scaling_active is False
    assert ctrl._input_phase == "exact"          # exact-shape path hit
    assert len(backend.shapes) == 2              # broad (begin), exact (end)
    exact_path = backend.shapes[-1][1]
    broad_path = backend.shapes[0][1]
    assert (exact_path.boundingRect().toRect()
            != broad_path.boundingRect().toRect())
    assert save_calls == [1]                     # exactly one save scheduled
    assert ctrl._save_pending is True            # debounced, not yet written

    ctrl.end_scale_gesture(1.44)                 # idempotent second end

    assert save_calls == [1]                     # still exactly one
    assert len(backend.shapes) == 2              # no extra shape work
    ctrl.leave()


# ---------------------------------------------------------------------------
# Single-writer lockout (wheel notches dropped mid-gesture)
# ---------------------------------------------------------------------------
def test_wheel_notches_dropped_while_gesture_active(qapp):
    """set_scale_by_notches during a live gesture leaves the scale untouched
    (dropped, not queued) and schedules nothing."""
    ctrl, provider, window, created = _make(settings=_DictSettings())
    assert ctrl.enter() is True
    assert ctrl.begin_scale_gesture() is not None
    ctrl.update_scale_gesture(1.3)

    ctrl.set_scale_by_notches(5)

    assert ctrl.scale == 1.3                     # untouched
    assert ctrl._view_scale == 1.3
    assert ctrl._save_pending is False           # notch never scheduled a save
    assert _settle_timer_inactive(ctrl)          # broad still HELD (no re-arm)
    ctrl.end_scale_gesture(1.3)
    ctrl.leave()


# ---------------------------------------------------------------------------
# Force-cancel: leave() mid-gesture
# ---------------------------------------------------------------------------
def test_leave_mid_gesture_terminates_and_flushes_gesture_scale(qapp):
    """leave() with a live gesture force-cancels through the termination path
    FIRST, so the leave-time save flush persists the gesture's scale (not the
    framed 1.0 reset, not a stale pre-gesture value) and the broad shape is
    never stranded."""
    settings = _DictSettings()
    ctrl, provider, window, created = _make(settings=settings)
    assert ctrl.enter() is True
    assert ctrl.begin_scale_gesture() is not None
    ctrl.update_scale_gesture(1.6)

    ctrl.leave()                                 # must not raise

    assert ctrl.is_active is False
    assert ctrl._gesture_active is False
    assert ctrl._scaling_active is False         # broad never stranded
    assert settings.get(KEY_SCALE) == 1.6        # the flush saw the gesture scale


# ---------------------------------------------------------------------------
# Force-cancel: topology settle re-clamp mid-gesture (topology wins)
# ---------------------------------------------------------------------------
def test_topology_settle_mid_gesture_force_cancels_before_reclamp(qapp, monkeypatch):
    """The topology settle callback force-cancels a live gesture BEFORE any
    re-clamp work (spec 2.5: topology wins) - it must NOT defer the way it
    does for a wheel-notch gesture - and the re-clamp then proceeds."""
    ctrl, provider, window, created = _make(settings=_DictSettings())
    assert ctrl.enter() is True
    assert ctrl.begin_scale_gesture() is not None
    ctrl.update_scale_gesture(1.3)
    ctrl._anchor = (99999, 99999)                # stranded (off every screen)

    # Record the gesture flag when the re-clamp work starts (its first step is
    # the screen-list read): termination must already have run.
    orig_screens = ctrl._screens
    gesture_flag_at_reclamp: list = []

    def _spy_screens():
        gesture_flag_at_reclamp.append(ctrl._gesture_active)
        return orig_screens()

    monkeypatch.setattr(ctrl, "_screens", _spy_screens)

    assert ctrl._revalidate_anchor_for_screens() is True   # re-clamped, not deferred

    assert gesture_flag_at_reclamp[0] is False   # terminated BEFORE re-clamp work
    assert ctrl._gesture_active is False
    assert ctrl._scaling_active is False
    assert ctrl.scale == 1.3                     # committed current, no snap
    assert ctrl._view_scale == 1.3
    name, l, t, r, b = orig_screens()[0]
    assert ctrl._anchor == ((l + r) // 2, (t + b) // 2)    # recentered
    ctrl.leave()


# ---------------------------------------------------------------------------
# cursor_over_chrome (the gesture-begin gate)
# ---------------------------------------------------------------------------
# WINDOW-LOCAL probes, derived from the stub cluster (_PIVOT is the emblem
# center at every scale; the exact union is the emblem + visible controls):
# inside cell 1's first control at scale 1.0 (host (220, 20)), off the emblem.
_CHROME_CONTROL_PT = (_PIVOT[0] + 110, _PIVOT[1] - 70)
# Host (170, 90): off every control and PAST the emblem's scale-1.0 edge
# (pivot+50), but INSIDE the emblem once the exact shape re-applies at 1.5
# (pivot+75) - distinguishes the stored LAST region from a live recompute.
_CHROME_EMBLEM_15_PT = (_PIVOT[0] + 60, _PIVOT[1])
# Window corner: inside the BROAD (full-window) capture rect, outside every
# exact rect at any tested scale.
_CHROME_OFF_PT = (1, 1)


def _global_pt(ctrl, wx, wy):
    """WINDOW-local (x, y) -> GLOBAL QPoint through the model window rect (the
    same envelope+anchor math the predicate must map queries through)."""
    win = ctrl._compute_window_rect()
    return QPoint(win.x() + int(wx), win.y() + int(wy))


def test_over_chrome_answers_exact_region_in_global_coords(qapp):
    """After enter() the predicate answers from the enter-time EXACT region
    (emblem + visible-card controls) in GLOBAL coordinates - and from pure
    geometry: nothing here is shown/activated (the real overlay is
    nonactivating by design), so an app-active gate would answer False."""
    ctrl, provider, window, created = _make()
    assert ctrl.enter() is True
    # Pure-geometry precondition: the cluster window is never the app-active
    # window here (the stub is never really shown), so any activeWindow-style
    # gate inside the predicate would answer False below.
    assert QApplication.activeWindow() is not created[0]

    assert ctrl.cursor_over_chrome(_global_pt(ctrl, *_CHROME_CONTROL_PT)) is True
    assert ctrl.cursor_over_chrome(_global_pt(ctrl, *_PIVOT)) is True   # emblem
    assert ctrl.cursor_over_chrome(_global_pt(ctrl, *_CHROME_OFF_PT)) is False
    ctrl.leave()


def test_over_chrome_broad_phase_answers_from_last_exact_region(qapp):
    """Mid-gesture (BROAD full-window capture shape HELD) the predicate still
    answers from the LAST EXACT region: a point inside the broad rect but off
    the real controls is NOT chrome (no broad-rect false positives), while
    the last exact region keeps answering truthfully. The single termination
    path then refreshes the stored region at the final scale."""
    ctrl, provider, window, created = _make()
    assert ctrl.enter() is True
    assert ctrl.begin_scale_gesture() is not None   # broad applied + HELD
    ctrl.update_scale_gesture(1.5)

    assert ctrl.cursor_over_chrome(_global_pt(ctrl, *_CHROME_OFF_PT)) is False
    assert ctrl.cursor_over_chrome(_global_pt(ctrl, *_CHROME_CONTROL_PT)) is True
    # Chrome only once the exact shape re-applies at 1.5 - never mid-gesture.
    assert ctrl.cursor_over_chrome(
        _global_pt(ctrl, *_CHROME_EMBLEM_15_PT)) is False

    ctrl.end_scale_gesture(1.5)                     # settle re-stores at 1.5

    assert ctrl.cursor_over_chrome(
        _global_pt(ctrl, *_CHROME_EMBLEM_15_PT)) is True
    assert ctrl.cursor_over_chrome(_global_pt(ctrl, *_CHROME_CONTROL_PT)) is False
    assert ctrl.cursor_over_chrome(_global_pt(ctrl, *_CHROME_OFF_PT)) is False
    ctrl.leave()


def test_over_chrome_follows_a_window_move_without_reapply(qapp):
    """The stored region is window-LOCAL: after a drag (which never re-applies
    the exact shape) the predicate follows the window - the same window-local
    probe stays True at its NEW screen position and the OLD screen point goes
    False."""
    ctrl, provider, window, created = _make()
    assert ctrl.enter() is True
    before = _global_pt(ctrl, *_CHROME_CONTROL_PT)
    assert ctrl.cursor_over_chrome(before) is True

    assert ctrl.move_group(40, 30) is True

    assert ctrl.cursor_over_chrome(_global_pt(ctrl, *_CHROME_CONTROL_PT)) is True
    assert ctrl.cursor_over_chrome(before) is False
    ctrl.leave()


def test_over_chrome_radial_geometry_only_while_open(qapp, monkeypatch):
    """The radial window's geometry is chrome ONLY while the ring is OPEN: the
    persistent top-level stays MAPPED while closed (empty + click-through),
    so its invisible canvas must never gate a pinch in before/after."""
    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make()
    assert ctrl.enter() is True
    rsurf = created_radial["surfaces"][0]        # pre-mapped at enter

    def _corner():
        return rsurf.geometry().topLeft() + QPoint(3, 3)

    assert ctrl.cursor_over_chrome(_corner()) is False   # closed: not chrome
    assert ctrl.open_radial_menu() is not None
    assert ctrl.cursor_over_chrome(_corner()) is True
    outside = rsurf.geometry().topLeft() - QPoint(2, 2)
    assert ctrl.cursor_over_chrome(outside) is False     # just past the canvas
    ctrl.close_radial_menu()
    assert ctrl.cursor_over_chrome(_corner()) is False
    ctrl.leave()


def test_over_chrome_panel_geometry_only_while_open(qapp, monkeypatch):
    """Same open-marker rule for the portable Settings panel: its persistent
    top-level's geometry counts as chrome only between open and close."""
    created_panel = _patch_panel(monkeypatch)
    ctrl, provider, window, created = _make()
    assert ctrl.enter() is True
    psurf = created_panel["surfaces"][0]         # pre-mapped at enter

    def _corner():
        return psurf.geometry().topLeft() + QPoint(3, 3)

    assert ctrl.cursor_over_chrome(_corner()) is False   # closed: not chrome
    assert ctrl.open_panel_surface(QWidget()) is psurf
    assert ctrl.cursor_over_chrome(_corner()) is True
    ctrl.close_panel_surface()
    assert ctrl.cursor_over_chrome(_corner()) is False
    ctrl.leave()


def test_over_chrome_false_when_framed(qapp):
    """Framed (never entered, and again after leave()): False everywhere -
    even on a point that IS chrome while floating - and the stored region
    dies with the envelope state."""
    ctrl, provider, window, created = _make()
    probe = _global_pt(ctrl, *_PIVOT)    # model rect is recomputable pre-enter

    assert ctrl.cursor_over_chrome(probe) is False

    assert ctrl.enter() is True
    assert ctrl.cursor_over_chrome(probe) is True
    ctrl.leave()

    assert ctrl.cursor_over_chrome(probe) is False
    assert ctrl._exact_input_region is None      # cleared with the envelope
