"""Tests for ClusterOverlayController: enter / leave / borrow / metrics-reset.

The single-window cluster controller borrows the WHOLE `_grid_host` subtree into
one ``ClusterSurface`` (instead of one surface per card), minimizes the main
window, and on leave restores the host + resets framed (scale-1.0) metrics. It is
a drop-in analog of ``OverlayGroupController`` for the single-window cluster, and
mirrors its minimize, fail-closed, and orphan-retention discipline.

These tests use LIGHT STUBS (no heavy real _CompactLayout): a stub provider whose
capture/restore record calls and ACTUALLY re-parent a real `_grid_host` (capture
detaches it; restore re-parents it to a holder widget), a stub window recording
showMinimized/showNormal, and a stub surface recording host/geometry/show/hide/
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
from PySide6.QtWidgets import QWidget

from utils.overlay.backend import NoOpOverlayBackend
from utils.overlay.cluster_controller import ClusterOverlayController
from utils.overlay.cluster_surface import ClusterSurface
from utils.overlay.persistence import KEY_ANCHOR, KEY_MONITOR, KEY_SCALE
from utils.overlay.scale import SCALE_MAX, SCALE_MIN


# Known cluster geometry baked into the stub provider so placement is exact.
_HOST_W, _HOST_H = 400, 300
# OFF-CENTER emblem so emblem_center_local (60+50, 40+50) = (110, 90) differs from
# the bbox center (200, 150) - this pins the emblem-center invariant and would
# catch a bbox-center regression.
_EMBLEM_X, _EMBLEM_Y, _EMBLEM_S = 60, 40, 100
_EMBLEM_CX = _EMBLEM_X + _EMBLEM_S // 2   # 110
_EMBLEM_CY = _EMBLEM_Y + _EMBLEM_S // 2   # 90

# Four card cells parented under the grid host at known WINDOW-LOCAL origins
# (cells live in the grid host, exactly like the real _CompactLayout), each
# exposing two CARD-LOCAL control rects via control_rects() - matching the real
# _CompactLayout.control_rects(cell_index) -> list[QRect] signature. The exact
# input union translates each card-local control rect by its cell origin into
# window-local coords.
_CELL_ORIGINS = {0: (10, 10), 1: (210, 10), 2: (10, 160), 3: (210, 160)}
_CELL_SIZE = (180, 130)
_CONTROL_RECTS_LOCAL = [QRect(8, 8, 30, 18), QRect(8, 40, 30, 18)]   # card-local

# A control point that lands inside cell 1's first control (window-local
# (218,18,30,18)) but OUTSIDE the emblem - so an emblem-only union (the
# production card_cell_rects regression) would NOT contain it.
_CONTROL_PROBE = (220, 20)
# A control point inside cell 0's first control (window-local (18,18,30,18)) and
# OUTSIDE the emblem - the occupancy tests use it as the VISIBLE-card probe paired
# with _CONTROL_PROBE (cell 1) as the EMPTY-card probe.
_VISIBLE_CONTROL_PROBE = (20, 20)


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
        self.last_metrics = metrics
        # Real apply_metrics changes each card's size, so the host's sizeHint (and
        # thus the cluster window) grows/shrinks with scale. Mirror that here so a
        # notch OBSERVABLY resizes the surface: scale the host + (off-center)
        # emblem geometry by metrics.scale.
        s = metrics.scale
        self._grid_host.resize(round(_HOST_W * s), round(_HOST_H * s))
        self._emblem.setGeometry(
            round(_EMBLEM_X * s), round(_EMBLEM_Y * s),
            round(_EMBLEM_S * s), round(_EMBLEM_S * s),
        )

    @property
    def _card_slots(self):
        """Mirror _CompactLayout._card_slots: the list of cell dicts (each with a
        ``"cell"`` widget). The controller reads the cell origin from these to
        translate control_rects into window-local coords."""
        return [{"cell": cw} for cw in self._cell_widgets]

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
    ``setVisible`` is shadowed at the INSTANCE level so a stray ``setVisible(False)``
    - a pinwheel collapse, which this task forbids - is recorded and assertable.
    Instance shadowing (not a virtual override) catches only PYTHON-level calls, so
    Qt's own internal visibility changes are not mistaken for a controller collapse."""

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
                sink.append(cw)
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


