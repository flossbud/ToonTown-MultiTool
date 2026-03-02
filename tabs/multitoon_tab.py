import queue

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QSpacerItem, QSizePolicy, QFrame
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from services.input_service import InputService
from utils.theme_manager import resolve_theme, get_theme_colors, make_chat_icon, make_refresh_icon
from utils.symbols import S
from utils.ttr_api import get_toon_names_threaded, invalidate_port_to_wid_cache


class MultitoonTab(QWidget):
    _toon_names_ready = Signal(list)
    def __init__(self, logger=None, settings_manager=None):
        super().__init__()
        self.logger = logger
        self.settings_manager = settings_manager
        self.service_running = False
        self.toon_labels = []
        self.toon_buttons = []
        self.chat_buttons = []
        self.movement_dropdowns = []
        self.toon_cards = []
        self.enabled_toons = [False] * 4
        self.chat_enabled  = [True]  * 4
        self.toon_names       = [None] * 4
        self._refresh_gen     = 0
        self._last_window_ids = []

        self.key_event_queue = queue.Queue()

        self.build_ui()

        self.input_service = InputService(
            get_enabled_toons=self.get_enabled_toons,
            get_movement_modes=self.get_movement_modes,
            get_event_queue_func=self.get_key_event_queue,
            get_chat_enabled=self.get_chat_enabled,
            settings_manager=settings_manager
        )
        self.input_service.window_ids_updated.connect(self.update_toon_controls)
        self._toon_names_ready.connect(self._apply_toon_names)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(5000)
        self.refresh_timer.timeout.connect(self._auto_refresh)

        self.refresh_theme()
        self.apply_all_visual_states()

    def build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(16, 12, 16, 12)
        outer_layout.setSpacing(0)

        self.outer_card = QFrame()
        outer_card_layout = QVBoxLayout(self.outer_card)
        outer_card_layout.setContentsMargins(16, 16, 16, 16)
        outer_card_layout.setSpacing(10)

        self.service_label = QLabel("Service Controls")
        outer_card_layout.addWidget(self.service_label)

        self.toggle_service_button = QPushButton("Start Service")
        self.toggle_service_button.setCheckable(True)
        self.toggle_service_button.clicked.connect(self.toggle_service)
        self.toggle_service_button.setFixedHeight(38)
        outer_card_layout.addWidget(self.toggle_service_button)

        self.status_label = QLabel("Service idle")
        self.status_label.setAlignment(Qt.AlignLeft)
        outer_card_layout.addWidget(self.status_label)

        config_row = QHBoxLayout()
        config_row.setSpacing(8)
        self.config_label = QLabel("Toon Configuration")
        config_row.addWidget(self.config_label)
        config_row.addStretch()
        self.refresh_button = QPushButton()
        self.refresh_button.setIcon(make_refresh_icon(14))
        self.refresh_button.setFixedSize(26, 26)
        self.refresh_button.setToolTip("Refresh toon windows and names")
        self.refresh_button.clicked.connect(self.manual_refresh)
        config_row.addWidget(self.refresh_button)
        outer_card_layout.addLayout(config_row)

        for i in range(4):
            card = QFrame()
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(12, 12, 12, 12)
            card_layout.setSpacing(10)

            name_label   = QLabel(f"Toon {i+1}")
            status_label = QLabel()
            status_label.setFixedSize(10, 10)
            status_label.setToolTip("Not Found")
            self.toon_labels.append((name_label, status_label))
            card_layout.addWidget(name_label)
            card_layout.addWidget(status_label)

            card_layout.addStretch()

            btn = QPushButton("Enable")
            btn.setCheckable(True)
            btn.setFixedHeight(36)
            btn.setFixedWidth(90)
            btn.clicked.connect(lambda checked, idx=i: self.toggle_toon(idx))
            self.toon_buttons.append(btn)
            card_layout.addWidget(btn)

            chat_btn = QPushButton()
            chat_btn.setCheckable(True)
            chat_btn.setChecked(True)
            chat_btn.setFixedHeight(36)
            chat_btn.setFixedWidth(36)
            chat_btn.setIcon(make_chat_icon(16))
            chat_btn.setToolTip("Toggle chat broadcasting for this toon")
            chat_btn.clicked.connect(lambda checked, idx=i: self.toggle_chat(idx))
            self.chat_buttons.append(chat_btn)
            card_layout.addWidget(chat_btn)

            dropdown = QComboBox()
            dropdown.addItems(["WASD", "ARROWS"])
            dropdown.setFixedHeight(36)
            dropdown.setFixedWidth(92)
            dropdown.setToolTip("Movement keys for this toon.")
            self.movement_dropdowns.append(dropdown)
            card_layout.addWidget(dropdown)

            self.toon_cards.append(card)
            outer_card_layout.addWidget(card)

        outer_card_layout.addStretch()
        outer_layout.addWidget(self.outer_card)
        outer_layout.addStretch()

        self.update_service_button_style()
        self.update_status_label()

    def _c(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

    def refresh_theme(self):
        c = self._c()

        self.outer_card.setStyleSheet(f"""
            QFrame {{
                background-color: {c['bg_card']};
                border-radius: 12px;
                border: 1px solid {c['border_card']};
            }}
        """)
        self.service_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {c['text_secondary']}; background: none; border: none;"
        )
        self.config_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {c['text_secondary']}; background: none; border: none; margin-top: 4px;"
        )
        self.refresh_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {c['btn_bg']};
                color: {c['text_secondary']};
                border: 1px solid {c['btn_border']};
                border-radius: 6px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {c['toon_btn_inactive_hover']};
                border: 1px solid {c['accent_blue']};
            }}
        """)

        for i, card in enumerate(self.toon_cards):
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {c['bg_card_inner']};
                    border-radius: 8px;
                    border: 1px solid {c['border_muted']};
                }}
            """)
            name_label, status_label = self.toon_labels[i]
            name_label.setStyleSheet(
                f"font-size: 13px; font-weight: bold; color: {c['text_primary']}; background: none; border: none;"
            )

        self.apply_all_visual_states()
        self.update_status_label()

    def apply_visual_state(self, index):
        c = self._c()
        name_label, status_label = self.toon_labels[index]
        btn      = self.toon_buttons[index]
        chat_btn = self.chat_buttons[index]
        dropdown = self.movement_dropdowns[index]
        window_available = index < len(self.input_service.window_ids)

        active = window_available and self.enabled_toons[index] and self.service_running
        if active:
            status_label.setToolTip("Connected")
            status_label.setStyleSheet("background-color: #56c856; border-radius: 5px; border: none;")
        elif window_available:
            status_label.setToolTip("Found — not enabled")
            status_label.setStyleSheet("background-color: #888888; border-radius: 5px; border: none;")
        else:
            status_label.setToolTip("Not Found")
            status_label.setStyleSheet("background-color: #555555; border-radius: 5px; border: none;")

        disabled_dropdown = f"""
            QComboBox {{
                padding: 4px 8px; border-radius: 6px;
                background-color: {c['bg_input_dark']};
                color: {c['text_muted']};
                border: 1px solid {c['border_muted']};
            }}
        """
        enabled_dropdown = f"""
            QComboBox {{
                padding: 4px 8px; border-radius: 6px;
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

        service_and_window = self.service_running and window_available

        if not service_and_window:
            btn.setEnabled(False)
            btn.setText("Enable")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['btn_disabled']};
                    color: {c['text_disabled']};
                    border: none; border-radius: 6px;
                    font-size: 12px;
                }}
            """)
            chat_btn.setEnabled(False)
            chat_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['btn_disabled']};
                    color: {c['text_disabled']};
                    border: none; border-radius: 6px;
                    font-size: 13px;
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
                    color: white; font-size: 12px; font-weight: bold;
                    border: 2px solid {c['accent_green_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['accent_green_hover']};
                    border: 2px solid {c['accent_green_hover_border']};
                }}
            """)
            self._apply_chat_btn_style(index, c)
            dropdown.setEnabled(True)
            dropdown.setStyleSheet(enabled_dropdown)

        else:
            btn.setEnabled(True)
            btn.setText("Enable")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['toon_btn_inactive_bg']};
                    color: {c['text_primary']}; font-size: 12px;
                    border: 1px solid {c['toon_btn_inactive_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['toon_btn_inactive_hover']};
                    border: 1px solid {c['toon_btn_inactive_hover_border']};
                }}
            """)
            self._apply_chat_btn_style(index, c)
            dropdown.setEnabled(True)
            dropdown.setStyleSheet(enabled_dropdown)

    def _apply_chat_btn_style(self, index, c):
        chat_btn = self.chat_buttons[index]
        chat_btn.setEnabled(True)
        if self.chat_enabled[index]:
            chat_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['accent_blue_btn']};
                    color: white;
                    border: 2px solid {c['accent_blue_btn_border']};
                    border-radius: 6px;
                    font-size: 13px;
                }}
                QPushButton:hover {{
                    background-color: {c['accent_blue_btn_hover']};
                    border: 2px solid {c['accent_blue_btn_border']};
                }}
            """)
        else:
            chat_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['toon_btn_inactive_bg']};
                    color: {c['text_muted']};
                    border: 1px solid {c['toon_btn_inactive_border']};
                    border-radius: 6px;
                    font-size: 13px;
                }}
                QPushButton:hover {{
                    background-color: {c['toon_btn_inactive_hover']};
                    border: 1px solid {c['toon_btn_inactive_hover_border']};
                }}
            """)

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
            self.status_label.setText(f"{S('✅', '✔')} Sending input to {count} toon{'s' if count != 1 else ''}")
            self.status_label.setStyleSheet(base + f"background-color: {c['status_success_bg']}; color: {c['status_success_text']}; border-left: 6px solid {c['status_success_border']}; }}")
        elif self.service_running:
            self.status_label.setText(f"{S('⚠️', '⚠')} Service running — no toons enabled")
            self.status_label.setStyleSheet(base + f"background-color: {c['status_warning_bg']}; color: {c['status_warning_text']}; border-left: 6px solid {c['status_warning_border']}; }}")
        else:
            self.status_label.setText(f"{S('⏸️', '◼')} Service idle")
            self.status_label.setStyleSheet(base + f"background-color: {c['status_idle_bg']}; color: {c['status_idle_text']}; border-left: 6px solid {c['status_idle_border']}; }}")

    def _fetch_names_if_enabled(self, num_slots: int):
        if self.settings_manager and self.settings_manager.get("enable_companion_app", True):
            self._refresh_gen += 1
            gen = self._refresh_gen
            def _callback(names):
                if gen == self._refresh_gen:
                    self._on_toon_names_received(names)
            get_toon_names_threaded(num_slots, _callback,
                                    list(self.input_service.window_ids))

    def manual_refresh(self):
        invalidate_port_to_wid_cache()
        self.input_service.assign_windows()
        self._fetch_names_if_enabled(4)
        self.log("[Service] Manual refresh triggered.")

    def _auto_refresh(self):
        self.input_service.assign_windows()
        self._fetch_names_if_enabled(4)

    def toggle_service(self):
        self.service_running = not self.service_running
        if self.service_running:
            self._start_service_internal()
        else:
            self.input_service.stop()
            self.refresh_timer.stop()
            self.disable_all_toon_controls()
            self.log("[Service] Multitoon service stopped.")
        self.update_service_button_style()

    def _start_service_internal(self):
        self.input_service.start()
        self.log("[Service] Multitoon service started.")
        for i in range(4):
            if i < len(self.input_service.window_ids):
                self.enabled_toons[i] = True
                self.chat_enabled[i]  = True
                self.toon_buttons[i].setChecked(True)
                self.chat_buttons[i].setChecked(True)
                self.apply_visual_state(i)
        self.update_status_label()
        self.refresh_timer.start()

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
            self.chat_buttons[i].setChecked(True)
            self.enabled_toons[i] = False
            self.chat_enabled[i]  = True
            self.toon_names[i]    = None
            self.apply_visual_state(i)
        self._refresh_toon_name_labels()
        self.update_status_label()

    def toggle_toon(self, index):
        self.enabled_toons[index] = not self.enabled_toons[index]
        self.toon_buttons[index].setChecked(self.enabled_toons[index])
        self.apply_visual_state(index)
        self.update_status_label()

    def toggle_chat(self, index):
        self.chat_enabled[index] = not self.chat_enabled[index]
        self.chat_buttons[index].setChecked(self.chat_enabled[index])
        self.apply_visual_state(index)

    def set_toon_enabled(self, index, enabled: bool):
        self.enabled_toons[index] = enabled
        self.toon_buttons[index].setChecked(enabled)
        self.apply_visual_state(index)
        self.update_status_label()

    def update_toon_controls(self, window_ids):
        ids_changed = window_ids != self._last_window_ids
        self._last_window_ids = list(window_ids)

        if ids_changed:
            invalidate_port_to_wid_cache()

        for i in range(4):
            # Only reset toons that are no longer connected
            if i >= len(window_ids):
                self.enabled_toons[i] = False
                self.chat_enabled[i]  = True
                self.toon_buttons[i].setChecked(False)
                self.chat_buttons[i].setChecked(True)
            # Auto-enable newly discovered toons if service is running
            elif self.service_running and not self.enabled_toons[i]:
                self.enabled_toons[i] = True
                self.toon_buttons[i].setChecked(True)
            self.apply_visual_state(i)
        self.update_status_label()
        self._fetch_names_if_enabled(len(window_ids))

    def _on_toon_names_received(self, names: list):
        """Called from background thread — deliver names to main thread via signal."""
        self._toon_names_ready.emit(list(names))

    @Slot(list)
    def _apply_toon_names(self, names: list):
        """Apply names and refresh labels — always runs on the main thread."""
        for i, name in enumerate(names):
            self.toon_names[i] = name
        self._refresh_toon_name_labels()

    @Slot()
    def _refresh_toon_name_labels(self):
        c = self._c()
        for i, (name_label, _) in enumerate(self.toon_labels):
            display = self.toon_names[i] if self.toon_names[i] else f"Toon {i + 1}"
            name_label.setText(display)
            name_label.setStyleSheet(
                f"font-size: 13px; font-weight: bold; color: {c['text_primary']}; background: none; border: none;"
            )

    def get_enabled_toons(self):
        return self.enabled_toons

    def get_chat_enabled(self):
        return self.chat_enabled

    def get_movement_modes(self):
        return [dropdown.currentText() for dropdown in self.movement_dropdowns]

    def get_key_event_queue(self):
        return self.key_event_queue

    def log(self, msg):
        if self.logger:
            self.logger.append_log(msg)
        else:
            print(msg)