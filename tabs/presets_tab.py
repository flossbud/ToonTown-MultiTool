from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame
)
from PySide6.QtCore import Qt, Signal
from utils.theme_manager import resolve_theme


class PresetsTab(QWidget):
    save_preset_requested = Signal(int)
    load_preset_requested = Signal(int)

    def __init__(self, settings_manager=None):
        super().__init__()
        self.settings_manager = settings_manager
        self.dot_states = {i: False for i in range(1, 6)}  # Preset active/inactive state

        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        self.layout.setContentsMargins(30, 30, 30, 30)
        self.layout.setSpacing(14)

        #self.title = QLabel("Presets")
        #self.title.setAlignment(Qt.AlignHCenter)
        #self.layout.addWidget(self.title)

        self.rows = []
        for i in range(1, 6):
            row = self._create_preset_row(i)
            self.layout.addWidget(row)
            self.rows.append(row)

        self.tip = QLabel("Tip: Press Ctrl + 1–5 to quickly load a preset")
        self.tip.setAlignment(Qt.AlignHCenter)
        self.layout.addWidget(self.tip)

        self.layout.addStretch()
        self.refresh_theme()

    def _create_preset_row(self, index):
        row = QFrame()
        row.setObjectName(f"preset_row_{index}")
        row.setMinimumHeight(48)

        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 6, 12, 6)
        row_layout.setSpacing(10)

        label = QLabel(f"Preset {index}")
        label.setObjectName(f"preset_label_{index}")
        row_layout.addWidget(label)

        dot = QLabel()
        dot.setObjectName(f"preset_dot_{index}")
        dot.setFixedSize(12, 12)
        row_layout.addWidget(dot)

        row_layout.addStretch()

        save_btn = QPushButton("💾 Save")
        load_btn = QPushButton("📂 Load")
        save_btn.setObjectName(f"save_btn_{index}")
        load_btn.setObjectName(f"load_btn_{index}")
        save_btn.setFixedSize(90, 28)
        load_btn.setFixedSize(90, 28)
        save_btn.clicked.connect(lambda _, i=index: self.save_preset_requested.emit(i))
        load_btn.clicked.connect(lambda _, i=index: self.load_preset_requested.emit(i))
        row_layout.addWidget(save_btn)
        row_layout.addWidget(load_btn)

        return row

    def refresh_theme(self):
        theme = resolve_theme(self.settings_manager) if self.settings_manager else "dark"
        is_dark = theme == "dark"

        bg_color = "#2e2e2e" if is_dark else "#f6f6f6"
        card_bg = "#3a3a3a" if is_dark else "#ffffff"
        border = "#555" if is_dark else "#ccc"
        text_color = "#eeeeee" if is_dark else "#222222"
        tip_color = "#888888" if is_dark else "#666666"
        dot_off = "#666666" if is_dark else "#bbbbbb"
        dot_on = "#56c856"
        button_bg = "#4a4a4a" if is_dark else "#e0e0e0"
        button_border = "#666" if is_dark else "#aaa"
        button_hover = "#5a5a5a" if is_dark else "#d0ffd0"

        self.setStyleSheet(f"background-color: {bg_color}; color: {text_color};")
        #self.title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {text_color};")
        self.tip.setStyleSheet(f"font-size: 11px; color: {tip_color}; margin-top: 8px; background: transparent;")


        for i, row in enumerate(self.rows, 1):
            row.setStyleSheet(f"""
                QFrame {{
                    background-color: {card_bg};
                    border-radius: 8px;
                    border: 1px solid {border};
                }}
            """)
            label = row.findChild(QLabel, f"preset_label_{i}")
            if label:
                label.setStyleSheet(f"""
                    font-size: 14px;
                    font-weight: 600;
                    color: {text_color};
                """)
            dot = row.findChild(QLabel, f"preset_dot_{i}")
            if dot:
                dot.setStyleSheet(f"""
                    background-color: {dot_on if self.dot_states[i] else dot_off};
                    border-radius: 6px;
                    margin-left: 4px;
                    margin-right: 4px;
                """)
            for btn_name in [f"save_btn_{i}", f"load_btn_{i}"]:
                btn = row.findChild(QPushButton, btn_name)
                if btn:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {button_bg};
                            color: {text_color};
                            border-radius: 6px;
                            padding: 4px 10px;
                            border: 1px solid {button_border};
                        }}
                        QPushButton:hover {{
                            background-color: {button_hover};
                            border: 1px solid #80c080;
                        }}
                    """)

    def set_preset_dot_state(self, index, active: bool):
        self.dot_states[index] = active
        self.refresh_theme()  # Full redraw with new dot state
