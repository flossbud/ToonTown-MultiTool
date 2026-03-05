from PySide6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit, QLabel, QGraphicsDropShadowEffect
from PySide6.QtGui import QColor
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
            border-radius: 6px;
        """)
        shadow = QGraphicsDropShadowEffect(self.log_output)
        shadow.setColor(QColor(0, 0, 0, 70))
        shadow.setBlurRadius(14)
        shadow.setOffset(0, 2)
        self.log_output.setGraphicsEffect(shadow)
        layout.addWidget(self.log_output)

    def append_log(self, message: str):
        # Fix #9: Clearer timestamp format — brackets outside the format spec
        self.log_output.appendPlainText(f"[{datetime.now():%H:%M:%S}] {message}")
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())