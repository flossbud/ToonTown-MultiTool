"""Custom window chrome for the frameless main window: resize-edge math,
control-button glyphs, the traffic-light control buttons, and the
WindowChromeController that wires drag / resize / window-state behavior.

Move and resize delegate to the compositor via QWindow.startSystemMove() /
startSystemResize(), which is the only reliable cross-platform path
(X11, Wayland, Windows) and preserves native snap/tiling. We never hand-roll
move()/resize() — that breaks on Wayland."""

from PySide6.QtCore import Qt, QObject, QEvent, QPointF, QRectF, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QFontMetricsF
from PySide6.QtWidgets import QAbstractButton, QApplication, QWidget
from utils.widgets.window_chrome_style import (
    DOT_DIAMETER, TRAFFIC, glyph_pixel_size,
    hover_targets, brighten, inactive_grey,
)
import utils.motion as motion


def resize_edge_for_pos(x: int, y: int, w: int, h: int, margin: int = 6):
    """Return the Qt.Edge (or OR'd corner edges) for a point near the window
    frame, or None if the point is in the interior. Pure function for testing."""
    left = x <= margin
    right = x >= w - margin
    top = y <= margin
    bottom = y >= h - margin
    edges = Qt.Edge(0)
    if left:
        edges |= Qt.Edge.LeftEdge
    if right:
        edges |= Qt.Edge.RightEdge
    if top:
        edges |= Qt.Edge.TopEdge
    if bottom:
        edges |= Qt.Edge.BottomEdge
    # PySide6 6.10: Qt.Edge is a flag type; int() fails — use .value instead
    return edges if edges.value else None


def maximize_glyph(is_maximized: bool) -> str:
    """Glyph for the maximize/restore control."""
    return "❐" if is_maximized else "□"  # restore / maximize


