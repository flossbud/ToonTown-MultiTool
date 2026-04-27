"""Full UI layout for the Multitoon tab — activated at >= 1280x800.

The Full UI is a 2x2 card grid with large portraits and a Discord-style status
indicator (background-colored ring overlapping the portrait + colored dot inside).
"""

from PySide6.QtCore import Qt, Property
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class _StatusIndicator(QWidget):
    """32x32 widget: a 32px ring in the card-bg color + a 24px filled dot.

    Z-order when overlaid on the portrait: portrait -> ring -> dot. The ring
    color must match the parent card background to create the cutout illusion.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self._active = False
        self._ring_color = QColor("#2a2a30")  # default = dark card-bg
        self._dot_color_active = QColor("#3aaa5e")
        self._dot_color_idle = QColor("#45454c")
        self._glow = 0.0  # 0.0..1.0, animated when active

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self.update()

    def apply_theme(self, ring_hex: str, active_hex: str, idle_hex: str) -> None:
        self._ring_color = QColor(ring_hex)
        self._dot_color_active = QColor(active_hex)
        self._dot_color_idle = QColor(idle_hex)
        self.update()

    # Animated glow property — driven by a QPropertyAnimation in a later task.
    def _get_glow(self) -> float:
        return self._glow

    def _set_glow(self, v: float) -> None:
        self._glow = max(0.0, min(1.0, v))
        self.update()

    glow = Property(float, _get_glow, _set_glow)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        # Ring fills the entire widget bounds — same color as parent card bg.
        p.setBrush(self._ring_color)
        p.drawEllipse(0, 0, 32, 32)

        # Dot — 24x24 centered, leaves a 4px ring on every side.
        dot_color = self._dot_color_active if self._active else self._dot_color_idle
        if self._active and self._glow > 0:
            # Glow halo: extra outer dot at low alpha
            halo = QColor(dot_color)
            halo.setAlphaF(0.35 * self._glow)
            p.setBrush(halo)
            p.drawEllipse(1, 1, 30, 30)
        p.setBrush(dot_color)
        p.drawEllipse(4, 4, 24, 24)