class _ScaledStubProvider:
    """Like ``_StubProvider`` but ``apply_metrics`` FAITHFULLY scales the cell origins
    AND the control rects by ``metrics.scale`` - mirroring how the real
    ``_CompactLayout`` physically resizes the card widgets so both the cell
    screen-geometry and ``control_rects()`` come back AT-SCALE.

    The plain ``_StubProvider`` only scales ``_grid_host`` + ``_emblem``, leaving the
    cell origins + control rects at their base (scale-1.0) values, so at any scale its
    at-scale layout is a fiction. That makes ``control_hits(..., 1.0)`` and
    ``control_hits(..., self._scale)`` INDISTINGUISHABLE (a ghost-click regression
    that reintroduced ``/ self._scale`` would pass unnoticed). This stub models a REAL
    at-scale layout so a NON-1.0-scale ghost-click test can pin the load-bearing
    ``scale=1.0`` decision in ``_ghost_click_pass``."""

    def __init__(self):
        self._holder = QWidget()
        self._grid_host = QWidget(self._holder)
        self._grid_host.resize(_HOST_W, _HOST_H)
        self._emblem = QWidget(self._grid_host)
        self._emblem.setGeometry(_EMBLEM_X, _EMBLEM_Y, _EMBLEM_S, _EMBLEM_S)
        self._scale = 1.0
        self._cell_widgets = []
        for i in range(4):
            cw = QWidget(self._grid_host)
            ox, oy = _CELL_ORIGINS[i]
            cw.setGeometry(ox, oy, *_CELL_SIZE)
            self._cell_widgets.append(cw)
        self._token = object()
        self.ghost_clicks: list = []
        self.shell_opacities: list = []

    def capture_cluster_host(self):
        self._grid_host.setParent(None)
        return self._token

    def restore_cluster_host(self, token):
        self._grid_host.setParent(self._holder)

    def apply_metrics(self, metrics):
        s = metrics.scale
        self._scale = s
        self._grid_host.resize(round(_HOST_W * s), round(_HOST_H * s))
        self._emblem.setGeometry(
            round(_EMBLEM_X * s), round(_EMBLEM_Y * s),
            round(_EMBLEM_S * s), round(_EMBLEM_S * s))
        # Faithfully move + resize each cell so its origin within the grid host and
        # its size are AT-SCALE (like the real physical card resize).
        for i, cw in enumerate(self._cell_widgets):
            ox, oy = _CELL_ORIGINS[i]
            cw.setGeometry(round(ox * s), round(oy * s),
                           round(_CELL_SIZE[0] * s), round(_CELL_SIZE[1] * s))

    @property
    def _card_slots(self):
        return [{"cell": cw} for cw in self._cell_widgets]

    def control_rects(self, cell_index):
        """AT-SCALE card-local control rects (the real _CompactLayout returns the
        controls at the current scale, not the framed base rects)."""
        s = self._scale
        return [QRect(round(r.x() * s), round(r.y() * s),
                      round(r.width() * s), round(r.height() * s))
                for r in _CONTROL_RECTS_LOCAL]

    def deliver_ghost_click(self, cell_index, x, y):
        self.ghost_clicks.append((cell_index, x, y))

    def set_shell_extra_opacity(self, cell_index, bg_opacity, portrait_opacity):
        self.shell_opacities.append(
            (cell_index, round(float(bg_opacity), 4), round(float(portrait_opacity), 4)))


def _make(provider=None, window=None, host_raises=False, release_raises=False,
          on_active_changed=None, anchor=None, backend=None, settings=None):
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
    )
    if anchor is not None:
        ctrl._anchor = anchor   # inject a known anchor for exact placement
    return ctrl, provider, window, created


