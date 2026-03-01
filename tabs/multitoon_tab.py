import queue
import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel,
    QComboBox, QGridLayout, QSpacerItem, QSizePolicy, QFrame
)
from PySide6.QtCore import Qt
from services.input_service import InputService
from utils.theme_manager import resolve_theme, get_theme_colors


class MultitoonTab(QWidget):
    def __init__(self, logger=None, settings_manager=None):
        super().__init__()
        self.logger = logger
        self.settings_manager = settings_manager
        self.service_running = False
        self.toon_labels = []
        self.toon_buttons = []
        self.movement_dropdowns = []
        self.enabled_toons = [False] * 4

        self.key_event_queue = queue.Queue()

        self.build_ui()

        self.input_service = InputService(
            get_enabled_toons=self.get_enabled_toons,
            get_movement_modes=self.get_movement_modes,
            get_event_queue_func=self.get_key_event_queue,
            settings_manager=settings_manager
        )
        self.input_service.window_ids_updated.connect(self.update_toon_controls)

        self.refresh_theme()
        self.apply_all_visual_states()

    def build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(30, 20, 30, 20)
        outer_layout.setSpacing(20)

        self.card = QFrame()
        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setSpacing(16)

        self.service_label = QLabel("Service Controls")
        self.card_layout.addWidget(self.service_label)

        self.toggle_service_button = QPushButton("Start Service")
        self.toggle_service_button.setCheckable(True)
        self.toggle_service_button.clicked.connect(self.toggle_service)
        self.toggle_service_button.setFixedHeight(36)
        self.card_layout.addWidget(self.toggle_service_button)

        self.status_label = QLabel("⏸️ Service idle")
        self.status_label.setAlignment(Qt.AlignLeft)
        self.card_layout.addWidget(self.status_label)

        self.config_label = QLabel("Toon Configuration")
        self.card_layout.addWidget(self.config_label)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(20)
        self.grid.setVerticalSpacing(10)

        for i in range(4):
            frame = QFrame()
            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(0, 0, 0, 0)
            frame_layout.setSpacing(2)

            name_label = QLabel(f"Toon {i+1}")
            status_label = QLabel("⚪ Not Found")
            frame_layout.addWidget(name_label)
            frame_layout.addWidget(status_label)
            self.toon_labels.append((name_label, status_label))

            btn = QPushButton("Enable")
            btn.setCheckable(True)
            btn.setFixedHeight(36)
            btn.clicked.connect(lambda checked, idx=i: self.toggle_toon(idx))
            self.toon_buttons.append(btn)

            dropdown = QComboBox()
            dropdown.addItems(["WASD", "ARROWS"])
            dropdown.setMinimumHeight(28)
            dropdown.setToolTip("Select which keys you will press to control this toon.")
            self.movement_dropdowns.append(dropdown)

            self.grid.addWidget(frame, i, 0)
            self.grid.addWidget(btn, i, 1)
            self.grid.addWidget(dropdown, i, 2)

        self.card_layout.addLayout(self.grid)
        self.card_layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))
        outer_layout.addWidget(self.card)

        self.update_service_button_style()
        self.update_status_label()

    def _c(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

    def refresh_theme(self):
        c = self._c()
        self.card.setStyleSheet(f"""
            QFrame {{
                background-color: {c['bg_card']};
                border-radius: 12px;
                border: 1px solid {c['border_card']};
                padding: 16px;
            }}
        """)
        self.service_label.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {c['text_secondary']};")
        self.config_label.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {c['text_secondary']};")
        for i, (name_label, _) in enumerate(self.toon_labels):
            name_label.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {c['text_primary']}; background: none; border: none;"
            )
            frame = self.grid.itemAtPosition(i, 0).widget()
            frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {c['bg_card_inner']};
                    border: 1px solid {c['border_card']};
                    border-radius: 6px;
                    padding: 6px 8px;
                }}
            """)
        self.apply_all_visual_states()
        self.update_status_label()

    def apply_visual_state(self, index):
        c = self._c()
        name_label, status_label = self.toon_labels[index]
        btn = self.toon_buttons[index]
        dropdown = self.movement_dropdowns[index]
        window_available = index < len(self.input_service.window_ids)

        if window_available:
            status_label.setText("🟢 Connected")
            status_label.setStyleSheet("font-size: 10px; color: #80e080; background: none; border: none;")
        else:
            status_label.setText("⚪ Not Found")
            status_label.setStyleSheet(f"font-size: 10px; color: {c['text_muted']}; background: none; border: none;")

        disabled_dropdown = f"""
            QComboBox {{
                padding: 6px 8px; border-radius: 6px;
                background-color: {c['bg_input_dark']};
                color: {c['text_muted']};
                border: 1px solid {c['border_muted']};
            }}
        """
        enabled_dropdown = f"""
            QComboBox {{
                padding: 6px 8px; border-radius: 6px;
                background-color: {c['dropdown_bg']};
                color: {c['dropdown_text']};
                border: 1px solid {c['dropdown_border']};
            }}
            QComboBox:hover {{ border: 1px solid {c['accent_blue']}; }}
            QComboBox QAbstractItemView {{
                background-color: {c['dropdown_list_bg']};
                color: {c['dropdown_text']};
                selection-background-color: {c['dropdown_sel_bg']};
                selection-color: {c['dropdown_sel_text']};
            }}
        """

        if not self.service_running or not window_available:
            btn.setEnabled(False)
            btn.setText("Enable")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['btn_disabled']};
                    color: {c['text_disabled']};
                    border: none; border-radius: 6px;
                }}
            """)
            dropdown.setEnabled(False)
            dropdown.setStyleSheet(disabled_dropdown)
        elif self.enabled_toons[index]:
            btn.setEnabled(True)
            btn.setText("Enabled")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['accent_green']};
                    color: white;
                    border: 2px solid {c['accent_green_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['accent_green_hover']};
                    border: 2px solid {c['accent_green_hover_border']};
                }}
            """)
            dropdown.setEnabled(True)
            dropdown.setStyleSheet(enabled_dropdown)
        else:
            btn.setEnabled(True)
            btn.setText("Enable")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['toon_btn_inactive_bg']};
                    color: {c['text_primary']};
                    border: 1px solid {c['toon_btn_inactive_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['toon_btn_inactive_hover']};
                    border: 1px solid {c['toon_btn_inactive_hover_border']};
                }}
            """)
            dropdown.setEnabled(True)
            dropdown.setStyleSheet(enabled_dropdown)

    def update_service_button_style(self):
        c = self._c()
        if self.service_running:
            self.toggle_service_button.setText("Stop Service")
            self.toggle_service_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['accent_red']};
                    color: white; font-weight: bold;
                    border: 2px solid {c['accent_red_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['accent_red_hover']};
                    border: 2px solid {c['accent_red_hover_border']};
                }}
            """)
        else:
            self.toggle_service_button.setText("Start Service")
            self.toggle_service_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['accent_green']};
                    color: white; font-weight: bold;
                    border: 2px solid {c['accent_green_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['accent_green_hover']};
                    border: 2px solid {c['accent_green_hover_border']};
                }}
            """)

    def apply_all_visual_states(self):
        for i in range(4):
            self.apply_visual_state(i)

    def update_status_label(self):
        c = self._c()
        count = sum(self.enabled_toons)
        base = "QLabel { font-size: 12px; font-weight: 500; border-radius: 4px; padding: 6px 12px; "
        if self.service_running and count > 0:
            self.status_label.setText(f"✅ Sending input to {count} toon{'s' if count != 1 else ''}")
            self.status_label.setStyleSheet(base + f"background-color: {c['status_success_bg']}; color: {c['status_success_text']}; border-left: 6px solid {c['status_success_border']}; }}")
        elif self.service_running:
            self.status_label.setText("⚠️ Service running (no toons enabled)")
            self.status_label.setStyleSheet(base + f"background-color: {c['status_warning_bg']}; color: {c['status_warning_text']}; border-left: 6px solid {c['status_warning_border']}; }}")
        else:
            self.status_label.setText("⏸️ Service idle")
            self.status_label.setStyleSheet(base + f"background-color: {c['status_idle_bg']}; color: {c['status_idle_text']}; border-left: 6px solid {c['status_idle_border']}; }}")

    def toggle_service(self):
        self.service_running = not self.service_running
        if self.service_running:
            self.input_service.start()
            self.log("[Service] Multitoon service started.")
            for i in range(4):
                if i < len(self.input_service.window_ids):
                    self.enabled_toons[i] = True
                    self.toon_buttons[i].setChecked(True)
                    self.apply_visual_state(i)
            self.update_status_label()
        else:
            self.input_service.stop()
            self.disable_all_toon_controls()
            self.log("[Service] Multitoon service stopped.")
        self.update_service_button_style()

    def start_service(self):
        if not self.service_running:
            self.toggle_service()

    def stop_service(self):
        if self.service_running:
            self.toggle_service()

    def set_service_active(self, active: bool):
        if self.service_running != active:
            self.toggle_service()

    def disable_all_toon_controls(self):
        for i in range(4):
            self.toon_buttons[i].setChecked(False)
            self.enabled_toons[i] = False
            self.apply_visual_state(i)
        self.update_status_label()

    def toggle_toon(self, index):
        self.enabled_toons[index] = not self.enabled_toons[index]
        self.toon_buttons[index].setChecked(self.enabled_toons[index])
        self.apply_visual_state(index)
        self.update_status_label()

    def set_toon_enabled(self, index, enabled: bool):
        self.enabled_toons[index] = enabled
        self.toon_buttons[index].setChecked(enabled)
        self.apply_visual_state(index)
        self.update_status_label()

    def update_toon_controls(self, window_ids):
        for i in range(4):
            self.enabled_toons[i] = False
            self.toon_buttons[i].setChecked(False)
            self.apply_visual_state(i)
        self.update_status_label()

    def get_enabled_toons(self):
        return self.enabled_toons

    def get_movement_modes(self):
        return [dropdown.currentText() for dropdown in self.movement_dropdowns]

    def get_key_event_queue(self):
        return self.key_event_queue

    def log(self, msg):
        if self.logger:
            self.logger.append_log(msg)
        else:
            print(msg)