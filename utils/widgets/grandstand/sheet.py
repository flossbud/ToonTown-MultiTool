"""The focus-mode sheet shell (spec §2): header, any body, footer.

Surface-agnostic so sub-project B can drop the Appearance editor into it: the
shell knows nothing about accounts. Title, subtitle, the one cross-link
(handoff §4.5 — never a tab bar), the note and the two footer buttons are all
set by the owner; the shell only emits what the user asked for.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QFrame, QHBoxLayout, QLabel, QPushButton,
    QToolButton, QVBoxLayout, QWidget,
)

from utils.widgets.grandstand import palette as gp

BACK_SIZE = 28          # handoff §4.4: 28 px back arrow
CROSS_LINK_H = 28       # handoff §4.5: `.sheet-x`
FOOTER_BUTTON_H = 30    # handoff §4.4: `.sheet-foot` buttons
HEADER_H = 34           # the shelf's head row height, so the panels align
SHEET_MARGINS = (12, 12, 12, 12)
BODY_MARGINS = (0, 12, 0, 12)
BACK_GLYPH = "‹"


def _transparent(widget: QWidget, name: str) -> None:
    """Containers are styled-background widgets under the app's global
    `QWidget { background-color }` rule; each must opt out or it paints a
    square of page colour over the sheet surface."""
    widget.setObjectName(name)
    widget.setStyleSheet(f"#{name} {{ background: transparent; }}")


class SheetHeader(QWidget):
    """Back arrow, title, subtitle and the one cross-link. Shared by the sheet
    shell and the toon browser (handoff §4.7 uses the same head row)."""

    back_requested = Signal()
    cross_link_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _transparent(self, "gs_sheet_header")
        self.setFixedHeight(HEADER_H)
        self._is_dark = True
        self._title = ""
        self._subtitle = ""

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self.back_button = QToolButton(self)
        self.back_button.setObjectName("gs_sheet_back")
        self.back_button.setFixedSize(BACK_SIZE, BACK_SIZE)
        self.back_button.setCursor(Qt.PointingHandCursor)
        self.back_button.setFocusPolicy(Qt.TabFocus)
        self.back_button.setText(BACK_GLYPH)
        self.back_button.setToolTip("Back")
        self.back_button.clicked.connect(self.back_requested.emit)
        row.addWidget(self.back_button, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self.title = QLabel(self)
        self.subtitle = QLabel(self)
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        row.addLayout(col, 1)

        self.cross_link = QPushButton(self)
        self.cross_link.setObjectName("gs_sheet_x")
        self.cross_link.setFixedHeight(CROSS_LINK_H)
        self.cross_link.setCursor(Qt.PointingHandCursor)
        self.cross_link.setFocusPolicy(Qt.TabFocus)
        self.cross_link.setVisible(False)
        self.cross_link.clicked.connect(self.cross_link_requested.emit)
        row.addWidget(self.cross_link, 0, Qt.AlignVCenter)

        self.apply_theme(True)

    def set_copy(self, title: str, subtitle: str) -> None:
        """The title renders as an uppercase section label (the prototype's
        `text-transform`); `title_text()` keeps the verbatim copy."""
        self._title, self._subtitle = title, subtitle
        self.title.setText(title.upper())
        self.subtitle.setText(subtitle)

    def set_cross_link(self, text: str) -> None:
        self.cross_link.setText(text)
        self.cross_link.setVisible(bool(text))

    def title_text(self) -> str:
        return self._title

    def subtitle_text(self) -> str:
        return self._subtitle

    def cross_link_text(self) -> str:
        return self.cross_link.text() if self.cross_link.isVisibleTo(self) else ""

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        ink = gp.sheet_ink(is_dark)
        self.title.setStyleSheet(
            f"color: {ink['title'].name()}; font-size: 10px; font-weight: 800;"
            " letter-spacing: 0.8px; background: transparent;")
        self.subtitle.setStyleSheet(
            f"color: {ink['sub'].name()}; font-size: 10px; background: transparent;")
        rest = gp.sheet_chrome_button(False, is_dark)
        hover = gp.sheet_chrome_button(True, is_dark)
        self.back_button.setStyleSheet(
            "QToolButton {"
            f" background: {rest['bg'].name(QColor.HexArgb)};"
            f" border: 1px solid {rest['border'].name(QColor.HexArgb)};"
            f" border-radius: {BACK_SIZE // 2}px; color: {rest['ink'].name()};"
            " font-size: 16px; font-weight: 700; }"
            " QToolButton:hover {"
            f" background: {hover['bg'].name(QColor.HexArgb)};"
            f" border: 1px solid {hover['border'].name(QColor.HexArgb)};"
            f" color: {hover['ink'].name()}; }}")
        self.cross_link.setStyleSheet(
            "QPushButton {"
            f" background: {rest['bg'].name(QColor.HexArgb)};"
            f" border: 1px solid {rest['border'].name(QColor.HexArgb)};"
            f" border-radius: {CROSS_LINK_H // 2}px; padding: 0 13px;"
            f" color: {rest['ink'].name()}; font-size: 12px; font-weight: 500; }}"
            " QPushButton:hover {"
            f" background: {hover['bg'].name(QColor.HexArgb)};"
            f" border: 1px solid {hover['border'].name(QColor.HexArgb)};"
            f" color: {hover['ink'].name()}; }}")


class SheetShell(QFrame):
    """Header + body slot + footer (note, Cancel, Save)."""

    back_requested = Signal()
    cancel_requested = Signal()
    save_requested = Signal()
    cross_link_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("gs_sheet")
        # Focusable so a click on the sheet's own surface still routes Esc and
        # Enter (Task 7) through keyPressEvent below.
        self.setFocusPolicy(Qt.StrongFocus)
        self._is_dark = True
        self._body: Optional[QWidget] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(*SHEET_MARGINS)
        root.setSpacing(0)

        self.header = SheetHeader(self)
        self.header.back_requested.connect(self.back_requested.emit)
        self.header.cross_link_requested.connect(self.cross_link_requested.emit)
        root.addWidget(self.header)
        self.back_button = self.header.back_button

        self._body_slot = QVBoxLayout()
        self._body_slot.setContentsMargins(*BODY_MARGINS)
        self._body_slot.setSpacing(0)
        root.addLayout(self._body_slot, 1)

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(8)
        self.note = QLabel(self)
        foot.addWidget(self.note, 1)
        self.cancel_button = QPushButton("Cancel", self)
        self.save_button = QPushButton("Save", self)
        for button, signal in ((self.cancel_button, self.cancel_requested),
                               (self.save_button, self.save_requested)):
            button.setFixedHeight(FOOTER_BUTTON_H)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.StrongFocus)
            button.clicked.connect(signal.emit)
            foot.addWidget(button, 0)
        root.addLayout(foot)

        self.apply_theme(True)

    # ── inbound ────────────────────────────────────────────────────────────

    def set_body(self, body: QWidget) -> None:
        if self._body is not None:
            self._body_slot.removeWidget(self._body)
            self._body.setParent(None)
        self._body = body
        body.setParent(self)
        self._body_slot.addWidget(body, 1)
        self._wire_tab_order()
        if hasattr(body, "apply_theme"):
            body.apply_theme(self._is_dark)

    def body(self) -> Optional[QWidget]:
        return self._body

    def set_header(self, title: str, subtitle: str) -> None:
        self.header.set_copy(title, subtitle)

    def set_cross_link(self, text: str) -> None:
        self.header.set_cross_link(text)

    def set_note(self, text: str) -> None:
        self.note.setText(text)

    def note_text(self) -> str:
        return self.note.text()

    def _wire_tab_order(self) -> None:
        """Fields tab in visual order, then Cancel, Save (spec §4)."""
        chain = list(getattr(self._body, "tab_chain", lambda: [])())
        chain += [self.cancel_button, self.save_button]
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)

    # ── theme ──────────────────────────────────────────────────────────────

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        s = gp.sheet_surface(is_dark)
        self.setStyleSheet(
            f"QFrame#gs_sheet {{ background: {s['bg'].name()};"
            f" border: 1px solid {s['border'].name()}; border-radius: 9px; }}")
        self.header.apply_theme(is_dark)
        ink = gp.sheet_ink(is_dark)
        self.note.setStyleSheet(
            f"color: {ink['note'].name()}; font-size: 11px; background: transparent;")
        for button, primary in ((self.cancel_button, False),
                                (self.save_button, True)):
            rest = gp.sheet_footer_button(primary, False, is_dark)
            hover = gp.sheet_footer_button(primary, True, is_dark)
            button.setStyleSheet(
                "QPushButton {"
                f" background: {rest['bg'].name(QColor.HexArgb)};"
                f" border: 1px solid {rest['border'].name(QColor.HexArgb)};"
                f" border-radius: 5px; padding: 0 15px; color: {rest['ink'].name()};"
                " font-size: 12px; font-weight: 600; }"
                " QPushButton:hover {"
                f" background: {hover['bg'].name(QColor.HexArgb)};"
                f" border: 1px solid {hover['border'].name(QColor.HexArgb)};"
                f" color: {hover['ink'].name()}; }}")
        body = self._body
        if body is not None and hasattr(body, "apply_theme"):
            body.apply_theme(is_dark)