# ---------------------------------------------------------------------------
# 1. enter() borrows + minimizes + places at the EXACT emblem-centered rect
# ---------------------------------------------------------------------------
def test_enter_borrows_minimizes_and_places_emblem_on_anchor(qapp):
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
    # EXACT placement: the window is sized to the host and positioned so the
    # OFF-CENTER emblem center lands on the anchor (NOT the bbox center).
    ax, ay = anchor
    assert surface.geom == QRect(ax - _EMBLEM_CX, ay - _EMBLEM_CY, _HOST_W, _HOST_H)
    assert surface.shown == 1
    assert window.minimized == 1
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

    # (b) exactly ONE shape applied on enter, and it is the settled EXACT shape.
    assert ctrl._input_phase == "exact"
    assert len(backend.shapes) == 1
    win, path, _dpr = backend.shapes[0]
    assert win is surface
    # Solid over the emblem + every visible card's controls (click-catching)...
    assert path.contains(QPointF(_EMBLEM_CX, _EMBLEM_CY))
    assert path.contains(QPointF(*_VISIBLE_CONTROL_PROBE))   # cell 0 control
    assert path.contains(QPointF(*_CONTROL_PROBE))           # cell 1 control
    # ...but CLICK-THROUGH over a gap (a cell interior away from its controls and
    # the emblem): the shape is the exact union, not the full window rect.
    assert not path.contains(QPointF(380, 280))


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
    assert window.minimized == 1            # not minimized again


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
    assert window.minimized == 2
    assert ctrl._orphans == []              # nothing orphaned across clean cycles


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
    assert provider._grid_host.parent() is provider._holder
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


def test_notch_resizes_surface_and_applies_broad_shape(qapp):
    """One notch: applies metrics, RESIZES the cluster window (size changed), and
    applies a BROAD (full-window-rect) input shape; scaling-active in 'broad'."""
    backend = _RecordingBackend()
    ctrl, provider, window, created = _make(backend=backend)
    ctrl.enter()
    surface = created[0]
    geom_before = surface.geom
    backend.shapes.clear()                       # ignore any enter-time shaping

    ctrl.set_scale_by_notches(1)

    # Metrics applied at the new scale, and the surface was resized (one resize).
    assert provider.last_metrics.scale == ctrl.scale
    assert surface.geom != geom_before
    # Broad phase: scaling active, one broad apply of the FULL window-local rect.
    assert ctrl._scaling_active is True
    assert ctrl._input_phase == "broad"
    assert len(backend.shapes) == 1
    win, broad_path, _dpr = backend.shapes[0]
    assert win is surface
    assert broad_path.boundingRect().toRect() == QRect(
        0, 0, surface.geom.width(), surface.geom.height())


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
    # The exact union must CONTAIN a real (translated) card control - a point that
    # is inside a control but outside the emblem. An emblem-only union (the
    # production card_cell_rects regression, where the real provider lacks that
    # method) would NOT contain it.
    from PySide6.QtCore import QPointF
    assert exact_path.contains(QPointF(*_CONTROL_PROBE))


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


def test_notch_keeps_emblem_center_on_anchor(qapp):
    """The scaling anchor invariant: after a notch (the emblem geometry changes
    with apply_metrics), the emblem center still lands exactly on the anchor."""
    anchor = (1234, 567)
    ctrl, provider, window, created = _make(anchor=anchor)
    ctrl.enter()
    surface = created[0]

    ctrl.set_scale_by_notches(1)

    g = provider._emblem.geometry()              # scaled by apply_metrics
    cx = g.x() + g.width() // 2
    cy = g.y() + g.height() // 2
    assert surface.geom.x() + cx == anchor[0]
    assert surface.geom.y() + cy == anchor[1]


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


