"""Tests for ClusterOverlayController: enter / leave / borrow / metrics-reset.

The single-window cluster controller borrows the WHOLE `_grid_host` subtree into
one ``ClusterSurface`` (instead of one surface per card), hides the main
window, and on leave restores the host + resets framed (scale-1.0) metrics. It is
a drop-in analog of ``OverlayGroupController`` for the single-window cluster, and
mirrors its hide, fail-closed, and orphan-retention discipline.

These tests use LIGHT STUBS (no heavy real _CompactLayout): a stub provider whose
capture/restore record calls and ACTUALLY re-parent a real `_grid_host` (capture
detaches it; restore re-parents it to a holder widget), a stub window recording
hide/showNormal/close, and a stub surface recording host/geometry/show/hide/
release/deleteLater. Real integration is validated live later.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
        PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
        ./venv/bin/python -m pytest tests/test_cluster_controller.py -q
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
# Calm the radial/dim animations so the internal dim (a real RadialDimWidget) and
# the radial menu snap instead of starting QVariantAnimations during unit tests.
os.environ.setdefault("TTMT_NO_RADIAL_ANIM", "1")

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from utils.overlay.backend import NoOpOverlayBackend
from utils.overlay.card_metrics import CardMetrics
from utils.overlay.cluster_controller import ClusterOverlayController
from utils.overlay.cluster_geometry import envelope_for
from utils.overlay.cluster_surface import ClusterSurface
from utils.overlay.persistence import KEY_ANCHOR, KEY_MONITOR, KEY_SCALE
from utils.overlay.scale import SCALE_MAX, SCALE_MIN

# Deterministic scaling in tests: notches snap the rendered scale to the target
# synchronously instead of tweening it over the event loop.
os.environ.setdefault("TTMT_NO_OVERLAY_SCALE_ANIM", "1")


# Known cluster geometry baked into the stub provider so placement is exact.
_HOST_W, _HOST_H = 400, 300
# OFF-CENTER emblem so emblem_center_local (60+50, 40+50) = (110, 90) differs from
# the bbox center (200, 150) - this pins the emblem-center invariant and would
# catch a bbox-center regression.
_EMBLEM_X, _EMBLEM_Y, _EMBLEM_S = 60, 40, 100
_EMBLEM_CX = _EMBLEM_X + _EMBLEM_S // 2   # 110
_EMBLEM_CY = _EMBLEM_Y + _EMBLEM_S // 2   # 90

# The FIXED window envelope + pivot for that host/emblem (transform model): the
# window is sized to the SCALE_MAX bbox about the emblem center, and the emblem
# center sits on the PIVOT (window-local) at every scale.
_ENV_SIZE, _PIVOT = envelope_for(
    (_HOST_W, _HOST_H), (_EMBLEM_CX, _EMBLEM_CY), SCALE_MAX)


def _win_pt(hx, hy, scale=1.0):
    """Map a HOST-local (framed 1.0) point into WINDOW coords under the fixed-
    envelope transform: ``pivot + (host - emblem_center) * scale`` - the same
    math the controller's _map_host_rect / the surface's proxy transform use."""
    return (_PIVOT[0] + (hx - _EMBLEM_CX) * scale,
            _PIVOT[1] + (hy - _EMBLEM_CY) * scale)


# Four card cells parented under the grid host at known HOST-LOCAL origins
# (cells live in the grid host, exactly like the real _CompactLayout), each
# exposing two CARD-LOCAL control rects via control_rects() - matching the real
# _CompactLayout.control_rects(cell_index) -> list[QRect] signature. The exact
# input union translates each card-local control rect by its cell origin into
# host coords, then maps it through the transform into window-local coords.
_CELL_ORIGINS = {0: (10, 10), 1: (210, 10), 2: (10, 160), 3: (210, 160)}
_CELL_SIZE = (180, 130)
_CONTROL_RECTS_LOCAL = [QRect(8, 8, 30, 18), QRect(8, 40, 30, 18)]   # card-local
# Per-quadrant concave-carve corner, mirroring _compact_layout._CFG: the carve
# always faces the pinwheel center. The stub provider exposes it via each slot's
# "cfg" plus a CardMetrics(1.0) `_metrics` (cutout_r 96), so the controller
# builds the same cutout circles the real layout paints.
_CELL_CUTOUTS = {0: "br", 1: "bl", 2: "tr", 3: "tl"}

# A WINDOW-LOCAL point inside cell 1's first control (host rect (218,18,30,18),
# mapped through the scale-1.0 transform) but OUTSIDE the emblem - so an
# emblem-only union (the production card_cell_rects regression) would NOT
# contain it.
_CONTROL_PROBE = _win_pt(220, 20)
# A WINDOW-LOCAL point inside cell 0's first control (host rect (18,18,30,18),
# mapped) and OUTSIDE the emblem - the occupancy tests use it as the
# VISIBLE-card probe paired with _CONTROL_PROBE (cell 1) as the EMPTY-card probe.
_VISIBLE_CONTROL_PROBE = _win_pt(20, 20)


# ---------------------------------------------------------------------------
# Light stubs
# ---------------------------------------------------------------------------
class _NoopSignal:
    """Minimal signal stand-in for the PLAIN-object radial-menu stubs (the ones that
    avoid QObject to dodge the PySide6/3.14 GC flake): supports connect()/emit() as
    no-ops so open_radial_menu()'s ``menu.closing.connect(...)`` wiring works without
    a real QObject signal. QWidget-based stubs use a real ``Signal()`` instead."""

    def connect(self, *_a, **_k):
        pass

    def emit(self, *_a, **_k):
        pass


class _StubProvider:
    """Stand-in for _CompactLayout: a real `_grid_host` (parented under a holder,
    with a real off-center `_emblem` child) plus recording capture/restore/
    apply_metrics. capture DETACHES the host; restore RE-PARENTS it to the holder,
    so restoration is real and verifiable."""

    def __init__(self, capture_raises: bool = False):
        self._holder = QWidget()                      # stands in for the tab parent
        self._grid_host = QWidget(self._holder)
        self._grid_host.resize(_HOST_W, _HOST_H)
        self._emblem = QWidget(self._grid_host)
        self._emblem.setGeometry(_EMBLEM_X, _EMBLEM_Y, _EMBLEM_S, _EMBLEM_S)
        # Four card cells under the grid host at known origins (cells live in the
        # grid host, like the real _CompactLayout). control_rects() returns their
        # card-local control rects; the controller translates by each cell origin.
        self._cell_widgets = []
        for i in range(4):
            cw = QWidget(self._grid_host)
            ox, oy = _CELL_ORIGINS[i]
            cw.setGeometry(ox, oy, *_CELL_SIZE)
            self._cell_widgets.append(cw)
        self._token = object()
        self._metrics = CardMetrics(1.0)   # real metrics: cutout_r feeds the carve circles
        self.captured = 0
        self.restored: list = []
        self.last_metrics = None
        self.capture_raises = capture_raises
        self.restore_raises = False
        # Recording hooks for the cluster-local hover-peek / ghost-click port (T8).
        self.ghost_clicks: list = []      # (cell_index, x, y) from deliver_ghost_click
        self.shell_opacities: list = []   # (cell_index, bg, portrait) from the peek fade

    def capture_cluster_host(self):
        self.captured += 1
        if self.capture_raises:
            raise RuntimeError("capture boom")
        self._grid_host.setParent(None)               # detach (observable borrow)
        return self._token

    def restore_cluster_host(self, token):
        self.restored.append(token)
        if self.restore_raises:
            raise RuntimeError("restore boom")
        self._grid_host.setParent(self._holder)       # real restoration

    def apply_metrics(self, metrics):
        # Record-only: in the transform model the controller never re-lays-out the
        # host on a scale change; the ONLY apply_metrics call left is leave()'s
        # defensive framed (1.0) reset, which the leave tests assert via this.
        self.last_metrics = metrics

    @property
    def _card_slots(self):
        """Mirror _CompactLayout._card_slots: the list of cell dicts (each with a
        ``"cell"`` widget and its quadrant ``"cfg"``). The controller reads the
        cell origin from these to translate control_rects into window-local
        coords, and the cfg's carve corner to build the peek cutout circles."""
        return [{"cell": cw, "cfg": {"cutout": _CELL_CUTOUTS[i]}}
                for i, cw in enumerate(self._cell_widgets)]

    def control_rects(self, cell_index):
        """Mirror _CompactLayout.control_rects(cell_index) -> list[QRect]: the
        CARD-LOCAL rects of the cell's interactive controls."""
        return [QRect(r) for r in _CONTROL_RECTS_LOCAL]

    def deliver_ghost_click(self, cell_index, x, y):
        """Mirror _CompactLayout.deliver_ghost_click: record the cluster-local
        (cell-root-local) click coordinate the controller resolved."""
        self.ghost_clicks.append((cell_index, x, y))

    def set_shell_extra_opacity(self, cell_index, bg_opacity, portrait_opacity):
        """Mirror _CompactLayout.set_shell_extra_opacity: record the SAFE
        paint-time hover-peek translucency the controller pushed per shell."""
        self.shell_opacities.append(
            (cell_index, round(float(bg_opacity), 4), round(float(portrait_opacity), 4)))


class _StubWindow:
    """Records hide / showNormal / close; can be told to raise on hide."""

    def __init__(self):
        self.hidden = 0
        self.normaled = 0
        self.closed = 0
        self.hide_raises = False

    def hide(self):
        self.hidden += 1
        if self.hide_raises:
            raise RuntimeError("hide boom")

    def showNormal(self):
        self.normaled += 1

    def close(self):
        self.closed += 1


class _StubSurface(QWidget):
    """Recording surface exposing host/set_overlay_geometry/show/hide/release/
    deleteLater; host() actually re-parents so the borrow is observable. host()
    and release() can be made to raise to exercise the fail-closed / orphan paths."""

    def __init__(self, host_raises: bool = False, release_raises: bool = False):
        super().__init__()
        self.host_raises = host_raises
        self.release_raises = release_raises
        self.hosted = None
        self.geom = None
        self.shown = 0
        self.hidden = 0
        self.released = 0
        self.deleted = 0
        self.prepared = 0
        self.prepared_at_show = None      # value of self.prepared when show() ran

    def prepare_initial_state(self):
        self.prepared += 1

    def host(self, widget):
        if self.host_raises:
            raise RuntimeError("host boom")
        self.hosted = widget
        widget.setParent(self)

    def release(self):
        self.released += 1
        if self.release_raises:
            raise RuntimeError("release boom")
        w = self.hosted
        if w is not None:
            w.setParent(None)
            self.hosted = None
        return w

    def set_overlay_geometry(self, rect):
        self.geom = rect

    def show(self):
        self.prepared_at_show = self.prepared     # capture pre-map ordering
        self.shown += 1

    def hide(self):
        self.hidden += 1

    def deleteLater(self):
        self.deleted += 1


class _RecordingBackend(NoOpOverlayBackend):
    """NoOp backend that records every apply_input_shape call as
    (window, path, dpr) so the scaling tests can inspect the broad/exact shapes."""

    def __init__(self):
        self.shapes: list = []

    def apply_input_shape(self, window, path, dpr) -> None:
        self.shapes.append((window, path, dpr))


class _OccupancyStubProvider(QObject):
    """``_StubProvider`` analog that ALSO exposes occupancy: a controllable
    ``occupied_cells()`` plus a REAL ``occupied_cells_changed`` Signal (so it
    subclasses QObject, like the production ``_CompactLayout``). Cell widgets'
    ``setVisible`` is shadowed at the INSTANCE level so every hide is recorded
    WITH the cell's retain-size flag at hide time - the controller must set
    ``retainSizeWhenHidden`` BEFORE hiding, or the pinwheel grid would collapse.
    Instance shadowing (not a virtual override) catches only PYTHON-level calls, so
    Qt's own internal visibility changes are not mistaken for a controller hide."""

    occupied_cells_changed = Signal()

    def __init__(self, occupied=None):
        super().__init__()
        self._holder = QWidget()
        self._grid_host = QWidget(self._holder)
        self._grid_host.resize(_HOST_W, _HOST_H)
        self._emblem = QWidget(self._grid_host)
        self._emblem.setGeometry(_EMBLEM_X, _EMBLEM_Y, _EMBLEM_S, _EMBLEM_S)
        self.hidden_cells: list = []   # any cell that got setVisible(False)
        self._cell_widgets = []
        for i in range(4):
            cw = QWidget(self._grid_host)
            ox, oy = _CELL_ORIGINS[i]
            cw.setGeometry(ox, oy, *_CELL_SIZE)
            self._shadow_set_visible(cw)
            self._cell_widgets.append(cw)
        self._token = object()
        self.captured = 0
        self.restored: list = []
        self.last_metrics = None
        self._occupied = set(occupied if occupied is not None else {0, 1, 2, 3})
        # Recording hook for the hover-peek settle (a peeked card that drops out of
        # the visible set must be pushed back to fully opaque via this SAFE
        # paint-time hook - mirrors _StubProvider.set_shell_extra_opacity).
        self.shell_opacities: list = []

    def _shadow_set_visible(self, cw):
        original = cw.setVisible
        sink = self.hidden_cells

        def _spy(visible):
            if not visible:
                # Record the retain flag AT HIDE TIME: the controller must have
                # set retainSizeWhenHidden BEFORE the hide (no grid collapse).
                sink.append((cw, cw.sizePolicy().retainSizeWhenHidden()))
            original(visible)

        cw.setVisible = _spy

    def occupied_cells(self):
        return frozenset(self._occupied)

    def set_occupied(self, cells):
        self._occupied = set(cells)

    def capture_cluster_host(self):
        self.captured += 1
        self._grid_host.setParent(None)
        return self._token

    def restore_cluster_host(self, token):
        self.restored.append(token)
        self._grid_host.setParent(self._holder)

    def apply_metrics(self, metrics):
        self.last_metrics = metrics

    @property
    def _card_slots(self):
        return [{"cell": cw} for cw in self._cell_widgets]

    def control_rects(self, cell_index):
        return [QRect(r) for r in _CONTROL_RECTS_LOCAL]

    def deliver_ghost_click(self, cell_index, x, y):
        pass

    def set_shell_extra_opacity(self, cell_index, bg_opacity, portrait_opacity):
        self.shell_opacities.append(
            (cell_index, round(float(bg_opacity), 4), round(float(portrait_opacity), 4)))


def _make(provider=None, window=None, host_raises=False, release_raises=False,
          on_active_changed=None, anchor=None, backend=None, settings=None,
          dismiss_capture_factory=None):
    """Build a controller wired to recording stubs. Returns
    (controller, provider, window, created_surfaces)."""
    provider = provider if provider is not None else _StubProvider()
    window = window if window is not None else _StubWindow()
    created: list = []

    def factory():
        s = _StubSurface(host_raises=host_raises, release_raises=release_raises)
        created.append(s)
        return s

    ctrl = ClusterOverlayController(
        window,
        backend=backend if backend is not None else NoOpOverlayBackend(),
        settings=settings,
        surface_factory=factory,
        card_provider=provider,
        on_active_changed=on_active_changed,
        dismiss_capture_factory=dismiss_capture_factory,
    )
    if anchor is not None:
        ctrl._anchor = anchor   # inject a known anchor for exact placement
    return ctrl, provider, window, created


# ---------------------------------------------------------------------------
# 1. enter() borrows + hides + places at the EXACT emblem-centered rect
# ---------------------------------------------------------------------------
def test_enter_borrows_hides_and_places_emblem_on_anchor(qapp):
    events: list = []
    anchor = (1000, 700)
    ctrl, provider, window, created = _make(
        on_active_changed=events.append, anchor=anchor)

    ok = ctrl.enter()

    assert ok is True
    assert provider.captured == 1
    assert len(created) == 1
    surface = created[0]
    # The WHOLE grid_host is hosted into the single cluster surface.
    assert surface.hosted is provider._grid_host
    assert provider._grid_host.parent() is surface
    # EXACT placement: the window is the FIXED max-scale envelope, positioned so
    # the PIVOT (where the OFF-CENTER emblem center renders at every scale) lands
    # on the anchor (NOT the bbox center).
    ax, ay = anchor
    assert surface.geom == QRect(ax - _PIVOT[0], ay - _PIVOT[1], *_ENV_SIZE)
    assert surface.shown == 1
    assert window.hidden == 1
    assert ctrl.is_active is True
    assert events == [True]                 # on_active_changed(True) fired


def test_enter_prepares_state_then_applies_exact_click_through_shape(qapp):
    """enter() must (a) install the pre-map EWMH state BEFORE show() and (b) apply
    the EXACT emblem+controls input shape immediately, so the cluster is
    click-through the instant it appears - NOT left with X11's default full-rect
    input region that blocks clicks to the games until the first scale/occupancy/
    screen event heals it (the review's Important finding)."""
    backend = _RecordingBackend()
    ctrl, provider, window, created = _make(backend=backend)

    ok = ctrl.enter()
    assert ok is True
    surface = created[0]

    # (a) pre-map WM state installed BEFORE the window was mapped.
    assert surface.prepared_at_show == 1        # prepare_initial_state ran before show()
    assert surface.shown == 1

    # (b) exactly ONE shape applied to the CLUSTER surface on enter, and it is
    # the settled EXACT shape. The persistent radial/panel top-levels pre-mapped
    # by enter get their own EMPTY (fully click-through) shapes.
    assert ctrl._input_phase == "exact"
    cluster_shapes = [s for s in backend.shapes if s[0] is surface]
    assert len(cluster_shapes) == 1
    others = [s for s in backend.shapes if s[0] is not surface]
    assert len(others) == 2                       # persistent radial + panel
    assert all(p.isEmpty() for _w, p, _d in others)
    win, path, _dpr = cluster_shapes[0]
    assert win is surface
    # Solid over the emblem (its center renders on the PIVOT) + every visible
    # card's transform-mapped controls (click-catching)...
    assert path.contains(QPointF(*_PIVOT))
    assert path.contains(QPointF(*_VISIBLE_CONTROL_PROBE))   # cell 0 control
    assert path.contains(QPointF(*_CONTROL_PROBE))           # cell 1 control
    # ...but CLICK-THROUGH over a gap (a cell interior away from its controls and
    # the emblem): the shape is the exact union, not the full window rect.
    assert not path.contains(QPointF(*_win_pt(380, 280)))


# ---------------------------------------------------------------------------
# 2. leave() restores (before delete) + resets metrics
# ---------------------------------------------------------------------------
def test_leave_restores_before_delete_and_resets_metrics(qapp):
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
    # The host was released + restored to the holder BEFORE the surface was torn
    # down: its parent is the holder, NOT the (deleted) surface.
    assert provider._grid_host.parent() is provider._holder
    # Surface torn down.
    assert surface.hidden == 1
    assert surface.deleted == 1
    assert window.normaled == 1
    assert ctrl.is_active is False
    assert events == [False]                # on_active_changed(False) fired


# ---------------------------------------------------------------------------
# 3. enter/leave no-ops + clean re-cycle
# ---------------------------------------------------------------------------
def test_enter_while_active_is_noop(qapp):
    ctrl, provider, window, created = _make()
    ctrl.enter()
    assert provider.captured == 1

    again = ctrl.enter()

    assert again is True
    assert provider.captured == 1           # no second capture
    assert len(created) == 1                # no second surface
    assert window.hidden == 1            # not hidden again


def test_leave_while_inactive_is_noop(qapp):
    ctrl, provider, window, created = _make()
    ctrl.leave()                            # never entered
    assert provider.restored == []
    assert window.normaled == 0
    assert ctrl.is_active is False


def test_enter_leave_enter_recycles_cleanly(qapp):
    """enter -> leave -> enter again borrows fresh (state reset between cycles)."""
    ctrl, provider, window, created = _make()

    assert ctrl.enter() is True
    ctrl.leave()
    assert ctrl.is_active is False
    assert ctrl._surface is None and ctrl._token is None

    assert ctrl.enter() is True
    assert ctrl.is_active is True
    assert provider.captured == 2           # captured fresh on the second enter
    assert len(created) == 2                # a brand-new surface
    assert provider._grid_host.parent() is created[1]
    assert window.hidden == 2
    assert ctrl._orphans == []              # nothing orphaned across clean cycles


