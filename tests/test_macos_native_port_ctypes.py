"""Bridge-level tests for the pure-ctypes (PyObjC-free) native delivery port.

These run only on macOS: they exercise the real libobjc / AppKit / CoreGraphics ABI
to prove the raw objc_msgSend NSEvent->CGEvent construction produces a genuine
CGEvent of the expected type WITHOUT importing PyObjC. If the objc_msgSend ABI were
wrong, _build_ns_cgevent would return null or the CGEvent would carry the wrong type.
"""
import ctypes
import sys

import pytest

import utils.macos_mouse_delivery as d

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="native libobjc/CoreGraphics bridge is macOS-only")


def _coregraphics_get_type():
    """A separate CoreGraphics CDLL with CGEventGetType typed, for read-back."""
    cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    cg.CGEventGetType.restype = ctypes.c_uint32
    cg.CGEventGetType.argtypes = [ctypes.c_void_p]
    return cg


@pytest.mark.parametrize("ns_type", [1, 2, 5, 6])
def test_build_cgevent_types(ns_type):
    """_build_ns_cgevent(ns_type, click, 0) must return a non-null CGEventRef whose
    CGEventType equals the NSEventType it was built from (the mouse NSEventType and the
    mouse CGEventType enums coincide for down=1, up=2, moved=5, dragged=6)."""
    click = d.click_count_for("move") if ns_type == 5 else 1
    pool = d._objc().objc_autoreleasePoolPush()   # reclaim the autoreleased NSEvent
    try:
        ev = d._build_ns_cgevent(ns_type, click, 0)
        assert ev, f"_build_ns_cgevent returned null for ns_type={ns_type} (objc_msgSend ABI wrong)"
        got = _coregraphics_get_type().CGEventGetType(ctypes.c_void_p(ev))
        assert got == ns_type, f"CGEventGetType={got} != ns_type={ns_type} (objc_msgSend ABI wrong)"
    finally:
        d._objc().objc_autoreleasePoolPop(pool)
