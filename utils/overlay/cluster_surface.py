"""Single always-mapped translucent window that hosts the borrowed cluster.

``ClusterSurface`` is the one frameless, always-on-top, non-activating
top-level that will host the borrowed ``_grid_host`` cluster subtree (the four
cards + emblem) as a single rigid window, instead of one surface per card. It
subclasses ``OverlaySurface`` to inherit all of the window flags (Qt.Window |
Frameless | StaysOnTop | DoesNotAcceptFocus; MANAGED keep-above by default,
override-redirect only under TTMT_OVERLAY_UNMANAGED), ``WA_TranslucentBackground``,
the non-activating attributes, the ``host()``/``release()`` plumbing, and the
backend hookup.

It adds exactly ONE thing: a mandatory full-rect transparent SOURCE-CLEAR
``paintEvent``.

WHY (load-bearing): a single translucent ARGB top-level can retain stale or
opaque native-backing pixels on resize/partial-update, exactly like the
``EmblemSurface`` bug. ``OverlaySurface`` "paints nothing", so the window's
unpainted regions are never written to the native backing - on a resize the
WM/compositor can flash a stale opaque square for one frame. ClusterSurface
MUST source-clear its whole rect to transparent on every paint so the cluster
window can never flash a stale square; the borrowed cluster subtree paints its
own opaque card bodies over this transparent fill as usual. See the proven
``EmblemSurface.paintEvent`` in ``utils/overlay/surface.py``.
"""
from __future__ import annotations

from utils.overlay.surface import OverlaySurface