# ---------------------------------------------------------------------------
# 4. FAIL-CLOSED enter
# ---------------------------------------------------------------------------
def test_enter_failclosed_on_capture_raise(qapp):
    """capture raises (before hide): no exception escapes, stays framed,
    the window is never hidden (so never left hidden)."""
    provider = _StubProvider(capture_raises=True)
    ctrl, provider, window, created = _make(provider=provider)

    ok = ctrl.enter()

    assert ok is False
    assert ctrl.is_active is False
    assert window.hidden == 0            # never hidden -> no showNormal needed
    # A surface was built before capture; it was torn down (release ok -> deleted).
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
    assert provider._grid_host.parent() is provider._holder
    assert created[0].deleted == 1
    assert window.hidden == 0


def test_enter_failclosed_on_hide_raise(qapp):
    """hide() raises (after show): the window is restored via showNormal, the
    quit guard is restored, and the controller stays framed."""
    prev = qapp.quitOnLastWindowClosed()
    try:
        qapp.setQuitOnLastWindowClosed(True)
        ctrl, provider, window, created = _make()
        window.hide_raises = True
        ok = ctrl.enter()
        assert ok is False
        assert ctrl.is_active is False
        assert window.hidden == 1
        assert window.normaled == 1             # restored after the mid-enter failure
        assert qapp.quitOnLastWindowClosed() is True
        assert provider.restored == [provider._token]
        assert provider._grid_host.parent() is provider._holder
        assert created[0].deleted == 1
    finally:
        qapp.setQuitOnLastWindowClosed(prev)


# ---------------------------------------------------------------------------
# Quit guard + teardown ordering (float owns the taskbar; main window HIDDEN)
# ---------------------------------------------------------------------------
def test_enter_sets_quit_guard_and_leave_restores_it(qapp):
    """While active the main window is HIDDEN (no taskbar entry to restore the
    gutted window UI from), so quit-on-last-window-closed must be OFF - a
    mid-float window close would otherwise quit the app. leave() restores the
    value captured at enter."""
    prev = qapp.quitOnLastWindowClosed()
    try:
        qapp.setQuitOnLastWindowClosed(True)
        ctrl, provider, window, created = _make()
        assert ctrl.enter() is True
        assert qapp.quitOnLastWindowClosed() is False
        ctrl.leave()
        assert qapp.quitOnLastWindowClosed() is True
    finally:
        qapp.setQuitOnLastWindowClosed(prev)


def test_quit_guard_restores_the_captured_value_not_hardcoded_true(qapp):
    prev = qapp.quitOnLastWindowClosed()
    try:
        qapp.setQuitOnLastWindowClosed(False)
        ctrl, provider, window, created = _make()
        ctrl.enter()
        ctrl.leave()
        assert qapp.quitOnLastWindowClosed() is False
    finally:
        qapp.setQuitOnLastWindowClosed(prev)


def test_leave_reshows_window_before_surface_teardown(qapp):
    """ORDERING PIN: with the main window hidden, destroying the last visible
    window posts the app quit - so leave() must re-show the main window while
    the cluster surface is still mapped (the host is already restored at that
    point, so the shown window is complete - no gutted flash)."""
    order: list = []
    ctrl, provider, window, created = _make()
    ctrl.enter()
    surface = created[0]
    real_restore = provider.restore_cluster_host

    def _recording_restore(token):
        order.append("host_restored")
        return real_restore(token)

    provider.restore_cluster_host = _recording_restore
    window.showNormal = lambda: order.append("window_shown")
    surface.hide = lambda: order.append("surface_hidden")
    surface.deleteLater = lambda: order.append("surface_deleted")
    ctrl.leave()
    assert "window_shown" in order
    # Host back in the tab BEFORE the window is shown (complete, no gutted flash)...
    assert order.index("host_restored") < order.index("window_shown")
    # ...and the window shown BEFORE the surface teardown (never zero visible windows).
    assert order.index("window_shown") < order.index("surface_hidden")
    assert order.index("window_shown") < order.index("surface_deleted")


def test_leave_failclosed_when_teardown_step_raises(qapp):
    """FAIL-CLOSED PIN: a raising teardown step (here the settings save flush,
    the first step of leave()) must never strand the app - leave() swallows it,
    restores the borrowed host to the tab, re-shows the main window, restores
    the quit guard, deletes the surface, and lands framed. No exit from leave()
    may leave the host un-restored, the main window hidden, or the guard off."""
    prev = qapp.quitOnLastWindowClosed()
    try:
        qapp.setQuitOnLastWindowClosed(True)
        ctrl, provider, window, created = _make()
        assert ctrl.enter() is True
        surface = created[0]

        def _boom():
            raise RuntimeError("flush boom")

        ctrl.flush_pending_save = _boom
        ctrl.leave()                            # must not raise
        assert window.normaled == 1
        assert qapp.quitOnLastWindowClosed() is True
        assert ctrl.is_active is False
        assert surface.deleted == 1
        # The borrowed host must return to the tab on EVERY path - a skipped
        # restore would leave it PARENTLESS (the surface release orphans it,
        # bypassing the _orphans net) and the re-shown main window gutted.
        assert provider.restored == [provider._token]
        assert provider._grid_host.parent() is provider._holder
    finally:
        qapp.setQuitOnLastWindowClosed(prev)


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


# ---------------------------------------------------------------------------
# 6. CRITICAL: release() raises -> surface is ORPHANED, never destroyed
# ---------------------------------------------------------------------------
def test_leave_orphans_surface_when_release_raises(qapp):
    """If release() raises (surface may still host the live cluster subtree) AND
    the host can't be re-parented out, the surface must be RETAINED as an orphan
    and NEVER deleteLater'd - so the borrowed cards/emblem/glow are never
    destroyed. The window is still restored and the controller goes framed."""
    ctrl, provider, window, created = _make(release_raises=True)
    ctrl.enter()
    surface = created[0]
    # Make restore a no-op re-parent too, so the host stays inside the surface.
    provider.restore_raises = True
    provider.restored.clear()

    ctrl.leave()                            # must not raise

    # Surface retained as an orphan, NOT destroyed.
    assert surface.deleted == 0
    assert surface in ctrl._orphans
    # release() raised -> restore was skipped -> the host is still hosted (ALIVE)
    # inside the retained surface, never deleted.
    assert provider._grid_host.parent() is surface
    assert provider.restored == []          # restore skipped (release failed)
    # The window is still restored and the controller is framed.
    assert window.normaled == 1
    assert ctrl.is_active is False


# ---------------------------------------------------------------------------
# 7. Single-window scaling: clamp, broad/exact input-shape timing, drag lockout
# ---------------------------------------------------------------------------
def test_set_scale_by_notches_clamps_to_range(qapp):
    """A big notch burst clamps to SCALE_MAX; a big negative burst to SCALE_MIN."""
    ctrl, provider, window, created = _make()
    ctrl.enter()

    ctrl.set_scale_by_notches(100)
    assert ctrl.scale == SCALE_MAX

    ctrl.set_scale_by_notches(-100)
    assert ctrl.scale == SCALE_MIN


def test_set_scale_by_notches_noop_when_inactive(qapp):
    """No surface, no metrics, no shape applied while framed."""
    backend = _RecordingBackend()
    ctrl, provider, window, created = _make(backend=backend)

    ctrl.set_scale_by_notches(1)

    assert ctrl.scale == 1.0
    assert provider.last_metrics is None
    assert backend.shapes == []
    assert ctrl._scaling_active is False


def test_notch_keeps_window_geometry_and_applies_broad_shape(qapp):
    """One notch: the window geometry does NOT change (the fixed max-scale
    envelope - the judder fix: nothing for the compositor to mis-order), the host
    is NOT re-laid-out (no apply_metrics - the non-uniformity fix), the rendered
    scale tracks the target, and one BROAD (full-window-rect) input shape is
    applied; scaling-active in 'broad'."""
    backend = _RecordingBackend()
    ctrl, provider, window, created = _make(backend=backend)
    ctrl.enter()
    surface = created[0]
    geom_before = QRect(surface.geom)
    backend.shapes.clear()                       # ignore any enter-time shaping

    ctrl.set_scale_by_notches(1)

    # Transform-only: no re-layout, no resize, no move.
    assert provider.last_metrics is None
    assert surface.geom == geom_before
    assert ctrl._view_scale == ctrl.scale        # rendered scale tracked the target
    # Broad phase: scaling active, one broad apply of the FULL window-local rect.
    assert ctrl._scaling_active is True
    assert ctrl._input_phase == "broad"
    assert len(backend.shapes) == 1
    win, broad_path, _dpr = backend.shapes[0]
    assert win is surface
    assert broad_path.boundingRect().toRect() == QRect(
        0, 0, surface.geom.width(), surface.geom.height())


def test_scale_burst_and_settle_never_touch_window_geometry(qapp):
    """The load-bearing fixed-envelope invariant: an entire scroll burst (up and
    down) plus the settle leaves the window geometry BIT-IDENTICAL to enter's.
    Any regression that reintroduces a per-notch resize/move (the XWayland judder)
    fails here."""
    ctrl, provider, window, created = _make()
    ctrl.enter()
    surface = created[0]
    geom_at_enter = QRect(surface.geom)

    for notches in (1, 1, 1, -2, 3, -1):
        ctrl.set_scale_by_notches(notches)
        assert surface.geom == geom_at_enter
    ctrl._settle_input()

    assert surface.geom == geom_at_enter
    assert ctrl._view_scale == ctrl.scale
    ctrl.leave()


def test_settle_applies_exact_shape_and_clears_scaling(qapp):
    """_settle_input(): scaling clears, phase -> 'exact', a SECOND (different)
    input shape is applied (the precise emblem+controls union, not the full rect)."""
    backend = _RecordingBackend()
    ctrl, provider, window, created = _make(backend=backend)
    ctrl.enter()
    surface = created[0]
    backend.shapes.clear()                       # ignore the enter-time exact shape
    ctrl.set_scale_by_notches(1)
    assert len(backend.shapes) == 1
    broad_path = backend.shapes[-1][1]

    ctrl._settle_input()

    assert ctrl._scaling_active is False
    assert ctrl._input_phase == "exact"
    assert len(backend.shapes) == 2              # broad, then exact
    win, exact_path, _dpr = backend.shapes[-1]
    assert win is surface
    # The exact shape differs from the broad full-window shape.
    assert (exact_path.boundingRect().toRect()
            != broad_path.boundingRect().toRect())
    # The exact union must CONTAIN a real (transform-mapped) card control - a
    # point inside a control but outside the emblem, mapped at the SETTLED scale
    # (a notch was scrolled above). An emblem-only union (the production
    # card_cell_rects regression, where the real provider lacks that method)
    # would NOT contain it.
    from PySide6.QtCore import QPointF
    assert exact_path.contains(QPointF(*_win_pt(220, 20, ctrl.scale)))


def test_settle_input_post_leave_is_true_noop(qapp):
    """A stray settle timeout AFTER leave() must not apply a shape or flip the
    framed phase from None to 'exact' (the guard runs before the phase assign)."""
    backend = _RecordingBackend()
    ctrl, provider, window, created = _make(backend=backend)
    ctrl.enter()
    ctrl.set_scale_by_notches(1)
    ctrl.leave()                                 # framed; phase reset to None
    backend.shapes.clear()

    ctrl._settle_input()                          # stray late timeout

    assert ctrl._input_phase is None              # NOT flipped to "exact"
    assert backend.shapes == []                    # no shape applied to a dead surface


