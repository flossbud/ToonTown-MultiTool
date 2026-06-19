from PySide6.QtGui import QWheelEvent
from PySide6.QtCore import Qt, QPoint, QPointF
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
