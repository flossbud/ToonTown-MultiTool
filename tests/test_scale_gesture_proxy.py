"""Unit tests for ScaleProxyWindow.

The proxy's rendering and override-redirect stacking are LIVE-only (the
offscreen Qt platform cannot composite translucent surfaces or honor
override-redirect z-order), so these tests assert only the pure, observable
contract: snapshot/scale storage, ``set_scale`` updating the live scale, the
wheel-notch forwarding, and the window flags/attributes.
"""

from PySide6.QtCore import Qt, QRect, QPoint, QPointF, QObject, Signal
from PySide6.QtGui import QImage, QWheelEvent

from utils.overlay.scale_gesture_proxy import ScaleGestureProxy, ScaleProxyWindow
from utils.overlay.scale import step_scale


def _img(w, h):
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(0xFF112233)
    return img


def _make(base_scale=1.0):
    snapshot = _img(40, 30)
    bbox = QRect(100, 50, 40, 30)
    anchor = QPoint(120, 65)
    return ScaleProxyWindow(snapshot, bbox, anchor, base_scale)


def _wheel(dy):
    return QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, dy),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
    )


def test_stores_snapshot_and_base_scale(qapp):
    snap = _img(40, 30)
    pw = ScaleProxyWindow(snap, QRect(100, 50, 40, 30), QPoint(120, 65), 0.8)
    assert pw._snapshot is snap
    assert pw._base_scale == 0.8
    assert pw._scale == 0.8


def test_set_scale_updates_live_scale_and_requests_repaint(qapp, monkeypatch):
    pw = _make(base_scale=1.0)
    assert pw._scale == 1.0
    updated = []
    monkeypatch.setattr(pw, "update", lambda *a, **k: updated.append(1))
    pw.set_scale(1.4)
    assert pw._scale == 1.4
    assert updated == [1]            # set_scale must request a repaint


def test_wheel_event_emits_one_notch_per_event(qapp):
    # Sign-based, matching the emblem (_compact_layout _Emblem.wheelEvent): one
    # notch per wheel event regardless of magnitude, so trackpad/high-res deltas
    # are not floor-divided away and the sign is consistent both directions.
    pw = _make()
    got = []
    pw.wheel_notch.connect(got.append)
    pw.wheelEvent(_wheel(120))
    pw.wheelEvent(_wheel(-240))      # magnitude ignored -> still one notch
    pw.wheelEvent(_wheel(40))        # small (trackpad) positive -> +1, not 0
    pw.wheelEvent(_wheel(0))         # no movement -> no emit
    assert got == [1, -1, 1]


def test_non_wheel_pointer_events_are_swallowed(qapp):
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    pw = _make()
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    pw.mousePressEvent(ev)
    assert ev.isAccepted()           # consumed, not passed through


def test_window_flags_and_attributes(qapp):
    pw = _make()
    flags = pw.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
    assert flags & Qt.WindowDoesNotAcceptFocus
    assert flags & Qt.X11BypassWindowManagerHint
    assert pw.testAttribute(Qt.WA_TranslucentBackground)
    assert pw.testAttribute(Qt.WA_ShowWithoutActivating)
    assert pw.testAttribute(Qt.WA_DeleteOnClose) is False


# --------------------------------------------------------------------------- #
# ScaleGestureProxy coordinator (state machine)                               #
# --------------------------------------------------------------------------- #

class _FakeProxy(QObject):
    """Stand-in for ScaleProxyWindow exposing only the coordinator's contract."""

    wheel_notch = Signal(int)

    def __init__(self):
        super().__init__()
        self.scales = []
        self.shown = False
        self.hidden = False
        self.deleted = False

    def set_scale(self, value):
        self.scales.append(float(value))

    def show(self):
        self.shown = True

    def hide(self):
        self.hidden = True

    def deleteLater(self):
        self.deleted = True


