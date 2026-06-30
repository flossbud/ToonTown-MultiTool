"""Single-window cluster overlay controller (enter / leave / borrow / reset).

``ClusterOverlayController`` is the single-window analog of
``OverlayGroupController``: instead of one overlay surface per card, it borrows
the WHOLE ``_grid_host`` subtree (glow + the 2x2 card grid + the emblem) into ONE
``ClusterSurface`` so the cluster moves and scales as a single rigid window. Its
constructor is drop-in compatible with ``OverlayGroupController`` so the two can
be swapped behind the same call sites.

This module implements ONLY the lifecycle slice:

* ``enter()`` - build the cluster surface, borrow the host, place + show it, then
  MINIMIZE the main window (never hide, so the single taskbar icon stays).
* ``leave()`` - reset framed (scale-1.0) metrics, restore the borrowed host to the
  tab, tear down the surface, and restore the main window.

Both are FAIL-CLOSED, mirroring ``OverlayGroupController``: if any step of
``enter()`` raises, the borrowed host is returned to the tab, the surface is torn
down, the window is restored if it was minimized, and the controller stays Framed
(``is_active`` False) - the app is never left with a half-built overlay. No
exception escapes ``enter()`` (it returns ``False``). ``leave()`` is likewise
guarded: a restore failure must still reset metrics, restore the window, and
clear state.

Scaling (single-window metrics + input-shape phase machine), drag, occupancy
(the visible set narrows the EXACT input shape while the grid SHELL stays fixed -
empty cards keep their cell, never hidden/reshaped), and persistence (load the
saved anchor + scale on enter, debounced save on scale/move, flush on leave) are
built here. Hover-peek, ghost clicks, and the radial menu are LATER tasks and are
intentionally NOT built here.
"""
from __future__ import annotations

from utils.overlay.backend import get_overlay_backend
from utils.overlay.scale import step_scale

# Quiescence window after the last scale notch before the EXACT input shape is
# swapped in. Long enough that a continuous wheel spin keeps re-arming it (so the
# broad shape stays up and keeps capturing notches), short enough to feel instant.
_SETTLE_INTERVAL_MS = 250


