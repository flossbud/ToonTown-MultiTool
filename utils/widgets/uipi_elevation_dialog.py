"""Modal shown when a background game runs elevated and Windows blocks TTMT from
sending it input. Offers an elevated restart, a remediation explainer, and
dismissal options."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

_BODY = (
    "One of your games is running as administrator, so Windows is blocking "
    "ToonTown MultiTool from sending it movement. To control your toons "
    "together, run MultiTool with the same access."
)
_REMEDIATION = (
    "Prefer not to use administrator access? Close the game, right click its "
    "shortcut, open Properties, and turn off 'Run this program as an "
    "administrator', then start the game again. You can also leave that setting "
    "off in the launcher."
)


class UipiElevationDialog(QDialog):
    restart_as_admin = Signal()
    dont_ask_again = Signal()

    def __init__(self, affected_toons=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Background toons can't move")
        self.setModal(True)
        self.setMinimumWidth(440)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)

        self._title = QLabel("Background toons can't move together")
        self._title.setStyleSheet("color:#fff; font-weight:700; font-size:14px;")
        outer.addWidget(self._title)

        self._body = QLabel(_BODY)
        self._body.setWordWrap(True)
        self._body.setStyleSheet("color:#c4d0e4; font-size:12px;")
        outer.addWidget(self._body)

        if affected_toons:
            self._affected = QLabel("Affected: " + ", ".join(affected_toons))
            self._affected.setStyleSheet("color:#8a9bb8; font-size:11px;")
            outer.addWidget(self._affected)

        self._remediation = QLabel(_REMEDIATION)
        self._remediation.setWordWrap(True)
        self._remediation.setStyleSheet("color:#8a9bb8; font-size:11px;")
        self._remediation.setVisible(False)
        outer.addWidget(self._remediation)

        row = QHBoxLayout()
        self._why_btn = QPushButton("Why is this happening?")
        self._dont_ask_btn = QPushButton("Don't ask again")
        self._not_now_btn = QPushButton("Not now")
        self._restart_btn = QPushButton("Restart as administrator")
        self._restart_btn.setDefault(True)
        row.addWidget(self._why_btn)
        row.addStretch()
        row.addWidget(self._dont_ask_btn)
        row.addWidget(self._not_now_btn)
        row.addWidget(self._restart_btn)
        outer.addLayout(row)

        self._why_btn.clicked.connect(lambda: self._remediation.setVisible(True))
        self._restart_btn.clicked.connect(self.restart_as_admin.emit)
        self._restart_btn.clicked.connect(self.accept)
        self._not_now_btn.clicked.connect(self.reject)
        self._dont_ask_btn.clicked.connect(self.dont_ask_again.emit)
        self._dont_ask_btn.clicked.connect(self.reject)
