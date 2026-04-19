import subprocess

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QFrame
from PySide6.QtCore import Qt
from services.launcher_env import build_launcher_env
from utils.theme_manager import resolve_theme, get_theme_colors, apply_card_shadow
from utils.symbols import S


class KeepAliveTab(QWidget):
    """Extras tab — currently just hosts the TTR launcher button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.settings_manager = getattr(parent, "settings_manager", None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self.tip_label = QLabel(
            "Keep-Alive is now configured per-toon in the Multitoon tab.\n"
            "Key and delay settings are in the Settings tab."
        )
        self.tip_label.setAlignment(Qt.AlignHCenter)
        self.tip_label.setWordWrap(True)
        self.tip_label.setMaximumWidth(360)
        layout.addWidget(self.tip_label)

        layout.addStretch()

        # Launch card
        self.launch_card = QFrame()
        self.launch_card.setFixedWidth(280)
        card_layout = QVBoxLayout(self.launch_card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)

        self.launch_title = QLabel("Quick Launch")
        self.launch_title.setAlignment(Qt.AlignHCenter)
        card_layout.addWidget(self.launch_title)

        self.launch_button = QPushButton(f"{S('🚀', '▶')} Launch TTR")
        self.launch_button.setFixedWidth(200)
        self.launch_button.clicked.connect(self.launch_ttr)
        card_layout.addWidget(self.launch_button, alignment=Qt.AlignHCenter)

        layout.addWidget(self.launch_card, alignment=Qt.AlignHCenter)

        layout.addStretch()
        self.refresh_theme()

    def _c(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

    def refresh_theme(self):
        c = self._c()
        is_dark = resolve_theme(self.settings_manager) == "dark"
        self.setStyleSheet(f"background: {c['bg_app']}; color: {c['text_primary']};")
        self.tip_label.setStyleSheet(
            f"color: {c['text_muted']}; font-size: 11px; background: transparent;"
        )
        self.launch_card.setStyleSheet(f"""
            QFrame {{
                background-color: {c['bg_card']};
                border-radius: 10px;
                border: 1px solid {c['border_card']};
            }}
        """)
        apply_card_shadow(self.launch_card, is_dark, blur=14, offset_y=3)
        self.launch_title.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {c['text_secondary']}; background: none; border: none;"
        )
        self.launch_button.setStyleSheet(f"""
            QPushButton {{
                background: {c['btn_bg']}; color: {c['btn_text']};
                padding: 8px 12px; border-radius: 6px;
                border: 1px solid {c['btn_border']}; font-weight: bold;
            }}
            QPushButton:hover {{ border: 1px solid {c['accent_blue']}; }}
        """)

    def launch_ttr(self):
        try:
            subprocess.Popen(
                ["flatpak", "run", "com.toontownrewritten.Launcher"],
                env=build_launcher_env({"QT_QPA_PLATFORM": "xcb"}),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if self.parent_window:
                self.parent_window.log("[Extras] Toontown Rewritten launcher started silently (X11).")
        except Exception as e:
            if self.parent_window:
                self.parent_window.log(f"[Extras] Failed to launch TTR: {e}")
