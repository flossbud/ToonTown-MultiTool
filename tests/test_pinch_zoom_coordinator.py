"""PinchZoomCoordinator: the Qt-thin layer between a platform GestureTranslator
and the cluster controller's continuous-gesture API.

The coordinator owns policy the pure machine and the dumb translators must
not: the begin gate (kill switch, float mode, cursor over chrome, drag
interlock), the watchdog timer (a lost gesture-end must never strand the
BROAD input shape), translator arming with the startup stamp (the
running-code proof for live validation), and disarm-on-translator-error.
Pinned here, per spec sections 2.2/2.4/2.6:

- Callback mapping: on_begin gated (a blocked begin leaves the machine IDLE);
  on_end(False) -> machine end() (snap applied); on_end(True) -> machine
  cancel() (no snap); updates keep flowing after the cursor drifts OFF chrome
  (begin-gated, update-flowing).
- Drag interlock: begin refused while a cluster drag runs; a drag STARTING
  while a pinch is ACTIVE force-cancels the pinch through the single
  termination path BEFORE the drag poll starts.
- Watchdog: (re)started on every translator event, expiry terminates with
  cancel semantics (commit current, NO snap). Fired manually - no sleeps.
- Translator exception (start() or mid-callback): disarm - translator
  stopped, "[PinchZoom] disarmed (<error>)" stamped, broad shape released,
  nothing propagates.
- Stamps: disabled/unavailable/armed, exactly one line per arm attempt; the
  armed format is pinned NOW for the Phase 2 translators.
- stop() idempotent; controller leave() tears the coordinator down and a
  re-enter re-arms it (the coordinator outlives float sessions, its
  translator does not).

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
        PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
        ./venv/bin/python -m pytest tests/test_pinch_zoom_coordinator.py -q
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("TTMT_NO_RADIAL_ANIM", "1")
os.environ.setdefault("TTMT_NO_OVERLAY_SCALE_ANIM", "1")

import sys

import pytest

import utils.overlay.pinch_zoom as pinch_zoom
from tests.test_cluster_controller import _SignalEmblem
from tests.test_cluster_scale_gesture import (
    _CHROME_CONTROL_PT, _CHROME_OFF_PT, _global_pt, _make,
)
from utils.overlay.pinch_zoom import (
    PINCH_WATCHDOG_MS,
    PinchState,
    PinchZoomCoordinator,
    TRANSLATOR_REGISTRY,
    platform_bucket,
)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------
class _FakeTranslator:
    """Recording GestureTranslator: the coordinator assigns the three callback
    attributes before start(); start/stop record. ``fail_start`` arms the
    translator-exception-at-start path."""
    mechanism = "fake-mech"

    def __init__(self, fail_start: bool = False):
        self.fail_start = fail_start
        self.started: list = []
        self.stopped: int = 0
        self.on_begin = None
        self.on_update = None
        self.on_end = None

    def start(self, surfaces):
        if self.fail_start:
            raise RuntimeError("boom-start")
        self.started.append(tuple(surfaces))

    def stop(self):
        self.stopped += 1


class _Cursor:
    """Injectable cursor supplier (the QCursor.pos seam): tests move the
    'fingers' by reassigning ``pos``."""

    def __init__(self, pos=None):
        self.pos = pos

    def __call__(self):
        return self.pos


def _stamps(monkeypatch):
    """Capture every coordinator stamp line (the overlay_trace seam)."""
    lines: list = []
    monkeypatch.setattr(pinch_zoom, "overlay_trace", lines.append)
    return lines


def _entered(cursor_pos=None, watchdog_ms=PINCH_WATCHDOG_MS):
    """Real-controller harness: entered cluster + a coordinator installed on
    it (as connect_emblem would), cursor defaulting to a chrome point.
    Returns (ctrl, coord, cursor, created_surfaces)."""
    ctrl, _provider, _window, created = _make()
    assert ctrl.enter() is True
    cursor = _Cursor(cursor_pos if cursor_pos is not None
                     else _global_pt(ctrl, *_CHROME_CONTROL_PT))
    coord = PinchZoomCoordinator(ctrl, cursor_pos=cursor,
                                 watchdog_ms=watchdog_ms, registry={})
    ctrl._pinch_coordinator = coord
    return ctrl, coord, cursor, created


def _idle(coord) -> bool:
    return coord._machine.state is PinchState.IDLE


def _watchdog_running(coord) -> bool:
    return coord._watchdog is not None and coord._watchdog.isActive()


# ---------------------------------------------------------------------------
# Platform bucket (the registry key) - sys.platform PINNED, never inherited
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,bucket", [
    ("darwin", "darwin"),
    ("win32", "win32"),
    ("linux", "linux"),
    ("linux2", "linux"),      # historical spelling collapses to the X11 bucket
])
def test_platform_bucket_pinned(monkeypatch, raw, bucket):
    monkeypatch.setattr(sys, "platform", raw)
    assert platform_bucket() == bucket


# ---------------------------------------------------------------------------
# Callback mapping: begin gate + update flow + end/cancel semantics
# ---------------------------------------------------------------------------
def test_begin_over_chrome_opens_gesture_and_updates_flow(qapp):
    """The happy path: begin over chrome opens machine + controller gesture at
    the rendered base; each on_update drives the controller with the machine's
    clamped live scale (base * abs_factor)."""
    ctrl, coord, cursor, created = _entered()

    coord.on_begin()

    assert coord._machine.active is True
    assert ctrl._gesture_active is True

    coord.on_update(1.5)

    assert ctrl.scale == 1.5                      # base 1.0 * factor 1.5
    assert ctrl._view_scale == 1.5
    coord.on_end(False)
    ctrl.leave()


def test_on_end_normal_maps_to_machine_end_and_snaps(qapp):
    """on_end(False) is the machine's end(): the ONLY terminator that applies
    the wheel path's snap-to-1.0 window."""
    ctrl, coord, cursor, created = _entered()
    coord.on_begin()
    coord.on_update(1.02)                         # inside SNAP_WINDOW of 1.0

    coord.on_end(False)

    assert ctrl.scale == 1.0                      # snapped
    assert _idle(coord)
    assert ctrl._gesture_active is False
    assert not _watchdog_running(coord)
    ctrl.leave()


