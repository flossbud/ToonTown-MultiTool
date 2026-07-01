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
