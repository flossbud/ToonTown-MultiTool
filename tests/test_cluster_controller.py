"""Tests for ClusterOverlayController: enter / leave / borrow / metrics-reset.

The single-window cluster controller borrows the WHOLE `_grid_host` subtree into
one ``ClusterSurface`` (instead of one surface per card), minimizes the main
window, and on leave restores the host + resets framed (scale-1.0) metrics. It is
a drop-in analog of ``OverlayGroupController`` for the single-window cluster, and
mirrors its minimize + fail-closed discipline.

These tests use LIGHT STUBS (no heavy real _CompactLayout): a stub provider whose
capture/restore record calls and actually re-parent a real `_grid_host`, a stub
window recording showMinimized/showNormal, and a stub surface recording
host/geometry/show/hide/deleteLater. Real integration is validated live later.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
        PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
        ./venv/bin/python -m pytest tests/test_cluster_controller.py -q
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtWidgets import QWidget

from utils.overlay.backend import NoOpOverlayBackend
from utils.overlay.cluster_controller import ClusterOverlayController


# ---------------------------------------------------------------------------
# Light stubs
# ---------------------------------------------------------------------------
class _StubProvider:
    """Stand-in for _CompactLayout: a real `_grid_host` (+ a real `_emblem`
    child with a geometry) plus recording capture/restore/apply_metrics."""

    def __init__(self, capture_raises: bool = False):
        self._grid_host = QWidget()
        self._grid_host.resize(400, 300)
        self._emblem = QWidget(self._grid_host)
        self._emblem.setGeometry(150, 100, 100, 100)   # center (200, 150)
        self._token = object()
        self.captured = 0
        self.restored: list = []
        self.last_metrics = None
        self.capture_raises = capture_raises
        self.restore_raises = False

    def capture_cluster_host(self):
        self.captured += 1
        if self.capture_raises:
            raise RuntimeError("capture boom")
        # Actually detach so the borrow is observable.
        self._grid_host.setParent(None)
        return self._token

    def restore_cluster_host(self, token):
        self.restored.append(token)
        if self.restore_raises:
            raise RuntimeError("restore boom")

    def apply_metrics(self, metrics):
        self.last_metrics = metrics


class _StubWindow:
    """Records showMinimized / showNormal; can be told to raise on minimize."""

    def __init__(self):
        self.minimized = 0
        self.normaled = 0
        self.minimize_raises = False

    def showMinimized(self):
        self.minimized += 1
        if self.minimize_raises:
            raise RuntimeError("minimize boom")

    def showNormal(self):
        self.normaled += 1


class _StubSurface(QWidget):
    """Recording surface exposing host/set_overlay_geometry/show/hide/
    deleteLater/release; host() actually re-parents so the borrow is observable."""

    def __init__(self, host_raises: bool = False):
        super().__init__()
        self.host_raises = host_raises
        self.hosted = None
        self.geom = None
        self.shown = 0
        self.hidden = 0
        self.released = 0
        self.deleted = 0

    def host(self, widget):
        if self.host_raises:
            raise RuntimeError("host boom")
        self.hosted = widget
        widget.setParent(self)

    def release(self):
        self.released += 1
        w = self.hosted
        if w is not None:
            w.setParent(None)
            self.hosted = None
        return w

    def set_overlay_geometry(self, rect):
        self.geom = rect

    def show(self):
        self.shown += 1

    def hide(self):
        self.hidden += 1

    def deleteLater(self):
        self.deleted += 1


def _make(provider=None, window=None, host_raises=False, on_active_changed=None):
    """Build a controller wired to recording stubs. Returns
    (controller, provider, window, created_surfaces)."""
    provider = provider if provider is not None else _StubProvider()
    window = window if window is not None else _StubWindow()
    created: list = []

    def factory():
        s = _StubSurface(host_raises=host_raises)
        created.append(s)
        return s

    ctrl = ClusterOverlayController(
        window,
        backend=NoOpOverlayBackend(),
        surface_factory=factory,
        card_provider=provider,
        on_active_changed=on_active_changed,
    )
    return ctrl, provider, window, created


# ---------------------------------------------------------------------------
# 1. enter() borrows + minimizes
# ---------------------------------------------------------------------------
def test_enter_borrows_and_minimizes(qapp):
    events: list = []
    ctrl, provider, window, created = _make(on_active_changed=events.append)

    ok = ctrl.enter()

    assert ok is True
    assert provider.captured == 1
    assert len(created) == 1
    surface = created[0]
    # The WHOLE grid_host is hosted into the single cluster surface.
    assert surface.hosted is provider._grid_host
    assert provider._grid_host.parent() is surface
    assert surface.geom is not None        # geometry was placed
    assert surface.shown == 1
    assert window.minimized == 1
    assert ctrl.is_active is True
    assert events == [True]                 # on_active_changed(True) fired


# ---------------------------------------------------------------------------
# 2. leave() restores + resets metrics
# ---------------------------------------------------------------------------
def test_leave_restores_and_resets_metrics(qapp):
    events: list = []
    ctrl, provider, window, created = _make(on_active_changed=events.append)
    ctrl.enter()
    surface = created[0]
    events.clear()

    ctrl.leave()

    # Framed metrics reset to base scale 1.0.
    assert provider.last_metrics is not None
    assert provider.last_metrics.scale == 1.0
    # Host restored with the SAME token captured at enter.
    assert provider.restored == [provider._token]
    # Surface torn down.
    assert surface.hidden == 1
    assert surface.deleted == 1
    assert window.normaled == 1
    assert ctrl.is_active is False
    assert events == [False]                # on_active_changed(False) fired


# ---------------------------------------------------------------------------
# 3. enter() while active is a no-op
# ---------------------------------------------------------------------------
def test_enter_while_active_is_noop(qapp):
    ctrl, provider, window, created = _make()
    ctrl.enter()
    assert provider.captured == 1

    again = ctrl.enter()

    assert again is True
    assert provider.captured == 1           # no second capture
    assert len(created) == 1                # no second surface
    assert window.minimized == 1            # not minimized again


def test_leave_while_inactive_is_noop(qapp):
    ctrl, provider, window, created = _make()
    ctrl.leave()                            # never entered
    assert provider.restored == []
    assert window.normaled == 0
    assert ctrl.is_active is False


# ---------------------------------------------------------------------------
# 4. FAIL-CLOSED enter
# ---------------------------------------------------------------------------
def test_enter_failclosed_on_capture_raise(qapp):
    """capture raises (before minimize): no exception escapes, stays framed,
    the window is never minimized (so never left minimized)."""
    provider = _StubProvider(capture_raises=True)
    ctrl, provider, window, created = _make(provider=provider)

    ok = ctrl.enter()

    assert ok is False
    assert ctrl.is_active is False
    assert window.minimized == 0            # never minimized -> no showNormal needed
    # A surface may have been built before capture; if so it was torn down.
    if created:
        assert created[0].deleted == 1


def test_enter_failclosed_on_host_raise_restores_borrow(qapp):
    """host raises (after capture): the borrowed grid_host is restored to the
    tab, the surface is torn down, no exception escapes, stays framed."""
    ctrl, provider, window, created = _make(host_raises=True)

    ok = ctrl.enter()

    assert ok is False
    assert ctrl.is_active is False
    assert provider.captured == 1
    assert provider.restored == [provider._token]   # borrow returned to the tab
    assert created[0].deleted == 1
    assert window.minimized == 0


def test_enter_failclosed_on_minimize_raise_restores_window(qapp):
    """showMinimized raises (after show): the window is restored via showNormal,
    the borrow is returned, the surface is torn down, stays framed."""
    window = _StubWindow()
    window.minimize_raises = True
    ctrl, provider, window, created = _make(window=window)

    ok = ctrl.enter()

    assert ok is False
    assert ctrl.is_active is False
    assert window.minimized == 1
    assert window.normaled == 1             # restored after the mid-enter failure
    assert provider.restored == [provider._token]
    assert created[0].deleted == 1


# ---------------------------------------------------------------------------
# 5. leave() resets metrics even if restore raises
# ---------------------------------------------------------------------------
def test_leave_resets_metrics_even_if_restore_raises(qapp):
    ctrl, provider, window, created = _make()
    ctrl.enter()
    surface = created[0]
    provider.restore_raises = True

    ctrl.leave()                            # must not raise

    # Metrics still reset to base scale 1.0.
    assert provider.last_metrics is not None
    assert provider.last_metrics.scale == 1.0
    # Window still restored, state cleared, surface torn down.
    assert window.normaled == 1
    assert ctrl.is_active is False
    assert surface.deleted == 1
