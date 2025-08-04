import sys
import subprocess
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QTabWidget, QLabel, QProxyStyle, QStyle
)
from PySide6.QtCore import QRect, Qt, QMetaObject, Q_ARG
from pynput import keyboard

# === Internal Imports ===
from tabs.multitoon_tab import MultitoonTab
from tabs.keep_alive_tab import KeepAliveTab
from tabs.presets_tab import PresetsTab
from tabs.settings_tab import SettingsTab
from tabs.debug_tab import DebugTab
from tabs.diagnostics_tab import DiagnosticsTab
from utils.preset_manager import PresetManager
from utils.settings_manager import SettingsManager
from utils.theme_manager import apply_theme, resolve_theme

class NoFocusProxyStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PE_FrameFocusRect:
            return
        super().drawPrimitive(element, option, painter, widget)

class MultiToonTool(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("ToonTown MultiTool")
        self.setGeometry(QRect(100, 100, 460, 600))

        self.pressed_keys = set()
        self.service_running = False
        self.preset_manager = PresetManager()
        self.settings_manager = SettingsManager()

        # Store own window ID
        self.setObjectName("MultiToonToolMainWindow")
        try:
            win_id = subprocess.check_output(["xdotool", "search", "--name", "ToonTown MultiTool"]).decode().strip().split("\n")[0]
            self.settings_manager.set("multitool_window_id", win_id)
        except:
            print("[Main] Warning: Failed to get MultiTool window ID.")

        self.debug_tab = DebugTab()
        self.logger = self.debug_tab

        self.multitoon_tab = MultitoonTab(logger=self.logger, settings_manager=self.settings_manager)
        self.keep_alive_tab = KeepAliveTab(parent=self)
        self.presets_tab = PresetsTab(settings_manager=self.settings_manager)
        self.settings_tab = SettingsTab(self.settings_manager)
        self.diagnostics_tab = DiagnosticsTab(logger=self.logger)

        self.settings_tab.debug_visibility_changed.connect(self.toggle_debug_tab_visibility)
        self.settings_tab.diagnostics_visibility_changed.connect(self.toggle_diagnostics_tab_visibility)
        self.settings_tab.theme_changed.connect(self.on_theme_changed)
        self.presets_tab.save_preset_requested.connect(self.save_preset)
        self.presets_tab.load_preset_requested.connect(self.load_preset)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background: transparent;
            }
        """)
        self.tabs.addTab(self.multitoon_tab, "Multitoon")
        self.tabs.addTab(self.keep_alive_tab, "Extras")
        self.tabs.addTab(self.presets_tab, "Presets")
        self.tabs.addTab(self.settings_tab, "Settings")
        if self.settings_manager.get("show_diagnostics_tab", False):
            self.tabs.addTab(self.diagnostics_tab, "Diagnostics")
        if self.settings_manager.get("show_debug_tab", False):
            self.tabs.addTab(self.debug_tab, "Debug")

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        initial_theme = resolve_theme(self.settings_manager)
        title_color = "#ffffff" if initial_theme == "dark" else "#222222"

        self.title = QLabel("ToonTown MultiTool")
        self.title.setAlignment(Qt.AlignHCenter)
        self.title.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {title_color}; background-color: transparent;"
        )

        self.subtitle = QLabel("by flossbud")
        self.subtitle.setAlignment(Qt.AlignHCenter)
        self.subtitle.setStyleSheet(
            "font-size: 13px; color: #bbbbbb; margin-bottom: 6px; background-color: transparent;"
        )

        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.tabs)

        self.container = QWidget()
        self.container.setLayout(layout)
        self.setCentralWidget(self.container)
        self.apply_background_theme(initial_theme)

        self.start_global_hotkey_listener()
        self.log("[Debug] ToonTown MultiTool launched.")

    def apply_background_theme(self, theme):
        if theme == "dark":
            gradient = """
                QWidget {
                    background: qlineargradient(
                        spread:pad, x1:0, y1:0, x2:0, y2:1,
                        stop:0 #1b1b1b, stop:1 #2e2e2e
                    );
                }
            """
        else:
            gradient = """
                QWidget {
                    background: qlineargradient(
                        spread:pad, x1:0, y1:0, x2:0, y2:1,
                        stop:0 #ffffff, stop:0.5 #e6e6e6, stop:1 #cccccc
                    );
                }
            """
        self.container.setStyleSheet(gradient)

    def on_theme_changed(self):
        theme = resolve_theme(self.settings_manager)
        apply_theme(QApplication.instance(), theme)
        self.apply_background_theme(theme)
        self.update_theme_on_children(self)

        self.multitoon_tab.refresh_theme()
        self.multitoon_tab.apply_all_visual_states()
        self.keep_alive_tab.refresh_theme()
        self.presets_tab.refresh_theme()
        self.settings_tab.refresh_theme()

        title_color = "#ffffff" if theme == "dark" else "#222222"
        self.title.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {title_color}; background-color: transparent;"
        )
        self.subtitle.setStyleSheet(
            "font-size: 13px; color: #bbbbbb; margin-bottom: 6px; background-color: transparent;"
        )

    def update_theme_on_children(self, widget):
        widget.setStyleSheet(widget.styleSheet())
        for child in widget.findChildren(QWidget):
            child.setStyleSheet(child.styleSheet())

    def toggle_debug_tab_visibility(self, show: bool):
        index = self.tabs.indexOf(self.debug_tab)
        if show and index == -1:
            self.tabs.addTab(self.debug_tab, "Debug")
        elif not show and index != -1:
            self.tabs.removeTab(index)

    def toggle_diagnostics_tab_visibility(self, show: bool):
        index = self.tabs.indexOf(self.diagnostics_tab)
        if show and index == -1:
            self.tabs.addTab(self.diagnostics_tab, "Diagnostics")
        elif not show and index != -1:
            self.tabs.removeTab(index)

    def start_global_hotkey_listener(self):
        self.listener = keyboard.Listener(
            on_press=self.on_global_key_press,
            on_release=self.on_global_key_release
        )
        self.listener.start()

    def on_global_key_press(self, key):
        try:
            if key in [keyboard.Key.ctrl_l, keyboard.Key.ctrl_r]:
                self.pressed_keys.add("ctrl")
            elif hasattr(key, 'char') and key.char:
                self.pressed_keys.add(key.char)
                if "ctrl" in self.pressed_keys and key.char in "12345":
                    QMetaObject.invokeMethod(
                        self, "load_preset", Qt.QueuedConnection, Q_ARG(int, int(key.char))
                    )
        except:
            pass

    def on_global_key_release(self, key):
        try:
            if key in [keyboard.Key.ctrl_l, keyboard.Key.ctrl_r]:
                self.pressed_keys.discard("ctrl")
            elif hasattr(key, 'char') and key.char:
                self.pressed_keys.discard(key.char)
        except:
            pass

    def start_service(self):
        self.service_running = True
        self.multitoon_tab.start_service()
        self.log("[Service] Multitoon service started.")

    def stop_service(self):
        self.service_running = False
        self.multitoon_tab.stop_service()
        self.log("[Service] Multitoon service stopped.")

    def save_preset(self, index: int):
        state = {
            "enabled_toons": [btn.isChecked() for btn in self.multitoon_tab.toon_buttons],
            "movement_modes": [box.currentText() for box in self.multitoon_tab.movement_dropdowns],
            "service_running": self.multitoon_tab.service_running
        }
        self.preset_manager.save_preset(index, state)
        self.log(f"[Preset] Preset {index} saved.")

    def load_preset(self, index: int):
        preset = self.preset_manager.load_preset(index)
        if not preset:
            self.log(f"[Preset] No saved preset {index}")
            return

        self.service_running = preset.get("service_running", False)
        self.log(f"[Debug] Preset {index} wants service_running = {self.service_running}")
        self.multitoon_tab.set_service_active(self.service_running)
        self.multitoon_tab.input_service.assign_windows()

        for i, mode in enumerate(preset.get("movement_modes", [])):
            if i < len(self.multitoon_tab.movement_dropdowns):
                self.multitoon_tab.movement_dropdowns[i].setCurrentText(mode)

        for i, state in enumerate(preset.get("enabled_toons", [])):
            if i < len(self.multitoon_tab.toon_buttons):
                self.multitoon_tab.set_toon_enabled(i, state)
                btn = self.multitoon_tab.toon_buttons[i]
                btn.setStyleSheet(self._enabled_style() if state else self._disabled_style())

        self.multitoon_tab.apply_all_visual_states()
        self.log(f"[Preset] Preset {index} loaded.")

        for i in range(1, 6):
            self.presets_tab.set_preset_dot_state(i, i == index)

    def closeEvent(self, event):
        try:
            self.stop_service()
            self.keep_alive_tab.stop_keep_alive()
            key = self.keep_alive_tab.key_input.text().strip()
            if key and self.settings_manager:
                self.settings_manager.set("keep_alive_key", key)
        except Exception as e:
            print(f"[CloseEvent] Error during shutdown: {e}")
        super().closeEvent(event)

    def _enabled_style(self):
        return """
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 6px;
                border-radius: 8px;
                border: 2px solid #3e8e41;
            }
            QPushButton:hover {
                background-color: #45a049;
                border: 2px solid #34a853;
            }
        """

    def _disabled_style(self):
        return """
            QPushButton {
                background-color: #4a4a4a;
                color: #ccc;
                border: none !important;
                padding: 6px;
                border-radius: 8px;
                outline: none !important;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
                border: none !important;
                outline: none !important;
            }
            QPushButton:disabled {
                background-color: #4a4a4a;
                color: #999;
                border: none !important;
                outline: none !important;
            }
        """

    def log(self, message: str):
        print(message)
        self.debug_tab.append_log(message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle(NoFocusProxyStyle(app.style()))
    settings = SettingsManager()
    apply_theme(app, resolve_theme(settings))
    window = MultiToonTool()
    window.show()
    sys.exit(app.exec())
