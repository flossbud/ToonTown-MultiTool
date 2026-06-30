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

import pytest
from PySide6.QtCore import QObject, QPointF, QRect, Signal
from PySide6.QtWidgets import QWidget

from utils.overlay.backend import NoOpOverlayBackend
from utils.overlay.cluster_controller import ClusterOverlayController
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
          on_active_changed=None, anchor=None, backend=None):
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
