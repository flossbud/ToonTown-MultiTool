"""Override-redirect proxy window for the overlay scale gesture.

During the scale gesture the live overlay surfaces are frozen and a single
composited snapshot (see :mod:`utils.overlay.scale_snapshot`) is shown instead.
``ScaleProxyWindow`` is that snapshot's host: a parentless, override-redirect,
translucent, non-activating top-level window that paints the snapshot scaled
about a fixed anchor (the emblem center) and forwards wheel notches to the
gesture coordinator.

Painting and stacking are inherently LIVE-only behaviors - the offscreen Qt
platform cannot composite translucent surfaces or honor override-redirect
stacking - so the unit tests only assert the pure, observable contract:
the stored snapshot/scale, that ``set_scale`` updates the live scale and
requests a repaint, and that ``wheelEvent`` emits the notch count. The visual
correctness of the scaled paint is validated live, not offscreen.
"""

from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget


class ScaleProxyWindow(QWidget):
    """A frozen-snapshot proxy window that zooms about an anchor.

    The window lives in screen coordinates: ``bbox`` describes where the
    snapshot sits at ``base_scale`` and ``anchor`` is the (fixed) emblem center.
    Scaling is applied about the anchor by the factor
    ``self._scale / self._base_scale``.
    """

    wheel_notch = Signal(int)

    def __init__(
        self, snapshot: QImage, bbox: QRect, anchor: QPoint, base_scale: float
    ):
        super().__init__(None)
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
            | Qt.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        self._snapshot = snapshot
        self._bbox = QRect(bbox)
        self._anchor = QPoint(anchor)
        self._base_scale = float(base_scale)
        self._scale = float(base_scale)

    def set_scale(self, scale: float):
        """Update the live scale and request an atomic repaint.

        One window paints the whole cluster, so a single ``update()`` repaints
        every card in unison (no per-surface tearing).
        """
        self._scale = float(scale)
        self.update()

    def paintEvent(self, ev):
        f = self._scale / self._base_scale if self._base_scale else 1.0
        pos = self.pos()
        ax = self._anchor.x() - pos.x()
        ay = self._anchor.y() - pos.y()
        bx = self._bbox.topLeft().x() - pos.x()
        by = self._bbox.topLeft().y() - pos.y()

        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.translate(ax, ay)
            p.scale(f, f)
            p.translate(-ax, -ay)
            p.drawImage(QPoint(bx, by), self._snapshot)
        finally:
            p.end()

    def wheelEvent(self, ev):
        # Match the emblem's sign-based convention (one notch per event) so the
        # gesture behaves identically whether the emblem or the proxy receives the
        # wheel, and so high-res/trackpad deltas are not floor-divided to nothing.
        dy = ev.angleDelta().y()
        if dy:
            self.wheel_notch.emit(1 if dy > 0 else -1)
        ev.accept()

    # During the freeze the proxy swallows all non-wheel pointer events so the
    # frozen snapshot cannot be dragged/clicked through to the live surfaces.
    def mousePressEvent(self, ev):
        ev.accept()

    def mouseReleaseEvent(self, ev):
        ev.accept()

    def mouseMoveEvent(self, ev):
        ev.accept()
