"""Tests for OverlaySurface: parentless non-activating borrowed-widget host.

Run with:
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/test_overlay_surface.py -q
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt, QRect
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from utils.overlay.backend import OverlayBackend
from utils.overlay.surface import OverlaySurface


# ---------------------------------------------------------------------------
# Stub backend
# ---------------------------------------------------------------------------

class StubBackend(OverlayBackend):
    def __init__(self):
        self.above_calls: list = []
        self.non_activating_calls: list = []

    def is_available(self) -> bool:
        return True

    def set_above(self, window) -> None:
        self.above_calls.append(window)

    def set_non_activating(self, window) -> None:
        self.non_activating_calls.append(window)


# ---------------------------------------------------------------------------
# Construction / flags / attributes
# ---------------------------------------------------------------------------

def test_parentless_top_level(qapp):
    s = OverlaySurface()
    assert s.parent() is None


def test_window_flags(qapp):
    s = OverlaySurface()
    flags = s.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
    assert flags & Qt.WindowDoesNotAcceptFocus
    # The window TYPE (masked) must be plain Qt.Window, NOT Qt.Tool: a Tool window
    # is coupled to the app's main window and is minimized/destroyed along with it,
    # which made the cluster vanish when transparent mode minimizes the main window.
    # (Type flags are values within WindowType_Mask, not independent bits, so this
    # must be an equality test on the masked type - Qt.Tool overlaps the Window bit.)
    window_type = flags & Qt.WindowType_Mask
    assert window_type == Qt.Window
    assert window_type != Qt.Tool


def test_attributes_set(qapp):
    s = OverlaySurface()
    assert s.testAttribute(Qt.WA_TranslucentBackground)
    assert s.testAttribute(Qt.WA_ShowWithoutActivating)


def test_delete_on_close_is_off(qapp):
    s = OverlaySurface()
    assert not s.testAttribute(Qt.WA_DeleteOnClose)


# ---------------------------------------------------------------------------
# host() / release()
# ---------------------------------------------------------------------------

def test_host_reparents_widget(qapp):
    s = OverlaySurface()
    w = QWidget()
    s.host(w)
    assert w.parent() is s


def test_host_full_bleed_layout(qapp):
    s = OverlaySurface()
    w = QWidget()
    s.host(w)
    margins = s.layout().contentsMargins()
    assert margins.left() == 0
    assert margins.top() == 0
    assert margins.right() == 0
    assert margins.bottom() == 0


def test_host_second_releases_first(qapp):
    s = OverlaySurface()
    w1 = QWidget()
    w2 = QWidget()
    s.host(w1)
    s.host(w2)
    # w1 must have been released (no parent), w2 must be hosted
    assert w1.parent() is None
    assert w2.parent() is s


def test_host_idempotent_same_widget(qapp):
    """Hosting the same widget twice should not double-add it."""
    s = OverlaySurface()
    w = QWidget()
    s.host(w)
    s.host(w)
    assert s.layout().count() == 1


# ---------------------------------------------------------------------------
# release()
# ---------------------------------------------------------------------------

def test_release_returns_widget(qapp):
    s = OverlaySurface()
    w = QWidget()
    s.host(w)
    returned = s.release()
    assert returned is w


def test_release_clears_parent(qapp):
    s = OverlaySurface()
    w = QWidget()
    s.host(w)
    s.release()
    assert w.parent() is None


def test_release_does_not_delete_widget(qapp):
    s = OverlaySurface()
    w = QWidget()
    s.host(w)
    s.release()
    assert isValid(w)


def test_release_second_call_returns_none(qapp):
    s = OverlaySurface()
    w = QWidget()
    s.host(w)
    s.release()
    assert s.release() is None


def test_release_empty_returns_none(qapp):
    s = OverlaySurface()
    assert s.release() is None


# ---------------------------------------------------------------------------
# set_overlay_geometry()
# ---------------------------------------------------------------------------

def test_set_overlay_geometry(qapp):
    s = OverlaySurface()
    rect = QRect(50, 60, 300, 200)
    s.show()
    QApplication.processEvents()
    s.set_overlay_geometry(rect)
    QApplication.processEvents()
    # Under offscreen QPA geometry is accepted but position may not be reported.
    # Assert size always; position is a best-effort check.
    assert s.width() == rect.width()
    assert s.height() == rect.height()


# ---------------------------------------------------------------------------
# Backend delegation on first show
# ---------------------------------------------------------------------------

def test_backend_called_on_show(qapp):
    stub = StubBackend()
    s = OverlaySurface(backend=stub)
    s.show()
    QApplication.processEvents()
    assert s in stub.above_calls
    assert s in stub.non_activating_calls


def test_backend_reapplied_on_every_show(qapp):
    """Hints must re-apply on EVERY show, not once: if the native window handle is
    recreated across a hide/show, a one-shot latch would leave the new X window
    without SKIP_TASKBAR/ABOVE (the stray taskbar icons + drop-below-games bug)."""
    stub = StubBackend()
    s = OverlaySurface(backend=stub)
    s.show()
    QApplication.processEvents()
    s.hide()
    s.show()
    QApplication.processEvents()
    assert stub.above_calls.count(s) == 2
    assert stub.non_activating_calls.count(s) == 2


def test_noop_backend_show_safe(qapp):
    """Constructing with no explicit backend (NoOp) must not raise on show."""
    s = OverlaySurface()
    s.show()
    QApplication.processEvents()
    s.hide()


class _RaisingAboveBackend(StubBackend):
    def set_above(self, window) -> None:
        raise RuntimeError("boom")


def test_set_above_failure_does_not_skip_non_activating(qapp):
    """Independent backend ops: a set_above failure must not skip
    set_non_activating (else the surface is 'above' but still activating)."""
    stub = _RaisingAboveBackend()
    s = OverlaySurface(backend=stub)
    s.show()
    QApplication.processEvents()
    assert stub.non_activating_calls.count(s) == 1  # still applied despite set_above raising


def test_host_none_is_noop(qapp):
    """host(None) is a no-op and does not disturb an already-hosted widget."""
    s = OverlaySurface()
    w = QWidget()
    s.host(w)
    s.host(None)
    assert s._hosted is w  # unchanged
    s.host(w)  # still releasable normally
    assert s.release() is w


def test_cross_surface_rehost_clears_old_tracking(qapp):
    """Hosting a widget already hosted by another surface releases it there
    first, so the old surface's _hosted does not go stale (else its later
    release() would orphan the widget out from under the new surface)."""
    import shiboken6
    s1, s2 = OverlaySurface(), OverlaySurface()
    w = QWidget()
    s1.host(w)
    s2.host(w)
    assert s2._hosted is w
    assert s1._hosted is None              # old tracking cleared
    assert w.parent() is s2
    assert s1.release() is None            # nothing to release on s1
    assert w.parent() is s2                # NOT orphaned
    assert shiboken6.isValid(w)