def test_enter_measures_emblem_after_fixing_host_size(qapp):
    """REGRESSION (live: radial ring off-center from the emblem): framed mode
    STRETCHES the host past its sizeHint and centers the emblem on that live
    size. enter() must fix the host at its 1.0 hint, activate the layout, and
    re-assert the provider's own emblem placement BEFORE measuring the pivot -
    so the measured center is the SETTLED one, and any later provider relayout
    (_position_emblem via apply_cell_permutation) lands on the same point,
    keeping the emblem exactly on the pivot (where the radial ring centers)."""

    class _Host(QWidget):
        def sizeHint(self):
            from PySide6.QtCore import QSize
            return QSize(_HOST_W, _HOST_H)

    class _Provider:
        def __init__(self):
            self._holder = QWidget()
            self._grid_host = _Host(self._holder)
            self._grid_host.resize(600, 500)          # framed live stretch > hint
            self._emblem = QWidget(self._grid_host)
            self._emblem.setFixedSize(100, 100)
            self._position_emblem()                    # centered on the LIVE size
            self._token = object()

        def _position_emblem(self):
            # Mirror _CompactLayout._position_emblem: center on the CURRENT size.
            gh, e = self._grid_host, self._emblem
            e.move(int(gh.width() / 2 - e.width() / 2),
                   int(gh.height() / 2 - e.height() / 2))

        def capture_cluster_host(self):
            self._grid_host.setParent(None)
            return self._token

        def restore_cluster_host(self, token):
            self._grid_host.setParent(self._holder)

        def apply_metrics(self, metrics):
            pass

    provider = _Provider()
    g = provider._emblem.geometry()
    assert (g.x() + 50, g.y() + 50) == (300, 250)      # on the STRETCHED center

    ctrl, provider, window, created = _make(provider=provider)
    assert ctrl.enter() is True

    # Host fixed at its 1.0 hint; the emblem re-centered BEFORE the pivot measure.
    assert (provider._grid_host.width(), provider._grid_host.height()) == (
        _HOST_W, _HOST_H)
    assert ctrl._emblem_center == (_HOST_W // 2, _HOST_H // 2)
    # The mapped emblem rect centers on the pivot (= where the radial centers).
    er = ctrl._emblem_rect()
    px, py = ctrl._pivot
    assert abs(er.x() + er.width() / 2 - px) <= 1.0
    assert abs(er.y() + er.height() / 2 - py) <= 1.0

    # A LATER provider relayout must not move the emblem off the pivot: with the
    # size fixed, _position_emblem is idempotent.
    provider._position_emblem()
    assert ctrl._emblem_rect() == er
    ctrl.leave()


def test_notch_keeps_emblem_center_on_anchor(qapp):
    """The scaling anchor invariant: after a notch the transform-MAPPED emblem
    rect still centers on the anchor - the window never moved (pivot on anchor)
    and the transform pins the emblem center on the pivot at every scale."""
    anchor = (1234, 567)
    ctrl, provider, window, created = _make(anchor=anchor)
    ctrl.enter()
    surface = created[0]

    ctrl.set_scale_by_notches(1)

    # The window itself did not move: the pivot sits exactly on the anchor.
    assert (surface.geom.x() + _PIVOT[0], surface.geom.y() + _PIVOT[1]) == anchor
    # The mapped emblem rect centers on the pivot (outward edge rounding may
    # shift the integer center by at most 1px).
    er = ctrl._emblem_rect()
    assert abs(surface.geom.x() + er.x() + er.width() / 2 - anchor[0]) <= 1.0
    assert abs(surface.geom.y() + er.y() + er.height() / 2 - anchor[1]) <= 1.0


def test_move_group_locked_out_during_scale_then_allowed_after_settle(qapp):
    """Drag is LOCKED OUT (returns False, no move) while a scale gesture is live;
    after settle it returns True and moves the window."""
    ctrl, provider, window, created = _make()
    ctrl.enter()
    surface = created[0]

    ctrl.set_scale_by_notches(1)
    assert ctrl._scaling_active is True
    geom_during = surface.geom
    assert ctrl.move_group(10, 10) is False      # locked out mid-gesture
    assert surface.geom == geom_during           # window did NOT move

    ctrl._settle_input()
    geom_after_settle = surface.geom
    assert ctrl.move_group(10, 10) is True        # gesture settled -> drag allowed
    assert surface.geom != geom_after_settle     # window moved


def test_move_group_noop_when_inactive(qapp):
    """move_group is a no-op (False) when the controller is framed."""
    ctrl, provider, window, created = _make()
    assert ctrl.move_group(10, 10) is False


def test_move_group_clamp_reconciles_anchor_no_dead_zone(qapp):
    """At the envelope edge the anchor is reconciled to the CLAMPED rect, so:
    a further push the SAME way is a pinned no-op (False, no visual move), and a
    push back the OPPOSITE way moves IMMEDIATELY (no accumulated dead zone)."""
    ctrl, provider, window, created = _make(anchor=(700, 400))  # on the 800x800 screen
    ctrl.enter()
    surface = created[0]
    big = 5000   # far past the right envelope edge

    # First push past the edge: clamps to the boundary and actually moves.
    assert ctrl.move_group(big, 0) is True
    pinned_geom = surface.geom

    # Push further the SAME way: already pinned -> no visual move -> False.
    assert ctrl.move_group(big, 0) is False
    assert surface.geom == pinned_geom

    # Push back the OPPOSITE way by the same delta: moves immediately (no dead
    # zone). With a raw-accumulated anchor this would still be pinned (False).
    assert ctrl.move_group(-big, 0) is True
    assert surface.geom != pinned_geom
    assert surface.geom.x() < pinned_geom.x()    # moved back to the left


# ---------------------------------------------------------------------------
# 8. Occupancy: filters the exact input union, keeps the grid shell fixed
#    (no card hide, no window reshape)
# ---------------------------------------------------------------------------
def test_enter_initializes_visible_cells_from_occupancy(qapp):
    """enter() seeds _visible_cells from the provider's occupied_cells()."""
    provider = _OccupancyStubProvider(occupied={0, 2})
    ctrl, provider, window, created = _make(provider=provider)

    ctrl.enter()

    assert ctrl._visible_cells == {0, 2}


def test_exact_union_includes_visible_excludes_empty(qapp):
    """With occupancy {0,2}, the EXACT input union (after _settle_input) CONTAINS a
    control point of a visible card (cell 0) and EXCLUDES one of an empty card
    (cell 1) - empty cards drop OUT of the click region."""
    backend = _RecordingBackend()
    provider = _OccupancyStubProvider(occupied={0, 2})
    ctrl, provider, window, created = _make(provider=provider, backend=backend)
    ctrl.enter()

    ctrl._settle_input()

    exact_path = backend.shapes[-1][1]
    assert exact_path.contains(QPointF(*_VISIBLE_CONTROL_PROBE))   # cell 0 visible
    assert not exact_path.contains(QPointF(*_CONTROL_PROBE))        # cell 1 empty


def test_occupancy_change_updates_cell_visibility_and_input_without_reshaping(qapp):
    """An occupancy nudge re-reads occupied_cells, updates _visible_cells,
    hides/shows the cells to match (0 toons -> 0 cards), and RE-APPLIES the input
    shape (a new apply) - WITHOUT resizing/reshaping the window (fixed envelope)
    and with retainSizeWhenHidden set BEFORE every hide (no pinwheel collapse)."""
    backend = _RecordingBackend()
    provider = _OccupancyStubProvider(occupied={0, 2})
    ctrl, provider, window, created = _make(provider=provider, backend=backend)
    ctrl.enter()
    surface = created[0]
    geom_before = surface.geom
    # enter() hid exactly the EMPTY cells (1, 3), each with retain already set.
    assert [c for c, _r in provider.hidden_cells] == [
        provider._cell_widgets[1], provider._cell_widgets[3]]
    assert all(retained for _c, retained in provider.hidden_cells)
    assert not provider._cell_widgets[0].isHidden()
    assert provider._cell_widgets[1].isHidden()
    provider.hidden_cells.clear()
    backend.shapes.clear()

    provider.set_occupied({1, 3})
    provider.occupied_cells_changed.emit()

    assert ctrl._visible_cells == {1, 3}
    assert len(backend.shapes) >= 1              # input shape RE-APPLIED
    assert surface.geom == geom_before           # window NOT resized/reshaped
    # Visibility flipped to the new occupancy: 0, 2 hidden (retain set), 1, 3 shown.
    assert {c for c, _r in provider.hidden_cells} == {
        provider._cell_widgets[0], provider._cell_widgets[2]}
    assert all(retained for _c, retained in provider.hidden_cells)
    assert not provider._cell_widgets[1].isHidden()
    assert provider._cell_widgets[0].isHidden()
    # The new union now blocks the newly-occupied cell 1 and frees the now-empty 0.
    new_path = backend.shapes[-1][1]
    assert new_path.contains(QPointF(*_CONTROL_PROBE))                # cell 1 visible
    assert not new_path.contains(QPointF(*_VISIBLE_CONTROL_PROBE))    # cell 0 empty


def test_leave_restores_all_cells_visible_with_original_retain_flags(qapp):
    """leave() must un-hide every cell (framed mode always shows all four shells)
    and restore each cell's ORIGINAL retainSizeWhenHidden flag (False here), so
    the borrowed host returns to the tab exactly as captured."""
    provider = _OccupancyStubProvider(occupied={2})
    ctrl, provider, window, created = _make(provider=provider)
    ctrl.enter()
    assert provider._cell_widgets[0].isHidden()          # empty cells hidden
    assert not provider._cell_widgets[2].isHidden()      # occupied cell shown
    assert provider._cell_widgets[0].sizePolicy().retainSizeWhenHidden()

    ctrl.leave()

    for cw in provider._cell_widgets:
        assert not cw.isHidden()                          # all shells visible again
        assert cw.sizePolicy().retainSizeWhenHidden() is False   # flag restored
    assert ctrl._cell_retain_flags == {}                  # bookkeeping cleared


def test_leave_disconnects_occupancy_signal(qapp):
    """leave() disconnects the occupancy signal: a post-leave emit does not raise
    and does not change state; _visible_cells resets to the framed default."""
    backend = _RecordingBackend()
    provider = _OccupancyStubProvider(occupied={0, 2})
    ctrl, provider, window, created = _make(provider=provider, backend=backend)
    ctrl.enter()

    ctrl.leave()

    assert ctrl._occupancy_connected is False
    assert ctrl._visible_cells == {0, 1, 2, 3}   # reset to the framed default
    backend.shapes.clear()

    provider.set_occupied({1, 3})
    provider.occupied_cells_changed.emit()        # must be a safe no-op

    assert ctrl.is_active is False
    assert backend.shapes == []                    # nothing re-applied post-leave
    assert ctrl._visible_cells == {0, 1, 2, 3}     # unchanged by the stray emit


def test_provider_without_occupancy_degrades_to_all_visible(qapp):
    """A provider lacking occupied_cells degrades to all-visible and enter() runs
    without crashing."""
    ctrl, provider, window, created = _make()      # _StubProvider has NO occupancy

    assert ctrl.enter() is True
    assert ctrl._visible_cells == {0, 1, 2, 3}


def test_set_cards_hidden_hides_all_cells_and_frees_input(qapp):
    """The user Hide-Cards toggle (radial spoke) hides EVERY cell - occupied or
    not - via the same reconcile path as occupancy: retain-size set before each
    hide (no grid reflow), the window NOT resized (fixed envelope), and the
    exact input shape re-applied so the hidden cards click through. Toggling
    back re-reads occupancy and restores exactly the occupied cells."""
    backend = _RecordingBackend()
    provider = _OccupancyStubProvider(occupied={0, 2})
    ctrl, provider, window, created = _make(provider=provider, backend=backend)
    ctrl.enter()
    surface = created[0]
    geom_before = surface.geom
    assert ctrl.cards_hidden is False
    assert not provider._cell_widgets[0].isHidden()   # occupied cell visible
    provider.hidden_cells.clear()
    backend.shapes.clear()

    ctrl.set_cards_hidden(True)

    assert ctrl.cards_hidden is True
    assert ctrl._visible_cells == set()
    for cw in provider._cell_widgets:
        assert cw.isHidden()                          # ALL cells hidden
    assert all(retained for _c, retained in provider.hidden_cells)
    assert surface.geom == geom_before                # window NOT resized
    assert len(backend.shapes) >= 1                   # input shape RE-APPLIED
    path = backend.shapes[-1][1]
    assert not path.contains(QPointF(*_VISIBLE_CONTROL_PROBE))   # card freed
    backend.shapes.clear()

    ctrl.set_cards_hidden(False)

    assert ctrl.cards_hidden is False
    assert ctrl._visible_cells == {0, 2}              # back to occupancy
    assert not provider._cell_widgets[0].isHidden()
    assert provider._cell_widgets[1].isHidden()       # empty cell stays hidden
    assert backend.shapes[-1][1].contains(QPointF(*_VISIBLE_CONTROL_PROBE))


def test_occupancy_churn_while_cards_hidden_stays_hidden(qapp):
    """Occupancy changes while the Hide-Cards toggle is on must NOT re-show any
    card (the toggle overrides occupancy); toggling off then shows the
    THEN-CURRENT occupancy, not the stale one from before the hide."""
    provider = _OccupancyStubProvider(occupied={0, 2})
    ctrl, provider, window, created = _make(provider=provider)
    ctrl.enter()
    ctrl.set_cards_hidden(True)

    provider.set_occupied({1, 3})
    provider.occupied_cells_changed.emit()

    assert ctrl._visible_cells == set()               # still all hidden
    for cw in provider._cell_widgets:
        assert cw.isHidden()

    ctrl.set_cards_hidden(False)

    assert ctrl._visible_cells == {1, 3}              # the CURRENT occupancy
    assert provider._cell_widgets[1].isHidden() is False
    assert provider._cell_widgets[0].isHidden()


def test_leave_resets_cards_hidden_and_ignored_while_framed(qapp):
    """leave() resets the Hide-Cards toggle (a float session never STARTS with
    invisible cards) and set_cards_hidden while framed is ignored, so a stray
    framed-mode call can never poison the next enter()'s visible-cells seed."""
    provider = _OccupancyStubProvider(occupied={0, 2})
    ctrl, provider, window, created = _make(provider=provider)
    ctrl.enter()
    ctrl.set_cards_hidden(True)
    assert ctrl.cards_hidden is True

    ctrl.leave()

    assert ctrl.cards_hidden is False
    for cw in provider._cell_widgets:
        assert not cw.isHidden()                      # framed shows all four

    ctrl.set_cards_hidden(True)                       # framed: ignored
    assert ctrl.cards_hidden is False

    ctrl.enter()
    assert ctrl._visible_cells == {0, 2}              # seeded from occupancy
    ctrl.leave()


def test_toggle_cards_hidden_flips_and_returns_state(qapp):
    provider = _OccupancyStubProvider(occupied={0, 2})
    ctrl, provider, window, created = _make(provider=provider)
    ctrl.enter()

    assert ctrl.toggle_cards_hidden() is True
    assert ctrl._visible_cells == set()
    assert ctrl.toggle_cards_hidden() is False
    assert ctrl._visible_cells == {0, 2}
    ctrl.leave()


def test_occupancy_change_during_scale_defers_exact_until_settle(qapp):
    """An occupancy nudge that arrives DURING an active scale (BROAD phase) updates
    _visible_cells but must NOT swap in the narrow exact shape mid-gesture (that
    would shrink the wheel-capture region under the pointer and stall the stream).
    The re-armed settle timer replays the exact shape with the fresh visible set on
    quiesce."""
    backend = _RecordingBackend()
    provider = _OccupancyStubProvider(occupied={0, 2})
    ctrl, provider, window, created = _make(provider=provider, backend=backend)
    ctrl.enter()
    surface = created[0]

    ctrl.set_scale_by_notches(1)                  # BROAD phase: full-window shape up
    assert ctrl._scaling_active is True
    shapes_after_notch = len(backend.shapes)
    broad_path = backend.shapes[-1][1]
    # The broad shape is the FULL window rect -> it contains EVERY cell point.
    assert broad_path.boundingRect().toRect() == QRect(
        0, 0, surface.geom.width(), surface.geom.height())

    provider.set_occupied({0})                    # cells 1, 2, 3 now empty
    provider.occupied_cells_changed.emit()

    # (a) The visible set is refreshed immediately ...
    assert ctrl._visible_cells == {0}
    # (b) ... but NO new shape was applied mid-gesture: the last applied shape is
    # STILL the broad full-window one (it still contains an EMPTY cell's point - an
    # exact shape for {0} would have narrowed it out).
    assert len(backend.shapes) == shapes_after_notch
    assert backend.shapes[-1][1].contains(QPointF(*_CONTROL_PROBE))   # cell 1 still in

    # (c) On settle the exact shape replays with the NEW visible set: cell 0 in,
    # cell 1 (now empty) out. Probes are mapped at the SETTLED scale (the exact
    # union is transform-mapped, and the scale changed with the notch above).
    ctrl._settle_input()
    exact_path = backend.shapes[-1][1]
    assert exact_path.contains(QPointF(*_win_pt(20, 20, ctrl.scale)))       # cell 0 visible
    assert not exact_path.contains(QPointF(*_win_pt(220, 20, ctrl.scale)))  # cell 1 empty


def test_connect_occupancy_is_idempotent(qapp):
    """A second _connect_occupancy() while already connected must NOT add a
    duplicate Qt connection (else the slot fires twice per nudge). One emit -> one
    reconcile -> exactly one input-shape apply."""
    backend = _RecordingBackend()
    provider = _OccupancyStubProvider(occupied={0, 2})
    ctrl, provider, window, created = _make(provider=provider, backend=backend)
    ctrl.enter()
    ctrl._connect_occupancy()                     # second call: must be a no-op
    backend.shapes.clear()

    provider.occupied_cells_changed.emit()

    assert len(backend.shapes) == 1              # reconcile fired exactly once


# ---------------------------------------------------------------------------
# 9. Persistence: load anchor+scale on enter, debounced save, flush on leave
# ---------------------------------------------------------------------------
class _DictSettings:
    """Mirror tests/test_overlay_persistence.py's stub: a dict-backed settings
    object the pure persistence helpers read/write via get()/set()."""

    def __init__(self, d=None):
        self._d = dict(d or {})

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value):
        self._d[key] = value


class _CountingSettings(_DictSettings):
    """A _DictSettings that counts each FULL save (one per KEY_ANCHOR write), so a
    test can assert a debounced save was written exactly once."""

    def __init__(self, d=None):
        super().__init__(d)
        self.saves = 0

    def set(self, key, value):
        if key == KEY_ANCHOR:
            self.saves += 1
        super().set(key, value)


def test_enter_restores_saved_scale_and_anchor(qapp):
    """enter() with a SAVED scale+anchor adopts the saved scale and the saved
    (clamped) anchor. The window is the FIXED max-scale envelope regardless of the
    restored scale (the transform renders the zoom - no apply_metrics re-layout),
    with the pivot on the anchor so the emblem center lands there."""
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    name = screen.name()
    g = screen.geometry()
    inside = (g.left() + 120, g.top() + 120)   # well inside -> clamp keeps it
    s = _DictSettings({KEY_ANCHOR: list(inside), KEY_SCALE: 1.5, KEY_MONITOR: name})

    ctrl, provider, window, created = _make(settings=s)
    assert ctrl.enter() is True

    assert ctrl._scale == 1.5
    assert ctrl._view_scale == 1.5              # rendered at the restored scale
    assert ctrl._anchor == inside
    assert provider.last_metrics is None        # transform, never a re-layout
    surface = created[0]
    # Fixed envelope, independent of the restored scale; pivot on the anchor.
    assert (surface.geom.width(), surface.geom.height()) == _ENV_SIZE
    assert surface.geom.x() + _PIVOT[0] == inside[0]
    assert surface.geom.y() + _PIVOT[1] == inside[1]
    # The mapped (scale-1.5) emblem rect still centers on the saved anchor.
    er = ctrl._emblem_rect()
    assert abs(surface.geom.x() + er.x() + er.width() / 2 - inside[0]) <= 1.0
    assert abs(surface.geom.y() + er.y() + er.height() / 2 - inside[1]) <= 1.0
    ctrl.leave()


def test_enter_with_no_saved_state_uses_defaults(qapp):
    """enter() with empty settings keeps scale 1.0 + the default anchor (no crash,
    current default behavior preserved)."""
    s = _DictSettings()
    ctrl, provider, window, created = _make(settings=s)

    assert ctrl.enter() is True

    assert ctrl._scale == 1.0
    assert ctrl._anchor == ClusterOverlayController._default_anchor()
    ctrl.leave()


def test_scale_change_schedules_debounced_save_of_current_state(qapp):
    """set_scale_by_notches() schedules a debounced save; firing _run_pending_save()
    writes the CURRENT scale (+ anchor + monitor)."""
    s = _DictSettings()
    ctrl, provider, window, created = _make(settings=s)
    ctrl.enter()

    ctrl.set_scale_by_notches(-2)
    assert ctrl._save_pending is True            # debounced (not yet written)
    assert s.get(KEY_SCALE) is None              # nothing flushed yet

    ctrl._run_pending_save()

    assert ctrl._save_pending is False
    assert s.get(KEY_SCALE) == ctrl._scale
    assert s.get(KEY_ANCHOR) == [ctrl._anchor[0], ctrl._anchor[1]]
    assert s.get(KEY_MONITOR) is not None         # the (offscreen) screen the anchor sits on
    ctrl.leave()


def test_move_schedules_save_with_clamped_anchor(qapp):
    """A real move_group() schedules a save; the saved anchor reflects the moved
    (clamped/reconciled) anchor, not the raw accumulated target."""
    s = _DictSettings()
    ctrl, provider, window, created = _make(settings=s, anchor=(700, 400))
    ctrl.enter()

    assert ctrl.move_group(5000, 0) is True       # slam far past the right edge -> clamped
    assert ctrl._save_pending is True

    ctrl._run_pending_save()

    assert s.get(KEY_ANCHOR) == [ctrl._anchor[0], ctrl._anchor[1]]
    assert ctrl._anchor[0] != 700 + 5000           # the anchor was actually clamped
    ctrl.leave()


def test_leave_flushes_pending_save_once_and_stops_timer(qapp):
    """leave() flushes a pending debounced save (writes the final state exactly
    once) and stops/clears the save timer."""
    s = _CountingSettings()
    ctrl, provider, window, created = _make(settings=s, anchor=(700, 400))
    ctrl.enter()
    ctrl.move_group(40, 25)                        # schedules a save (pending, unwritten)
    assert ctrl._save_pending is True
    assert s.saves == 0                            # debounced -> nothing written yet
    final_anchor = [ctrl._anchor[0], ctrl._anchor[1]]

    ctrl.leave()

    assert ctrl._save_pending is False
    assert s.saves == 1                            # flushed exactly once
    assert s.get(KEY_ANCHOR) == final_anchor       # final anchor persisted
    assert s.get(KEY_SCALE) is not None
    # The timer is stopped (a stray late timeout cannot re-save after leave).
    if ctrl._save_timer is not None:
        assert ctrl._save_timer.isActive() is False
    # A second run after leave is a no-op (the save already happened once).
    ctrl._run_pending_save()
    assert s.saves == 1


def test_load_recenters_anchor_when_saved_monitor_gone(qapp):
    """A loaded anchor on a now-missing monitor is recentered onto a currently
    visible monitor (lands inside the screen envelope), not the bogus saved coords."""
    s = _DictSettings({
        KEY_ANCHOR: [999999, 999999],             # far off any real/offscreen screen
        KEY_SCALE: 0.75,
        KEY_MONITOR: "NONEXISTENT-DISPLAY",
    })
    ctrl, provider, window, created = _make(settings=s)

    ctrl._load_persisted_state()

    assert ctrl._scale == 0.75
    assert ctrl._anchor != (999999, 999999)
    cx, cy = ctrl._anchor
    screens = ctrl._screens()
    assert any(l <= cx <= r and t <= cy <= b for (_n, l, t, r, b) in screens), \
        "recentered anchor must land within a visible monitor"


class _RaisingSettings:
    """A corrupt/unreadable settings store: every read RAISES. Loading from it
    must degrade to defaults rather than tank enter()."""

    def get(self, key, default=None):
        raise RuntimeError("corrupt settings store")

    def set(self, key, value):
        raise RuntimeError("corrupt settings store")


def test_leave_flushes_user_scale_before_framed_reset(qapp):
    """leave() must flush the USER scale (the scale the user left at) BEFORE it
    resets the framed metrics to 1.0 - reordering the flush after the reset would
    persist 1.0 and fail this test."""
    import pytest

    s = _DictSettings()
    ctrl, provider, window, created = _make(settings=s)
    ctrl.enter()
    ctrl.set_scale_by_notches(-2)              # a real non-1.0 user scale
    user_scale = ctrl._scale
    assert user_scale != 1.0
    # Do NOT run the pending save; leave() must flush it.
    ctrl.leave()

    assert s.get(KEY_SCALE) == pytest.approx(user_scale)
    assert s.get(KEY_SCALE) != 1.0             # NOT the framed reset value


def test_save_debounce_collapses_burst_to_one_final_write(qapp):
    """A rapid burst of changes restarts the single-shot timer each time (true
    trailing-edge debounce): nothing is written DURING the burst, and firing the
    timer once writes exactly ONE record of the FINAL state."""
    s = _CountingSettings()
    ctrl, provider, window, created = _make(settings=s)
    ctrl.enter()

    ctrl.set_scale_by_notches(1)
    ctrl.set_scale_by_notches(1)
    ctrl.set_scale_by_notches(1)

    # Armed exactly once, pending, nothing written yet (debounced, not throttled).
    assert ctrl._save_pending is True
    assert s.saves == 0
    assert ctrl._save_timer is not None and ctrl._save_timer.isActive()
    final_scale = ctrl._scale

    ctrl._run_pending_save()                   # the single trailing-edge fire

    assert s.saves == 1                        # exactly ONE write for the whole burst
    assert s.get(KEY_SCALE) == final_scale      # ... of the FINAL state
    ctrl.leave()


def test_enter_degrades_to_defaults_on_corrupt_settings(qapp):
    """A settings store whose load RAISES must not tank enter(): the controller
    degrades to defaults (scale 1.0, default anchor) and enter() still succeeds."""
    s = _RaisingSettings()
    ctrl, provider, window, created = _make(settings=s)

    assert ctrl.enter() is True                # corrupt settings did NOT tank enter()

    assert ctrl._scale == 1.0
    assert ctrl._anchor == ClusterOverlayController._default_anchor()
    ctrl.leave()


# ---------------------------------------------------------------------------
# 10. Radial menu + internal dim layer + radial-open window expansion
# ---------------------------------------------------------------------------
def _patch_radial(monkeypatch):
    """Replace the real RadialSurface + RadialMenuWidget with lightweight recording
    stubs so open/close exercise the controller wiring WITHOUT building real
    top-levels or touching the global pose fetcher (mirrors the group-controller
    radial tests). Returns a dict capturing the created stub surfaces + menus."""
    created = {"surfaces": [], "menus": []}

    class _StubRadialSurface(QWidget):
        def __init__(self, backend=None):
            super().__init__()
            self.backend = backend
            self.geom = None
            self.shown = 0
            self.hidden = 0
            self.deleted = 0
            self.prepared = 0
            self.hosted = None
            created["surfaces"].append(self)

        def host(self, widget):
            self.hosted = widget

        def set_overlay_geometry(self, rect):
            self.geom = rect
            # Real geometry too: the click-off chrome hit-test reads geometry()
            # to translate screen points into window-local path coords.
            self.setGeometry(rect)

        def prepare_initial_state(self):
            self.prepared += 1

        def show(self):
            self.shown += 1

        def hide(self):
            self.hidden += 1

        def deleteLater(self):
            self.deleted += 1

    class _StubRadialMenu(QWidget):
        closing = Signal()         # fly-back begun -> internal dim collapse (parity)
        close_requested = Signal()  # fly-back done -> teardown (parity)
        state_changed = Signal()    # main <-> accounts swap -> input reshape (parity)

        # Two known spoke circles in WINDOW-LOCAL coords (the menu fills the
        # fixed max-canvas window full-bleed): one off-center at (700, 400)
        # r=40 and one at (346, 346) r=40. The controller's input shape and the
        # click-off chrome hit-test both consume this.
        SPOKES = ((700.0, 400.0, 40.0), (346.0, 346.0, 40.0))

        def __init__(self, emblem_diameter=0.0, customizations=None,
                     variant="transparent", parent=None):
            super().__init__()
            self.emblem_diameter = emblem_diameter
            self.diameters = []
            self.reveals = 0
            self.begin_closes = 0
            created["menus"].append(self)

        def interactive_path(self):
            from PySide6.QtCore import QRectF
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            for (cx, cy, r) in self.SPOKES:
                path.addEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
            return path

        def set_emblem_diameter(self, d):
            self.diameters.append(d)

        def start_reveal(self):
            self.reveals += 1

        def _begin_close(self):
            # Mirror the real menu's kill-switch (no-anim) mode: closing fires at
            # the start of the fly-back, close_requested on (here: immediate)
            # completion - the controller's wiring then runs the real teardown.
            self.begin_closes += 1
            self.closing.emit()
            self.close_requested.emit()

    monkeypatch.setattr("utils.overlay.cluster_surface.RadialSurface",
                        _StubRadialSurface)
    monkeypatch.setattr("utils.overlay.radial_menu.RadialMenuWidget",
                        _StubRadialMenu)
    return created