class _FakeHost:
    """Injected adapter that records the coordinator's calls in order."""

    def __init__(self, scale=1.0):
        self._scale = float(scale)
        self.events = []
        self.proxy = None
        self.made = []

    @property
    def scale(self):
        return self._scale

    @scale.setter
    def scale(self, value):
        self._scale = float(value)

    def snapshot(self):
        self.events.append("snapshot")
        return (
            _img(40, 30),
            QRect(100, 50, 40, 30),
            QPoint(120, 65),
            [QRect(0, 0, 5, 5)],
            1.0,
        )

    def make_proxy(self, snapshot, bbox, anchor, base_scale, wheel_rects):
        self.events.append("make_proxy")
        self.made.append((snapshot, bbox, anchor, base_scale, wheel_rects))
        self.proxy = _FakeProxy()
        # make_proxy is responsible for SHOWING the proxy synchronously, so the
        # snapshot is mapped before the queued hide takes the real windows down.
        self.proxy.show()
        return self.proxy

    def park_scaling_windows(self):
        self.events.append("park_scaling_windows")

    def unpark_scaling_windows(self):
        self.events.append("unpark_scaling_windows")

    def repaint_scaling_windows(self):
        self.events.append("repaint_scaling_windows")

    def capture_full_input(self, proxy):
        self.events.append("capture_full_input")

    def reassert_after_settle(self):
        self.events.append("reassert_after_settle")

    def settle_placement(self, reassert=True):
        self.events.append(("settle_placement", reassert))

    def on_gesture_end(self):
        self.events.append("on_gesture_end")


def test_begin_snapshots_makes_proxy_at_start_and_arms(qapp):
    host = _FakeHost(scale=1.0)
    coord = ScaleGestureProxy(host)
    coord.begin(1)

    assert coord.active is True
    assert "snapshot" in host.events
    # The proxy is built at the START scale, not the (stepped) target.
    assert host.made[0][3] == 1.0
    assert coord._proxy is host.proxy
    # target accumulates the one notch off the live scale.
    assert coord.target == step_scale(1.0, 1)


def test_target_accumulates_from_target_not_host(qapp):
    # The key correctness property: begin(1) then notch(1) is TWO discrete
    # step_scale applications, accumulated off the coordinator's own target,
    # never off the animated host scale.
    host = _FakeHost(scale=1.0)
    coord = ScaleGestureProxy(host)
    coord.begin(1)
    coord.notch(1)
    assert coord.target == step_scale(step_scale(1.0, 1), 1)


def test_target_accumulates_on_direction_reversal(qapp):
    host = _FakeHost(scale=1.0)
    coord = ScaleGestureProxy(host)
    coord.begin(1)
    coord.notch(-3)
    assert coord.target == step_scale(step_scale(1.0, 1), -3)


def test_begin_arms_and_sets_handoff_guard(qapp):
    # begin() arms synchronously, sets the restack-suppression guard on the host,
    # and QUEUES the park (so the just-shown proxy maps first) - park is NOT
    # synchronous.
    host = _FakeHost(scale=1.0)
    coord = ScaleGestureProxy(host)
    coord.begin(1)
    assert coord.active is True
    assert coord._park_pending is True
    assert getattr(host, "_scale_handoff_active", False) is True
    assert "make_proxy" in host.events
    assert "park_scaling_windows" not in host.events  # queued, not synchronous


def test_park_then_start_runs_after_event_loop(qapp):
    host = _FakeHost(scale=1.0)
    coord = ScaleGestureProxy(host)
    coord.begin(1)
    qapp.processEvents()                       # drain the queued _park_then_start
    assert "park_scaling_windows" in host.events
    assert host.events.index("make_proxy") < host.events.index("park_scaling_windows")
    assert coord._park_pending is False


def test_notch_while_park_pending_only_updates_target(qapp):
    host = _FakeHost(scale=1.0)
    coord = ScaleGestureProxy(host)
    coord.begin(1)                             # park still pending (not drained)
    assert coord._park_pending is True
    coord.notch(1)
    assert coord.target == step_scale(step_scale(1.0, 1), 1)
    assert "park_scaling_windows" not in host.events  # still not parked, no anim start


def test_settle_order_holds_proxy_then_drops(qapp):
    host = _FakeHost(scale=1.0)
    coord = ScaleGestureProxy(host)
    coord.begin(2)
    qapp.processEvents()                       # park + start anim
    host.events.clear()
    target = coord.target
    proxy = coord._proxy
    coord._settle()

    # Front half (synchronous): full input captured, reals placed WITHOUT restack,
    # repainted; proxy NOT yet dropped; gesture still busy; guard still set.
    assert host.scale == target
    assert host.events == [
        "capture_full_input",
        ("settle_placement", False),
        "repaint_scaling_windows",
    ]
    assert coord._proxy is proxy
    assert proxy.deleted is False
    assert coord.active is True and coord._settling is True
    assert getattr(host, "_scale_handoff_active") is True

    coord._finish_settle()                     # the hold timer's target (call directly)

    # Back half: proxy dropped, z-order reasserted, guard cleared, end fired.
    assert proxy.deleted is True
    assert coord._proxy is None
    assert "reassert_after_settle" in host.events
    assert "on_gesture_end" in host.events
    assert getattr(host, "_scale_handoff_active") is False
    assert coord.active is False and coord._settling is False


