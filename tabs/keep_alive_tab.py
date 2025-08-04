import threading, time, subprocess
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from utils.theme_manager import resolve_theme

SPECIAL_KEYS = {
    Qt.Key_Space: "space", Qt.Key_Return: "Return", Qt.Key_Enter: "Return",
    Qt.Key_Tab: "Tab", Qt.Key_Backspace: "BackSpace", Qt.Key_Escape: "Escape",
    Qt.Key_Shift: "Shift_L", Qt.Key_Control: "Control_L",
    Qt.Key_Alt: "Alt_L", Qt.Key_Delete: "Delete"
}

class KeyCaptureLineEdit(QLineEdit):
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings_manager, self.key_set, self.awaiting_key = settings_manager, False, False
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.set_default_state()

    def current_theme(self):
        return resolve_theme(self.settings_manager) if self.settings_manager else "dark"

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if not self.key_set:
            self.awaiting_key = True
            self.setText("Press any key to set")
            self.update_theme(True)

    def keyPressEvent(self, e):
        if not self.awaiting_key: return e.ignore()
        key = SPECIAL_KEYS.get(e.key(), e.text().lower())
        if key:
            self.setText(key)
            self.key_set = True
            self.awaiting_key = False
            self.update_theme()
            self.clearFocus()
            if hasattr(self.parent(), "log_key_set"): self.parent().log_key_set(key)
        e.accept()

    def set_default_state(self):
        self.setText("Click to set a key")
        self.key_set = self.awaiting_key = False
        self.update_theme()

    def update_theme(self, editing=False):
        d = self.current_theme() == "dark"
        bg, fg, bd = ("#2f2f2f", "#ffffff", "#6ab8ff" if editing else "#666") if d else ("#ffffff", "#111111", "#cccccc")
        inactive = "#bbbbbb" if d else "#555555"
        self.setStyleSheet(f"QLineEdit {{background:{bg};color:{fg if self.key_set else inactive};border:1px solid {bd};border-radius:6px;padding:6px 8px;}}")

class NonToggleableCheckBox(QCheckBox):
    def keyPressEvent(self, e):
        if e.key() in [Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter]:
            e.ignore()
        else:
            super().keyPressEvent(e)

class KeepAliveTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.settings_manager = getattr(parent, "settings_manager", None)
        self.input_service = getattr(getattr(parent, "multitoon_tab", None), "input_service", None)
        self.keep_alive_thread, self.keep_alive_running, self.internal_toggle_block = None, False, False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self.enable_checkbox = NonToggleableCheckBox("Enable Keep-Alive")
        layout.addWidget(self.enable_checkbox, alignment=Qt.AlignLeft)

        self.status_label = QLabel("⏸️ Keep-Alive: Disabled")
        layout.addWidget(self.status_label)

        self.card = QFrame()
        self.card.setFixedWidth(360)
        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(16, 16, 16, 16)
        self.card_layout.setSpacing(10)

        self.key_label = QLabel("Keep-Alive Key:")
        self.card_layout.addWidget(self.key_label)

        self.key_input = KeyCaptureLineEdit(self.settings_manager, self)
        clear_btn = QPushButton("X")
        clear_btn.setToolTip("Clear key")
        clear_btn.setFixedHeight(30)
        clear_btn.setMinimumWidth(30)
        clear_btn.clicked.connect(self.clear_keep_alive_key)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.key_input)
        row.addWidget(clear_btn)
        self.card_layout.addLayout(row)

        self.delay_label = QLabel("Delay Interval:")
        self.delay_dropdown = QComboBox()
        self.delay_dropdown.addItems(["5 sec", "10 sec", "30 sec", "1 min", "5 min", "10 min"])
        self.delay_dropdown.currentIndexChanged.connect(self.log_delay_changed)
        self.card_layout.addWidget(self.delay_label)
        self.card_layout.addWidget(self.delay_dropdown)

        layout.addWidget(self.card)

        self.tip_label = QLabel("Tip: Multitoon service must be started for Keep-Alive to work.")
        self.tip_label.setAlignment(Qt.AlignHCenter)
        self.tip_label.setWordWrap(True)
        self.tip_label.setMaximumWidth(360)
        layout.addWidget(self.tip_label)

        self.countdown_label = QLabel("")
        layout.addWidget(self.countdown_label)

        self.launch_button = QPushButton("🚀 Launch TTR")
        self.launch_button.setFixedWidth(160)
        self.launch_button.clicked.connect(self.launch_ttr)
        layout.addWidget(self.launch_button, alignment=Qt.AlignHCenter)

        self.enable_checkbox.stateChanged.connect(self.toggle_keep_alive)

        self.load_persisted_state()
        self.refresh_theme()

    def refresh_theme(self):
        d = resolve_theme(self.settings_manager) == "dark"
        def c(light, dark): return dark if d else light
        self.setStyleSheet(f"background:{c('#f6f6f6','#2e2e2e')};color:{c('#000','#fff')};")
        self.enable_checkbox.setStyleSheet(f"""
            QCheckBox {{
                background-color: transparent;
                color: {c('#000', '#fff')};
                font-weight: bold;
                font-size: 14px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 2px solid {c('#444', '#ccc')};
                background-color: transparent;
            }}
            QCheckBox::indicator:checked {{
                background-color: {c('#66aa66', '#88c0d0')};
                image: none;
            }}
        """)
        self.status_label.setStyleSheet(f"QLabel {{background:{c('#fff','#2f2f2f')};color:{c('#333','#ccc')};font-size:12px;font-weight:500;border-left:6px solid {c('#ccc','#555')};border-radius:4px;padding:6px 12px;margin-bottom:4px;}}")
        self.card.setStyleSheet(f"""
            QFrame {{
                background-color: {c('rgba(255, 255, 255, 0.95)', 'rgba(50, 50, 50, 0.95)')};
                border-radius: 10px;
                border: 1px solid {c('rgba(0, 0, 0, 0.08)', 'rgba(255, 255, 255, 0.12)')};
            }}
        """)

        lbl_style = f"QLabel {{background:none;border:none;padding:0;margin:0;font-weight:bold;color:{c('#000','#fff')};font-size:13px;}}"
        self.key_label.setStyleSheet(lbl_style)
        self.delay_label.setStyleSheet(lbl_style)
        self.delay_dropdown.setStyleSheet(f"QComboBox {{padding:6px 8px;border-radius:6px;background:{c('#fff','#2f2f2f')};color:{c('#111','#fff')};border:1px solid {c('#ccc','#555')};}} QComboBox:hover {{border:1px solid {c('#66aa66','#88c0d0')};}} QComboBox QAbstractItemView {{background:{c('#fff','#2f2f2f')};color:{c('#111','#fff')};selection-background-color:#555;selection-color:white;}}")
        self.tip_label.setStyleSheet("color: #aaaaaa; font-size: 11px; background: transparent;")
        self.countdown_label.setStyleSheet("color: #888888; font-size: 12px; margin-top: 8px; background: transparent;")
        self.launch_button.setStyleSheet(f"QPushButton {{background:{c('#dddddd','#444444')};color:{c('#000','#fff')};padding:8px 12px;border-radius:6px;border:1px solid {c('#aaa','#666')};font-weight:bold;}} QPushButton:hover {{border:1px solid {c('#66aa66','#88c0d0')};}}")
        self.key_input.update_theme()

    def clear_keep_alive_key(self):
        self.internal_toggle_block = True
        self.stop_keep_alive()
        self.update_status("⏸️ Keep-Alive: Disabled", "#cccccc", "#555")
        self.countdown_label.setText("")
        self.key_input.set_default_state()
        self.enable_checkbox.setChecked(False)
        self.enable_checkbox.setEnabled(True)
        self.internal_toggle_block = False
        if self.settings_manager: self.settings_manager.set("keep_alive_key", "")
        if self.parent_window: self.parent_window.log("[KeepAlive] Key cleared.")

    def load_persisted_state(self):
        sm = self.settings_manager
        if not sm: return
        key = sm.get("keep_alive_key", "")
        if key:
            self.key_input.setText(key)
            self.key_input.key_set = True
            self.key_input.awaiting_key = False
            self.key_input.update_theme()
            self.enable_checkbox.setEnabled(True)
        delay = sm.get("keep_alive_delay", "30 sec")
        i = self.delay_dropdown.findText(delay)
        if i >= 0: self.delay_dropdown.setCurrentIndex(i)

    def log_key_set(self, key):
        if self.parent_window: self.parent_window.log(f"[KeepAlive] Key set to: {key}")
        if self.settings_manager: self.settings_manager.set("keep_alive_key", key)
        self.enable_checkbox.setEnabled(True)
        self.update_status("⏸️ Keep-Alive: Disabled", "#cccccc", "#555")
        self.countdown_label.setText("")

    def log_delay_changed(self, i):
        delay = self.delay_dropdown.itemText(i)
        if self.parent_window: self.parent_window.log(f"[KeepAlive] Delay set to: {delay}")
        if self.settings_manager: self.settings_manager.set("keep_alive_delay", delay)

    def update_status(self, text, color, border):
        d = resolve_theme(self.settings_manager) == "dark"
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"QLabel {{background:{'#2f2f2f' if d else '#fff'};color:{color};font-size:12px;font-weight:500;border-left:6px solid {border};border-radius:4px;padding:6px 12px;margin-bottom:4px;}}")

    def toggle_keep_alive(self, state):
        if self.internal_toggle_block: return
        if state != 0 and self.key_input.key_set:
            self.update_status("✅ Keep-Alive: Active", "#ccffcc" if resolve_theme(self.settings_manager) == "dark" else "#228833", "#56c856")
            self.start_keep_alive()
            if self.parent_window: self.parent_window.log("[KeepAlive] Keep-Alive enabled.")
        elif state != 0:
            self.update_status("⚠️ Set key before enabling!", "orange", "#ffaa00")
            self.countdown_label.setText("")
            self.internal_toggle_block = True
            self.enable_checkbox.setChecked(False)
            self.internal_toggle_block = False
        else:
            self.update_status("⏸️ Keep-Alive: Disabled", "#cccccc", "#555")
            self.countdown_label.setText("")
            self.stop_keep_alive()
            if self.parent_window: self.parent_window.log("[KeepAlive] Keep-Alive disabled.")

    def start_keep_alive(self):
        if not self.keep_alive_running:
            self.keep_alive_running = True
            self.keep_alive_thread = threading.Thread(target=self.run_keep_alive_loop, daemon=True)
            self.keep_alive_thread.start()

    def stop_keep_alive(self):
        self.keep_alive_running = False

    def get_delay_seconds(self):
        return {"5 sec": 5, "10 sec": 10, "30 sec": 30, "1 min": 60, "5 min": 300, "10 min": 600}.get(self.delay_dropdown.currentText(), 60)

    def run_keep_alive_loop(self):
        try:
            while self.keep_alive_running:
                end = time.time() + self.get_delay_seconds()
                while self.keep_alive_running and time.time() < end:
                    self.update_countdown_label(int(end - time.time()))
                    time.sleep(1)
                if not self.keep_alive_running: break
                key = self.key_input.text().strip()
                if key and self.input_service:
                    self.input_service.send_keep_alive_key(key)
                    if self.parent_window: self.parent_window.log(f"[KeepAlive] Sent key: {key}")
        except Exception as e:
            if self.parent_window: self.parent_window.log(f"[KeepAlive] Error: {e}")

    def update_countdown_label(self, sec):
        self.countdown_label.setText(f"Next key in {sec} second{'s' if sec != 1 else ''}...")

    def launch_ttr(self):
        try:
            import os
            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "xcb"
            subprocess.Popen(
                ["flatpak", "run", "com.toontownrewritten.Launcher"],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            if self.parent_window:
                self.parent_window.log("[Extras] Toontown Rewritten launcher started silently (X11).")
        except Exception as e:
            if self.parent_window:
                self.parent_window.log(f"[Extras] Failed to launch TTR: {e}")
