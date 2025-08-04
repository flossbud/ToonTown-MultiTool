import subprocess
import time
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt


class DiagnosticsTab(QWidget):
    def __init__(self, logger=None):
        super().__init__()
        self.logger = logger
        self.window_id = None

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)
        layout.setSpacing(16)

        layout.addWidget(QLabel("Diagnostics", styleSheet="font-size: 18px; font-weight: bold;"))
        layout.addWidget(QLabel("Test sending symbols and special keys to Toontown.\nResults will appear in the Debug tab.",
                                styleSheet="color: gray; font-size: 12px;"))

        btn = QPushButton("Run Symbol & Key Test")
        btn.clicked.connect(self.run_symbol_test)
        layout.addWidget(btn)

    def log(self, msg):
        print(msg)
        if self.logger:
            self.logger.append_log(msg)

    def run_symbol_test(self):
        self.log("[Diagnostics] Starting symbol test...")
        self.window_id = self.get_first_ttr_window()

        if not self.window_id:
            self.log("[Diagnostics] No TTR window found.")
            return

        keys = list("~!@#$%^&*()_+{}|:\"<>?`-=[]\\;',./") + \
               ["Return", "BackSpace", "Tab", "Escape", "Delete", "space",
                "Shift_L", "Control_L", "Alt_L", "Up", "Down", "Left", "Right"] + \
               list("abcdefghijklmnopqrstuvwxyz1234567890")

        for key in keys:
            time.sleep(0.05)
            self.try_all_methods(key)

        self.log("[Diagnostics] Symbol test complete.")

    def try_all_methods(self, key):
        for label, cmd in [
            ("key", ["xdotool", "key", "--window", self.window_id, key]),
            ("keydown", ["xdotool", "keydown", "--window", self.window_id, key]),
            ("keyup", ["xdotool", "keyup", "--window", self.window_id, key]),
            ("type", ["xdotool", "type", "--window", self.window_id, key])
        ]:
            if label == "keyup":
                time.sleep(0.01)
            self.try_cmd(cmd, label)

    def try_cmd(self, cmd, label):
        try:
            subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
            self.log(f"✅ {label.upper()} OK: {' '.join(cmd)}")
        except subprocess.CalledProcessError as e:
            self.log(f"❌ {label.upper()} FAIL: {' '.join(cmd)}\n    stderr: {e.stderr.decode().strip()}")

    def get_first_ttr_window(self):
        try:
            out = subprocess.check_output(["xdotool", "search", "--class", "Toontown Rewritten"])
            return out.decode().strip().split("\n")[0]
        except subprocess.CalledProcessError:
            return None
