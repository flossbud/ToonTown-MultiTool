"""Custom window chrome for the frameless main window: resize-edge math,
control-button glyphs, the traffic-light control buttons, and the
WindowChromeController that wires drag / resize / window-state behavior.

Move and resize delegate to the compositor via QWindow.startSystemMove() /
startSystemResize(), which is the only reliable cross-platform path
(X11, Wayland, Windows) and preserves native snap/tiling. We never hand-roll
move()/resize() — that breaks on Wayland."""

from PySide6.QtCore import Qt, QObject, QEvent
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton, QApplication, QWidget


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
    """A 22x22 button (comfortable hit area) that paints a centered 14px
    colored circle with a subtle tinted glyph. No QGraphicsEffect (avoids the
    paint-device conflict that effects cause with custom paintEvent)."""

    _VISUAL_DIAMETER = 14
    _HIT = 22

    def __init__(self, dot_color: str, glyph: str, glyph_color: str,
                 accessible_name: str, parent=None):
        super().__init__(parent)
        self._dot_color = QColor(dot_color)
        self._glyph = glyph
        self._glyph_color = QColor(glyph_color)
        self.setFixedSize(self._HIT, self._HIT)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAccessibleName(accessible_name)
        self.setToolTip(accessible_name)

    def set_glyph(self, glyph: str):
        self._glyph = glyph
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        d = self._VISUAL_DIAMETER
        off = (self._HIT - d) / 2
        p.setPen(Qt.NoPen)
        p.setBrush(self._dot_color)
        p.drawEllipse(int(off), int(off), d, d)
        if self._glyph:
            p.setPen(self._glyph_color)
            f = p.font()
            f.setPixelSize(9)
            f.setBold(True)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, self._glyph)
        p.end()


class WindowChromeController(QObject):
    """Owns the custom window controls + drag/resize/state for a frameless
    main window. Construct only when custom chrome is active (the
    use_system_title_bar setting is off)."""

    _RESIZE_MARGIN = 6

    def __init__(self, window, header, parent=None):
        super().__init__(parent or window)
        self._win = window
        self._header = header
        self._is_maximized = False
        self._logged_move_fail = False
        self._logged_resize_fail = False

        self.btn_min = _TrafficDot("#4aa3ff", "−", "#d7ebff", "Minimize", header)
        self.btn_max = _TrafficDot("#0077ff", maximize_glyph(False), "#aed5ff", "Maximize", header)
        self.btn_close = _TrafficDot("#ff5f56", "×", "#ffcecb", "Close", header)
        self.btn_min.setObjectName("win_ctl_min")
        self.btn_max.setObjectName("win_ctl_max")
        self.btn_close.setObjectName("win_ctl_close")

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

    def _sync_window_state(self, is_maximized: bool):
        self._is_maximized = is_maximized
        self.btn_max.set_glyph(maximize_glyph(is_maximized))

    def reposition(self):
        """Pin the control cluster to the header's top-right corner."""
        x = self._header.width() - 12 - self.btn_close.width()
        gap = 8
        self.btn_close.move(x, 12)
        self.btn_max.move(x - (self.btn_max.width() + gap), 12)
        self.btn_min.move(x - 2 * (self.btn_max.width() + gap), 12)

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
