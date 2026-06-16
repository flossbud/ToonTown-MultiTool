"""First-run macOS permissions dialog. Translocation-gated: if the app is not
in a stable location, it asks the user to move it before any TCC request."""
from __future__ import annotations
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget)
from utils import macos_permissions as mp

_LABELS = {"accessibility": "Accessibility", "input_monitoring": "Input Monitoring"}


class MacOSPermissionsDialog(QDialog):
    def __init__(self, manager: mp.PermissionManager, location_ok: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("macOS Permissions")
        self._m = manager
        self._location_ok = location_ok
        self._rows = {}
        lay = QVBoxLayout(self)
        if not location_ok:
            warn = QLabel(
                "Move ToonTown MultiTool into your Applications folder, then "
                "reopen it. Permissions only stick when the app runs from "
                "Applications.")
            warn.setWordWrap(True)
            lay.addWidget(warn)
        intro = QLabel(
            "ToonTown MultiTool needs these permissions to control your "
            "background toons. Beta and stable are separate apps, so each "
            "needs its own grant. After you enable Input Monitoring in System "
            "Settings, restart ToonTown MultiTool for it to take effect.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        for perm in mp.PermissionManager.PERMS:
            row = QWidget(); h = QHBoxLayout(row)
            name = QLabel(_LABELS[perm]); status = QLabel("…")
            btn = QPushButton("Grant")
            btn.setEnabled(location_ok)
            btn.clicked.connect(lambda _=False, p=perm: self._on_grant(p))
            h.addWidget(name); h.addStretch(1); h.addWidget(status); h.addWidget(btn)
            lay.addWidget(row)
            self._rows[perm] = (status, btn)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        lay.addWidget(close)
        self._timer = QTimer(self); self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh); self._timer.start()
        self.refresh()

    def is_move_required(self) -> bool:
        return not self._location_ok

    def row_state(self, perm) -> str:
        return self._m.next_action(perm)

    def _on_grant(self, perm):
        action = self._m.next_action(perm)
        if action == "request":
            self._m.request(perm)
        else:
            mp.open_settings(perm)
        self.refresh()

    def refresh(self):
        for perm, (status, btn) in self._rows.items():
            st = self._m.next_action(perm)
            status.setText({"granted": "Granted",
                            "request": "Not granted",
                            "open_settings": "Open Settings"}.get(st, st))
            btn.setText("Granted" if st == "granted" else
                        ("Grant" if st == "request" else "Open Settings"))
            btn.setEnabled(self._location_ok and st != "granted")