class ClusterSurface(OverlaySurface):
    """The single translucent cluster window with a mandatory source-clear.

    Everything except the source-clear ``paintEvent`` and the transform-scaled
    hosting seam is inherited from ``OverlaySurface`` (flags, attributes,
    host()/release(), backend hookup).

    Transform hosting: ``host_scaled()`` embeds the borrowed ``_grid_host``
    through a :class:`~utils.overlay.scaled_cluster_view.ScaledClusterView`
    (whole-cluster QGraphicsScene proxy pivoted on the emblem center) instead of
    a plain reparent, so ``set_cluster_scale()`` zooms the live cluster with ONE
    uniform transform - no widget re-layout and no window geometry change per
    notch. The plain ``host()`` path stays untouched for the subclasses
    (``RadialSurface``/``PanelSurface`` host their own widgets full-bleed);
    ``release()`` dispatches to whichever path is active.
    """

    def __init__(self, backend=None) -> None:
        super().__init__(backend=backend)
        self._cluster_view = None  # ScaledClusterView holding the borrowed host
        self._awaiting_first_paint = False  # opacity-staged until the first buffer
        self._content_blanked = False  # opacity-0 while an EMPTY persistent surface

    def host_scaled(self, widget, emblem_center, pivot, envelope_size,
                    initial_scale: float = 1.0) -> None:
        """Host the borrowed cluster THROUGH a ScaledClusterView (transform zoom).

        ``emblem_center``/``pivot``/``envelope_size`` come from
        ``cluster_geometry.envelope_for``; ``initial_scale`` is the restored
        cluster scale to render at immediately (no animation). The caller fixes
        the host to its 1.0 size before this so the proxy geometry is stable.
        """
        if widget is None:
            return
        from utils.overlay.scaled_cluster_view import ScaledClusterView
        if self._cluster_view is not None or self._hosted is not None:
            self.release()
        view = ScaledClusterView()
        view.host_cluster(widget, emblem_center, pivot, envelope_size)
        view.set_scale(float(initial_scale))
        self._cluster_view = view
        self._layout.addWidget(view)

    def set_cluster_scale(self, scale: float) -> None:
        """Drive the whole-cluster transform zoom. No-op before host_scaled()."""
        if self._cluster_view is not None:
            self._cluster_view.set_scale(scale)

    def cluster_scale(self) -> float:
        """The scale the view currently RENDERS at (the animated visual value)."""
        if self._cluster_view is not None:
            return self._cluster_view.scale()
        return 1.0

    def release(self):  # type: ignore[override]
        """Release whichever hosting path is active without deleting the widget.

        Scaled path: un-proxy the borrowed host, clear the fixed-size constraint
        host_scaled()'s caller imposed (min==max), and destroy the view (owned
        by this surface; the host was borrowed). Plain path (RadialSurface /
        PanelSurface / a pre-transform host()): defer to OverlaySurface.
        """
        view = self._cluster_view
        if view is None:
            return super().release()
        host = view.release_cluster()
        # Clear the fixed size imposed for proxying: setFixedSize sets min==max,
        # and restore_cluster_host re-applies the CAPTURED constraints afterwards;
        # clearing here keeps the host sane even if that restore never runs.
        if host is not None:
            host.setMinimumSize(0, 0)
            host.setMaximumSize(16777215, 16777215)
        self._layout.removeWidget(view)
        self._cluster_view = None
        view.deleteLater()  # the view is owned by the surface; the host was borrowed
        return host

    def prepare_initial_state(self) -> None:
        """Base pre-map EWMH state, plus ``_NET_WM_WINDOW_OPACITY = 0``.

        A mapped window with NO buffer composites as an OPAQUE BLACK rect on
        KWin/XWayland, and KWin force-places OSD-typed windows mid-screen
        regardless of the requested geometry (both probed 2026-07-02). At a
        startup float launch the first buffer - the event loop's first paint -
        can be SECONDS after enter() maps this window, so the black square is
        user-visible. Opacity 0 makes it invisible by construction whatever
        KWin composites; ``paintEvent`` lifts the stage only after this
        window's own first real paint (paint-before-opacity ordering)."""
        super().prepare_initial_state()
        try:
            self._backend.set_window_opacity(self, 0.0)
            self._awaiting_first_paint = True
        except Exception:
            pass

    def _lift_first_paint_stage(self) -> None:
        """Runs one event-loop turn after the first paint: a synchronous
        repaint (the window is exposed now, so this flushes a CURRENT buffer)
        and only then the opacity write - the taskbar rep's proven
        anti-stale-frame ordering. A content-blanked surface defers: the blank
        owns opacity until its own unblank path (host -> paint -> opacity)."""
        if self._content_blanked:
            return
        try:
            self.repaint()
            self._backend.set_window_opacity(self, 1.0)
        except Exception:
            pass

    def set_content_blanked(self, blanked: bool) -> None:
        """Blank (opacity 0) while this persistent surface hosts NO content.

        An empty mapped window is only invisible while its buffer is fully
        transparent - but a RESIZE exposes a fresh region with NO buffer,
        which KWin/XWayland composites as an OPAQUE BLACK band until the next
        paint flush lands (probed 2026-07-02, re-probed under a stalled event
        loop). During a scale burst the GUI thread is saturated by the
        whole-cluster repaint, so the closed panel's per-notch ``emblem*6``
        resize showed exactly that band live (the J-shaped black rectangle).
        Opacity 0 makes ANY closed-state geometry change invisible by
        construction, whatever KWin composites and however late the paint
        lands; the open paths lift it only AFTER content is hosted and
        painted (paint-before-opacity, the taskbar rep's proven ordering).
        Idempotent."""
        blanked = bool(blanked)
        if blanked == self._content_blanked:
            return
        self._content_blanked = blanked
        try:
            from utils.overlay.backend import overlay_trace
            overlay_trace(f"{type(self).__name__}: content-blank -> {blanked}")
        except Exception:
            pass
        if not blanked:
            # Paint-before-opacity, enforced HERE so no caller can reorder it:
            # flush a buffer that covers the full current canvas before the
            # window becomes visible.
            try:
                self.repaint()
            except Exception:
                pass
        try:
            self._backend.set_window_opacity(self, 0.0 if blanked else 1.0)
        except Exception:
            pass

    def closeEvent(self, ev):
        # Taskbar-identity mode (Windows: this window IS the app's taskbar
        # entry): a spontaneous close (taskbar Close, preview X) means QUIT
        # THE APP - refuse the close itself and route to the owner's callback
        # DEFERRED, the taskbar representative's proven pattern (never
        # re-enter the WM close handshake synchronously). Without the
        # callback the base refusal stands: a stray WM close must never
        # destroy an overlay window.
        cb = getattr(self, "_on_spontaneous_close", None)
        if ev.spontaneous() and cb is not None:
            ev.ignore()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, cb)
            return
        # Honour the base's spontaneous-close refusal first; only release the
        # borrowed host when the close is actually going through, so Qt's
        # destruction cascade can never delete the proxied live cluster.
        super().closeEvent(ev)
        if ev.isAccepted() and self._cluster_view is not None:
            self.release()

    def changeEvent(self, ev):
        super().changeEvent(ev)
        from PySide6.QtCore import QEvent
        if (getattr(self, "_bounce_minimize", False)
                and ev.type() == QEvent.WindowStateChange
                and self.isMinimized()):
            # Taskbar-identity mode: a taskbar-button minimize would freeze
            # the float UI into a stranded thumbnail; bounce back DEFERRED so
            # the WM's state change settles first (the rep's pattern), with
            # the context-object form so a destroyed surface cancels it.
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self, self.showNormal)

    def paintEvent(self, ev) -> None:
        """SOURCE-clear the whole window to transparent on every paint.

        The base OverlaySurface paints nothing, so Qt's partial-update flushes
        only the hosted cluster regions; the rest of this single ARGB top-level
        is never written to the native backing and can retain stale/opaque
        content - which the compositor would flash as a dark square for one
        frame on resize. An explicit full-rect transparent source-clear forces
        every pixel into the backing each repaint, so resizes stay clean. The
        hosted cluster subtree paints its opaque card bodies over this fill.
        """
        from PySide6.QtGui import QPainter, QColor
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), QColor(0, 0, 0, 0))
        p.end()
        if self._awaiting_first_paint:
            # First real paint: a buffer exists now. Lift the pre-map opacity
            # stage NEXT loop turn (after this paint's flush), never inside
            # the paint pass. Context-object form so a destroyed surface
            # cancels the timer instead of firing into a dead C++ object.
            self._awaiting_first_paint = False
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self, self._lift_first_paint_stage)