def test_occupancy_change_reapplies_input_without_hiding_or_reshaping(qapp):
    """An occupancy nudge re-reads occupied_cells, updates _visible_cells, and
    RE-APPLIES the input shape (a new apply) - WITHOUT hiding any grid cell and
    WITHOUT resizing/reshaping the window (the grid shell stays fixed)."""
    backend = _RecordingBackend()
    provider = _OccupancyStubProvider(occupied={0, 2})
    ctrl, provider, window, created = _make(provider=provider, backend=backend)
    ctrl.enter()
    surface = created[0]
    geom_before = surface.geom
    backend.shapes.clear()

    provider.set_occupied({1, 3})
    provider.occupied_cells_changed.emit()

    assert ctrl._visible_cells == {1, 3}
    assert len(backend.shapes) >= 1              # input shape RE-APPLIED
    assert surface.geom == geom_before           # window NOT resized/reshaped
    assert provider.hidden_cells == []           # NO grid cell setVisible(False)
    # The new union now blocks the newly-occupied cell 1 and frees the now-empty 0.
    new_path = backend.shapes[-1][1]
    assert new_path.contains(QPointF(*_CONTROL_PROBE))                # cell 1 visible
    assert not new_path.contains(QPointF(*_VISIBLE_CONTROL_PROBE))    # cell 0 empty


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
    # cell 1 (now empty) out.
    ctrl._settle_input()
    exact_path = backend.shapes[-1][1]
    assert exact_path.contains(QPointF(*_VISIBLE_CONTROL_PROBE))      # cell 0 visible
    assert not exact_path.contains(QPointF(*_CONTROL_PROBE))           # cell 1 empty


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
    (clamped) anchor; the cluster window is sized at the RESTORED scale (the host
    is resized via apply_metrics) and the scaled emblem center lands on the anchor."""
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    name = screen.name()
    g = screen.geometry()
    inside = (g.left() + 120, g.top() + 120)   # well inside -> clamp keeps it
    s = _DictSettings({KEY_ANCHOR: list(inside), KEY_SCALE: 1.5, KEY_MONITOR: name})

    ctrl, provider, window, created = _make(settings=s)
    assert ctrl.enter() is True

    assert ctrl._scale == 1.5
    assert ctrl._anchor == inside
    surface = created[0]
    # The window spans the host at the RESTORED scale (host resized by apply_metrics).
    assert surface.geom.width() == round(_HOST_W * 1.5)
    assert surface.geom.height() == round(_HOST_H * 1.5)
    # The (scaled) emblem center still lands exactly on the saved anchor.
    emb_cx = round(_EMBLEM_X * 1.5) + round(_EMBLEM_S * 1.5) // 2
    emb_cy = round(_EMBLEM_Y * 1.5) + round(_EMBLEM_S * 1.5) // 2
    assert surface.geom.x() + emb_cx == inside[0]
    assert surface.geom.y() + emb_cy == inside[1]
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

        def prepare_initial_state(self):
            self.prepared += 1

        def show(self):
            self.shown += 1

        def hide(self):
            self.hidden += 1

        def deleteLater(self):
            self.deleted += 1

    class _StubRadialMenu(QWidget):
        closing = Signal()      # fly-back begun -> internal dim collapse (parity)

        def __init__(self, emblem_diameter=0.0, customizations=None,
                     variant="transparent", parent=None):
            super().__init__()
            self.emblem_diameter = emblem_diameter
            self.diameters = []
            self.reveals = 0
            created["menus"].append(self)

        def set_emblem_diameter(self, d):
            self.diameters.append(d)

        def start_reveal(self):
            self.reveals += 1

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
    the old code moved it to (798,478)). The fix keeps the window at the closed
    bbox, so the host never reflows and the emblem center holds across
    open -> scale-while-open -> close, while the radial top-level still gets the
    full ``emblem*4`` canvas."""
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

    # --- open: NO window expansion, NO host reflow, emblem stays on anchor ---
    menu = ctrl.open_radial_menu()
    qapp.processEvents()
    assert menu is not None
    assert provider._grid_host.size() == host_size_before     # host did NOT reflow
    c1 = emblem_global_center()
    assert (c1.x(), c1.y()) == anchor
    # The cluster window stays at the CLOSED bbox rect (never the dim canvas).
    w, h = ctrl._cluster_size()
    ecx, ecy = ctrl._emblem_center_local(w, h)
    assert surface.geometry() == window_rect_for((w, h), (ecx, ecy), anchor)
    # The radial top-level still receives the full emblem*4 canvas.
    canvas = int(CardMetrics(ctrl.scale).emblem * 4)
    rsurf = created_radial["surfaces"][-1]
    assert rsurf.geom.width() == canvas and rsurf.geom.height() == canvas

    # --- scale while open: emblem still on anchor, window still the (scaled) bbox ---
    ctrl.set_scale_by_notches(2)
    qapp.processEvents()
    c2 = emblem_global_center()
    assert (c2.x(), c2.y()) == anchor
    w2, h2 = ctrl._cluster_size()
    ecx2, ecy2 = ctrl._emblem_center_local(w2, h2)
    assert surface.geometry() == window_rect_for((w2, h2), (ecx2, ecy2), anchor)

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
    canvas = int(CardMetrics(1.0).emblem * 4)
    rsurf = created_radial["surfaces"][-1]
    assert rsurf.geom.width() == canvas and rsurf.geom.height() == canvas
    assert rsurf.geom.x() == int(anchor[0] - canvas / 2)
    assert rsurf.geom.y() == int(anchor[1] - canvas / 2)
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