def test_dim_layer_sits_between_cards_and_emblem(qapp):
    """After enter(), the internal dim widget's z-order is ABOVE the cards and
    BELOW the emblem (so it dims the cards behind the ring, never the emblem)."""
    ctrl, provider, window, created = _make()
    ctrl.enter()

    order = ctrl.cluster_layer_order()           # e.g. ["glow","cards","dim","emblem"]

    assert "cards" in order and "dim" in order and "emblem" in order
    assert order.index("cards") < order.index("dim") < order.index("emblem")
    ctrl.leave()


def test_internal_dim_built_hidden_child_of_grid_host_on_enter(qapp):
    """enter() builds the internal dim as a HIDDEN child of the borrowed grid host
    (shown only while the radial is open)."""
    ctrl, provider, window, created = _make()
    ctrl.enter()

    assert ctrl._dim is not None
    assert ctrl._dim.parent() is provider._grid_host
    assert ctrl._dim.isHidden() is True
    ctrl.leave()


def test_radial_open_does_not_reflow_cluster_or_move_emblem(qapp, monkeypatch):
    """REGRESSION (Task 7 Critical): opening the radial must NOT expand the cluster
    window, reflow the borrowed host, or move the emblem off the anchor.

    Built on a REAL ``ClusterSurface`` (not the recording stub) so
    ``OverlaySurface.host()``'s zero-margin FILL ``QVBoxLayout`` is actually
    exercised - the full-bleed path the recording stub hid. In the borrowed state
    the emblem is a fixed-position child (the framed ``_relayout_all`` that would
    re-center it is detached), so if the radial-open code re-grows the window the
    fill layout resizes ``_grid_host`` while the emblem stays put, dragging the
    emblem's global center off the anchor (with this geometry + anchor (1000,700)
    the old code moved it to (798,478)). The fix keeps the window at the FIXED
    max-scale envelope, so the host never reflows and the emblem center holds
    across open -> scale-while-open -> close, while the radial top-level gets its
    own fixed max-scale ``emblem*4`` canvas."""
    from utils.overlay.cluster_geometry import window_rect_for
    from utils.overlay.card_metrics import CardMetrics

    created_radial = _patch_radial(monkeypatch)
    provider = _StubProvider()
    anchor = (1000, 700)
    created_surfaces: list = []

    def factory():
        s = ClusterSurface(backend=NoOpOverlayBackend())
        created_surfaces.append(s)
        return s

    ctrl = ClusterOverlayController(
        _StubWindow(), backend=NoOpOverlayBackend(), settings=None,
        surface_factory=factory, card_provider=provider)
    ctrl._anchor = anchor

    assert ctrl.enter() is True
    surface = created_surfaces[0]
    qapp.processEvents()

    def emblem_global_center():
        # Use width//2 (the controller's _emblem_center_local convention) so the
        # mapped point matches the placement math exactly (no QRect.center() skew).
        e = provider._emblem
        return e.mapToGlobal(QPoint(e.width() // 2, e.height() // 2))

    host_size_before = QRect(provider._grid_host.rect()).size()
    c0 = emblem_global_center()
    assert (c0.x(), c0.y()) == anchor                # framed-open: emblem on anchor
    envelope_rect = window_rect_for(_ENV_SIZE, _PIVOT, anchor)
    assert surface.geometry() == envelope_rect       # the fixed envelope placement

    # --- open: NO window expansion, NO host reflow, emblem stays on anchor ---
    menu = ctrl.open_radial_menu()
    qapp.processEvents()
    assert menu is not None
    assert provider._grid_host.size() == host_size_before     # host did NOT reflow
    c1 = emblem_global_center()
    assert (c1.x(), c1.y()) == anchor
    # The cluster window stays at the fixed envelope (never the dim canvas).
    assert surface.geometry() == envelope_rect
    # The radial top-level receives the FIXED max-scale emblem*4 canvas.
    canvas_max = int(CardMetrics(SCALE_MAX).emblem) * 4
    rsurf = created_radial["surfaces"][-1]
    assert rsurf.geom.width() == canvas_max and rsurf.geom.height() == canvas_max

    # --- scale while open: emblem still on anchor, window geometry UNCHANGED ---
    ctrl.set_scale_by_notches(2)
    qapp.processEvents()
    c2 = emblem_global_center()
    assert (c2.x(), c2.y()) == anchor
    assert surface.geometry() == envelope_rect       # fixed envelope: no resize/move

    # --- close: emblem still on anchor ---
    ctrl.close_radial_menu()
    qapp.processEvents()
    c3 = emblem_global_center()
    assert (c3.x(), c3.y()) == anchor

    ctrl.leave()


def test_open_radial_menu_returns_widget_shows_dim_and_centers_radial(qapp, monkeypatch):
    """open_radial_menu(): returns the RadialMenuWidget, shows the internal dim,
    flips is_radial_open, and centers the radial top-level on the anchor."""
    from utils.overlay.card_metrics import CardMetrics

    created_radial = _patch_radial(monkeypatch)
    anchor = (1000, 700)
    ctrl, provider, window, created = _make(anchor=anchor)
    ctrl.enter()
    assert ctrl.is_radial_open is False

    menu = ctrl.open_radial_menu()

    assert menu is not None and menu in created_radial["menus"]
    assert ctrl.is_radial_open is True
    assert ctrl._dim.isHidden() is False                # dim revealed
    # The radial top-level is the FIXED max-scale canvas centered on the anchor
    # (never resized by a scale gesture; only the click region tracks the scale).
    canvas_max = int(CardMetrics(SCALE_MAX).emblem) * 4
    rsurf = created_radial["surfaces"][-1]
    assert rsurf.geom.width() == canvas_max and rsurf.geom.height() == canvas_max
    assert rsurf.geom.x() == int(anchor[0] - canvas_max / 2)
    assert rsurf.geom.y() == int(anchor[1] - canvas_max / 2)
    # The click-region bookkeeping tracks the CURRENT-scale canvas.
    assert ctrl._radial_size == int(CardMetrics(1.0).emblem * 4)
    assert rsurf.shown == 1
    ctrl.close_radial_menu()


def test_open_radial_menu_idempotent(qapp, monkeypatch):
    """A second open while already open is a no-op (returns None, no 2nd surface)."""
    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make()
    ctrl.enter()

    m1 = ctrl.open_radial_menu()
    m2 = ctrl.open_radial_menu()

    assert m1 is not None and m2 is None
    assert len(created_radial["surfaces"]) == 1
    ctrl.close_radial_menu()


def test_open_radial_menu_noop_when_inactive(qapp, monkeypatch):
    """open_radial_menu is a no-op (None, no surface) while framed."""
    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make()

    assert ctrl.open_radial_menu() is None
    assert created_radial["surfaces"] == []
    assert ctrl.is_radial_open is False


def test_close_radial_menu_tears_down_menu_keeps_surface_and_hides_dim(qapp, monkeypatch):
    """close_radial_menu(): deletes the MENU, hides (keeps) the internal dim,
    clears is_radial_open - but the PERSISTENT radial top-level stays MAPPED
    (unmapping + re-mapping per open is what plays the compositor's window-open
    animation: the notification slide-in seen live). leave() destroys it."""
    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(1000, 700))
    ctrl.enter()
    ctrl.open_radial_menu()
    rsurf = created_radial["surfaces"][-1]

    ctrl.close_radial_menu()

    assert ctrl.is_radial_open is False
    assert ctrl._radial_surface is rsurf          # surface persists across opens
    assert rsurf.hidden == 0 and rsurf.deleted == 0
    assert ctrl._radial_menu is None
    assert ctrl._dim is not None and ctrl._dim.isHidden() is True

    # Re-open hosts a NEW menu into the SAME (never re-mapped) surface.
    menu2 = ctrl.open_radial_menu()
    assert menu2 is not None
    assert created_radial["surfaces"][-1] is rsurf
    assert rsurf.shown == 1                       # mapped ONCE, at enter

    # leave() is what finally unmaps + deletes the persistent top-level.
    ctrl.leave()
    assert rsurf.hidden >= 1 and rsurf.deleted >= 1
    assert ctrl._radial_surface is None


def test_closed_persistent_surfaces_track_anchor_so_open_has_no_delta(qapp, monkeypatch):
    """Moving the cluster while the ring/panel are CLOSED must re-center the empty
    persistent top-levels immediately: the compositor animates geometry changes of
    the notification-typed windows, so a stale window caught up at open time would
    visibly MORPH in from the old spot (seen live: reopen-after-drag animated the
    ring from the previous emblem position). Kept glued while invisible, the
    open-time geometry call carries no delta."""
    created_radial = _patch_radial(monkeypatch)
    created_panel = _patch_panel(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(1000, 700), settings=_DictSettings())
    ctrl.enter()
    menu = ctrl.open_radial_menu()
    assert menu is not None
    rsurf = created_radial["surfaces"][-1]
    psurf = created_panel["surfaces"][-1]
    ctrl.close_radial_menu()

    ctrl.move_group(-60, 40)                     # drag while everything is CLOSED
    ax, ay = ctrl._anchor

    from utils.overlay.card_metrics import CardMetrics
    canvas_max = ctrl._radial_canvas_max()
    expected_radial = QRect(int(ax - canvas_max / 2), int(ay - canvas_max / 2),
                            canvas_max, canvas_max)
    psize = int(CardMetrics(ctrl.scale).emblem * 6)
    expected_panel = QRect(int(ax - psize / 2), int(ay - psize / 2), psize, psize)

    # The EMPTY surfaces already sit at the new-anchor placement...
    assert rsurf.geom == expected_radial
    assert psurf.geom == expected_panel

    # ...so reopening produces NO geometry change (nothing to morph).
    ctrl.open_radial_menu()
    assert rsurf.geom == expected_radial
    ctrl.close_radial_menu()
    ctrl.leave()


class _StubDismissCapture:
    """Recording stand-in for XRecordCapture: start/stop counters + the on_event
    callback exposed so tests can feed synthetic global presses."""

    def __init__(self, on_event):
        self.on_event = on_event
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1
        return True

    def stop(self):
        self.stopped += 1

    def is_running(self):
        return self.started > self.stopped


def test_click_off_dismisses_ring_with_flyback(qapp, monkeypatch):
    """A global press OFF the ring's chrome dismisses through the ANIMATED path
    (menu._begin_close -> fly-back -> close_requested -> close). Presses ON a
    spoke or ON the emblem do nothing (their owners handle them natively), and
    motion events are filtered before the bridge. The watcher starts with the
    open, stops with the close, and a late press after close is a safe no-op."""
    caps: list = []

    def cap_factory(cb):
        c = _StubDismissCapture(cb)
        caps.append(c)
        return c

    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(1000, 700),
                                            dismiss_capture_factory=cap_factory)
    ctrl.enter()
    menu = ctrl.open_radial_menu()
    assert len(caps) == 1 and caps[0].is_running()
    rsurf = created_radial["surfaces"][-1]
    ox, oy = rsurf.geometry().x(), rsurf.geometry().y()

    # ON a spoke (window-local spoke center -> screen): the menu owns the press.
    sx, sy = menu.SPOKES[0][0] + ox, menu.SPOKES[0][1] + oy
    caps[0].on_event("press", sx, sy, 0, 0)
    qapp.processEvents()
    assert menu.begin_closes == 0 and ctrl.is_radial_open is True

    # ON the emblem (the anchor IS the emblem center): the toggle owns it.
    caps[0].on_event("press", 1000, 700, 0, 0)
    qapp.processEvents()
    assert menu.begin_closes == 0 and ctrl.is_radial_open is True

    # Motion anywhere is filtered out before the bridge.
    caps[0].on_event("motion", 50, 50, 0, 0)
    qapp.processEvents()
    assert ctrl.is_radial_open is True

    # OFF chrome: the ANIMATED dismiss runs; the stub fly-back completes
    # synchronously, so close_requested has already torn the menu down.
    caps[0].on_event("press", 50, 50, 0, 0)
    qapp.processEvents()
    assert menu.begin_closes == 1
    assert ctrl.is_radial_open is False
    assert caps[0].stopped == 1                     # watcher stopped with the close

    # Late queued press after close: safe no-op.
    ctrl._on_radial_global_press(50, 50)
    assert ctrl.is_radial_open is False
    ctrl.leave()


def test_click_on_open_panel_does_not_dismiss_ring(qapp, monkeypatch):
    """With the Settings panel open above the ring, pressing INSIDE the panel
    must not dismiss the ring beneath it; pressing off everything still does."""
    caps: list = []

    def cap_factory(cb):
        c = _StubDismissCapture(cb)
        caps.append(c)
        return c

    created_radial = _patch_radial(monkeypatch)
    created_panel = _patch_panel(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(1000, 700), settings=_DictSettings(),
                                            dismiss_capture_factory=cap_factory)
    ctrl.enter()
    menu = ctrl.open_radial_menu()
    psurf = ctrl.open_panel_surface(QWidget())
    assert psurf is not None

    # Inside the panel rect (well away from the spokes and the emblem).
    g = psurf.geometry()
    caps[0].on_event("press", g.x() + 20, g.y() + 20, 0, 0)
    qapp.processEvents()
    assert menu.begin_closes == 0 and ctrl.is_radial_open is True

    # Off everything: dismiss (the panel stays; only the ring closes).
    caps[0].on_event("press", 30, 30, 0, 0)
    qapp.processEvents()
    assert menu.begin_closes == 1
    assert ctrl.is_radial_open is False
    assert ctrl.is_panel_open is True
    ctrl.close_panel_surface()
    ctrl.leave()


def test_radial_closing_signal_collapses_internal_dim(qapp, monkeypatch):
    """The menu's `closing` signal (fly-back begun) retracts the internal dim via
    its reverse animation, so the backdrop collapses IN STEP with the ring instead
    of the old hard hide() at teardown (OverlayGroupController._collapse_dim
    parity)."""
    _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(1000, 700))
    ctrl.enter()
    menu = ctrl.open_radial_menu()
    assert menu is not None
    dim = ctrl._dim
    assert dim is not None
    calls: list = []
    monkeypatch.setattr(dim, "start_close", lambda animate=True: calls.append(animate))

    menu.closing.emit()                     # ring fly-back begins

    assert calls, "internal dim did not collapse on menu.closing"
    ctrl.leave()


def test_close_radial_menu_idempotent_when_never_open(qapp, monkeypatch):
    """close_radial_menu when the radial was never open is a safe no-op and does
    NOT resize the window."""
    _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make()
    ctrl.enter()
    surface = created[0]
    before = surface.geom

    ctrl.close_radial_menu()

    assert ctrl.is_radial_open is False
    assert surface.geom == before


def test_leave_closes_radial_and_removes_internal_dim(qapp, monkeypatch):
    """leave() closes the radial (it must never outlive the overlay) and removes
    the internal dim BEFORE the borrowed host is restored, so framed mode gets the
    host back with NO stray dim child."""
    from utils.overlay.radial_menu import RadialDimWidget

    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make()
    ctrl.enter()
    ctrl.open_radial_menu()
    rsurf = created_radial["surfaces"][-1]
    assert ctrl.is_radial_open is True

    # Spy on restore_cluster_host so we can inspect the grid host's children AT THE
    # MOMENT the host is handed back to framed mode. The dim must already be detached
    # by then (removed BEFORE the restore, not merely by the time leave() returns).
    dims_at_restore: list = []
    orig_restore = provider.restore_cluster_host

    def _spy_restore(token):
        dims_at_restore.append([
            c for c in provider._grid_host.children()
            if isinstance(c, RadialDimWidget)])
        return orig_restore(token)

    provider.restore_cluster_host = _spy_restore

    ctrl.leave()

    assert ctrl.is_radial_open is False
    assert rsurf.hidden == 1 and rsurf.deleted == 1
    assert ctrl._dim is None
    # restore_cluster_host ran exactly once, and at that instant NO RadialDimWidget
    # was still parented under the grid host (dim removed before the host handoff).
    assert dims_at_restore == [[]]
    leftover = [c for c in provider._grid_host.children()
                if isinstance(c, RadialDimWidget)]
    assert leftover == []


def test_scale_while_radial_open_keeps_both_windows_fixed(qapp, monkeypatch):
    """A scale change WHILE the radial is open changes NO window geometry at all:
    the cluster window stays at its fixed envelope AND the radial top-level stays
    at its fixed max-scale canvas (the same no-geometry-during-scale discipline).
    Only the menu's painted ring diameter and the click-region bookkeeping track
    the new scale; the click-region re-apply is deferred to the settle timer."""
    from utils.overlay.card_metrics import CardMetrics

    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(1000, 700))
    ctrl.enter()
    surface = created[0]
    cluster_geom_before = QRect(surface.geom)
    ctrl.open_radial_menu()
    rsurf = created_radial["surfaces"][-1]
    menu = created_radial["menus"][-1]
    radial_geom_before = QRect(rsurf.geom)
    canvas_before = ctrl._radial_size

    ctrl.set_scale_by_notches(2)                  # scale up while the radial is open

    assert ctrl._radial_size > canvas_before       # click-region canvas tracked the emblem
    assert menu.diameters                          # set_emblem_diameter re-applied
    assert menu.diameters[-1] == float(CardMetrics(ctrl.scale).emblem)
    # NEITHER window changed geometry (the whole point of the transform model).
    assert surface.geom == cluster_geom_before
    assert rsurf.geom == radial_geom_before
    ctrl.close_radial_menu()


def test_move_while_radial_open_recenters_radial_top_level_on_new_anchor(qapp, monkeypatch):
    """COVERAGE: move_group() while the radial is open must run the move-while-open
    branch (``if self.is_radial_open: self._reposition_radial()``), re-centering the
    SEPARATE radial top-level on the NEW (reconciled) anchor - while the emblem
    global center still lands on that new anchor. Built on a REAL ``ClusterSurface``
    so the emblem's ``mapToGlobal`` reflects the actual on-screen placement."""
    created_radial = _patch_radial(monkeypatch)
    provider = _StubProvider()
    anchor = (400, 400)                        # well inside the 800x800 offscreen screen
    created_surfaces: list = []

    def factory():
        s = ClusterSurface(backend=NoOpOverlayBackend())
        created_surfaces.append(s)
        return s

    ctrl = ClusterOverlayController(
        _StubWindow(), backend=NoOpOverlayBackend(), settings=None,
        surface_factory=factory, card_provider=provider)
    ctrl._anchor = anchor

    assert ctrl.enter() is True
    qapp.processEvents()

    def emblem_global_center():
        e = provider._emblem
        return e.mapToGlobal(QPoint(e.width() // 2, e.height() // 2))

    c0 = emblem_global_center()
    assert (c0.x(), c0.y()) == anchor           # framed-open: emblem on the anchor

    assert ctrl.open_radial_menu() is not None
    qapp.processEvents()
    rsurf = created_radial["surfaces"][-1]
    canvas = ctrl._radial_size                  # unchanged by a pure move (no scale)
    canvas_max = ctrl._radial_canvas_max()      # the fixed radial window side

    # A real move (small delta -> no clamp on the 800x800 screen) while OPEN.
    assert ctrl.move_group(30, -20) is True
    qapp.processEvents()
    new_anchor = ctrl._anchor
    assert new_anchor != anchor                 # the anchor actually moved

    # The move-while-open branch re-centered the (fixed max-canvas) radial
    # top-level on the NEW anchor.
    assert ctrl._radial_size == canvas          # pure move: click canvas unchanged
    assert rsurf.geom.width() == canvas_max and rsurf.geom.height() == canvas_max
    assert rsurf.geom.x() == int(new_anchor[0] - canvas_max / 2)
    assert rsurf.geom.y() == int(new_anchor[1] - canvas_max / 2)
    # ... and the emblem global center still lands exactly on the new anchor.
    c1 = emblem_global_center()
    assert (c1.x(), c1.y()) == new_anchor

    ctrl.close_radial_menu()
    ctrl.leave()


def test_radial_click_region_is_menu_spokes_only(qapp, monkeypatch):
    """The radial input shape is EXACTLY the menu's interactive spokes: canvas
    corners, the emblem disc, and the gap between them are all CLICK-THROUGH,
    so game UI / card controls beneath the invisible canvas stay usable while
    the ring is open (live complaint: the old full-canvas square swallowed the
    game's friends button). Click-off dismissal belongs to the global-press
    watcher, not the input shape."""
    backend = _RecordingBackend()
    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(1000, 700), backend=backend)
    ctrl.enter()
    menu = ctrl.open_radial_menu()
    rsurf = created_radial["surfaces"][-1]
    path = [s for s in backend.shapes if s[0] is rsurf][-1][1]

    canvas_max = ctrl._radial_canvas_max()
    center = canvas_max / 2.0
    for (cx, cy, _r) in menu.SPOKES:
        assert path.contains(QPointF(cx, cy))          # spokes accept clicks
    assert not path.contains(QPointF(center, center))  # emblem center: through
    assert not path.contains(QPointF(10, 10))          # canvas corner: through
    assert not path.contains(QPointF(666, 546))        # emblem-spoke gap: through
    ctrl.close_radial_menu()
    ctrl.leave()


def test_radial_state_change_reapplies_input_shape(qapp, monkeypatch):
    """Swapping the ring between the main and accounts states re-applies the
    spokes-only input shape (the spoke set/geometry changed); the controller
    wires menu.state_changed for exactly this."""
    backend = _RecordingBackend()
    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(1000, 700), backend=backend)
    ctrl.enter()
    menu = ctrl.open_radial_menu()
    rsurf = created_radial["surfaces"][-1]
    n = len([s for s in backend.shapes if s[0] is rsurf])

    menu.state_changed.emit()

    assert len([s for s in backend.shapes if s[0] is rsurf]) == n + 1
    ctrl.close_radial_menu()
    ctrl.leave()


