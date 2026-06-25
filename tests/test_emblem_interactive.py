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


def test_scroll_emits_only_when_armed(qapp):
    e = _Emblem()
    e.set_interactive(True)
    got = []
    e.resize_scrolled.connect(lambda n: got.append(n))

    ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
                     Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)

    e.wheelEvent(ev)          # not armed yet
    assert got == []

    e._armed = True            # simulate dwell arm
    e.wheelEvent(ev)
    assert got == [1]


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
