"""
Shared custom widgets used across multiple tabs.

IOSToggle           — Animated iOS-style toggle switch
IOSSegmentedControl — iOS-style segmented control for small option sets
PulsingDot          — Animated status dot with optional breathing glow
SmoothProgressBar   — Sub-pixel precision progress bar with rounded pill shape
"""

import math

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import (
    Qt, Signal, QPropertyAnimation, QEasingCurve, QVariantAnimation,
    Property, QRectF,
)
from PySide6.QtGui import QColor, QPainter, QFont, QRadialGradient


# ── iOS Toggle Switch ────────────────────────────────────────────────────────

class IOSToggle(QWidget):
    """Animated iOS-style toggle switch."""
    toggled = Signal(bool)

    TRACK_W = 51
    TRACK_H = 31
    THUMB_D = 27
    PADDING = 2

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._thumb_x = float(self.PADDING if not checked else self.TRACK_W - self.THUMB_D - self.PADDING)
        self.setFixedSize(self.TRACK_W, self.TRACK_H)
        self.setCursor(Qt.PointingHandCursor)

        self._anim = QPropertyAnimation(self, b"thumbX")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def _get_thumb_x(self):
        return self._thumb_x

    def _set_thumb_x(self, val):
        self._thumb_x = val
        self.update()

    thumbX = Property(float, _get_thumb_x, _set_thumb_x)

    def isChecked(self):
        return self._checked

    def setChecked(self, val: bool, animate=False):
        if val == self._checked:
            return
        self._checked = val
        target = float(self.TRACK_W - self.THUMB_D - self.PADDING) if val else float(self.PADDING)
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._thumb_x)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._thumb_x = target
            self.update()

    def mousePressEvent(self, e):
        self._checked = not self._checked
        target = float(self.TRACK_W - self.THUMB_D - self.PADDING) if self._checked else float(self.PADDING)
        self._anim.stop()
        self._anim.setStartValue(self._thumb_x)
        self._anim.setEndValue(target)
        self._anim.start()
        self.toggled.emit(self._checked)

    def set_theme_colors(self, off_color: str):
        """Set the off-track color from theme."""
        self._off_color = off_color
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Track
        r = self.TRACK_H / 2.0
        off_hex = getattr(self, '_off_color', '#3a3a3a')
        track_color = QColor("#34C759") if self._checked else QColor(off_hex)
        # Interpolate color during animation
        if self._thumb_x != self.PADDING and self._thumb_x != (self.TRACK_W - self.THUMB_D - self.PADDING):
            t = (self._thumb_x - self.PADDING) / (self.TRACK_W - self.THUMB_D - 2 * self.PADDING)
            t = max(0.0, min(1.0, t))
            off = QColor(off_hex)
            on  = QColor("#34C759")
            track_color = QColor(
                int(off.red()   + t * (on.red()   - off.red())),
                int(off.green() + t * (on.green() - off.green())),
                int(off.blue()  + t * (on.blue()  - off.blue())),
            )

        p.setPen(Qt.NoPen)
        p.setBrush(track_color)
        p.drawRoundedRect(QRectF(0, 0, self.TRACK_W, self.TRACK_H), r, r)

        # Thumb shadow
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QRectF(self._thumb_x + 1, self.PADDING + 2, self.THUMB_D, self.THUMB_D))

        # Thumb
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(self._thumb_x, self.PADDING, self.THUMB_D, self.THUMB_D))
        p.end()


# ── iOS Segmented Control ────────────────────────────────────────────────────

class IOSSegmentedControl(QWidget):
    """iOS-style segmented control for small option sets."""
    index_changed = Signal(int)

    def __init__(self, options: list, parent=None):
        super().__init__(parent)
        self._options = options
        self._index = 0
        self.setFixedHeight(32)
        self.setCursor(Qt.PointingHandCursor)

        self._anim_x_val = 0.0
        self._anim = QPropertyAnimation(self, b"_anim_x")
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    @Property(float)
    def _anim_x(self):
        return self._anim_x_val

    @_anim_x.setter
    def _anim_x(self, val):
        self._anim_x_val = val
        self.update()

    def currentIndex(self):
        return self._index

    def setCurrentIndex(self, idx: int):
        self._index = max(0, min(idx, len(self._options) - 1))
        self.update()

    def mousePressEvent(self, e):
        w = self.width() / len(self._options)
        idx = int(e.position().x() / w)
        idx = max(0, min(idx, len(self._options) - 1))
        if idx != self._index:
            self._index = idx
            self.index_changed.emit(idx)
            self.update()

    def set_theme_colors(self, track_color: str, pill_color: str, active_text: str, inactive_text: str):
        """Set colors from theme."""
        self._track_color = track_color
        self._pill_color = pill_color
        self._active_text = active_text
        self._inactive_text = inactive_text
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        seg_w = w / len(self._options)
        r = 8.0

        # Track background
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(getattr(self, '_track_color', '#3a3a3a')))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        # Selected pill
        sx = self._index * seg_w + 2
        p.setBrush(QColor(getattr(self, '_pill_color', '#636366')))
        p.drawRoundedRect(QRectF(sx, 2, seg_w - 4, h - 4), r - 2, r - 2)

        # Labels
        font = QFont()
        font.setPixelSize(12)
        font.setBold(False)
        p.setFont(font)

        for i, opt in enumerate(self._options):
            x = i * seg_w
            color = QColor(getattr(self, '_active_text', '#ffffff')) if i == self._index else QColor(getattr(self, '_inactive_text', '#888888'))
            p.setPen(color)
            p.drawText(QRectF(x, 0, seg_w, h), Qt.AlignCenter, opt)

        p.end()


