"""Single-window cluster overlay controller (enter / leave / borrow / reset).

``ClusterOverlayController`` is the single-window analog of
``OverlayGroupController``: instead of one overlay surface per card, it borrows
the WHOLE ``_grid_host`` subtree (glow + the 2x2 card grid + the emblem) into ONE
``ClusterSurface`` so the cluster moves and scales as a single rigid window. Its
constructor is drop-in compatible with ``OverlayGroupController`` so the two can
be swapped behind the same call sites.

Lifecycle entry points:

* ``enter()`` - build the cluster surface, borrow the host, place + show it, then
  HIDE the main window (no taskbar/Alt-Tab entry while floating).
* ``leave()`` - reset framed (scale-1.0) metrics, restore the borrowed host to the
  tab, tear down the surface, and re-show the main window.

Both are FAIL-CLOSED, mirroring ``OverlayGroupController``: if any step of
``enter()`` raises, the borrowed host is returned to the tab, the surface is torn
down, the window is re-shown if it was hidden, and the controller stays Framed
(``is_active`` False) - the app is never left with a half-built overlay. No
exception escapes ``enter()`` (it returns ``False``). ``leave()`` is likewise
guarded: a restore failure must still reset metrics, restore the window, and
clear state.

Scaling is a FIXED-ENVELOPE TRANSFORM: the window is sized ONCE (on enter) to
the SCALE_MAX bounding box pivoted on the emblem center, and NEVER resizes or
moves during a scale gesture - a scroll notch is one uniform zoom transform on
the live host (``ClusterSurface.set_cluster_scale``, optionally tweened), plus
the input-shape phase machine (broad-while-scaling, exact-on-settle). The host
keeps its framed 1.0 layout forever; every window-local hit/shape consumer maps
host coordinates through ``cluster_geometry.map_host_rect_to_window``. Window
geometry changing per notch was the scale judder (an XWayland resize+move is
never atomic across the compositor), and per-notch metric re-layout was the
non-uniformity (independent per-element rounding); the transform removes both
by construction. Drag, occupancy (the visible set narrows the EXACT input shape
while the grid SHELL stays fixed - empty cards keep their cell, never
hidden/reshaped), and persistence (load the saved anchor + scale on enter,
debounced save on scale/move, flush on leave) are built here. Hover-peek,
ghost-click pass-through, the radial menu, and the portable Settings panel are
built here too: this module is the whole single-window controller.
"""
from __future__ import annotations

from utils.overlay.backend import get_overlay_backend
from utils.overlay.peek import GhostPointStore, peeking_indices, control_hits
from utils.overlay.scale import step_scale
from utils.screen_coords import emitted_to_logical
from utils.settings_keys import GHOST_CURSORS_ENABLED, GHOST_CURSORS_CONTROL_CARDS

# Quiescence window after the last scale notch before the EXACT input shape is
# swapped in. Long enough that a continuous wheel spin keeps re-arming it (so the
# broad shape stays up and keeps capturing notches), short enough to feel instant.
_SETTLE_INTERVAL_MS = 250

# Per-notch zoom tween duration. Each notch retargets the running animation from
# the CURRENT rendered scale to the accumulated target, so a scroll burst reads
# as one continuous zoom (mirrors the proven proxy-era ramp timing).
_SCALE_ANIM_MS = 140


def _scale_anim_enabled() -> bool:
    """False when ``TTMT_NO_OVERLAY_SCALE_ANIM`` is set truthy: notches then snap
    to the target scale synchronously (still perfectly uniform - the tween is
    polish, not correctness). Kill switch for live tuning + deterministic tests."""
    import os
    return os.environ.get("TTMT_NO_OVERLAY_SCALE_ANIM", "").strip().lower() \
        in ("", "0", "no", "n", "false", "f", "off")