def test_cancel_unparks_and_drops_without_committing(qapp):
    host = _FakeHost(scale=1.0)
    coord = ScaleGestureProxy(host)
    coord.begin(1)
    qapp.processEvents()                       # parked
    proxy = coord._proxy
    coord.cancel()
    assert coord.active is False and coord._settling is False
    assert coord._proxy is None and proxy.deleted is True
    assert host.scale == 1.0                              # start scale restored
    assert ("settle_placement", False) in host.events    # un-park at start scale
    assert "unpark_scaling_windows" in host.events        # safety-net restore
    assert "on_gesture_end" not in host.events            # no commit
    assert getattr(host, "_scale_handoff_active") is False


def test_cancel_before_park_drains_never_parks(qapp):
    host = _FakeHost(scale=1.0)
    coord = ScaleGestureProxy(host)
    coord.begin(1)                             # park still queued
    coord.cancel()                             # cancel before it drains
    qapp.processEvents()                       # the queued _park_then_start must no-op
    assert "park_scaling_windows" not in host.events
    assert coord._proxy is None
    assert getattr(host, "_scale_handoff_active") is False


def test_begin_while_active_delegates_to_notch(qapp):
    host = _FakeHost(scale=1.0)
    coord = ScaleGestureProxy(host)
    coord.begin(1)
    snapshots_before = host.events.count("snapshot")
    coord.begin(1)  # second begin while active -> notch, no re-snapshot
    assert host.events.count("snapshot") == snapshots_before
    assert coord.target == step_scale(step_scale(1.0, 1), 1)


def test_notch_while_inactive_begins(qapp):
    host = _FakeHost(scale=1.0)
    coord = ScaleGestureProxy(host)
    coord.notch(1)  # no active gesture -> begin
    assert coord.active is True
    assert "snapshot" in host.events
    assert coord.target == step_scale(1.0, 1)


def test_notch_ignored_while_settling(qapp):
    # A late notch arriving after _settle() has started committing must NOT
    # retarget the stopped animation or revive the dropping proxy.
    host = _FakeHost(scale=1.0)
    coord = ScaleGestureProxy(host)
    coord.begin(1)
    qapp.processEvents()  # drain the queued park
    coord._settle()
    assert coord._settling is True
    target_before = coord.target
    anim_before = coord._anim

    coord.notch(1)  # arrives mid-settle -> ignored

    assert coord.target == target_before   # target unchanged
    assert coord._anim is anim_before       # no new animation started

    coord._finish_settle()  # the hold timer's target completes the back half
    assert coord.active is False
    assert coord._settling is False


def test_cancel_during_settling_leaves_clean_state(qapp):
    # Cancelling mid-settle (proxy shown, _finish_settle queued) must drop the
    # proxy once, clear active/_settling, and the queued back half must become a
    # no-op (no double-drop, no on_gesture_end after cancel).
    host = _FakeHost(scale=1.0)
    coord = ScaleGestureProxy(host)
    coord.begin(1)
    qapp.processEvents()  # drain the queued park
    coord._settle()
    proxy = coord._proxy
    assert coord._settling is True

    coord.cancel()  # before the queued _finish_settle runs

    assert coord._proxy is None
    assert proxy.deleted is True
    assert coord.active is False
    assert coord._settling is False
    assert "on_gesture_end" not in host.events

    proxy.deleted = False  # detect a (forbidden) second drop
    coord._finish_settle()  # the stale hold-timer back half must no-op

    assert proxy.deleted is False
    assert "on_gesture_end" not in host.events


def test_cancel_restores_start_scale(qapp):
    """cancel() must restore the gesture's START scale (the animation walked the
    live host.scale to a transient mid-value); otherwise a later save flush could
    persist that transient scale, violating 'cancel = no commit'."""
    host = _FakeHost(scale=1.0)
    coord = ScaleGestureProxy(host)
    coord.begin(1)
    coord._on_frame(1.32)        # animation frame moved the live scale
    assert host.scale == 1.32
    coord.cancel()
    assert host.scale == 1.0     # restored to the pre-gesture scale