def test_on_end_cancelled_maps_to_machine_cancel_no_snap(qapp):
    """on_end(True) is the machine's cancel(): commit the current live scale
    with NO snap, even inside the snap window."""
    ctrl, coord, cursor, created = _entered()
    coord.on_begin()
    coord.on_update(1.02)

    coord.on_end(True)

    assert ctrl.scale == pytest.approx(1.02)      # NOT snapped
    assert _idle(coord)
    assert ctrl._gesture_active is False
    assert not _watchdog_running(coord)
    ctrl.leave()


def test_begin_blocked_by_kill_switch_leaves_idle(qapp, monkeypatch):
    ctrl, coord, cursor, created = _entered()
    monkeypatch.setenv("TTMT_NO_PINCH_ZOOM", "1")

    coord.on_begin()

    assert _idle(coord)
    assert ctrl._gesture_active is False
    assert not _watchdog_running(coord)
    ctrl.leave()


def test_begin_blocked_when_controller_framed(qapp):
    """No float mode -> no gesture (the machine stays IDLE, nothing armed)."""
    ctrl, _provider, _window, _created = _make()   # never entered
    coord = PinchZoomCoordinator(ctrl, cursor_pos=_Cursor(_global_pt(ctrl, 0, 0)),
                                 registry={})

    coord.on_begin()

    assert _idle(coord)
    assert ctrl._gesture_active is False
    assert not _watchdog_running(coord)


def test_begin_blocked_off_chrome(qapp):
    """A point inside the window but OFF the exact chrome region blocks the
    begin (the broad capture rect is a gesture artifact, never chrome)."""
    ctrl, coord, cursor, created = _entered()
    cursor.pos = _global_pt(ctrl, *_CHROME_OFF_PT)

    coord.on_begin()

    assert _idle(coord)
    assert ctrl._gesture_active is False
    assert not _watchdog_running(coord)
    ctrl.leave()


def test_updates_flow_after_cursor_drifts_off_chrome(qapp):
    """Begin-gated, update-flowing: once ACTIVE, updates keep driving the
    controller even though the fingers' cursor has left the chrome."""
    ctrl, coord, cursor, created = _entered()
    coord.on_begin()
    cursor.pos = _global_pt(ctrl, *_CHROME_OFF_PT)   # drifted off mid-gesture

    coord.on_update(1.4)

    assert coord._machine.active is True
    assert ctrl.scale == 1.4
    coord.on_end(False)
    ctrl.leave()


