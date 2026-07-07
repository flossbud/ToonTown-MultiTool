"""PortraitBadge - the v2 kit's 46px circular ringed badge.

Glyph variant: gradient disc (lighten(c,0.12) -> darken(c,0.72), 145deg)
with a white line glyph. Logo variant: flat badge_logo_bg disc with the
game logo clipped to the circle. Ring is 3px in the theme's badge_ring.
Pure paintEvent - no QGraphicsEffect (kit law).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from utils.color_math import darken_rgb, lighten_rgb
from utils.theme_manager import V2_ACCENTS, get_v2_tokens

SIZE = 46
RING_W = 3


class PortraitBadge(QWidget):
    def __init__(self, accent_key: str | None = None, icon=None,
                 logo_path: str | None = None, parent=None):
        super().__init__(parent)
        self._accent = V2_ACCENTS.get(accent_key or "blue", V2_ACCENTS["blue"])
        self._icon = icon                      # QIcon (white line glyph) or None
        self._logo = QPixmap(logo_path) if logo_path else QPixmap()
        self._t = get_v2_tokens(True)
        self.setFixedSize(SIZE, SIZE)
        self.setStyleSheet("background: transparent;")

    def apply_theme(self, is_dark: bool) -> None:
        self._t = get_v2_tokens(is_dark)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        inner = QRectF(RING_W / 2, RING_W / 2, SIZE - RING_W, SIZE - RING_W)

        clip = QPainterPath()
        clip.addEllipse(inner)
        p.save()
        p.setClipPath(clip)
        if not self._logo.isNull():
            p.setPen(Qt.NoPen)
            p.fillPath(clip, _qcolor_from_rgba(self._t["badge_logo_bg"]))
            pm = self._logo.scaled(
                int(inner.width()), int(inner.height()),
                Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(int(inner.x()), int(inner.y()), pm)
        else:
            c = QColor(self._accent["c"])
            grad = QLinearGradient(inner.topLeft(), inner.bottomRight())  # ~145deg
            grad.setColorAt(0.0, lighten_rgb(c, 0.12))
            grad.setColorAt(1.0, darken_rgb(c, 0.72))
            p.fillPath(clip, grad)
            if self._icon is not None:
                pm = self._icon.pixmap(20, 20)
                p.drawPixmap(int((SIZE - 20) / 2), int((SIZE - 20) / 2), pm)
        p.restore()

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_qcolor_from_rgba(self._t["badge_ring"]), RING_W))
        p.drawEllipse(inner)
        p.end()


def _qcolor_from_rgba(qss: str) -> QColor:
    """Parse this codebase's `rgba(r, g, b, a)` QSS strings (a = 0-255)."""
    if qss.startswith("#"):
        return QColor(qss)
    parts = qss[qss.index("(") + 1:qss.rindex(")")].split(",")
    r, g, b, a = (int(float(x.strip())) for x in parts)
    return QColor(r, g, b, a)
