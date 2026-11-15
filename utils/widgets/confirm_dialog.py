"""Modal confirm dialog for destructive actions (Quit, Delete).
Optional 'Don't ask again' checkbox for Quit (delete is permanent and
should always confirm)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from utils.theme_manager import is_dark_palette
from utils.widgets.modal_colors import (
    SECTION_OBJECT_NAME, modal_colors, surface_stylesheet,
)


class ConfirmDialog(QDialog):
    def __init__(
        self,
        title: str,
        body: str,
        confirm_label: str,
        show_dont_ask_again: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(360)
        col = modal_colors(is_dark_palette())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Red accent bar
        accent = QFrame()
        accent.setFixedHeight(3)
        accent.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 #c84e34, stop:1 #ff7575);"
        )
        outer.addWidget(accent)

        # Header
        hdr = QFrame()
        hdr.setObjectName(SECTION_OBJECT_NAME)
        hdr_lay = QVBoxLayout(hdr)
        hdr_lay.setContentsMargins(18, 14, 18, 10)
        hdr_lay.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"background: transparent; color: {col['title']};"
            " font-weight: 700; font-size: 14px;")
        self.title_label.setWordWrap(True)
        hdr_lay.addWidget(self.title_label)
        outer.addWidget(hdr)

        # Body
        body_frame = QFrame()
        body_frame.setObjectName(SECTION_OBJECT_NAME)
        body_lay = QVBoxLayout(body_frame)
        body_lay.setContentsMargins(18, 4, 18, 14)
        body_lay.setSpacing(10)
        self.body_label = body_label = QLabel(body)
        body_label.setWordWrap(True)
        body_label.setStyleSheet(
            f"background: transparent; color: {col['body']}; font-size: 13px;")
        body_lay.addWidget(body_label)

        # Optional Don't ask again
        self.dont_ask_again_check = None
        if show_dont_ask_again:
            self.dont_ask_again_check = QCheckBox("Don't ask again")
            self.dont_ask_again_check.setStyleSheet(
                f"QCheckBox {{ background: transparent; color: {col['muted']};"
                " font-size: 11px; spacing: 6px; }"
                # Explicit box: the app theme does not style checkboxes, and
                # the platform default is unreadable on these surfaces.
                " QCheckBox::indicator { width: 12px; height: 12px;"
                f" border: 1px solid {col['cancel_border']}; border-radius: 3px;"
                f" background: {col['input_bg']}; }}"
                " QCheckBox::indicator:checked {"
                f" background: {col['save_bg']}; border-color: {col['save_bg']}; }}"
            )
            body_lay.addWidget(self.dont_ask_again_check)

        # Actions
        acts = QHBoxLayout()
        acts.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {col['cancel_border']};"
            f" color: {col['cancel_text']}; border-radius: 5px; padding: 6px 14px; font-size: 12px; }}"
        )
        self.cancel_btn.clicked.connect(self.reject)
        acts.addWidget(self.cancel_btn)
        self.confirm_btn = QPushButton(confirm_label)
        self.confirm_btn.setStyleSheet(
            f"QPushButton {{ background: {col['danger_bg']}; color: {col['danger_text']}; border: none;"
            " border-radius: 5px; padding: 6px 14px; font-size: 12px; font-weight: 600; }"
        )
        self.confirm_btn.clicked.connect(self.accept)
        acts.addWidget(self.confirm_btn)
        body_lay.addLayout(acts)

        outer.addWidget(body_frame)
        self.setStyleSheet(surface_stylesheet(col))

    def dont_ask_again_checked(self) -> bool:
        return bool(self.dont_ask_again_check and self.dont_ask_again_check.isChecked())
