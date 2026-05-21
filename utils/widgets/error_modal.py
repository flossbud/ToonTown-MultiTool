"""Expanded error modal. Shown when user clicks the ☰ on a FAILED status
band. Shows the full raw error string and provides a Copy button."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)


_GAME_NAMES = {"ttr": "Toontown Rewritten", "cc": "Corporate Clash"}


class ErrorModal(QDialog):
    def __init__(self, account_name: str, game: str, raw_message: str, parent=None):
        super().__init__(parent)
        self._raw = raw_message
        self.setWindowTitle(f"Launch failed: {account_name}")
        self.setModal(True)
        self.setFixedWidth(480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        accent = QFrame()
        accent.setFixedHeight(3)
        accent.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 #c84e34, stop:1 #ff7575);"
        )
        outer.addWidget(accent)

        hdr = QFrame()
        hdr_lay = QVBoxLayout(hdr)
        hdr_lay.setContentsMargins(18, 14, 18, 10)
        hdr_lay.setSpacing(2)
        self.title_label = QLabel(f"Launch failed: {account_name}")
        self.title_label.setStyleSheet("color: #fff; font-weight: 700; font-size: 14px;")
        hdr_lay.addWidget(self.title_label)
        sub = QLabel(f"{_GAME_NAMES.get(game, game.upper())} · {datetime.now():%Y-%m-%d %H:%M}")
        sub.setStyleSheet("color: #8a9bb8; font-size: 11px;")
        hdr_lay.addWidget(sub)
        outer.addWidget(hdr)

        body = QFrame()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(18, 4, 18, 16)
        body_lay.setSpacing(10)

        self.body_text = QPlainTextEdit(raw_message)
        self.body_text.setReadOnly(True)
        self.body_text.setMaximumHeight(200)
        self.body_text.setStyleSheet(
            "QPlainTextEdit { background: rgba(0,0,0,0.3); border-radius: 5px;"
            " padding: 8px 10px; font-family: monospace; font-size: 11px;"
            " color: #ffaaaa; }"
        )
        body_lay.addWidget(self.body_text)

        acts = QHBoxLayout()
        acts.addStretch()
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.06); border:"
            " 1px solid rgba(255,255,255,0.12); color: #cfd6e6;"
            " border-radius: 5px; padding: 6px 14px; font-size: 12px; }"
        )
        self.copy_btn.clicked.connect(self._on_copy)
        acts.addWidget(self.copy_btn)
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid rgba(255,255,255,0.15);"
            " color: #cfd6e6; border-radius: 5px; padding: 6px 14px; font-size: 12px; }"
        )
        close_btn.clicked.connect(self.accept)
        acts.addWidget(close_btn)
        body_lay.addLayout(acts)

        outer.addWidget(body)
        self.setStyleSheet("QDialog { background: #1a2236; }")

    def _on_copy(self) -> None:
        QApplication.clipboard().setText(self._raw)