class ClusterOverlayController:
    """Borrow the whole cluster into one window; hide the main window.

    Drop-in compatible constructor with ``OverlayGroupController``. The single
    ``ClusterSurface`` is built by ``surface_factory`` (a zero-arg callable) when
    supplied - tests inject a recording stub - otherwise a real ``ClusterSurface``
    bound to the backend is built.
    """

    def __init__(self, window, backend=None, settings=None, surface_factory=None,
                 card_provider=None, on_active_changed=None,
                 dismiss_capture_factory=None):
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
        # timers running while the hidden main window would stop them). Never
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
        # quitOnLastWindowClosed value captured at enter (restored on leave/fail):
        # while active the main window is HIDDEN, so Qt's quit-on-last-window
        # default would fire if anything closed the remaining overlay windows.
        self._quit_prev: bool = True
        self._taskbar_rep = None   # TaskbarRepresentative while active (or None)
        # Peek-active latch for the rep's blanking rule (set by _peek_tick): a
        # faded card under an opaque mirror copy would visibly cancel the fade.
        self._rep_peek_active = False

        # Scaling state. The cluster is ONE window with FIXED geometry (no proxy/
        # park/snapshot, no per-notch resize): a notch retargets the zoom tween on
        # the surface's whole-cluster transform, plus the input-shape phase machine
        # (broad-while-scaling, exact-on-settle). _scale is the AUTHORITATIVE
        # target (persisted, used for all hit/shape mapping); _view_scale tracks
        # the value the view currently RENDERS at (they differ only mid-tween,
        # while every mapping consumer is suspended by _scaling_active).
        self._scale: float = 1.0
        self._view_scale: float = 1.0
        self._scale_anim = None
        # Fixed-envelope placement, computed once per enter() from the framed 1.0
        # host: envelope size, the window-local pivot the emblem center sits on at
        # every scale, the emblem center within the 1.0 host, and the 1.0 host
        # size. None while framed (pre-enter callers recompute fresh).
        self._envelope: tuple[int, int] | None = None
        self._pivot: tuple[int, int] | None = None
        self._emblem_center: tuple[int, int] | None = None
        self._host_size: tuple[int, int] | None = None
        # Input-shape phase machine: re-applying the EXACT (per-control) input
        # shape under the pointer every notch can stall the wheel stream, so each
        # notch applies one BROAD (full-window) shape and (re)arms a settle timer
        # that swaps in the EXACT shape once the gesture quiesces.
        self._scaling_active: bool = False
        self._input_phase: str | None = None
        self._settle_timer = None

        # Occupancy. The grid GEOMETRY is fixed (retainSizeWhenHidden keeps every
        # quadrant's space, so the pinwheel never reflows), but an EMPTY card is
        # hidden VISUALLY (cell setVisible(False)) as well as dropped from the
        # EXACT input (click-through) shape - matching the legacy overlay, which
        # hid empty card SURFACES (0 toons -> 0 cards, 1 toon -> 1 card).
        # _visible_cells seeds from provider.occupied_cells() on enter() (all four
        # when the provider has no occupancy) and is reconciled live off
        # occupied_cells_changed; leave() restores every shell visible for framed
        # mode (which always shows all four) with its original retain flag.
        self._visible_cells: set = {0, 1, 2, 3}
        self._occupancy_connected: bool = False
        self._cell_retain_flags: dict = {}
        # User Hide-Cards toggle (the radial's bottom-center spoke): while True,
        # _target_visible_cells returns the EMPTY set - every card is hidden even
        # if its game window is present - and the same occupancy-reconcile path
        # applies it (visual hide with retained size, input shape, rep re-align).
        # Float-session-scoped: leave() always resets it, so a session never
        # starts with invisible cards.
        self._cards_hidden: bool = False
        # Tuck animation (Hide-Cards): a transient TuckGhostLayer child of the
        # borrowed _grid_host (the internal-dim hosting pattern) animating card
        # SNAPSHOTS into/out of the emblem while the real cells flip via the
        # instant path. _tuck_show_pending marks a show whose authoritative
        # flip is deferred to the animation's end (the cells stay hidden until
        # the ghosts land); _finish_tuck() is the single idempotent finalizer.
        self._tuck_layer = None
        self._tuck_anim = None
        self._tuck_show_pending: bool = False

        # Glove echo (ghost cursors over the cards). The confined ghost windows
        # stack BELOW this dock-layer cluster by construction, so the cluster
        # paints its own glove echo: a paint-only GhostEchoLayer child of the
        # surface, clipped to the visible painted content (_echo_content_path).
        # Fed by GhostCursorController through the ghost_echo_* sink methods;
        # created lazily per float session, dies with the surface.
        self._ghost_echo = None

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
        # Click-off dismissal: while the ring is open, a portal-safe GLOBAL
        # mouse-press watcher (XRecord; injectable factory for tests) dismisses
        # the ring on any press that is not on our chrome. The press itself is
        # never consumed - the radial window's input shape is only the spokes,
        # so it lands on whatever sits beneath. The bridge marshals the capture
        # thread's events onto the GUI thread (created lazily, GUI thread only).
        self._dismiss_capture_factory = dismiss_capture_factory
        self._radial_dismiss_capture = None
        self._press_bridge = None

        # Portable Settings panel. A SEPARATE click-accepting source-cleared
        # top-level (PanelSurface) hosting an arbitrary CALLER-PROVIDED widget (the
        # floating SettingsTab container), centered on the anchor and floating ABOVE
        # the emblem + radial. Unlike the cluster window it does NOT borrow/reflow
        # _grid_host, so it is simpler than the dim: a plain owned surface. Its size
        # is fixed at open (emblem*6 at the open-time scale) and only re-CENTERED as
        # the cluster moves/scales - never rescaled. ``_panel_on_close`` runs FIRST
        # in close_panel_surface() so the caller reparents its hosted content out
        # before the surface (and with it the hosted container) is torn down. The
        # panel exists only between open_panel_surface() and close_panel_surface().
        self._panel_surface = None
        self._panel_on_close = None
        self._panel_size: int = 0

        # Hover-peek / ghost-click / drag (Task 8), ported from
        # OverlayGroupController to CLUSTER-LOCAL (one window) hit tests.
        #
        # Ghost points (click-sync ghost cursors) accumulate in the store, fed by
        # on_ghost_event/on_ghost_clear (caller wiring is a LATER task). A ~30ms
        # QCursor poll (_peek_timer) unions the real cursor with the ghost points
        # and fades the hovered card via the provider's SAFE paint-time
        # set_shell_extra_opacity (never windowOpacity, never a QGraphicsEffect).
        # Per-slot (0-3) fade progress 0.0 (opaque) -> 1.0 (peeked).
        self._peek_store = GhostPointStore()
        self._peek_timer = None
        self._peek_progress = [0.0, 0.0, 0.0, 0.0]
        # Emblem-drag poll: move_requested fires ONCE at drag-start with no delta,
        # so the controller tracks the global cursor itself (a ~16ms poll) and
        # shifts the anchor via the clamped move_group until the button releases.
        self._drag_timer = None
        self._drag_last = None
        # The _Emblem whose gesture signals (toggle/move/scroll) are wired to this
        # controller by connect_emblem. Tracked so a re-bind can drop the previous
        # emblem's three connections (mirrors OverlayGroupController._emblem). This
        # is the controller's OWN bookkeeping slot - distinct from the provider's
        # self._card_provider._emblem (the widget used for placement/hit tests).
        self._emblem = None

        # Multi-monitor / HiDPI screen-change reshape. The single cluster window's
        # input shape is a LOGICAL surface-local path that the backend converts to
        # DEVICE pixels via surface.devicePixelRatio() AT APPLY TIME. When the window
        # moves to a monitor with a different device-pixel ratio the logical path is
        # unchanged but the device conversion changes, so the shape MUST be re-applied
        # at the new DPR (else the click-through region is wrong on the new monitor).
        # The QWindow's screenChanged signal drives that re-apply. windowHandle() may
        # be None until the window is shown, so the connect runs AFTER show() in
        # enter(); the guard flag keeps it idempotent + the handle is remembered so
        # leave() can disconnect exactly what it connected.
        self._screen_change_connected: bool = False
        self._screen_change_handle = None

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def is_radial_open(self) -> bool:
        """True while the radial MENU is up (between open_radial_menu and
        close_radial_menu). The radial top-level itself is PERSISTENT - pre-mapped
        empty at enter() and reused across opens, because MAPPING a fresh
        notification-typed window is what plays the compositor's open animation
        (KWin slides it in from the screen edge) - so the hosted menu, not the
        surface, is the open marker."""
        return self._radial_menu is not None

    @property
    def is_panel_open(self) -> bool:
        """True while the portable Settings panel is up (between open_panel_surface
        and close_panel_surface). Like the radial, the panel top-level is
        PERSISTENT (pre-mapped empty at enter, content swapped per open), so the
        open marker is the nonzero open-time size, not surface existence."""
        return self._panel_surface is not None and self._panel_size > 0

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

    @staticmethod
    def _quit_on_last_window() -> bool:
        """Current QApplication.quitOnLastWindowClosed (True when appless)."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        return bool(app.quitOnLastWindowClosed()) if app is not None else True

    @staticmethod
    def _set_quit_on_last_window(value: bool) -> None:
        """Scoped quit guard. While the overlay is active the main window is
        HIDDEN (not minimized) so it no longer counts as a visible window;
        without this guard, closing/destroying the overlay windows mid-float
        (or during leave() teardown) would fire quit-on-last-window-closed and
        exit the app. Best-effort: never raises."""
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                app.setQuitOnLastWindowClosed(bool(value))
        except Exception:
            pass

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
        """``(emblem disc diameter, square canvas px)`` for the radial menu at
        the current cluster scale. ONE formula shared by open_radial_menu and the
        scale path so the two never drift (mirrors
        ``OverlayGroupController._radial_canvas``)."""
        from utils.overlay.card_metrics import CardMetrics
        emblem_dia = float(CardMetrics(self._scale).emblem)
        return emblem_dia, int(emblem_dia * 4)

    def _radial_canvas_max(self) -> int:
        """The FIXED radial-surface side: the ``emblem*4`` canvas at SCALE_MAX.
        The radial top-level is sized to this once at open and never resized by a
        scale gesture (only the menu's painted ring diameter and the centered
        click region track the live scale) - the same no-geometry-during-scale
        discipline as the cluster window, so scaling with the ring open cannot
        judder the ring window either."""
        from utils.overlay.card_metrics import CardMetrics
        from utils.overlay.scale import SCALE_MAX
        return int(CardMetrics(SCALE_MAX).emblem) * 4

    def _envelope_spec(self):
        """``(envelope_size, pivot, emblem_center, host_size)`` for placement and
        transform mapping. Returns the values stored by ``enter()`` while active;
        recomputes fresh from the provider otherwise (pre-enter callers), so the
        math is identical either way."""
        if self._envelope is not None:
            return (self._envelope, self._pivot, self._emblem_center,
                    self._host_size)
        from utils.overlay.cluster_geometry import envelope_for
        from utils.overlay.scale import SCALE_MAX
        w, h = self._cluster_size()
        emblem_center = self._emblem_center_local(w, h)
        size, pivot = envelope_for((w, h), emblem_center, SCALE_MAX)
        return (size, pivot, emblem_center, (w, h))

    def _map_host_rect(self, rect):
        """Map a host-local (framed 1.0) rect into window coords under the current
        AUTHORITATIVE scale - the same math the surface's proxy transform renders
        with, so hit/shape rects and pixels can never drift apart."""
        from utils.overlay.cluster_geometry import map_host_rect_to_window
        _size, pivot, emblem_center, _hs = self._envelope_spec()
        return map_host_rect_to_window(rect, emblem_center, pivot, self._scale)

    def _map_host_point(self, point):
        """Map a host-local (framed 1.0) ``(x, y)`` point into window coords under
        the current AUTHORITATIVE scale - the single-point companion of
        ``_map_host_rect``."""
        from utils.overlay.cluster_geometry import map_host_point_to_window
        _size, pivot, emblem_center, _hs = self._envelope_spec()
        return map_host_point_to_window(point, emblem_center, pivot, self._scale)

    def _compute_window_rect(self):
        """The SCREEN rect for the single cluster window: the FIXED max-scale
        envelope placed so the pivot (= the emblem center at every scale) lands on
        the anchor.

        The rect is independent of the current scale AND of radial state - scaling
        zooms the transform inside this window; radial-open never grows it (the
        radial menu is its own top-level, the internal dim a Qt-clipped child of
        ``_grid_host``). The window only ever MOVES (drag/clamp), never resizes,
        which is the whole judder fix: there is no per-notch geometry for the
        compositor to mis-order."""
        from utils.overlay.cluster_geometry import window_rect_for
        size, pivot, _emblem_center, _host_size = self._envelope_spec()
        return window_rect_for(size, pivot, self._anchor)

    def _build_surface(self):
        if self._surface_factory is not None:
            return self._surface_factory()
        from utils.overlay.cluster_surface import ClusterSurface
        return ClusterSurface(backend=self._backend)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def enter(self) -> bool:
        """Build + show the cluster surface around the borrowed host, then hide
        the main window (no taskbar/Alt-Tab entry while floating). No-op
        (returns True) if already active.

        Transactional / fail-closed: returns True on success (now transparent),
        or False if any step raised - in which case the borrowed host is returned
        to the tab, the surface is torn down, the main window is re-shown if it
        was hidden, and the controller stays Framed. No exception escapes.
        """
        if self._active:
            return True
        from utils.overlay.backend import overlay_trace
        from PySide6.QtCore import Qt as _Qt
        _emb0 = getattr(self._card_provider, "_emblem", None)
        overlay_trace(
            f"cluster.enter begin: backend_avail={self._backend.is_available()} "
            f"emblem={_emb0 is not None} emblem_passive="
            f"{_emb0.testAttribute(_Qt.WA_TransparentForMouseEvents) if _emb0 is not None else 'n/a'}")
        provider = self._card_provider
        surface = None
        token = None
        hidden = False
        try:
            surface = self._build_surface()
            if not getattr(self._backend, "wants_taskbar_rep", lambda: True)():
                # Windows taskbar identity: the backend skips the aligned-mirror
                # rep, so the CLUSTER window itself is the app's taskbar entry
                # while floating. WIN_TASKBAR_IDENTITY is read pre-map by
                # set_initial_state (APPWINDOW instead of TOOLWINDOW); the title
                # names the button; spontaneous close (taskbar Close / preview
                # X) quits like the rep did; minimize is bounced (a minimized
                # cluster strands the whole float UI). Plain attributes so
                # injected test surfaces need no extra API.
                surface.WIN_TASKBAR_IDENTITY = True
                surface._on_spontaneous_close = self._request_app_quit
                surface._bounce_minimize = True
                try:
                    surface.setWindowTitle("ToonTown MultiTool")
                except Exception:
                    pass
                overlay_trace("cluster.enter: taskbar identity ON "
                              "(cluster window is the taskbar entry)")
            token = provider.capture_cluster_host()
            # Restore the persisted scale + anchor BEFORE computing placement so
            # the window re-centers on the remembered anchor and the transform
            # renders at the remembered zoom. Nothing saved (or no settings) ->
            # scale 1.0 + the default anchor.
            self._load_persisted_state()
            # Measure the FRAMED 1.0 host (its layout is intact after the detach)
            # and derive the fixed envelope + pivot from it. The host keeps this
            # 1.0 layout for the whole overlay session: a restored/changed scale
            # is a TRANSFORM, never an apply_metrics re-layout.
            from utils.overlay.cluster_geometry import envelope_for
            from utils.overlay.scale import SCALE_MAX
            w, h = self._cluster_size()
            # Fix the host at its 1.0 size and SETTLE it BEFORE measuring the
            # pivot (mirrors CardSurface.host's base_size clamp; the captured
            # token restores the original constraints on leave). Order is
            # load-bearing: framed mode STRETCHES the host past its sizeHint and
            # centers the emblem on that live size, so measuring first and
            # resizing after freezes a STALE emblem center into the pivot - the
            # next provider relayout (apply_cell_permutation -> _relayout_all ->
            # _position_emblem) re-centers the emblem to the fixed size's center
            # and the emblem drifts off the pivot (seen live as the radial ring
            # off-center from the emblem). Fixing the size, activating the
            # layout, and re-asserting the provider's own emblem placement FIRST
            # makes the measured center the settled one; any later
            # _position_emblem lands on the same point (the size never changes
            # again).
            host = provider._grid_host
            host.setFixedSize(w, h)
            lay = host.layout()
            if lay is not None:
                lay.activate()
            self._safe_call(provider, "_position_emblem")
            emblem_center = self._emblem_center_local(w, h)
            size, pivot = envelope_for((w, h), emblem_center, SCALE_MAX)
            self._host_size = (w, h)
            self._emblem_center = emblem_center
            self._envelope = size
            self._pivot = pivot
            # Host through the transform seam when the surface provides it (the
            # real ClusterSurface); a plain-host surface (test stubs) still gets
            # correct placement + input shapes - the mapping math is controller-
            # side - it just renders unscaled.
            host_scaled = getattr(surface, "host_scaled", None)
            if host_scaled is not None:
                host_scaled(host, emblem_center, pivot, size,
                            initial_scale=self._scale)
            else:
                surface.host(host)
            self._view_scale = self._scale
            rect = self._compute_window_rect()
            surface.set_overlay_geometry(rect)
            # Install the pre-map EWMH state (skip-taskbar/pager + above) BEFORE the
            # window is mapped, mirroring the proven OverlayGroupController.enter()
            # discipline, so the single cluster window never flashes in the taskbar
            # or maps below the games on the first frame. Best-effort (_safe_call): a
            # decorative WM-hint failure must never fail-close an otherwise valid
            # borrow.
            self._safe_call(surface, "prepare_initial_state")
            surface.show()
            # HIDE, not minimize: a minimized window keeps a taskbar entry whose
            # hover preview is the stale window-UI texture and whose click
            # restores the gutted window UI (the cards+emblem are borrowed into
            # this overlay). A hidden window has no taskbar entry and no Alt-Tab
            # entry - the radial Window spoke is the only way back, by
            # construction. The surface was shown above, so there is never an
            # instant with zero visible windows. Capture the previous guard value
            # BEFORE the flag, so a capture failure can never trigger a restore
            # of a value the guard never modified; flag BEFORE the guard-off +
            # hide so a failure in either still triggers the except-path restore;
            # the quit guard BEFORE the hide so no window close can quit the app
            # while the main window is not counted as visible.
            self._quit_prev = self._quit_on_last_window()
            hidden = True
            self._set_quit_on_last_window(False)
            self._window.hide()
            overlay_trace("cluster.enter: main window HIDDEN "
                          "(float UI owns the taskbar); quit guard OFF")
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster_controller.enter() transaction FAILED:\n"
                          + traceback.format_exc())
            # Fail-closed: return the borrowed host to the tab FIRST
            # (release-before-restore so the surface never deletes the live host),
            # THEN restore the window (and the quit guard) if hidden, then destroy
            # the now-empty surface - same never-zero-visible-windows ordering
            # (and the same showNormal-then-guard order) as leave().
            self._release_and_restore(surface, token)
            if hidden:
                self._safe_call(self._window, "showNormal")
                self._set_quit_on_last_window(self._quit_prev)
            self._teardown_surface(surface)
            self._surface = None
            self._token = None
            self._active = False
            self._clear_envelope_state()
            return False
        self._surface = surface
        self._token = token
        # Seed the visible set from live occupancy and subscribe to changes so the
        # exact input shape tracks which cards actually hold a window. A provider
        # without occupancy degrades to all-visible (no signal -> no subscription).
        self._visible_cells = self._target_visible_cells()
        self._connect_occupancy()
        # Hide the EMPTY cells visually (retain-size so the pinwheel keeps its
        # shape): 0 toons -> 0 cards, 1 toon -> 1 card, matching the legacy
        # overlay's hidden empty surfaces. leave() restores every shell.
        self._apply_cell_visibility()
        self._active = True
        # Build the internal dim (hidden) now that the host is borrowed + measured.
        # Decorative + best-effort: a dim failure must never flip a successful enter
        # back to framed, so _build_internal_dim swallows its own errors.
        self._build_internal_dim()
        # Pre-map the PERSISTENT radial + panel top-levels now, empty (transparent
        # + click-through) - any compositor window-open animation plays once here
        # on invisible windows. Their OSD window type keeps them in a strictly
        # higher KWin layer than this dock cluster, so no raise order can ever
        # put the cluster (and its internal dim) above them. Best-effort: both
        # ensures self-clean on failure and re-run lazily at open.
        self._ensure_radial_surface()
        self._ensure_panel_surface()
        # Taskbar representative: the app's taskbar/Alt-Tab entry while the
        # main window is hidden (best-effort; see _ensure_taskbar_rep).
        self._ensure_taskbar_rep()
        # Clear any ghost points that leaked into the store while framed (a queued
        # on_ghost_event arriving after a prior leave()), so a stale hover can never
        # survive into this fresh session, then start the hover-peek poll (the ~30ms
        # QCursor union that fades the hovered card). Ghost points arrive via
        # on_ghost_event (caller wiring is a LATER task); the timer drives the fade
        # regardless of the real cursor.
        self._peek_store.clear()
        # Unlatch the rep's peek flag too: leave() resets it inside its try, so
        # a raising teardown step could carry a stale True into this session
        # and keep the fresh rep blanked until the next hover.
        self._rep_peek_active = False
        self._start_peek_timer()
        # Reshape on a monitor/DPI change: now that the surface is shown its native
        # windowHandle exists, so connect screenChanged to re-apply the input shape at
        # the new device-pixel ratio when the window crosses to another monitor.
        self._connect_screen_change()
        # Apply the EXACT click-through shape NOW (emblem + visible-card controls
        # union) so the cluster is click-through the instant it appears. Without this
        # the freshly-mapped window keeps X11's default FULL-RECT input region and
        # blocks clicks to the games underneath until the first scale/occupancy/
        # screen event reshapes it. This is the settled (non-scaling) terminal state,
        # so the phase is "exact" - identical to what _settle_input() lands on.
        self._input_phase = "exact"
        self._apply_exact_input_shape()
        from utils.overlay.backend import overlay_trace as _ot_ok
        _emb1 = getattr(self._card_provider, "_emblem", None)
        from PySide6.QtCore import Qt as _Qt2
        _ot_ok(
            f"cluster.enter OK: active={self._active} visible={self._visible_cells} "
            f"emblem_rect={self._emblem_rect()} emblem_passive="
            f"{_emb1.testAttribute(_Qt2.WA_TransparentForMouseEvents) if _emb1 is not None else 'n/a'}")
        self._emit_active_changed()   # self._active is True here
        return True

    def leave(self) -> None:
        """Restore the borrowed host to the tab, reset framed (scale-1.0)
        metrics, tear down the cluster surface, and restore the main window.
        No-op if framed.

        Fail-closed BY CONSTRUCTION: the whole teardown sequence runs inside a
        try/except, and the window restore + quit-guard restore + state clear
        run unconditionally after it - so no exit from leave() (not even a
        raising teardown step, e.g. a settings write failing inside the save
        flush) can leave the main window hidden, the quit guard off, or the
        controller stuck active.
        """
        if not self._active:
            return
        provider = self._card_provider
        surface = self._surface
        token = self._token
        try:
            # Persist the FINAL anchor + scale before any teardown/reset (the
            # remembered overlay position, restored on the next enter). MUST run
            # before the scale reset below, else the flush would save the framed
            # 1.0 instead of the scale the user left at. Then stop the save timer
            # unconditionally so no late timeout survives the leave (the active
            # guard in _run_pending_save is the backstop).
            self.flush_pending_save()
            if self._save_timer is not None:
                self._save_timer.stop()
            # The radial + portable panel must never outlive the overlay: close
            # them FIRST (the panel's on_close runs so the caller reparents its
            # content out; the radial deletes its menu + hides the dim) before any
            # host teardown - mirrors OverlayGroupController._teardown calling
            # close_panel_surface() + close_radial_menu(). Then destroy the
            # PERSISTENT (now-empty) top-levels; per-open close keeps them mapped
            # by design.
            self.close_panel_surface()
            self.close_radial_menu()
            # Snap any in-flight card tuck to its final state and destroy the
            # ghost layer BEFORE the host is restored - a stray ghost child
            # must never ride the borrowed _grid_host back into framed mode
            # (same discipline as the internal dim below).
            self._finish_tuck()
            self._destroy_persistent_surfaces()
            # The representative must not outlive the float session (the cluster
            # surface is still mapped here, so no zero-visible-window instant).
            self._teardown_taskbar_rep()
            # Stop the emblem-drag poll and the hover-peek poll. Settling the peek
            # (restoring every faded card to fully opaque) runs HERE - before the
            # host is restored - so the borrowed cards never return to the framed
            # grid stuck dim.
            self._end_drag()
            self._stop_peek_timer()
            self._rep_peek_active = False   # re-enter starts unlatched
            # Stop reshaping on monitor/DPI changes: disconnect the screenChanged
            # handler so a late signal after teardown can never re-apply a shape
            # to a dead surface.
            self._disconnect_screen_change()
            # Cancel any pending settle, stop the zoom tween, and reset scaling
            # state so a re-enter starts framed (scale 1.0, no in-flight gesture).
            # A late timer/frame firing post-leave is a guarded no-op, but
            # stopping here avoids the wasted callback.
            if self._settle_timer is not None:
                self._settle_timer.stop()
            if self._scale_anim is not None:
                self._scale_anim.stop()
            self._scaling_active = False
            self._input_phase = None
            self._scale = 1.0
            self._view_scale = 1.0
            # Disconnect occupancy first so a late occupied_cells_changed after
            # teardown is a safe no-op, and reset the visible set to the framed
            # default.
            self._disconnect_occupancy()
            self._visible_cells = {0, 1, 2, 3}
            # Un-hide every cell shell (framed mode always shows all four) and
            # restore the original retain-size flags BEFORE the host returns to
            # the tab.
            self._restore_cell_visibility()
            # Re-assert framed (scale-1.0) metrics. In the transform model the
            # host never left its 1.0 layout, so this is a defensive idempotent
            # no-op that guarantees the cards come back at base scale even if
            # something external re-metered the host mid-overlay.
            if provider is not None:
                try:
                    from utils.overlay.card_metrics import CardMetrics
                    provider.apply_metrics(CardMetrics(1.0))
                except Exception:
                    pass
            # Remove the internal dim BEFORE restoring the host, so the borrowed
            # _grid_host returns to framed mode with no stray overlay-only child.
            self._teardown_internal_dim()
        except Exception:
            # Swallow: leave() must be TOTAL. The host restore, window/guard
            # restore, and state clear below run regardless of where the
            # teardown broke.
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster.leave teardown raised:\n"
                          + traceback.format_exc())
        # INVARIANT: no exit from leave() may leave the host un-restored, the
        # main window hidden, the quit guard off, or the taskbar representative
        # alive - the lines below run on EVERY path (success or a swallowed
        # teardown failure). The host restore sits OUTSIDE the try (it is fully
        # self-guarded, so it cannot raise here): inside it, a raising earlier
        # step would skip it, and the unconditional _teardown_surface below
        # would then release the borrowed host PARENTLESS (bypassing the
        # _orphans net) while showNormal re-shows a GUTTED main window. Release
        # the host from the surface and restore it to the tab, THEN re-show the
        # main window BEFORE the surface teardown: the host is back (the window
        # is complete - no gutted flash) and the cluster surface is still
        # mapped, so there is never an instant with zero visible windows -
        # destroying the last visible window would post the app quit before the
        # re-show ran. Then restore the quit-on-last-window value captured at
        # enter. The rep teardown re-runs here (idempotent, never raises): a
        # raising step inside the try would skip the in-try call and leave a
        # stale mapped keep-below window painting the old mirror, plus a live
        # taskbar/Alt-Tab entry beside the restored framed app's own.
        # _finish_tuck re-runs here for the same reason (total + idempotent): a
        # raising step before the in-try call would otherwise leak a live ghost
        # layer child on the host as it returns to the framed tab.
        self._finish_tuck()
        self._teardown_taskbar_rep()
        self._release_and_restore(surface, token)
        self._safe_call(self._window, "showNormal")
        self._set_quit_on_last_window(self._quit_prev)
        # Destroy the now-empty surface.
        self._teardown_surface(surface)
        self._surface = None
        self._token = None
        self._clear_envelope_state()
        # The Hide-Cards toggle never outlives the float session (reset HERE, on
        # the unconditional path, so not even a raising teardown step can leak a
        # stale True into the next enter()'s _target_visible_cells seed).
        self._cards_hidden = False
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
        """Step the cluster scale by *notches* as ONE transform retarget. No-op
        if not active.

        The window geometry does NOT change (fixed max-scale envelope) and the
        host is NOT re-laid-out (no apply_metrics): a notch updates the
        authoritative target scale, retargets the zoom tween on the surface's
        whole-cluster transform (snap when the tween is killed/absent), and
        drives the input-shape phase machine (one BROAD full-window apply that
        keeps the wheel stream captured, then the EXACT shape on settle). This
        is what makes scaling judder-free: there is nothing for the compositor
        to mis-order and nothing that scales on a different curve.

        Unlike enter()/leave() this is NOT transactional: it is an idempotent
        retarget, so a mid-gesture failure self-corrects on the next notch.
        """
        if not self._active:
            return
        prev_scale = self.scale
        self.scale = step_scale(self.scale, notches)
        # Clamped at SCALE_MIN/MAX -> the scale did not actually change: skip the
        # whole broad phase (which would otherwise mark _scaling_active and lock
        # out drag for the ~250ms settle window on a NO-OP scroll) and the save.
        # Mirrors move_group's clamp-pinned no-op early-return.
        if self.scale == prev_scale:
            return
        # Retarget the rendered zoom toward the new authoritative scale.
        self._drive_view_scale(self.scale)
        # Radial open: keep the ring diameter in lockstep with the emblem (its
        # top-level stays at the FIXED max canvas; the click-region re-apply is
        # deferred to the radial settle timer). The internal dim needs nothing:
        # it is a child of the transformed host, so it zooms with the cluster.
        # Both calls run even while CLOSED so the empty persistent windows track
        # the state the next open will use (the closed panel resizes to the new
        # scale's emblem*6 here) - any compositor morph plays invisibly.
        self._reposition_radial()
        self._reposition_panel()
        # Drive the input-shape phase machine: broad now, exact on settle.
        self._enter_broad_phase(self._compute_window_rect())
        # Persist the new scale (debounced). A clamp-pinned no-op scroll already
        # returned above, so reaching here always means the scale actually changed.
        self._schedule_save()

    def _drive_view_scale(self, target: float) -> None:
        """Bring the RENDERED scale to *target*: retarget the zoom tween from the
        current visual value (so a scroll burst reads as one continuous zoom), or
        snap synchronously when animation is disabled or the surface has no
        transform seam (test stubs). Best-effort: a surface error must never
        propagate into the Qt wheel handler."""
        target = float(target)
        surface = self._surface
        setter = getattr(surface, "set_cluster_scale", None) \
            if surface is not None else None
        if setter is None:
            self._view_scale = target
            return
        if not _scale_anim_enabled():
            self._view_scale = target
            try:
                setter(target)
            except Exception:
                pass
            return
        from PySide6.QtCore import QVariantAnimation, QEasingCurve
        anim = self._scale_anim
        if anim is None:
            anim = QVariantAnimation()
            anim.setDuration(_SCALE_ANIM_MS)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(self._on_scale_anim_frame)
            self._scale_anim = anim
        anim.stop()
        anim.setStartValue(float(self._view_scale))
        anim.setEndValue(target)
        anim.start()

    def _on_scale_anim_frame(self, value) -> None:
        """One zoom-tween frame: push the interpolated scale to the surface's
        transform. Guarded against a frame landing after leave() (anim stopped
        there, but a queued frame must still be harmless)."""
        if not self._active:
            return
        self._view_scale = float(value)
        surface = self._surface
        setter = getattr(surface, "set_cluster_scale", None) \
            if surface is not None else None
        if setter is None:
            return
        try:
            setter(self._view_scale)
        except Exception:
            pass

    def _sync_view_scale_to_target(self) -> None:
        """Snap the rendered scale to the authoritative target and stop any
        running tween. Used at settle (paranoia: a lagging/killed animation must
        never leave the visual mid-ramp once hit-mapping resumes) and on leave."""
        if self._scale_anim is not None:
            self._scale_anim.stop()
        self._view_scale = self._scale
        surface = self._surface
        setter = getattr(surface, "set_cluster_scale", None) \
            if surface is not None else None
        if setter is None:
            return
        try:
            setter(self._view_scale)
        except Exception:
            pass

    def move_group(self, dx: int, dy: int) -> bool:
        """Shift the cluster anchor by (dx, dy), clamp to the screen envelope, and
        reposition the window. Returns True only if the window ACTUALLY moved.

        Drag is LOCKED OUT while a scale gesture is live (``_scaling_active``):
        returns False without moving so a wheel-zoom is never fought by a stray
        drag. Also a no-op (False) when not active.

        Anchor reconciliation: the anchor accumulates only the delta the clamp
        actually applied (not the raw requested point), so dragging into an
        envelope edge cannot build up a phantom offset that a reverse drag must
        first unwind (the dead-zone bug). The clamp operates on the VISIBLE
        content rect at the current scale, not the fixed envelope window (which
        overstates the content below SCALE_MAX). A clamp that pins the rect to
        its current position is reported as no move (returns False).
        """
        if not self._active:
            return False
        if self._scaling_active:
            return False
        from utils.overlay.cluster_geometry import (
            clamp_to_envelope, scaled_content_rect,
        )
        _size, _pivot, emblem_center, host_size = self._envelope_spec()
        ax, ay = self._anchor
        # Clamp the VISIBLE CONTENT rect, not the window: the window is the fixed
        # max-scale envelope, which overstates the content at any smaller scale -
        # clamping it would let every visible pixel slide off-screen. The content
        # rect at the CURRENT (already-reconciled) anchor == the on-screen
        # placement; the candidate is the shifted rect, clamped to the screens.
        current = scaled_content_rect(host_size, emblem_center, (ax, ay),
                                      self._scale)
        candidate = scaled_content_rect(host_size, emblem_center,
                                        (ax + dx, ay + dy), self._scale)
        clamped = clamp_to_envelope(
            candidate, self._screens_xywh(), self._move_margin())
        if clamped == current:
            return False  # clamp pinned -> no visual move (no anchor drift)
        # Reconcile the anchor by the delta the clamp actually applied (the clamp
        # only translates), so the anchor accumulates exactly the visual move and
        # a drag into an envelope edge cannot build a phantom offset that a
        # reverse drag must first unwind (the dead-zone bug).
        self._anchor = (ax + dx + (clamped.x() - candidate.x()),
                        ay + dy + (clamped.y() - candidate.y()))
        if self._surface is not None:
            # Pure MOVE of the fixed envelope (size never changes here): place the
            # pivot on the reconciled anchor; the radial top-level + panel
            # re-center separately below.
            try:
                self._surface.set_overlay_geometry(self._compute_window_rect())
            except Exception:
                pass
        # Both persistent top-levels track the anchor even while CLOSED (empty +
        # invisible): the compositor animates their geometry changes, so a stale
        # window caught up at open time would visibly morph in from the old spot.
        self._reposition_radial()
        self._reposition_panel()
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
        self._update_rep_blanking()
        self._input_phase = "broad"
        self._apply_input_shape(self._broad_input_path(rect))
        # The echo clip is settled-state geometry: it would lag the live view
        # transform every notch, poking echoes past shrinking cards. Hide the
        # layer for the gesture; _settle_input re-shows it under a fresh clip.
        if self._ghost_echo is not None:
            self._ghost_echo.setVisible(False)
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
        # The gesture is over: the rendered scale must equal the authoritative
        # target before hit-mapping consumers (peek/ghost/drag) resume.
        self._sync_view_scale_to_target()
        self._input_phase = "exact"
        self._apply_exact_input_shape()   # also refreshes the echo clip
        if self._ghost_echo is not None:
            self._ghost_echo.setVisible(True)
        self._update_rep_blanking()   # settled: unblank + re-align + re-grab

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
        # The settled painted content just (potentially) changed - keep the
        # glove-echo clip on the same cadence as the exact input shape.
        self._refresh_echo_clip()

    def _apply_input_shape(self, path) -> None:
        """Apply *path* as the single window's INPUT (click-through) shape via the
        backend. Best-effort: a shape failure must never break the scale gesture."""
        surface = self._surface
        if surface is None:
            return
        try:
            from utils.overlay.backend import overlay_trace
            try:
                br = path.boundingRect()
                wid = int(surface.winId())
                dpr = surface.devicePixelRatio()
            except Exception as _e:
                br, wid, dpr = f"<err {_e!r}>", None, None
            overlay_trace(
                f"cluster.apply_input_shape phase={self._input_phase} bbox={br} "
                f"dpr={dpr} winId={wid} visible={self._visible_cells} "
                f"empty_path={getattr(path, 'isEmpty', lambda: '?')()}")
        except Exception:
            pass
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
        """The emblem hit rect in window-local coords: the emblem widget's framed
        1.0 geometry mapped through the cluster transform (the host renders scaled
        about the pivot inside the fixed envelope). Null QRect when unavailable."""
        from PySide6.QtCore import QRect
        emblem = getattr(self._card_provider, "_emblem", None)
        if emblem is not None:
            g = emblem.geometry()
            if g.width() > 0 and g.height() > 0:
                return self._map_host_rect(QRect(g))
        return QRect()

    @staticmethod
    def _cell_origin(root, grid_host):
        """The cell root's origin within ``grid_host`` (window-local coords). Uses
        ``mapTo`` when the cell is a nested descendant, falling back to ``pos()`` when
        it is a direct child (or when there is no grid host). Shared by
        ``_window_control_rects`` (input-shape) and ``_visible_card_geoms``
        (peek/ghost) so the cell-origin computation never drifts between them."""
        from PySide6.QtCore import QPoint
        if grid_host is not None and root is not grid_host:
            return root.mapTo(grid_host, QPoint(0, 0))
        return root.pos()

    def _window_control_rects(self) -> dict:
        """``{slot_id: [QRect, ...]}`` of each card's interactive-control rects in
        WINDOW-LOCAL coords - the input-union's per-slot ``card_controls``.

        The provider's real ``control_rects(cell_index)`` returns CARD-LOCAL rects
        at the framed 1.0 layout (the host never re-layouts in the transform
        model). Each rect is translated by its cell's origin within the grid host
        (``cell.mapTo(grid_host)``) into HOST coords, then mapped through the
        cluster transform into window coords - the same math the proxy renders
        with, so the click region always sits on the pixels.

        Empty dict when the provider lacks ``control_rects``/``_card_slots`` (the
        exact union then collapses to the emblem only - documented placeholder
        behavior; occupancy + the per-control refinements land in a LATER task).
        """
        provider = self._card_provider
        rects_fn = getattr(provider, "control_rects", None)
        slots = getattr(provider, "_card_slots", None)
        if rects_fn is None or slots is None:
            return {}
        grid_host = getattr(provider, "_grid_host", None)
        out: dict = {}
        for cell_index, slot in enumerate(slots):
            root = slot.get("cell") if isinstance(slot, dict) else None
            if root is None:
                continue
            try:
                origin = self._cell_origin(root, grid_host)
                local_rects = rects_fn(cell_index)
                out[cell_index] = [
                    self._map_host_rect(r.translated(origin))
                    for r in local_rects
                ]
            except Exception:
                continue
        return out

    # ------------------------------------------------------------------
    # Hover-peek / ghost-click / drag (cluster-local hit tests)
    # ------------------------------------------------------------------
    @staticmethod
    def _point_xy(pt):
        """Accept a QPoint(F) or an (x, y) pair -> (x, y) ints."""
        x = getattr(pt, "x", None)
        if callable(x):
            return int(pt.x()), int(pt.y())
        return int(pt[0]), int(pt[1])

    def slot_at_window_point(self, pt):
        """The VISIBLE slot whose control rect(s) contain the WINDOW-LOCAL point
        *pt* (a QPoint or (x, y)), or None. Considers only ``self._visible_cells``,
        using the same window-local control rects the exact input shape is built from
        (``_window_control_rects``)."""
        from PySide6.QtCore import QPoint
        px, py = self._point_xy(pt)
        p = QPoint(px, py)
        for slot, rects in self._window_control_rects().items():
            if slot not in self._visible_cells:
                continue
            for r in rects:
                if r.contains(p):
                    return slot
        return None

    def card_control_point(self, slot):
        """A representative WINDOW-LOCAL QPoint INSIDE *slot*'s control region: the
        center of its first control rect. None when the slot has no control rects.
        The inverse of ``slot_at_window_point`` for a visible slot."""
        from PySide6.QtCore import QPoint
        rects = self._window_control_rects().get(slot)
        if not rects:
            return None
        r = rects[0]
        return QPoint(r.x() + r.width() // 2, r.y() + r.height() // 2)

    # Card-local corner the concave carve is centered on, keyed by the cell
    # cfg's "cutout" token (the same table _card_body_path paints from).
    _CUTOUT_CORNERS = {
        "tl": (0.0, 0.0), "tr": (1.0, 0.0),
        "bl": (0.0, 1.0), "br": (1.0, 1.0),
    }

    def _cutout_circle(self, slot, host_rect):
        """*slot*'s concave-corner carve as a SCREEN-space circle ``(cx, cy, r)``,
        or None when the provider carries no cutout spec/metrics (bare stubs).

        The painted card body fills its cell rect exactly
        (``_position_cell_bg``) and is carved by a circle of the metrics'
        ``cutout_r`` centered ON the cell's emblem-facing corner
        (``_card_body_path``) - the emblem nests inside that carve. Mapping the
        corner + radius through the cluster transform lets hit tests follow the
        PAINTED shape instead of the flat rect, so a cursor on the emblem (or in
        the transparent breathing ring around it) never reads as over the card.
        *host_rect* is the cell's framed 1.0 rect; the returned circle is in
        WINDOW coords (the caller translates to screen with the card rect)."""
        cfg = slot.get("cfg") if isinstance(slot, dict) else None
        corner_key = cfg.get("cutout") if isinstance(cfg, dict) else None
        frac = self._CUTOUT_CORNERS.get(corner_key)
        metrics = getattr(self._card_provider, "_metrics", None)
        radius = getattr(metrics, "cutout_r", None)
        if frac is None or not radius:
            return None
        fx, fy = frac
        corner = (host_rect.x() + host_rect.width() * fx,
                  host_rect.y() + host_rect.height() * fy)
        cx, cy = self._map_host_point(corner)
        return (cx, cy, float(radius) * self._scale)

    def _visible_card_geoms(self):
        """``[(slot, screen_rect QRect, [card-local control QRect, ...],
        cutout_circle), ...]`` for the VISIBLE cells.

        A card's SCREEN rect = the window placement origin (``_compute_window_rect``,
        derived from the anchor - matching the surface geometry and robust to a stub
        surface that never really moves) PLUS the cell's framed 1.0 rect within
        ``_grid_host`` mapped through the cluster transform (where the transform
        actually renders it). The control rects are the raw CARD-LOCAL 1.0 rects -
        exactly the ``control_hits`` contract, which divides by the scale passed to
        it. ``cutout_circle`` is the cell's concave carve as a SCREEN ``(cx, cy, r)``
        circle (``_cutout_circle``), or None without a cutout spec. Empty when the
        provider lacks the ``control_rects`` / ``_card_slots`` hooks."""
        provider = self._card_provider
        rects_fn = getattr(provider, "control_rects", None) if provider is not None else None
        slots = getattr(provider, "_card_slots", None) if provider is not None else None
        if rects_fn is None or slots is None:
            return []
        from PySide6.QtCore import QRect
        grid_host = getattr(provider, "_grid_host", None)
        win = self._compute_window_rect()
        ox, oy = win.x(), win.y()
        out = []
        for cell_index, slot in enumerate(slots):
            if cell_index not in self._visible_cells:
                continue
            root = slot.get("cell") if isinstance(slot, dict) else None
            if root is None:
                continue
            try:
                origin = self._cell_origin(root, grid_host)
                size = root.size()
                host_rect = QRect(origin.x(), origin.y(),
                                  size.width(), size.height())
                screen_rect = self._map_host_rect(host_rect).translated(ox, oy)
                cutout = self._cutout_circle(slot, host_rect)
                if cutout is not None:
                    cutout = (cutout[0] + ox, cutout[1] + oy, cutout[2])
                out.append((cell_index, screen_rect, rects_fn(cell_index), cutout))
            except Exception:
                continue
        return out

    # ---- Ghost events -------------------------------------------------
    def on_ghost_event(self, payload) -> None:
        """Receive a click-sync ghost_pointer_event (motion/press/release).

        Converts the native points to logical coords once (HiDPI-correct), feeds the
        hover-peek store, and - on a 'press', when ghost-control-clicks are enabled -
        fires the matching card controls. A no-op mid scale gesture (the frozen
        cluster must not take ghost clicks) OR while framed: a QUEUED event that
        arrives after leave() must NEVER re-seed the peek store, or a stale hover
        would survive into the next enter(). Caller wiring is a LATER task.

        This is a QUEUED Qt slot in production (fired from the input-service capture
        thread, marshalled to the GUI thread), so it MUST NEVER raise into Qt's
        dispatch. Malformed payload items are already dropped in
        ``_ghost_payload_to_logical``; the whole body is ALSO wrapped in a defensive
        try/except as a backstop for anything else (e.g. a
        ``QGuiApplication.screens()`` failure in the logical conversion)."""
        if self._scaling_active or not self._active:
            return
        try:
            payload = self._ghost_payload_to_logical(payload)
            self._peek_store.ingest(payload)
            if not self._ghost_click_enabled():
                return
            try:
                kind, items = payload
            except (TypeError, ValueError):
                return
            if kind == "press":
                self._ghost_click_pass(items)
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster_controller.on_ghost_event() suppressed "
                          "(never raise into Qt dispatch):\n" + traceback.format_exc())

    def on_ghost_clear(self) -> None:
        """Receive click-sync ghost_clear: drop all ghost points and settle any faded
        card back to fully opaque."""
        self._peek_store.clear()
        self._settle_peek()

    def _ghost_payload_to_logical(self, payload):
        """Convert a ghost payload's native points to logical coords (fetching the
        screen list once), DROPPING any malformed item (one that is not a
        ``(slot, x, y)`` triple) instead of passing it downstream where the unpack in
        ``_peek_store.ingest`` / ``_ghost_click_pass`` would raise into the queued Qt
        slot. A payload that is not a ``(kind, items)`` pair is returned UNCHANGED
        (the downstream ingest + press guards then no-op on it); the well-formed
        service payloads always convert."""
        from PySide6.QtGui import QGuiApplication
        try:
            kind, items = payload
        except (TypeError, ValueError):
            return payload
        screens = QGuiApplication.screens()
        conv = []
        for item in items:
            try:
                slot, x, y = item
            except (TypeError, ValueError):
                continue  # drop a malformed item; never propagate a bad unpack
            conv.append((slot, *emitted_to_logical(x, y, screens)))
        return (kind, conv)

    def _ghost_click_enabled(self) -> bool:
        """True when ghost cursors may press card controls: a settings object, an
        active overlay, a card provider, and both ghost settings on."""
        if self._settings is None or not self._active or self._card_provider is None:
            return False
        return bool(self._settings.get(GHOST_CURSORS_ENABLED, True)
                    and self._settings.get(GHOST_CURSORS_CONTROL_CARDS, True))

    def _ghost_click_pass(self, items) -> None:
        """Map each (already-logical, SCREEN) ghost point to a card control and
        deliver a synthetic click at its CELL-ROOT-LOCAL coordinate.

        The cards list feeds the shared ``control_hits`` helper: each visible
        slot's SCREEN rect (the transform-mapped cell rect at the window origin)
        plus its card-local FRAMED 1.0 control rects. ``control_hits`` divides the
        in-rect offset by the cluster scale, so the resolved (x, y) is the 1.0
        cell-root-local point ``deliver_ghost_click``'s ``childAt`` walk expects
        (the cells keep their 1.0 layout in the transform model - same contract as
        the legacy per-card path). Defensive per card: ``on_ghost_event`` is a
        QUEUED Qt slot, so one bad card drops only its own click, never the whole
        press."""
        provider = self._card_provider
        if provider is None:
            return
        cards = []
        # The cutout circle is irrelevant here: ghost clicks resolve against the
        # CONTROL rects, which never overlap the carved corner.
        for slot, screen_rect, local_rects, _cutout in self._visible_card_geoms():
            rect_tuples = [(r.x(), r.y(), r.width(), r.height()) for r in local_rects]
            cards.append((slot,
                          (screen_rect.x(), screen_rect.y(),
                           screen_rect.width(), screen_rect.height()),
                          rect_tuples))
        points = [(x, y) for _slot, x, y in items]
        for slot, x, y in control_hits(points, cards, self._scale):
            try:
                provider.deliver_ghost_click(slot, x, y)
            except Exception:
                continue
        # Emblem parity: a ghost press on the emblem DISC acts like a real
        # left-click on the emblem (menu_requested -> main's radial toggle).
        # Controls and the emblem never overlap, so the two hit passes are
        # disjoint; one batch fires the toggle at most once. Best-effort like
        # everything on this queued path.
        emblem = self._emblem
        if emblem is None:
            return
        try:
            er = self._emblem_rect()
            if er.isNull():
                return
            win = self._compute_window_rect()
            cx = win.x() + er.x() + er.width() / 2.0
            cy = win.y() + er.y() + er.height() / 2.0
            radius = min(er.width(), er.height()) / 2.0
            for _slot, x, y in items:
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius:
                    emblem.menu_requested.emit()
                    break
        except Exception:
            pass

    # ---- Glove echo (ghost cursors over the cards) ---------------------
    # The confined ghost overlays stack directly above their game window and
    # below everything else - including this DOCK-layer cluster, whose cards
    # deliberately float over the games. "Above the cards but below other
    # windows" is a stacking cycle (the dock layer beats every regular
    # window), so the cluster paints the glove itself: GhostCursorController
    # mirrors each glove change into these sink methods, and a paint-only
    # GhostEchoLayer child draws the sprites clipped to the visible painted
    # content. Everything here is best-effort - a cosmetic echo failure must
    # never raise into the ghost pipeline (mirrors on_ghost_event).

    def ghost_echo_shown(self, slot, x, y, pixmap) -> None:
        """A glove sprite was shown/moved: mirror it onto the echo layer.
        ``(x, y)`` is the sprite TOP-LEFT in logical SCREEN coords (hotspot
        already applied by the caller)."""
        if not self._active or self._surface is None:
            return
        try:
            echo = self._ensure_ghost_echo()
            if echo is None:
                return
            from PySide6.QtCore import QPoint
            win = self._compute_window_rect()
            echo.show_slot(slot, QPoint(int(x) - win.x(), int(y) - win.y()),
                           pixmap)
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster.ghost_echo_shown suppressed:\n"
                          + traceback.format_exc())

    def ghost_echo_fading(self, slot, duration_ms) -> None:
        """The glove's idle fade started: fade the echo in step (the caller
        passes its own fade duration, so the two can never drift)."""
        if self._ghost_echo is None:
            return
        try:
            self._ghost_echo.fade_slot(slot, duration_ms)
        except Exception:
            pass

    def ghost_echo_hidden(self, slot) -> None:
        """A glove was hidden immediately (focus suppression): drop its echo."""
        if self._ghost_echo is None:
            return
        try:
            self._ghost_echo.hide_slot(slot)
        except Exception:
            pass

    def ghost_echo_cleared(self) -> None:
        """All gloves hidden (ghost_clear / setting off): drop every echo."""
        if self._ghost_echo is None:
            return
        try:
            self._ghost_echo.clear()
        except Exception:
            pass

    def _ensure_ghost_echo(self):
        """The per-session echo layer, created on first use as a full-envelope
        child of the surface, raised above the hosted cluster view. None when
        framed/surfaceless. The surface never resizes while active (fixed
        envelope), so the geometry is set once."""
        if self._ghost_echo is not None:
            return self._ghost_echo
        surface = self._surface
        if not self._active or surface is None:
            return None
        from utils.overlay.ghost_echo import GhostEchoLayer
        echo = GhostEchoLayer(surface)
        echo.setGeometry(surface.rect())
        echo.raise_()
        echo.show()
        self._ghost_echo = echo
        self._refresh_echo_clip()
        from utils.overlay.backend import overlay_trace
        overlay_trace(f"cluster.ghost_echo created: geom={echo.geometry()}")
        return echo

    def _refresh_echo_clip(self) -> None:
        """Rebuild the echo layer's content clip from the CURRENT visible set,
        scale, and provider geometry. Piggybacks on _apply_exact_input_shape
        (enter / settle / occupancy / hide-cards / screen change), so the clip
        refreshes exactly when the settled painted content changes. Guarded:
        a geometry failure clears the clip (fail closed - the layer then
        draws nothing) rather than raising."""
        echo = self._ghost_echo
        if echo is None:
            return
        try:
            echo.set_clip(self._echo_content_path())
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster._refresh_echo_clip failed (echo cleared):\n"
                          + traceback.format_exc())
            try:
                echo.set_clip(None)
            except Exception:
                pass

    def _echo_content_path(self):
        """The cluster's visible painted content as a WINDOW-LOCAL
        QPainterPath: each VISIBLE cell's card-body path (rounded rect minus
        the concave carve - the exact shape the card paints, from
        ``_card_body_path``) translated to host coords and mapped through the
        cluster transform, plus the emblem DISC (the emblem widget rect inset
        by its transparent ring margin). This is deliberately the PAINTED
        union, not the input union: the echo must cover card bodies, not just
        their interactive controls."""
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainterPath, QTransform
        path = QPainterPath()
        provider = self._card_provider
        if provider is None:
            return path
        _size, pivot, emblem_center, _hs = self._envelope_spec()
        s = float(self._scale)
        # window = pivot + (host - emblem_center) * scale; QTransform composes
        # last-called-first, so this maps host-local points exactly like
        # map_host_rect_to_window / the surface's proxy transform.
        t = (QTransform()
             .translate(float(pivot[0]), float(pivot[1]))
             .scale(s, s)
             .translate(-float(emblem_center[0]), -float(emblem_center[1])))
        # Emblem disc: the widget rect includes the transparent ring/glow
        # room around the disc (_Emblem._RING_MARGIN); inset it back out so
        # the echo never paints over the see-through breathing ring.
        emblem = getattr(provider, "_emblem", None)
        if emblem is not None:
            g = emblem.geometry()
            if g.width() > 0 and g.height() > 0:
                try:
                    margin = int(getattr(emblem, "_ring_margin", 0) or 0)
                except Exception:
                    margin = 0
                disc = g.adjusted(margin, margin, -margin, -margin)
                if disc.width() > 0 and disc.height() > 0:
                    dp = QPainterPath()
                    dp.addEllipse(QRectF(disc))
                    path.addPath(t.map(dp))
        # Visible cards' painted bodies (host 1.0 layout; the transform does
        # the scaling - same contract as every other hit/shape consumer).
        slots = getattr(provider, "_card_slots", None)
        if slots is None:
            return path
        metrics = getattr(provider, "_metrics", None)
        grid_host = getattr(provider, "_grid_host", None)
        for cell_index, slot in enumerate(slots):
            if cell_index not in self._visible_cells:
                continue
            root = slot.get("cell") if isinstance(slot, dict) else None
            if root is None:
                continue
            try:
                origin = self._cell_origin(root, grid_host)
                size = root.size()
                if size.width() <= 0 or size.height() <= 0:
                    continue
                cfg = slot.get("cfg") if isinstance(slot, dict) else None
                cutout = cfg.get("cutout") if isinstance(cfg, dict) else None
                body = self._card_body_path_local(
                    size.width(), size.height(), cutout, metrics)
                body.translate(origin.x(), origin.y())
                path.addPath(t.map(body))
            except Exception:
                continue
        return path

    @staticmethod
    def _card_body_path_local(w, h, cutout, metrics):
        """One card's painted body outline at host-local 1.0 (card-local
        coords): the shared ``_card_body_path`` when the cell carries a valid
        carve-corner token, a plain rounded rect otherwise (a bare stub still
        gets a sane echo clip)."""
        from PySide6.QtGui import QPainterPath
        from tabs.multitoon._compact_layout import _card_body_path
        radius = getattr(metrics, "card_radius", None)
        cutout_r = getattr(metrics, "cutout_r", None)
        if cutout in ("tl", "tr", "bl", "br"):
            if radius and cutout_r:
                return _card_body_path(w, h, cutout, radius, cutout_r)
            return _card_body_path(w, h, cutout)
        body = QPainterPath()
        body.addRoundedRect(0.0, 0.0, float(w), float(h),
                            float(radius or 0.0), float(radius or 0.0))
        return body

    # ---- Hover-peek (SAFE paint-time opacity only) --------------------
    PEEK_BODY_OPACITY = 0.65       # card BACKGROUND fill at full hover-peek
    PEEK_PORTRAIT_OPACITY = 0.25   # circular portrait (frame + toon image) at full peek
    _PEEK_FADE_STEP = 0.25         # progress per 30ms tick -> ~120ms full fade

    def _peek_opacities(self, progress):
        """``(bg, portrait)`` net opacities for a peek *progress* 0..1.

        Unlike the per-surface controller there is NO whole-card content tier in the
        single window (``windowOpacity`` is banned; a ``QGraphicsEffect`` on a custom
        ``paintEvent`` widget is banned), so the background fill + portrait fade
        DIRECTLY to their net targets via the provider's SAFE
        ``set_shell_extra_opacity`` (each widget's own paint-time ``setOpacity``)."""
        bg = 1.0 - (1.0 - self.PEEK_BODY_OPACITY) * progress
        portrait = 1.0 - (1.0 - self.PEEK_PORTRAIT_OPACITY) * progress
        return bg, portrait

    def _apply_peek_fade(self, slot, active) -> None:
        """Step one card's hover-peek progress toward its target and push the SAFE
        paint-time translucency (background fill + portrait) via the provider. A
        settled card (already at its target) is skipped so idle cards never repaint."""
        target = 1.0 if active else 0.0
        cur = self._peek_progress[slot]
        if cur < target:
            cur = min(target, cur + self._PEEK_FADE_STEP)
        elif cur > target:
            cur = max(target, cur - self._PEEK_FADE_STEP)
        else:
            return  # already settled; nothing to repaint
        self._peek_progress[slot] = cur
        bg, portrait = self._peek_opacities(cur)
        provider = self._card_provider
        if provider is not None:
            try:
                provider.set_shell_extra_opacity(slot, bg, portrait)
            except Exception:
                pass

    def _peek_tick(self, real_point) -> None:
        """One hover-peek detection pass: union the real cursor with the ghost points
        and fade each VISIBLE card toward peeked (hovered) or opaque (not). The hit
        test follows the card's PAINTED shape (rect minus the concave corner carve),
        so a cursor on the emblem never peeks the cards it nests between.

        real_point: (x, y) SCREEN global, or None when the OS pointer is unavailable.
        A no-op mid scale gesture (frozen cluster) or while framed."""
        if self._scaling_active:
            return
        if not self._active:
            return
        cards = self._visible_card_geoms()
        rects = [(g.x(), g.y(), g.width(), g.height()) for _slot, g, _cr, _cut in cards]
        cutouts = [cut for _slot, _g, _cr, cut in cards]
        points = list(self._peek_store.points())
        if real_point is not None:
            points.append(real_point)
        peeking = peeking_indices(points, rects, cutouts)
        peek_now = bool(peeking)   # `peeking` = this tick's peeked-indices set
        if peek_now != self._rep_peek_active:
            self._rep_peek_active = peek_now
            self._update_rep_blanking()
        for i, (slot, _g, _cr, _cut) in enumerate(cards):
            self._apply_peek_fade(slot, i in peeking)

    def _settle_peek_slot(self, slot) -> None:
        """Restore ONE card to fully opaque (both tiers) and reset its progress, if it
        is currently faded. A settled card (progress already 0.0) is a no-op so idle
        cards never repaint. Guarded: a provider without ``set_shell_extra_opacity``
        (a bare stub) is a safe no-op. Shared by ``_settle_peek`` and the occupancy
        reconcile (a card that drops out of the visible set)."""
        if not (0 <= slot < len(self._peek_progress)):
            return
        if self._peek_progress[slot] == 0.0:
            return
        self._peek_progress[slot] = 0.0
        provider = self._card_provider
        if provider is not None:
            try:
                provider.set_shell_extra_opacity(slot, 1.0, 1.0)
            except Exception:
                pass

    def _settle_peek(self) -> None:
        """Restore every faded card to fully opaque (both tiers) and reset progress,
        so a borrowed card never returns to the framed grid stuck dim. Used by
        ``on_ghost_clear`` + ``_stop_peek_timer`` (leave)."""
        for slot in range(len(self._peek_progress)):
            self._settle_peek_slot(slot)

    def _on_peek_timer(self) -> None:
        from PySide6.QtGui import QCursor
        try:
            p = QCursor.pos()
            point = (p.x(), p.y())
        except Exception:
            point = None
        self._peek_tick(point)

    def _start_peek_timer(self) -> None:
        from PySide6.QtCore import QTimer
        if self._peek_timer is None:
            self._peek_timer = QTimer()
            self._peek_timer.setInterval(30)  # ~33Hz, light
            self._peek_timer.timeout.connect(self._on_peek_timer)
        self._peek_timer.start()

    def _stop_peek_timer(self) -> None:
        """Stop the poll, drop the ghost points, and settle every card opaque."""
        if self._peek_timer is not None:
            self._peek_timer.stop()
        self._peek_store.clear()
        self._settle_peek()

    # ---- Emblem drag (cluster-local, one window) ----------------------
    def connect_emblem(self, emblem) -> None:
        """Wire an _Emblem's gesture signals to this controller. The connections
        are live in BOTH modes; the controller methods are mode-aware (toggle
        flips; move/scale no-op when framed):

          * toggle_requested (click)        -> toggle()  (enter/leave)
          * move_requested (drag start)     -> begin_group_drag()
          * resize_scrolled (dwell wheel)   -> set_scale_by_notches(notches)

        Idempotent and re-bindable: re-connecting the SAME emblem is a no-op (Qt
        permits duplicate connections, which would double-fire), and connecting a
        NEW emblem first drops the previous emblem's connections. A straight port
        of ``OverlayGroupController.connect_emblem`` so the two controllers stay
        drop-in interchangeable behind the same call site.
        """
        if emblem is self._emblem:
            return
        if self._emblem is not None:
            for sig, slot in (
                (self._emblem.toggle_requested, self.toggle),
                (self._emblem.move_requested, self.begin_group_drag),
                (self._emblem.resize_scrolled, self.set_scale_by_notches),
            ):
                try:
                    sig.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
        self._emblem = emblem
        emblem.toggle_requested.connect(self.toggle)
        emblem.move_requested.connect(self.begin_group_drag)
        emblem.resize_scrolled.connect(self.set_scale_by_notches)

    def begin_group_drag(self) -> None:
        """Start a manual drag of the whole cluster, following the cursor.

        move_requested fires ONCE at drag-start with no delta, so the controller
        tracks the GLOBAL cursor itself (a ~16ms poll) and shifts the anchor via the
        clamped ``move_group`` until the left button is released. No-op when framed;
        re-entrant-safe (restarts from the current cursor).

        An OPEN radial ring auto-dismisses at drag start: the drag reaches the
        emblem through the ring's emblem-disc input hole (see
        ``_radial_click_path``), and the user asked the emblem to move, not the
        menu. The dismiss is the ANIMATED one (spokes fly back into the emblem)
        - the ring window keeps following the anchor during the fly-back via
        move_group's ``_reposition_radial``, so the icons retract into the
        moving emblem instead of fading out with a hard teardown."""
        if not self._active:
            return
        if self.is_radial_open:
            self.dismiss_radial_menu()
        from PySide6.QtGui import QCursor
        from PySide6.QtCore import QTimer
        self._drag_last = QCursor.pos()
        if self._drag_timer is None:
            self._drag_timer = QTimer()
            self._drag_timer.setInterval(16)
            self._drag_timer.timeout.connect(self._drag_step)
        self._drag_timer.start()
        self._update_rep_blanking()

    def _drag_step(self) -> None:
        """One poll of the manual drag: move the group by the cursor delta, or end the
        drag when the left button is released / the cluster left transparent.

        The move is the clamped ``move_group``, which is a NO-OP while a scale gesture
        is live (the Task-5 drag-lockout-during-scale), so the drag inherits that
        lockout for free."""
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
        if not self._active:
            self._end_drag()
            return
        if not (QApplication.mouseButtons() & Qt.LeftButton):
            self._end_drag()
            return
        pos = QCursor.pos()
        if self._drag_last is not None:
            dx = pos.x() - self._drag_last.x()
            dy = pos.y() - self._drag_last.y()
            if dx or dy:
                self.move_group(dx, dy)
        self._drag_last = pos

    def _end_drag(self) -> None:
        """Stop the manual-drag poll (idempotent)."""
        if self._drag_timer is not None:
            self._drag_timer.stop()
        self._drag_last = None
        # The drag is over: unblank + re-anchor + re-grab the representative.
        self._update_rep_blanking()

    # ------------------------------------------------------------------
    # Occupancy (keep the grid shell fixed; only narrow the input shape)
    # ------------------------------------------------------------------
    @property
    def cards_hidden(self) -> bool:
        """True while the user's Hide-Cards toggle is holding every card hidden."""
        return self._cards_hidden

    def set_cards_hidden(self, hidden, animate: bool = False) -> None:
        """Hide (True) or show (False) ALL cards, occupied or not - the radial's
        Hide-Cards toggle. The cards are never torn down or reparented: the flip
        rides the exact live occupancy-reconcile path (cells ``setVisible`` with
        retained size - no grid reflow, no window resize, one repaint - the exact
        input shape re-applied so hidden cards click through to the games, and
        the taskbar representative re-aligned to the new composition), so hiding
        and unhiding are instant. The emblem always stays. Idempotent; ignored
        while framed (the toggle is float-session state - ``leave()`` resets it,
        so a session can never START with invisible cards).

        ``animate=True`` (the UI path) additionally plays the tuck: card
        SNAPSHOTS shrink into / grow out of the emblem on a transient ghost
        layer while the real cells use the instant path above. HIDE flips the
        authoritative state FIRST (input shape and taskbar mirror are correct
        from the first frame; the ghosts are pure decoration), SHOW defers the
        flip to the ghosts' landing (the live cells swap in pixel-identical
        under the ghosts' final frame). Honors the radial animation gate
        (kill switch + reduce motion) by snapping to the instant path."""
        if not self._active:
            return
        # Complete any in-flight tuck first so toggles can never interleave
        # (a pending deferred show-flip is applied here, making the state
        # comparison below authoritative).
        self._finish_tuck()
        hidden = bool(hidden)
        if hidden == self._cards_hidden:
            return
        if animate:
            try:
                from utils.overlay.radial_menu import radial_anim_enabled
                animate = radial_anim_enabled()
            except Exception:
                animate = False
        if not animate:
            self._cards_hidden = hidden
            self._reconcile_occupancy()
            return
        if hidden:
            # Snapshot BEFORE the flip (the cells are still visible), settle any
            # hover-peek fade first so the ghosts are grabbed fully opaque.
            for slot in self._visible_cells:
                self._settle_peek_slot(slot)
            specs = self._grab_tuck_specs(self._visible_cells)
            self._cards_hidden = True
            self._reconcile_occupancy()
            self._begin_tuck(specs, hiding=True)
        else:
            # Ghosts fly OUT of the emblem over the still-hidden cells (grab()
            # renders hidden widgets - retained size keeps their geometry), and
            # the authoritative flip lands with them in _finish_tuck.
            specs = self._grab_tuck_specs(self._occupancy_cells())
            if not specs:
                self._cards_hidden = False
                self._reconcile_occupancy()
                return
            self._tuck_show_pending = True
            self._begin_tuck(specs, hiding=False)

    def toggle_cards_hidden(self, animate: bool = False) -> bool:
        """Flip the Hide-Cards toggle; returns the new hidden state. NOTE: with
        ``animate=True`` a show's authoritative flip is deferred to the ghosts'
        landing, so the returned state is the INTENT (False) only after the
        animation completes; callers needing the settled state read
        ``cards_hidden`` later."""
        target = not (self._cards_hidden or self._tuck_show_pending)
        self.set_cards_hidden(target, animate=animate)
        return target if self._active else self._cards_hidden

    def _grab_tuck_specs(self, cells) -> list:
        """Snapshot each of ``cells`` as a tuck-ghost spec: the cell widget's
        grabbed pixmap at its resting host-coords rect, plus its accent-halo
        pixmap (via the provider's glow-cache seam) at the halo's blit rect.
        ``QWidget.grab()`` renders hidden widgets too (retained size keeps
        their geometry live), which is what lets the SHOW path snapshot cards
        that are still hidden. Best-effort per cell; never raises."""
        from PySide6.QtCore import QRectF
        provider = self._card_provider
        slots = getattr(provider, "_card_slots", None) if provider is not None else None
        if not slots:
            return []
        halo_fn = getattr(provider, "glow_pixmap_for_cell", None)
        specs = []
        for i in sorted(cells):
            if not (0 <= i < len(slots)):
                continue
            root = slots[i].get("cell") if isinstance(slots[i], dict) else None
            if root is None:
                continue
            try:
                pm = root.grab()
                if pm.isNull():
                    continue
                geo = root.geometry()   # cells live in the grid host
                halo_pm = halo_rect = None
                if halo_fn is not None:
                    entry = halo_fn(i)
                    if entry is not None:
                        halo_pm, pad = entry
                        # Reproduce _GlowLayer's blit exactly: top-left at
                        # (x - pad, y - pad), NATIVE pixmap size (the rounded
                        # halo canvas), so progress 0 matches the live halo.
                        halo_rect = QRectF(geo.x() - pad, geo.y() - pad,
                                           halo_pm.width(), halo_pm.height())
                specs.append({"pm": pm, "rect": QRectF(geo),
                              "halo_pm": halo_pm, "halo_rect": halo_rect})
            except Exception:
                continue
        return specs

    def _begin_tuck(self, specs, hiding: bool) -> None:
        """Build the ghost layer and start the tuck driver. HIDE runs 0 -> 1
        (ease-in, in step with the ring's fly-back), SHOW 1 -> 0 (ease-out,
        the ring's fly-out). Transaction-safe: any failure finalizes through
        ``_finish_tuck`` (which also applies a pending show-flip), so the
        authoritative state can never be stranded on the animation."""
        if not specs:
            self._finish_tuck()
            return
        provider = self._card_provider
        grid_host = getattr(provider, "_grid_host", None) if provider is not None else None
        if grid_host is None:
            self._finish_tuck()
            return
        try:
            from PySide6.QtCore import QPointF, QVariantAnimation, QEasingCurve
            from utils.overlay.tuck_animation import (
                TuckGhostLayer, TUCK_HIDE_MS, TUCK_SHOW_MS)
            _size, _pivot, (ecx, ecy), (hw, hh) = self._envelope_spec()
            layer = TuckGhostLayer(grid_host, QPointF(ecx, ecy))
            layer.setGeometry(0, 0, int(hw), int(hh))
            layer.set_specs(specs)
            layer.set_progress(0.0 if hiding else 1.0)
            self._tuck_layer = layer
            layer.show()
            self._restack_internal_layers()   # cards < ghosts < dim < emblem
            anim = QVariantAnimation(layer)
            anim.setStartValue(0.0 if hiding else 1.0)
            anim.setEndValue(1.0 if hiding else 0.0)
            anim.setDuration(TUCK_HIDE_MS if hiding else TUCK_SHOW_MS)
            anim.setEasingCurve(QEasingCurve.InCubic if hiding
                                else QEasingCurve.OutCubic)
            anim.valueChanged.connect(
                lambda v, lyr=layer: lyr.set_progress(float(v)))
            anim.finished.connect(self._finish_tuck)
            self._tuck_anim = anim
            anim.start()
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster._begin_tuck FAILED (snapping to final "
                          "state):\n" + traceback.format_exc())
            self._finish_tuck()

    def _finish_tuck(self) -> None:
        """Complete the tuck NOW: stop the driver, apply a deferred show-flip
        (the ghosts' landing = the real cells appear), destroy the ghost
        layer. THE single finalizer - the animation's natural end, a second
        toggle, ``leave()``, and any begin failure all funnel here. Idempotent
        and total (every step guarded); a no-op when nothing is in flight."""
        anim, self._tuck_anim = self._tuck_anim, None
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass
        if self._tuck_show_pending:
            self._tuck_show_pending = False
            self._cards_hidden = False
            if self._active:
                self._reconcile_occupancy()
        layer, self._tuck_layer = self._tuck_layer, None
        if layer is not None:
            try:
                layer.hide()
                layer.setParent(None)
                layer.deleteLater()
            except Exception:
                pass

    def _occupancy_cells(self) -> set:
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

    def _target_visible_cells(self) -> set:
        """``_occupancy_cells()``, except the user Hide-Cards toggle OVERRIDES
        occupancy: while it is on, the target set is EMPTY (occupancy churn
        while hidden lands here and stays hidden; the toggle-off reconcile
        re-reads the then-current occupancy)."""
        if self._cards_hidden:
            return set()
        return self._occupancy_cells()

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

    def _apply_cell_visibility(self) -> None:
        """Show occupied cells, hide empty ones VISUALLY (0 toons -> 0 cards).

        Each cell's size policy gets ``retainSizeWhenHidden`` BEFORE the hide so
        the 2x2 grid keeps the hidden quadrant's space - the pinwheel shape and
        the emblem-center invariant never reflow (the legacy overlay achieved the
        same by hiding empty card SURFACES; the single window hides the cell
        widgets inside the transformed host instead). The original retain flag is
        recorded once per cell and restored by ``_restore_cell_visibility`` on
        leave. Best-effort per cell: a provider without ``_card_slots`` (a bare
        stub) is a safe no-op."""
        provider = self._card_provider
        slots = getattr(provider, "_card_slots", None) if provider is not None else None
        if not slots:
            return
        for cell_index, slot in enumerate(slots):
            root = slot.get("cell") if isinstance(slot, dict) else None
            if root is None:
                continue
            try:
                sp = root.sizePolicy()
                if cell_index not in self._cell_retain_flags:
                    self._cell_retain_flags[cell_index] = sp.retainSizeWhenHidden()
                if not sp.retainSizeWhenHidden():
                    sp.setRetainSizeWhenHidden(True)
                    root.setSizePolicy(sp)
                root.setVisible(cell_index in self._visible_cells)
            except Exception:
                continue
        self._refresh_provider_glow()

    def _refresh_provider_glow(self) -> None:
        """Rebuild the provider's painted accent-glow specs after a cell
        visibility flip. The ``_GlowLayer`` is a SIBLING widget behind the
        cells keyed on each cell's LIT state, so hiding a shell does not
        remove its halo by itself - without this re-derive (whose spec build
        skips hidden shells) a lit card's accent glow would keep painting
        over bare desktop after Hide-Cards. Guarded: a provider without the
        hook (a bare stub) is a safe no-op."""
        refresh = getattr(self._card_provider, "_refresh_glow", None)
        if refresh is None:
            return
        try:
            refresh()
        except Exception:
            pass

    def _restore_cell_visibility(self) -> None:
        """leave(): every shell visible again (framed mode always shows all four)
        with its original retain-size flag. Idempotent; safe with nothing hidden."""
        provider = self._card_provider
        slots = getattr(provider, "_card_slots", None) if provider is not None else None
        flags, self._cell_retain_flags = self._cell_retain_flags, {}
        if not slots:
            return
        for cell_index, slot in enumerate(slots):
            root = slot.get("cell") if isinstance(slot, dict) else None
            if root is None:
                continue
            try:
                root.setVisible(True)
                if cell_index in flags and not flags[cell_index]:
                    sp = root.sizePolicy()
                    sp.setRetainSizeWhenHidden(False)
                    root.setSizePolicy(sp)
            except Exception:
                continue
        self._refresh_provider_glow()

    def _reconcile_occupancy(self) -> None:
        """Occupancy nudge (the signal slot; also driven by the Hide-Cards
        toggle): re-read ``occupied_cells()``, update
        ``self._visible_cells``, hide/show the cells to match, and RE-APPLY the
        exact input shape so empty cards drop out of the click region. No-op when
        framed (a stray post-leave signal is safe).

        The grid GEOMETRY is untouched: hidden cells retain their space
        (``retainSizeWhenHidden``) so the pinwheel never collapses, and the window
        is NOT resized or reshaped (the fixed envelope). The VISUAL hide/show runs
        regardless of gesture state (paint-safe); only the INPUT-shape swap is
        deferred during a scale.

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
        prev_visible = self._visible_cells
        self._visible_cells = self._target_visible_cells()
        # Settle any card that just LEFT the visible set back to fully opaque. The
        # hover-peek poll (_peek_tick) only iterates VISIBLE cards, so a card that was
        # mid-peek when it dropped out of occupancy would otherwise stay extra-dimmed
        # until on_ghost_clear/leave. Runs regardless of gesture state - the opacity
        # is paint-time safe; only the INPUT-shape swap is deferred during a scale.
        for slot in prev_visible - self._visible_cells:
            self._settle_peek_slot(slot)
        self._apply_cell_visibility()
        # Keep the representative aligned with the new composition: the bbox
        # ORIGIN can move when the visible set changes (not just its size), so
        # a bare mirror refresh would leave every pixel offset - a persistent
        # visible ghost over bare desktop. _update_rep_blanking re-aligns THEN
        # re-grabs when settled; while blanked (mid-gesture) it defers, and the
        # settle terminal replays it with this fresh visible set.
        self._update_rep_blanking()
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
    # Multi-monitor / HiDPI screen-change reshape
    # ------------------------------------------------------------------
    def _connect_screen_change(self) -> None:
        """Connect the cluster window's ``screenChanged`` to ``_on_screen_changed`` so
        the input shape is re-applied at the new device-pixel ratio when the window
        crosses to another monitor.

        Called from ``enter()`` AFTER ``surface.show()`` because ``windowHandle()`` may
        be None until the window is shown (a None handle is a safe no-op). Idempotent:
        the guard flag stops a re-enter (or a double call) from double-connecting the
        slot, so a single screenChanged fires the reshape exactly once. Fully guarded -
        a wiring failure must never tank a successful ``enter()``."""
        if self._screen_change_connected:
            return
        surface = self._surface
        if surface is None:
            return
        get_handle = getattr(surface, "windowHandle", None)
        if get_handle is None:
            return
        try:
            wh = get_handle()
            if wh is None:
                return
            wh.screenChanged.connect(self._on_screen_changed)
            self._screen_change_handle = wh
            self._screen_change_connected = True
        except Exception:
            pass

    def _disconnect_screen_change(self) -> None:
        """Disconnect the ``screenChanged`` handler (``leave()`` / teardown) so a late
        signal after the surface is gone can never re-apply a shape. Idempotent +
        guarded: a no-op when never connected, and safe if the handle is already gone
        or the disconnect raises."""
        if not self._screen_change_connected:
            return
        self._screen_change_connected = False
        wh = self._screen_change_handle
        self._screen_change_handle = None
        if wh is None:
            return
        try:
            wh.screenChanged.disconnect(self._on_screen_changed)
        except Exception:
            pass

    def _on_screen_changed(self, *_args) -> None:
        """The window moved to another monitor: its device-pixel ratio may have
        changed, so RE-APPLY the input shape(s) at the surface's CURRENT (fresh) DPR.

        The input path is LOGICAL surface-local; the backend converts it to DEVICE
        pixels via ``surface.devicePixelRatio()`` at apply time, so the SAME logical
        path yields a different device region on a different-DPR monitor - hence the
        re-apply. No-op when framed (a stray post-leave emit is safe).

        A screen change is a DISCRETE event (not a scroll burst), so the exact shape is
        re-applied IMMEDIATELY - it does NOT need the wheel-stall settle deferral. The
        one exception: if a scale gesture is genuinely mid-flight (``_scaling_active``)
        the broad-phase discipline is respected - the (re-armed) settle timer replays
        the exact shape on quiesce rather than narrowing the wheel-capture region under
        the pointer. A screenChanged handler must never raise into Qt dispatch, so the
        whole body is guarded (traced, never propagated)."""
        if not self._active:
            return
        try:
            # Cluster exact shape: immediate on a plain monitor move; deferred to the
            # settle timer if a scale gesture is genuinely live.
            scaling = self._scaling_active
            if scaling:
                self._arm_settle_timer()
            else:
                self._apply_exact_input_shape()
            # Radial: ALWAYS re-center/re-size on the fresh emblem (cheap; runs
            # even while CLOSED so the empty persistent window never goes stale -
            # a stale window caught up at open would visibly morph in; and
            # _reposition_radial schedules its OWN deferred reshape when the
            # canvas changed). The IMMEDIATE full-canvas click-region re-apply is
            # GATED on open + not-scaling, mirroring the cluster's broad-phase
            # deferral above - forcing it mid-scale would narrow the X11 input
            # region under the pointer and undo the settle-timer deferral.
            self._reposition_radial()
            if self.is_radial_open and not scaling:
                self._reapply_radial_shape()
            # Panel: re-center ALWAYS (open or empty); the immediate full-rect
            # click-region re-apply is likewise gated (same broad-phase deferral).
            self._reposition_panel()
            if self.is_panel_open and not scaling:
                self._reapply_panel_shape()
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster_controller._on_screen_changed() suppressed "
                          "(never raise into Qt dispatch):\n" + traceback.format_exc())

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
        """Center the internal dim on the emblem in FRAMED 1.0 ``_grid_host``-local
        coords at the 1.0 ``emblem*4`` canvas. Scale-independent by design: the dim
        is a child of the transformed host, so the cluster zoom scales it in
        lockstep with the emblem - positioning it at the current scale would
        double-scale it."""
        dim = self._dim
        if dim is None:
            return
        from PySide6.QtCore import QRect
        from utils.overlay.card_metrics import CardMetrics
        _size, _pivot, (ecx, ecy), _host_size = self._envelope_spec()
        canvas = int(CardMetrics(1.0).emblem) * 4
        dim.setGeometry(QRect(ecx - canvas // 2, ecy - canvas // 2, canvas, canvas))

    def _restack_internal_layers(self) -> None:
        """Re-assert the cards < tuck-ghosts < dim < emblem z-order inside
        ``_grid_host``: raise the tuck ghost layer above the cards (the ghosts
        must slide UNDER the emblem disc), then the dim, then the emblem. The
        glow stays at the bottom (never raised). Each step is a guarded no-op
        when that widget is absent."""
        tuck = self._tuck_layer
        if tuck is not None:
            self._safe_call(tuck, "raise_")
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

    def _collapse_internal_dim(self) -> None:
        """Play the internal dim's reverse (fly-back) animation, driven by
        ``RadialMenuWidget.closing`` (emitted when a dismiss path BEGINS its
        fly-back). The dim child is hidden/torn down later by ``close_radial_menu``;
        this only retracts the backdrop IN STEP WITH the ring instead of a single
        hard ``hide()`` at teardown. Mirrors ``OverlayGroupController._collapse_dim``.
        Best-effort + guarded: a no-op when there is no dim."""
        dim = self._dim
        if dim is None:
            return
        try:
            from utils.overlay.radial_menu import radial_anim_enabled
            dim.start_close(animate=radial_anim_enabled())
        except Exception:
            pass

    def _ensure_radial_surface(self):
        """The PERSISTENT radial top-level: created + MAPPED once per overlay
        session (empty, fully transparent via the source-clear paint, and
        click-through via an EMPTY input shape), then reused by every ring open.

        WHY persistent (load-bearing): mapping a window is what triggers
        compositor open animations (when the surfaces were NOTIFICATION-typed,
        the slidingnotifications effect slid every fresh map in from the screen
        edge - live round 3's "fly up from below the monitor"). Probed
        2026-07-01: the geometry is honored from the first frame (such slides
        are purely visual) and no skip-OPEN-animation property exists (only
        _KDE_NET_WM_SKIP_CLOSE_ANIMATION is in the server's atom table). So the
        one map happens at enter() on an EMPTY invisible window; opening the
        ring later only hosts content into the already-mapped surface. The
        radial/panel are OSD-typed besides (not matched by that effect -
        source-verified + live-probed), and their OSD layer keeps them above
        the dock cluster through any raise order.

        Returns the surface, or None when construction failed (the caller then
        fails closed). Best-effort self-cleaning: a mid-build failure never
        leaks a half-built top-level."""
        if self._radial_surface is not None:
            return self._radial_surface
        if not self._active:
            return None
        surface = None
        try:
            from utils.overlay.cluster_surface import RadialSurface
            from PySide6.QtCore import QRect
            from PySide6.QtGui import QPainterPath
            canvas_max = self._radial_canvas_max()
            ax, ay = self._anchor
            surface = RadialSurface(backend=self._backend)
            surface.set_overlay_geometry(
                QRect(int(ax - canvas_max / 2), int(ay - canvas_max / 2),
                      canvas_max, canvas_max))
            self._safe_call(surface, "prepare_initial_state")
            # Opacity-0 while EMPTY (not just until first paint): a closed
            # mapped window that changes geometry exposes buffer-less regions
            # KWin composites as opaque black; the blank makes every
            # closed-state move/resize invisible by construction. Lifted only
            # by the open path once content is hosted + painted. Guarded:
            # test stubs may lack the method.
            blank = getattr(surface, "set_content_blanked", None)
            if blank is not None:
                blank(True)
            surface.show()
            self._radial_surface = surface
            # Click-through while empty: a mapped window without a shape keeps
            # X11's default FULL-RECT input region and would swallow every
            # click over its (invisible) canvas.
            self._apply_radial_input_shape(QPainterPath())
            # Running-code stamp (anchor-tracking build): live validation must be
            # able to prove THIS lifecycle is running and identify the window.
            try:
                from utils.overlay.backend import overlay_trace
                overlay_trace(
                    "persistent radial surface pre-mapped (anchor-tracking build) "
                    f"xid={int(surface.winId()):#x} at {surface.geometry()}")
            except Exception:
                pass
            return surface
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster_controller._ensure_radial_surface() FAILED:\n"
                          + traceback.format_exc())
            self._radial_surface = None
            if surface is not None:
                self._safe_call(surface, "hide")
                self._safe_call(surface, "deleteLater")
            return None

    def _ensure_panel_surface(self):
        """The PERSISTENT portable-Settings top-level: same lifecycle and same
        rationale as ``_ensure_radial_surface`` (one map per session on an empty
        invisible window; per-open content swaps never re-map, so the
        compositor's notification open animation can never play over content).
        Sized to the CURRENT-scale ``emblem*6`` canvas - the size the next open
        will use - so the open-time geometry call carries no delta for the
        compositor to morph; ``_reposition_panel`` keeps the empty window glued
        to that size + the anchor as they change while closed."""
        if self._panel_surface is not None:
            return self._panel_surface
        if not self._active:
            return None
        surface = None
        try:
            from utils.overlay.cluster_surface import PanelSurface
            from utils.overlay.card_metrics import CardMetrics
            from PySide6.QtCore import QRect
            from PySide6.QtGui import QPainterPath
            size = int(CardMetrics(self._scale).emblem * 6)
            ax, ay = self._anchor
            surface = PanelSurface(backend=self._backend)
            surface.set_overlay_geometry(
                QRect(int(ax - size / 2), int(ay - size / 2), size, size))
            self._safe_call(surface, "prepare_initial_state")
            # Opacity-0 while EMPTY - the closed panel is RESIZED on every
            # scale notch (emblem*6 tracking), and a resize of a mapped
            # buffer-behind window composites its fresh L-band as opaque
            # black whenever the paint flush lags (the busy GUI thread during
            # a scale burst) - the live J-shaped black rectangle. Blanked,
            # the tracking geometry changes are invisible by construction.
            # Guarded: test stubs may lack the method.
            blank = getattr(surface, "set_content_blanked", None)
            if blank is not None:
                blank(True)
            surface.show()
            self._panel_surface = surface
            self._apply_panel_input_shape(QPainterPath())   # click-through while empty
            return surface
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster_controller._ensure_panel_surface() FAILED:\n"
                          + traceback.format_exc())
            self._panel_surface = None
            if surface is not None:
                self._safe_call(surface, "hide")
                self._safe_call(surface, "deleteLater")
            return None

    def _destroy_persistent_surfaces(self) -> None:
        """Unmap + delete the persistent radial/panel top-levels. leave() only:
        per-open close keeps them mapped (unmapping and re-mapping is what
        replays the compositor's open animation). Content is already gone by
        the time this runs (close_radial_menu/close_panel_surface ran first).
        Panel first, then radial (the reverse of the ensure order at enter)."""
        panel = self._panel_surface
        self._panel_surface = None
        if panel is not None:
            self._safe_call(panel, "hide")
            self._safe_call(panel, "deleteLater")
        surface = self._radial_surface
        self._radial_surface = None
        if surface is not None:
            self._safe_call(surface, "hide")
            self._safe_call(surface, "deleteLater")

    # ------------------------------------------------------------------
    # Taskbar representative (float UI owns the taskbar)
    # ------------------------------------------------------------------
    def _ensure_taskbar_rep(self) -> None:
        """Create + show the taskbar representative. Best-effort and decorative:
        a failure must never affect an otherwise-successful enter. No-op when
        one is already up or when the backend is unavailable (no X11 = no
        thumbnail/stacking machinery to lean on; the plain hide() behavior of
        enter() stands alone)."""
        if self._taskbar_rep is not None:
            return
        if not self._backend.is_available():
            return
        # Capability gate: on Windows the cluster window itself is taskbar-
        # listed (WIN_TASKBAR_IDENTITY ex-styles), so the aligned-mirror rep -
        # a KWin-specific workaround - is never built there.
        if not getattr(self._backend, "wants_taskbar_rep", lambda: True)():
            from utils.overlay.backend import overlay_trace
            overlay_trace("taskbar_rep: skipped (backend declines; cluster "
                          "carries the taskbar identity)")
            return
        try:
            from utils.overlay.taskbar_representative import TaskbarRepresentative
            rep = TaskbarRepresentative(
                on_close_requested=self._request_app_quit,
                on_tick=self._refresh_taskbar_rep,
                backend=self._backend)
            self._taskbar_rep = rep
            self._position_taskbar_rep()    # geometry BEFORE map (program-specified)
            self._refresh_taskbar_rep()     # first mirror BEFORE map (no blank preview)
            rep.prepare_initial_state()     # pre-map hints (below + click-through)
            rep.show()
            from utils.overlay.backend import overlay_trace
            overlay_trace("taskbar_rep: shown (float UI owns the taskbar)")
        except Exception:
            self._teardown_taskbar_rep()

    def _teardown_taskbar_rep(self) -> None:
        """Destroy the representative (idempotent; never raises)."""
        rep = self._taskbar_rep
        self._taskbar_rep = None
        if rep is None:
            return
        try:
            rep.hide()
            rep.deleteLater()
        except Exception:
            pass

    def _request_app_quit(self) -> None:
        """Close on the representative = quit the app via the main window's
        normal close() -> shutdown path (the exact route the radial Exit spoke
        takes; close() reaches a hidden window's closeEvent normally)."""
        self._safe_call(self._window, "close")

    def _content_bbox_window_coords(self):
        """Union of the emblem rect and every VISIBLE cell's transform-mapped
        rect, in window-local coords: the tight crop the taskbar preview shows
        ("the emblem plus however many cards are up" - never the mostly-empty
        max-scale envelope). Null QRect when nothing is measurable."""
        from PySide6.QtCore import QRect
        bbox = QRect(self._emblem_rect())
        win = self._compute_window_rect()
        ox, oy = win.x(), win.y()
        for _idx, screen_rect, _controls, _cutout in self._visible_card_geoms():
            bbox = bbox.united(screen_rect.translated(-ox, -oy))
        return bbox

    @staticmethod
    def _opaque_only(pixmap):
        """Strip sub-opaque pixels (alpha < 250 -> fully transparent).

        The on-screen rep may only paint pixels the cluster hides with
        IDENTICAL fully-opaque ones; translucent pixels (card shadows, glow,
        AA edges) would double-composite and read darker/stronger inside the
        bbox. Byte-level translate keeps this C-speed. ARGB32 little-endian
        memory layout is BGRA, so the alpha byte sits at offset 3. The wrapping
        QImage references the mutated bytearray WITHOUT copying; the single
        defensive ``out.copy()`` detaches the result from that scope-local
        buffer before it leaves the function."""
        from PySide6.QtGui import QImage, QPixmap
        img = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        buf = bytearray(img.constBits())
        tbl = bytes(255 if a >= 250 else 0 for a in range(256))
        buf[3::4] = buf[3::4].translate(tbl)
        out = QImage(buf, img.width(), img.height(),
                     img.bytesPerLine(), QImage.Format_ARGB32)
        out.setDevicePixelRatio(img.devicePixelRatio())
        return QPixmap.fromImage(out.copy())

    def _refresh_taskbar_rep(self, force: bool = False) -> None:
        """Re-grab the cropped, opaque-only float-UI mirror into the
        representative. Best-effort and cheap enough for the slow tick; no-op
        when inactive or blanked (a blanked rep is invisible everywhere, so a
        grab mid-gesture would be wasted work on frozen pixels). *force*
        bypasses ONLY the blanked early-return: the unblank sequence must grab
        the fresh mirror while the rep is still blanked (paint-before-opacity,
        see _update_rep_blanking)."""
        rep = self._taskbar_rep
        if rep is None or not self._active or self._surface is None:
            return
        if rep.is_blanked() and not force:
            return
        try:
            bbox = self._content_bbox_window_coords()
            if bbox.isNull() or bbox.isEmpty():
                return
            grab = getattr(self._surface, "grab", None)
            if grab is None:
                return
            rep.set_mirror(self._opaque_only(grab(bbox)))
        except Exception:
            pass

    def _position_taskbar_rep(self) -> None:
        """Pixel-align the representative UNDER the on-screen content bbox: the
        aligned-mirror invariant (every opaque rep pixel covered by an identical
        cluster pixel above it) is what makes it invisible. Best-effort."""
        rep = self._taskbar_rep
        if rep is None:
            return
        try:
            bbox = self._content_bbox_window_coords()
            if bbox.isNull() or bbox.isEmpty():
                return
            win = self._compute_window_rect()
            rep.setGeometry(bbox.translated(win.topLeft()))
        except Exception:
            pass

    def _update_rep_blanking(self) -> None:
        """Single source of truth for the aligned-mirror invariant: the rep may
        be visible ONLY in the settled, unobstructed state. Any gesture that
        moves/scales/fades the cluster out from over the mirror blanks it;
        settling re-aligns, re-grabs, and only THEN unblanks.

        ORDERING INVARIANT (paint-before-opacity): the opacity-1 write goes
        LAST. set_blanked(False) flushes on the xlib connection immediately,
        while the re-align/re-grab land as Qt-side paints - unblanking first
        would show one full-opacity frame of the STALE mirror at the OLD
        position after every drag end / scale settle. So the settled branch
        aligns, force-grabs (the rep is still blanked, hence force=True to
        bypass the refresh's blanked early-return), synchronously repaints,
        and writes the opacity only once the visible window already holds the
        fresh aligned mirror."""
        rep = self._taskbar_rep
        if rep is None:
            return
        drag_active = self._drag_timer is not None and self._drag_timer.isActive()
        obstructed = (self._scaling_active or drag_active
                      or self._rep_peek_active or self.is_radial_open)
        if obstructed:
            rep.set_blanked(True)
            return
        self._position_taskbar_rep()
        self._refresh_taskbar_rep(force=True)
        try:
            rep.repaint()             # paint lands before the opacity flush
        except Exception:
            pass
        rep.set_blanked(False)

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
        leak untracked state. The menu is tracked BEFORE any fallible step, so on
        ANY error ``close_radial_menu()`` tears the partial state down and the
        method fails closed (returns None, ``is_radial_open`` False). The surface
        is the PERSISTENT pre-mapped top-level (``_ensure_radial_surface``); it is
        never mapped here, so the compositor's window-open animation cannot play
        over the ring - the menu's own fly-out is the only reveal motion."""
        from utils.overlay.backend import overlay_trace as _otr
        _otr(f"cluster.open_radial_menu called: active={self._active} "
             f"already_open={self.is_radial_open}")
        if not self._active:
            return None
        if self.is_radial_open:
            return None  # already open (and already wired by the first call)
        surface = self._ensure_radial_surface()
        if surface is None:
            return None  # fail-closed: no top-level to host the ring in
        from utils.overlay.radial_menu import RadialMenuWidget, radial_anim_enabled
        from PySide6.QtCore import QRect
        try:
            emblem_dia, canvas = self._radial_canvas()
            canvas_max = self._radial_canvas_max()
            menu = RadialMenuWidget(emblem_diameter=emblem_dia)
            self._radial_size = canvas
            ax, ay = self._anchor
            # The radial top-level is sized to the FIXED max-scale canvas (never
            # resized by a scale gesture - the same no-geometry-during-scale
            # discipline as the cluster window); the menu paints its ring from
            # emblem_dia about the widget center, so the extra margin is inert.
            geom = QRect(int(ax - canvas_max / 2), int(ay - canvas_max / 2),
                         canvas_max, canvas_max)
            # Diagnostic: the open-time geometry DELTA must be zero (the closed-
            # state anchor tracking already parked the window here); a nonzero
            # delta live means the tracking never ran (stale build / missed path).
            try:
                cur = surface.geometry()
                _otr(f"radial open: surface at ({cur.x()},{cur.y()}) target "
                     f"({geom.x()},{geom.y()}) delta "
                     f"({geom.x() - cur.x()},{geom.y() - cur.y()})")
            except Exception:
                pass
            # Track the menu IMMEDIATELY (before any fallible host step), so a
            # failure from here on is cleaned up by close_radial_menu() instead
            # of leaking a built-but-untracked menu.
            self._radial_menu = menu
            surface.host(menu)
            # Re-center the ALREADY-MAPPED window on the current anchor: a pure
            # move, which the compositor never animates (only a map does).
            surface.set_overlay_geometry(geom)
            # NON-EMPTY click region: the CURRENT-scale canvas, centered in the
            # fixed max-canvas window, MINUS the emblem disc - the hole lets
            # emblem gestures (click-to-close, scroll-to-scale, drag) pass
            # through to the cluster window while the ring is open. The cluster
            # window stays click-through; this surface is additive. Clicks in
            # the inert margin outside the canvas pass through to the games.
            self._apply_radial_input_shape(self._radial_click_path())
            # Re-assert the dim's framed-1.0 placement BEFORE showing it (it is
            # scale-independent in the transform model; this is belt-and-suspenders
            # against anything having moved it while closed).
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
            # Retract the internal dim IN STEP WITH the ring's fly-back: the menu
            # emits `closing` when any dismiss path begins its fly-back (and defers
            # `close_requested` until the animation completes), so this makes the
            # backdrop collapse with the ring instead of a hard hide at teardown.
            # Mirrors OverlayGroupController's `menu.closing.connect(_collapse_dim)`.
            menu.closing.connect(self._collapse_internal_dim)
            # Teardown when the fly-back completes: every dismiss path (menu-side
            # Esc/idle/close-spoke AND the controller-side dismiss_radial_menu used
            # by the drag auto-close) funnels through close_requested. The caller
            # (main._wire_radial_menu) also connects this; close_radial_menu is
            # idempotent, so the double invocation is harmless - this
            # controller-side connect keeps dismiss_radial_menu self-sufficient.
            # Guarded: a stub menu without the signal must not tank the open.
            try:
                menu.close_requested.connect(self.close_radial_menu)
            except Exception:
                pass
            # Re-apply the spokes-only input shape when the ring swaps between the
            # main and accounts states (different spoke count/geometry). Guarded:
            # a stub menu without the signal must not tank the open.
            try:
                menu.state_changed.connect(self._reapply_radial_shape)
            except Exception:
                pass
            try:
                menu.start_reveal()
            except Exception:
                pass
            # Lift the empty-state blank only AFTER start_reveal has staged the
            # entrance's frame-0 state: set_content_blanked(False) force-paints
            # before its opacity-1 write (paint-before-opacity), so unblanking
            # any earlier flashes one frame of the RESTING fully-open ring
            # before the fly-out resets it (seen live 2026-07-02). After the
            # staging, the painted frame IS the animation start - the flash is
            # impossible by ordering. With animations disabled start_reveal
            # snaps to the settled ring and this paints exactly that. Stub
            # surfaces without the method open unblanked as before; on the
            # real surface a failure propagates into the rollback.
            unblank = getattr(surface, "set_content_blanked", None)
            if unblank is not None:
                unblank(False)
            # Click-off dismissal: watch global presses for the ring's lifetime
            # (best-effort; self-guarded + backend-gated).
            self._start_radial_dismiss_capture()
            # If the portable Settings panel is ALSO open, keep it ABOVE the
            # just-shown/-restacked radial top-level (the panel must always float
            # above the emblem AND the radial). Best-effort re-raise: a failure here
            # must never tank a successful radial open.
            if self.is_panel_open:
                self._safe_call(self._panel_surface, "raise_")
            self._update_rep_blanking()
            return menu
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster_controller.open_radial_menu() FAILED; rolling "
                          "back (fail-closed):\n" + traceback.format_exc())
            self.close_radial_menu()
            return None

    def dismiss_radial_menu(self) -> None:
        """Begin the ring's ANIMATED dismiss: the spokes fly back into the emblem
        (the menu's own ``_begin_close``), the internal dim collapses in step
        (via the ``closing`` signal), and the actual teardown runs when the
        fly-back completes (``close_requested`` -> ``close_radial_menu``) - the
        exact same sequence as every menu-side dismiss (Esc / idle / close
        spoke), so a controller-side close (emblem click toggle, drag start)
        looks identical. Falls back to the immediate ``close_radial_menu()``
        when the menu lacks the animation engine (a bare stub) or begin-close
        raises. Idempotent: ``_begin_close`` self-guards while already closing,
        and a call with no ring open is a no-op."""
        menu = self._radial_menu
        begin = getattr(menu, "_begin_close", None) if menu is not None else None
        if begin is None:
            if self.is_radial_open:
                self.close_radial_menu()
            return
        try:
            begin()
        except Exception:
            self.close_radial_menu()

    def close_radial_menu(self) -> None:
        """Tear down the radial MENU and hide (but keep) the internal dim.
        Idempotent: a call when the radial was never open is a safe no-op.

        The persistent radial top-level is NOT unmapped: it goes back to its
        empty state (transparent + EMPTY input shape = invisible and
        click-through) so the next open never re-maps a window - re-mapping is
        what plays the compositor's open animation. The surface dies only at
        leave() (``_destroy_persistent_surfaces``).

        The cluster window is never resized here: it stays at the closed bbox the
        whole time the radial is open (the radial-open expansion was removed), so
        there is nothing to shrink back."""
        surface = self._radial_surface           # persists across opens
        menu = self._radial_menu
        self._radial_menu = None
        self._radial_size = 0
        self._stop_radial_dismiss_capture()      # the ring is gone; stop watching
        if self._radial_reshape_timer is not None:
            self._radial_reshape_timer.stop()  # drop any pending settle reshape
        dim = self._dim
        if dim is not None:
            self._safe_call(dim, "hide")
        if menu is not None:
            # Reparent the menu OUT of the persistent surface, then delete it.
            # release() (the OverlaySurface API) unhooks the layout tracking; a
            # stub surface without it degrades to a plain hide + unparent.
            released = None
            release = getattr(surface, "release", None) if surface is not None else None
            if release is not None:
                try:
                    released = release()
                except Exception:
                    released = None
            if released is None:
                self._safe_call(menu, "hide")
                try:
                    menu.setParent(None)
                except Exception:
                    pass
            self._safe_call(menu, "deleteLater")
        if surface is not None:
            # Click-through while empty (see _ensure_radial_surface).
            from PySide6.QtGui import QPainterPath
            self._apply_radial_input_shape(QPainterPath())
            # Re-engage the empty-state blank so closed-state anchor tracking
            # stays invisible by construction (guarded: stubs may lack it).
            blank = getattr(surface, "set_content_blanked", None)
            if blank is not None:
                try:
                    blank(True)
                except Exception:
                    pass
        self._restack_internal_layers()
        # Radial gone (immediate close or the dismiss fly-back's terminal step,
        # which funnels here via close_requested): unblank + re-align + re-grab.
        self._update_rep_blanking()

    def _reposition_radial(self) -> None:
        """Keep the radial top-level centered on the anchor and its painted ring in
        lockstep with the emblem at the CURRENT scale. The surface geometry is the
        FIXED max-scale canvas - a scale change only updates the menu's emblem
        diameter (a repaint) and defers the click-region re-apply to the settle
        timer (re-applying the X11 input shape under the pointer mid-scroll stalls
        the wheel stream); a drag re-centers the fixed-size window (a pure move).

        The surface move runs even while CLOSED (empty persistent window): the
        compositor animates geometry changes of the notification-typed window,
        so it must track the anchor while INVISIBLE - if it only caught up at
        open, KWin would morph the ring from the stale position to the emblem
        (seen live: reopen-after-drag animated in from the old spot). Kept glued
        here, the open-time geometry call has no delta left to animate."""
        surface = self._radial_surface
        if surface is None:
            return
        from PySide6.QtCore import QRect
        canvas_max = self._radial_canvas_max()
        ax, ay = self._anchor
        geom = QRect(int(ax - canvas_max / 2), int(ay - canvas_max / 2),
                     canvas_max, canvas_max)
        try:
            moved = geom != surface.geometry()
            surface.set_overlay_geometry(geom)
            if moved and not self.is_radial_open:
                # Diagnostic: proves the CLOSED-state tracking executed live
                # (per drag step). Silent unless TTMT_OVERLAY_TRACE is set.
                from utils.overlay.backend import overlay_trace
                overlay_trace(f"closed radial tracked anchor -> {geom}")
        except Exception:
            pass
        if not self.is_radial_open:
            return   # empty persistent window: anchoring it is all there is to do
        emblem_dia, canvas = self._radial_canvas()
        resized = canvas != self._radial_size
        self._radial_size = canvas
        if resized:
            if self._radial_menu is not None:
                try:
                    self._radial_menu.set_emblem_diameter(emblem_dia)
                except Exception:
                    pass
            self._schedule_radial_reshape()
        # The dim is scale-independent (a child of the transformed host); this is
        # a cheap idempotent re-assert of its framed-1.0 placement.
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
        """Apply the CURRENT-scale canvas click region (with the emblem-disc
        hole), centered in the fixed max-canvas window. Fired by the settle
        timer; a no-op once the menu is closed."""
        surface = self._radial_surface
        if surface is None or self._radial_size <= 0:
            return
        self._apply_radial_input_shape(self._radial_click_path())

    def _radial_click_path(self):
        """The radial surface's click region: ONLY the ring's interactive spoke
        circles (``menu.interactive_path()``; widget coords == window coords
        because the menu fills the fixed max-canvas window full-bleed).

        Everything else on the invisible canvas - the corners, the gap between
        the emblem and the spokes - is CLICK-THROUGH, so game UI or card
        controls sitting under the canvas stay usable while the ring is open
        (live complaint: the old full-canvas square swallowed the game's
        friends button). Click-off dismissal is the global-press watcher's job
        (``_on_radial_global_press``), not an input-shape concern. The emblem
        needs no explicit hole anymore - the spokes never overlap its disc, so
        emblem gestures (click-to-toggle, scroll-to-scale, drag) pass through
        by construction.

        Fallback for a menu without ``interactive_path`` (bare stubs): the
        legacy CURRENT-scale canvas square minus the emblem disc."""
        menu = self._radial_menu
        path_fn = getattr(menu, "interactive_path", None) if menu is not None else None
        if path_fn is not None:
            try:
                return path_fn()
            except Exception:
                pass
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainterPath
        emblem_dia, canvas = self._radial_canvas()
        canvas_max = self._radial_canvas_max()
        off = (canvas_max - canvas) // 2
        outer = QPainterPath()
        outer.addRect(off, off, canvas, canvas)
        hole = QPainterPath()
        c = canvas_max / 2.0
        r = emblem_dia / 2.0
        hole.addEllipse(QRectF(c - r, c - r, emblem_dia, emblem_dia))
        return outer.subtracted(hole)

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

    # ---- Click-off dismissal (global-press watcher) --------------------
    def _start_radial_dismiss_capture(self) -> None:
        """Start watching GLOBAL mouse presses while the ring is open (portal-safe
        XRecord observation, same machinery click-sync uses): a press that is
        not on the ring's spokes, the emblem, or the open panel dismisses the
        ring through the SAME fly-back path as every other close. The press is
        never consumed - the radial window is click-through outside the spokes,
        so it lands on whatever is beneath (game UI, card controls).

        Gated on backend availability so offscreen tests (NoOp backends) never
        open real X connections. Degrades silently: without the watcher the
        ring still closes via emblem toggle / spoke / Esc / idle timer. Only
        real DEVICE presses are observed (XRecord excludes the app's own
        synthetic XSendEvent clicks by construction)."""
        if self._radial_dismiss_capture is not None:
            return
        factory = self._dismiss_capture_factory
        if factory is None:
            if not self._backend.is_available():
                return
            import sys
            if sys.platform == "win32":
                # Same contract as XRecordCapture (factory(on_event) ->
                # .start()/.stop()); pynput WH_MOUSE_LL, observe-only, and
                # blind to the app's own PostMessage traffic by construction.
                from utils.win32_mouse_capture import Win32MouseCapture
                factory = Win32MouseCapture
            elif sys.platform.startswith("linux"):
                from utils.xrecord_capture import XRecordCapture
                factory = XRecordCapture
            elif sys.platform == "darwin":
                # Same contract again: listen-only CGEventTap, gated on the
                # Input Monitoring TCC grant (start() returns False without
                # it - the graceful no-dismiss degrade below), and blind to
                # the app's own SkyLight/CGEventPostToPid traffic via the
                # SPIKE_EVENT_TAG marker + own-pid guard by default.
                from utils.macos_mouse_capture import MacOSMouseCapture
                factory = MacOSMouseCapture
            else:
                return
        try:
            if self._press_bridge is None:
                from PySide6.QtCore import QObject, Signal

                class _PressBridge(QObject):
                    pressed = Signal(int, int)

                self._press_bridge = _PressBridge()
                # Connected on the GUI thread: emits from the capture thread are
                # QUEUED onto it (the on_ghost_event marshalling pattern).
                self._press_bridge.pressed.connect(self._on_radial_global_press)
            bridge = self._press_bridge

            def _on_event(kind, root_x, root_y, _state, _time):
                # Capture thread: filter cheap, marshal presses only.
                if kind == "press":
                    bridge.pressed.emit(int(root_x), int(root_y))

            capture = factory(_on_event)
            if capture.start():
                self._radial_dismiss_capture = capture
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("radial dismiss capture start FAILED (degrading to "
                          "menu-side closes only):\n" + traceback.format_exc())
            self._radial_dismiss_capture = None

    def _stop_radial_dismiss_capture(self) -> None:
        capture = self._radial_dismiss_capture
        self._radial_dismiss_capture = None
        if capture is not None:
            try:
                capture.stop()
            except Exception:
                pass

    def _on_radial_global_press(self, x, y) -> None:
        """A GLOBAL device press while the ring is open (GUI thread; queued from
        the capture thread). *x*, *y* are physical root pixels - convert like the
        ghost path does. Dismiss with the fly-back unless the press is on our
        chrome. Never raises into Qt dispatch."""
        if not self.is_radial_open:
            return   # late queued press after close: no-op
        try:
            lx, ly = emitted_to_logical(x, y)
            if self._point_on_radial_chrome(lx, ly):
                return
            self.dismiss_radial_menu()
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster_controller._on_radial_global_press() suppressed "
                          "(never raise into Qt dispatch):\n" + traceback.format_exc())

    def _point_on_radial_chrome(self, lx, ly) -> bool:
        """True when the LOGICAL screen point sits on ring chrome that handles its
        own clicks: the spokes (the menu acts), the emblem (the toggle acts), or
        the open Settings panel (interacting with it must not dismiss the ring
        beneath it). Everything else is 'off' - the dismissal zone."""
        from PySide6.QtCore import QPointF
        surface = self._radial_surface
        if surface is not None:
            try:
                g = surface.geometry()
                if self._radial_click_path().contains(QPointF(lx - g.x(), ly - g.y())):
                    return True
            except Exception:
                pass
        try:
            emblem = self._emblem_rect()
            if not emblem.isNull():
                win = self._compute_window_rect()
                if emblem.translated(win.x(), win.y()).contains(int(lx), int(ly)):
                    return True
        except Exception:
            pass
        if self.is_panel_open and self._panel_surface is not None:
            try:
                if self._panel_surface.geometry().contains(int(lx), int(ly)):
                    return True
            except Exception:
                pass
        return False

    # ------------------------------------------------------------------
    # Portable Settings panel surface
    # ------------------------------------------------------------------
    def open_panel_surface(self, widget, on_close=None):
        """Host an arbitrary *widget* on a centered, click-accepting owned top-level
        (the portable Settings panel), floating ABOVE the emblem + radial.

        Sizes the panel to a generous ``emblem*6`` canvas at the current scale,
        centers it on the anchor (the emblem's screen center), shows + raises it, and
        applies a FULL-RECT click-accepting input shape (the whole panel is
        interactive - unlike the click-through cluster window). ``on_close`` runs in
        close_panel_surface() BEFORE teardown so the caller reparents its hosted
        content out first. Returns the surface (the SAME surface when already open),
        or None when framed / when the open transaction fails.

        ``on_close`` CONTRACT: it MUST be idempotent and safe to call even when the
        hosted widget was never reparented IN. On a failed-open rollback the widget may
        never have been hosted (``host`` can raise before the reparent) yet
        close_panel_surface() still runs ``on_close``; and the real caller
        (``main.py``) also runs its own restore on a None return - so ``on_close`` can
        fire TWICE (once during the rollback, once from the caller's None-guard) and
        must tolerate both.

        Transaction-safe (the Task-7 lesson): the surface + on_close are tracked BEFORE
        any fallible step, and EVERY fallible open step (host, geometry,
        prepare_initial_state, show, raise_, and the input-shape apply) runs UNGUARDED
        so ANY failure PROPAGATES to the except-clause, which rolls back via
        close_panel_surface() (runs on_close, tears the partial top-level down) and
        fails closed (returns None, is_panel_open False) - never a half-open panel that
        was tracked but never prepared/shown/raised/shaped. Only THIS open path
        propagates; the post-open _reposition_panel() path stays best-effort."""
        if not self._active:
            return None
        if self.is_panel_open:
            return self._panel_surface   # already open (and already wired)
        surface = self._ensure_panel_surface()
        if surface is None:
            return None   # fail-closed: no persistent top-level to host into
        from utils.overlay.card_metrics import CardMetrics
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QPainterPath
        try:
            size = int(CardMetrics(self._scale).emblem * 6)
            # Track the open marker + on_close IMMEDIATELY (before any fallible
            # host step), so a failure from here on is cleaned up by
            # close_panel_surface() instead of leaking untracked state. The
            # surface itself is the persistent pre-mapped top-level
            # (_ensure_panel_surface) - it is never mapped here, so the
            # compositor's window-open animation cannot play over the panel.
            self._panel_size = size
            self._panel_on_close = on_close
            # EVERY fallible open step runs UNGUARDED so any failure PROPAGATES to the
            # except-clause (fail-closed rollback). Do NOT wrap these in _safe_call /
            # swallow=True: that would leave is_panel_open True with a panel that was
            # never hosted/raised/shaped. (_reposition_panel stays guarded.)
            surface.host(widget)
            ax, ay = self._anchor
            # Re-size + re-center the ALREADY-MAPPED window (no map, no animation).
            surface.set_overlay_geometry(
                QRect(int(ax - size / 2), int(ay - size / 2), size, size))
            surface.raise_()
            # NON-EMPTY click region: the WHOLE panel accepts clicks.
            path = QPainterPath()
            path.addRect(0, 0, size, size)
            self._apply_panel_input_shape(path, swallow=False)
            # Content hosted + shaped: lift the empty-state blank LAST (the
            # surface paints-before-opacity internally). A stub surface
            # without the method opens unblanked as before. Unguarded on the
            # real surface: a failure propagates into the rollback.
            unblank = getattr(surface, "set_content_blanked", None)
            if unblank is not None:
                unblank(False)
            return surface
        except Exception:
            from utils.overlay.backend import overlay_trace
            import traceback
            overlay_trace("cluster_controller.open_panel_surface() FAILED; rolling "
                          "back (fail-closed):\n" + traceback.format_exc())
            self.close_panel_surface()
            return None

    def close_panel_surface(self) -> None:
        """Close the panel: run ``on_close`` FIRST so the caller can reparent its
        hosted content out, then return the PERSISTENT surface to its empty state
        (invisible + click-through, still mapped - see ``_ensure_panel_surface``
        for why it is never unmapped per close). The surface itself dies only at
        leave() (``_destroy_persistent_surfaces``). Idempotent: a call when the
        panel was never open is a safe no-op.

        ``on_close`` CONTRACT: it MUST be idempotent and safe to call even when the
        hosted widget was never reparented IN. This method runs it during a
        failed-open rollback (where ``host`` may have raised before the reparent) as
        well as on a normal close, and the real caller also runs its own restore on a
        None return - so ``on_close`` can fire more than once and must tolerate it.

        Borrowed-content safety: ``on_close`` runs in a try/except (a raise must never
        abort the teardown), and any child STILL hosted in the surface afterwards is
        reparented out (see ``_release_panel_content``), so a raising on_close that
        never reclaimed the caller's widget cannot strand it inside the persistent
        surface (where leave()'s deleteLater would destroy it)."""
        cb = self._panel_on_close
        self._panel_on_close = None
        if cb is not None:
            try:
                cb()                          # restore reparented content FIRST
            except Exception:
                pass
        surface = self._panel_surface         # persists across opens (leave() kills it)
        self._panel_size = 0
        if surface is not None:
            # Protect BORROWED content: if on_close raised (or otherwise failed to
            # reparent the caller's widget out), the widget may still be a child of the
            # surface, and the surface outliving this close would strand it there.
            # Reparent any still-hosted child out FIRST (best effort); a child the
            # caller already moved elsewhere is left alone, so the happy path is
            # untouched.
            self._release_panel_content(surface)
            # Back to the empty persistent state: invisible (source-cleared, no
            # content) + click-through. NOT unmapped - re-mapping on the next open
            # would replay the compositor's window-open animation.
            from PySide6.QtGui import QPainterPath
            self._apply_panel_input_shape(QPainterPath())
            # Re-engage the empty-state blank: the closed panel resumes its
            # per-notch geometry tracking, which must stay invisible by
            # construction (guarded: stubs may lack the method).
            blank = getattr(surface, "set_content_blanked", None)
            if blank is not None:
                try:
                    blank(True)
                except Exception:
                    pass

    def _release_panel_content(self, surface) -> None:
        """Reparent the panel surface's still-hosted child out to None so a subsequent
        deleteLater cannot destroy a BORROWED widget. Best-effort + guarded, and a
        no-op unless the child is STILL parented to *surface* (a child the caller's
        on_close already reparented elsewhere is left where it is - the happy path).
        Uses the surface's ``release()`` when present (the OverlaySurface API), else a
        direct ``setParent(None)`` fallback."""
        if surface is None:
            return
        try:
            hosted = getattr(surface, "_hosted", None)
            if hosted is None or hosted.parent() is not surface:
                return
            release = getattr(surface, "release", None)
            if release is not None:
                release()
            else:
                hosted.setParent(None)
        except Exception:
            pass

    def _reposition_panel(self) -> None:
        """Re-center the panel top-level on the anchor. While OPEN it stays at its
        FIXED open-time size (the panel is re-centered, never rescaled) and is
        re-raised above the emblem + radial. While CLOSED (empty persistent
        window) it tracks the anchor AND the current-scale ``emblem*6`` size the
        NEXT open will use - same rationale as ``_reposition_radial``: the
        compositor animates geometry changes of the notification-typed window,
        so any catch-up move/resize must happen while it is invisible, leaving
        the open-time geometry call with no delta to animate."""
        surface = self._panel_surface
        if surface is None:
            return
        from PySide6.QtCore import QRect
        if self._panel_size > 0:
            size = self._panel_size
        else:
            from utils.overlay.card_metrics import CardMetrics
            size = int(CardMetrics(self._scale).emblem * 6)
        ax, ay = self._anchor
        try:
            surface.set_overlay_geometry(
                QRect(int(ax - size / 2), int(ay - size / 2), size, size))
        except Exception:
            pass
        if self.is_panel_open:
            self._safe_call(surface, "raise_")

    def _apply_panel_input_shape(self, path, swallow: bool = True) -> None:
        """Apply *path* as the panel surface's INPUT (click-accept) shape via the
        backend. Best-effort by default (``swallow=True``) so a shape failure never
        breaks a reposition; the OPEN path calls with ``swallow=False`` so a failure
        PROPAGATES into the open transaction (fail-closed rollback)."""
        surface = self._panel_surface
        if surface is None:
            return
        try:
            self._backend.apply_input_shape(surface, path, surface.devicePixelRatio())
        except Exception:
            if not swallow:
                raise

    def _reapply_panel_shape(self) -> None:
        """Re-apply the panel's FULL-RECT click region at the current panel size (and
        thus the surface's CURRENT device-pixel ratio). The panel's LOGICAL rect is
        unchanged; only the device conversion differs on a new monitor, so a
        screen-change re-apply honors the logical/device contract. No-op when the
        panel is closed. Mirrors ``_reapply_radial_shape``."""
        if self._panel_surface is None or self._panel_size <= 0:
            return
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.addRect(0, 0, self._panel_size, self._panel_size)
        self._apply_panel_input_shape(path)

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
    def _clear_envelope_state(self) -> None:
        """Drop the enter()-computed fixed-envelope placement (leave / a failed
        enter), so a framed controller recomputes fresh from the provider."""
        self._envelope = None
        self._pivot = None
        self._emblem_center = None
        self._host_size = None
        # The echo layer is a child of the (just-torn-down) surface: it dies
        # with it; only the reference is dropped here.
        self._ghost_echo = None

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
