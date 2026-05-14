"""Modern auto-hide scrollbar — thin pill that fades in on activity."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPropertyAnimation, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect, QScrollBar

import utils.motion as motion


_QSS_TEMPLATE = """
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {active_color};
    min-width: 8px;
    margin-left: 4px;
    min-height: 36px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: {hover_color};
    min-width: 12px;
    margin-left: 0px;
    border-radius: 6px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    background: transparent;
    border: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""

_DARK_ACTIVE = "rgba(255, 255, 255, 0.45)"
_DARK_HOVER  = "rgba(255, 255, 255, 0.70)"
_LIGHT_ACTIVE = "rgba(15, 23, 42, 0.30)"
_LIGHT_HOVER  = "rgba(15, 23, 42, 0.55)"


class AutoHideScrollBar(QScrollBar):
    """A QScrollBar that fades in on activity and fades out at idle."""

    # Class constants — tests monkey-patch these for instant animations.
    _FADE_IN_MS = 120
    _FADE_OUT_MS = 240
    _IDLE_TIMEOUT_MS = 800

    def __init__(self, parent=None):
        super().__init__(parent)
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._on_idle)

        self.valueChanged.connect(self._on_value_changed)

    def wake(self) -> None:
        """Make the bar visible. Animated unless reduce-motion is on."""
        if motion.is_reduced():
            self._anim.stop()
            self._idle_timer.stop()
            self._opacity_effect.setOpacity(1.0)
            return
        if self._opacity_effect.opacity() < 1.0 or self._anim.state() == QPropertyAnimation.Running:
            self._anim.stop()
            self._anim.setDuration(self._FADE_IN_MS)
            self._anim.setStartValue(self._opacity_effect.opacity())
            self._anim.setEndValue(1.0)
            self._anim.start()
        # Restart idle countdown on every wake.
        self._idle_timer.start(self._IDLE_TIMEOUT_MS)

    def _on_idle(self) -> None:
        if motion.is_reduced():
            return
        self._anim.stop()
        self._anim.setDuration(self._FADE_OUT_MS)
        self._anim.setStartValue(self._opacity_effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_value_changed(self, _value: int) -> None:
        self.wake()

    def enterEvent(self, event):
        self.wake()
        super().enterEvent(event)

    def attach_to_viewport(self, viewport) -> None:
        """Install self as event filter on the QScrollArea's viewport so
        wheel-scrolls and hover over the content area wake the bar."""
        viewport.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Wheel, QEvent.Enter):
            self.wake()
        return super().eventFilter(obj, event)

    def set_theme(self, is_dark: bool) -> None:
        if is_dark:
            qss = _QSS_TEMPLATE.format(
                active_color=_DARK_ACTIVE,
                hover_color=_DARK_HOVER,
            )
        else:
            qss = _QSS_TEMPLATE.format(
                active_color=_LIGHT_ACTIVE,
                hover_color=_LIGHT_HOVER,
            )
        self.setStyleSheet(qss)