def test_radial_click_region_fallback_without_interactive_path(qapp, monkeypatch):
    """A menu WITHOUT interactive_path (bare stub / degraded build) falls back
    to the legacy canvas-minus-emblem-disc region: the ring still takes clicks
    and emblem gestures still pass through the center hole."""
    from utils.overlay.card_metrics import CardMetrics

    created = {"surfaces": [], "menus": []}

    class _BareRadialSurface(QWidget):
        def __init__(self, backend=None):
            super().__init__()
            created["surfaces"].append(self)

        def host(self, widget):
            pass

        def set_overlay_geometry(self, rect):
            self.setGeometry(rect)

        def prepare_initial_state(self):
            pass

        def show(self):
            pass

        def hide(self):
            pass

        def deleteLater(self):
            pass

    class _BareRadialMenu(QWidget):
        closing = _NoopSignal()

        def __init__(self, emblem_diameter=0.0, **kw):
            super().__init__()

        def start_reveal(self):
            pass

    monkeypatch.setattr("utils.overlay.cluster_surface.RadialSurface",
                        _BareRadialSurface)
    monkeypatch.setattr("utils.overlay.radial_menu.RadialMenuWidget",
                        _BareRadialMenu)
    backend = _RecordingBackend()
    ctrl, provider, window, c = _make(anchor=(1000, 700), backend=backend)
    ctrl.enter()
    ctrl.open_radial_menu()
    rsurf = created["surfaces"][-1]
    path = [s for s in backend.shapes if s[0] is rsurf][-1][1]

    canvas_max = ctrl._radial_canvas_max()
    center = canvas_max / 2.0
    emblem_dia, canvas = ctrl._radial_canvas()
    assert emblem_dia == float(CardMetrics(1.0).emblem)
    assert not path.contains(QPointF(center, center))            # disc hole
    assert path.contains(QPointF(center + emblem_dia * 0.77, center))  # ring area
    off = (canvas_max - canvas) // 2
    assert not path.contains(QPointF(off - 10, center))          # inert margin
    ctrl.close_radial_menu()
    ctrl.leave()


def test_begin_group_drag_dismisses_open_radial_animated_and_starts_drag(qapp, monkeypatch):
    """Dragging the emblem while the ring is open must dismiss the ring through
    the ANIMATED path (the menu's _begin_close: fly-back into the emblem, then
    close_requested -> teardown) - never the hard fade-out teardown - and still
    start the drag poll."""
    from PySide6.QtGui import QCursor

    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(400, 400))
    ctrl.enter()
    menu = ctrl.open_radial_menu()
    assert ctrl.is_radial_open is True
    rsurf = created_radial["surfaces"][-1]
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: QPoint(100, 100)))

    ctrl.begin_group_drag()

    assert menu.begin_closes == 1                        # ANIMATED dismiss used
    # The stub completes its fly-back synchronously (kill-switch mode), so the
    # close_requested wiring has already run the real teardown. The PERSISTENT
    # radial top-level stays mapped (only the menu died).
    assert ctrl.is_radial_open is False
    assert rsurf.hidden == 0 and rsurf.deleted == 0
    assert ctrl._radial_surface is rsurf
    assert ctrl._drag_timer is not None and ctrl._drag_timer.isActive()
    ctrl._end_drag()
    ctrl.leave()


def test_dismiss_radial_menu_falls_back_to_hard_close_without_anim_engine(qapp, monkeypatch):
    """A menu without _begin_close (a bare stub / degraded build) must still
    close: dismiss_radial_menu falls back to the immediate teardown. And with no
    ring open at all, dismiss is a safe no-op."""
    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(400, 400))
    ctrl.enter()

    ctrl.dismiss_radial_menu()                           # nothing open: no-op
    assert ctrl.is_radial_open is False

    menu = ctrl.open_radial_menu()
    rsurf = created_radial["surfaces"][-1]
    monkeypatch.delattr(type(menu), "_begin_close")      # degrade the menu

    ctrl.dismiss_radial_menu()

    assert ctrl.is_radial_open is False                  # hard-close fallback ran
    assert rsurf.hidden == 0 and rsurf.deleted == 0      # persistent surface kept
    assert ctrl._radial_surface is rsurf
    ctrl.leave()


def test_dim_is_scale_independent_and_open_reasserts_it(qapp, monkeypatch):
    """The internal dim lives INSIDE the transformed host, so its widget geometry
    must stay at the framed-1.0 ``emblem*4`` canvas centered on the 1.0 emblem
    center regardless of scale - the cluster transform already zooms it in
    lockstep with the emblem, and positioning it at the current scale would
    DOUBLE-scale it. open_radial_menu() re-asserts that framed placement, so a
    desynced dim can never flash wrong on open."""
    from utils.overlay.card_metrics import CardMetrics

    _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make()
    ctrl.enter()
    canvas0 = int(CardMetrics(1.0).emblem) * 4
    expected = QRect(_EMBLEM_CX - canvas0 // 2, _EMBLEM_CY - canvas0 // 2,
                     canvas0, canvas0)
    assert ctrl._dim.geometry() == expected        # built at the framed placement

    ctrl.set_scale_by_notches(2)                    # scale while the radial is CLOSED
    # Scale-independent: the dim's HOST-local geometry is untouched (the zoom is
    # the transform's job - a current-scale reposition here would double-scale).
    assert ctrl._dim.geometry() == expected

    # Deliberately DESYNC the dim geometry so ONLY open_radial_menu()'s own
    # open-time _position_internal_dim() re-assert can correct it.
    ctrl._dim.setGeometry(QRect(0, 0, 3, 3))
    assert ctrl._dim.geometry() == QRect(0, 0, 3, 3)   # desync took effect

    ctrl.open_radial_menu()
    # Open re-asserts the framed placement (never the stale desynced one). Fails
    # if the open-time _position_internal_dim() call is removed.
    assert ctrl._dim.geometry() == expected
    ctrl.close_radial_menu()
    ctrl.leave()


def test_open_radial_menu_failclosed_on_setup_error(qapp, monkeypatch):
    """A failure mid-open (here the radial surface's host raises) must fail closed:
    no exception escapes, is_radial_open is False, no menu is tracked - and the
    PERSISTENT radial top-level survives the rollback (only leave() deletes it)."""
    created: dict = {"surfaces": []}

    class _BoomRadialSurface(QWidget):
        def __init__(self, backend=None):
            super().__init__()
            self.hidden = 0
            self.deleted = 0
            self.geom = None
            created["surfaces"].append(self)

        def host(self, widget):
            raise RuntimeError("radial host boom")

        def set_overlay_geometry(self, rect):
            self.geom = rect

        def prepare_initial_state(self):
            pass

        def show(self):
            pass

        def hide(self):
            self.hidden += 1

        def deleteLater(self):
            self.deleted += 1

    class _StubRadialMenu(QWidget):
        def __init__(self, emblem_diameter=0.0, **kw):
            super().__init__()

        def start_reveal(self):
            pass

    monkeypatch.setattr("utils.overlay.cluster_surface.RadialSurface",
                        _BoomRadialSurface)
    monkeypatch.setattr("utils.overlay.radial_menu.RadialMenuWidget",
                        _StubRadialMenu)

    ctrl, provider, window, c = _make()
    ctrl.enter()

    result = ctrl.open_radial_menu()                # must not raise

    assert result is None
    assert ctrl.is_radial_open is False
    assert ctrl._radial_menu is None
    # The PERSISTENT top-level (pre-mapped at enter) survives the rollback -
    # deleting + re-mapping it per open would replay the compositor's window-open
    # animation. leave() is what finally destroys it.
    assert len(created["surfaces"]) == 1
    assert ctrl._radial_surface is created["surfaces"][0]
    assert created["surfaces"][0].deleted == 0
    ctrl.leave()
    assert created["surfaces"][0].deleted == 1
    assert ctrl._radial_surface is None


def test_radial_input_shape_applied_once_then_deferred_to_settle(qapp, monkeypatch):
    """The radial click region is applied EXACTLY ONCE on open (on top of the
    EMPTY click-through shape the persistent surface got when enter() pre-mapped
    it); a scale-while-open does NOT re-apply it immediately (the X11 reshape is
    deferred to the settle timer); firing the settle (_reapply_radial_shape)
    applies it; close returns the surface to an EMPTY shape; and a stray settle
    after close()/leave() is a safe no-op. Shapes are filtered to the radial
    surface so the cluster window's broad/exact shapes are excluded."""
    backend = _RecordingBackend()
    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(1000, 700), backend=backend)
    ctrl.enter()
    rsurf = created_radial["surfaces"][-1]          # persistent, pre-mapped at enter

    def radial_shapes():
        return [s for s in backend.shapes if s[0] is rsurf]

    assert len(radial_shapes()) == 1                # enter: the EMPTY shape
    assert radial_shapes()[0][1].isEmpty()

    ctrl.open_radial_menu()
    assert len(radial_shapes()) == 2                # exactly one apply on open...
    assert not radial_shapes()[-1][1].isEmpty()     # ...and it is the CLICK region

    ctrl.set_scale_by_notches(2)                    # scale while open
    assert len(radial_shapes()) == 2               # NOT re-applied (deferred to settle)
    # The deferral is a REAL armed settle timer (not just a direct-call artifact):
    # _schedule_radial_reshape() must have created + started a single-shot QTimer.
    timer = ctrl._radial_reshape_timer
    assert isinstance(timer, QTimer)
    assert timer.isSingleShot() is True
    assert timer.isActive() is True                 # actually armed by the scale-while-open

    ctrl._reapply_radial_shape()                    # the settle fires
    assert len(radial_shapes()) == 3               # now re-applied

    ctrl.close_radial_menu()
    # close_radial_menu() must STOP the armed reshape timer so no late reshape
    # fires against the emptied radial surface, and returns the persistent
    # surface to its EMPTY click-through shape.
    assert timer.isActive() is False
    assert radial_shapes()[-1][1].isEmpty()
    after_close = len(radial_shapes())
    ctrl._reapply_radial_shape()                    # stray late settle after close
    assert len(radial_shapes()) == after_close     # safe no-op (menu gone, size 0)

    ctrl.leave()
    after_leave = len(radial_shapes())
    ctrl._reapply_radial_shape()                    # stray late settle after leave
    assert len(radial_shapes()) == after_leave     # still a safe no-op


# ---------------------------------------------------------------------------
# 11. Portable Settings-panel surface (T7b)
# ---------------------------------------------------------------------------
def _patch_panel(monkeypatch):
    """Replace the real PanelSurface with a lightweight recording stub so the panel
    lifecycle can be exercised WITHOUT building a real override-redirect top-level.
    Returns a dict capturing the created stub surfaces (mirrors _patch_radial)."""
    created = {"surfaces": []}

    class _StubPanelSurface(QWidget):
        def __init__(self, backend=None):
            super().__init__()
            self.backend = backend
            self.geom = None
            self.shown = 0
            self.hidden = 0
            self.deleted = 0
            self.prepared = 0
            self.raised = 0
            self.hosted = None
            created["surfaces"].append(self)

        def host(self, widget):
            self.hosted = widget
            widget.setParent(self)

        def set_overlay_geometry(self, rect):
            self.geom = rect
            # Real geometry too: the click-off chrome hit-test reads geometry().
            self.setGeometry(rect)

        def prepare_initial_state(self):
            self.prepared += 1

        def show(self):
            self.shown += 1

        def hide(self):
            self.hidden += 1

        def raise_(self):
            self.raised += 1

        def deleteLater(self):
            self.deleted += 1

    monkeypatch.setattr("utils.overlay.cluster_surface.PanelSurface",
                        _StubPanelSurface)
    return created


def _panel_size(scale):
    from utils.overlay.card_metrics import CardMetrics
    return int(CardMetrics(scale).emblem * 6)


def test_open_panel_surface_noop_when_inactive(qapp, monkeypatch):
    """open_panel_surface is a no-op (None, no surface) while framed."""
    created_panel = _patch_panel(monkeypatch)
    ctrl, provider, window, created = _make()

    assert ctrl.open_panel_surface(QWidget()) is None
    assert created_panel["surfaces"] == []
    assert ctrl.is_panel_open is False


def test_open_panel_surface_double_open_returns_same_surface(qapp, monkeypatch):
    """A second open while already open returns the SAME surface (no 2nd top-level)."""
    created_panel = _patch_panel(monkeypatch)
    ctrl, provider, window, created = _make()
    ctrl.enter()

    s1 = ctrl.open_panel_surface(QWidget())
    s2 = ctrl.open_panel_surface(QWidget())

    assert s1 is not None
    assert s2 is s1
    assert len(created_panel["surfaces"]) == 1
    assert ctrl.is_panel_open is True
    ctrl.close_panel_surface()


def test_open_panel_surface_centers_on_anchor_at_emblem_times_six(qapp, monkeypatch):
    """open_panel_surface(): hosts the widget, sizes the panel to emblem*6, centers
    it on the anchor, shows + raises it, and applies a FULL-RECT click-accepting
    input shape."""
    backend = _RecordingBackend()
    created_panel = _patch_panel(monkeypatch)
    anchor = (1000, 700)
    ctrl, provider, window, created = _make(anchor=anchor, backend=backend)
    ctrl.enter()
    backend.shapes.clear()                          # ignore enter-time cluster shaping
    widget = QWidget()

    surface = ctrl.open_panel_surface(widget)

    assert surface is not None
    assert surface.hosted is widget
    size = _panel_size(1.0)
    ax, ay = anchor
    assert surface.geom == QRect(
        int(ax - size / 2), int(ay - size / 2), size, size)
    assert surface.shown == 1
    assert surface.raised >= 1
    assert surface.prepared == 1
    # A FULL-RECT click-accepting input shape was applied to the PANEL surface.
    panel_shapes = [s for s in backend.shapes if s[0] is surface]
    assert len(panel_shapes) == 1
    _win, path, _dpr = panel_shapes[0]
    assert path.boundingRect().toRect() == QRect(0, 0, size, size)
    ctrl.close_panel_surface()


def test_close_panel_surface_runs_on_close_before_teardown_and_is_idempotent(qapp, monkeypatch):
    """close_panel_surface() runs on_close FIRST (the surface still exists + is
    undestroyed at that instant, so the caller can reparent its content out),
    then returns the PERSISTENT surface to its empty state - still mapped, never
    deleted per close (re-mapping would replay the compositor's open animation).
    leave() deletes it. A second close is a safe no-op."""
    created_panel = _patch_panel(monkeypatch)
    ctrl, provider, window, created = _make()
    ctrl.enter()
    surface = ctrl.open_panel_surface(QWidget())

    order: list = []

    def on_close():
        # At the moment on_close runs, the surface is still tracked + NOT yet
        # torn down (deleteLater not called) - so the caller can reclaim content.
        order.append(("on_close", ctrl._panel_surface is surface, surface.deleted))

    # Re-open path can't set on_close after the fact, so wire it directly.
    ctrl._panel_on_close = on_close

    ctrl.close_panel_surface()

    assert order == [("on_close", True, 0)]          # ran first, surface alive
    assert surface.hidden == 0 and surface.deleted == 0   # persistent: kept mapped
    assert ctrl._panel_surface is surface
    assert ctrl.is_panel_open is False
    assert ctrl._panel_on_close is None

    # Idempotent: a second close does nothing (no re-run).
    ctrl.close_panel_surface()
    assert order == [("on_close", True, 0)]

    # leave() is what finally unmaps + deletes the persistent top-level.
    ctrl.leave()
    assert surface.hidden == 1 and surface.deleted == 1
    assert ctrl._panel_surface is None


def test_open_panel_surface_failclosed_on_setup_error(qapp, monkeypatch):
    """A failure mid-open (the panel surface's host raises) must fail closed: no
    exception escapes, is_panel_open False, no on_close/size left tracked, the
    PERSISTENT top-level survives the rollback (leave() deletes it), and on_close
    still runs during the rollback so the caller reclaims its widget."""
    created: dict = {"surfaces": []}
    ran_on_close: list = []

    class _BoomPanelSurface(QWidget):
        def __init__(self, backend=None):
            super().__init__()
            self.hidden = 0
            self.deleted = 0
            self.geom = None
            created["surfaces"].append(self)

        def host(self, widget):
            raise RuntimeError("panel host boom")

        def set_overlay_geometry(self, rect):
            self.geom = rect

        def prepare_initial_state(self):
            pass

        def show(self):
            pass

        def hide(self):
            self.hidden += 1

        def deleteLater(self):
            self.deleted += 1

    monkeypatch.setattr("utils.overlay.cluster_surface.PanelSurface",
                        _BoomPanelSurface)

    ctrl, provider, window, c = _make()
    ctrl.enter()

    result = ctrl.open_panel_surface(QWidget(), on_close=lambda: ran_on_close.append(1))

    assert result is None
    assert ctrl.is_panel_open is False
    assert ctrl._panel_on_close is None
    assert ctrl._panel_size == 0
    # The PERSISTENT top-level (pre-mapped at enter) survives the rollback.
    assert len(created["surfaces"]) == 1
    assert ctrl._panel_surface is created["surfaces"][0]
    assert created["surfaces"][0].deleted == 0
    # The rollback ran on_close (so the caller reclaims its widget on a failed open).
    assert ran_on_close == [1]
    ctrl.leave()
    assert created["surfaces"][0].deleted == 1
    assert ctrl._panel_surface is None


def test_move_group_recenters_open_panel_on_new_anchor(qapp, monkeypatch):
    """A real move_group() while the panel is open re-centers the SEPARATE panel
    top-level on the NEW (reconciled) anchor; the panel size is unchanged (the panel
    is re-centered, never rescaled)."""
    created_panel = _patch_panel(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(400, 400))
    ctrl.enter()
    surface = ctrl.open_panel_surface(QWidget())
    size_before = surface.geom.width()

    assert ctrl.move_group(30, -20) is True
    new_anchor = ctrl._anchor
    assert new_anchor != (400, 400)

    size = _panel_size(ctrl.scale)
    assert surface.geom.width() == size_before       # size unchanged
    assert surface.geom == QRect(
        int(new_anchor[0] - size / 2), int(new_anchor[1] - size / 2), size, size)
    ctrl.close_panel_surface()


