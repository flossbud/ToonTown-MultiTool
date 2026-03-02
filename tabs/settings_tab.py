from PySide6.QtWidgets import QWidget, QVBoxLayout, QCheckBox, QLabel, QComboBox, QApplication, QMessageBox
from PySide6.QtCore import Qt, Signal, QPropertyAnimation
from utils.theme_manager import apply_theme, resolve_theme, get_theme_colors


class SettingsTab(QWidget):
    debug_visibility_changed = Signal(bool)
    theme_changed = Signal()
    input_backend_changed = Signal()

    def __init__(self, settings_manager):
        super().__init__()
        self.settings_manager = settings_manager
        self.section_labels = []
        self.checkboxes = []

        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        self.layout.setContentsMargins(30, 30, 30, 30)
        self.layout.setSpacing(24)

        # === General Section ===
        self.layout.addWidget(self._section_label("General"))

        self.show_advanced_checkbox = self._create_checkbox(
            "Show Advanced Settings",
            False,
            self.toggle_advanced_visibility
        )
        self.layout.addWidget(self.show_advanced_checkbox)

        # === Theme Section ===
        self.layout.addWidget(self._section_label("Theme"))

        self.theme_selector = QComboBox()
        self.theme_selector.addItems(["System Default", "Light", "Dark"])
        current = self.settings_manager.get("theme", "system")
        self.theme_selector.setCurrentIndex(["system", "light", "dark"].index(current))
        self.theme_selector.currentIndexChanged.connect(self.change_theme)
        self.layout.addWidget(self.theme_selector)

        # === Advanced Section ===
        self.advanced_container = QWidget()
        self.advanced_container.setMaximumHeight(0)
        adv_layout = QVBoxLayout(self.advanced_container)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(24)

        adv_layout.addWidget(self._section_label("Advanced"))

        self.enable_companion_app_checkbox = self._create_checkbox(
            "Enable Companion App Support",
            self.settings_manager.get("enable_companion_app", True),
            self.toggle_companion_app
        )
        adv_layout.addWidget(self.enable_companion_app_checkbox)

        self.show_debug_checkbox = self._create_checkbox(
            "Show Logs Tab",
            self.settings_manager.get("show_debug_tab", False),
            self.toggle_debug_tab
        )
        adv_layout.addWidget(self.show_debug_checkbox)

        adv_layout.addWidget(self._section_label("Input Backend"))

        self.input_backend_dropdown = QComboBox()
        self.input_backend_dropdown.addItems(["Xlib (recommended)", "xdotool"])
        current_backend = self.settings_manager.get("input_backend", "xlib")
        self.input_backend_dropdown.setCurrentIndex(0 if current_backend == "xlib" else 1)
        self.input_backend_dropdown.currentIndexChanged.connect(self.change_input_backend)
        adv_layout.addWidget(self.input_backend_dropdown)

        self.advanced_anim = QPropertyAnimation(self.advanced_container, b"maximumHeight")
        self.advanced_anim.setDuration(250)
        self.layout.addWidget(self.advanced_container)
        self.layout.addStretch()

        self.refresh_theme()

    def _section_label(self, text):
        label = QLabel(text)
        self.section_labels.append(label)
        return label

    def _create_checkbox(self, label, checked, callback):
        box = QCheckBox(label)
        box.setChecked(checked)
        box.stateChanged.connect(callback)
        self.checkboxes.append(box)
        return box

    def change_theme(self, index):
        theme = ["system", "light", "dark"][index]
        self.settings_manager.set("theme", theme)
        apply_theme(QApplication.instance(), resolve_theme(self.settings_manager))
        self.theme_changed.emit()

    def toggle_advanced_visibility(self, state):
        expanding = state != 0
        if expanding:
            self.advanced_container.setVisible(True)
            self.advanced_anim.setStartValue(0)
            self.advanced_anim.setEndValue(self.advanced_container.sizeHint().height())
            try:
                self.advanced_anim.finished.disconnect()
            except:
                pass
        else:
            self.advanced_anim.setStartValue(self.advanced_container.height())
            self.advanced_anim.setEndValue(0)
            try:
                self.advanced_anim.finished.disconnect()
            except:
                pass
            self.advanced_anim.finished.connect(lambda: self.advanced_container.setVisible(False))
        self.advanced_anim.start()

    def toggle_companion_app(self, state):
        self.settings_manager.set("enable_companion_app", state != 0)

    def change_input_backend(self, index):
        backend = "xlib" if index == 0 else "xdotool"
        if backend == "xdotool" and self._is_gnome_wayland():
            dlg = QMessageBox(self)
            dlg.setWindowTitle("Warning: xdotool on GNOME Wayland")
            dlg.setIcon(QMessageBox.Warning)
            dlg.setText(
                "xdotool on GNOME Wayland will trigger repeated Remote Desktop "
                "authorization prompts and will likely break input sending.\n\n"
                "Xlib is strongly recommended for GNOME Wayland.\n\n"
                "This will restart the service.\n\n"
                "Switch to xdotool anyway?"
            )
            dlg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            dlg.setDefaultButton(QMessageBox.Cancel)
            result = dlg.exec()
            if result != QMessageBox.Ok:
                self.input_backend_dropdown.blockSignals(True)
                self.input_backend_dropdown.setCurrentIndex(0)
                self.input_backend_dropdown.blockSignals(False)
                return
        self.settings_manager.set("input_backend", backend)
        self.input_backend_changed.emit()

    def _is_gnome_wayland(self) -> bool:
        import os
        return (os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
                and "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper())

    def toggle_debug_tab(self, state):
        show = state != 0
        self.settings_manager.set("show_debug_tab", show)
        self.debug_visibility_changed.emit(show)

    def refresh_theme(self):
        c = get_theme_colors(resolve_theme(self.settings_manager) == "dark")
        is_dark = resolve_theme(self.settings_manager) == "dark"

        self.setStyleSheet(f"background-color: {c['bg_app']};")

        for label in self.section_labels:
            label.setStyleSheet(
                f"font-size: 15px; font-weight: bold; color: {c['text_secondary']}; margin-bottom: 4px; background: transparent;"
            )

        for box in self.checkboxes:
            box.setStyleSheet(f"""
                QCheckBox {{
                    font-size: 13px;
                    color: {c['text_primary']};
                    background-color: transparent;
                }}
                QCheckBox::indicator {{
                    width: 16px;
                    height: 16px;
                }}
                QCheckBox:hover {{
                    color: {c['accent_green_subtle']};
                }}
            """)

        self.theme_selector.setStyleSheet(f"""
            QComboBox {{
                padding: 6px 8px;
                border-radius: 6px;
                background-color: {c['dropdown_bg']};
                color: {c['dropdown_text']};
                border: 1px solid {c['dropdown_border']};
            }}
            QComboBox:hover {{
                border: 1px solid {c['accent_blue']};
            }}
            QComboBox QAbstractItemView {{
                background-color: {c['dropdown_list_bg']};
                color: {c['dropdown_text']};
                selection-background-color: {c['dropdown_sel_bg']};
                selection-color: {c['dropdown_sel_text']};
            }}
        """)

        dropdown_style = f"""
            QComboBox {{
                padding: 6px 8px;
                border-radius: 6px;
                background-color: {c['dropdown_bg']};
                color: {c['dropdown_text']};
                border: 1px solid {c['dropdown_border']};
                font-size: 13px;
            }}
            QComboBox:hover {{
                border: 1px solid {c['accent_blue']};
            }}
            QComboBox QAbstractItemView {{
                background-color: {c['dropdown_list_bg']};
                color: {c['dropdown_text']};
                selection-background-color: {c['dropdown_sel_bg']};
                selection-color: {c['dropdown_sel_text']};
            }}
        """
        self.input_backend_dropdown.setStyleSheet(dropdown_style)

        self.advanced_container.setStyleSheet("background: transparent;")