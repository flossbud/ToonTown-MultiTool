"""In-app overlay that replaces the floating ToonCustomizationDialog.

Owns:
  - _BackdropBlur: paints a frozen blurred grab of the multitoon tab
                   plus a 40 % black dim layer
  - _Panel:        the editor card (header / preview / pill nav /
                   section stack / footer)
  - ToonCustomizationOverlay: the host widget. Public API:
                              open_for, request_close,
                              close_and_discard, close_and_save.

See docs/superpowers/specs/2026-05-26-customization-inline-panel-design.md
for the design contract.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from utils.image_blur import gaussian_blur_pixmap


class _BackdropBlur(QWidget):
    """Static blurred backdrop for the customization overlay."""

    DIM_COLOR = QColor(0, 0, 0, int(0.40 * 255))
    BLUR_RADIUS = 16

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._blurred: Optional[QPixmap] = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    def set_source_pixmap(self, pix: QPixmap) -> None:
        """Capture a fresh blurred copy of the given pixmap."""
        if pix.isNull():
            self._blurred = None
        else:
            self._blurred = gaussian_blur_pixmap(pix, self.BLUR_RADIUS)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        if self._blurred is not None and not self._blurred.isNull():
            # Stretch the captured pixmap to fill the widget bounds.
            p.drawPixmap(self.rect(), self._blurred, self._blurred.rect())
        p.fillRect(self.rect(), self.DIM_COLOR)
        p.end()