def test_stray_update_and_end_while_idle_are_noops(qapp):
    """A translator race after end/force-cancel: update/end with an IDLE
    machine touch nothing (and never start the watchdog)."""
    ctrl, coord, cursor, created = _entered()

    coord.on_update(1.6)
    coord.on_end(False)

    assert ctrl.scale == 1.0
    assert ctrl._gesture_active is False
    assert not _watchdog_running(coord)
    ctrl.leave()


def test_lost_end_rebegin_commits_then_reopens_rebased(qapp):
    """on_begin while ACTIVE (a lost gesture-end): the current live scale is
    committed with cancel semantics through the single termination path, then
    the gesture re-opens with base = the committed scale (machine 2.1
    semantics), so the new factor stream near 1.0 cannot snap the scale back."""
    ctrl, coord, cursor, created = _entered()
    coord.on_begin()
    coord.on_update(1.5)

    coord.on_begin()                              # lost end + new gesture

    assert ctrl.scale == 1.5                      # committed, no snap
    assert coord._machine.active is True
    assert ctrl._gesture_active is True           # re-opened

    coord.on_update(1.1)

    assert ctrl.scale == pytest.approx(1.65)      # rebased at 1.5, not 1.0
    coord.on_end(True)
    ctrl.leave()


# ---------------------------------------------------------------------------
# Drag interlock (spec 2.4)
# ---------------------------------------------------------------------------
def test_begin_refused_while_drag_in_progress(qapp):
    ctrl, coord, cursor, created = _entered()
    ctrl.begin_group_drag()
    assert ctrl.drag_in_progress is True

    coord.on_begin()

    assert _idle(coord)
    assert ctrl._gesture_active is False
    ctrl._end_drag()
    ctrl.leave()


def test_drag_start_force_cancels_active_pinch_first(qapp, monkeypatch):
    """A drag STARTING while a pinch is ACTIVE force-cancels the pinch through
    the single termination path BEFORE the drag poll starts: the termination
    must observe drag_in_progress False (ordering), and the commit is the
    current scale with no snap. The termination's settle also clears
    _scaling_active - without it move_group would stay locked out for the
    whole drag."""
    ctrl, coord, cursor, created = _entered()
    coord.on_begin()
    coord.on_update(1.5)
    assert ctrl._scaling_active is True           # broad held mid-gesture

    order: list = []
    orig_end = ctrl.end_scale_gesture

    def _spy_end(final):
        order.append(("terminate", ctrl.drag_in_progress))
        orig_end(final)

    monkeypatch.setattr(ctrl, "end_scale_gesture", _spy_end)

    ctrl.begin_group_drag()

    assert order == [("terminate", False)]        # cancel BEFORE the drag poll
    assert _idle(coord)
    assert ctrl._gesture_active is False
    assert ctrl._scaling_active is False          # drag's move_group unblocked
    assert not _watchdog_running(coord)
    assert ctrl.scale == 1.5                      # committed current, no snap
    assert ctrl.drag_in_progress is True          # the drag then proceeded
    ctrl._end_drag()
    ctrl.leave()


# ---------------------------------------------------------------------------
# Watchdog (no sleeps: fired via the timeout handler)
# ---------------------------------------------------------------------------
def test_watchdog_started_on_begin_restarted_on_update_stopped_on_end(qapp):
    ctrl, coord, cursor, created = _entered(watchdog_ms=50)
    coord.on_begin()

    assert _watchdog_running(coord)
    assert coord._watchdog.interval() == 50       # injectable interval seam

    coord._watchdog.stop()                        # prove the RE-start
    coord.on_update(1.2)

    assert _watchdog_running(coord)

    coord.on_end(False)

    assert not _watchdog_running(coord)
    ctrl.leave()


def test_watchdog_default_interval_is_the_spec_constant(qapp):
    ctrl, coord, cursor, created = _entered()
    coord.on_begin()

    assert coord._watchdog.interval() == PINCH_WATCHDOG_MS == 1500

    coord.on_end(False)
    ctrl.leave()


def test_watchdog_expiry_terminates_with_cancel_semantics(qapp):
    """Expiry is exactly cancel: commit the current live scale, NO snap (even
    inside the snap window), broad shape released through the single
    termination path."""
    ctrl, coord, cursor, created = _entered()
    coord.on_begin()
    coord.on_update(1.02)                         # snap-window value

    coord._on_watchdog_expired()

    assert ctrl.scale == pytest.approx(1.02)      # NOT snapped
    assert _idle(coord)
    assert ctrl._gesture_active is False
    assert ctrl._scaling_active is False          # broad never stranded
    ctrl.leave()