# ── Pulsing Dot ──────────────────────────────────────────────────────────────

class PulsingDot(QWidget):
    """Animated status dot -- breathes with a soft glow when in 'active' state."""

    def __init__(self, size=10, parent=None):
        super().__init__(parent)
        self._dot_size = size
        # Extra space around the dot for the glow halo
        self.setFixedSize(size + 8, size + 8)
        self._color = QColor("#555555")
        self._pulse_val = 0.0
        self._pulsing = False

        self._anim = QVariantAnimation()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(2800)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Linear)
        self._anim.valueChanged.connect(self._on_pulse)

    def set_color(self, hex_color: str, pulse: bool = False):
        self._color = QColor(hex_color)
        if pulse:
            if not self._pulsing:
                self._pulsing = True
                self._anim.start()
        else:
            self._stop_pulse()
        self.update()

    def set_state(self, state: str, tooltip: str = ""):
        self.setToolTip(tooltip)
        if state == "active":
            self.set_color("#56c856", pulse=True)
        elif state == "keep_alive":
            self.set_color("#ff9900", pulse=True)
        elif state == "disabled":
            self.set_color("#e84141", pulse=False)
        elif state == "found":
            self.set_color("#888888", pulse=False)
        else:
            self.set_color("#555555", pulse=False)

    def _stop_pulse(self):
        if self._pulsing:
            self._pulsing = False
            self._anim.stop()
            self._pulse_val = 0.0

    def _on_pulse(self, val):
        # Map linear 0->1 through sin(pi*val) to get smooth 0->1->0 per cycle
        self._pulse_val = math.sin(val * math.pi)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        r = self._dot_size / 2.0

        if self._pulsing:
            # Soft outer glow -- fades in/out with the pulse
            glow_alpha = int(60 * self._pulse_val)
            glow_r = r + 3 + 2 * self._pulse_val
            grad = QRadialGradient(cx, cy, glow_r)
            glow_color = QColor(self._color)
            glow_color.setAlpha(glow_alpha)
            grad.setColorAt(0.0, glow_color)
            glow_color.setAlpha(0)
            grad.setColorAt(1.0, glow_color)
            p.setBrush(grad)
            p.drawEllipse(QRectF(cx - glow_r, cy - glow_r, glow_r * 2, glow_r * 2))

            # Core dot -- gentle brightness shift (only ~18% lighter at peak)
            core = QColor(self._color).lighter(100 + int(18 * self._pulse_val))
            p.setBrush(core)
        else:
            p.setBrush(QColor(self._color))

        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        p.end()


# ── Smooth Progress Bar ────────────────────────────────────────────────────

class SmoothProgressBar(QWidget):
    """Progress bar painted with sub-pixel precision and rounded pill shape."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = 0.0  # 0.0 to 1.0
        self._bg_color = QColor("#141414")
        self._fill_color = QColor("#e0943a")
        self.setFixedHeight(7)
        self.setMinimumWidth(40)

    def set_progress(self, value: float):
        self._progress = max(0.0, min(1.0, value))
        self.update()

    def set_fill_color(self, hex_color: str):
        self._fill_color = QColor(hex_color)
        self.update()

    def set_bg_color(self, hex_color: str):
        self._bg_color = QColor(hex_color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        r = h / 2.0

        # Track background
        p.setPen(Qt.NoPen)
        p.setBrush(self._bg_color)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        # Fill
        if self._progress > 0.001:
            fill_w = self._progress * w
            # Clamp minimum to pill shape diameter so it stays rounded
            fill_w = max(fill_w, h)
            p.setBrush(self._fill_color)
            p.drawRoundedRect(QRectF(0, 0, fill_w, h), r, r)

        p.end()
