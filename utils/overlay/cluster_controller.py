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

Scaling, occupancy, hover-peek, ghost clicks, the radial menu, drag, and
persistence are LATER tasks and are intentionally NOT built here.
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
        # Stored for later tasks (anchor/scale persistence); unused in this slice.
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

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self._active

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

    def _compute_window_rect(self):
        """The SCREEN rect for the single cluster window: sized to the borrowed
        host and placed so the emblem center lands on the anchor. Radial/dim are
        LATER tasks, so radial_open=False, dim_extent=(0, 0)."""
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
        self._active = True
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
        # Cancel any pending settle and reset scaling state so a re-enter starts
        # framed (scale 1.0, no in-flight gesture). A late timer firing post-leave
        # is a guarded no-op, but stopping it here avoids the wasted callback.
        if self._settle_timer is not None:
            self._settle_timer.stop()
        self._scaling_active = False
        self._input_phase = None
        self._scale = 1.0
        # Reset framed (scale-1.0) metrics so the cards come back at base scale.
        if provider is not None:
            try:
                from utils.overlay.card_metrics import CardMetrics
                provider.apply_metrics(CardMetrics(1.0))
            except Exception:
                pass
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
        self.scale = step_scale(self.scale, notches)
        provider = self._card_provider
        if provider is not None:
            try:
                from utils.overlay.card_metrics import CardMetrics
                provider.apply_metrics(CardMetrics(self.scale))
            except Exception:
                pass
        # The cluster size changed: recompute + apply the window rect ONCE (same
        # emblem-centered placement path enter() uses).
        rect = self._compute_window_rect()
        if self._surface is not None:
            self._surface.set_overlay_geometry(rect)
        # Drive the input-shape phase machine: broad now, exact on settle.
        self._enter_broad_phase(rect)

    def move_group(self, dx: int, dy: int) -> bool:
        """Shift the cluster anchor by (dx, dy), clamp to the screen envelope, and
        reposition the window. Returns True if the window moved.

        Drag is LOCKED OUT while a scale gesture is live (``_scaling_active``):
        returns False without moving so a wheel-zoom is never fought by a stray
        drag. Also a no-op (False) when not active.
        """
        if not self._active:
            return False
        if self._scaling_active:
            return False
        ax, ay = self._anchor
        self._anchor = (ax + dx, ay + dy)
        rect = self._compute_window_rect()
        from utils.overlay.cluster_geometry import clamp_to_envelope
        rect = clamp_to_envelope(rect, self._screens_xywh(), self._move_margin())
        if self._surface is not None:
            self._surface.set_overlay_geometry(rect)
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
        """Settle callback (directly callable from tests): leave the broad phase,
        mark the exact phase, and apply the EXACT input shape (emblem + visible
        controls union). No-op once framed (a late timer firing post-leave)."""
        self._scaling_active = False
        self._input_phase = "exact"
        if not self._active or self._surface is None:
            return
        from utils.overlay.cluster_geometry import input_union
        emblem_rect = self._emblem_rect()
        cells = self._card_cell_rects()
        card_controls = {slot_id: [r] for slot_id, r in cells.items()}
        visible = list(cells.keys())
        region = input_union(emblem_rect, card_controls, visible)
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

    def _card_cell_rects(self) -> dict:
        """``{slot_id: QRect}`` per-card control rects (window-local). Placeholder
        per-cell rects today; occupancy refines ``visible`` + the real per-control
        rects in a LATER task. Empty dict when the provider has no accessor."""
        fn = getattr(self._card_provider, "card_cell_rects", None)
        if fn is None:
            return {}
        try:
            return dict(fn())
        except Exception:
            return {}

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
