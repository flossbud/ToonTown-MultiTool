"""Static blurred backdrop widget.

A frozen, blurred snapshot painted with a dim scrim, used behind floating
content (the customization overlay and the Credits screen). We deliberately do
NOT use QGraphicsEffect: QGraphicsBlurEffect/QGraphicsOpacityEffect render
invisibly when applied to widgets hosted in a QGraphicsProxyWidget (the
_FullLayout scale wrapper) and risk the Py3.14/PySide6 paint-time GC SEGV.
Blurring a captured pixmap and painting with QPainter.setOpacity keeps
everything inside the widget's single painter."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Property, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from utils.image_blur import gaussian_blur_pixmap


class BackdropBlur(QWidget):
    DIM_COLOR = QColor(0, 0, 0, int(0.40 * 255))
    BLUR_RADIUS = 16

    def __init__(self, parent: Optional[QWidget] = None,
                 mouse_transparent: bool = False):
        super().__init__(parent)
        self._blurred: Optional[QPixmap] = None
        self._opacity: float = 1.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, mouse_transparent)

    def set_source_pixmap(self, pix: QPixmap) -> None:
        """Capture a fresh blurred copy of the given pixmap (or clear if null)."""
        if pix is None or pix.isNull():
            self._blurred = None
        else:
            self._blurred = gaussian_blur_pixmap(pix, self.BLUR_RADIUS)
        self.update()

    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, value: float) -> None:
        self._opacity = float(value)
        self.update()

    opacity = Property(float, _get_opacity, _set_opacity)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setOpacity(self._opacity)
        if self._blurred is not None and not self._blurred.isNull():
            p.drawPixmap(self.rect(), self._blurred, self._blurred.rect())
        p.fillRect(self.rect(), self.DIM_COLOR)
        p.end()
