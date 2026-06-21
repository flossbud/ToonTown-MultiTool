"""Surface-state model and pinwheel layout geometry for the transparent-mode overlay.

The TOP of this module is PURE geometry + state (SurfaceState, pinwheel_rects,
SLOT_CUTOUTS): no QApplication, importable headless via PySide6.QtCore (QRect).
The OverlayGroupController (Task 3.2) at the BOTTOM drives the five-surface
lifecycle; it lazy-imports the Qt-heavy ``_compact_layout`` / ``CardMetrics``
inside its methods so the pure parts above stay importable without pulling that
dependency at module load.

Emblem convention in SurfaceState
----------------------------------
Cards use surface_id 0-3 (matching the four pinwheel slots).
The emblem uses surface_id=-1 (a sentinel; callers must not depend on the
specific value) plus is_emblem=True.  Always check is_emblem, never the
sentinel value, when branching on emblem vs card.

Controller integration note (unit-scaling contract)
----------------------------------------------------
With a real card_provider the cards scale as ONE locked unit: each card is laid
out once at its framed 1.0 size and proxied into a per-card QGraphicsView whose
transform applies the group scale (so the card content never re-layouts and
nothing floats). The controller sizes each card window to the FRAMED 1.0 size
(provider.overlay_base_card_size()) times the scale and sets each card view's
transform; it does NOT call apply_metrics per scale. The emblem stays a single
painted widget and keeps metric-scaling via provider.scale_emblem(scale). When no
provider is present (the Task 3.2 tests) the controller falls back to the
placeholder base sizes + self._scale below.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from PySide6.QtCore import QRect

from utils.overlay.backend import get_overlay_backend
from utils.overlay.peek import GhostPointStore, peeking_indices, control_hits
from utils.screen_coords import emitted_to_logical
from utils.settings_keys import (
    GHOST_CURSORS_ENABLED, GHOST_CURSORS_CONTROL_CARDS,
)
from utils.overlay.scale import step_scale
from utils.overlay.surface import CardSurface, EmblemSurface, ShapeMode


# ---------------------------------------------------------------------------
# Slot -> cutout-corner mapping
# ---------------------------------------------------------------------------
# Which corner of each card faces the group center (gets the pinwheel bite).
# Matches scripts/transparent_multiwindow_spike.py Group.__init__ and
# _CFG in tabs/multitoon/_compact_layout.py, and spec section 7.
SLOT_CUTOUTS: dict[int, str] = {
    0: "br",   # top-left quadrant     -> bite bottom-right toward center
    1: "bl",   # top-right quadrant    -> bite bottom-left toward center
    2: "tr",   # bottom-left quadrant  -> bite top-right toward center
    3: "tl",   # bottom-right quadrant -> bite top-left toward center
}


# ---------------------------------------------------------------------------
# SurfaceState dataclass
# ---------------------------------------------------------------------------
@dataclass
class SurfaceState:
    """Per-surface state for one overlay window (a card or the emblem).

    v1 invariants
    -------------
    - attached is always True (all four cards + emblem form one cluster).
    - group_id is always 0 (single group).
    - shape_mode is PINWHEEL_BITE for cards; not meaningful for the emblem.

    v2 extension path
    -----------------
    Setting attached=False and shape_mode=ROUNDED_RECT marks a card as
    free-floating.  No structural change needed here; it is a pure state
    transition the controller (Task 3.2+) reconciles into new geometry.

    Emblem convention
    -----------------
    Cards:  surface_id in {0, 1, 2, 3}, is_emblem=False.
    Emblem: surface_id=-1 (sentinel, do not rely on the value), is_emblem=True.
    """

    surface_id: int
    is_emblem: bool = False
    group_id: int = 0
    attached: bool = True
    anchor: tuple[int, int] = (0, 0)
    scale: float = 1.0
    shape_mode: ShapeMode = ShapeMode.PINWHEEL_BITE

    def __post_init__(self) -> None:
        # The two emblem discriminators must agree (callers branch on is_emblem;
        # keep surface_id in sync so the sentinel can never contradict the flag).
        if self.is_emblem and self.surface_id != -1:
            raise ValueError("emblem SurfaceState must use surface_id=-1")
        if not self.is_emblem and self.surface_id not in (0, 1, 2, 3):
            raise ValueError("card SurfaceState surface_id must be a slot 0-3")


# ---------------------------------------------------------------------------
# Return type alias for pinwheel_rects
# ---------------------------------------------------------------------------
# Keys: int (0-3) for card slots, or str "emblem" for the emblem window.
PinwheelRects = dict[Union[int, str], QRect]


# ---------------------------------------------------------------------------
# Pinwheel layout function
# ---------------------------------------------------------------------------
def pinwheel_rects(
    anchor: tuple[int, int],
    scale: float,
    card_w: int,
    card_h: int,
    emblem: int,
    gap: int,
) -> PinwheelRects:
    """Compute the screen-space QRect for each card slot and the emblem.

    This is the PROVEN spike formula from ``Group.apply()`` in
    ``scripts/transparent_multiwindow_spike.py`` (lines 208-224), extracted
    verbatim as a pure function.

    Parameters
    ----------
    anchor:
        ``(cx, cy)`` screen coordinates of the emblem CENTER / group pivot.
    scale:
        Overlay zoom factor (1.0 = base size). Applied internally to all base
        dimensions before computing positions (exactly as the spike does:
        ``cw = int(card_w * scale)``, etc.).
    card_w, card_h:
        BASE (scale-1.0) card dimensions in pixels.
    emblem:
        BASE (scale-1.0) emblem disc diameter in pixels.
    gap:
        BASE (scale-1.0) gap between each card's inner corner and the group
        center in pixels.

    Returns
    -------
    dict mapping:
        ``0, 1, 2, 3`` -> QRect for each card slot window (top-left origin).
        ``"emblem"``    -> QRect for the emblem window (centered on anchor).

    Slot layout (matches spike and ``_CFG`` in tabs/multitoon/_compact_layout.py):

    ====  =====================  =============
    Slot  Screen quadrant        Bite corner
    ====  =====================  =============
    0     top-left               br (bottom-right toward center)
    1     top-right              bl (bottom-left toward center)
    2     bottom-left            tr (top-right toward center)
    3     bottom-right           tl (top-left toward center)
    ====  =====================  =============

    See also ``SLOT_CUTOUTS`` for the slot -> bite-corner lookup table.
    """
    cx, cy = anchor

    # Scale all base dimensions (verbatim spike: int(X * s))
    cw: int = int(card_w * scale)
    ch: int = int(card_h * scale)
    em: int = int(emblem * scale)
    g: int = int(gap * scale)

    # Card top-left positions (spike formula, verbatim from Group.apply())
    card_origins = [
        (cx - g - cw, cy - g - ch),   # slot 0: top-left quadrant,     bite br
        (cx + g,      cy - g - ch),   # slot 1: top-right quadrant,    bite bl
        (cx - g - cw, cy + g),        # slot 2: bottom-left quadrant,  bite tr
        (cx + g,      cy + g),        # slot 3: bottom-right quadrant, bite tl
    ]

    result: PinwheelRects = {}
    for slot, (x, y) in enumerate(card_origins):
        result[slot] = QRect(x, y, cw, ch)

    # Emblem: centered on anchor (spike: emblem.move(cx - em // 2, cy - em // 2))
    result["emblem"] = QRect(cx - em // 2, cy - em // 2, em, em)

    return result


# ---------------------------------------------------------------------------
# Controller base-layout inputs
# ---------------------------------------------------------------------------
# Base (scale-1.0) card WIDTH for the provider=None fallback path only. A live
# card_provider sources the real scaled sizeHint instead (see _compute_rects +
# the "Controller integration note" in the module docstring); this placeholder
# is used solely by the Task 3.2 stub-surface orchestration tests, which have no
# real card to measure. card_h + emblem come from CardMetrics(1.0) in that path.
_BASE_CARD_W = 300
# Inter-corner gap between each card and the group center, matching the spike
# (scripts/transparent_multiwindow_spike.py GAP=24).
_GROUP_GAP = 24


# ---------------------------------------------------------------------------
# OverlayGroupController
# ---------------------------------------------------------------------------
class OverlayGroupController:
    """Orchestrates the five overlay surfaces (4 cards + emblem) as one cluster.

    This is the lifecycle owner for transparent mode: it builds the surfaces,
    lays them out in the pinwheel, shapes their click-through holes, minimizes
    the main window, and tears everything down again.  It owns the LIVE anchor
    and scale; each ``SurfaceState`` carries a snapshot for the v2 detach path.

    Surfaces are NOT created here directly - they come from ``surface_factory``,
    a callable ``factory(state) -> surface``.  The default builds a real
    ``CardSurface`` / ``EmblemSurface``; tests inject a stub factory whose stub
    surfaces record their calls.  That injection is the key testability seam:
    no QApplication-bound overlay windows are needed to exercise orchestration.

    Fail-closed (spec section 5): ``enter()`` is a transaction.  If any step
    (factory / geometry / shape / show) raises, every surface created so far is
    released + closed, the main window is restored if it was minimized, and the
    controller stays Framed (``is_transparent`` False, ``enter()`` returns
    ``False``).  The app is never left with a half-built overlay.

    Real card widgets (Task 4.1b): when a ``card_provider`` (the _CompactLayout)
    is supplied, ``enter()`` reparents the REAL pinwheel cards + emblem into the
    surfaces - capturing each widget's exact tab placement BEFORE host() so the
    transaction can restore it - and ``leave()`` releases each widget from its
    surface and restores it to that exact slot, then resets framed (scale-1.0)
    metrics.  The fail-closed unwind returns every borrowed widget to the tab
    before destroying the surfaces (a live card is never deleted or stranded).
    When ``card_provider`` is None (the Task 3.2 orchestration tests), ``enter()``
    builds EMPTY surfaces with no reparent, exactly as before.
    """

    def __init__(self, window, backend=None, settings=None, surface_factory=None,
                 card_provider=None, on_active_changed=None):
        self._window = window
        # Optional observer notified with the new active state after a successful
        # enter() and after leave(). The tab uses it to keep the keep-alive
        # bar/glow repaint timers running while the (minimized) main window would
        # otherwise stop them. Best-effort: never invoked on a failed enter.
        self._on_active_changed = on_active_changed
        self._backend = backend if backend is not None else get_overlay_backend()
        # Stored for Task 6.1 (anchor/scale persistence); unused in this task.
        self._settings = settings
        self._surface_factory = surface_factory or self._default_surface_factory
        # The _CompactLayout (Task 4.1b). When present, enter() reparents the REAL
        # pinwheel cards + emblem into the surfaces (and leave()/fail-closed
        # restores them to the tab); when None, enter() builds EMPTY surfaces
        # exactly as the Task 3.2 orchestration tests expect (no reparent). The
        # provider must expose slot_widget(int) / emblem_widget() / capture_slot(w)
        # -> record / restore_slot(record) / apply_metrics(CardMetrics) /
        # control_rects(int) -> list[QRect].
        self._card_provider = card_provider
        # Transparent-mode card visibility: the surface_ids (0-3) currently
        # mapped. Empty quadrants are hosted-but-unmapped (no flash, fully
        # click-through). Reconciled live from the provider's occupancy.
        self._visible_cells: set = set()
        self._occupancy_pending: bool = False
        if card_provider is not None:
            sig = getattr(card_provider, "occupied_cells_changed", None)
            if sig is not None:
                sig.connect(self._on_occupancy_changed)

        # Per-surface state: cards 0-3 then the emblem LAST.  Order is load
        # bearing: the emblem is built + shown last and raised above the cards
        # (spec section 8 z-order), so it must be the final element here.
        self._states: list[SurfaceState] = [
            SurfaceState(surface_id=0),
            SurfaceState(surface_id=1),
            SurfaceState(surface_id=2),
            SurfaceState(surface_id=3),
            SurfaceState(surface_id=-1, is_emblem=True),
        ]
        # Emblem-last is load bearing (built/shown/raised last for z-order).
        assert self._states[-1].is_emblem, "emblem must be the last surface state"
        self._surfaces: list = []          # parallel to _states; built on enter()
        # Parallel to _surfaces when a card_provider is active: one
        # (surface, SlotRecord) per reparented widget, captured BEFORE host() so
        # leave()/fail-closed can restore each borrowed card/emblem to its EXACT
        # tab placement. Empty when provider is None (no widgets borrowed).
        self._captured: list = []
        # Surfaces whose release() failed during teardown: we KEEP a reference so
        # Python GC cannot destroy the parentless surface (which would delete the
        # still-hosted borrowed card). Leaks the surface to keep the card alive.
        self._orphans: list = []
        self._anchor: tuple[int, int] = self._default_anchor()
        self._scale: float = 1.0
        self._active: bool = False
        # Debounce gate for the provider recompute (scale_emblem + per-card
        # set_card_scale transform + geometry + reshape). set_scale_by_notches updates self._scale
        # synchronously but coalesces a burst of recomputes into ONE on the next
        # event-loop tick; this flag is the single scheduling/cancel gate (see
        # _schedule_recompute / _run_pending_recompute / flush_pending_recompute).
        self._recompute_pending: bool = False
        # Emblem gesture wiring (Task 5.1). The emblem reference + an active
        # manual-drag poll: move_requested fires ONCE at drag-start and carries no
        # delta, so the controller tracks the global cursor itself and moves the
        # group anchor until the mouse button is released.
        self._emblem = None
        self._drag_timer = None
        self._drag_last = None
        # Debounced persistence of the group anchor + scale + monitor (Task 6.1).
        # A burst of drag/scale changes coalesces into one settings write. No-op
        # when settings is None (the orchestration/stub tests).
        self._save_timer = None
        self._save_pending = False
        # Low-frequency ABOVE re-assert while transparent (Task 7.1): best-effort,
        # since some WMs drop _NET_WM_STATE_ABOVE when another window takes focus.
        self._above_timer = None
        # Hover-peek (transparent mode): a ~30ms poll that unions the real cursor
        # with click-sync ghost points and toggles each card's peek state. The
        # GhostPointStore is fed by on_ghost_event/on_ghost_clear (wired in main.py).
        self._peek_store = GhostPointStore()
        self._peek_timer = None
        # Per-card (surface_id 0-3) hover-peek progress 0.0 (normal) -> 1.0 (peeked),
        # lerped each tick for a smooth fade. Drives two tiers: the whole card to
        # CONTENT opacity (surface) + the background fill a bit further to BODY.
        self._peek_progress = [0.0, 0.0, 0.0, 0.0]
        # Accent-glow surface behind the cluster: a single click-through window
        # spanning the four card rects that paints the same soft halo the framed
        # tab draws behind its cards (the _GlowLayer that fills the central hole so
        # the emblem nests). Owned (created/destroyed here), NOT a borrowed widget.
        self._glow_surface = None
        self._glow_widget = None

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def is_transparent(self) -> bool:
        # Alias of is_active (one source of truth) - "transparent mode" == active.
        return self.is_active

    # ------------------------------------------------------------------
    # Defaults (factory + anchor)
    # ------------------------------------------------------------------
    def _default_surface_factory(self, state: SurfaceState):
        """Build a real overlay surface for *state* (cards vs emblem)."""
        if state.is_emblem:
            return EmblemSurface(backend=self._backend)
        return CardSurface(state.surface_id, backend=self._backend)

    @staticmethod
    def _default_anchor() -> tuple[int, int]:
        """Center of the primary screen, or (0, 0) if there is no QApplication."""
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return (0, 0)
        geo = screen.geometry()
        return (geo.x() + geo.width() // 2, geo.y() + geo.height() // 2)

    # ------------------------------------------------------------------
    # Persistence (Task 6.1): group anchor + scale + monitor identity
    # ------------------------------------------------------------------
    @staticmethod
    def _screens():
        """Connected screens as ``(name, left, top, right, bottom)`` logical
        tuples (the primitive form the pure persistence helpers consume)."""
        from PySide6.QtGui import QGuiApplication
        out = []
        for s in QGuiApplication.screens():
            g = s.geometry()
            out.append((s.name(), g.left(), g.top(), g.right(), g.bottom()))
        return out

    def _load_persisted_state(self) -> bool:
        """Restore the saved group scale + anchor, clamping the anchor to a
        currently-visible monitor (recenter if the saved monitor is gone). No-op
        without a settings object (the stub/orchestration tests).

        Returns True if a SAVED anchor was restored, so enter() skips the
        default-anchor fallback: a saved anchor of (0, 0) is a VALID origin point
        and must NOT be mistaken for the no-QApplication sentinel."""
        if self._settings is None:
            return False
        from utils.overlay.persistence import (
            load_overlay_state, clamp_anchor_to_screens,
        )
        anchor, scale, monitor = load_overlay_state(self._settings)
        self._scale = scale
        for state in self._states:
            state.scale = scale
        if anchor is not None:
            self._anchor = clamp_anchor_to_screens(anchor, monitor, self._screens())
            return True
        return False

    def _save_state(self) -> None:
        """Persist the current group anchor + scale + the monitor it sits on."""
        if self._settings is None:
            return
        from utils.overlay.persistence import save_overlay_state, monitor_for_anchor
        monitor = monitor_for_anchor(self._anchor, self._screens())
        save_overlay_state(self._settings, self._anchor, self._scale, monitor)

    def _schedule_save(self) -> None:
        """Debounce a persistence write: a burst of drag/scale changes collapses
        into one settings write ~250ms after a change. No-op without settings."""
        if self._settings is None or self._save_pending:
            return
        from PySide6.QtCore import QTimer
        self._save_pending = True
        if self._save_timer is None:
            self._save_timer = QTimer()
            self._save_timer.setSingleShot(True)
            self._save_timer.setInterval(250)
            self._save_timer.timeout.connect(self._run_pending_save)
        self._save_timer.start()

    def _run_pending_save(self) -> None:
        if not self._save_pending:
            return
        self._save_pending = False
        self._save_state()

    def flush_pending_save(self) -> None:
        """Write any pending debounced save synchronously NOW (tests + leave)."""
        if self._save_pending:
            self._save_pending = False
            if self._save_timer is not None:
                self._save_timer.stop()
            self._save_state()

    # ------------------------------------------------------------------
    # Geometry + shape helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _key(state: SurfaceState):
        """pinwheel_rects key for *state*: "emblem" or the card slot int."""
        return "emblem" if state.is_emblem else state.surface_id

    def _compute_rects(self) -> "PinwheelRects":
        """Pinwheel rects at the current anchor + scale.

        Two contracts, by whether a card_provider is present:

        * provider present (unit-scaling): each card window is the FRAMED 1.0 size
          (provider.overlay_base_card_size()) multiplied by the group scale - the
          card content itself is NOT re-laid-out per scale; it stays at 1.0 and the
          per-card view transform zooms it (so nothing floats). The emblem extent
          (provider.emblem_size()) reflects the most recent scale_emblem(scale).
          Sizes are passed ALREADY SCALED with ``scale=1.0`` so pinwheel_rects keeps
          them verbatim, and the gap derives from the framed grid_gap/2.
        * provider None (Task 3.2 orchestration tests): the placeholder base
          sizes (_BASE_CARD_W) + CardMetrics(1.0) for card_h/emblem, with the
          scale applied INSIDE pinwheel_rects exactly as before.
        """
        # CardMetrics is pure, but lazy-import it (per the module docstring) so
        # the pure geometry at the top never pulls anything at module load.
        from utils.overlay.card_metrics import CardMetrics
        provider = self._card_provider
        if provider is not None:
            base_w, base_h = provider.overlay_base_card_size()   # framed 1.0 size
            card_w, card_h = round(base_w * self._scale), round(base_h * self._scale)
            emblem = provider.emblem_size()
            # Spacing must MATCH the framed 2x2 grid, not the spike's looser gap.
            # The framed grid puts cards `grid_gap` apart, so each card's inner
            # corner sits grid_gap/2 from the emblem center. The old _GROUP_GAP
            # (24) flung the cards ~2.7x too far (central gap 48 vs framed 18),
            # leaving the emblem floating with large gaps. Derive from the live
            # grid_gap so the cluster nests exactly like the tab.
            gap = round(CardMetrics(self._scale).grid_gap / 2)
            # Card sizes are pre-scaled (base * scale); scale=1.0 so pinwheel_rects
            # keeps them verbatim (int(x * 1.0) == x). The contract: scaled sizes +
            # scale=1.0, never base sizes + scale (that would double-scale).
            return pinwheel_rects(self._anchor, 1.0, card_w, card_h, emblem, gap)
        base = CardMetrics(1.0)
        return pinwheel_rects(
            self._anchor, self._scale,
            _BASE_CARD_W, base.card_min_h, base.emblem, _GROUP_GAP,
        )

    def _shape_path(self, state: SurfaceState, rect: QRect):
        """Surface-local QPainterPath for *state* at *rect* (w x h at origin).

        Cards: the card-body path (rounded rect minus the concave pinwheel bite)
        at the scaled radii from CardMetrics.  Emblem: a disc over its rect.
        Coordinates are surface-local (origin 0,0) - the backend converts to
        device pixels via dpr.
        """
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainterPath
        w, h = rect.width(), rect.height()
        if state.is_emblem:
            path = QPainterPath()
            path.addEllipse(QRectF(0.0, 0.0, float(w), float(h)))
            return path
        # Lazy-import the Qt-heavy card layout only when actually shaping a card.
        from tabs.multitoon._compact_layout import _card_body_path
        from utils.overlay.card_metrics import CardMetrics
        m = CardMetrics(self._scale)
        cutout = SLOT_CUTOUTS[state.surface_id]
        return _card_body_path(w, h, cutout, m.card_radius, m.cutout_r)

    def _apply_input_region(self, state, surface, rect) -> None:
        """Apply the click-through input region for one surface.

        Emblem: the disc path (unchanged). Card: the controls-only region (Model B)
        - the union of its control-widget rects, so the body is click-through and
        only the buttons block clicks. Falls back to the legacy body path when no
        card_provider is present (the orchestration stub tests) or when the
        provider yields no rects (defensive).
        """
        dpr = surface.devicePixelRatio()
        if state.is_emblem:
            surface.apply_shape(self._shape_path(state, rect), dpr)
            return
        rects_base = []
        if self._card_provider is not None:
            try:
                rects_base = self._card_provider.control_rects(state.surface_id)
            except Exception:
                # Best-effort, matching the overlay's never-crash-on-shape ethos:
                # a misbehaving provider must not break enter()/reshape, so fall
                # back to the body path (a slightly more click-blocking card) rather
                # than raise. Silent by module convention (the overlay has no logger).
                rects_base = []
        if rects_base:
            from utils.overlay.region import controls_region
            surface.apply_input_region(controls_region(rects_base, self._scale, dpr))
        else:
            surface.apply_shape(self._shape_path(state, rect), dpr)

    def _raise_emblem(self) -> None:
        """Raise the emblem above the four cards (spec section 8 z-order).

        The emblem is the last surface (it is the last element of _states), so
        raising the final surface puts it on top of the cluster.
        """
        if self._surfaces:
            self._surfaces[-1].raise_()

    # ------------------------------------------------------------------
    # Hover-peek detection (transparent mode)
    # ------------------------------------------------------------------
    def on_ghost_event(self, payload) -> None:
        """Receive a click-sync ghost_pointer_event payload (motion/press/release).

        Converts the points to logical coords once (so the dim and the click pass
        agree, and the dim is correct on HiDPI), feeds the hover-peek store, and
        on a "press" - when ghost-control-clicks are enabled and the overlay is
        active - fires the matching card controls."""
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

    def on_ghost_clear(self) -> None:
        """Receive click-sync ghost_clear: drop all ghost points."""
        self._peek_store.clear()

    def _ghost_payload_to_logical(self, payload):
        """Convert a ghost payload's native points to logical coords, fetching the
        screen list once for the whole batch (motion fires at refresh rate).

        A malformed payload - bad top-level shape, or a point that will not unpack
        - is returned UNCHANGED as a best-effort degrade, not a correctness path;
        the well-formed service payloads always convert. (A returned-unconverted
        payload is not itself re-sanitised downstream, so this only stays safe
        because the service never emits one.)"""
        from PySide6.QtGui import QGuiApplication
        try:
            kind, items = payload
            screens = QGuiApplication.screens()
            conv = [(slot, *emitted_to_logical(x, y, screens))
                    for slot, x, y in items]
        except (TypeError, ValueError):
            return payload
        return (kind, conv)

    def _ghost_click_enabled(self) -> bool:
        """True when ghost cursors may press card controls: a settings object,
        an active overlay, a card provider, and both settings on."""
        if self._settings is None or not self._active or self._card_provider is None:
            return False
        return bool(self._settings.get(GHOST_CURSORS_ENABLED, True)
                    and self._settings.get(GHOST_CURSORS_CONTROL_CARDS, True))

    def _ghost_click_pass(self, items) -> None:
        """Map each (already-logical) ghost point to a card control and deliver a
        synthetic click there. Indexed by surface_id, matching control_rects.

        Defensive per card: on_ghost_event is a QUEUED Qt slot (the service emits
        ghost events from its capture thread, marshalled to the GUI thread), so a
        misbehaving provider must not raise into Qt's dispatch. Isolating each card
        means one bad surface drops only its own click, never the whole press -
        matching the overlay's never-crash-on-shape convention."""
        cards = []
        for st, su in self._card_surfaces():
            try:
                g = su.geometry()
                rects = self._card_provider.control_rects(st.surface_id)
                rect_tuples = [(r.x(), r.y(), r.width(), r.height()) for r in rects]
                cards.append((st.surface_id,
                              (g.x(), g.y(), g.width(), g.height()),
                              rect_tuples))
            except Exception:
                continue
        points = [(x, y) for _slot, x, y in items]
        for surface_id, x, y in control_hits(points, cards, self._scale):
            try:
                self._card_provider.deliver_ghost_click(surface_id, x, y)
            except Exception:
                continue

    def _card_surfaces(self):
        """[(state, surface), ...] for the four card surfaces (emblem excluded)."""
        return [(st, su) for st, su in zip(self._states, self._surfaces)
                if not st.is_emblem]

    def _target_visible_cells(self) -> set:
        """The card surface_ids that should be mapped right now: the provider's
        occupied cells, or all four when there is no occupancy-aware provider
        (the Task 3.2 stub-orchestration flow keeps showing all cards)."""
        provider = self._card_provider
        fn = getattr(provider, "occupied_cells", None) if provider is not None else None
        if fn is None:
            return {0, 1, 2, 3}
        try:
            return set(fn())
        except Exception:
            return {0, 1, 2, 3}

    def _visible_card_surfaces(self):
        """[(state, surface), ...] for the MAPPED card surfaces only. Consumed by
        the hover-peek + ghost-click passes (Task 6) so hidden cards are skipped."""
        return [(st, su) for st, su in self._card_surfaces()
                if st.surface_id in self._visible_cells]

    def _on_occupancy_changed(self) -> None:
        """Provider occupancy nudge: schedule ONE deferred reconcile. Deferring to
        the next event-loop tick is load-bearing - it lets both window-manager
        routing handlers (ids then cell-assignment) settle first, so the reconcile
        reads the final occupancy (no one-frame wrong picture)."""
        if not self._active or self._occupancy_pending:
            return
        self._occupancy_pending = True
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._run_occupancy_reconcile)

    def _run_occupancy_reconcile(self) -> None:
        if not self._occupancy_pending:
            return
        self._occupancy_pending = False
        if not self._active:
            return
        self._reconcile_visibility()

    def _reconcile_visibility(self) -> None:
        """Map the occupied card surfaces, unmap the rest; refresh the glow. The
        emblem is never touched. Re-reads occupancy fresh, so it is correct
        whenever it runs. No-op when framed."""
        if not self._active:
            return
        target = self._target_visible_cells()
        rects = self._compute_rects()
        for st, su in self._card_surfaces():
            want = st.surface_id in target
            have = st.surface_id in self._visible_cells
            # Per-card isolation: this runs from a queued Qt slot with no
            # fail-closed wrapper (unlike enter()), so one bad surface must not
            # abort the reconcile for the others (matches _ghost_click_pass).
            try:
                if want and not have:
                    self._show_card_surface(st, su, rects[self._key(st)])
                elif have and not want:
                    self._hide_card_surface(st, su)
            except Exception:
                pass
        self._refresh_glow(rects)
        self._raise_emblem()

    def _show_card_surface(self, state, surface, rect) -> None:
        """Map a previously-hidden card: geometry -> initial state -> show ->
        input region -> reassert topmost (shape only takes effect after show)."""
        surface.set_overlay_geometry(rect)
        self._safe_call(surface, "prepare_initial_state")
        surface.show()
        # Track as visible the instant it is mapped, BEFORE the (best-effort)
        # input region: if _apply_input_region raises, the surface is still shown,
        # so _visible_cells must agree (else the next reconcile re-shows it).
        self._visible_cells.add(state.surface_id)
        self._apply_input_region(state, surface, rect)
        try:
            self._backend.set_above(surface)
        except Exception:
            pass
        try:
            self._backend.set_non_activating(surface)
        except Exception:
            pass

    def _hide_card_surface(self, state, surface) -> None:
        """Unmap an emptied card and clear any lingering hover-peek dim so it
        returns clean if it is shown again."""
        self._safe_call(surface, "hide")
        self._visible_cells.discard(state.surface_id)
        sid = state.surface_id
        if 0 <= sid < len(self._peek_progress) and self._peek_progress[sid] != 0.0:
            self._peek_progress[sid] = 0.0
            try:
                surface.set_content_opacity(1.0)
            except Exception:
                pass
            if self._card_provider is not None:
                try:
                    self._card_provider.set_shell_extra_opacity(sid, 1.0, 1.0)
                except Exception:
                    pass

    def _refresh_glow(self, rects) -> None:
        """Reconcile the glow to the current visible set: tear it down when no
        cards are visible, build it when missing but cards are visible, else
        re-place it. Called by the visibility reconcile."""
        if self._card_provider is None:
            return
        if not self._visible_cells:
            self._teardown_glow()
        elif self._glow_surface is None:
            self._build_glow(rects)
        else:
            self._place_glow(rects)

    PEEK_CONTENT_OPACITY = 0.80    # whole card (controls, text, portrait ring) on hover
    PEEK_BODY_OPACITY = 0.65       # card BACKGROUND fill on hover (more see-through)
    PEEK_PORTRAIT_OPACITY = 0.25   # circular portrait (frame + toon image) on hover
    _PEEK_FADE_STEP = 0.25         # progress per 30ms tick -> ~120ms full fade

    def _peek_tick(self, real_point) -> None:
        """One detection pass: union real cursor + ghost points, apply per card.

        real_point: (x, y) global, or None when the OS pointer is unavailable.
        """
        if not self._active:
            return
        cards = self._card_surfaces()
        rects = []
        for _st, su in cards:
            g = su.geometry()
            rects.append((g.x(), g.y(), g.width(), g.height()))
        points = list(self._peek_store.points())
        if real_point is not None:
            points.append(real_point)
        peeking = peeking_indices(points, rects)
        for i, (st, su) in enumerate(cards):
            active = i in peeking
            # Direct call (not getattr): every card surface is a CardSurface with
            # set_peek, so a missing method is a real bug that should fail loudly.
            su.set_peek(active)
            self._apply_peek_fade(st.surface_id, su, active)

    def _peek_opacities(self, progress):
        """Three-tier (content, body_extra, portrait_extra) opacities for a peek
        *progress* 0..1.

        content: whole-card opacity (1.0 -> CONTENT). body_extra / portrait_extra:
        multiplicative factors on the background fill / toon image so their net
        opacity (content * factor) reaches BODY / PORTRAIT at full peek."""
        content = 1.0 - (1.0 - self.PEEK_CONTENT_OPACITY) * progress
        body_factor = self.PEEK_BODY_OPACITY / self.PEEK_CONTENT_OPACITY
        body_extra = 1.0 - (1.0 - body_factor) * progress
        portrait_factor = self.PEEK_PORTRAIT_OPACITY / self.PEEK_CONTENT_OPACITY
        portrait_extra = 1.0 - (1.0 - portrait_factor) * progress
        return content, body_extra, portrait_extra

    def _apply_peek_fade(self, surface_id, surface, active) -> None:
        """Step one card's hover-peek progress toward its target and apply the
        opacity tiers: the whole card via the surface (content), the background
        fill + toon image a bit further via the card provider. No-op for the extra
        tiers without a provider (stub tests still drive the surface tier)."""
        target = 1.0 if active else 0.0
        cur = self._peek_progress[surface_id]
        if cur < target:
            cur = min(target, cur + self._PEEK_FADE_STEP)
        elif cur > target:
            cur = max(target, cur - self._PEEK_FADE_STEP)
        else:
            return  # already settled; nothing to repaint
        self._peek_progress[surface_id] = cur
        content, body_extra, portrait_extra = self._peek_opacities(cur)
        try:
            surface.set_content_opacity(content)
        except Exception:
            pass
        if self._card_provider is not None:
            try:
                self._card_provider.set_shell_extra_opacity(
                    surface_id, body_extra, portrait_extra)
            except Exception:
                pass

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
        if self._peek_timer is not None:
            self._peek_timer.stop()
        self._peek_store.clear()
        # Restore every card to fully opaque (both tiers) so a borrowed card never
        # returns to the framed grid stuck dim.
        card_surfaces = self._card_surfaces() if self._surfaces else []
        for st, su in card_surfaces:
            if self._peek_progress[st.surface_id] != 0.0:
                try:
                    su.set_content_opacity(1.0)
                except Exception:
                    pass
                if self._card_provider is not None:
                    try:
                        self._card_provider.set_shell_extra_opacity(st.surface_id, 1.0, 1.0)
                    except Exception:
                        pass
        self._peek_progress = [0.0, 0.0, 0.0, 0.0]

    # ------------------------------------------------------------------
    # Topmost re-assert + reshape-on-screen-change (Task 7.1)
    # ------------------------------------------------------------------
    def _reassert_topmost(self) -> None:
        """Re-apply ABOVE + SKIP_TASKBAR/PAGER on every surface + the
        emblem-above-cards z-order. Best-effort - some WMs drop ABOVE when another
        window takes focus, and KWin can re-add the surfaces to the taskbar right
        after the main window minimizes (they briefly become the app's only managed
        windows), so both hints are re-asserted on enter, after a scale change, and
        on a low-frequency timer."""
        for surface in self._surfaces:
            try:
                self._backend.set_above(surface)
            except Exception:
                pass
            try:
                self._backend.set_non_activating(surface)  # re-hide from taskbar/pager
            except Exception:
                pass
        self._reassert_glow()  # keep the glow above games but below the cards
        self._raise_emblem()

    def _start_above_timer(self) -> None:
        from PySide6.QtCore import QTimer
        if self._above_timer is None:
            self._above_timer = QTimer()
            self._above_timer.setInterval(1500)  # ~1.5s; droppable if the WM holds ABOVE
            self._above_timer.timeout.connect(self._reassert_topmost)
        self._above_timer.start()

    def _stop_above_timer(self) -> None:
        if self._above_timer is not None:
            self._above_timer.stop()

    def _connect_screen_change(self) -> None:
        """Reshape on a monitor/DPI change (spec section 14): when the emblem
        surface's native window moves to another screen, re-place + re-shape the
        cluster (its device-pixel ratio - and thus the shape - may change)."""
        if not self._surfaces:
            return
        get_handle = getattr(self._surfaces[-1], "windowHandle", None)  # emblem surface
        if get_handle is None:
            return
        try:
            wh = get_handle()
            if wh is not None:
                wh.screenChanged.connect(self._on_screen_changed)
        except Exception:
            pass

    def _on_screen_changed(self, *_args) -> None:
        if self._active:
            self.update_shapes()

    def _place_all(self, reshape: bool) -> None:
        """Re-position (and optionally re-shape) every live surface, emblem last.

        reshape=False (move): geometry only, no shape recompute (size unchanged).
        reshape=True (scale): geometry + shape, since the sizes change.
        """
        rects = self._compute_rects()
        self._place_glow(rects)  # keep the glow under the cluster on move/scale
        for state, surface in zip(self._states, self._surfaces):
            rect = rects[self._key(state)]
            surface.set_overlay_geometry(rect)
            if reshape:
                self._apply_input_region(state, surface, rect)
        self._raise_emblem()

    # ------------------------------------------------------------------
    # Accent glow behind the cluster (parity with the framed _GlowLayer)
    # ------------------------------------------------------------------
    def _cluster_bbox(self, rects, cells):
        """Bounding QRect of the given card cells' rects in screen coords."""
        from PySide6.QtCore import QRect
        cards = [rects[i] for i in sorted(cells)]
        left = min(r.x() for r in cards)
        top = min(r.y() for r in cards)
        right = max(r.x() + r.width() for r in cards)
        bottom = max(r.y() + r.height() for r in cards)
        return QRect(left, top, right - left, bottom - top)

    def _build_glow(self, rects) -> None:
        """Create + show the click-through accent-glow surface BELOW the cards.

        Mirrors the framed tab's _GlowLayer (a soft halo of the card shapes that
        fills the central hole so the emblem nests). Best-effort: a glow failure
        must NEVER break the enter transaction, so it self-tears-down on error and
        the cluster proceeds without the (decorative) glow."""
        if self._card_provider is None:
            return  # stub/orchestration path has no real cards to glow
        if not self._visible_cells:
            return  # nothing to glow yet (emblem-only)
        try:
            from tabs.multitoon._compact_layout import _GlowLayer
            from utils.overlay.surface import OverlaySurface
            from PySide6.QtGui import QPainterPath
            surface = OverlaySurface(backend=self._backend)
            self._glow_surface = surface
            self._glow_widget = _GlowLayer()
            surface.host(self._glow_widget)
            self._place_glow(rects)
            surface.prepare_initial_state()
            surface.show()
            surface.lower()  # bottom of the overlay group (below the cards)
            # Fully click-through: an EMPTY input region so clicks in the glow's
            # gaps reach the games. The glow only PAINTS; it must never grab input.
            surface.apply_shape(QPainterPath(), surface.devicePixelRatio())
        except Exception:
            self._teardown_glow()

    def _place_glow(self, rects) -> None:
        """Position the glow surface to the VISIBLE cluster bbox and feed the
        _GlowLayer each visible card's body spec at bbox-relative coords. Pure
        geometry + specs: it does NOT show/raise/lower the surface, so it is cheap
        to call on every drag/zoom tick (via _place_all). Mapping + z-order are
        owned by _build_glow (initial) and _reassert_glow (ongoing); teardown when
        nothing is visible is owned by _refresh_glow. No-op without a glow surface
        or with no visible cards."""
        if self._glow_surface is None or self._glow_widget is None:
            return
        visible = sorted(self._visible_cells)
        if not visible:
            return  # _refresh_glow tears the glow down when nothing is visible
        from PySide6.QtGui import QColor
        from utils.overlay.card_metrics import CardMetrics
        m = CardMetrics(self._scale)
        bbox = self._cluster_bbox(rects, visible)
        try:
            accents = self._card_provider.card_accents()
        except Exception:
            accents = []
        default = QColor("#555555")
        specs = []
        for slot in visible:
            r = rects[slot]
            specs.append({
                "x": r.x() - bbox.x(), "y": r.y() - bbox.y(),
                "w": r.width(), "h": r.height(),
                "cutout": SLOT_CUTOUTS[slot],
                "accent": accents[slot] if slot < len(accents) else default,
                "radius": m.card_radius, "cutout_r": m.cutout_r,
            })
        self._glow_widget.set_blur(m.glow_blur)
        self._glow_widget.set_cards(specs)
        self._glow_surface.set_overlay_geometry(bbox)

    def _reassert_glow(self) -> None:
        """Keep the glow above the games but below the cards (best-effort)."""
        if self._glow_surface is None:
            return
        try:
            self._backend.set_above(self._glow_surface)
        except Exception:
            pass
        try:
            self._glow_surface.lower()
        except Exception:
            pass

    def _teardown_glow(self) -> None:
        """Destroy the OWNED glow surface (+ its _GlowLayer child). Unlike the
        borrowed cards, the glow widget is ours, so the surface deletes it."""
        surface = self._glow_surface
        self._glow_surface = None
        self._glow_widget = None
        if surface is not None:
            self._safe_call(surface, "hide")
            self._safe_call(surface, "deleteLater")

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------
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

    def _teardown(self, surfaces: list) -> None:
        """Hide, release, then destroy each surface.

        release() MUST precede close()/deleteLater(): an OverlaySurface never
        OWNS its hosted widget, but Qt parent-child destruction would delete a
        still-hosted child, so the widget must be released first (the ownership
        contract documented in surface.py).

        If release() FAILS for a surface, do NOT close()/deleteLater() it: the
        borrowed card may still be hosted, and destroying the surface would
        delete the real card (matters once Task 4.1b hosts live cards). We RETAIN
        a reference to that surface in self._orphans so Python GC cannot destroy
        the parentless surface (and its child) once the caller drops _surfaces -
        leaking the surface keeps the card ALIVE (recoverable) instead of deleted
        (fatal to the MultitoonTab widget registry). Teardown continues to the
        rest (each surface is independent / exception-isolated).
        """
        for surface in surfaces:
            self._safe_call(surface, "hide")
            if self._safe_call(surface, "release"):
                self._safe_call(surface, "close")
                self._safe_call(surface, "deleteLater")
            else:
                self._orphans.append(surface)

    # ------------------------------------------------------------------
    # Widget reparent (Task 4.1b): card_provider seam
    # ------------------------------------------------------------------
    def _provider_widget(self, state: SurfaceState):
        """The REAL tab widget the surface for *state* will host.

        Cards (slots 0-3) host the grid-managed card QFrame; the emblem state
        hosts the manually-positioned emblem widget. Pulled from the provider
        via small accessors so this module never reaches into _CompactLayout's
        private _cells / _emblem internals.
        """
        provider = self._card_provider
        if state.is_emblem:
            return provider.emblem_widget()
        return provider.slot_widget(state.surface_id)

    def _restore_widgets(self, captured: list) -> None:
        """Return every borrowed widget in *captured* to its EXACT tab slot.

        release-before-restore: detach the widget from its surface FIRST, then
        ``restore_slot`` it back into the tab (the card to its grid cell, the
        emblem manual + raised). This is the critical fail-closed / leave step:
        a borrowed LIVE card must never be deleted or stranded in a dead
        surface. Each widget is independent (exception-isolated) so one failure
        cannot orphan the rest; a surface whose release() raises is left for
        _teardown to retain in _orphans (its widget may still be hosted, so the
        surface must NOT be destroyed) rather than risk deleting the card.

        No-op when *captured* is empty (the card_provider=None path), so the
        Task 3.2 stub-surface flow is unchanged.
        """
        provider = self._card_provider
        if provider is None:
            return
        for surface, record in captured:
            # If release() raises the widget is still hosted: skip restore and
            # let _teardown orphan the surface (deleting it would delete the
            # borrowed card). restore_slot below re-parents the widget itself,
            # so even a stale (host-raised) parent is corrected.
            if not self._safe_call(surface, "release"):
                continue
            try:
                provider.restore_slot(record)
            except Exception:
                # Defensive only: grid.removeWidget/addWidget (card) and
                # setParent/setGeometry (emblem) do not raise for a valid widget.
                # If one ever did, the widget was already released (parentless);
                # as a LAST RESORT re-attach it to its captured parent so the
                # borrowed card is returned to the tab's widget tree (never left
                # floating/parentless, never deleted) - the next populate/relayout
                # re-places it. Exact-cell can't be guaranteed when restore_slot
                # itself (the exact-cell mechanism) is the failing step.
                try:
                    if record.parent is not None:
                        record.widget.setParent(record.parent)
                        # setParent hides the widget (Qt hides on reparent), so
                        # restore its intrinsic visibility too - else the card is
                        # back in the tab tree but stuck hidden.
                        record.widget.setVisible(record.visible)
                except Exception:
                    pass

    def _reset_provider_scale(self) -> None:
        """Reset the tab's framed (scale-1.0) metrics after the cards return.

        Spec section 5: leave (and the fail-closed unwind) restore NORMAL
        metrics. This is a no-op for the framed look today, but matters once
        Task 4.2 scales the hosted cards - the cards must come back at 1.0.
        Guarded + lazy-imported so a metrics failure cannot abort the rest of
        the restore/teardown. No-op when there is no provider.
        """
        provider = self._card_provider
        if provider is None:
            return
        try:
            from utils.overlay.card_metrics import CardMetrics
            provider.apply_metrics(CardMetrics(1.0))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
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

    def enter(self) -> bool:
        """Build + show + shape the cluster, then minimize the main window.

        Transactional / fail-closed: returns True on success (now transparent),
        or False if any step raised - in which case every surface created so far
        is torn down, the main window is restored if it was minimized, and the
        controller stays Framed.  No-op (returns True) if already active.
        """
        if self._active:
            return True
        # Defensive: no debounced recompute can be outstanding while framed, but
        # clear the gate so a stray queued tick from a prior session is inert.
        self._recompute_pending = False
        # Task 6.1: load the persisted group scale + anchor, clamping the anchor to
        # a currently-visible monitor (recenter if the saved monitor is gone).
        loaded_anchor = self._load_persisted_state()
        # Only apply the default-anchor fallback when NO saved anchor was restored;
        # a saved (0,0) is a valid origin anchor, not the no-QApplication sentinel.
        if not loaded_anchor and self._anchor == (0, 0):
            self._anchor = self._default_anchor()
        created: list = []
        # (surface, SlotRecord) per reparented widget; stays empty in the
        # card_provider=None path (no reparent), so that flow is unchanged.
        captured: list = []
        provider = self._card_provider
        minimized = False
        try:
            # Scale the emblem BEFORE computing rects, so emblem_size() in
            # Normalize the cards to the canonical 1.0 layout BEFORE measuring the
            # base size + hosting. The framed/window mode does not reliably leave the
            # cards at 1.0 (it can lay them out at a window-fit metric), so without
            # this the FIRST enter shows content sized for the wrong metric -
            # overlapping the portrait / clipping the card edge - until an exit
            # (which resets to 1.0) and re-enter. apply_metrics(1.0) here makes every
            # enter start from the same 1.0 state the leave-reset leaves behind. The
            # per-card view transform (set below) then scales the 1.0 card as a unit.
            if provider is not None:
                from utils.overlay.card_metrics import CardMetrics
                provider.apply_metrics(CardMetrics(1.0))
                provider.scale_emblem(self._scale)
            # Decide which quadrants are occupied (have a detected window) BEFORE
            # building the glow + surfaces, so empty card surfaces are never shown
            # (no map/unmap flash) and the glow spans only visible cards.
            self._visible_cells = set(self._target_visible_cells())
            rects = self._compute_rects()
            # Build the glow surface FIRST so it shows below the cards (it paints
            # the soft halo that fills the central hole). Best-effort: it never
            # raises into this transaction.
            self._build_glow(rects)
            for state in self._states:
                surface = self._surface_factory(state)
                created.append(surface)
                rect = rects[self._key(state)]
                # Provider mode: reparent the REAL card/emblem into this surface.
                # Capture its exact tab placement BEFORE host() so a leave() or a
                # fail-closed unwind can restore it byte-for-byte; record the
                # (surface, record) pair so restoration knows which surface holds
                # which widget.  Cards are hosted through a ScaledCardView proxy
                # at the framed 1.0 base size; the view transform (set_card_scale)
                # is the sole zoom mechanism, so cards never re-layout and never
                # float. The emblem is hosted plain (it scales via scale_emblem).
                if provider is not None:
                    widget = self._provider_widget(state)
                    captured.append((surface, provider.capture_slot(widget)))
                    if state.is_emblem:
                        surface.host(widget)                       # emblem: plain
                    else:
                        base = provider.overlay_base_card_size()
                        surface.host(widget, base_size=base)       # card: proxied
                        # Re-place the card's manual body/status-dot to the new fixed
                        # size (the parent layout's resizeEvent never fires for a
                        # reparented cell), else content spills past the painted body.
                        provider.overlay_relayout_card(widget)
                        surface.set_card_scale(self._scale)
                surface.set_overlay_geometry(rect)
                # Set the EWMH initial state (above + skip-taskbar/pager) as a
                # property BEFORE mapping, so the WM honors it from the first frame
                # and the surface never flashes into the taskbar.
                surface.prepare_initial_state()
                # show() MUST precede apply_shape(): the X11 ShapeInput needs a
                # realized native handle (winId), which show() provides; shaping a
                # not-yet-shown window is a silent no-op (see
                # OverlaySurface.apply_shape). This order matches the live-validated
                # Phase 0 spike (Group.apply: show then reshape). The shape affects
                # INPUT only and the window is translucent, so there is no visual
                # flash; do NOT reorder to shape-before-show (it would never apply).
                # Emblem always maps; a card maps only if its quadrant is occupied.
                # Empty cards stay hosted-but-unmapped (truly invisible). Shaping a
                # not-yet-shown surface is a silent no-op, so it is gated with show.
                if state.is_emblem or state.surface_id in self._visible_cells:
                    surface.show()
                    self._apply_input_region(state, surface, rect)
                # Snapshot the live anchor/scale into the state (v2 detach reads it).
                state.anchor = self._anchor
                state.scale = self._scale
            # The emblem (last created) sits ABOVE the cards.
            created[-1].raise_()
            # Spec: MINIMIZE (never hide) so the single taskbar icon stays.
            # Set the flag BEFORE the call so a showMinimized() failure (or any
            # future step added here) still triggers the except-path restore.
            minimized = True
            self._window.showMinimized()
        except Exception:
            # Fail-closed: return every borrowed widget to its EXACT tab slot
            # FIRST (release from the surface, then restore_slot) so a live card
            # is never deleted or stranded; THEN destroy the now-empty surfaces;
            # reset framed (scale-1.0) metrics; restore the window. Stay Framed.
            self._restore_widgets(captured)
            self._teardown(created)
            self._teardown_glow()
            self._reset_provider_scale()
            if minimized:
                self._safe_call(self._window, "showNormal")
            self._surfaces = []
            self._captured = []
            self._visible_cells = set()   # framed invariant (mirror leave())
            self._active = False
            return False
        self._surfaces = created
        self._captured = captured
        self._active = True
        # Task 7.1: re-assert ABOVE + z-order now, keep it best-effort via a
        # low-frequency timer, and reshape if a surface changes monitor/DPI.
        self._reassert_topmost()
        self._start_above_timer()
        self._start_peek_timer()
        self._connect_screen_change()
        # The main window was just minimized, which can make KWin re-add the
        # surfaces to the taskbar a few ms later. Re-assert skip-taskbar/above once
        # the minimize settles (the 1.5s timer would also heal it, but with a
        # visible taskbar flicker), so the single-icon state is reached promptly.
        self._schedule_post_minimize_reassert()
        self._emit_active_changed()   # self._active is True here
        return True

    def _schedule_post_minimize_reassert(self) -> None:
        from PySide6.QtCore import QTimer
        for delay in (150, 600):
            QTimer.singleShot(delay, self._reassert_if_active)

    def _reassert_if_active(self) -> None:
        if self._active:
            self._reassert_topmost()

    def leave(self) -> None:
        """Restore the borrowed cards/emblem to the tab, tear down the cluster,
        and restore the main window.  No-op if framed.

        With a card_provider: first return each borrowed widget to its EXACT tab
        slot (release-before-restore), then destroy the now-empty surfaces, then
        reset framed (scale-1.0) metrics; finally showNormal + clear state. With
        no provider (Task 3.2 stub flow) the restore/reset steps are no-ops, so
        leave() is just teardown + restore as before.
        """
        if not self._active:
            return
        # Cancel any in-progress group drag (the emblem window is going away).
        self._end_drag()
        # Stop the topmost re-assert timer (no surfaces to keep above once framed).
        self._stop_above_timer()
        self._stop_peek_timer()
        # Persist the FINAL group anchor + scale before teardown (the remembered
        # overlay position, restored on the next enter).
        self.flush_pending_save()
        # Cancel any debounced recompute: leave() resets to framed (scale-1.0)
        # metrics, so a queued recompute at the old scale must NOT fire (its
        # _run_pending_recompute will find the flag cleared + _active False and
        # no-op - never recompute after teardown).
        self._recompute_pending = False
        self._restore_widgets(self._captured)
        self._teardown(self._surfaces)
        self._teardown_glow()  # destroy the owned glow surface (+ its _GlowLayer)
        self._reset_provider_scale()
        self._surfaces = []
        self._captured = []
        self._visible_cells = set()
        self._occupancy_pending = False
        self._safe_call(self._window, "showNormal")
        self._active = False
        self._emit_active_changed()   # self._active is False here

    def toggle(self) -> bool:
        """Leave if active, else enter.  Returns the resulting active state."""
        if self._active:
            self.leave()
        else:
            self.enter()
        return self._active

    # ------------------------------------------------------------------
    # Emblem gesture wiring (Task 5.1)
    # ------------------------------------------------------------------
    def connect_emblem(self, emblem) -> None:
        """Wire an _Emblem's gesture signals to this controller. The connections
        are live in BOTH modes; the controller methods are mode-aware (toggle
        flips; move/scale no-op when framed):

          * toggle_requested (click)        -> toggle()  (enter/leave)
          * move_requested (drag start)     -> begin_group_drag()
          * resize_scrolled (dwell wheel)   -> set_scale_by_notches(notches)

        Idempotent and re-bindable: re-connecting the SAME emblem is a no-op (Qt
        permits duplicate connections, which would double-fire), and connecting a
        NEW emblem first drops the previous emblem's connections.
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
        tracks the GLOBAL cursor itself (a ~16ms poll) and shifts the group anchor
        until the left button is released. No-op when framed; re-entrant-safe
        (restarts from the current cursor)."""
        if not self._active:
            return
        from PySide6.QtGui import QCursor
        from PySide6.QtCore import QTimer
        self._drag_last = QCursor.pos()
        if self._drag_timer is None:
            self._drag_timer = QTimer()
            self._drag_timer.setInterval(16)
            self._drag_timer.timeout.connect(self._drag_step)
        self._drag_timer.start()

    def _drag_step(self) -> None:
        """One poll of the manual drag: move the group by the cursor delta, or end
        the drag when the left button is released / the cluster left transparent."""
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

    def set_scale_by_notches(self, notches: int) -> None:
        """Step the cluster scale by *notches*. No-op if not active.

        The scale value updates SYNCHRONOUSLY (so any read of self._scale right
        after this call is current). The recompute differs by mode:

        * provider present (unit-scaling): scale the emblem disc (scale_emblem) +
          set each card's view transform (set_card_scale) + re-geometry/reshape the
          windows to base*scale. The cards do NOT re-layout (the transform zooms the
          fixed 1.0 card), so this is cheaper than the old apply_metrics path, but it
          is still DEBOUNCED: a burst of notches in one event-loop tick collapses
          into ONE recompute at the FINAL scale (scheduled on the next tick via
          _schedule_recompute; force it now with flush_pending_recompute()).
        * provider None (Task 3.2 stub flow): no content rescale; re-geometry +
          reshape SYNCHRONOUSLY at the placeholder sizes, exactly as before.

        Unlike enter()/leave(), the re-layout mutators (this, move_group,
        update_shapes) are NOT transactional - they are idempotent re-layouts, so
        a mid-loop failure self-corrects on the next call. The gesture handler
        (Task 5.1) should tolerate a stray exception rather than expect a rollback.
        """
        if not self._active:
            return
        self._scale = step_scale(self._scale, notches)
        for state in self._states:
            state.scale = self._scale
        self._clamp_anchor()  # emblem size changed -> re-clamp the parked anchor
        self._schedule_save()  # persist the new scale (debounced)
        if self._card_provider is None:
            # Task 3.2 path: no apply_metrics, placeholder geometry, synchronous.
            self._place_all(reshape=True)
            self._reassert_topmost()  # re-assert ABOVE after a scale change
            return
        # Provider path: coalesce the expensive recompute to one per tick.
        self._schedule_recompute()

    def _schedule_recompute(self) -> None:
        """Coalesce a burst of scale changes into ONE recompute on the next
        event-loop tick. The pending flag is the single gate: a second call while
        one is already pending does nothing (so N rapid notches -> one recompute
        at the final scale). flush_pending_recompute()/leave() clear the flag, so
        an already-queued tick that finds it cleared simply no-ops."""
        if self._recompute_pending:
            return
        self._recompute_pending = True
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._run_pending_recompute)

    def _run_pending_recompute(self) -> None:
        """Event-loop callback for the debounced recompute. No-op if the pending
        flag was already cleared (flushed/cancelled) or the cluster was torn down
        before the tick fired (never recompute after teardown)."""
        if not self._recompute_pending:
            return
        self._recompute_pending = False
        if not self._active:
            return
        self._recompute_now()

    def flush_pending_recompute(self) -> None:
        """Run any pending debounced recompute synchronously NOW. Used by tests
        today; the Task 5.1 gesture handler may force a sync settle. (leave()
        CANCELS a pending recompute rather than flushing it.) Safe no-op when
        nothing is pending or the cluster is framed."""
        if not self._recompute_pending:
            return
        self._recompute_pending = False
        if self._active:
            self._recompute_now()

    def _recompute_now(self) -> None:
        """Re-place every surface at the current scale: scale ONLY the emblem via
        metrics (single widget, never floats) and scale each card via its view
        transform (the card stays at framed 1.0, so it never re-layouts/floats)."""
        provider = self._card_provider
        if provider is not None:
            provider.scale_emblem(self._scale)
        for surface in self._surfaces:
            setter = getattr(surface, "set_card_scale", None)
            if setter is not None:
                setter(self._scale)
        self._place_all(reshape=True)
        self._reassert_topmost()  # re-assert ABOVE after a scale change (interaction)

    def _clamp_anchor(self) -> None:
        """Clamp self._anchor to the parking envelope at the current scale and
        mirror it onto every surface state.

        Envelope = the union of the connected screens, each inflated by
        emblem_size/4, so the leading quarter of the emblem stays on-screen while
        the rest of the cluster may slide off any edge. Pure-helper-backed, so it
        is a safe identity with no screens. Centralizes the anchor->state mirror so
        the CLAMPED value is what gets placed and persisted.
        """
        from utils.overlay.persistence import clamp_anchor_to_envelope
        from utils.overlay.card_metrics import CardMetrics
        margin = int(CardMetrics(self._scale).emblem // 4)
        self._anchor = clamp_anchor_to_envelope(self._anchor, self._screens(), margin)
        for state in self._states:
            state.anchor = self._anchor

    def move_group(self, dx: int, dy: int) -> None:
        """Shift the cluster anchor by (dx, dy), clamp it to the parking envelope,
        and re-position all surfaces. Sizes are unchanged, so no reshape is needed
        (emblem is re-raised). No-op if not active."""
        if not self._active:
            return
        cx, cy = self._anchor
        self._anchor = (cx + dx, cy + dy)
        self._clamp_anchor()  # parking envelope + anchor->state mirror
        self._place_all(reshape=False)
        self._schedule_save()  # persist the new anchor (debounced)

    def update_shapes(self) -> None:
        """Re-place AND re-shape every surface (DPI / screen / monitor change,
        Task 7.1). A full re-layout (geometry + shape): a monitor change can move
        a surface as well as change its device-pixel ratio, so geometry must be
        re-applied too, not just the shape. No-op if not active."""
        if not self._active:
            return
        self._place_all(reshape=True)
        self._reassert_topmost()  # screen/DPI change can also drop ABOVE
