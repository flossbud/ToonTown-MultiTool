from PySide6.QtGui import QWheelEvent
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from tabs.multitoon._compact_layout import _Emblem


def test_default_is_passive(qapp):
    e = _Emblem()
    assert e.testAttribute(Qt.WA_TransparentForMouseEvents) is True


def test_set_interactive_enables_mouse(qapp):
    e = _Emblem()
    e.set_interactive(True)
    assert e.testAttribute(Qt.WA_TransparentForMouseEvents) is False


def _wheel(dy, phase=Qt.ScrollUpdate):
    return QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, dy),
                       Qt.NoButton, Qt.NoModifier, phase, False)


def test_scroll_emits_only_when_armed(qapp):
    e = _Emblem()
    e.set_interactive(True)
    got = []
    e.resize_scrolled.connect(lambda n: got.append(n))

    e.wheelEvent(_wheel(120))  # not armed yet
    assert got == []

    e._armed = True            # simulate dwell arm
    e.wheelEvent(_wheel(120))
    assert got == [1]


# --- notch accumulation (high-resolution scroll devices) ----------------------
# Trackpads/Magic Mouse deliver many small angleDelta events per gesture plus a
# momentum tail; emitting a notch per EVENT made scaling feel slippery-fast on
# macOS (user report 2026-07-04). One notch per +-120 accumulated = detent feel;
# classic wheels (one +-120 event per detent) behave exactly as before.

def _armed_emblem():
    e = _Emblem()
    e.set_interactive(True)
    e._armed = True
    got = []
    e.resize_scrolled.connect(lambda n: got.append(n))
    return e, got


def test_high_res_deltas_accumulate_to_one_notch_per_detent(qapp):
    e, got = _armed_emblem()
    e.wheelEvent(_wheel(40))
    e.wheelEvent(_wheel(40))
    assert got == []                    # 80 < 120: no notch yet
    e.wheelEvent(_wheel(40))
    assert got == [1]                   # 120 accumulated -> one notch
    e.wheelEvent(_wheel(40))
    assert got == [1]                   # remainder starts over


def test_momentum_phase_never_scales(qapp):
    e, got = _armed_emblem()
    e.wheelEvent(_wheel(240, Qt.ScrollMomentum))
    assert got == []                    # the coast tail must not keep scaling


def test_direction_flip_resets_accumulation(qapp):
    e, got = _armed_emblem()
    e.wheelEvent(_wheel(100))           # no notch, 100 pending upward
    e.wheelEvent(_wheel(-120))          # flip: pending resets, then a full detent
    assert got == [-1]


def test_fast_spin_batches_notches_in_one_emit(qapp):
    e, got = _armed_emblem()
    e.wheelEvent(_wheel(240))
    assert got == [2]                   # two detents in one event -> one emit of 2


def test_arming_resets_stale_accumulation(qapp):
    e, got = _armed_emblem()
    e.wheelEvent(_wheel(100))           # 100 pending, below a notch
    e._on_dwell_timeout()               # fresh arming gesture
    e.wheelEvent(_wheel(40))
    assert got == []                    # stale 100 must not combine with new 40


# --- disarm robustness against synthetic Leave from overlay window churn ------
# When the radial menu is open, each scroll-scale tick resizes/restacks overlay
# surfaces over the emblem, so Qt fires a SYNTHETIC leaveEvent even though the
# physical cursor never left the emblem. _armed is a physical-hover state, so it
# must survive that and only disarm on a real departure.

def test_point_on_emblem_true_at_center_false_outside(qapp):
    e = _Emblem()
    cx, cy = e.width() // 2, e.height() // 2
    assert e._point_on_emblem(QPoint(cx, cy)) is True          # center: on the disc
    assert e._point_on_emblem(QPoint(0, 0)) is False           # corner: outside inscribed disc
    assert e._point_on_emblem(QPoint(e.width() + 50, cy)) is False  # well outside


