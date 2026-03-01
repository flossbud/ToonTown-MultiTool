from PySide6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit, QLabel
from datetime import datetime


class DebugTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Debug Log", styleSheet="font-weight: bold; font-size: 14px;"))

        self.log_output = QPlainTextEdit(readOnly=True)
        self.log_output.setStyleSheet("""
            font-family: monospace;
            font-size: 11px;
            background-color: #1e1e1e;
            color: #ccc;
            border: 1px solid #444;
        """)
        layout.addWidget(self.log_output)

    def append_log(self, message: str):
        self.log_output.appendPlainText(f"{datetime.now():[%H:%M:%S]} {message}")
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())
