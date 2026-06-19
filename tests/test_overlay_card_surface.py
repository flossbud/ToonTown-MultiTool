"""Tests for CardSurface, EmblemSurface, ShapeMode, and apply_shape/clear_shape.

Run with:
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python \
        -m pytest tests/test_overlay_surface.py tests/test_overlay_card_surface.py -q
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainterPath

from utils.overlay.backend import OverlayBackend
from utils.overlay.region import device_input_region
from utils.overlay.surface import (
    CardSurface,
    EmblemSurface,
    OverlaySurface,
    ShapeMode,
)


# ---------------------------------------------------------------------------
# Stub backend that records shape calls
# ---------------------------------------------------------------------------

class ShapeStubBackend(OverlayBackend):
    def __init__(self):
        self.apply_calls: list[tuple] = []
        self.clear_calls: list = []

    def is_available(self) -> bool:
        return True

    def set_above(self, window) -> None:
        pass

    def set_non_activating(self, window) -> None:
        pass

    def apply_input_shape(self, window, path, dpr: float) -> None:
        self.apply_calls.append((window, path, dpr))

    def clear_input_region(self, window) -> None:
        self.clear_calls.append(window)


def _simple_path() -> QPainterPath:
    p = QPainterPath()
    p.addRect(0, 0, 100, 80)
    return p


# ---------------------------------------------------------------------------
# ShapeMode constants
# ---------------------------------------------------------------------------

def test_shapemode_values():
    assert ShapeMode.PINWHEEL_BITE.value == "pinwheel_bite"
    assert ShapeMode.ROUNDED_RECT.value == "rounded_rect"


# ---------------------------------------------------------------------------
# CardSurface: inheritance + construction
# ---------------------------------------------------------------------------

def test_card_surface_is_overlay_surface(qapp):
    s = CardSurface(surface_id=0)
    assert isinstance(s, OverlaySurface)


def test_card_surface_parentless(qapp):
    s = CardSurface(surface_id=2)
    assert s.parent() is None


def test_card_surface_window_flags(qapp):
    s = CardSurface(surface_id=0)
    flags = s.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
    assert flags & Qt.Tool
    assert flags & Qt.WindowDoesNotAcceptFocus


def test_card_surface_attributes(qapp):
    s = CardSurface(surface_id=1)
    assert s.testAttribute(Qt.WA_TranslucentBackground)
    assert s.testAttribute(Qt.WA_ShowWithoutActivating)
    assert not s.testAttribute(Qt.WA_DeleteOnClose)


def test_card_surface_stores_surface_id(qapp):
    for slot in range(4):
        s = CardSurface(surface_id=slot)
        assert s.surface_id == slot


def test_card_surface_default_shape_mode(qapp):
    s = CardSurface(surface_id=0)
    assert s.shape_mode is ShapeMode.PINWHEEL_BITE


def test_card_surface_set_input_shape_mode(qapp):
    s = CardSurface(surface_id=0)
    s.set_input_shape_mode(ShapeMode.ROUNDED_RECT)
    assert s.shape_mode is ShapeMode.ROUNDED_RECT
    # can switch back
    s.set_input_shape_mode(ShapeMode.PINWHEEL_BITE)
    assert s.shape_mode is ShapeMode.PINWHEEL_BITE


def test_card_surface_set_scale(qapp):
    s = CardSurface(surface_id=3)
    s.set_scale(1.5)
    assert s._scale == 1.5
    s.set_scale(0.75)
    assert s._scale == 0.75


# ---------------------------------------------------------------------------
# EmblemSurface: inheritance + construction
# ---------------------------------------------------------------------------

def test_emblem_surface_is_overlay_surface(qapp):
    s = EmblemSurface()
    assert isinstance(s, OverlaySurface)


def test_emblem_surface_parentless(qapp):
    s = EmblemSurface()
    assert s.parent() is None


def test_emblem_surface_window_flags(qapp):
    s = EmblemSurface()
    flags = s.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
    assert flags & Qt.Tool
    assert flags & Qt.WindowDoesNotAcceptFocus


def test_emblem_surface_attributes(qapp):
    s = EmblemSurface()
    assert s.testAttribute(Qt.WA_TranslucentBackground)
    assert s.testAttribute(Qt.WA_ShowWithoutActivating)
    assert not s.testAttribute(Qt.WA_DeleteOnClose)


def test_emblem_surface_set_scale(qapp):
    s = EmblemSurface()
    s.set_scale(0.5)
    assert s._scale == 0.5
    s.set_scale(1.75)
    assert s._scale == 1.75


# ---------------------------------------------------------------------------
# DPR routing: apply_shape / clear_shape pass-through (the key test)
# ---------------------------------------------------------------------------

def test_apply_shape_routes_to_backend_unchanged(qapp):
    """apply_shape must forward (surface, path, dpr) to backend.apply_input_shape
    WITHOUT scaling or converting path - the single device-pixel conversion is
    in the backend, not the surface."""
    stub = ShapeStubBackend()
    s = CardSurface(surface_id=0, backend=stub)
    path = _simple_path()
    s.apply_shape(path, 2.0)

    assert len(stub.apply_calls) == 1
    window_arg, path_arg, dpr_arg = stub.apply_calls[0]
    assert window_arg is s
    assert path_arg is path        # same object - not a copy or scaled version
    assert dpr_arg == 2.0


def test_clear_shape_routes_to_backend(qapp):
    stub = ShapeStubBackend()
    s = CardSurface(surface_id=1, backend=stub)
    s.clear_shape()

    assert len(stub.clear_calls) == 1
    assert stub.clear_calls[0] is s


def test_apply_shape_emblem_routes_to_backend(qapp):
    stub = ShapeStubBackend()
    s = EmblemSurface(backend=stub)
    path = _simple_path()
    s.apply_shape(path, 1.5)

    assert len(stub.apply_calls) == 1
    window_arg, path_arg, dpr_arg = stub.apply_calls[0]
    assert window_arg is s
    assert path_arg is path
    assert dpr_arg == 1.5


def test_clear_shape_emblem_routes_to_backend(qapp):
    stub = ShapeStubBackend()
    s = EmblemSurface(backend=stub)
    s.clear_shape()
    assert stub.clear_calls == [s]


# ---------------------------------------------------------------------------
# Integration: device_input_region scales with dpr (end-to-end lock)
#
# apply_shape passes dpr to backend.apply_input_shape, which calls
# device_input_region(path, dpr).  We verify that function directly here
# (exercising the real X11 backend headless is impractical); the stub-routing
# test above confirms apply_shape feeds the dpr to the backend.
# ---------------------------------------------------------------------------

def test_device_input_region_scales_with_dpr():
    """device_input_region at dpr=2 must produce a region ~2x the logical size."""
    path = QPainterPath()
    path.addRect(0, 0, 100, 80)

    region_1x = device_input_region(path, 1.0)
    region_2x = device_input_region(path, 2.0)

    bounds_1x = region_1x.boundingRect()
    bounds_2x = region_2x.boundingRect()

    # Width and height should each be approximately doubled.
    assert bounds_2x.width() >= bounds_1x.width() * 1.9
    assert bounds_2x.height() >= bounds_1x.height() * 1.9


def test_device_input_region_bad_dpr_falls_back():
    """Non-positive dpr must not crash or produce an empty/inverted region."""
    path = QPainterPath()
    path.addRect(0, 0, 50, 40)
    region = device_input_region(path, -1.0)
    # Falls back to 1.0 - bounding rect should be approximately logical size.
    bounds = region.boundingRect()
    assert bounds.width() > 0
    assert bounds.height() > 0
