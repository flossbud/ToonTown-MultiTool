"""Picker chrome: PickerChip helper, ElidedLabel, and PickerCard row widget.

PickerChip
    Namespace for chip rendering: QSS background gradient (used by
    PickerCard's chip QLabel) and inline HTML snippet (used by
    tabs/settings_tab.py's GamePathRow when the active CC install matches).

ElidedLabel
    QLabel subclass that paints middle-elided text and exposes the full
    string as a tooltip. Used by PickerCard for the path line so long
    Bottles/Flatpak paths don't blow out the dialog width.

PickerCard
    (added in Task 3) Single-row widget composing chip + name + path + state
    (active, selected, stale). Consumed by cc_install_picker.py and
    cc_compat_picker.py.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import QLabel

from utils.launcher_chip import (
    LAUNCHER_CHIP_LABEL,
    chip_style_for,
)


class PickerChip:
    """Stateless namespace for chip rendering primitives."""

    @staticmethod
    def label_for(slug: str) -> str:
        """The uppercase label shown inside the chip."""
        return LAUNCHER_CHIP_LABEL.get(slug, slug.upper())

    @staticmethod
    def qss_background(slug: str) -> str:
        """QSS background-image gradient for the chip widget itself."""
        return chip_style_for(slug)

    @staticmethod
    def inline_html(slug: str, *, height_px: int = 18) -> str:
        """Render a chip as an inline HTML snippet for QLabel rich-text.

        Used by Settings CC row (GamePathRow._refresh_display) when the
        active install matches a discovered one. The QLabel hosting the
        snippet must have setTextFormat(Qt.RichText).
        """
        from utils.launcher_chip import LAUNCHER_CHIP_COLOR, _FALLBACK_PAIR
        start, end = LAUNCHER_CHIP_COLOR.get(slug, _FALLBACK_PAIR)
        label = PickerChip.label_for(slug)
        # Inline-block span with background gradient, white text, padding.
        # QLabel's rich text supports a subset of HTML; gradient backgrounds
        # work via CSS `background: linear-gradient(...)` in the style attr.
        return (
            f'<span style="'
            f'background: qlineargradient(x1:0, y1:0, x2:1, y2:1, '
            f'stop:0 {start}, stop:1 {end}); '
            f'color:#fff; font-weight:800; letter-spacing:0.5px; '
            f'padding:2px 6px; border-radius:5px; '
            f'font-size:10px; line-height:{height_px}px;'
            f'">{label}</span>'
        )


class ElidedLabel(QLabel):
    """QLabel that paints text elided from the middle and tooltips the full text.

    The visible elided text is recomputed on every paintEvent against the
    current widget width and font metrics, so resizing the parent dialog
    re-elides automatically.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setToolTip(text)

    def full_text(self) -> str:
        return self._full_text

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        fm = QFontMetrics(self.font())
        elided = fm.elidedText(self._full_text, Qt.ElideMiddle, self.width())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, elided)
