from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel,
    QComboBox, QGridLayout, QSpacerItem, QSizePolicy, QFrame
)
from PySide6.QtCore import Qt
from pynput import keyboard
from pynput.keyboard import Key
from services.input_service import InputService
from utils.theme_manager import resolve_theme


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
        self.pressed_keys = set()

        self.build_ui()

        self.listener = keyboard.Listener(
            on_press=self.on_global_key_press,
            on_release=self.on_global_key_release
        )
        self.listener.start()

        self.input_service = InputService(
            get_enabled_toons=self.get_enabled_toons,
            get_movement_modes=self.get_movement_modes,
            get_pressed_keys_func=self.get_pressed_keys,
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

    def refresh_theme(self):
        is_dark = resolve_theme(self.settings_manager) == "dark"
        self.card.setStyleSheet(f"QFrame {{ background-color: {'#444' if is_dark else '#fff'}; border-radius: 12px; border: 1px solid {'#555' if is_dark else '#ccc'}; padding: 16px; }}")
        self.service_label.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {'#bbb' if is_dark else '#444'};")
        self.config_label.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {'#bbb' if is_dark else '#444'};")
        for i, (name_label, _) in enumerate(self.toon_labels):
            name_label.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {'#fff' if is_dark else '#000'}; background: none; border: none;")
            frame = self.grid.itemAtPosition(i, 0).widget()
            frame.setStyleSheet(f"QFrame {{ background-color: {'#3a3a3a' if is_dark else '#f0f0f0'}; border: 1px solid {'#555' if is_dark else '#aaa'}; border-radius: 6px; padding: 6px 8px; }}")
        self.apply_all_visual_states()
        self.update_status_label()

    def apply_visual_state(self, index):
        is_dark = resolve_theme(self.settings_manager) == "dark"
        name_label, status_label = self.toon_labels[index]
        btn = self.toon_buttons[index]
        dropdown = self.movement_dropdowns[index]
        window_available = index < len(self.input_service.window_ids)

        if window_available:
            status_label.setText("🟢 Connected")
            status_label.setStyleSheet("font-size: 10px; color: #80e080; background: none; border: none;")
        else:
            status_label.setText("⚪ Not Found")
            status_label.setStyleSheet("font-size: 10px; color: #888888; background: none; border: none;")

        disabled_style = (
            "QComboBox { padding: 6px 8px; border-radius: 6px; background-color: "
            + ("#2a2a2a; color: #888; border: 1px solid #444;" if is_dark else "#eeeeee; color: #888; border: 1px solid #aaa;") +
            " }"
        )
        enabled_style = (
            "QComboBox { padding: 6px 8px; border-radius: 6px; background-color: "
            + ("#3a3a3a; color: white; border: 1px solid #666;" if is_dark else "#ffffff; color: #111; border: 1px solid #999;") +
            "} QComboBox:hover { border: 1px solid " +
            ("#88c0d0;" if is_dark else "#66aa66;") +
            "} QComboBox QAbstractItemView { background-color: " +
            ("#2a2a2a; color: white; selection-background-color: #555; selection-color: white;" if is_dark else "#f8f8f8; color: #111; selection-background-color: #e0e0e0; selection-color: #000;") +
            "}"
        )

        if not self.service_running or not window_available:
            btn.setEnabled(False)
            btn.setText("Enable")
            btn.setStyleSheet(
                "QPushButton { background-color: " + ("#555;" if is_dark else "#e0e0e0;") +
                " color: " + ("#999;" if is_dark else "#888;") +
                " border: none; border-radius: 6px; }"
            )
            dropdown.setEnabled(False)
            dropdown.setStyleSheet(disabled_style)
        elif self.enabled_toons[index]:
            btn.setEnabled(True)
            btn.setText("Enabled")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #3da343;
                    color: white;
                    border: 2px solid #56d66a;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background-color: #4fc95c;
                    border: 2px solid #6ae87d;
                }
            """)
            dropdown.setEnabled(True)
            dropdown.setStyleSheet(enabled_style)
        else:
            btn.setEnabled(True)
            btn.setText("Enable")
            if is_dark:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #666;
                        color: white;
                        border: 1px solid #777;
                        border-radius: 6px;
                    }
                    QPushButton:hover {
                        background-color: #777;
                        border: 1px solid #999;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #f0f0f0;
                        color: #222;
                        border: 1px solid #aaa;
                        border-radius: 6px;
                    }
                    QPushButton:hover {
                        background-color: #e8e8e8;
                        border: 1px solid #888;
                    }
                """)
            dropdown.setEnabled(True)
            dropdown.setStyleSheet(enabled_style)

    def update_service_button_style(self):
        if self.service_running:
            self.toggle_service_button.setText("Stop Service")
            self.toggle_service_button.setStyleSheet("""
                QPushButton {
                    background-color: #b34848;
                    color: white;
                    font-weight: bold;
                    border: 2px solid #d95757;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background-color: #cc5e5e;
                    border: 2px solid #f06868;
                }
            """)
        else:
            self.toggle_service_button.setText("Start Service")
            self.toggle_service_button.setStyleSheet("""
                QPushButton {
                    background-color: #3da343;
                    color: white;
                    font-weight: bold;
                    border: 2px solid #56d66a;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background-color: #4fc95c;
                    border: 2px solid #6ae87d;
                }
            """)

    def apply_all_visual_states(self):
        for i in range(4):
            self.apply_visual_state(i)

    def update_status_label(self):
        is_dark = resolve_theme(self.settings_manager) == "dark"
        count = sum(self.enabled_toons)
        if self.service_running and count > 0:
            self.status_label.setText(f"✅ Sending input to {count} toon{'s' if count != 1 else ''}")
            self.status_label.setStyleSheet("QLabel { background-color: " + ("#2c3f2c" if is_dark else "#e8f5e9") + "; color: " + ("#ccffcc" if is_dark else "#2e7d32") + "; font-size: 12px; font-weight: 500; border-left: 6px solid " + ("#56c856" if is_dark else "#66bb6a") + "; border-radius: 4px; padding: 6px 12px; }")
        elif self.service_running:
            self.status_label.setText("⚠️ Service running (no toons enabled)")
            self.status_label.setStyleSheet("QLabel { background-color: " + ("#3a2f1a" if is_dark else "#fff8e1") + "; color: " + ("#ffcc99" if is_dark else "#444") + "; font-size: 12px; font-weight: 500; border-left: 6px solid " + ("#ffaa00" if is_dark else "#f0b400") + "; border-radius: 4px; padding: 6px 12px; }")
        else:
            self.status_label.setText("⏸️ Service idle")
            self.status_label.setStyleSheet("QLabel { background-color: " + ("#2f2f2f" if is_dark else "#f0f0f0") + "; color: " + ("#cccccc" if is_dark else "#444") + "; font-size: 12px; font-weight: 500; border-left: 6px solid " + ("#555" if is_dark else "#bbb") + "; border-radius: 4px; padding: 6px 12px; }")

    def toggle_service(self):
        self.service_running = not self.service_running
        if self.service_running:
            self.input_service.start()
            self.log("[Service] Multitoon service started.")

            # Auto-enable all connected toons
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

    def get_pressed_keys(self):
        return self.pressed_keys

    def on_global_key_press(self, key):
        s = self.normalize_key(key)
        if s and s not in self.pressed_keys:
            self.pressed_keys.add(s)

    def on_global_key_release(self, key):
        s = self.normalize_key(key)
        if s and s in self.pressed_keys:
            self.pressed_keys.remove(s)

    def normalize_key(self, key):
        if hasattr(key, 'char') and key.char:
            return key.char
        name = getattr(key, 'name', None)
        return {
            "space": "space", "enter": "Return", "esc": "Escape",
            "shift": "Shift_L", "ctrl": "Control_L", "alt": "Alt_L",
            "backspace": "BackSpace", "up": "Up", "down": "Down",
            "left": "Left", "right": "Right"
        }.get(name, None)

    def log(self, msg):
        if self.logger:
            self.logger.append_log(msg)
        else:
            print(msg)