def test_watchdog_expiry_while_idle_is_a_noop(qapp):
    ctrl, coord, cursor, created = _entered()

    coord._on_watchdog_expired()

    assert ctrl.scale == 1.0
    assert ctrl._gesture_active is False
    ctrl.leave()


# ---------------------------------------------------------------------------
# Arm attempts + stamps (one line per attempt; format pinned for Phase 2)
# ---------------------------------------------------------------------------
def test_kill_switch_stamps_disabled_once_per_attempt(qapp, monkeypatch):
    stamps = _stamps(monkeypatch)
    monkeypatch.setenv("TTMT_NO_PINCH_ZOOM", "1")
    ctrl, _provider, _window, _created = _make()
    coord = PinchZoomCoordinator(ctrl, registry={})

    assert coord.arm() is False
    assert stamps == ["[PinchZoom] disabled (env)"]

    assert coord.arm() is False                   # second ATTEMPT, second line
    assert stamps == ["[PinchZoom] disabled (env)"] * 2
    assert coord.armed is False


@pytest.mark.parametrize("raw,bucket", [
    ("darwin", "darwin"),
    ("win32", "win32"),
    ("linux", "linux"),
])
def test_empty_registry_stamps_unavailable_with_bucket(qapp, monkeypatch,
                                                       raw, bucket):
    """The Phase 1 reality on EVERY platform: the shipped registry is EMPTY,
    so every arm attempt stamps unavailable with the platform bucket."""
    assert TRANSLATOR_REGISTRY == {}              # ships empty in this plan
    stamps = _stamps(monkeypatch)
    monkeypatch.setattr(sys, "platform", raw)     # PINNED, never inherited
    ctrl, _provider, _window, _created = _make()
    coord = PinchZoomCoordinator(ctrl)            # the shipped default registry

    assert coord.arm() is False

    assert stamps == [f"[PinchZoom] unavailable (no translator: {bucket})"]
    assert coord.armed is False


def test_armed_stamp_format_pinned_for_phase2(qapp, monkeypatch):
    """With a registered translator the arm succeeds: callbacks assigned,
    start() gets the watch surfaces, and the stamp carries mechanism + Qt
    version + platform bucket in the pinned format."""
    from PySide6.QtCore import qVersion
    stamps = _stamps(monkeypatch)
    monkeypatch.setattr(pinch_zoom, "platform_bucket", lambda: "testbucket")
    translator = _FakeTranslator()
    ctrl, _provider, _window, _created = _make()
    coord = PinchZoomCoordinator(ctrl, registry={"testbucket": lambda: translator})
    sentinel = object()

    assert coord.arm(surfaces=(sentinel,)) is True

    assert stamps == [f"[PinchZoom] armed (fake-mech) "
                      f"qt={qVersion()} platform=testbucket"]
    assert coord.armed is True
    assert translator.started == [(sentinel,)]
    assert translator.on_begin == coord.on_begin
    assert translator.on_update == coord.on_update
    assert translator.on_end == coord.on_end
    coord.stop()


# ---------------------------------------------------------------------------
# Translator exceptions -> disarm (never crash, never strand the broad shape)
# ---------------------------------------------------------------------------
def test_start_exception_disarms_with_stamp(qapp, monkeypatch):
    stamps = _stamps(monkeypatch)
    monkeypatch.setattr(pinch_zoom, "platform_bucket", lambda: "testbucket")
    translator = _FakeTranslator(fail_start=True)
    ctrl, _provider, _window, _created = _make()
    coord = PinchZoomCoordinator(ctrl, registry={"testbucket": lambda: translator})

    assert coord.arm() is False                   # swallowed, no crash

    assert stamps == ["[PinchZoom] disarmed (boom-start)"]
    assert coord.armed is False
    assert translator.stopped == 1                # stopped despite failed start
    assert not _watchdog_running(coord)


