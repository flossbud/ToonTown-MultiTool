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

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

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


class _Panel(QFrame):
    """The editor card. Header / preview / pill nav / section stack /
    footer. Emits high-level intent signals that the overlay routes."""

    PANEL_W = 543
    PANEL_H = 738
    HEADER_H = 44
    FOOTER_H = 52
    PREVIEW_H = 180
    PILL_ROW_H = 40

    close_requested = Signal()
    cancel_requested = Signal()
    save_requested = Signal()
    reset_requested = Signal()
    section_changed = Signal(str)  # active pill name

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("CustomizationPanel")
        self.setStyleSheet(
            "QFrame#CustomizationPanel {"
            "  background: rgba(31, 34, 48, 240);"  # ~94 % alpha of #1f2230
            "  border: 1px solid #3a3f55;"
            "  border-radius: 12px;"
            "}"
        )
        self.setFixedSize(self.PANEL_W, self.PANEL_H)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_preview_placeholder())
        outer.addWidget(self._build_pill_row())
        outer.addWidget(self._build_section_stack(), 1)
        outer.addWidget(self._build_footer())

    # -- subwidgets ------------------------------------------------------

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(self.HEADER_H)
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 0, 8, 0)
        row.setSpacing(8)

        self.title_label = QLabel("Customize")
        self.title_label.setStyleSheet(
            "color: #e8e8f0; font-size: 15px; font-weight: 600;"
        )
        row.addWidget(self.title_label, 1)

        self.close_btn = QPushButton()
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setToolTip("Close (Esc)")
        self.close_btn.setStyleSheet(
            "QPushButton {"
            "  background: #353a52; color: #e8e8f0;"
            "  border: none; border-radius: 6px;"
            "  font-size: 16px; font-weight: bold;"
            "}"
            "QPushButton:hover { background: #4a5070; }"
        )
        # No glyph yet: the button is identified by its dark square
        # styling + tooltip. A real "×" or SVG icon lands in a later
        # task once the glyph source is settled; until then, .text()
        # stays empty (tests assert this) and the tooltip plus the
        # styled background carry the affordance.
        self.close_btn.clicked.connect(self.close_requested)
        row.addWidget(self.close_btn)
        return bar

    def _build_preview_placeholder(self) -> QWidget:
        # CardPreviewWidget is added by populate() in a later task;
        # for now this is a fixed-height slot the layout reserves.
        self.preview_host = QWidget()
        self.preview_host.setFixedHeight(self.PREVIEW_H)
        return self.preview_host

    def _build_pill_row(self) -> QWidget:
        row_widget = QWidget()
        row_widget.setFixedHeight(self.PILL_ROW_H)
        self.pill_row = QHBoxLayout(row_widget)
        self.pill_row.setContentsMargins(16, 5, 16, 5)
        self.pill_row.setSpacing(6)
        self._pill_group = QButtonGroup(row_widget)
        self._pill_group.setExclusive(True)
        self._pill_group.idClicked.connect(self._on_pill_clicked)
        return row_widget

    def _build_section_stack(self) -> QWidget:
        self.section_stack = QStackedWidget()
        self.section_stack.setStyleSheet(
            "QStackedWidget { background: transparent; }"
        )
        return self.section_stack

    def _build_footer(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(self.FOOTER_H)
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(8)

        self.reset_btn = QPushButton("Reset all")
        self.reset_btn.setFixedHeight(32)
        self.reset_btn.setStyleSheet(self._secondary_btn_css())
        self.reset_btn.clicked.connect(self.reset_requested)
        row.addWidget(self.reset_btn)

        row.addStretch(1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedHeight(32)
        self.cancel_btn.setStyleSheet(self._secondary_btn_css())
        self.cancel_btn.clicked.connect(self.cancel_requested)
        row.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.setFixedHeight(32)
        self.save_btn.setDefault(True)
        self.save_btn.setStyleSheet(self._primary_btn_css())
        self.save_btn.clicked.connect(self.save_requested)
        row.addWidget(self.save_btn)
        return bar

    @staticmethod
    def _secondary_btn_css() -> str:
        return (
            "QPushButton {"
            "  background: #353a52; color: #c8c8d0;"
            "  border: none; border-radius: 6px;"
            "  padding: 0 14px; font-size: 13px;"
            "}"
            "QPushButton:hover { background: #4a5070; }"
        )

    @staticmethod
    def _primary_btn_css() -> str:
        return (
            "QPushButton {"
            "  background: #4a7cff; color: #ffffff;"
            "  border: none; border-radius: 6px;"
            "  padding: 0 14px; font-size: 13px; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #5d8cff; }"
        )

    def _on_pill_clicked(self, index: int) -> None:
        self.section_stack.setCurrentIndex(index)
        btn = self._pill_group.button(index)
        if btn is not None:
            self.section_changed.emit(btn.text())
