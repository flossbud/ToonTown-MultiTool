"""Tests for paint_cc_badge accepting portrait_brush and pattern args."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _paint(qapp, **kwargs):
    """Render once; return without crashing means the signature accepts the kwargs."""
    from utils.cc_badge_paint import paint_cc_badge
    pm = QPixmap(64, 64)
    pm.fill(QColor("#00000000"))
    p = QPainter(pm)
    paint_cc_badge(
        p,
        QRect(0, 0, 64, 64),
        QColor("#d9a04e"),
        None,  # no asset stem so we don't depend on assets being present
        1,
        **kwargs,
    )
    p.end()
    return pm


def test_baseline_call_still_works(qapp):
    pm = _paint(qapp)
    assert not pm.isNull()


def test_accepts_portrait_brush_kwarg(qapp):
    pm = _paint(qapp, portrait_brush=QBrush(QColor("#56c856")))
    assert not pm.isNull()


def test_accepts_pattern_kwarg(qapp):
    pm = _paint(qapp, pattern=("dots", QColor("#ffffff")))
    assert not pm.isNull()


def test_pattern_none_is_noop(qapp):
    pm = _paint(qapp, pattern=None)
    assert not pm.isNull()
