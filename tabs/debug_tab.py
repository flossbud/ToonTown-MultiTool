from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QLabel, QGraphicsDropShadowEffect, QStackedWidget
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt
from datetime import datetime
from utils.shared_widgets import IOSSegmentedControl


class DebugTab(QWidget):
    def __init__(self):
        super().__init__()
        self.logging_enabled = False
        from PySide6.QtWidgets import QFrame
        from utils.layout import clamp_centered

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        content = QFrame()
        layout = QVBoxLayout(content)

        header_lay = QHBoxLayout()
        header_lay.addWidget(QLabel("Logs", styleSheet="font-weight: bold; font-size: 14px;"))
        header_lay.addStretch()

        self.segment = IOSSegmentedControl(["Raw Terminal", "Input Service", "TTR API"])
        self.segment.setFixedWidth(340)
        self.segment.index_changed.connect(self._on_tab_changed)
        header_lay.addWidget(self.segment)
        layout.addLayout(header_lay)

        self.stack = QStackedWidget()
        self.logs_raw = self._create_log_widget()
        self.logs_input = self._create_log_widget()
        self.logs_api = self._create_log_widget()

        self.stack.addWidget(self.logs_raw)
        self.stack.addWidget(self.logs_input)
        self.stack.addWidget(self.logs_api)
        layout.addWidget(self.stack)

        clamp_centered(outer, content, 720)

    def _create_log_widget(self):
        w = QPlainTextEdit(readOnly=True)
        w.setStyleSheet("""
            font-family: monospace;
            font-size: 11px;
            background-color: #1e1e1e;
            color: #ccc;
            border: 1px solid #444;
            border-radius: 6px;
        """)
        shadow = QGraphicsDropShadowEffect(w)
        shadow.setColor(QColor(0, 0, 0, 70))
        shadow.setBlurRadius(14)
        shadow.setOffset(0, 2)
        w.setGraphicsEffect(shadow)
        return w

    def _on_tab_changed(self, idx):
        self.stack.setCurrentIndex(idx)

    def append_log(self, message: str):
        # Credential/keyring diagnostics always pass through so AppImage users
        # can inspect keyring behavior even when the debug tab is otherwise
        # hidden at startup.
        is_credentials = any(tag in message for tag in ("[Credentials]", "[CredentialsManager]"))
        if not self.logging_enabled and not is_credentials:
            return
        # Fix #9: Clearer timestamp format — brackets outside the format spec
        ts = f"[{datetime.now():%H:%M:%S}] "
        full_msg = ts + message

        # Route to Input Service Subtab (excluded from Raw Terminal)
        if any(tag in message for tag in ("[Input]", "[KeepAlive]", "[Hotkey]", "[Service]")):
            self.logs_input.appendPlainText(full_msg)
            self.logs_input.verticalScrollBar().setValue(self.logs_input.verticalScrollBar().maximum())
            return

        # Route to TTR API Subtab (excluded from Raw Terminal)
        if any(tag in message for tag in ("[TTR API]", "[Profile]", "[Launch]")):
            self.logs_api.appendPlainText(full_msg)
            self.logs_api.verticalScrollBar().setValue(self.logs_api.verticalScrollBar().maximum())
            return

        # Route everything else to Raw Terminal
        self.logs_raw.appendPlainText(full_msg)
        self.logs_raw.verticalScrollBar().setValue(self.logs_raw.verticalScrollBar().maximum())