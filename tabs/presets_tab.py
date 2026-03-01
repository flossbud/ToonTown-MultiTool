from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame
)
from PySide6.QtCore import Qt, Signal
from utils.theme_manager import resolve_theme, get_theme_colors


class PresetsTab(QWidget):
    save_preset_requested = Signal(int)
    load_preset_requested = Signal(int)

    def __init__(self, settings_manager=None):
        super().__init__()
        self.settings_manager = settings_manager
        self.dot_states = {i: False for i in range(1, 6)}

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(14)

        self.rows = []
        for i in range(1, 6):
            row = self._create_preset_row(i)
            layout.addWidget(row)
            self.rows.append(row)

        self.tip = QLabel("Tip: Press Ctrl + 1–5 to quickly load a preset")
        self.tip.setAlignment(Qt.AlignHCenter)
        layout.addWidget(self.tip)

        layout.addStretch()
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

    def _c(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

    def refresh_theme(self):
        c = self._c()
        self.setStyleSheet(f"background-color: {c['bg_app']}; color: {c['text_primary']};")
        self.tip.setStyleSheet(f"font-size: 11px; color: {c['text_muted']}; margin-top: 8px; background: transparent;")

        for i, row in enumerate(self.rows, 1):
            row.setStyleSheet(f"""
                QFrame {{
                    background-color: {c['bg_card']};
                    border-radius: 8px;
                    border: 1px solid {c['border_card']};
                }}
            """)
            label = row.findChild(QLabel, f"preset_label_{i}")
            if label:
                label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {c['text_primary']};")

            dot = row.findChild(QLabel, f"preset_dot_{i}")
            if dot:
                dot_color = c['accent_green_border'] if self.dot_states[i] else c['text_muted']
                dot.setStyleSheet(f"""
                    background-color: {dot_color};
                    border-radius: 6px;
                    margin-left: 4px;
                    margin-right: 4px;
                """)

            for btn_name in (f"save_btn_{i}", f"load_btn_{i}"):
                btn = row.findChild(QPushButton, btn_name)
                if btn:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {c['btn_bg']};
                            color: {c['text_primary']};
                            border-radius: 6px;
                            padding: 4px 10px;
                            border: 1px solid {c['btn_border']};
                        }}
                        QPushButton:hover {{
                            background-color: {c['btn_hover']};
                            border: 1px solid {c['accent_green_subtle']};
                        }}
                    """)

    def set_preset_dot_state(self, index, active: bool):
        self.dot_states[index] = active
        self.refresh_theme()