"""Floating container for the portable Settings panel over the overlay.

Wraps an injected content widget (the app's real SettingsTab, reparented in)
with a titled panel + a red close button, and emits ``closed`` on the close
button or Esc. ``release_content`` detaches the content so the caller can
restore it to the main window's tab stack before this container is destroyed.

The title bar is draggable: clicking and dragging it moves the whole floating
panel (its hosting overlay surface) so the user can slide it aside from the
emblem underneath. The panel has no dim scrim of its own; only the panel chrome
is painted, so the cards/games behind stay visible around it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
)

from utils.widgets.window_chrome import _TrafficDot
from utils.widgets.window_chrome_style import TRAFFIC


class _CloseDot(_TrafficDot):
    """The exact windowed-mode traffic-light CLOSE dot, reused standalone.

    In the main window a ``_TrafficCluster`` reveals each dot's glyph on cluster
    hover; here the dot is alone, so it drives its own glyph reveal on its own
    hover (same colors, size, animations, and 'x'-on-hover behavior)."""

    def __init__(self, parent=None):
        super().__init__(TRAFFIC["close"][0], "×", TRAFFIC["close"][1], "Close", parent)
        self.setObjectName("win_ctl_close")

    def enterEvent(self, event):
        super().enterEvent(event)        # scale + brightness pop
        self.set_cluster_hovered(True)   # reveal the x glyph

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.set_cluster_hovered(False)


class _TitleBar(QFrame):
    """Drag handle: dragging it moves the panel's top-level window (the hosting
    overlay surface). Children that consume their own mouse events (the close
    button) are unaffected; the title label ignores mouse events, so dragging
    over it still moves the panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.SizeAllCursor)
        self._press_global: QPoint | None = None
        self._win_origin: QPoint | None = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_global = e.globalPosition().toPoint()
            self._win_origin = self.window().frameGeometry().topLeft()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press_global is not None and self._win_origin is not None:
            delta = e.globalPosition().toPoint() - self._press_global
            self.window().move(self._win_origin + delta)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press_global = None
        self._win_origin = None
        super().mouseReleaseEvent(e)


class PortableSettingsContainer(QWidget):
    closed = Signal()

    def __init__(self, content: QWidget, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._content = content
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        panel = QFrame(self)
        panel.setObjectName("portable_settings_panel")
        panel.setStyleSheet(
            "#portable_settings_panel{background:#141824;border:1px solid #232a3a;"
            "border-radius:12px;}")
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)
        bar = _TitleBar(panel)
        bar.setObjectName("portable_settings_titlebar")
        bar.setStyleSheet("#portable_settings_titlebar{background:transparent;}")
        header = QHBoxLayout(bar)
        header.setContentsMargins(14, 10, 10, 6)
        title = QLabel("Settings")
        title.setStyleSheet("color:#e7ecf3;font-weight:600;")
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # let drags reach the bar
        close_btn = _CloseDot(bar)
        close_btn.clicked.connect(self.closed.emit)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(close_btn)
        pv.addWidget(bar)
        content.setParent(panel)
        pv.addWidget(content, 1)
        # setParent() hides the widget, and the real SettingsTab arrives EXPLICITLY
        # hidden (it is a non-current QStackedWidget page). addWidget() will not
        # re-show an explicitly-hidden widget, so without this the panel renders
        # only its chrome over an invisible body. Re-show the content we host.
        content.show()
        outer.addWidget(panel)

    def release_content(self) -> QWidget:
        """Detach the content widget so it survives this container's destruction."""
        c = self._content
        self._content = None
        if c is not None:
            c.setParent(None)
        return c

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.closed.emit()
            return
        super().keyPressEvent(e)