def test_close_radial_menu_tears_down_radial_and_hides_dim(qapp, monkeypatch):
    """close_radial_menu(): tears down the radial top-level, hides (keeps) the
    internal dim, clears is_radial_open."""
    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(1000, 700))
    ctrl.enter()
    ctrl.open_radial_menu()
    rsurf = created_radial["surfaces"][-1]

    ctrl.close_radial_menu()

    assert ctrl.is_radial_open is False
    assert ctrl._radial_surface is None
    assert rsurf.hidden == 1 and rsurf.deleted == 1
    assert ctrl._dim is not None and ctrl._dim.isHidden() is True


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


def test_scale_while_radial_open_keeps_window_at_bbox_and_recenters_radial(qapp, monkeypatch):
    """A scale change WHILE the radial is open keeps the cluster window sized to the
    (new, scaled) cluster BBOX - never the dim extent - and re-sizes + re-centers the
    SEPARATE radial top-level on the anchor. The window must NOT grow to the dim
    canvas (that reflow was the Task 7 Critical); the dim canvas lives entirely on the
    radial top-level + the host-clipped internal dim."""
    from utils.overlay.cluster_geometry import window_rect_for
    from utils.overlay.card_metrics import CardMetrics

    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(1000, 700))
    ctrl.enter()
    surface = created[0]
    ctrl.open_radial_menu()
    rsurf = created_radial["surfaces"][-1]
    menu = created_radial["menus"][-1]
    canvas_before = ctrl._radial_size

    ctrl.set_scale_by_notches(2)                  # scale up while the radial is open

    assert ctrl._radial_size > canvas_before       # radial canvas grew with the emblem
    assert menu.diameters                          # set_emblem_diameter re-applied
    # The cluster window stays at the (new, scaled) BBOX, NOT the dim extent.
    s = ctrl.scale
    new_canvas = int(CardMetrics(s).emblem * 4)
    w, h = ctrl._cluster_size()
    ecx, ecy = ctrl._emblem_center_local(w, h)
    expected = window_rect_for((w, h), (ecx, ecy), ctrl._anchor)
    assert surface.geom == expected
    assert rsurf.geom.width() == new_canvas        # radial re-sized to the new canvas
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

    # A real move (small delta -> no clamp on the 800x800 screen) while OPEN.
    assert ctrl.move_group(30, -20) is True
    qapp.processEvents()
    new_anchor = ctrl._anchor
    assert new_anchor != anchor                 # the anchor actually moved

    # The move-while-open branch re-centered the radial top-level on the NEW anchor.
    assert ctrl._radial_size == canvas          # pure move: canvas unchanged
    assert rsurf.geom.width() == canvas and rsurf.geom.height() == canvas
    assert rsurf.geom.x() == int(new_anchor[0] - canvas / 2)
    assert rsurf.geom.y() == int(new_anchor[1] - canvas / 2)
    # ... and the emblem global center still lands exactly on the new anchor.
    c1 = emblem_global_center()
    assert (c1.x(), c1.y()) == new_anchor

    ctrl.close_radial_menu()
    ctrl.leave()


