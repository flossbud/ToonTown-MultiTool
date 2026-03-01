from PySide6.QtWidgets import QWidget, QVBoxLayout, QCheckBox, QLabel, QComboBox, QApplication
from PySide6.QtCore import Qt, Signal, QPropertyAnimation
from utils.theme_manager import apply_theme, resolve_theme, get_theme_colors


class SettingsTab(QWidget):
    debug_visibility_changed = Signal(bool)
    diagnostics_visibility_changed = Signal(bool)
    extras_visibility_changed = Signal(bool)
    theme_changed = Signal()

    def __init__(self, settings_manager):
        super().__init__()
        self.settings_manager = settings_manager
        self.section_labels = []
        self.checkboxes = []

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(24)

        # === General ===
        layout.addWidget(self._section_label("General"))

        self.sort_left_to_right_checkbox = self._create_checkbox(
            "Assign Toon 1 and 2 by window position (left to right)",
            self.settings_manager.get("left_to_right_assignment", False),
            self.toggle_left_to_right_assignment
        )
        layout.addWidget(self.sort_left_to_right_checkbox)

        self.show_advanced_checkbox = self._create_checkbox(
            "Show Advanced Settings", False, self.toggle_advanced_visibility
        )
        layout.addWidget(self.show_advanced_checkbox)

        # === Theme ===
        layout.addWidget(self._section_label("Theme"))

        self.theme_selector = QComboBox()
        self.theme_selector.addItems(["System Default", "Light", "Dark"])
        current = self.settings_manager.get("theme", "system")
        self.theme_selector.setCurrentIndex(["system", "light", "dark"].index(current))
        self.theme_selector.currentIndexChanged.connect(self.change_theme)
        layout.addWidget(self.theme_selector)

        # === Advanced (collapsible) ===
        self.advanced_container = QWidget()
        self.advanced_container.setMaximumHeight(0)
        adv_layout = QVBoxLayout(self.advanced_container)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(24)

        adv_layout.addWidget(self._section_label("Advanced"))

        self.show_debug_checkbox = self._create_checkbox(
            "Show Debug Tab",
            self.settings_manager.get("show_debug_tab", False),
            self.toggle_debug_tab
        )
        adv_layout.addWidget(self.show_debug_checkbox)

        self.show_diagnostics_checkbox = self._create_checkbox(
            "Show Diagnostics Tab",
            self.settings_manager.get("show_diagnostics_tab", False),
            self.toggle_diagnostics_tab
        )
        adv_layout.addWidget(self.show_diagnostics_checkbox)

        self.show_extras_checkbox = self._create_checkbox(
            "Show Extras Tab",
            self.settings_manager.get("show_extras_tab", False),
            self.toggle_extras_tab
        )
        adv_layout.addWidget(self.show_extras_checkbox)

        self.advanced_anim = QPropertyAnimation(self.advanced_container, b"maximumHeight")
        self.advanced_anim.setDuration(250)
        layout.addWidget(self.advanced_container)
        layout.addStretch()

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

    def _c(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

    def refresh_theme(self):
        c = self._c()
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
                    width: 16px; height: 16px;
                }}
                QCheckBox:hover {{
                    color: {c['accent_green_subtle']};
                }}
            """)

        self.theme_selector.setStyleSheet(f"""
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
        """)
        self.advanced_container.setStyleSheet("background: transparent;")

    def change_theme(self, index):
        theme = ["system", "light", "dark"][index]
        self.settings_manager.set("theme", theme)
        apply_theme(QApplication.instance(), resolve_theme(self.settings_manager))
        self.theme_changed.emit()

    def toggle_left_to_right_assignment(self, state):
        self.settings_manager.set("left_to_right_assignment", state != 0)

    def toggle_advanced_visibility(self, state):
        expanding = state != 0
        if expanding:
            self.advanced_container.setVisible(True)
            self.advanced_anim.setStartValue(0)
            self.advanced_anim.setEndValue(self.advanced_container.sizeHint().height())
            try:
                self.advanced_anim.finished.disconnect()
            except Exception:
                pass
        else:
            self.advanced_anim.setStartValue(self.advanced_container.height())
            self.advanced_anim.setEndValue(0)
            try:
                self.advanced_anim.finished.disconnect()
            except Exception:
                pass
            self.advanced_anim.finished.connect(lambda: self.advanced_container.setVisible(False))
        self.advanced_anim.start()

    def toggle_debug_tab(self, state):
        show = state != 0
        self.settings_manager.set("show_debug_tab", show)
        self.debug_visibility_changed.emit(show)

    def toggle_diagnostics_tab(self, state):
        show = state != 0
        self.settings_manager.set("show_diagnostics_tab", show)
        self.diagnostics_visibility_changed.emit(show)

    def toggle_extras_tab(self, state):
        show = state != 0
        self.settings_manager.set("show_extras_tab", show)
        self.extras_visibility_changed.emit(show)