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

Controller integration note (Task 3.2 / 4.2 - NOT implemented here)
----------------------------------------------------------------------
The controller (Task 3.2+) will reconcile each surface's final QRect with the
card's ACTUAL scaled sizeHint, which may differ from card_w*scale by rounding.
pinwheel_rects() provides the OFFSET geometry only; the controller owns the
size-reconcile step. Specifically: CardMetrics uses ``round(base * scale)``
while this function uses ``int(base * scale)`` (matching the spike), so for some
scales (e.g. 0.8, 1.3) the sizes differ by 1px. The controller resolves this by
reading ``sizeHint()`` from the real card widget (Task 4.2), NOT by recomputing
sizes here. The controller sources card_w/card_h from the live card's sizeHint
and the inter-corner gap (spike GAP=24) + emblem (CardMetrics.emblem=156) as the
base inputs to this function.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from PySide6.QtCore import QRect

from utils.overlay.backend import get_overlay_backend
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
# Base (scale-1.0) card WIDTH fed to pinwheel_rects.  This is a PLACEHOLDER:
# Task 4.2 replaces it with the real card sizeHint() read from the live
# MultitoonTab card widget (see the "Controller integration note" in the module
# docstring above) - the card's true width is not a fixed constant once its
# chrome reflows, so the controller will source card_w from the widget, not from
# this constant.  card_h + emblem come from CardMetrics(1.0); only card_w lacks a
# pure source until 4.2.
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
                 card_provider=None):
        self._window = window
        self._backend = backend if backend is not None else get_overlay_backend()
        # Stored for Task 6.1 (anchor/scale persistence); unused in this task.
        self._settings = settings
        self._surface_factory = surface_factory or self._default_surface_factory
        # The _CompactLayout (Task 4.1b). When present, enter() reparents the REAL
        # pinwheel cards + emblem into the surfaces (and leave()/fail-closed
        # restores them to the tab); when None, enter() builds EMPTY surfaces
        # exactly as the Task 3.2 orchestration tests expect (no reparent). The
        # provider must expose slot_widget(int) / emblem_widget() / capture_slot(w)
        # -> record / restore_slot(record) / apply_metrics(CardMetrics).
        self._card_provider = card_provider

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
    # Geometry + shape helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _key(state: SurfaceState):
        """pinwheel_rects key for *state*: "emblem" or the card slot int."""
        return "emblem" if state.is_emblem else state.surface_id

    def _compute_rects(self) -> "PinwheelRects":
        """Pinwheel rects at the current anchor + scale.

        card_h + emblem come from CardMetrics(1.0); card_w is the placeholder
        _BASE_CARD_W (Task 4.2 reconciliation).  Scale is applied INSIDE
        pinwheel_rects, so the BASE (scale-1.0) dimensions are passed here.
        """
        # CardMetrics is pure, but lazy-import it (per the module docstring) so
        # the pure geometry at the top never pulls anything at module load.
        from utils.overlay.card_metrics import CardMetrics
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

    def _raise_emblem(self) -> None:
        """Raise the emblem above the four cards (spec section 8 z-order).

        The emblem is the last surface (it is the last element of _states), so
        raising the final surface puts it on top of the cluster.
        """
        if self._surfaces:
            self._surfaces[-1].raise_()

    def _place_all(self, reshape: bool) -> None:
        """Re-position (and optionally re-shape) every live surface, emblem last.

        reshape=False (move): geometry only, no shape recompute (size unchanged).
        reshape=True (scale): geometry + shape, since the sizes change.
        """
        rects = self._compute_rects()
        for state, surface in zip(self._states, self._surfaces):
            rect = rects[self._key(state)]
            surface.set_overlay_geometry(rect)
            if reshape:
                surface.apply_shape(self._shape_path(state, rect), surface.devicePixelRatio())
        self._raise_emblem()

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
    def enter(self) -> bool:
        """Build + show + shape the cluster, then minimize the main window.

        Transactional / fail-closed: returns True on success (now transparent),
        or False if any step raised - in which case every surface created so far
        is torn down, the main window is restored if it was minimized, and the
        controller stays Framed.  No-op (returns True) if already active.
        """
        if self._active:
            return True
        # Defensive: if the anchor is still the no-QApplication sentinel, recompute
        # now that a QApplication certainly exists (Task 6.1 persistence may also
        # have set it).
        if self._anchor == (0, 0):
            self._anchor = self._default_anchor()
        created: list = []
        # (surface, SlotRecord) per reparented widget; stays empty in the
        # card_provider=None path (no reparent), so that flow is unchanged.
        captured: list = []
        provider = self._card_provider
        minimized = False
        try:
            # Inside the try so a CardMetrics import/build failure is fail-closed too.
            rects = self._compute_rects()
            for state in self._states:
                surface = self._surface_factory(state)
                created.append(surface)
                rect = rects[self._key(state)]
                # Provider mode: reparent the REAL card/emblem into this surface.
                # Capture its exact tab placement BEFORE host() so a leave() or a
                # fail-closed unwind can restore it byte-for-byte; record the
                # (surface, record) pair so restoration knows which surface holds
                # which widget. Reparent at the current scale (1.0); Task 4.2 owns
                # the per-surface scale recompute.
                if provider is not None:
                    widget = self._provider_widget(state)
                    captured.append((surface, provider.capture_slot(widget)))
                    surface.host(widget)
                surface.set_overlay_geometry(rect)
                # show() MUST precede apply_shape(): the X11 ShapeInput needs a
                # realized native handle (winId), which show() provides; shaping a
                # not-yet-shown window is a silent no-op (see
                # OverlaySurface.apply_shape). This order matches the live-validated
                # Phase 0 spike (Group.apply: show then reshape). The shape affects
                # INPUT only and the window is translucent, so there is no visual
                # flash; do NOT reorder to shape-before-show (it would never apply).
                surface.show()
                surface.apply_shape(self._shape_path(state, rect), surface.devicePixelRatio())
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
            self._reset_provider_scale()
            if minimized:
                self._safe_call(self._window, "showNormal")
            self._surfaces = []
            self._captured = []
            self._active = False
            return False
        self._surfaces = created
        self._captured = captured
        self._active = True
        return True

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
        self._restore_widgets(self._captured)
        self._teardown(self._surfaces)
        self._reset_provider_scale()
        self._surfaces = []
        self._captured = []
        self._safe_call(self._window, "showNormal")
        self._active = False

    def toggle(self) -> bool:
        """Leave if active, else enter.  Returns the resulting active state."""
        if self._active:
            self.leave()
        else:
            self.enter()
        return self._active

    def set_scale_by_notches(self, notches: int) -> None:
        """Step the cluster scale by *notches* and re-geometry + re-shape all.
        No-op if not active.

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
        self._place_all(reshape=True)

    def move_group(self, dx: int, dy: int) -> None:
        """Shift the cluster anchor by (dx, dy) and re-position all surfaces.
        Sizes are unchanged, so no reshape is needed (emblem is re-raised).
        No-op if not active."""
        if not self._active:
            return
        cx, cy = self._anchor
        self._anchor = (cx + dx, cy + dy)
        for state in self._states:
            state.anchor = self._anchor
        self._place_all(reshape=False)

    def update_shapes(self) -> None:
        """Re-place AND re-shape every surface (DPI / screen / monitor change,
        Task 7.1). A full re-layout (geometry + shape): a monitor change can move
        a surface as well as change its device-pixel ratio, so geometry must be
        re-applied too, not just the shape. No-op if not active."""
        if not self._active:
            return
        self._place_all(reshape=True)
