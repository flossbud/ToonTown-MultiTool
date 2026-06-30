"""Single always-mapped translucent window that hosts the borrowed cluster.

``ClusterSurface`` is the one override-redirect, frameless, always-on-top,
non-activating top-level that will host the borrowed ``_grid_host`` cluster
subtree (the four cards + emblem) as a single rigid window, instead of one
surface per card. It subclasses ``OverlaySurface`` to inherit all of the
window flags (Qt.Window | Frameless | StaysOnTop | DoesNotAcceptFocus |
X11BypassWindowManagerHint), ``WA_TranslucentBackground``, the non-activating
attributes, the ``host()``/``release()`` plumbing, and the backend hookup.

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

    Everything except the source-clear ``paintEvent`` is inherited from
    ``OverlaySurface`` (flags, attributes, host()/release(), backend hookup).
    """

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
