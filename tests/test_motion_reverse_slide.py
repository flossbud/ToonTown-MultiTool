import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget, QLabel


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _build_stack(qapp):
    st = QStackedWidget()
    st.addWidget(QWidget()); st.addWidget(QWidget())
    st.resize(400, 300)
    st.show(); qapp.processEvents()
    return st


def _proxy_start_ys(st):
    from PySide6.QtWidgets import QLabel as _QL
    return sorted(p.pos().y() for p in st.findChildren(_QL)
                  if p.property("is_transition_proxy"))


def _pos_anim_end_ys(group):
    from PySide6.QtCore import QPropertyAnimation
    ys = []
    for i in range(group.animationCount()):
        a = group.animationAt(i)
        if isinstance(a, QPropertyAnimation) and a.propertyName() == b"pos":
            ys.append(a.endValue().y())
    return sorted(ys)


def test_vertical_forward_incoming_from_top(qapp, monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: False)
    st = _build_stack(qapp)
    grp = motion.push_slide_pages(st, 0, 1, axis="v")
    ys = _proxy_start_ys(st)
    assert -300 in ys and 0 in ys
    assert int(300 * 0.08) in _pos_anim_end_ys(grp)


def test_vertical_reverse_incoming_from_below(qapp, monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: False)
    st = _build_stack(qapp)
    grp = motion.push_slide_pages(st, 1, 0, axis="v", reverse=True)
    ys = _proxy_start_ys(st)
    assert int(300 * 0.08) in ys and 0 in ys
    assert -300 not in ys
    assert -300 in _pos_anim_end_ys(grp)        # outgoing exits UP to y=-h
