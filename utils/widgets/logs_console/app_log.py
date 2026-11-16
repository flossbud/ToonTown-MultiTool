"""AppLogConsole: the app's logger and the Logs surface it fills.

The window logs through append_log(message, level=None). Lines are kept only
while `logging_enabled` is on (the Verbose logging / Enable Logging setting),
except credential diagnostics ("[Credentials]", "[CredentialsManager]"),
which are always captured so keyring problems can be inspected. The lines
show in the LogsCard it holds (`.card`), which the launchpad's Settings
sheet mounts as its Logs tab.

Moved from tabs/debug_tab.py (the old window's hidden Logs tab), which
re-exports it as DebugTab.
"""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from utils.widgets.logs_console.logs_card import LogsCard


class AppLogConsole(QWidget):
    def __init__(self):
        super().__init__()
        self.logging_enabled = False
        lay = QVBoxLayout(self)
        # LogsCard owns the EDGE_PAD-compensated margins; nothing extra here.
        lay.setContentsMargins(0, 0, 0, 0)
        self.card = LogsCard(self)
        lay.addWidget(self.card)

    def append_log(self, message: str, level: str | None = None):
        is_credentials = any(tag in message for tag in
                             ("[Credentials]", "[CredentialsManager]"))
        if not self.logging_enabled and not is_credentials:
            return
        self.card.append(message, level=level)

    def apply_theme(self, is_dark: bool):
        self.card.apply_theme(is_dark)
