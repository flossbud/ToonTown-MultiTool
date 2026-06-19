"""Tests for ClusterHost: uniform-scale QGraphicsView proxy."""
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from utils.overlay.cluster_host import ClusterHost


def _content():
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(QLabel("x"))
    w.setFixedSize(200, 200)
    return w


def test_set_scale_resizes_host(qapp):
    host = ClusterHost(_content())
    host.set_scale(1.0)
    base = host.size()
    host.set_scale(0.5)
    assert host.width() < base.width() and host.height() < base.height()


def test_scale_is_clamped(qapp):
    host = ClusterHost(_content())
    host.set_scale(9.0)
    assert host.current_scale() <= 1.75