def test_scale_while_panel_open_recenters_panel_without_rescaling(qapp, monkeypatch):
    """A scale change WHILE the panel is open keeps the panel at its open-time size
    (NOT rescaled) and centered on the anchor - the panel follows the anchor, never
    the growing emblem."""
    created_panel = _patch_panel(monkeypatch)
    anchor = (1000, 700)
    ctrl, provider, window, created = _make(anchor=anchor)
    ctrl.enter()
    surface = ctrl.open_panel_surface(QWidget())
    size_at_open = surface.geom.width()
    raised_before = surface.raised

    ctrl.set_scale_by_notches(2)                     # scale up while the panel is open

    # The panel is NOT rescaled: it stays at the open-time size, centered on anchor.
    assert surface.geom.width() == size_at_open
    assert surface.geom == QRect(
        int(anchor[0] - size_at_open / 2), int(anchor[1] - size_at_open / 2),
        size_at_open, size_at_open)
    # De-tautologized: the geometry alone is unchanged (fixed size + same anchor), so
    # assert a side effect ONLY _reposition_panel() performs - it re-RAISES the panel
    # from the scale path. This FAILS if the scale-path _reposition_panel() call is
    # removed (the geometry assertions above would still pass without it).
    assert surface.raised == raised_before + 1
    ctrl.close_panel_surface()


def test_leave_closes_panel_and_runs_on_close_before_restore(qapp, monkeypatch):
    """leave() closes the panel (it must never outlive the overlay), running its
    on_close BEFORE the borrowed host is restored, and leaves nothing behind."""
    created_panel = _patch_panel(monkeypatch)
    ctrl, provider, window, created = _make()
    ctrl.enter()
    surface = ctrl.open_panel_surface(QWidget())

    events: list = []
    orig_restore = provider.restore_cluster_host

    def _spy_restore(token):
        events.append("restore")
        return orig_restore(token)

    provider.restore_cluster_host = _spy_restore
    ctrl._panel_on_close = lambda: events.append("on_close")

    ctrl.leave()

    # on_close ran, and it ran BEFORE the host was handed back to framed mode.
    assert "on_close" in events and "restore" in events
    assert events.index("on_close") < events.index("restore")
    # The panel is fully torn down, nothing left behind.
    assert ctrl.is_panel_open is False
    assert ctrl._panel_surface is None
    assert ctrl._panel_on_close is None
    assert surface.hidden == 1 and surface.deleted == 1


# ---------------------------------------------------------------------------
# 11b. Transaction-safe panel OPEN: a failure in ANY fallible open step rolls back
# ---------------------------------------------------------------------------
def _patch_boom_step_panel(monkeypatch, boom_on):
    """Patch PanelSurface with a recording stub that RAISES at a chosen OPEN step
    (``boom_on`` in {"prepare", "raise", "shape"}) so the transaction-safe rollback
    can be exercised per-step. ``shape`` raises inside ``devicePixelRatio()`` so the
    input-shape apply step (the last open step) fails. Returns the created dict."""
    created = {"surfaces": []}

    class _BoomStepPanelSurface(QWidget):
        def __init__(self, backend=None):
            super().__init__()
            self.hidden = 0
            self.deleted = 0
            self.hosted = None
            self.geom = None
            created["surfaces"].append(self)

        def host(self, widget):
            self.hosted = widget
            widget.setParent(self)

        def set_overlay_geometry(self, rect):
            self.geom = rect

        def prepare_initial_state(self):
            if boom_on == "prepare":
                raise RuntimeError("prepare boom")

        def show(self):
            pass

        def raise_(self):
            if boom_on == "raise":
                raise RuntimeError("raise boom")

        def devicePixelRatio(self):
            if boom_on == "shape":
                raise RuntimeError("dpr boom")
            return super().devicePixelRatio()

        def hide(self):
            self.hidden += 1

        def deleteLater(self):
            self.deleted += 1

    monkeypatch.setattr("utils.overlay.cluster_surface.PanelSurface",
                        _BoomStepPanelSurface)
    return created


@pytest.mark.parametrize("boom_on", ["raise", "shape"])
def test_open_panel_surface_failclosed_on_open_step_raise(qapp, monkeypatch, boom_on):
    """Transaction-safe open: a failure in ANY fallible open step (raise_ or the
    input-shape apply; prepare_initial_state moved to the best-effort persistent
    pre-map at enter) fails closed - open returns None, is_panel_open is False, no
    on_close/size is left tracked, the PERSISTENT top-level survives (leave()
    deletes it), and on_close ran during the rollback. Reverting the fix
    (re-guarding these steps with _safe_call / swallow) would swallow the failure
    and return the surface with is_panel_open True."""
    created = _patch_boom_step_panel(monkeypatch, boom_on)
    ran_on_close: list = []
    ctrl, provider, window, c = _make()
    ctrl.enter()

    result = ctrl.open_panel_surface(
        QWidget(), on_close=lambda: ran_on_close.append(1))     # must not raise

    assert result is None
    assert ctrl.is_panel_open is False
    assert ctrl._panel_on_close is None
    assert ctrl._panel_size == 0
    # The persistent top-level survives the rollback (never re-mapped per open).
    assert len(created["surfaces"]) == 1
    assert ctrl._panel_surface is created["surfaces"][0]
    assert created["surfaces"][0].deleted == 0
    # The rollback ran on_close (so the caller reclaims its widget on a failed open).
    assert ran_on_close == [1]
    ctrl.leave()
    assert created["surfaces"][0].deleted == 1


# ---------------------------------------------------------------------------
# 11c. Panel stays ABOVE the radial when BOTH are open
# ---------------------------------------------------------------------------
def test_panel_stays_above_radial_when_both_open(qapp, monkeypatch):
    """Opening the radial while the panel is already open must re-raise the panel
    (it floats above the emblem AND the radial) - and must NOT re-map (show) the
    persistent radial top-level: re-mapping per open is what played the
    compositor's window-open animation. Both surfaces are mapped once at enter
    (radial first, panel second - the map order that stacks the panel on top);
    after that, opens only re-raise. Reverting the persistent-surface fix would
    re-show the radial here; dropping the panel re-raise in open_radial_menu
    would drop the post-clear panel-raise event."""
    z_events: list = []

    class _StubRadialSurface(QWidget):
        def __init__(self, backend=None):
            super().__init__()
            self.geom = None

        def host(self, widget):
            pass

        def set_overlay_geometry(self, rect):
            self.geom = rect

        def prepare_initial_state(self):
            pass

        def show(self):
            z_events.append(("radial-show", self))

        def hide(self):
            pass

        def deleteLater(self):
            pass

    class _StubRadialMenu(QWidget):
        closing = Signal()      # fly-back begun -> internal dim collapse (parity)

        def __init__(self, emblem_diameter=0.0, **kw):
            super().__init__()

        def set_emblem_diameter(self, d):
            pass

        def start_reveal(self):
            pass

    class _StubPanelSurface(QWidget):
        def __init__(self, backend=None):
            super().__init__()
            self.geom = None
            self.raised = 0

        def host(self, widget):
            widget.setParent(self)

        def set_overlay_geometry(self, rect):
            self.geom = rect

        def prepare_initial_state(self):
            pass

        def show(self):
            pass

        def raise_(self):
            self.raised += 1
            z_events.append(("panel-raise", self))

        def hide(self):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr("utils.overlay.cluster_surface.RadialSurface", _StubRadialSurface)
    monkeypatch.setattr("utils.overlay.radial_menu.RadialMenuWidget", _StubRadialMenu)
    monkeypatch.setattr("utils.overlay.cluster_surface.PanelSurface", _StubPanelSurface)

    ctrl, provider, window, created = _make(anchor=(1000, 700))
    ctrl.enter()
    # Both persistent surfaces were mapped ONCE at enter, radial before panel.
    assert [k for k, _ in z_events] == [("radial-show")]

    psurf = ctrl.open_panel_surface(QWidget())
    assert psurf is not None
    assert psurf.raised >= 1                    # single-open z-order: panel raised on open
    z_events.clear()

    menu = ctrl.open_radial_menu()
    assert menu is not None

    kinds = [k for k, _ in z_events]
    assert "radial-show" not in kinds           # NEVER re-mapped per open (no anim)
    assert "panel-raise" in kinds               # the panel was re-raised while opening it

    ctrl.close_radial_menu()
    ctrl.close_panel_surface()
    ctrl.leave()


# ---------------------------------------------------------------------------
# 11d. A raising on_close must not destroy the BORROWED hosted widget
# ---------------------------------------------------------------------------
def _cpp_alive(widget) -> bool:
    """True while the widget's underlying C++ object is not yet destroyed (a deleted
    QWidget raises RuntimeError on any method access)."""
    try:
        widget.objectName()
        return True
    except RuntimeError:
        return False


def test_close_panel_surface_protects_hosted_widget_when_on_close_raises(qapp):
    """A raising on_close must not strand the BORROWED hosted widget inside the
    persistent surface. Built on a REAL PanelSurface: close_panel_surface()
    reparents the still-hosted widget out even though on_close raised and never
    reclaimed it, so leave()'s later surface destruction (deleteLater DOES
    cascade to children) cannot delete the borrowed widget. Reverting the fix
    (dropping _release_panel_content) leaves the widget parented to the surface
    and leave() would destroy it."""
    ctrl, provider, window, created = _make()
    ctrl.enter()
    widget = QWidget()

    def boom():
        raise RuntimeError("on_close boom")

    surface = ctrl.open_panel_surface(widget, on_close=boom)   # REAL PanelSurface
    assert surface is not None
    assert ctrl.is_panel_open is True
    assert widget.parent() is surface                # hosted in the surface

    ctrl.close_panel_surface()                       # on_close raises; must not tank the close

    assert ctrl.is_panel_open is False
    assert widget.parent() is None                   # released out of the persistent surface
    assert _cpp_alive(surface) is True               # persistent: still alive after close

    ctrl.leave()                                     # destroys the persistent surface
    # Force the surface's deleteLater to actually run: DeferredDelete is NOT processed
    # by a plain processEvents(), so without this the surface (and any stranded child)
    # would still be alive and the survival check below would be meaningless.
    from PySide6.QtCore import QEvent
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)

    assert _cpp_alive(surface) is False              # the surface WAS really destroyed
    assert _cpp_alive(widget) is True                # BORROWED widget survived that destruction
    assert widget.parent() is None


# ---------------------------------------------------------------------------
# 12. Hover-peek / ghost-click / drag in CLUSTER-LOCAL coords (T8)
#
# The single-window cluster hosts all four cards in ONE window, so the old
# per-surface SCREEN hit tests become CLUSTER-LOCAL: a control lives at its
# cell's origin within _grid_host (window-local), and a card's SCREEN rect is
# the window origin plus that cell's offset. These tests pin the load-bearing
# hit-test round-trip, the ghost-click delivery, the emblem-drag poll, and the
# SAFE (paint-time set_shell_extra_opacity) hover-peek fade.
# ---------------------------------------------------------------------------

# Window origin for anchor (1000, 700): the placement rect top-left is
# anchor - emblem_center_local = (1000 - 110, 700 - 90) = (890, 610).
_GHOST_ANCHOR = (1000, 700)
_WIN_ORIGIN = (_GHOST_ANCHOR[0] - _EMBLEM_CX, _GHOST_ANCHOR[1] - _EMBLEM_CY)  # (890, 610)


def test_hover_peek_and_ghost_use_cluster_local_card_rects(qapp):
    """The load-bearing deliverable: slot_at_window_point / card_control_point are
    exact INVERSES in WINDOW-LOCAL coords for every slot, a point over no card
    returns None, and a point inside a NON-visible cell is excluded."""
    ctrl, provider, window, created = _make()
    ctrl.enter()

    # Round-trip: the representative control point of slot N hit-tests back to N.
    assert ctrl.slot_at_window_point(ctrl.card_control_point(0)) == 0
    assert ctrl.slot_at_window_point(ctrl.card_control_point(2)) == 2
    assert ctrl.slot_at_window_point(ctrl.card_control_point(1)) == 1
    assert ctrl.slot_at_window_point(ctrl.card_control_point(3)) == 3

    # A point over no card control (well outside every cell's control rects, and
    # off the emblem) returns None.
    assert ctrl.slot_at_window_point(QPoint(2, 2)) is None

    # A point INSIDE a non-visible cell's control is excluded (returns None): the
    # geometric point still exists, but the slot dropped out of the visible set.
    probe1 = ctrl.card_control_point(1)
    ctrl._visible_cells = {0, 2}
    assert ctrl.slot_at_window_point(probe1) is None
    ctrl._visible_cells = {0, 1, 2, 3}
    assert ctrl.slot_at_window_point(probe1) == 1
    ctrl.leave()


def test_ghost_press_over_control_delivers_cluster_local_click(qapp):
    """A SCREEN ghost 'press' over card N's control maps to
    deliver_ghost_click(N, card_local_x, card_local_y): the controller builds the
    cards list from the window origin + each cell's offset and resolves the click
    in cell-root-local coords. A press over no card delivers nothing."""
    ctrl, provider, window, created = _make(anchor=_GHOST_ANCHOR, settings=_DictSettings())
    ctrl.enter()

    # Center of cell 1's first control in SCREEN coords: window origin (890,610) +
    # cell 1 origin (210,10) + control card-local (8,8,30,18) center (23,17).
    ox, oy = _WIN_ORIGIN
    sx = ox + 210 + 8 + 15
    sy = oy + 10 + 8 + 9
    ctrl.on_ghost_event(("press", [(1, sx, sy)]))
    assert provider.ghost_clicks == [(1, 23, 17)]     # cell-root-local (at-scale) coords

    # A press over the card BODY (no control) delivers nothing.
    provider.ghost_clicks.clear()
    body_x = ox + 210 + 100          # inside cell 1, not on either control
    body_y = oy + 10 + 100
    ctrl.on_ghost_event(("press", [(1, body_x, body_y)]))
    assert provider.ghost_clicks == []

    # A press over open space (no card at all) delivers nothing.
    ctrl.on_ghost_event(("press", [(1, 2, 2)]))
    assert provider.ghost_clicks == []
    ctrl.leave()


def test_ghost_press_excludes_non_visible_cell(qapp):
    """A ghost press over a NON-visible cell's control delivers nothing (empty
    cards drop out of the click pass), while a visible cell still delivers."""
    ctrl, provider, window, created = _make(anchor=_GHOST_ANCHOR, settings=_DictSettings())
    ctrl.enter()
    ctrl._visible_cells = {0}                          # only cell 0 is occupied
    ox, oy = _WIN_ORIGIN

    # Screen center of cell 1's first control (cell 1 is NOT visible).
    s1x = ox + 210 + 8 + 15
    s1y = oy + 10 + 8 + 9
    ctrl.on_ghost_event(("press", [(1, s1x, s1y)]))
    assert provider.ghost_clicks == []                 # non-visible cell excluded

    # Screen center of cell 0's first control (cell 0 IS visible).
    s0x = ox + 10 + 8 + 15
    s0y = oy + 10 + 8 + 9
    ctrl.on_ghost_event(("press", [(0, s0x, s0y)]))
    assert provider.ghost_clicks == [(0, 23, 17)]
    ctrl.leave()


def test_ghost_click_disabled_without_settings(qapp):
    """No settings object -> ghost clicks are gated OFF (a press delivers nothing),
    mirroring the old controller's _ghost_click_enabled gate."""
    ctrl, provider, window, created = _make(anchor=_GHOST_ANCHOR)   # settings=None
    ctrl.enter()
    ox, oy = _WIN_ORIGIN
    ctrl.on_ghost_event(("press", [(1, ox + 210 + 8 + 15, oy + 10 + 8 + 9)]))
    assert provider.ghost_clicks == []
    ctrl.leave()


def test_begin_group_drag_follows_cursor_delta(qapp, monkeypatch):
    """begin_group_drag() starts a ~16ms cursor poll; each _drag_step shifts the
    anchor by the cursor delta (via the clamped move_group), and a left-button
    release ends the drag."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QCursor
    from PySide6.QtWidgets import QApplication

    ctrl, provider, window, created = _make(anchor=(400, 400))   # well inside 800x800
    ctrl.enter()

    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: QPoint(100, 100)))
    ctrl.begin_group_drag()
    assert ctrl._drag_last == QPoint(100, 100)
    assert ctrl._drag_timer is not None and ctrl._drag_timer.isActive()

    anchor0 = ctrl._anchor
    monkeypatch.setattr(QApplication, "mouseButtons", staticmethod(lambda: Qt.LeftButton))
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: QPoint(130, 80)))
    ctrl._drag_step()
    # The anchor followed the cursor delta (30, -20), clamped to the envelope (no
    # clamp needed this far from the edge).
    assert ctrl._anchor == (anchor0[0] + 30, anchor0[1] - 20)

    # Button released -> the poll ends (timer stopped, last cleared).
    monkeypatch.setattr(QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton))
    ctrl._drag_step()
    assert ctrl._drag_timer.isActive() is False
    assert ctrl._drag_last is None
    ctrl.leave()


def test_drag_step_locked_out_during_scale(qapp, monkeypatch):
    """The emblem drag inherits the Task-5 drag-lockout-during-scale for free: while
    a scale gesture is live (_scaling_active), _drag_step's move_group call is a
    no-op, so the anchor does NOT move mid-zoom."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QCursor
    from PySide6.QtWidgets import QApplication

    ctrl, provider, window, created = _make(anchor=(400, 400))
    ctrl.enter()

    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: QPoint(100, 100)))
    ctrl.begin_group_drag()
    ctrl.set_scale_by_notches(1)                        # scale gesture live
    assert ctrl._scaling_active is True

    anchor0 = ctrl._anchor
    monkeypatch.setattr(QApplication, "mouseButtons", staticmethod(lambda: Qt.LeftButton))
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: QPoint(160, 60)))
    ctrl._drag_step()
    assert ctrl._anchor == anchor0                     # locked out: no anchor move

    # After settle the lockout lifts and a drag step moves again.
    ctrl._settle_input()
    assert ctrl._scaling_active is False
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: QPoint(180, 40)))
    ctrl._drag_step()
    assert ctrl._anchor != anchor0                     # gesture settled -> drag allowed
    ctrl.leave()


def test_hover_peek_fades_hovered_card_via_shell_opacity(qapp):
    """A ghost point over card N fades ONLY card N via the SAFE paint-time
    set_shell_extra_opacity hook (bg + portrait < 1.0), leaving the other visible
    cards fully opaque. Ten ticks drive the fade to its net targets."""
    ctrl, provider, window, created = _make(anchor=_GHOST_ANCHOR, settings=_DictSettings())
    ctrl.enter()

    # Ghost motion over the CENTER of card 1 (screen coords): window origin +
    # cell 1 origin (210,10) + half the cell size (90, 65).
    ox, oy = _WIN_ORIGIN
    gx = ox + 210 + 90
    gy = oy + 10 + 65
    ctrl.on_ghost_event(("motion", [(1, gx, gy)]))
    for _ in range(10):
        ctrl._peek_tick(None)                          # no real cursor; ghost drives it

    assert ctrl._peek_progress[1] == pytest.approx(1.0, abs=1e-6)
    assert ctrl._peek_progress[0] == 0.0
    # Card 1 was faded via set_shell_extra_opacity to its net body/portrait targets;
    # the non-hovered visible cards never repainted (idle cards stay opaque).
    card1 = [c for c in provider.shell_opacities if c[0] == 1]
    assert card1, "hovered card 1 must receive a shell-opacity fade"
    _, bg1, portrait1 = card1[-1]
    assert bg1 == pytest.approx(0.65, abs=1e-6)         # PEEK_BODY_OPACITY (net)
    assert portrait1 == pytest.approx(0.25, abs=1e-6)   # PEEK_PORTRAIT_OPACITY (net)
    assert bg1 < 1.0 and portrait1 < 1.0
    assert all(c[0] == 1 for c in provider.shell_opacities)   # only card 1 repainted
    ctrl.leave()


