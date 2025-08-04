from PySide6.QtWidgets import QWidget, QVBoxLayout, QCheckBox, QLabel, QComboBox, QApplication
from PySide6.QtCore import Qt, Signal, QPropertyAnimation
from utils.theme_manager import apply_theme, resolve_theme


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

        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        self.layout.setContentsMargins(30, 30, 30, 30)
        self.layout.setSpacing(24)

        # === General Section ===
        self.layout.addWidget(self._section_label("General"))

        self.sort_left_to_right_checkbox = self._create_checkbox(
            "Assign Toon 1 and 2 by window position (left to right)",
            self.settings_manager.get("left_to_right_assignment", False),
            self.toggle_left_to_right_assignment
        )
        self.layout.addWidget(self.sort_left_to_right_checkbox)

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

    def refresh_theme(self):
        theme = resolve_theme(self.settings_manager)
        is_dark = theme == "dark"

        text_color = "#ffffff" if is_dark else "#111111"
        subtext_color = "#bbbbbb" if is_dark else "#333333"
        combo_bg = "#3a3a3a" if is_dark else "#ffffff"
        combo_fg = "#ffffff" if is_dark else "#111111"
        combo_border = "#666" if is_dark else "#aaa"
        combo_hover = "#88c0d0" if is_dark else "#66aa66"
        list_bg = "#2a2a2a" if is_dark else "#f8f8f8"
        list_fg = "#ffffff" if is_dark else "#111111"
        selection_bg = "#555" if is_dark else "#e0e0e0"
        selection_fg = "#ffffff" if is_dark else "#000000"

        self.setStyleSheet(f"background-color: {'#2c2c2c' if is_dark else '#f5f5f5'};")

        for label in self.section_labels:
            label.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {subtext_color}; margin-bottom: 4px; background: transparent;")

        for box in self.checkboxes:
            box.setStyleSheet(f"""
                QCheckBox {{
                    font-size: 13px;
                    color: {text_color};
                    background-color: transparent;
                }}
                QCheckBox::indicator {{
                    width: 16px;
                    height: 16px;
                }}
                QCheckBox:hover {{
                    color: #a0ffa0;
                }}
            """)

        self.theme_selector.setStyleSheet(f"""
            QComboBox {{
                padding: 6px 8px;
                border-radius: 6px;
                background-color: {combo_bg};
                color: {combo_fg};
                border: 1px solid {combo_border};
            }}
            QComboBox:hover {{
                border: 1px solid {combo_hover};
            }}
            QComboBox QAbstractItemView {{
                background-color: {list_bg};
                color: {list_fg};
                selection-background-color: {selection_bg};
                selection-color: {selection_fg};
            }}
        """)

        self.advanced_container.setStyleSheet("background: transparent;")