class RadialSurface(ClusterSurface):
    """Source-cleared top-level for the radial menu widget.

    Even in the single-window cluster design the radial menu
    (``utils.overlay.radial_menu.RadialMenuWidget``) stays a SEPARATE
    overlay top-level: it must sit ABOVE the cluster window AND be
    click-accepting (the cluster window is click-through), neither of which a
    child-of-the-cluster widget can do. Like the cluster window it is a single
    translucent ARGB top-level that resizes as the menu scales, so it needs the
    exact SAME mandatory full-rect transparent source-clear to avoid a stale /
    opaque backing flash on resize.

    ``RadialSurface`` inherits that source-clear ``paintEvent`` (the only thing
    ``ClusterSurface`` adds over ``OverlaySurface``) and nothing else, so the two
    windows' source-clear can never drift apart. Unlike the cluster window it hosts
    its OWN widget (the menu it was created with, not a borrowed subtree), so the
    controller tears it down with a plain ``hide()`` + ``deleteLater()`` - the menu
    dies with the surface, which is the intent.

    OSD type (_KDE_NET_WM_WINDOW_TYPE_ON_SCREEN_DISPLAY): the only window type
    that satisfies all three stacking/animation constraints at once - probed on
    KWin 6.7.1, 2026-07-02:
      (a) its layer is strictly above the dock layer and KWin's INTERNAL
          click-raise (workspace.raiseWindow) cannot cross layers, so an emblem
          press can never lift the cluster - and its internal radial dim -
          above this ring (NOTIFICATION/CRITICAL also pass this, DOCK variants
          all fail: keep-above does not elevate docks, and WM_TRANSIENT_FOR is
          not honored against internal raises);
      (b) it is NOT matched by the slidingnotifications effect (kwin source:
          isNotification() || isCriticalNotification() only), whose per-move
          displace animations QUEUE while a window is invisible and replay on
          the first content paint - the "ring travels from the old position"
          bug that killed NOTIFICATION and CRITICAL_NOTIFICATION typing;
      (c) it keeps the fit-to-desktop move-clamp exemption the ring needs to
          track the emblem near screen edges.
    Trade-off (accepted): the OSD layer sits above fullscreen windows, so an
    OPEN ring could cover system UI like the screenshot picker; the persistent
    cluster (dock) stays below such UI, and the ring is transient user-invoked
    chrome.
    """

    WM_WINDOW_TYPE = "_KDE_NET_WM_WINDOW_TYPE_ON_SCREEN_DISPLAY"


class PanelSurface(ClusterSurface):
    """Source-cleared top-level for the portable Settings panel.

    Like the radial menu, the portable Settings panel is a SEPARATE
    overlay top-level rather than a child of the click-through cluster
    window: it hosts an arbitrary CALLER-PROVIDED widget (the floating SettingsTab
    container) and must be fully CLICK-ACCEPTING and float ABOVE the cluster window
    + emblem + radial, none of which a child-of-the-cluster widget can do. Being a
    single translucent ARGB top-level that the controller sizes to a generous
    ``emblem*6`` canvas, it needs the exact SAME mandatory full-rect transparent
    source-clear as the cluster + radial windows so it can never flash a stale /
    opaque square on show/resize (the EmblemSurface bug).

    ``PanelSurface`` inherits that source-clear ``paintEvent`` (the only thing
    ``ClusterSurface`` adds over ``OverlaySurface``) and nothing else, so all three
    windows' source-clear can never drift apart. Like the radial it hosts its OWN
    (borrowed-from-the-caller) widget, so the controller tears it down with a plain
    ``hide()`` + ``deleteLater()`` AFTER running the caller's ``on_close`` (which
    reparents the hosted content back out first).

    OSD type like the radial (see ``RadialSurface`` for the full rationale and
    the probe record): the OSD layer guarantees the panel stacks above the
    DOCK cluster through any KWin internal click-raise. Panel-vs-radial are
    same-layer siblings; their relative order is click-to-front UX, not a
    correctness invariant - the hard invariant (both above the cluster, so
    the internal dim can never cover either) holds by layer.
    """

    WM_WINDOW_TYPE = "_KDE_NET_WM_WINDOW_TYPE_ON_SCREEN_DISPLAY"
