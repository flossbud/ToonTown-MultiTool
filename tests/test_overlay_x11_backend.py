import sys, pytest
pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="x11 only")
from PySide6.QtGui import QRegion
from PySide6.QtCore import QRect
from utils.overlay.x11_backend import region_to_rects, X11OverlayBackend
from utils.overlay.backend import NoOpOverlayBackend

def test_region_to_rects_round_trips():
    region = QRegion(QRect(10, 20, 30, 40)).united(QRegion(QRect(100, 0, 5, 5)))
    rects = region_to_rects(region)
    assert (10, 20, 30, 40) in rects
    assert (100, 0, 5, 5) in rects

def test_empty_region_is_empty_list():
    assert region_to_rects(QRegion()) == []

def test_noop_skip_close_animation_is_safe():
    # Base/NoOp must expose the method and never raise (best-effort hint).
    NoOpOverlayBackend().set_skip_close_animation(object())

def test_x11_backend_exposes_skip_close_animation():
    # The X11 backend declares the method; the actual property write is live-only
    # (needs a real X display), so we only assert the contract exists here.
    assert hasattr(X11OverlayBackend, "set_skip_close_animation")
