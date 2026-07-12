"""Hidden Logs tab — thin shell over the Logs V2 diagnostics console.
Keeps the historical contract every caller relies on: the `logging_enabled`
attribute, `append_log(message)` (now with optional `level`), and the
credential-diagnostics passthrough (credential lines are captured even
before Enable Logging is on, so AppImage users can inspect keyring
behavior)."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from utils.widgets.logs_console.logs_card import LogsCard


class DebugTab(QWidget):
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
