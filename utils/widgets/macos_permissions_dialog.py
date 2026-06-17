"""First-run macOS permissions dialog. Translocation-gated: if the app is not
in a stable location, it asks the user to move it before any TCC request."""
from __future__ import annotations
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget)
from utils import macos_clt
from utils import macos_permissions as mp

_LABELS = {"accessibility": "Accessibility", "input_monitoring": "Input Monitoring"}
# clt_state() forks xcode-select, so the 1s refresh timer must not re-probe it
# every tick; cache like the backend's _CLT_TTL. CLT install is a multi-minute
# GUI flow, so a few seconds of staleness is invisible to the user.
_CLT_PROBE_TTL = 5.0


class MacOSPermissionsDialog(QDialog):
    def __init__(self, manager: mp.PermissionManager, location_ok: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("macOS Permissions")
        self._m = manager
        self._location_ok = location_ok
        self._rows = {}
        self._clt_cache = None  # (monotonic_ts, present): TTL-cache the xcode-select fork
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
        # Command Line Tools row (mouse Click Sync only - NOT a keyboard gate).
        # The platform-binary mouse helper runs the CLT python3; keyboard
        # forwarding is unaffected, so this row never blocks the perms above.
        clt_row = QWidget(); ch = QHBoxLayout(clt_row)
        left = QWidget(); lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(0)
        clt_name = QLabel("Command Line Tools")
        clt_helper = QLabel("Needed for mouse click sync")
        clt_helper.setStyleSheet("color: gray; font-size: 11px;")
        lv.addWidget(clt_name); lv.addWidget(clt_helper)
        self._clt_status = QLabel("…")
        self._clt_btn = QPushButton("Install")
        self._clt_btn.clicked.connect(self._on_clt_install)
        ch.addWidget(left); ch.addStretch(1)
        ch.addWidget(self._clt_status); ch.addWidget(self._clt_btn)
        lay.addWidget(clt_row)
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

    def clt_present(self) -> bool:
        """Detection only (xcode-select -p), TTL-cached - NEVER triggers the installer.
        clt_state() forks xcode-select, so it is not re-probed on every 1s refresh tick
        (matches the backend's _CLT_TTL caching of the same call)."""
        now = time.monotonic()
        if self._clt_cache is not None and now - self._clt_cache[0] <= _CLT_PROBE_TTL:
            return self._clt_cache[1]
        present = bool(macos_clt.clt_state()[0])
        self._clt_cache = (now, present)
        return present

    def _on_clt_install(self):
        macos_clt.open_clt_installer()
        self.refresh()

    def _refresh_clt(self):
        present = self.clt_present()
        self._clt_status.setText("Installed" if present else "Not installed")
        self._clt_btn.setText("Installed" if present else "Install")
        self._clt_btn.setEnabled(not present)

    def refresh(self):
        for perm, (status, btn) in self._rows.items():
            st = self._m.next_action(perm)
            status.setText({"granted": "Granted",
                            "request": "Not granted",
                            "open_settings": "Open Settings"}.get(st, st))
            btn.setText("Granted" if st == "granted" else
                        ("Grant" if st == "request" else "Open Settings"))
            btn.setEnabled(self._location_ok and st != "granted")
        self._refresh_clt()