def test_hover_peek_excludes_carved_corner_and_emblem(qapp):
    """The peek hit test follows the PAINTED card shape (rect minus the concave
    carve the emblem nests in): a cursor inside a card's flat rect but within its
    carve circle fades nothing - putting the cursor on the emblem must never make
    any card transparent - while a body point still peeks. The carve scales with
    the cluster transform, so the exclusion holds at non-1.0 scales too."""
    ctrl, provider, window, created = _make(anchor=_GHOST_ANCHOR, settings=_DictSettings())
    ctrl.enter()
    ax, ay = _GHOST_ANCHOR

    def screen_pt(hx, hy, s=1.0):
        # Window origin = anchor - pivot and window pt = pivot + (host - ec) * s,
        # so a host point lands on screen at anchor + (host - emblem_center) * s.
        return (round(ax + (hx - _EMBLEM_CX) * s),
                round(ay + (hy - _EMBLEM_CY) * s))

    # Host (215, 135) is inside cell 1's rect but ~7px from its carve corner
    # (210, 140) - deep inside the cutout_r=96 circle: no fade, no repaint.
    for _ in range(10):
        ctrl._peek_tick(screen_pt(215, 135))
    assert ctrl._peek_progress[1] == 0.0
    assert provider.shell_opacities == []

    # The stub emblem center (110, 90) sits inside cell 0's rect AND inside its
    # carve circle: hovering the emblem itself peeks NO card.
    for _ in range(10):
        ctrl._peek_tick(screen_pt(_EMBLEM_CX, _EMBLEM_CY))
    assert ctrl._peek_progress == [0.0, 0.0, 0.0, 0.0]

    # A card-body point (cell 1 center, outside the carve) still peeks.
    for _ in range(10):
        ctrl._peek_tick(screen_pt(300, 75))
    assert ctrl._peek_progress[1] == pytest.approx(1.0, abs=1e-6)

    # At a settled non-1.0 scale the carve circle tracks the transform - center
    # AND radius. Peek the body first, then probe host (264, 68): distance 90
    # from the carve corner, so it is inside the SCALED circle (90 < 96) but
    # would fall OUTSIDE an unscaled radius (90 * 1.24 > 96) - a regression in
    # either the center mapping or the radius scaling re-peeks the card here.
    ctrl.set_scale_by_notches(3)               # 1.0 + 3 * 0.08 = 1.24
    ctrl._settle_input()
    s = ctrl.scale
    assert s != 1.0
    for _ in range(10):
        ctrl._peek_tick(screen_pt(300, 75, s))
    assert ctrl._peek_progress[1] == pytest.approx(1.0, abs=1e-6)
    for _ in range(10):
        ctrl._peek_tick(screen_pt(264, 68, s))
    assert ctrl._peek_progress[1] == 0.0
    ctrl.leave()


def test_on_ghost_clear_settles_peek_back_to_opaque(qapp):
    """on_ghost_clear() drops the ghost points AND settles a peeked card back to
    fully opaque (bg + portrait == 1.0), so a borrowed card never returns to the
    framed grid stuck dim."""
    ctrl, provider, window, created = _make(anchor=_GHOST_ANCHOR, settings=_DictSettings())
    ctrl.enter()
    ox, oy = _WIN_ORIGIN
    ctrl.on_ghost_event(("motion", [(1, ox + 210 + 90, oy + 10 + 65)]))
    for _ in range(10):
        ctrl._peek_tick(None)
    assert ctrl._peek_progress[1] == pytest.approx(1.0, abs=1e-6)
    provider.shell_opacities.clear()

    ctrl.on_ghost_clear()

    assert ctrl._peek_store.points() == []             # ghost points dropped
    assert ctrl._peek_progress[1] == 0.0               # progress reset
    assert provider.shell_opacities[-1] == (1, 1.0, 1.0)   # settled fully opaque
    ctrl.leave()


def test_peek_tick_noop_during_scale_gesture(qapp):
    """A peek tick during an active scale gesture (BROAD phase) is a no-op: the
    frozen-gesture rule forbids peek state changes mid-zoom."""
    ctrl, provider, window, created = _make(anchor=_GHOST_ANCHOR, settings=_DictSettings())
    ctrl.enter()
    ox, oy = _WIN_ORIGIN
    ctrl.on_ghost_event(("motion", [(1, ox + 210 + 90, oy + 10 + 65)]))
    ctrl.set_scale_by_notches(1)
    assert ctrl._scaling_active is True
    provider.shell_opacities.clear()

    ctrl._peek_tick(None)

    assert provider.shell_opacities == []              # no peek change mid-gesture
    assert ctrl._peek_progress[1] == 0.0
    ctrl.leave()


# ---------------------------------------------------------------------------
# 12b. Ghost/peek hardening: inactive-seed guard, malformed-payload fail-safe,
#      occupancy-drop peek settle, and a NON-1.0-scale ghost-click guard for
#      the framed-local coordinate contract under the cluster transform.
# ---------------------------------------------------------------------------
def test_ghost_event_while_inactive_does_not_seed_and_enter_clears(qapp):
    """FIX A: a queued ghost event arriving while the overlay is FRAMED must NOT seed
    the peek store (a stale hover would otherwise survive into the next enter()), and
    enter() clears the store as defense-in-depth."""
    ctrl, provider, window, created = _make(anchor=_GHOST_ANCHOR, settings=_DictSettings())

    # (1) Inactive: on_ghost_event must NOT seed the store (guards the active-gate;
    # reverting it re-seeds the store here).
    ctrl.on_ghost_event(("motion", [(1, 900, 620)]))
    assert ctrl._peek_store.points() == []

    # (2) Even a store somehow seeded while framed is cleared by enter() (guards the
    # enter-clear; reverting it leaves the injected point in the store after enter).
    ctrl._peek_store.ingest(("motion", [(2, 950, 650)]))
    assert ctrl._peek_store.points() != []
    ctrl.enter()
    assert ctrl._peek_store.points() == []
    ctrl.leave()


def test_on_ghost_event_malformed_payload_never_raises_and_delivers_no_click(qapp):
    """FIX B: a malformed ghost payload (items that are not (slot, x, y) triples) must
    NOT raise into the queued Qt slot and must deliver no click - the bad items are
    dropped in _ghost_payload_to_logical and the whole body is defensively wrapped.
    Reverting the fix makes the 2-tuple unpack raise ValueError (in _ghost_click_pass
    for a press, or GhostPointStore.ingest for a motion)."""
    ctrl, provider, window, created = _make(anchor=_GHOST_ANCHOR, settings=_DictSettings())
    ctrl.enter()

    ctrl.on_ghost_event(("press", [(1, 900)]))          # 2-tuple item (press path)
    assert provider.ghost_clicks == []
    assert ctrl._peek_store.points() == []

    ctrl.on_ghost_event(("motion", [(1, 900)]))         # 2-tuple item (motion path)
    assert ctrl._peek_store.points() == []

    # Other malformed shapes are also safe no-ops.
    ctrl.on_ghost_event("not-a-tuple")
    ctrl.on_ghost_event(("motion", "not-a-list"))
    ctrl.on_ghost_event(("press", [(1, 2, 3, 4)]))      # 4-tuple item
    assert provider.ghost_clicks == []

    # A WELL-FORMED press still delivers after the malformed ones (fail-safe did not
    # wedge the slot): center of cell 1's first control.
    ox, oy = _WIN_ORIGIN
    ctrl.on_ghost_event(("press", [(1, ox + 210 + 8 + 15, oy + 10 + 8 + 9)]))
    assert provider.ghost_clicks == [(1, 23, 17)]
    ctrl.leave()


def test_occupancy_drop_settles_peeked_card_back_to_opaque(qapp):
    """FIX C: a card that is mid hover-peek (progress>0) and then DROPS OUT of the
    visible set on an occupancy nudge is settled back to fully opaque immediately. The
    visible-only _peek_tick never settles a non-visible card, so without the fix the
    card stays stuck extra-dimmed until on_ghost_clear/leave."""
    backend = _RecordingBackend()
    provider = _OccupancyStubProvider(occupied={0, 1, 2, 3})
    ctrl, provider, window, created = _make(
        provider=provider, backend=backend, anchor=_GHOST_ANCHOR,
        settings=_DictSettings())
    ctrl.enter()

    # Peek card 1: a ghost point over its center, then tick to build up progress.
    ox, oy = _WIN_ORIGIN
    ctrl.on_ghost_event(("motion", [(1, ox + 210 + 90, oy + 10 + 65)]))
    for _ in range(10):
        ctrl._peek_tick(None)
    assert ctrl._peek_progress[1] > 0.0
    provider.shell_opacities.clear()

    # Card 1 drops out of occupancy -> reconcile settles it opaque + resets progress.
    provider.set_occupied({0, 2, 3})
    provider.occupied_cells_changed.emit()

    assert 1 not in ctrl._visible_cells
    assert ctrl._peek_progress[1] == 0.0                  # progress reset
    assert (1, 1.0, 1.0) in provider.shell_opacities      # settled fully opaque
    ctrl.leave()


def test_ghost_press_resolves_to_framed_local_coords_at_non_unit_scale(qapp):
    """GUARD (protects the load-bearing scale=self._scale in _ghost_click_pass):
    at a NON-1.0 scale the cells keep their FRAMED 1.0 layout (the zoom is a paint
    transform, never a re-layout), so a ghost 'press' at a control's
    TRANSFORM-MAPPED screen position must resolve back to the framed (1.0)
    cell-root-local coordinate that ``deliver_ghost_click``'s ``childAt`` walk
    expects. Passing 1.0 to ``control_hits`` would keep the at-scale offset and
    deliver a scaled - wrong - point (with scale 1.5 the true (23, 17) would
    arrive as ~(34, 26))."""
    # Save scale 1.5 so enter() restores a non-unit transform scale.
    s = _DictSettings({KEY_SCALE: 1.5})
    ctrl, provider, window, created = _make(anchor=_GHOST_ANCHOR, settings=s)
    ctrl.enter()
    assert ctrl.scale == 1.5

    # Cell 1's first control center, in FRAMED coords: card-local (23, 17),
    # host-local (233, 27) - then its transform-mapped SCREEN position.
    win = ctrl._compute_window_rect()
    cx = 8 + 15
    cy = 8 + 9
    wx, wy = _win_pt(210 + cx, 10 + cy, 1.5)
    ctrl.on_ghost_event(("press", [(1, win.x() + round(wx), win.y() + round(wy))]))

    # Delivered click is the FRAMED cell-root-local coord (control_hits divided
    # the at-scale offset back down by self._scale).
    assert provider.ghost_clicks == [(1, cx, cy)]
    ctrl.leave()


# ---------------------------------------------------------------------------
# 13. Multi-monitor / HiDPI screen-change reshape (T8d)
#
# The single cluster window's input shape is a LOGICAL surface-local path that the
# backend converts to DEVICE pixels via surface.devicePixelRatio() AT APPLY TIME.
# When the window moves to a monitor with a DIFFERENT device-pixel ratio the logical
# path is unchanged but the device conversion changes, so the shape MUST be
# RE-APPLIED at the new DPR (else the click-through region is wrong on the new
# monitor). These tests use a stub surface whose devicePixelRatio() is controllable
# and whose fake windowHandle() exposes a recordable screenChanged signal.
# ---------------------------------------------------------------------------
class _FakeSignal:
    """A minimal screenChanged stand-in recording connect/disconnect + emit, so the
    connect/disconnect LIFECYCLE (not just the _on_screen_changed guard) is exercised
    against the REAL wiring (mirrors tests/test_overlay_topmost.py). disconnect()
    raises (like Qt) when the slot was never connected, so the idempotent guard is
    what keeps double-leave safe."""

    def __init__(self):
        self.slots: list = []

    def connect(self, slot):
        self.slots.append(slot)

    def disconnect(self, slot):
        self.slots.remove(slot)   # bound-method equality; raises if absent (like Qt)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class _FakeWindowHandle:
    def __init__(self):
        self.screenChanged = _FakeSignal()


class _DprStubSurface(_StubSurface):
    """A recording surface with a CONTROLLABLE devicePixelRatio() and a fake
    windowHandle() exposing a recordable screenChanged signal - so a monitor move (a
    DPR change plus a screenChanged emit) can be simulated headlessly. Everything else
    (host/release/geometry/show/hide/deleteLater) is inherited from _StubSurface."""

    def __init__(self, dpr: float = 1.0, host_raises: bool = False,
                 release_raises: bool = False):
        super().__init__(host_raises=host_raises, release_raises=release_raises)
        self._dpr = float(dpr)
        self._handle = _FakeWindowHandle()

    def set_dpr(self, dpr: float) -> None:
        self._dpr = float(dpr)

    def devicePixelRatio(self):
        return self._dpr

    def windowHandle(self):
        return self._handle


def _make_dpr_surface_stub():
    """Build a fresh PLAIN (non-QWidget) recording surface-stub CLASS with a
    controllable ``devicePixelRatio()`` and the exact owned-top-level API the
    controller drives on the radial/panel surfaces (host / set_overlay_geometry /
    prepare_initial_state / show / hide / raise_ / deleteLater). Deliberately NOT a
    QWidget: a real QWidget subclass whose ``deleteLater`` is a no-op leaks a LIVE Qt
    object, which under this venv (Python 3.14 + PySide6 6.10) trips the paint-time GC
    race (the ~1/80 screen-change flake). A plain object has nothing live to leak, yet
    still records geometry + dpr so the screen-change re-apply behavior stays
    observable. Returns a NEW class per call so radial and panel stubs never share
    state."""

    class _DprSurfaceStub:
        def __init__(self, backend=None):
            self._dpr = 1.0
            self.geom = None
            self.raised = 0

        def host(self, widget):
            pass

        def set_overlay_geometry(self, rect):
            self.geom = rect

        def prepare_initial_state(self):
            pass

        def show(self):
            pass

        def hide(self):
            pass

        def raise_(self):
            self.raised += 1

        def deleteLater(self):
            pass

        def set_dpr(self, d):
            self._dpr = float(d)

        def devicePixelRatio(self):
            return self._dpr

    return _DprSurfaceStub


def _make_dpr(dpr: float = 1.0, provider=None, anchor=None, backend=None,
              settings=None):
    """Build a controller whose surface is a _DprStubSurface (controllable DPR + fake
    screenChanged). Returns (controller, provider, window, created)."""
    provider = provider if provider is not None else _StubProvider()
    window = _StubWindow()
    created: list = []

    def factory():
        s = _DprStubSurface(dpr=dpr)
        created.append(s)
        return s

    ctrl = ClusterOverlayController(
        window,
        backend=backend if backend is not None else NoOpOverlayBackend(),
        settings=settings,
        surface_factory=factory,
        card_provider=provider,
    )
    if anchor is not None:
        ctrl._anchor = anchor
    return ctrl, provider, window, created


def test_screen_change_reapplies_cluster_shape_at_new_dpr(qapp):
    """The load-bearing contract: when the window moves to a HiDPI monitor the
    cluster's EXACT input shape is RE-APPLIED with the NEW device-pixel ratio, so the
    backend's device conversion of the (unchanged) LOGICAL path tracks the new
    monitor. Reverting _on_screen_changed's re-apply leaves NO new shape after the
    move (backend.shapes stays empty) and fails the assertion."""
    backend = _RecordingBackend()
    ctrl, provider, window, created = _make_dpr(dpr=1.0, backend=backend)
    ctrl.enter()
    surface = created[0]
    # Settle so the EXACT shape lands at the ORIGINAL dpr (1.0), establishing baseline.
    ctrl._settle_input()
    assert backend.shapes, "expected an exact shape at the original dpr"
    assert backend.shapes[-1][2] == 1.0
    backend.shapes.clear()

    # The window crossed to a HiDPI monitor: its device-pixel ratio is now 2.0.
    surface.set_dpr(2.0)
    ctrl._on_screen_changed()

    cluster_shapes = [s for s in backend.shapes if s[0] is surface]
    assert cluster_shapes, "screen change must re-apply the cluster input shape"
    assert cluster_shapes[-1][2] == 2.0       # ... at the NEW dpr, not the stale 1.0
    ctrl.leave()


def test_screen_change_noop_when_inactive(qapp):
    """A stray screenChanged while FRAMED (never entered / after leave) is a safe
    no-op: nothing applied, nothing armed, no raise. To make the `not self._active`
    early-return LOAD-BEARING, a leftover mid-gesture flag is set: reverting the guard
    would let the handler arm the settle timer even while framed."""
    backend = _RecordingBackend()
    ctrl, provider, window, created = _make_dpr(dpr=1.0, backend=backend)

    # Simulate a stray mid-gesture screenChanged that arrives while FRAMED: with the
    # active-guard removed, the _scaling_active branch would arm the settle timer.
    ctrl._scaling_active = True
    ctrl._on_screen_changed()                  # must not raise

    assert backend.shapes == []                # nothing applied while framed
    assert ctrl._settle_timer is None          # active-guard short-circuited the arm
    assert ctrl.is_active is False


def test_screen_change_reapplies_radial_shape_at_new_dpr(qapp, monkeypatch):
    """With the radial open, a monitor move re-applies the radial surface's input
    shape at the NEW device-pixel ratio too (the radial canvas is LOGICAL; the backend
    converts to device pixels via the surface's dpr at apply time)."""
    backend = _RecordingBackend()

    # PLAIN (non-QWidget) recording stubs: a real QWidget subclass whose deleteLater
    # is a no-op leaks a LIVE Qt object, which under this venv (Python 3.14 +
    # PySide6 6.10) trips the paint-time GC race (~1/80 flake). These expose exactly
    # the surface/menu API the controller drives, with NO live Qt object to leak.
    _DprRadialSurface = _make_dpr_surface_stub()

    class _StubRadialMenu:
        closing = _NoopSignal()     # no-op signal stand-in (plain-object stub)

        def __init__(self, emblem_diameter=0.0, **kw):
            pass

        def set_emblem_diameter(self, d):
            pass

        def start_reveal(self):
            pass

    monkeypatch.setattr("utils.overlay.cluster_surface.RadialSurface", _DprRadialSurface)
    monkeypatch.setattr("utils.overlay.radial_menu.RadialMenuWidget", _StubRadialMenu)

    ctrl, provider, window, created = _make_dpr(dpr=1.0, backend=backend, anchor=(1000, 700))
    ctrl.enter()
    cluster = created[0]
    ctrl.open_radial_menu()
    rsurf = ctrl._radial_surface

    def radial_shapes():
        return [s for s in backend.shapes if s[0] is rsurf]

    # Two applies so far: the persistent surface's EMPTY shape at enter, then
    # the click region once on open - both at dpr 1.0.
    assert len(radial_shapes()) == 2
    assert radial_shapes()[-1][2] == 1.0

    # Both surfaces cross to the HiDPI monitor.
    cluster.set_dpr(2.0)
    rsurf.set_dpr(2.0)
    n_before = len(radial_shapes())
    ctrl._on_screen_changed()

    assert len(radial_shapes()) == n_before + 1   # radial shape RE-APPLIED on the move
    assert radial_shapes()[-1][2] == 2.0           # ... at the new dpr
    ctrl.close_radial_menu()
    ctrl.leave()


def test_screen_change_reapplies_panel_shape_at_new_dpr(qapp, monkeypatch):
    """With the portable panel open, a monitor move re-applies the panel surface's
    full-rect input shape at the NEW device-pixel ratio too."""
    backend = _RecordingBackend()

    # PLAIN (non-QWidget) recording stub - see _make_dpr_surface_stub: no live Qt
    # object to leak into the paint-time GC race, host() is a no-op (the panel's
    # click shape re-apply, not the reparent, is what these tests assert).
    _DprPanelSurface = _make_dpr_surface_stub()

    monkeypatch.setattr("utils.overlay.cluster_surface.PanelSurface", _DprPanelSurface)

    ctrl, provider, window, created = _make_dpr(dpr=1.0, backend=backend, anchor=(1000, 700))
    ctrl.enter()
    cluster = created[0]
    psurf = ctrl.open_panel_surface(object())   # hosted content placeholder (host is a no-op)

    def panel_shapes():
        return [s for s in backend.shapes if s[0] is psurf]

    # Two applies so far: the persistent surface's EMPTY shape at enter, then
    # the full-rect click region once on open - both at dpr 1.0.
    assert len(panel_shapes()) == 2
    assert panel_shapes()[-1][2] == 1.0

    cluster.set_dpr(2.0)
    psurf.set_dpr(2.0)
    n_before = len(panel_shapes())
    ctrl._on_screen_changed()

    assert len(panel_shapes()) == n_before + 1    # panel shape RE-APPLIED on the move
    assert panel_shapes()[-1][2] == 2.0            # ... at the new dpr
    ctrl.close_panel_surface()
    ctrl.leave()