class ClusterOverlayController:
    """Borrow the whole cluster into one window; minimize the main window.

    Drop-in compatible constructor with ``OverlayGroupController``. The single
    ``ClusterSurface`` is built by ``surface_factory`` (a zero-arg callable) when
    supplied - tests inject a recording stub - otherwise a real ``ClusterSurface``
    bound to the backend is built.
    """

    def __init__(self, window, backend=None, settings=None, surface_factory=None,
                 card_provider=None, on_active_changed=None):
        self._window = window
        self._backend = backend if backend is not None else get_overlay_backend()
        # The settings object the anchor/scale/monitor persistence reads + writes
        # through (load on enter, debounced save on scale/move). None -> persistence
        # is a no-op (the stub/orchestration tests).
        self._settings = settings
        # Zero-arg factory -> the single cluster surface. None -> a real
        # ClusterSurface bound to the backend.
        self._surface_factory = surface_factory
        # The _CompactLayout: exposes capture_cluster_host()/restore_cluster_host(),
        # apply_metrics(CardMetrics), and the _grid_host / _emblem widgets the
        # window placement is derived from.
        self._card_provider = card_provider
        # Best-effort observer notified with the new active state after a
        # successful enter() and after leave() (the tab uses it to keep repaint
        # timers running while the minimized main window would stop them). Never
        # invoked on a failed enter().
        self._on_active_changed = on_active_changed

        self._surface = None
        self._token = None
        # Surfaces whose release() raised during teardown: we KEEP a reference so
        # Python GC cannot destroy the parentless surface (which would delete the
        # still-hosted borrowed cluster subtree - the 4 cards + emblem + glow).
        # Leaking the surface keeps the cluster ALIVE (recoverable). Mirrors
        # OverlayGroupController._orphans.
        self._orphans: list = []
        self._anchor: tuple[int, int] = self._default_anchor()
        self._active: bool = False

        # Scaling state. The cluster is ONE window (no proxy/park/snapshot), so
        # scaling is a synchronous metrics-apply + single resize + an input-shape
        # phase machine (broad-while-scaling, exact-on-settle). Persistence of the
        # scale across sessions is a LATER task.
        self._scale: float = 1.0
        # Input-shape phase machine: re-applying the EXACT (per-control) input
        # shape under the pointer every notch can stall the wheel stream, so each
        # notch applies one BROAD (full-window) shape and (re)arms a settle timer
        # that swaps in the EXACT shape once the gesture quiesces.
        self._scaling_active: bool = False
        self._input_phase: str | None = None
        self._settle_timer = None

        # Occupancy. The grid SHELL is fixed (the permanent quadrant shells never
        # move/resize), so an empty card keeps its cell; occupancy only narrows the
        # EXACT input (click-through) shape so empty cards drop OUT of the click
        # region. The cards' CONTENT suppression is the provider's job, not the
        # controller's. _visible_cells seeds from provider.occupied_cells() on
        # enter() (all four when the provider has no occupancy) and is reconciled
        # live off occupied_cells_changed.
        self._visible_cells: set = {0, 1, 2, 3}
        self._occupancy_connected: bool = False

        # Persistence (anchor + scale + monitor identity). A TRAILING-edge debounce:
        # a burst of drag/scale changes restarts the single-shot timer so it
        # collapses into ONE settings write ~250ms after the LAST change; leave()
        # flushes any pending write synchronously (and stops the timer) before teardown.
        self._save_pending: bool = False
        self._save_timer = None

        # Radial menu + internal dim. The radial menu stays a SEPARATE source-cleared
        # top-level (RadialSurface): it must sit ABOVE the click-through cluster
        # window AND accept clicks, so it cannot be a child of the cluster. The DIM,
        # by contrast, is INTERNAL: a child of the borrowed _grid_host, stacked ABOVE
        # the cards and BELOW the emblem, so it dims the cards behind the ring without
        # a second backdrop window (z-order: glow -> cards -> dim -> emblem). The dim
        # widget is built (hidden) on enter() and REMOVED on leave() before the host
        # is restored, so framed mode is 100% unaffected. The radial surface + menu
        # exist only between open_radial_menu() and close_radial_menu().
        self._dim = None
        self._radial_surface = None
        self._radial_menu = None
        self._radial_size: int = 0
        # Re-applying the radial's click region on every scroll tick stalls the wheel
        # stream, so a scale-while-open change DEFERS the reshape to this settle timer
        # (mirrors OverlayGroupController._schedule_radial_reshape).
        self._radial_reshape_timer = None

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def is_radial_open(self) -> bool:
        """True while the radial menu top-level is up (between open_radial_menu and
        close_radial_menu). Drives the radial-aware window sizing and lets the
        emblem click toggle the ring shut (caller wiring, a LATER task)."""
        return self._radial_surface is not None

    @property
    def scale(self) -> float:
        """The live cluster scale (1.0 = framed base size)."""
        return self._scale

    @scale.setter
    def scale(self, value) -> None:
        self._scale = float(value)

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------
    @staticmethod
    def _default_anchor() -> tuple[int, int]:
        """Center of the primary screen, or (0, 0) if there is no QApplication.

        Mirrors ``OverlayGroupController._default_anchor``; persistence (restoring
        a saved anchor) is a LATER task.
        """
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return (0, 0)
        geo = screen.geometry()
        return (geo.x() + geo.width() // 2, geo.y() + geo.height() // 2)

    @staticmethod
    def _safe_call(obj, name: str) -> bool:
        """Call ``obj.name()`` swallowing exceptions. Returns True if it ran
        without raising (or the method is absent), False if it raised."""
        fn = getattr(obj, name, None)
        if fn is None:
            return True
        try:
            fn()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Placement
    # ------------------------------------------------------------------
    def _cluster_size(self) -> tuple[int, int]:
        """The (w, h) the single cluster window must span: the borrowed host's
        size. Prefer sizeHint() (valid even before the host is laid out); fall
        back to the live size() when the hint is invalid/zero."""
        host = self._card_provider._grid_host
        hint = host.sizeHint()
        w, h = hint.width(), hint.height()
        if w <= 0 or h <= 0:
            sz = host.size()
            w, h = sz.width(), sz.height()
        return (w, h)

    def _emblem_center_local(self, bbox_w: int, bbox_h: int) -> tuple[int, int]:
        """Emblem center within the host (top-left origin), derived from the
        emblem widget's geometry. Falls back to the bbox center when the emblem
        is unavailable or has no geometry yet."""
        emblem = getattr(self._card_provider, "_emblem", None)
        if emblem is not None:
            g = emblem.geometry()
            if g.width() > 0 and g.height() > 0:
                return (g.x() + g.width() // 2, g.y() + g.height() // 2)
        return (bbox_w // 2, bbox_h // 2)

    def _radial_canvas(self) -> tuple[float, int]:
        """``(emblem disc diameter, square canvas px)`` for the radial menu + dim at
        the current cluster scale. ONE formula shared by open_radial_menu and the
        scale path so the two never drift (mirrors
        ``OverlayGroupController._radial_canvas``)."""
        from utils.overlay.card_metrics import CardMetrics
        emblem_dia = float(CardMetrics(self._scale).emblem)
        return emblem_dia, int(emblem_dia * 4)

    def _compute_window_rect(self):
        """The SCREEN rect for the single cluster window: sized to the borrowed host
        (the closed cluster bbox) and placed so the emblem center lands on the anchor.

        The window is ALWAYS the closed bbox - radial-open never grows it. The
        internal dim is a CHILD of ``_grid_host`` (Qt hard-clips it to the host
        regardless of window size), so expanding the window can never enlarge the
        dim; it only stretches the host's fill layout, reflowing the cards and
        dragging the emblem off the anchor. Keeping the window at the bbox preserves
        the emblem-center invariant open, closed, and while scaling. The radial menu
        is its OWN top-level (sized to the full ``emblem*4`` canvas), independent of
        this window."""
        from utils.overlay.cluster_geometry import window_rect_for
        w, h = self._cluster_size()
        emblem_center = self._emblem_center_local(w, h)
        return window_rect_for(
            (w, h), emblem_center, self._anchor,
            radial_open=False, dim_extent=(0, 0),
        )

    def _build_surface(self):
        if self._surface_factory is not None:
            return self._surface_factory()
        from utils.overlay.cluster_surface import ClusterSurface
        return ClusterSurface(backend=self._backend)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def enter(self) -> bool:
        """Build + show the cluster surface around the borrowed host, then
        minimize the main window. No-op (returns True) if already active.

        Transactional / fail-closed: returns True on success (now transparent),
        or False if any step raised - in which case the borrowed host is returned
        to the tab, the surface is torn down, the main window is restored if it
        was minimized, and the controller stays Framed. No exception escapes.
        """
        if self._active:
            return True
        provider = self._card_provider
        surface = None
        token = None
        minimized = False
        try:
            surface = self._build_surface()
            token = provider.capture_cluster_host()
            surface.host(provider._grid_host)
            # Restore the persisted scale + anchor BEFORE measuring the host, so the
            # cluster window spans the host at the RESTORED scale and re-centers on
            # the remembered anchor. Nothing saved (or no settings) -> scale stays
            # 1.0 + the default anchor (current default behavior). At a restored
            # scale the host must be resized FIRST (apply_metrics) so the rect the
            # window is sized to reflects the scaled host.
            self._load_persisted_state()
            if self._scale != 1.0:
                from utils.overlay.card_metrics import CardMetrics
                provider.apply_metrics(CardMetrics(self._scale))
            rect = self._compute_window_rect()
            surface.set_overlay_geometry(rect)
            surface.show()
            # Set the flag BEFORE the call so a showMinimized() failure still
            # triggers the except-path window restore (mirrors OverlayGroupController).
            minimized = True
            self._window.showMinimized()
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster_controller.enter() transaction FAILED:\n"
                          + traceback.format_exc())
            # Fail-closed: return the borrowed host to the tab FIRST
            # (release-before-restore so the surface never deletes the live host),
            # THEN destroy the now-empty surface; restore the window if minimized.
            self._release_and_restore(surface, token)
            self._teardown_surface(surface)
            if minimized:
                self._safe_call(self._window, "showNormal")
            self._surface = None
            self._token = None
            self._active = False
            return False
        self._surface = surface
        self._token = token
        # Seed the visible set from live occupancy and subscribe to changes so the
        # exact input shape tracks which cards actually hold a window. A provider
        # without occupancy degrades to all-visible (no signal -> no subscription).
        self._visible_cells = self._target_visible_cells()
        self._connect_occupancy()
        self._active = True
        # Build the internal dim (hidden) now that the host is borrowed + measured.
        # Decorative + best-effort: a dim failure must never flip a successful enter
        # back to framed, so _build_internal_dim swallows its own errors.
        self._build_internal_dim()
        self._emit_active_changed()   # self._active is True here
        return True

    def leave(self) -> None:
        """Restore the borrowed host to the tab, reset framed (scale-1.0)
        metrics, tear down the cluster surface, and restore the main window.
        No-op if framed.

        Fail-closed: a restore failure must still reset metrics, restore the
        window, and clear state.
        """
        if not self._active:
            return
        provider = self._card_provider
        surface = self._surface
        token = self._token
        # Persist the FINAL anchor + scale before any teardown/reset (the remembered
        # overlay position, restored on the next enter). MUST run before the scale
        # reset below, else the flush would save the framed 1.0 instead of the scale
        # the user left at. Then stop the save timer unconditionally so no late
        # timeout survives the leave (the active guard in _run_pending_save is the
        # backstop).
        self.flush_pending_save()
        if self._save_timer is not None:
            self._save_timer.stop()
        # The radial must never outlive the overlay: close it FIRST (tears down its
        # top-level + hides the dim) before any host teardown (mirrors
        # OverlayGroupController._teardown calling close_radial_menu()).
        self.close_radial_menu()
        # Cancel any pending settle and reset scaling state so a re-enter starts
        # framed (scale 1.0, no in-flight gesture). A late timer firing post-leave
        # is a guarded no-op, but stopping it here avoids the wasted callback.
        if self._settle_timer is not None:
            self._settle_timer.stop()
        self._scaling_active = False
        self._input_phase = None
        self._scale = 1.0
        # Disconnect occupancy first so a late occupied_cells_changed after teardown
        # is a safe no-op, and reset the visible set to the framed default.
        self._disconnect_occupancy()
        self._visible_cells = {0, 1, 2, 3}
        # Reset framed (scale-1.0) metrics so the cards come back at base scale.
        if provider is not None:
            try:
                from utils.overlay.card_metrics import CardMetrics
                provider.apply_metrics(CardMetrics(1.0))
            except Exception:
                pass
        # Remove the internal dim BEFORE restoring the host, so the borrowed
        # _grid_host returns to framed mode with no stray overlay-only child.
        self._teardown_internal_dim()
        # Release the borrowed host from the surface, then restore it to the tab.
        self._release_and_restore(surface, token)
        # Destroy the now-empty surface.
        self._teardown_surface(surface)
        self._surface = None
        self._token = None
        self._safe_call(self._window, "showNormal")
        self._active = False
        self._emit_active_changed()   # self._active is False here

    def toggle(self) -> bool:
        """Leave if active, else enter. Returns the resulting active state."""
        if self._active:
            self.leave()
        else:
            self.enter()
        return self._active

    # ------------------------------------------------------------------
    # Scaling + move (single window: no proxy, no park, no snapshot)
    # ------------------------------------------------------------------
    def set_scale_by_notches(self, notches: int) -> None:
        """Step the cluster scale by *notches*, re-apply metrics, resize the ONE
        window, and drive the input-shape phase machine. No-op if not active.

        Crisp per-notch (no animation): the single window has no proxy/snapshot
        machinery, so a notch is a synchronous metrics-apply (cards + emblem grow/
        shrink), a SINGLE window resize (the cluster sizeHint changed - the surface
        source-clear handles the backing), and one BROAD input-shape apply that
        keeps the wheel stream captured while a settle timer arms the EXACT shape.

        Unlike enter()/leave() this is NOT transactional: it is an idempotent
        re-layout, so a mid-gesture failure self-corrects on the next notch.
        """
        if not self._active:
            return
        prev_scale = self.scale
        self.scale = step_scale(self.scale, notches)
        provider = self._card_provider
        if provider is not None:
            try:
                from utils.overlay.card_metrics import CardMetrics
                provider.apply_metrics(CardMetrics(self.scale))
            except Exception:
                pass
        # The cluster size changed: recompute + apply the window rect ONCE (same
        # emblem-centered placement path enter() uses). Best-effort, like enter():
        # a resize failure self-corrects on the next notch rather than propagating
        # into the Qt wheel handler.
        rect = self._compute_window_rect()
        if self._surface is not None:
            try:
                self._surface.set_overlay_geometry(rect)
            except Exception:
                pass
        # Radial open: keep its top-level + the internal dim sized + centered to the
        # new emblem (the click-region re-apply is deferred to the settle timer).
        # Radial CLOSED: still re-size + re-center the internal dim to the new scale's
        # emblem*4 canvas so it tracks scale regardless of radial state (otherwise a
        # scale-while-closed leaves the dim stale and the next open would flash it).
        if self.is_radial_open:
            self._reposition_radial()
        else:
            self._position_internal_dim()
        # Drive the input-shape phase machine: broad now, exact on settle.
        self._enter_broad_phase(rect)
        # Persist the new scale (debounced) - but only when the scale ACTUALLY
        # changed: scrolling against SCALE_MIN/MAX is a no-op that must not churn a
        # save (mirrors move_group, which only saves on a real move).
        if self.scale != prev_scale:
            self._schedule_save()

    def move_group(self, dx: int, dy: int) -> bool:
        """Shift the cluster anchor by (dx, dy), clamp to the screen envelope, and
        reposition the window. Returns True only if the window ACTUALLY moved.

        Drag is LOCKED OUT while a scale gesture is live (``_scaling_active``):
        returns False without moving so a wheel-zoom is never fought by a stray
        drag. Also a no-op (False) when not active.

        Anchor reconciliation: the anchor is stored as the emblem-center of the
        CLAMPED rect (not the raw accumulated point), so dragging into an envelope
        edge cannot build up a phantom offset that a reverse drag must first unwind
        (the dead-zone bug). A clamp that pins the rect to its current position is
        reported as no move (returns False).
        """
        if not self._active:
            return False
        if self._scaling_active:
            return False
        from utils.overlay.cluster_geometry import window_rect_for, clamp_to_envelope
        w, h = self._cluster_size()
        emblem_center = self._emblem_center_local(w, h)
        ex, ey = emblem_center
        ax, ay = self._anchor
        # The rect at the CURRENT (already-reconciled) anchor == the on-screen
        # placement; the candidate is the shifted rect, clamped to the envelope.
        current = window_rect_for((w, h), emblem_center, (ax, ay), False, (0, 0))
        candidate = window_rect_for(
            (w, h), emblem_center, (ax + dx, ay + dy), False, (0, 0))
        clamped = clamp_to_envelope(
            candidate, self._screens_xywh(), self._move_margin())
        if clamped == current:
            return False  # clamp pinned -> no visual move (no anchor drift)
        # Reconcile the anchor onto the clamped rect's emblem-center. The clamp +
        # reconcile run on the CLOSED (bare-cluster) geometry: the anchor IS the
        # emblem center regardless of radial state, and the transient dim canvas
        # should not change where the cluster parks.
        self._anchor = (clamped.x() + ex, clamped.y() + ey)
        if self._surface is not None:
            # The window is always the closed bbox rect (radial-open no longer grows
            # it), so the clamped rect IS the rect to apply whether or not the radial
            # is open; the radial top-level + dim re-center separately below.
            try:
                self._surface.set_overlay_geometry(clamped)
            except Exception:
                pass
        if self.is_radial_open:
            self._reposition_radial()
        # Persist the new (reconciled) anchor (debounced).
        self._schedule_save()
        return True

    # ------------------------------------------------------------------
    # Input-shape phase machine
    # ------------------------------------------------------------------
    def _enter_broad_phase(self, rect) -> None:
        """Enter (or stay in) the BROAD scaling phase: mark scaling active, apply
        the full-window input shape so wheel notches keep landing as the window
        resizes, and (re)arm the settle timer that will swap in the exact shape."""
        self._scaling_active = True
        self._input_phase = "broad"
        self._apply_input_shape(self._broad_input_path(rect))
        self._arm_settle_timer()

    def _arm_settle_timer(self) -> None:
        """(Re)start the single-shot settle timer. A continuous wheel spin re-arms
        it every notch, so the exact shape only lands once the gesture quiesces."""
        from PySide6.QtCore import QTimer
        if self._settle_timer is None:
            self._settle_timer = QTimer()
            self._settle_timer.setSingleShot(True)
            self._settle_timer.timeout.connect(self._settle_input)
        self._settle_timer.start(_SETTLE_INTERVAL_MS)

    def _settle_input(self) -> None:
        """Settle callback (directly callable from tests): leave the broad phase
        and apply the EXACT input shape (emblem + visible controls union). A late
        timeout that fires AFTER leave() is a true no-op: the guard runs BEFORE the
        phase assignment, so a framed controller never flips to the 'exact' phase
        and never shapes a dead surface."""
        self._scaling_active = False
        if not self._active or self._surface is None:
            return
        self._input_phase = "exact"
        self._apply_exact_input_shape()

    def _apply_exact_input_shape(self) -> None:
        """Build + apply the EXACT (per-control) input shape: the emblem union the
        controls of the VISIBLE cards only, so empty cards drop OUT of the click
        region. Best-effort + guarded: a no-op when framed or surfaceless. Shared by
        the settle callback and the occupancy reconcile."""
        if not self._active or self._surface is None:
            return
        from utils.overlay.cluster_geometry import input_union
        emblem_rect = self._emblem_rect()
        card_controls = self._window_control_rects()
        region = input_union(emblem_rect, card_controls, self._visible_cells)
        self._apply_input_shape(self._region_to_path(region))

    def _apply_input_shape(self, path) -> None:
        """Apply *path* as the single window's INPUT (click-through) shape via the
        backend. Best-effort: a shape failure must never break the scale gesture."""
        surface = self._surface
        if surface is None:
            return
        try:
            self._backend.apply_input_shape(surface, path, surface.devicePixelRatio())
        except Exception:
            pass

    @staticmethod
    def _broad_input_path(rect):
        """A QPainterPath covering the WHOLE window (window-local coords). The
        rect's screen origin is irrelevant for an input shape, which is local."""
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.addRect(0, 0, rect.width(), rect.height())
        return path

    @staticmethod
    def _region_to_path(region):
        """Convert a QRegion (the exact input union) into a QPainterPath the
        backend can consume."""
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.addRegion(region)
        return path

    def _emblem_rect(self):
        """The emblem hit rect in window-local coords (the host fills the window),
        from the emblem widget geometry. Null QRect when unavailable."""
        from PySide6.QtCore import QRect
        emblem = getattr(self._card_provider, "_emblem", None)
        if emblem is not None:
            g = emblem.geometry()
            if g.width() > 0 and g.height() > 0:
                return QRect(g)
        return QRect()

    def _window_control_rects(self) -> dict:
        """``{slot_id: [QRect, ...]}`` of each card's interactive-control rects in
        WINDOW-LOCAL coords - the input-union's per-slot ``card_controls``.

        The provider's real ``control_rects(cell_index)`` returns CARD-LOCAL rects
        (relative to that cell's root). In the single-window cluster the whole grid
        host is one window, so each rect is translated by its cell's origin within
        the grid host (``cell.mapTo(grid_host)``). ``apply_metrics`` has already
        resized the cards to the current scale, so both the control rects and the
        cell origins are at-scale - no extra scaling here.

        Empty dict when the provider lacks ``control_rects``/``_card_slots`` (the
        exact union then collapses to the emblem only - documented placeholder
        behavior; occupancy + the per-control refinements land in a LATER task).
        """
        provider = self._card_provider
        rects_fn = getattr(provider, "control_rects", None)
        slots = getattr(provider, "_card_slots", None)
        if rects_fn is None or slots is None:
            return {}
        from PySide6.QtCore import QPoint
        grid_host = getattr(provider, "_grid_host", None)
        out: dict = {}
        for cell_index, slot in enumerate(slots):
            root = slot.get("cell") if isinstance(slot, dict) else None
            if root is None:
                continue
            try:
                if grid_host is not None and root is not grid_host:
                    origin = root.mapTo(grid_host, QPoint(0, 0))
                else:
                    origin = root.pos()
                local_rects = rects_fn(cell_index)
                out[cell_index] = [r.translated(origin) for r in local_rects]
            except Exception:
                continue
        return out

    # ------------------------------------------------------------------
    # Occupancy (keep the grid shell fixed; only narrow the input shape)
    # ------------------------------------------------------------------
    def _target_visible_cells(self) -> set:
        """The slot ids whose cards currently hold a window: the provider's
        ``occupied_cells()``, or all four ``{0, 1, 2, 3}`` when the provider has no
        occupancy (a stub provider degrades to all-visible). Pure read; a provider
        that raises also degrades to all-visible."""
        provider = self._card_provider
        fn = getattr(provider, "occupied_cells", None) if provider is not None else None
        if fn is None:
            return {0, 1, 2, 3}
        try:
            return set(fn())
        except Exception:
            return {0, 1, 2, 3}

    def _connect_occupancy(self) -> None:
        """Subscribe ``_reconcile_occupancy`` to the provider's
        ``occupied_cells_changed`` signal, if it exposes one. Idempotent (a second
        call while already connected is a no-op, so the slot never double-fires) +
        guarded: a provider without the signal (a stub) is a safe no-op."""
        if self._occupancy_connected:
            return
        provider = self._card_provider
        sig = getattr(provider, "occupied_cells_changed", None) if provider is not None else None
        if sig is None:
            return
        try:
            sig.connect(self._reconcile_occupancy)
            self._occupancy_connected = True
        except Exception:
            pass

    def _disconnect_occupancy(self) -> None:
        """Unsubscribe from ``occupied_cells_changed`` so a late signal after
        teardown never reaches ``_reconcile_occupancy``. Guarded: disconnecting a
        signal that was never connected (or is gone) must never raise."""
        if not self._occupancy_connected:
            return
        self._occupancy_connected = False
        provider = self._card_provider
        sig = getattr(provider, "occupied_cells_changed", None) if provider is not None else None
        if sig is None:
            return
        try:
            sig.disconnect(self._reconcile_occupancy)
        except Exception:
            pass

    def _reconcile_occupancy(self) -> None:
        """Occupancy nudge (the signal slot): re-read ``occupied_cells()``, update
        ``self._visible_cells``, and RE-APPLY the exact input shape so empty cards
        drop out of the click region. No-op when framed (a stray post-leave signal
        is safe).

        The grid SHELL is left untouched: no cell is hidden/``setVisible(False)``
        (that would collapse the pinwheel) and the window is NOT resized or reshaped
        (the cluster bbox is fixed by the permanent shells). Only the click region
        changes.

        Mid scale gesture (BROAD phase: ``_scaling_active`` True, the full-window
        capture shape is up) the visible set is refreshed but the EXACT shape is NOT
        swapped in - narrowing the capture region under the pointer would stall the
        wheel stream (the very thing the broad/exact phase machine exists to
        prevent, and it would leave ``_input_phase`` stuck "broad" under an exact
        shape). The settle timer is re-armed every notch, so ``_settle_input()``
        replays the exact shape with this fresh visible set on quiesce. Mirrors
        ``OverlayGroupController._on_occupancy_changed``'s gesture deferral."""
        if not self._active:
            return
        self._visible_cells = self._target_visible_cells()
        if self._scaling_active:
            return
        self._apply_exact_input_shape()

    @staticmethod
    def _screens_xywh() -> list:
        """Connected screens as ``(x, y, w, h)`` tuples - the form
        ``clamp_to_envelope`` consumes."""
        from PySide6.QtGui import QGuiApplication
        out = []
        for s in QGuiApplication.screens():
            g = s.geometry()
            out.append((g.x(), g.y(), g.width(), g.height()))
        return out

    def _move_margin(self) -> int:
        """Envelope inflation for parking: a quarter of the (scaled) emblem may
        stay on-screen while the rest of the cluster slides off any edge."""
        from utils.overlay.card_metrics import CardMetrics
        return int(CardMetrics(self._scale).emblem // 4)

    # ------------------------------------------------------------------
    # Radial menu + internal dim layer
    # ------------------------------------------------------------------
    def cluster_layer_order(self) -> list:
        """The EFFECTIVE z-order of the cluster subtree as role names, derived from
        the real child stacking of the borrowed ``_grid_host`` (Qt's ``children()``
        reflects ``raise_()``/``lower_()`` order). Maps the glow, the four card
        cells (collapsed into a single ``"cards"`` entry), the internal dim, and the
        emblem to ``["glow", "cards", "dim", "emblem"]`` bottom-to-top. Layers that
        are absent (e.g. a stub provider with no glow, or before the dim is built)
        are simply omitted. Used by tests + future re-stack assertions."""
        provider = self._card_provider
        grid_host = getattr(provider, "_grid_host", None) if provider is not None else None
        if grid_host is None:
            return []
        from PySide6.QtWidgets import QWidget
        glow = getattr(provider, "_glow", None)
        emblem = getattr(provider, "_emblem", None)
        dim = self._dim
        cells = set()
        slots = getattr(provider, "_card_slots", None)
        if slots:
            for slot in slots:
                cell = slot.get("cell") if isinstance(slot, dict) else None
                if cell is not None:
                    cells.add(cell)
        order: list = []
        for child in grid_host.children():
            if not isinstance(child, QWidget):
                continue
            if glow is not None and child is glow:
                role = "glow"
            elif dim is not None and child is dim:
                role = "dim"
            elif emblem is not None and child is emblem:
                role = "emblem"
            elif child in cells:
                role = "cards"
            else:
                continue
            if order and order[-1] == role:
                continue  # collapse the four consecutive card cells into one entry
            order.append(role)
        return order

    def _build_internal_dim(self) -> None:
        """Create the internal dim as a HIDDEN child of the borrowed ``_grid_host``,
        sized to the ``emblem*4`` canvas centered on the emblem, stacked ABOVE the
        cards and BELOW the emblem. Best-effort: a failure leaves ``_dim`` None (the
        radial then opens without the dim) and never tanks enter()."""
        provider = self._card_provider
        grid_host = getattr(provider, "_grid_host", None) if provider is not None else None
        if grid_host is None:
            return
        try:
            from utils.overlay.radial_menu import RadialDimWidget
            dim = RadialDimWidget(grid_host)
            self._dim = dim
            self._position_internal_dim()
            dim.hide()
            self._restack_internal_layers()
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster_controller._build_internal_dim() FAILED "
                          "(continuing without dim):\n" + traceback.format_exc())
            self._dim = None

    def _position_internal_dim(self) -> None:
        """Center the internal dim on the emblem (``_grid_host``-local coords) at the
        current ``emblem*4`` canvas. The dim follows the emblem as the cluster
        scales (apply_metrics moves the emblem center)."""
        dim = self._dim
        if dim is None:
            return
        from PySide6.QtCore import QRect
        w, h = self._cluster_size()
        ecx, ecy = self._emblem_center_local(w, h)
        _dia, canvas = self._radial_canvas()
        dim.setGeometry(QRect(ecx - canvas // 2, ecy - canvas // 2, canvas, canvas))

    def _restack_internal_layers(self) -> None:
        """Re-assert the dim < emblem z-order inside ``_grid_host``: raise the dim
        above the cards, then raise the emblem above the dim. The glow stays at the
        bottom (never raised). Each step is a guarded no-op when that widget is
        absent."""
        dim = self._dim
        if dim is not None:
            self._safe_call(dim, "raise_")
        emblem = getattr(self._card_provider, "_emblem", None) if self._card_provider is not None else None
        if emblem is not None:
            self._safe_call(emblem, "raise_")

    def _teardown_internal_dim(self) -> None:
        """Detach + destroy the internal dim. Detaching (``setParent(None)``) runs
        BEFORE the host is restored so framed mode never sees a stray dim child.
        Idempotent + guarded."""
        dim = self._dim
        self._dim = None
        if dim is None:
            return
        try:
            dim.hide()
            dim.setParent(None)
            dim.deleteLater()
        except Exception:
            pass

    def open_radial_menu(self):
        """Show the click-accepting radial menu centered on the emblem.

        Builds a source-cleared ``RadialSurface`` top-level hosting a
        ``RadialMenuWidget`` at the ``emblem*4`` canvas centered on the anchor (the
        emblem's screen center, by the emblem-center invariant) and reveals the
        internal dim, then returns the menu so the caller can wire its intent
        signals. A no-op (returns None) when framed or already open.

        The cluster window is NOT resized: the dim is a child of ``_grid_host`` (Qt
        clips it to the host), so growing the window can never enlarge the dim - it
        only reflows the host's fill layout and drags the emblem off the anchor. The
        window stays at the closed bbox; only the SEPARATE radial top-level spans the
        full canvas.

        Transaction-safe: the whole setup is guarded so a mid-build failure can never
        leak an untracked top-level. The surface + menu are tracked BEFORE any
        fallible step, so on ANY error ``close_radial_menu()`` tears the partial state
        down and the method fails closed (returns None, ``is_radial_open`` False)."""
        if not self._active:
            return None
        if self._radial_surface is not None:
            return None  # already open (and already wired by the first call)
        from utils.overlay.cluster_surface import RadialSurface
        from utils.overlay.radial_menu import RadialMenuWidget, radial_anim_enabled
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QPainterPath
        try:
            emblem_dia, canvas = self._radial_canvas()
            menu = RadialMenuWidget(emblem_diameter=emblem_dia)
            self._radial_size = canvas
            ax, ay = self._anchor
            geom = QRect(int(ax - canvas / 2), int(ay - canvas / 2), canvas, canvas)
            surface = RadialSurface(backend=self._backend)
            # Track the surface + menu IMMEDIATELY (before any fallible host/show), so
            # a failure from here on is cleaned up by close_radial_menu() instead of
            # leaking a built-but-untracked top-level.
            self._radial_surface = surface
            self._radial_menu = menu
            surface.host(menu)
            surface.set_overlay_geometry(geom)
            self._safe_call(surface, "prepare_initial_state")
            surface.show()
            # NON-EMPTY click region: the whole radial canvas accepts clicks (the
            # cluster window stays click-through; this surface is additive).
            path = QPainterPath()
            path.addRect(0, 0, canvas, canvas)
            self._apply_radial_input_shape(path)
            # Reposition the dim to the CURRENT scale's emblem*4 canvas BEFORE showing
            # it: a scale-while-CLOSED leaves the dim sized to the old (enter-time)
            # canvas, so without this it would flash stale on open.
            self._position_internal_dim()
            # Reveal the internal dim behind the ring.
            dim = self._dim
            if dim is not None:
                self._safe_call(dim, "show")
                try:
                    dim.start_reveal(animate=radial_anim_enabled())
                except Exception:
                    pass
            self._restack_internal_layers()
            try:
                menu.start_reveal()
            except Exception:
                pass
            return menu
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster_controller.open_radial_menu() FAILED; rolling "
                          "back (fail-closed):\n" + traceback.format_exc())
            self.close_radial_menu()
            return None

    def close_radial_menu(self) -> None:
        """Tear down the radial top-level and hide (but keep) the internal dim.
        Idempotent: a call when the radial was never open is a safe no-op.

        The cluster window is never resized here: it stays at the closed bbox the
        whole time the radial is open (the radial-open expansion was removed), so
        there is nothing to shrink back."""
        surface = self._radial_surface
        self._radial_surface = None
        self._radial_menu = None
        self._radial_size = 0
        if self._radial_reshape_timer is not None:
            self._radial_reshape_timer.stop()  # drop any pending settle reshape
        dim = self._dim
        if dim is not None:
            self._safe_call(dim, "hide")
        if surface is not None:
            self._safe_call(surface, "hide")
            self._safe_call(surface, "deleteLater")  # the menu is OWNED; it dies too
        self._restack_internal_layers()

    def _reposition_radial(self) -> None:
        """Keep the radial top-level + internal dim sized and centered on the emblem
        (anchor) at the CURRENT scale. On a scale change the ``emblem*4`` canvas
        grows/shrinks with the emblem, so the menu's emblem diameter + the surface
        size + the dim follow; the radial click-region re-apply is DEFERRED to the
        settle timer (re-applying the X11 input shape under the pointer mid-scroll
        stalls the wheel stream). No-op when the radial is closed."""
        if not self.is_radial_open:
            return
        from PySide6.QtCore import QRect
        emblem_dia, canvas = self._radial_canvas()
        resized = canvas != self._radial_size
        self._radial_size = canvas
        ax, ay = self._anchor
        geom = QRect(int(ax - canvas / 2), int(ay - canvas / 2), canvas, canvas)
        surface = self._radial_surface
        if surface is not None:
            if resized and self._radial_menu is not None:
                try:
                    self._radial_menu.set_emblem_diameter(emblem_dia)
                except Exception:
                    pass
            try:
                surface.set_overlay_geometry(geom)
            except Exception:
                pass
            if resized:
                self._schedule_radial_reshape()
        # The dim is a _grid_host-local child, so it re-centers on the emblem (which
        # apply_metrics already moved) at the new canvas.
        self._position_internal_dim()
        self._restack_internal_layers()

    def _schedule_radial_reshape(self) -> None:
        """(Re)start the settle timer that re-applies the radial click region after a
        scale burst quiesces. Re-armed every notch, so the X11 ShapeInput re-apply
        runs ONCE after scrolling pauses (mirrors
        ``OverlayGroupController._schedule_radial_reshape``)."""
        from PySide6.QtCore import QTimer
        if self._radial_reshape_timer is None:
            self._radial_reshape_timer = QTimer()
            self._radial_reshape_timer.setSingleShot(True)
            self._radial_reshape_timer.setInterval(100)
            self._radial_reshape_timer.timeout.connect(self._reapply_radial_shape)
        self._radial_reshape_timer.start()

    def _reapply_radial_shape(self) -> None:
        """Apply the full-canvas click region at the current radial size. Fired by
        the settle timer; a no-op once the menu is closed."""
        surface = self._radial_surface
        if surface is None or self._radial_size <= 0:
            return
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.addRect(0, 0, self._radial_size, self._radial_size)
        self._apply_radial_input_shape(path)

    def _apply_radial_input_shape(self, path) -> None:
        """Apply *path* as the radial surface's INPUT (click-accept) shape via the
        backend. Best-effort: a shape failure must never break open/scale."""
        surface = self._radial_surface
        if surface is None:
            return
        try:
            self._backend.apply_input_shape(surface, path, surface.devicePixelRatio())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Persistence (anchor + scale + monitor identity)
    # ------------------------------------------------------------------
    @staticmethod
    def _screens() -> list:
        """Connected screens as ``(name, left, top, right, bottom)`` logical tuples
        - the primitive form the pure persistence helpers consume."""
        from PySide6.QtGui import QGuiApplication
        out = []
        for s in QGuiApplication.screens():
            g = s.geometry()
            out.append((s.name(), g.left(), g.top(), g.right(), g.bottom()))
        return out

    def _load_persisted_state(self) -> bool:
        """Restore the saved cluster scale + anchor, clamping the anchor to a
        currently-visible monitor (recenter if the saved monitor is gone). No-op
        without a settings object (the stub/orchestration tests).

        Returns True if a SAVED anchor was restored, so a caller can skip the
        default-anchor fallback: a saved anchor of (0, 0) is a VALID origin point
        and must NOT be mistaken for the no-QApplication sentinel. The scale is
        always set (the saved value, or 1.0 when nothing is saved)."""
        if self._settings is None:
            return False
        from utils.overlay.persistence import (
            clamp_anchor_to_screens, load_overlay_state,
        )
        try:
            anchor, scale, monitor = load_overlay_state(self._settings)
            self._scale = scale
            if anchor is not None:
                self._anchor = clamp_anchor_to_screens(
                    anchor, monitor, self._screens())
                return True
            return False
        except Exception:
            # A corrupt/raising settings store must never tank enter() (the user
            # would be locked out of transparent mode until they clear config):
            # degrade to defaults (default anchor + scale 1.0) so the overlay still
            # opens, and trace it.
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster_controller._load_persisted_state() FAILED; "
                          "degrading to defaults:\n" + traceback.format_exc())
            self._scale = 1.0
            self._anchor = self._default_anchor()
            return False

    def _save_state(self) -> None:
        """Persist the current cluster anchor + scale + the monitor it sits on.
        No-op without a settings object."""
        if self._settings is None:
            return
        from utils.overlay.persistence import monitor_for_anchor, save_overlay_state
        monitor = monitor_for_anchor(self._anchor, self._screens())
        save_overlay_state(self._settings, self._anchor, self._scale, monitor)

    def _schedule_save(self) -> None:
        """Debounce a persistence write (TRAILING edge): each call (re)starts the
        single-shot timer, so a burst of drag/scale changes collapses into ONE
        settings write ~250ms after the LAST change. No-op without settings or
        while framed."""
        if self._settings is None or not self._active:
            return
        from PySide6.QtCore import QTimer
        self._save_pending = True
        if self._save_timer is None:
            self._save_timer = QTimer()
            self._save_timer.setSingleShot(True)
            self._save_timer.setInterval(250)
            self._save_timer.timeout.connect(self._run_pending_save)
        # Restart on every call: a still-running timer is reset so only a quiescent
        # gesture (no change for 250ms) actually fires the write (true debounce, not
        # a throttle that writes every 250ms during a long drag).
        self._save_timer.start()

    def _run_pending_save(self) -> None:
        """Debounce timeout: write the pending state. Clears the pending gate
        regardless, then guards active/settings so a stray timeout AFTER the
        controller is framed can never write state (defense-in-depth: leave() also
        stops the timer)."""
        self._save_pending = False
        if not self._active or self._settings is None:
            return
        self._save_state()

    def flush_pending_save(self) -> None:
        """Write any pending debounced save synchronously NOW and stop the timer
        (tests + leave). No-op when nothing is pending."""
        if self._save_pending:
            self._save_pending = False
            if self._save_timer is not None:
                self._save_timer.stop()
            self._save_state()

    # ------------------------------------------------------------------
    # Teardown helpers
    # ------------------------------------------------------------------
    def _release_and_restore(self, surface, token) -> None:
        """Release the borrowed host from *surface*, then restore it to the tab.

        release-before-restore: the surface NEVER owns the borrowed host, but Qt
        parent-child destruction would delete a still-hosted child, so the host
        is released from the surface first; then ``restore_cluster_host`` re-inserts
        it into the tab's outer layout at its exact slot.

        If release() RAISES, the host may still be hosted in the surface, so the
        restore is SKIPPED (and ``_teardown_surface`` will orphan the surface
        rather than destroy the still-hosted live cluster subtree) - mirroring
        OverlayGroupController._restore_widgets, which likewise skips restore on a
        release failure. ``token`` is None when capture never ran (restore is then
        skipped); a None token is a documented safe no-op for
        ``restore_cluster_host`` regardless.
        """
        if surface is not None and not self._safe_call(surface, "release"):
            return  # release failed: host may still be hosted -> skip restore
        if token is not None and self._card_provider is not None:
            try:
                self._card_provider.restore_cluster_host(token)
            except Exception:
                pass

    def _teardown_surface(self, surface) -> None:
        """Hide, then destroy *surface* - but ONLY if release() succeeds.

        Mirrors OverlayGroupController._teardown: release() MUST succeed before
        deleteLater(). If release() raises, the surface may still host the
        borrowed cluster subtree (4 cards + emblem + glow); destroying it would
        delete those live widgets, so the surface is RETAINED in ``_orphans``
        (Python GC can't collect a referenced object) and never deleted. Leaking
        the surface keeps the cluster ALIVE (recoverable) instead of deleted
        (fatal to the tab's widget tree).
        """
        if surface is None:
            return
        self._safe_call(surface, "hide")
        if self._safe_call(surface, "release"):
            self._safe_call(surface, "deleteLater")
        else:
            self._orphans.append(surface)

    def _emit_active_changed(self) -> None:
        """Notify the optional observer of the CURRENT active state. Best-effort:
        an observer error must never corrupt the controller's enter/leave."""
        cb = self._on_active_changed
        if cb is None:
            return
        try:
            cb(self._active)
        except Exception:
            pass