def test_midcallback_exception_disarms_and_releases_broad_shape(qapp,
                                                                monkeypatch):
    """A controller error mid-update (standing in for any translator-path
    exception) disarms: gesture terminated through the single termination
    path (broad shape released), translator stopped, disarm stamped, and the
    exception never propagates into the translator's event pump."""
    ctrl, coord, cursor, created = _entered()
    monkeypatch.setattr(pinch_zoom, "platform_bucket", lambda: "testbucket")
    translator = _FakeTranslator()
    coord._registry = {"testbucket": lambda: translator}
    assert coord.arm() is True
    stamps = _stamps(monkeypatch)

    coord.on_begin()
    assert ctrl._scaling_active is True
    monkeypatch.setattr(ctrl, "update_scale_gesture",
                        lambda scale: (_ for _ in ()).throw(
                            RuntimeError("boom-mid")))

    coord.on_update(1.3)                          # must NOT raise

    assert stamps == ["[PinchZoom] disarmed (boom-mid)"]
    assert coord.armed is False
    assert translator.stopped == 1
    assert _idle(coord)
    assert ctrl._gesture_active is False
    assert ctrl._scaling_active is False          # broad shape released
    assert not _watchdog_running(coord)
    ctrl.leave()


# ---------------------------------------------------------------------------
# stop() + controller teardown wiring
# ---------------------------------------------------------------------------
def test_stop_is_idempotent_and_terminates_a_live_gesture(qapp, monkeypatch):
    ctrl, coord, cursor, created = _entered()
    monkeypatch.setattr(pinch_zoom, "platform_bucket", lambda: "testbucket")
    translator = _FakeTranslator()
    coord._registry = {"testbucket": lambda: translator}
    assert coord.arm() is True
    coord.on_begin()
    coord.on_update(1.3)

    coord.stop()

    assert ctrl.scale == pytest.approx(1.3)       # committed current, no snap
    assert _idle(coord)
    assert ctrl._gesture_active is False
    assert not _watchdog_running(coord)
    assert translator.stopped == 1

    coord.stop()                                  # idempotent

    assert translator.stopped == 1                # not stopped twice
    assert coord.armed is False
    ctrl.leave()


def test_connect_emblem_constructs_the_coordinator_once(qapp):
    """The construction site: connect_emblem builds the coordinator beside the
    resize_scrolled wiring; a same-emblem reconnect and an emblem re-bind keep
    the SAME instance (it holds no emblem state)."""
    ctrl, _provider, _window, _created = _make()
    assert ctrl._pinch_coordinator is None

    emblem = _SignalEmblem()
    ctrl.connect_emblem(emblem)

    coord = ctrl._pinch_coordinator
    assert isinstance(coord, PinchZoomCoordinator)

    ctrl.connect_emblem(emblem)                   # same-emblem no-op
    assert ctrl._pinch_coordinator is coord

    ctrl.connect_emblem(_SignalEmblem())          # re-bind
    assert ctrl._pinch_coordinator is coord


def test_enter_arms_and_leave_tears_down_then_reenter_rearms(qapp, monkeypatch):
    """Lifecycle wiring: enter() arms (translator started, watching the live
    overlay surfaces), leave() tears the coordinator down (translator stopped,
    watchdog stopped, no stray timer, machine IDLE), and the NEXT enter()
    re-arms with a fresh translator - the coordinator outlives float sessions,
    its translator does not."""
    monkeypatch.setattr(pinch_zoom, "platform_bucket", lambda: "testbucket")
    translators: list = []

    def _factory():
        t = _FakeTranslator()
        translators.append(t)
        return t

    monkeypatch.setitem(TRANSLATOR_REGISTRY, "testbucket", _factory)
    ctrl, _provider, _window, created = _make()
    ctrl.connect_emblem(_SignalEmblem())
    coord = ctrl._pinch_coordinator

    assert ctrl.enter() is True

    assert coord.armed is True
    assert len(translators) == 1
    assert created[0] in translators[0].started[0]   # watching the cluster

    # A live pinch at leave() must die with the session (cancel semantics).
    coord._cursor_pos = _Cursor(_global_pt(ctrl, *_CHROME_CONTROL_PT))
    coord.on_begin()
    coord.on_update(1.3)

    ctrl.leave()

    assert coord.armed is False
    assert translators[0].stopped == 1
    assert not _watchdog_running(coord)              # no stray timer
    assert _idle(coord)
    assert ctrl._gesture_active is False

    assert ctrl.enter() is True                      # re-enter re-arms

    assert coord.armed is True
    assert len(translators) == 2                     # a FRESH translator
    assert translators[1].started
    ctrl.leave()
    assert translators[1].stopped == 1