def test_screen_change_defers_all_reshapes_during_active_scale(qapp, monkeypatch):
    """The ACTIVE broad-phase deferral: when a scale gesture is genuinely mid-flight
    (``_scaling_active`` True) a monitor move must DEFER every input-shape re-apply to
    the settle timer instead of narrowing the X11 capture region under the pointer -
    re-applying mid-scroll stalls the wheel stream.

    With the cluster ACTIVE, the radial AND the panel open, and a fresh (higher) DPR,
    ``_on_screen_changed`` must (a) ARM the settle timer rather than apply the exact
    cluster shape immediately, and (b) NOT re-apply the radial's or panel's click shape
    immediately either. Re-centering (``_reposition_radial``/``_reposition_panel``)
    still runs - it is cheap and schedules its OWN deferred reshape - so only the
    IMMEDIATE full-shape re-apply is withheld.

    Red-green: forcing ``_apply_exact_input_shape()`` (or the immediate radial/panel
    reapply) during an active scale lands a shape at the NEW dpr and fails the
    'no new shape' / 'nothing at dpr 2.0' assertions below. The only existing active-
    flag screen-change test sets the flag while INACTIVE, proving the inactive guard -
    NOT this active deferral branch."""
    backend = _RecordingBackend()

    # Plain, non-QWidget stubs (see _make_dpr_surface_stub): no live Qt object to leak
    # into the paint-time GC race.
    _DprRadialSurface = _make_dpr_surface_stub()
    _DprPanelSurface = _make_dpr_surface_stub()

    class _StubRadialMenu:
        closing = _NoopSignal()     # no-op signal stand-in (plain-object stub)

        def __init__(self, emblem_diameter=0.0, **kw):
            pass

        def set_emblem_diameter(self, d):
            pass

        def start_reveal(self):
            pass

    monkeypatch.setattr("utils.overlay.cluster_surface.RadialSurface", _DprRadialSurface)
    monkeypatch.setattr("utils.overlay.radial_menu.RadialMenuWidget", _StubRadialMenu)
    monkeypatch.setattr("utils.overlay.cluster_surface.PanelSurface", _DprPanelSurface)

    ctrl, provider, window, created = _make_dpr(dpr=1.0, backend=backend, anchor=(1000, 700))
    ctrl.enter()
    cluster = created[0]
    ctrl._settle_input()                        # baseline EXACT cluster shape at dpr 1.0
    ctrl.open_radial_menu()
    rsurf = ctrl._radial_surface
    psurf = ctrl.open_panel_surface(object())   # hosted content placeholder (host no-op)

    def cluster_shapes():
        return [s for s in backend.shapes if s[0] is cluster]

    def radial_shapes():
        return [s for s in backend.shapes if s[0] is rsurf]

    def panel_shapes():
        return [s for s in backend.shapes if s[0] is psurf]

    n_cluster = len(cluster_shapes())
    n_radial = len(radial_shapes())
    n_panel = len(panel_shapes())
    assert n_radial >= 1 and n_panel >= 1        # each shaped once on open (dpr 1.0)

    # A scale gesture is genuinely LIVE, and the window crosses to a HiDPI monitor.
    ctrl._scaling_active = True
    cluster.set_dpr(2.0)
    rsurf.set_dpr(2.0)
    psurf.set_dpr(2.0)
    ctrl._on_screen_changed()

    # DEFERRED: the settle timer is armed for the cluster's exact reshape ...
    assert ctrl._settle_timer is not None
    assert ctrl._settle_timer.isActive()
    # ... and NOTHING was re-applied IMMEDIATELY at the new dpr - not the cluster, not
    # the radial, not the panel.
    assert len(cluster_shapes()) == n_cluster
    assert len(radial_shapes()) == n_radial
    assert len(panel_shapes()) == n_panel
    assert not any(s[2] == 2.0 for s in backend.shapes)

    # Draining the settle timer DOES land the deferred exact cluster shape at the new
    # dpr - proving the reshape was DEFERRED, not dropped.
    ctrl._settle_input()
    assert any(s[0] is cluster and s[2] == 2.0 for s in cluster_shapes())

    ctrl.close_panel_surface()
    ctrl.close_radial_menu()
    ctrl.leave()


def test_enter_connects_screen_change_leave_disconnects(qapp):
    """Lifecycle: enter() connects the surface's screenChanged (when windowHandle is
    available); leave() disconnects; both are idempotent (double-enter/leave safe);
    and a screenChanged after leave() is a no-op."""
    backend = _RecordingBackend()
    ctrl, provider, window, created = _make_dpr(dpr=1.0, backend=backend)
    ctrl.enter()
    surface = created[0]
    handle = surface.windowHandle()

    # enter() connected exactly one slot.
    assert ctrl._screen_change_connected is True
    assert len(handle.screenChanged.slots) == 1

    # Double-enter (already active -> a no-op) must NOT double-connect.
    ctrl.enter()
    assert len(handle.screenChanged.slots) == 1

    # A REAL screenChanged emit while active drives the reshape at the fresh DPR.
    ctrl._settle_input()                        # exact shape at dpr 1.0
    surface.set_dpr(2.0)
    backend.shapes.clear()
    handle.screenChanged.emit(object())
    assert any(s[0] is surface and s[2] == 2.0 for s in backend.shapes)

    ctrl.leave()

    # leave() disconnected the slot.
    assert ctrl._screen_change_connected is False
    assert handle.screenChanged.slots == []

    # Idempotent: a second leave (a no-op) is safe, and a stray post-leave emit does
    # nothing (the slot is gone AND _active is False).
    ctrl.leave()
    backend.shapes.clear()
    handle.screenChanged.emit(object())         # no slots -> nothing fires
    assert backend.shapes == []


def test_enter_leave_enter_reconnects_screen_change(qapp):
    """A fresh enter after leave re-connects screenChanged on the NEW surface's
    handle (the guard flag reset in leave lets the re-enter connect again)."""
    ctrl, provider, window, created = _make_dpr(dpr=1.0)
    ctrl.enter()
    ctrl.leave()
    assert ctrl._screen_change_connected is False

    ctrl.enter()
    assert ctrl._screen_change_connected is True
    surface2 = created[1]
    assert len(surface2.windowHandle().screenChanged.slots) == 1
    ctrl.leave()


# ---------------------------------------------------------------------------
# connect_emblem: wire the _Emblem gesture signals (Task 9)
#
# A straight port of OverlayGroupController.connect_emblem: the three gesture
# signals map to toggle()/begin_group_drag()/set_scale_by_notches(). Live in both
# modes (the controller methods are mode-aware); idempotent (re-connecting the
# SAME emblem is a no-op, never double-firing) and re-bindable (a NEW emblem drops
# the previous emblem's three connections).
# ---------------------------------------------------------------------------
class _SignalEmblem(QObject):
    """Minimal stand-in carrying the three real _Emblem gesture signals."""
    toggle_requested = Signal()
    move_requested = Signal()
    resize_scrolled = Signal(int)


def test_connect_emblem_wires_the_three_signals(qapp):
    ctrl, _p, _w, _c = _make()
    calls = {"toggle": 0, "drag": 0, "scale": []}
    # Spy BEFORE connect so the bound lookups in connect_emblem resolve to these
    # instance attributes (mirrors the group_controller wiring test).
    ctrl.toggle = lambda: calls.__setitem__("toggle", calls["toggle"] + 1)
    ctrl.begin_group_drag = lambda: calls.__setitem__("drag", calls["drag"] + 1)
    ctrl.set_scale_by_notches = lambda n: calls["scale"].append(n)

    emblem = _SignalEmblem()
    ctrl.connect_emblem(emblem)
    assert ctrl._emblem is emblem

    emblem.toggle_requested.emit()
    emblem.move_requested.emit()
    emblem.resize_scrolled.emit(2)

    assert calls["toggle"] == 1
    assert calls["drag"] == 1
    assert calls["scale"] == [2]        # the int notch passes through


def test_connect_emblem_is_idempotent_no_double_fire(qapp):
    ctrl, _p, _w, _c = _make()
    calls = {"toggle": 0}
    ctrl.toggle = lambda: calls.__setitem__("toggle", calls["toggle"] + 1)
    emblem = _SignalEmblem()
    ctrl.connect_emblem(emblem)
    ctrl.connect_emblem(emblem)         # SAME emblem -> no-op, must NOT double-fire
    emblem.toggle_requested.emit()
    assert calls["toggle"] == 1


def test_connect_emblem_rebinds_to_a_new_emblem(qapp):
    ctrl, _p, _w, _c = _make()
    calls = {"toggle": 0, "drag": 0, "scale": []}
    ctrl.toggle = lambda: calls.__setitem__("toggle", calls["toggle"] + 1)
    ctrl.begin_group_drag = lambda: calls.__setitem__("drag", calls["drag"] + 1)
    ctrl.set_scale_by_notches = lambda n: calls["scale"].append(n)

    old, new = _SignalEmblem(), _SignalEmblem()
    ctrl.connect_emblem(old)
    ctrl.connect_emblem(new)            # drops old's three connections
    assert ctrl._emblem is new

    # The OLD emblem no longer drives the controller (all three disconnected).
    old.toggle_requested.emit()
    old.move_requested.emit()
    old.resize_scrolled.emit(5)
    assert calls == {"toggle": 0, "drag": 0, "scale": []}

    # The NEW emblem drives it.
    new.toggle_requested.emit()
    new.move_requested.emit()
    new.resize_scrolled.emit(7)
    assert calls["toggle"] == 1
    assert calls["drag"] == 1
    assert calls["scale"] == [7]


# ---------------------------------------------------------------------------
# Taskbar representative (float UI owns the taskbar)
# ---------------------------------------------------------------------------
class _AvailableBackend(NoOpOverlayBackend):
    """is_available True so enter() builds the taskbar representative; records
    the representative-specific hint calls."""

    def __init__(self):
        self.rep_state: list = []
        self.opacities: list = []

    def is_available(self):
        return True

    def set_rep_initial_state(self, window):
        self.rep_state.append(window)

    def set_window_opacity(self, window, opacity):
        self.opacities.append((window, float(opacity)))


class _MirrorAtOpacityBackend(_AvailableBackend):
    """Also snapshots the rep's installed mirror object at every opacity write,
    to pin the paint-before-opacity ordering of the unblank."""

    def __init__(self):
        super().__init__()
        self.mirror_at_opacity: list = []

    def set_window_opacity(self, window, opacity):
        super().set_window_opacity(window, opacity)
        self.mirror_at_opacity.append((float(opacity), window._mirror))


class _FakeSpontaneousClose:
    def __init__(self):
        self.ignored = False

    def spontaneous(self):
        return True

    def ignore(self):
        self.ignored = True

    def accept(self):
        pass


def test_enter_builds_taskbar_rep_and_leave_destroys_it(qapp):
    backend = _AvailableBackend()
    ctrl, provider, window, created = _make(backend=backend)
    assert ctrl.enter() is True
    rep = ctrl._taskbar_rep
    assert rep is not None
    assert rep.isVisible()
    assert backend.rep_state == [rep]              # pre-map keep-below hint
    # Pre-map opacity STAGE only (a mapped window with no buffer composites
    # BLACK - probed); the first real paint lifts it. Every write at enter is
    # a 0.0 stage (rep + persistent radial/panel) - nothing map-time-visible.
    assert [(w, o) for w, o in backend.opacities if w is rep] == [(rep, 0.0)]
    assert all(o == 0.0 for _, o in backend.opacities)
    assert rep.is_blanked() is False                # settled state at enter
    # First mirror grabbed BEFORE the map: the entry never shows a blank preview.
    assert rep._mirror is not None and not rep._mirror.isNull()
    ctrl.leave()
    assert ctrl._taskbar_rep is None


def test_taskbar_rep_torn_down_when_leave_teardown_step_raises(qapp):
    """FAIL-CLOSED PIN: the representative may not outlive leave() on ANY path.
    A raising teardown step (here the settings save flush, the first step of
    leave()'s try) is swallowed, but the unconditional tail must still destroy
    the rep - a survivor would be a stale mapped keep-below window painting the
    old mirror, plus a live taskbar/Alt-Tab entry beside the restored framed
    app's own."""
    backend = _AvailableBackend()
    ctrl, provider, window, created = _make(backend=backend)
    assert ctrl.enter() is True
    assert ctrl._taskbar_rep is not None

    def _boom():
        raise RuntimeError("flush boom")

    ctrl.flush_pending_save = _boom
    ctrl.leave()                            # must not raise
    assert ctrl._taskbar_rep is None        # the rep may not outlive leave()
    # The existing fail-closed invariants still hold on this path.
    assert window.normaled == 1
    assert ctrl.is_active is False
    assert provider.restored == [provider._token]
    assert provider._grid_host.parent() is provider._holder


def test_no_taskbar_rep_without_backend(qapp):
    """No X11 backend -> no thumbnail mechanism to lean on: the plain hide()
    behavior stands alone and nothing extra is mapped."""
    ctrl, provider, window, created = _make()      # NoOp backend: unavailable
    ctrl.enter()
    assert ctrl._taskbar_rep is None
    ctrl.leave()


def test_rep_close_request_routes_to_main_window_close(qapp):
    """Taskbar Close on the representative = the radial-Exit quit path (the
    main window's close() -> shutdown -> app quit)."""
    backend = _AvailableBackend()
    ctrl, provider, window, created = _make(backend=backend)
    ctrl.enter()
    rep = ctrl._taskbar_rep
    ev = _FakeSpontaneousClose()
    rep.closeEvent(ev)
    assert ev.ignored
    for _ in range(3):
        qapp.processEvents()                       # run the deferred callback
    assert window.closed == 1
    ctrl.leave()


def test_occupancy_change_refreshes_rep_mirror(qapp):
    backend = _AvailableBackend()
    provider = _OccupancyStubProvider({0, 1, 2, 3})
    ctrl, provider, window, created = _make(provider=provider, backend=backend)
    ctrl.enter()
    rep = ctrl._taskbar_rep
    first = rep._mirror
    # {1} MOVES the bbox min-corner (cell 0 at host (10,10) was the min; the
    # emblem-union-cell-1 bbox starts at host (60,10)): the rep must be
    # RE-ALIGNED, not just re-grabbed - a stale origin would offset every
    # mirror pixel into a persistent visible ghost over bare desktop.
    provider.set_occupied({1})
    provider.occupied_cells_changed.emit()
    assert rep._mirror is not first                # re-grabbed on occupancy
    expected = ctrl._content_bbox_window_coords().translated(
        ctrl._compute_window_rect().topLeft())
    assert rep.geometry() == expected              # re-ALIGNED on occupancy


def test_content_bbox_covers_emblem_and_cells_and_is_a_crop(qapp):
    ctrl, provider, window, created = _make()
    ctrl.enter()
    bbox = ctrl._content_bbox_window_coords()
    assert bbox.contains(QPoint(*_PIVOT))          # emblem center renders on the pivot
    assert bbox.contains(QPoint(*_VISIBLE_CONTROL_PROBE))
    env_w, env_h = _ENV_SIZE
    assert bbox.width() < env_w and bbox.height() < env_h   # a CROP, not the envelope
    ctrl.leave()


def test_rep_blanked_during_scale_gesture_and_restored_at_settle(qapp):
    """The aligned-mirror invariant cannot hold mid-gesture: the rep must be
    blanked while _scaling_active and unblanked (with a fresh mirror) once
    _settle_input runs."""
    backend = _AvailableBackend()
    ctrl, provider, window, created = _make(backend=backend)
    ctrl.enter()
    rep = ctrl._taskbar_rep
    ctrl._scaling_active = True
    ctrl._update_rep_blanking()
    assert rep.is_blanked() is True
    before = rep._mirror
    ctrl._settle_input()                           # clears the flag + updates
    assert rep.is_blanked() is False
    assert rep._mirror is not before               # re-grabbed at settle
    ctrl.leave()


def test_unblank_aligns_and_regrabs_before_opacity_write(qapp):
    """ORDERING PIN: the opacity-1 write is the LAST step of the unblank. The
    opacity hint flushes on the xlib connection immediately while the
    re-align/re-grab land as Qt-side paints - unblanking first would show one
    full-opacity frame of the STALE mirror at the OLD position after every
    drag end / scale settle. At the moment of the opacity-1 write the fresh
    mirror must already be installed."""
    backend = _MirrorAtOpacityBackend()
    ctrl, provider, window, created = _make(backend=backend)
    ctrl.enter()
    rep = ctrl._taskbar_rep
    ctrl._scaling_active = True
    ctrl._update_rep_blanking()
    assert rep.is_blanked() is True
    stale = rep._mirror
    ctrl._settle_input()                           # unblank terminal
    assert rep.is_blanked() is False
    ones = [m for (op, m) in backend.mirror_at_opacity if op == 1.0]
    assert ones and ones[-1] is not stale          # fresh mirror BEFORE opacity 1
    ctrl.leave()


def test_rep_blanked_while_peek_active(qapp):
    """A hover-peeked (faded) card breaks pixel identity with the opaque
    mirror behind it: peek-active must blank the rep."""
    backend = _AvailableBackend()
    ctrl, provider, window, created = _make(backend=backend)
    ctrl.enter()
    rep = ctrl._taskbar_rep
    ctrl._rep_peek_active = True
    ctrl._update_rep_blanking()
    assert rep.is_blanked() is True
    ctrl._rep_peek_active = False
    ctrl._update_rep_blanking()
    assert rep.is_blanked() is False
    ctrl.leave()


def test_rep_blanked_during_drag_and_restored_at_end(qapp, monkeypatch):
    """A drag moves the cluster out from over the mirror: drag start must blank
    the rep, and drag end must unblank it with a fresh re-anchored mirror."""
    from PySide6.QtGui import QCursor
    backend = _AvailableBackend()
    ctrl, provider, window, created = _make(backend=backend, anchor=(400, 400))
    ctrl.enter()
    rep = ctrl._taskbar_rep
    assert rep.is_blanked() is False

    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: QPoint(100, 100)))
    ctrl.begin_group_drag()
    assert ctrl._drag_timer is not None and ctrl._drag_timer.isActive()
    assert rep.is_blanked() is True                # gesture live -> blanked
    before = rep._mirror
    ctrl._end_drag()
    assert rep.is_blanked() is False               # drag over -> restored
    assert rep._mirror is not before               # re-grabbed at drag end
    ctrl.leave()


def test_rep_blanked_while_radial_open(qapp, monkeypatch):
    """The radial dims the cluster (internal dim + ring): the mirror behind it
    would shine through undimmed, so radial-open must blank the rep and
    close must restore it."""
    _patch_radial(monkeypatch)
    backend = _AvailableBackend()
    ctrl, provider, window, created = _make(backend=backend)
    ctrl.enter()
    rep = ctrl._taskbar_rep
    assert rep.is_blanked() is False

    menu = ctrl.open_radial_menu()
    assert menu is not None
    assert rep.is_blanked() is True                # radial up -> blanked
    ctrl.close_radial_menu()
    assert rep.is_blanked() is False               # radial gone -> restored
    ctrl.leave()


def test_peek_tick_latch_drives_rep_blanking(qapp):
    """The ~30ms peek poll keeps the rep's peek latch in sync: a cursor over a
    card body blanks the rep (the faded card would break pixel identity with
    the opaque mirror), and moving off every card unblanks it."""
    backend = _AvailableBackend()
    ctrl, provider, window, created = _make(
        backend=backend, anchor=_GHOST_ANCHOR, settings=_DictSettings())
    ctrl.enter()
    rep = ctrl._taskbar_rep
    ax, ay = _GHOST_ANCHOR

    # Cell 1's body center (host 300, 75), outside the carve: screen point =
    # anchor + (host - emblem_center) - the same math the existing peek tests use.
    on_card = (ax + (300 - _EMBLEM_CX), ay + (75 - _EMBLEM_CY))
    ctrl._peek_tick(on_card)
    assert ctrl._rep_peek_active is True
    assert rep.is_blanked() is True                # peek live -> blanked

    ctrl._peek_tick((ax + 4000, ay + 4000))        # far off every card
    assert ctrl._rep_peek_active is False
    assert rep.is_blanked() is False               # peek over -> restored
    ctrl.leave()


def test_opaque_only_strips_subopaque_pixels(qapp):
    """The on-screen rep may only paint pixels the cluster hides with identical
    fully-opaque ones: translucent pixels (shadows, AA edges) would
    double-composite and read darker inside the bbox."""
    from PySide6.QtGui import QImage, QPixmap
    img = QImage(2, 1, QImage.Format_ARGB32)
    img.setPixelColor(0, 0, QColor(255, 0, 170, 255))    # opaque: kept
    img.setPixelColor(1, 0, QColor(255, 0, 170, 128))    # translucent: stripped
    out = ClusterOverlayController._opaque_only(QPixmap.fromImage(img)).toImage()
    assert out.pixelColor(0, 0).alpha() == 255
    assert out.pixelColor(1, 0).alpha() == 0
