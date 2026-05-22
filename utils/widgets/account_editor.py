"""Edit/Add account modal. One component, two modes ('edit' / 'add').
Top accent bar uses the game's accent color. Emits account_saved on Save."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)


_ACCENTS = {
    "ttr": ("#4A8FE7", "#88c0d0"),
    "cc":  ("#F26D21", "#E8963A"),
}
_GAME_NAMES = {"ttr": "Toontown Rewritten", "cc": "Corporate Clash"}
_GAME_SHORT = {"ttr": "TTR", "cc": "CC"}


class AccountEditor(QDialog):
    account_saved = Signal(str, str, str)  # label, username, password

    def __init__(
        self,
        game: str,
        mode: str,                      # "add" | "edit"
        initial_label: str = "",
        initial_username: str = "",
        initial_password: str = "",
        parent=None,
    ):
        super().__init__(parent)
        assert game in ("ttr", "cc")
        assert mode in ("add", "edit")
        self._game = game
        self._mode = mode

        primary, secondary = _ACCENTS[game]
        title = (
            f"Add {_GAME_SHORT[game]} Account" if mode == "add"
            else f"Edit {initial_label or initial_username or 'account'}"
        )
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(380)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Top accent bar
        self.accent_bar = QFrame()
        self.accent_bar.setFixedHeight(3)
        self.accent_bar.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            f" stop:0 {primary}, stop:1 {secondary});"
        )
        outer.addWidget(self.accent_bar)

        # Header
        hdr = QFrame()
        hdr_lay = QVBoxLayout(hdr)
        hdr_lay.setContentsMargins(18, 14, 18, 12)
        hdr_lay.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color: #fff; font-weight: 700; font-size: 15px;")
        hdr_lay.addWidget(self.title_label)
        self.subline = QLabel(_GAME_NAMES[game])
        self.subline.setStyleSheet("color: #8a9bb8; font-size: 12px;")
        hdr_lay.addWidget(self.subline)
        outer.addWidget(hdr)

        # Body
        body = QFrame()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(18, 14, 18, 18)
        body_lay.setSpacing(10)

        def labeled_input(lab_text: str, initial: str = "", password: bool = False):
            box = QVBoxLayout()
            box.setSpacing(3)
            l = QLabel(lab_text)
            l.setStyleSheet("color: #8a9bb8; font-size: 10px; font-weight: 600;"
                            " text-transform: uppercase; letter-spacing: 0.05em;")
            box.addWidget(l)
            inp = QLineEdit(initial)
            if password:
                inp.setEchoMode(QLineEdit.Password)
            inp.setStyleSheet(
                "QLineEdit { background: rgba(255,255,255,0.04); border: 1px solid"
                " rgba(255,255,255,0.1); border-radius: 5px; padding: 6px 9px;"
                " color: #fff; font-size: 12px; }"
            )
            box.addWidget(inp)
            err = QLabel("")
            err.setStyleSheet("color: #ff7575; font-size: 10px; font-weight: 600;")
            err.setVisible(False)
            box.addWidget(err)
            inp.textChanged.connect(lambda _: err.setVisible(False))
            return box, inp, err

        lay_lbl, self.label_input, self.label_error = labeled_input("Label (optional)", initial_label)
        lay_usr, self.username_input, self.username_error = labeled_input("Username", initial_username)
        lay_pwd, self.password_input, self.password_error = labeled_input("Password", initial_password, password=True)
        body_lay.addLayout(lay_lbl)
        body_lay.addLayout(lay_usr)
        body_lay.addLayout(lay_pwd)

        # Actions
        acts = QHBoxLayout()
        acts.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid rgba(255,255,255,0.15);"
            " color: #cfd6e6; border-radius: 5px; padding: 6px 14px; font-size: 12px; }"
        )
        # Qt's default autoDefault=True on every QPushButton in a QDialog can
        # hijack Enter so pressing Return in a QLineEdit triggers Cancel
        # rather than the Save button marked setDefault(True).
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.clicked.connect(self.reject)
        acts.addWidget(self.cancel_btn)
        self.save_btn = QPushButton("Save")
        self.save_btn.setStyleSheet(
            "QPushButton { background: #0077ff; color: white; border: none;"
            " border-radius: 5px; padding: 6px 14px; font-size: 12px; font-weight: 600; }"
        )
        self.save_btn.setAutoDefault(True)
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._on_save)
        acts.addWidget(self.save_btn)
        body_lay.addLayout(acts)

        outer.addWidget(body)
        self.setStyleSheet("QDialog { background: #1a2236; }")

    def _on_save(self) -> None:
        if self._mode == "add":
            ok = True
            if not self.username_input.text().strip():
                self.username_error.setText("Username is required")
                self.username_error.setVisible(True)
                ok = False
            if not self.password_input.text().strip():
                self.password_error.setText("Password is required")
                self.password_error.setVisible(True)
                ok = False
            if not ok:
                return
        self.account_saved.emit(
            self.label_input.text(),
            self.username_input.text(),
            self.password_input.text(),
        )
        self.accept()
