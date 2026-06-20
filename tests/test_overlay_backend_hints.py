"""Tests for overlay backend hints (set_above, set_non_activating, apply_input_shape)
and the device-pixel shape conversion (device_input_region).

Pure / offscreen - no MultitoonTab build, no live X11 display required.
Run:
  TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python \\
    -m pytest tests/test_overlay_backend_hints.py -q
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QPainterPath, QRegion

from utils.overlay.backend import NoOpOverlayBackend, get_overlay_backend
from utils.overlay.region import device_input_region
from utils.overlay.x11_backend import region_to_rects


# ---------------------------------------------------------------------------
# NoOpOverlayBackend - availability + no-raise safety
# ---------------------------------------------------------------------------

def test_noop_is_unavailable():
    assert NoOpOverlayBackend().is_available() is False


def test_noop_set_above_does_not_raise():
    NoOpOverlayBackend().set_above(None)


def test_noop_set_non_activating_does_not_raise():
    NoOpOverlayBackend().set_non_activating(None)


def test_noop_apply_input_shape_does_not_raise():
    path = QPainterPath()
    path.addRect(QRectF(0, 0, 100, 100))
    NoOpOverlayBackend().apply_input_shape(None, path, 1.0)


def test_factory_backend_has_new_methods():
    """get_overlay_backend() result must expose the new hint methods."""
    b = get_overlay_backend()
    for m in ("set_above", "set_non_activating", "apply_input_shape"):
        assert callable(getattr(b, m)), f"missing: {m}"


# ---------------------------------------------------------------------------
# region_to_rects - unchanged behavior
# ---------------------------------------------------------------------------

def test_region_to_rects_round_trips():
    region = QRegion(QRect(10, 20, 30, 40)).united(QRegion(QRect(100, 0, 5, 5)))
    rects = region_to_rects(region)
    assert (10, 20, 30, 40) in rects
    assert (100, 0, 5, 5) in rects


def test_region_to_rects_empty():
    assert region_to_rects(QRegion()) == []


# ---------------------------------------------------------------------------
# device_input_region - DPR conversion (the key new behavior to lock)
# ---------------------------------------------------------------------------

def _rect_path(x: float, y: float, w: float, h: float) -> QPainterPath:
    p = QPainterPath()
    p.addRect(QRectF(x, y, w, h))
    return p


def test_device_input_region_dpr1_preserves_bounds():
    """DPR=1.0: device region bounds match logical path bounds (within 1px polygon rounding)."""
    path = _rect_path(10, 20, 100, 80)
    region = device_input_region(path, 1.0)
    br = region.boundingRect()
    assert abs(br.x() - 10) <= 1
    assert abs(br.y() - 20) <= 1
    assert abs(br.width() - 100) <= 2
    assert abs(br.height() - 80) <= 2


def test_device_input_region_dpr2_doubles_bounds():
    """DPR=2.0: device region bounds are ~2x the logical path bounds."""
    path = _rect_path(10, 20, 100, 80)
    region = device_input_region(path, 2.0)
    br = region.boundingRect()
    assert abs(br.x() - 20) <= 1
    assert abs(br.y() - 40) <= 1
    assert abs(br.width() - 200) <= 2
    assert abs(br.height() - 160) <= 2


def test_device_input_region_empty_path_returns_empty():
    assert device_input_region(QPainterPath(), 2.0).isEmpty()


def test_device_input_region_dpr2_larger_than_dpr1():
    """DPR=2.0 region is strictly larger than DPR=1.0 region."""
    path = _rect_path(0, 0, 50, 50)
    r1 = device_input_region(path, 1.0)
    r2 = device_input_region(path, 2.0)
    assert r2.boundingRect().width() > r1.boundingRect().width()
    assert r2.boundingRect().height() > r1.boundingRect().height()


def test_device_input_region_fractional_dpr_15():
    """DPR=1.5 (common under XWayland fractional scaling): device bounds ~1.5x."""
    path = _rect_path(0, 0, 100, 80)
    br = device_input_region(path, 1.5).boundingRect()
    assert abs(br.width() - 150) <= 2
    assert abs(br.height() - 120) <= 2


def test_device_input_region_nonpositive_dpr_falls_back_to_logical():
    """A non-positive dpr (which Qt never reports) clamps to 1.0 so the shape
    renders at logical size instead of collapsing/vanishing."""
    path = _rect_path(10, 20, 100, 80)
    logical = device_input_region(path, 1.0).boundingRect()
    for bad in (0.0, -1.0):
        # Full-rect compare (x/y too): an unclamped dpr=-1 would mirror the
        # region to negative coordinates while preserving width/height.
        assert device_input_region(path, bad).boundingRect() == logical
