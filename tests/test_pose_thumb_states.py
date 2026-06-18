"""Tests for bounded shimmer/failure states on _PoseTile.

Covers: loading -> loaded, loading -> failed (timeout), failed -> retry -> loading,
and that timeout after load is a no-op.

Run with:
  QT_QPA_PLATFORM=offscreen TTMT_NO_VENV_REEXEC=1 \
    /tmp/pinwheel_venv/bin/python -m pytest tests/test_pose_thumb_states.py -v
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Required tests (per spec)
# ---------------------------------------------------------------------------

def test_tile_starts_loading_then_loads(qapp):
    from utils.widgets.toon_customization_sections import _PoseTile
    from PySide6.QtGui import QPixmap

    t = _PoseTile("portrait")
    assert t.is_loading() and not t.is_failed() and not t.has_pixmap()

    pm = QPixmap(80, 80)
    pm.fill()
    t.set_pixmap(pm)
    assert t.has_pixmap() and not t.is_loading() and not t.is_failed()


def test_timeout_flips_to_failed_and_retry(qapp):
    from utils.widgets.toon_customization_sections import _PoseTile

    t = _PoseTile("portrait")
    t._on_load_timeout()  # simulate timeout while still loading
    assert t.is_failed() and not t.is_loading()

    got = []
    t.retry_requested.connect(got.append)
    t._emit_click_for_test()  # triggers the failed-tile click path
    assert got == ["portrait"] and t.is_loading()  # retry returns to loading


def test_set_pixmap_before_timeout_is_loaded(qapp):
    from utils.widgets.toon_customization_sections import _PoseTile
    from PySide6.QtGui import QPixmap

    t = _PoseTile("portrait")
    pm = QPixmap(80, 80)
    pm.fill()
    t.set_pixmap(pm)
    t._on_load_timeout()  # timeout after load is a no-op
    assert t.has_pixmap() and not t.is_failed()


# ---------------------------------------------------------------------------
# Additional correctness tests
# ---------------------------------------------------------------------------

def test_loading_tile_click_does_not_emit_clicked_pose(qapp):
    """A click on a LOADING tile must not emit clicked_pose."""
    from utils.widgets.toon_customization_sections import _PoseTile

    t = _PoseTile("sit")
    assert t.is_loading()

    picked = []
    t.clicked_pose.connect(picked.append)
    t._emit_click_for_test()
    assert picked == []


def test_loaded_tile_click_emits_clicked_pose(qapp):
    """A click on a LOADED tile emits clicked_pose as before."""
    from utils.widgets.toon_customization_sections import _PoseTile
    from PySide6.QtGui import QPixmap

    t = _PoseTile("run")
    pm = QPixmap(80, 80)
    pm.fill()
    t.set_pixmap(pm)

    picked = []
    t.clicked_pose.connect(picked.append)
    t._emit_click_for_test()
    assert picked == ["run"]


def test_failed_tile_click_does_not_emit_clicked_pose(qapp):
    """A click on a FAILED tile must not emit clicked_pose."""
    from utils.widgets.toon_customization_sections import _PoseTile

    t = _PoseTile("wave")
    t._on_load_timeout()
    assert t.is_failed()

    picked = []
    t.clicked_pose.connect(picked.append)
    t._emit_click_for_test()
    assert picked == []


def test_failed_tile_retry_resets_to_loading(qapp):
    """After retry, the tile must be back in loading state."""
    from utils.widgets.toon_customization_sections import _PoseTile

    t = _PoseTile("dance")
    t._on_load_timeout()
    assert t.is_failed()

    t._emit_click_for_test()
    assert t.is_loading() and not t.is_failed() and not t.has_pixmap()


def test_set_pixmap_none_resets_to_loading(qapp):
    """set_pixmap(None) transitions a loaded tile back to loading state."""
    from utils.widgets.toon_customization_sections import _PoseTile
    from PySide6.QtGui import QPixmap

    t = _PoseTile("portrait")
    pm = QPixmap(80, 80)
    pm.fill()
    t.set_pixmap(pm)
    assert t.has_pixmap() and not t.is_loading()

    t.set_pixmap(None)
    assert t.is_loading() and not t.has_pixmap()


def test_pose_thumb_states_helpers_importable(qapp):
    """paint_shimmer and paint_failed_mark must be importable."""
    from utils.widgets.pose_thumb_states import paint_shimmer, paint_failed_mark
    assert callable(paint_shimmer)
    assert callable(paint_failed_mark)


def test_shimmer_paint_does_not_raise(qapp):
    """paint_shimmer must not raise for any phase in [0, 1]."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    from utils.widgets.pose_thumb_states import paint_shimmer

    img = QImage(80, 80, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    rect = QRect(0, 0, 80, 80)
    for phase in (0.0, 0.25, 0.5, 0.75, 1.0):
        paint_shimmer(p, rect, phase)
    p.end()


def test_failed_mark_paint_does_not_raise(qapp):
    """paint_failed_mark must not raise."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    from utils.widgets.pose_thumb_states import paint_failed_mark

    img = QImage(80, 80, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    rect = QRect(0, 0, 80, 80)
    paint_failed_mark(p, rect)
    p.end()


def test_load_timeout_constant_exists(qapp):
    """_LOAD_TIMEOUT_MS must be a positive integer constant on _PoseTile."""
    from utils.widgets.toon_customization_sections import _PoseTile
    assert isinstance(_PoseTile._LOAD_TIMEOUT_MS, int)
    assert _PoseTile._LOAD_TIMEOUT_MS > 0