def test_open_repositions_dim_to_current_scale_after_scale_while_closed(qapp, monkeypatch):
    """The internal dim must track scale even while the radial is CLOSED, and
    open_radial_menu() must (re)position it to the CURRENT scale's emblem*4 canvas
    before showing it - otherwise a scale-while-closed leaves the dim at the stale
    enter-scale size and it flashes wrong on open."""
    from utils.overlay.card_metrics import CardMetrics

    _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make()
    ctrl.enter()
    enter_canvas = int(CardMetrics(1.0).emblem * 4)
    assert ctrl._dim.width() == enter_canvas       # dim built at the enter scale

    ctrl.set_scale_by_notches(2)                    # scale change while the radial is CLOSED
    s = ctrl.scale
    scaled_canvas = int(CardMetrics(s).emblem * 4)
    assert scaled_canvas != enter_canvas
    # (a) The dim tracked the scale even while closed (no stale enter-scale size).
    assert ctrl._dim.width() == scaled_canvas
    assert ctrl._dim.height() == scaled_canvas

    # Deliberately DESYNC the dim geometry so ONLY open_radial_menu()'s own
    # open-time _position_internal_dim() call can correct it. Without this, the
    # scale-while-closed reposition already left the dim right and the assertion
    # below would pass even if the open-time reposition were deleted.
    ctrl._dim.setGeometry(QRect(0, 0, 3, 3))
    assert ctrl._dim.geometry() == QRect(0, 0, 3, 3)   # desync took effect

    ctrl.open_radial_menu()
    # (b) open positions the dim to the CURRENT scale's canvas, centered on the
    # (scaled) emblem center - never the stale (desynced) one. Fails if the
    # open-time _position_internal_dim() call is removed.
    w, h = ctrl._cluster_size()
    ecx, ecy = ctrl._emblem_center_local(w, h)
    assert ctrl._dim.geometry() == QRect(
        ecx - scaled_canvas // 2, ecy - scaled_canvas // 2, scaled_canvas, scaled_canvas)
    ctrl.close_radial_menu()
    ctrl.leave()


def test_open_radial_menu_failclosed_on_setup_error(qapp, monkeypatch):
    """A failure mid-open (here the radial surface's host raises) must fail closed:
    no exception escapes, is_radial_open is False, no radial surface/menu is tracked,
    and the partially-built top-level is torn down (not leaked)."""
    created: dict = {"surfaces": []}

    class _BoomRadialSurface(QWidget):
        def __init__(self, backend=None):
            super().__init__()
            self.hidden = 0
            self.deleted = 0
            created["surfaces"].append(self)

        def host(self, widget):
            raise RuntimeError("radial host boom")

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
    assert ctrl._radial_surface is None
    assert ctrl._radial_menu is None
    # The half-built radial top-level was cleaned up by the rollback, not leaked.
    assert len(created["surfaces"]) == 1
    assert created["surfaces"][0].deleted == 1
    ctrl.leave()


def test_radial_input_shape_applied_once_then_deferred_to_settle(qapp, monkeypatch):
    """The radial click region is applied EXACTLY ONCE on open; a scale-while-open
    does NOT re-apply it immediately (the X11 reshape is deferred to the settle
    timer); firing the settle (_reapply_radial_shape) applies it; and a stray settle
    after close()/leave() is a safe no-op. Shapes are filtered to the radial surface
    so the cluster window's broad/exact shapes are excluded."""
    backend = _RecordingBackend()
    created_radial = _patch_radial(monkeypatch)
    ctrl, provider, window, created = _make(anchor=(1000, 700), backend=backend)
    ctrl.enter()

    ctrl.open_radial_menu()
    rsurf = created_radial["surfaces"][-1]

    def radial_shapes():
        return [s for s in backend.shapes if s[0] is rsurf]

    assert len(radial_shapes()) == 1               # exactly one apply on open

    ctrl.set_scale_by_notches(2)                    # scale while open
    assert len(radial_shapes()) == 1               # NOT re-applied (deferred to settle)
    # The deferral is a REAL armed settle timer (not just a direct-call artifact):
    # _schedule_radial_reshape() must have created + started a single-shot QTimer.
    timer = ctrl._radial_reshape_timer
    assert isinstance(timer, QTimer)
    assert timer.isSingleShot() is True
    assert timer.isActive() is True                 # actually armed by the scale-while-open

    ctrl._reapply_radial_shape()                    # the settle fires
    assert len(radial_shapes()) == 2               # now re-applied

    ctrl.close_radial_menu()
    # close_radial_menu() must STOP the armed reshape timer so no late reshape
    # fires against the torn-down radial surface.
    assert timer.isActive() is False
    after_close = len(radial_shapes())
    ctrl._reapply_radial_shape()                    # stray late settle after close
    assert len(radial_shapes()) == after_close     # safe no-op (radial surface gone)

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
    """close_panel_surface() runs on_close BEFORE tearing the surface down (the
    surface still exists + is undestroyed at that instant, so the caller can
    reparent its content out first), then hides + deletes it. A second close is a
    safe no-op."""
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
    assert surface.hidden == 1 and surface.deleted == 1
    assert ctrl.is_panel_open is False
    assert ctrl._panel_on_close is None

    # Idempotent: a second close does nothing (no re-run, no re-delete).
    ctrl.close_panel_surface()
    assert surface.deleted == 1
    assert order == [("on_close", True, 0)]


def test_open_panel_surface_failclosed_on_setup_error(qapp, monkeypatch):
    """A failure mid-open (the panel surface's host raises) must fail closed: no
    exception escapes, is_panel_open False, no surface/on_close tracked, the
    partially-built top-level is torn down (not leaked), and on_close still runs
    during the rollback so the caller reclaims its widget."""
    created: dict = {"surfaces": []}
    ran_on_close: list = []

    class _BoomPanelSurface(QWidget):
        def __init__(self, backend=None):
            super().__init__()
            self.hidden = 0
            self.deleted = 0
            created["surfaces"].append(self)

        def host(self, widget):
            raise RuntimeError("panel host boom")

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
    assert ctrl._panel_surface is None
    assert ctrl._panel_on_close is None
    assert ctrl._panel_size == 0
    # The half-built panel top-level was cleaned up by the rollback, not leaked.
    assert len(created["surfaces"]) == 1
    assert created["surfaces"][0].deleted == 1
    # The rollback ran on_close (so the caller reclaims its widget on a failed open).
    assert ran_on_close == [1]
    ctrl.leave()


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


@pytest.mark.parametrize("boom_on", ["prepare", "raise", "shape"])
def test_open_panel_surface_failclosed_on_open_step_raise(qapp, monkeypatch, boom_on):
    """Transaction-safe open: a failure in ANY fallible open step
    (prepare_initial_state, raise_, or the input-shape apply) fails closed - open
    returns None, is_panel_open is False, no surface/on_close/size is left tracked,
    the half-built top-level is torn down (deleted), and on_close ran during the
    rollback. Reverting the fix (re-guarding these steps with _safe_call / swallow)
    would swallow the failure and return the surface with is_panel_open True."""
    created = _patch_boom_step_panel(monkeypatch, boom_on)
    ran_on_close: list = []
    ctrl, provider, window, c = _make()
    ctrl.enter()

    result = ctrl.open_panel_surface(
        QWidget(), on_close=lambda: ran_on_close.append(1))     # must not raise

    assert result is None
    assert ctrl.is_panel_open is False
    assert ctrl._panel_surface is None
    assert ctrl._panel_on_close is None
    assert ctrl._panel_size == 0
    # The half-built panel top-level was cleaned up by the rollback, not leaked.
    assert len(created["surfaces"]) == 1
    assert created["surfaces"][0].deleted == 1
    # The rollback ran on_close (so the caller reclaims its widget on a failed open).
    assert ran_on_close == [1]
    ctrl.leave()


# ---------------------------------------------------------------------------
# 11c. Panel stays ABOVE the radial when BOTH are open
# ---------------------------------------------------------------------------
def test_panel_stays_above_radial_when_both_open(qapp, monkeypatch):
    """Opening the radial while the panel is already open must re-raise the panel
    ABOVE the just-shown radial top-level (the panel floats above the emblem AND the
    radial). A shared z-event log records the radial show + the panel raise; the panel
    re-raise must occur AFTER the radial is shown (so the panel ends up on top).
    Reverting the fix (dropping the panel re-raise in open_radial_menu) removes the
    post-clear panel-raise, failing this test."""
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

    psurf = ctrl.open_panel_surface(QWidget())
    assert psurf is not None
    assert psurf.raised >= 1                    # single-open z-order: panel raised on open
    z_events.clear()

    menu = ctrl.open_radial_menu()
    assert menu is not None

    kinds = [k for k, _ in z_events]
    assert "radial-show" in kinds               # the radial top-level was shown
    assert "panel-raise" in kinds               # the panel was re-raised while opening it
    # ... and the panel re-raise happened AFTER the radial was shown, so the panel is
    # stacked ABOVE the radial.
    assert kinds.index("panel-raise") > kinds.index("radial-show")

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
    """A raising on_close must not let the surface teardown destroy the BORROWED
    hosted widget. Built on a REAL PanelSurface so deleteLater actually cascades to
    children: close_panel_surface() reparents the still-hosted widget out of the
    surface BEFORE deleteLater, so the widget survives even though on_close raised and
    never reclaimed it. Reverting the fix (dropping _release_panel_content) lets the
    surface's destruction cascade delete the borrowed widget."""
    ctrl, provider, window, created = _make()
    ctrl.enter()
    widget = QWidget()

    def boom():
        raise RuntimeError("on_close boom")

    surface = ctrl.open_panel_surface(widget, on_close=boom)   # REAL PanelSurface
    assert surface is not None
    assert ctrl.is_panel_open is True
    assert widget.parent() is surface                # hosted in the surface

    ctrl.close_panel_surface()                       # on_close raises; must not tank teardown
    # Force the surface's deleteLater to actually run: DeferredDelete is NOT processed
    # by a plain processEvents(), so without this the surface (and its child) would
    # still be alive and the survival check below would be meaningless.
    from PySide6.QtCore import QEvent
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)

    assert ctrl.is_panel_open is False               # surface fully torn down
    assert _cpp_alive(surface) is False              # the surface WAS really destroyed
    assert _cpp_alive(widget) is True                # BORROWED widget survived that destruction
    assert widget.parent() is None                   # released out of the (dead) surface
    ctrl.leave()


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
# 12b. T8 review fixes (dual-review consensus): inactive-seed guard,
#      malformed-payload fail-safe, occupancy-drop peek settle, and a
#      NON-1.0-scale ghost-click guard for the load-bearing scale=1.0 decision.
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


