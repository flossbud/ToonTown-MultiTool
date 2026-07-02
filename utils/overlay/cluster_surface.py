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

    def closeEvent(self, ev):
        # Honour the base's spontaneous-close refusal first; only release the
        # borrowed host when the close is actually going through, so Qt's
        # destruction cascade can never delete the proxied live cluster.
        super().closeEvent(ev)
        if ev.isAccepted() and self._cluster_view is not None:
            self.release()

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

    Stacking above the cluster is enforced by WM_TRANSIENT_FOR (the controller
    sets this surface transient for the cluster window pre-map): KWin keeps a
    transient above its parent in every restack, so a click-raise on the
    cluster (any emblem press) can never lift the cluster - and its internal
    radial dim - above this ring. The type stays DOCK like the cluster: the
    earlier NOTIFICATION layering made the ``slidingnotifications`` effect
    paint the ring traveling in from a stale position (its moves accumulate
    invisibly while empty; the first content paint replayed them), and docks
    are not animated by it. See ``X11OverlayBackend.set_transient_for``.
    """


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

    Stacking: DOCK type like the radial, transient-for the RADIAL surface (a
    chain - panel above radial above cluster - so no sibling-order policy can
    ever invert panel vs radial either; a click on the radial's spokes raises
    the panel along with it, transients ride their parent's raise). See
    ``RadialSurface`` for why the NOTIFICATION layering was abandoned.
    """
