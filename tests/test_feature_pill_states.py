"""FeaturePill unit behavior (label, click signal, dim/scale API).
Tab-level state-machine tests (label transitions driven through real
settings writes) live in the same file and are added with the tab wiring."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_pill_defaults_and_label(qapp):
    from tabs.multitoon._feature_pill import FeaturePill
    pill = FeaturePill()
    assert pill.label() == "Enable features"
    pill.set_label("More features")
    assert pill.label() == "More features"


def test_pill_click_emits(qapp):
    from tabs.multitoon._feature_pill import FeaturePill
    pill = FeaturePill()
    pill.resize(158, 38)
    hits = []
    pill.clicked.connect(lambda: hits.append(True))
    QTest.mouseClick(pill, Qt.LeftButton, pos=QPoint(79, 19))
    assert hits == [True]


def test_pill_dim_and_scale_apis(qapp):
    from tabs.multitoon._feature_pill import FeaturePill
    pill = FeaturePill()
    pill.set_dim_progress(0.5)
    pill.set_dim_progress(2.0)   # clamps, no raise
    pill.set_paint_scale(1.5)
    pill.set_paint_scale(1.5)    # idempotent, no raise


def test_pill_paint_smoke_across_envelope(qapp):
    """Exercise the paint path at the real control-column size across the
    CardMetrics scale envelope, fully dimmed, and with a long label. The
    widget is almost entirely paint math; grab() renders offscreen and any
    QPainter misuse raises or warns."""
    from tabs.multitoon._feature_pill import FeaturePill
    from utils.overlay.card_metrics import CardMetrics
    pill = FeaturePill()
    for scale in (0.5, 1.0, 1.75):
        m = CardMetrics(scale)
        pill.setFixedHeight(m.keyset_h)
        pill.resize(m.ctrl_w, m.keyset_h)
        pill.set_paint_scale(m.scale)
        for dim in (0.0, 1.0):
            pill.set_dim_progress(dim)
            img = pill.grab().toImage()
            assert not img.isNull()
    pill.set_label("An unexpectedly long feature discovery label")
    assert not pill.grab().toImage().isNull()


def test_pill_release_outside_does_not_emit(qapp):
    from PySide6.QtCore import QPointF, QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    from tabs.multitoon._feature_pill import FeaturePill
    pill = FeaturePill()
    pill.resize(158, 38)
    hits = []
    pill.clicked.connect(lambda: hits.append(True))
    outside = QPointF(500.0, 500.0)
    ev = QMouseEvent(QEvent.MouseButtonRelease, outside,
                     pill.mapToGlobal(outside.toPoint()),
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(pill, ev)
    assert hits == []
