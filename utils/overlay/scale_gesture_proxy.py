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

from PySide6.QtCore import (
    Qt,
    QRect,
    QPoint,
    Signal,
    QObject,
    QTimer,
    QVariantAnimation,
    QEasingCurve,
)
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget

from utils.overlay.scale import step_scale

_SETTLE_IDLE_MS = 130
_ANIM_MS = 140


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


class ScaleGestureProxy(QObject):
    """Begin/notch/settle/cancel state machine for the overlay scale gesture.

    The coordinator drives a scale gesture against an injected ``host`` adapter
    so the begin/notch/settle/cancel logic is unit-testable without real
    windows. It OWNS the target scale and steps it from ITSELF (via
    :func:`utils.overlay.scale.step_scale`), never from the live/animated host
    scale: ``begin(1)`` followed by ``notch(1)`` is two discrete ``step_scale``
    applications, not one. The host scale is only the smoothly animated value
    shown to the user; the target is the authoritative accumulator.
    """

    def __init__(self, host):
        super().__init__()
        self._host = host
        self._proxy = None
        self._anim = None
        self._idle = None
        self.active = False
        self.target = float(getattr(host, "scale", 1.0))

    # -- public API -------------------------------------------------------- #
    def begin(self, notches):
        host = self._host
        if self.active:
            # A begin while a gesture is live is just another notch; never
            # re-snapshot or rebuild the proxy mid-gesture.
            self.notch(notches)
            return
        start = float(host.scale)
        self.target = step_scale(host.scale, notches)
        snapshot, bbox, anchor, wheel, dpr = host.snapshot()
        self._proxy = host.make_proxy(snapshot, bbox, anchor, start, wheel)
        self._proxy.wheel_notch.connect(self.notch)
        self.active = True
        host.hide_scaling_windows()
        self._start_anim(start)
        self._restart_idle()

    def notch(self, notches):
        if not self.active:
            self.begin(notches)
            return
        # Accumulate off the coordinator's OWN target, not the animated host
        # scale, so rapid notches sum cleanly.
        self.target = step_scale(self.target, notches)
        self._start_anim(float(self._host.scale))
        self._restart_idle()

    def cancel(self):
        # Teardown WITHOUT settling: drop the proxy and the real windows stay
        # wherever they were (no commit, no persist).
        self._stop_timers()
        self._drop_proxy()
        self.active = False

    # -- internals --------------------------------------------------------- #
    def _start_anim(self, start):
        if self._anim is not None:
            self._anim.stop()
        anim = QVariantAnimation()
        anim.setDuration(_ANIM_MS)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(float(start))
        anim.setEndValue(float(self.target))
        anim.valueChanged.connect(self._on_frame)
        self._anim = anim
        anim.start()

    def _on_frame(self, value):
        self._host.scale = float(value)
        if self._proxy is not None:
            self._proxy.set_scale(float(value))

    def _restart_idle(self):
        if self._idle is None:
            self._idle = QTimer()
            self._idle.setSingleShot(True)
            self._idle.setInterval(_SETTLE_IDLE_MS)
            self._idle.timeout.connect(self._settle)
        self._idle.start()

    def _settle(self):
        if not self.active:
            return
        self._stop_timers()
        host = self._host
        host.scale = float(self.target)
        host.settle_placement()
        host.show_scaling_windows()
        self._drop_proxy()
        self.active = False
        host.on_gesture_end()

    def _stop_timers(self):
        if self._anim is not None:
            self._anim.stop()
        if self._idle is not None:
            self._idle.stop()

    def _drop_proxy(self):
        if self._proxy is not None:
            self._proxy.hide()
            self._proxy.deleteLater()
            self._proxy = None