def test_leave_keeps_armed_on_synthetic_crossing(qapp, monkeypatch):
    e = _Emblem(); e.set_interactive(True); e._armed = True
    e._dwell_timer.start()
    monkeypatch.setattr(e, "_cursor_on_emblem", lambda: True)   # cursor still on the disc
    e.leaveEvent(QEvent(QEvent.Leave))
    assert e._armed is True                                     # NOT disarmed by the synthetic leave
    assert e._dwell_timer.isActive() is True                   # dwell not reset either


def test_leave_disarms_on_real_departure(qapp, monkeypatch):
    e = _Emblem(); e.set_interactive(True); e._armed = True
    monkeypatch.setattr(e, "_cursor_on_emblem", lambda: False)  # cursor truly off the disc
    e.leaveEvent(QEvent(QEvent.Leave))
    assert e._armed is False                                    # real leave disarms


# --- darwin hover-poll arming (cocoa tracking is active-app-only) -------------
# cocoa delivers enter/leave only to the ACTIVE app's windows, and the float
# cluster is a nonactivating panel by design - hovering while a game is
# frontmost never fires enterEvent, so dwell-arming was focus-gated
# (trace-proven live: wheel events arrived with armed=False and ZERO enters).
# On darwin a 100ms global-cursor poll mirrors the enter/leave transitions;
# QCursor.pos() is activation-independent. X11/win32 keep the pure event path.

def _darwin_emblem(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "platform", "darwin")
    e = _Emblem()
    e.set_interactive(True)
    return e


def test_darwin_hover_poll_created_and_gated_on_interactive(qapp, monkeypatch):
    e = _darwin_emblem(monkeypatch)
    assert e._hover_poll is not None
    assert e._hover_poll.isActive() is True        # interactive -> polling
    e.set_interactive(False)
    assert e._hover_poll.isActive() is False       # passive -> stopped


def test_non_darwin_has_no_hover_poll(qapp, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "platform", "linux")
    e = _Emblem()
    e.set_interactive(True)
    assert e._hover_poll is None                   # event path untouched off-darwin


def test_darwin_poll_arms_without_any_enter_event(qapp, monkeypatch):
    """The regression: hover + scroll with the app INACTIVE, so no enterEvent
    is ever delivered. The poll alone must start the dwell, arm, and let the
    wheel scale."""
    e = _darwin_emblem(monkeypatch)
    monkeypatch.setattr(e, "_cursor_on_emblem", lambda: True)
    e._poll_hover()                                # first on-disc tick
    assert e._dwell_timer.isActive() is True       # dwell started by the poll
    assert e._armed is False                       # not before the dwell elapses
    e._on_dwell_timeout()                          # dwell elapses
    assert e._armed is True

    got = []
    e.resize_scrolled.connect(lambda n: got.append(n))
    ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
                     Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
    e.wheelEvent(ev)
    assert got == [1]                              # scroll-to-scale works unfocused


def test_darwin_poll_does_not_restart_a_running_dwell(qapp, monkeypatch):
    """A poll tick while the event-driven path already started the dwell must
    not restart it (transition-guarded: on-disc with _hover_on already True
    is a no-op)."""
    e = _darwin_emblem(monkeypatch)
    monkeypatch.setattr(e, "_cursor_on_emblem", lambda: True)
    e._hover_on = True                             # enterEvent already ran
    e._dwell_timer.start()
    e._poll_hover()                                # tick: no transition, no restart
    assert e._dwell_timer.isActive() is True
    assert e._armed is False


def test_darwin_poll_disarms_on_off_disc_tick(qapp, monkeypatch):
    e = _darwin_emblem(monkeypatch)
    on = {"v": True}
    monkeypatch.setattr(e, "_cursor_on_emblem", lambda: on["v"])
    e._poll_hover()
    e._on_dwell_timeout()
    assert e._armed is True
    on["v"] = False
    e._poll_hover()                                # off-disc tick
    assert e._armed is False                       # disarmed without any leaveEvent
    assert e._dwell_timer.isActive() is False
