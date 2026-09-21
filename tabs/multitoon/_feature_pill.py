"""Dashed sparkle chip: the always-visible per-card discovery affordance for
the globally gated extras (Click Sync and Keep-Alive), placed in each pinwheel
card's toggle row. This widget paints the chip and emits ``clicked``.

Hand-painted (no QSS border can be dashed AND capsule-radiused reliably
across styles), participates in the card dim via set_dim_progress using the
name-label alpha-mute convention (white content mutes toward 0.62 alpha;
dim_color would mis-tint white), and scales its painting via set_paint_scale
(driven by CardMetrics in _size_cell)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

_HOVER_MS = 140

# The four-point sparkle from the design bundle, on a 24x24 grid
# (multitoon-grid.reference.jsx Sparkle glyph).
_SPARKLE = [(12, 2), (14.2, 8.8), (21, 11), (14.2, 13.2),
            (12, 20), (9.8, 13.2), (3, 11), (9.8, 8.8)]


class FeaturePill(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = 0.0
        self._dim = 0.0
        self._scale = 1.0
        self._light_chrome = False
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(_HOVER_MS)
        self._hover_anim.valueChanged.connect(self._on_hover_value)
        self.setCursor(Qt.PointingHandCursor)
        # Square chip that lives in the toggle row; the real size is set from
        # CardMetrics (toggle_w/toggle_h) by _size_cell.
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedSize(34, 34)
        self.setStyleSheet("background: transparent;")

    # -- API consumed by MultitoonTab / _CompactLayout ----------------------
    def set_dim_progress(self, t: float) -> None:
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else float(t))
        if t != self._dim:
            self._dim = t
            self.update()

    def set_light_chrome(self, on: bool) -> None:
        """Dark-on-light ink family for light theme (paper/vivid cards).
        Injected by the style-writer; the pill never queries the theme."""
        on = bool(on)
        if on != self._light_chrome:
            self._light_chrome = on
            self.update()

    def set_paint_scale(self, s: float) -> None:
        # Mirror SetSelectorWidget's defensive floor; m.scale is pre-clamped
        # by clamp_scale, so this only guards direct callers.
        s = max(0.5, float(s))
        if s != self._scale:
            self._scale = s
            self.update()

    # -- events --------------------------------------------------------------
    def enterEvent(self, event):
        super().enterEvent(event)
        self._animate_hover(1.0)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._animate_hover(0.0)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _animate_hover(self, target: float) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def _on_hover_value(self, v) -> None:
        self._hover = float(v)
        self.update()

    # -- paint -----------------------------------------------------------------
    def _draw_sparkle(self, p, x: float, y: float, glyph: float, ink: QColor) -> None:
        """Paint the four-point sparkle with its top-left at (x, y), sized to
        `glyph`."""
        path = QPainterPath()
        pts = [(x + px / 24.0 * glyph, y + py / 24.0 * glyph) for px, py in _SPARKLE]
        path.moveTo(*pts[0])
        for pt in pts[1:]:
            path.lineTo(*pt)
        path.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(ink)
        p.drawPath(path)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        radius = h / 2.0
        # Dim mutes toward the same 0.62 factor the card's name label uses.
        dim_f = 1.0 + (0.62 - 1.0) * self._dim

        # Fill.
        p.setPen(Qt.NoPen)
        if self._light_chrome:
            p.setBrush(QColor(15, 23, 42, round(14 * dim_f)))
        else:
            p.setBrush(QColor(0, 0, 0, round(36 * dim_f)))
        p.drawRoundedRect(1, 1, w - 2, h - 2, radius - 1, radius - 1)

        # Dashed border: alpha 0.3 -> 0.6 on hover.
        border_a = round((77 + (153 - 77) * self._hover) * dim_f)
        border_rgb = QColor("#cbd5e1") if self._light_chrome else QColor(255, 255, 255)
        border_rgb.setAlpha(border_a)
        pen = QPen(border_rgb, 1)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([3, 3])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(1, 1, w - 2, h - 2, radius - 1, radius - 1)

        # Content: centered sparkle.
        text_a = round((191 + (255 - 191) * self._hover) * dim_f)
        ink = QColor("#64748b") if self._light_chrome else QColor(255, 255, 255)
        ink.setAlpha(text_a)
        glyph = round(12 * self._scale)

        self._draw_sparkle(p, (w - glyph) / 2.0, (h - glyph) / 2.0, glyph, ink)
        p.end()