class _TrafficDot(QAbstractButton):
    """A 22x22 button (comfortable hit area) that paints a centered 16px
    colored circle with a subtle tinted glyph. No QGraphicsEffect (avoids the
    paint-device conflict that effects cause with custom paintEvent)."""

    _VISUAL_DIAMETER = DOT_DIAMETER
    _HIT = 22

    def __init__(self, dot_color: str, glyph: str, glyph_color: str,
                 accessible_name: str, parent=None):
        super().__init__(parent)
        self._dot_color = QColor(dot_color)
        self._glyph = glyph
        self._glyph_color = QColor(glyph_color)
        # interaction state
        self._dot_hovered = False
        self._pressed = False
        self._cluster_hovered = False   # driven by the controller (later task)
        self._window_focused = True     # driven by the controller (later task)
        self._inactive_dot = QColor("#5a5d63")
        self._inactive_glyph = QColor("#33353a")
        # animated paint values
        self._glyph_opacity = 0.0       # hidden at rest; revealed on cluster hover
        self._dot_scale = 1.0
        self._brightness = 1.0
        self._glyph_anim = QPropertyAnimation(self, b"glyph_opacity", self)
        self._glyph_anim.setDuration(150); self._glyph_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._scale_anim = QPropertyAnimation(self, b"dot_scale", self)
        self._scale_anim.setDuration(130); self._scale_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._bright_anim = QPropertyAnimation(self, b"brightness", self)
        self._bright_anim.setDuration(130); self._bright_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.setFixedSize(self._HIT, self._HIT)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAccessibleName(accessible_name)
        self.setToolTip(accessible_name)

    def set_glyph(self, glyph: str):
        self._glyph = glyph
        self.update()

    def _glyph_pixel_size(self) -> int:
        """Glyph size derived from this dot's diameter (testable seam so the
        scaling can't silently regress to a hardcoded value)."""
        return glyph_pixel_size(self._VISUAL_DIAMETER)

    # --- animated paint properties (read by paintEvent) ---
    def _get_glyph_opacity(self): return self._glyph_opacity
    def _set_glyph_opacity(self, v): self._glyph_opacity = v; self.update()
    glyph_opacity = Property(float, _get_glyph_opacity, _set_glyph_opacity)

    def _get_dot_scale(self): return self._dot_scale
    def _set_dot_scale(self, v): self._dot_scale = v; self.update()
    dot_scale = Property(float, _get_dot_scale, _set_dot_scale)

    def _get_brightness(self): return self._brightness
    def _set_brightness(self, v): self._brightness = v; self.update()
    brightness = Property(float, _get_brightness, _set_brightness)

    def _set_target(self, anim, prop: bytes, value: float):
        """Animate `prop` to `value`, or jump instantly under reduced motion.
        Always stops any running animation first; no-op if already targeting."""
        name = bytes(prop).decode()
        if abs(getattr(self, name) - value) < 1e-6 and anim.state() != anim.State.Running:
            return
        anim.stop()
        if motion.is_reduced():
            setattr(self, name, value)
            self.update()
            return
        anim.setStartValue(getattr(self, name))
        anim.setEndValue(value)
        anim.start()

    def _glyph_opacity_rest(self) -> float:
        return 0.0  # glyphs hidden at rest; revealed on cluster hover

    def set_cluster_hovered(self, v: bool):
        self._cluster_hovered = bool(v)
        self._recompute_targets()

    def _recompute_targets(self):
        scale, bright = hover_targets(self._pressed, self._dot_hovered)
        self._set_target(self._scale_anim, b"dot_scale", scale)
        self._set_target(self._bright_anim, b"brightness", bright)
        self._set_target(self._glyph_anim, b"glyph_opacity",
                         1.0 if self._cluster_hovered else self._glyph_opacity_rest())

    def _set_dot_hovered(self, v: bool):
        self._dot_hovered = bool(v)
        self._recompute_targets()

    def _set_pressed(self, v: bool):
        self._pressed = bool(v)
        self._recompute_targets()

    def enterEvent(self, event):
        self._set_dot_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_dot_hovered(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._set_pressed(True)

    def mouseReleaseEvent(self, event):
        # Clear pressed state BEFORE super(): super() emits `clicked`, whose slot
        # (e.g. close) can synchronously delete this widget — touching self after
        # that would hit a dead Qt wrapper. Qt's internal pressed state is
        # separate, so `clicked` still fires.
        self._set_pressed(False)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        dot = self._dot_color if self._window_focused else self._inactive_dot
        fill = QColor(brighten(dot.name(), self._brightness))
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        p.save()
        p.translate(cx, cy); p.scale(self._dot_scale, self._dot_scale); p.translate(-cx, -cy)
        d = self._VISUAL_DIAMETER
        off = (self._HIT - d) / 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawEllipse(QRectF(off, off, d, d))
        if self._glyph and self._glyph_opacity > 0.001:
            p.setOpacity(self._glyph_opacity)
            gcol = self._glyph_color if self._window_focused else self._inactive_glyph
            p.setPen(gcol)
            f = p.font()
            f.setPixelSize(self._glyph_pixel_size())
            f.setBold(True)
            p.setFont(f)
            # The maximize/restore box glyphs (□/❐) are not vertically centered
            # within their font line box — they sit low — so Qt.AlignCenter
            # renders them below the dot's center. Center those on their tight
            # INK bounds instead. The minus and × already center correctly via
            # AlignCenter, so leave them on the simpler path.
            if self._glyph in (maximize_glyph(False), maximize_glyph(True)):
                br = QFontMetricsF(f).tightBoundingRect(self._glyph)
                gx = (self.width() - br.width()) / 2.0 - br.left()
                gy = (self.height() - br.height()) / 2.0 - br.top()
                p.drawText(QPointF(gx, gy), self._glyph)
            else:
                p.drawText(self.rect(), Qt.AlignCenter, self._glyph)
        p.restore()
        p.end()


class _TrafficCluster(QWidget):
    """Transparent fixed-size holder for the three control dots. Owns hover so
    moving the cursor between dots never flickers the cluster-hover state."""

    _GAP = 8

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self.setFixedSize(3 * _TrafficDot._HIT + 2 * self._GAP, _TrafficDot._HIT)

    def enterEvent(self, event):
        self._controller.set_cluster_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._controller.set_cluster_hovered(False)
        super().leaveEvent(event)


class WindowChromeController(QObject):
    """Owns the custom window controls + drag/resize/state for a frameless
    main window. Construct only when custom chrome is active (the
    use_system_title_bar setting is off)."""

    _RESIZE_MARGIN = 6

    def __init__(self, window, header, parent=None):
        super().__init__(parent or window)
        self._win = window
        self._header = header
        self._is_maximized = bool(window.isMaximized())
        self._logged_move_fail = False
        self._logged_resize_fail = False

        from PySide6.QtWidgets import QHBoxLayout
        self._cluster = _TrafficCluster(self, header)
        self.btn_min = _TrafficDot(TRAFFIC["min"][0], "−", TRAFFIC["min"][1], "Minimize", self._cluster)
        self.btn_max = _TrafficDot(TRAFFIC["max"][0], maximize_glyph(self._is_maximized), TRAFFIC["max"][1], "Maximize", self._cluster)
        self.btn_close = _TrafficDot(TRAFFIC["close"][0], "×", TRAFFIC["close"][1], "Close", self._cluster)
        self.btn_min.setObjectName("win_ctl_min")
        self.btn_max.setObjectName("win_ctl_max")
        self.btn_close.setObjectName("win_ctl_close")
        _lay = QHBoxLayout(self._cluster)
        _lay.setContentsMargins(0, 0, 0, 0); _lay.setSpacing(_TrafficCluster._GAP)
        _lay.addWidget(self.btn_min); _lay.addWidget(self.btn_max); _lay.addWidget(self.btn_close)

        self.btn_min.clicked.connect(self._win.showMinimized)
        self.btn_max.clicked.connect(self._toggle_max_restore)
        self.btn_close.clicked.connect(self._win.close)

        # App-level filter so we see presses delivered to child widgets too
        # (a QMainWindow is fully covered by its central widget, so a
        # window-level filter would never receive edge-resize presses).
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _toggle_max_restore(self):
        if self._is_maximized:
            self._win.showNormal()
        else:
            self._win.showMaximized()

    def set_cluster_hovered(self, v: bool):
        for b in (self.btn_min, self.btn_max, self.btn_close):
            b.set_cluster_hovered(v)

    def _sync_window_state(self, is_maximized: bool):
        self._is_maximized = is_maximized
        self.btn_max.set_glyph(maximize_glyph(is_maximized))

    def reposition(self):
        """Pin the control cluster to the header's top-right corner."""
        x = self._header.width() - 12 - self._cluster.width()
        self._cluster.move(x, 12)

    def _press_action(self, obj, win_pos):
        """Decide what a left press maps to: ('resize', edge), ('move', None),
        or None. Pure given obj + a window-local QPoint. Control buttons are
        never hijacked (they handle their own clicks)."""
        if isinstance(obj, _TrafficDot):
            return None
        if not self._is_maximized:
            edge = resize_edge_for_pos(
                win_pos.x(), win_pos.y(),
                self._win.width(), self._win.height(), self._RESIZE_MARGIN,
            )
            if edge is not None:
                return ("resize", edge)
        if obj is self._header or self._header.isAncestorOf(obj):
            return ("move", None)
        return None

    def eventFilter(self, obj, event):
        # Guard against Shiboken teardown ordering: Qt may fire eventFilter
        # after Python has partially cleared this object's attributes. Read
        # both attrs via getattr so a partially-torn-down object can't raise.
        header = getattr(self, "_header", None)
        win = getattr(self, "_win", None)
        if header is None or win is None:
            return False
        et = event.type()
        if et == QEvent.Resize and obj is header:
            self.reposition()
            return False
        if et == QEvent.WindowStateChange and obj is win:
            self._sync_window_state(bool(win.isMaximized()))
            return False
        if et in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            if not isinstance(obj, QWidget) or event.button() != Qt.LeftButton:
                return False
            if obj.window() is not win:
                return False
            win_pos = obj.mapTo(win, event.position().toPoint())
            if et == QEvent.MouseButtonDblClick:
                if not isinstance(obj, _TrafficDot) and (
                    obj is header or header.isAncestorOf(obj)
                ):
                    self._toggle_max_restore()
                    return True
                return False
            action = self._press_action(obj, win_pos)
            if action is None:
                return False
            kind, edge = action
            wh = win.windowHandle()
            if kind == "resize":
                if wh is not None and not wh.startSystemResize(edge):
                    if not self._logged_resize_fail:
                        print("[chrome] startSystemResize unsupported on this platform")
                        self._logged_resize_fail = True
                return True
            # kind == "move"
            if wh is not None and not wh.startSystemMove():
                if not self._logged_move_fail:
                    print("[chrome] startSystemMove unsupported on this platform")
                    self._logged_move_fail = True
            return True
        return False