def test_ghost_press_resolves_at_scale_local_coords_at_non_unit_scale(qapp):
    """GUARD (protects the load-bearing scale=1.0 in _ghost_click_pass): at a NON-1.0
    scale a ghost 'press' over a control resolves to the correct AT-SCALE
    cell-root-local coordinate. The cluster physically resizes the cards (via
    apply_metrics), so BOTH the card screen-geometry AND control_rects are already
    at-scale - control_hits must therefore divide by 1.0, not self._scale.

    Uses a stub whose apply_metrics FAITHFULLY scales the cell origins + control rects,
    so scale 1.0 vs self._scale are DISTINGUISHABLE here (they are not at scale 1.0):
    passing self._scale would divide the at-scale offset again and deliver the WRONG
    (framed) coordinate."""
    provider = _ScaledStubProvider()
    # Save scale 1.5 so enter() applies at-scale metrics (cells + controls scaled).
    s = _DictSettings({KEY_SCALE: 1.5})
    ctrl, provider, window, created = _make(
        provider=provider, anchor=_GHOST_ANCHOR, settings=s)
    ctrl.enter()
    assert ctrl.scale == 1.5

    # Screen center of cell 1's first control, computed from the ACTUAL at-scale
    # placement: window origin + at-scale cell origin + at-scale control center.
    win = ctrl._compute_window_rect()
    ox, oy = win.x(), win.y()
    cell_origin = provider._cell_widgets[1].pos()
    ctrl_rect = provider.control_rects(1)[0]              # AT-SCALE card-local
    cx = ctrl_rect.x() + ctrl_rect.width() // 2
    cy = ctrl_rect.y() + ctrl_rect.height() // 2
    sx = ox + cell_origin.x() + cx
    sy = oy + cell_origin.y() + cy

    ctrl.on_ghost_event(("press", [(1, sx, sy)]))
    # Delivered click is the AT-SCALE cell-root-local coord (cx, cy) - control_hits
    # divides by 1.0. Passing self._scale (1.5) would instead deliver
    # (round(cx / 1.5), round(cy / 1.5)) - a different, wrong point.
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

    assert len(radial_shapes()) == 1          # applied once on open (dpr 1.0)
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

    assert len(panel_shapes()) == 1           # applied once on open (dpr 1.0)
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
