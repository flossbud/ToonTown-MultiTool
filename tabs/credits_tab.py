from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from utils.theme_manager import resolve_theme, get_theme_colors, apply_card_shadow

class CreditsTab(QWidget):
    def __init__(self, settings_manager=None, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.build_ui()
        self.refresh_theme()

        if self.settings_manager:
            self.settings_manager.on_change(self._on_setting_changed)

    def _on_setting_changed(self, key, value):
        if key == "theme":
            self.refresh_theme()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        
        self.card = QFrame()
        self.card.setObjectName("credits_card")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(32, 40, 32, 40)
        card_layout.setSpacing(16)
        
        title = QLabel("ToonTown MultiTool v2.0")
        title_font = QFont()
        title_font.setWeight(QFont.Bold)
        title_font.setPointSize(24)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        
        desc = QLabel(
            "A powerful controller for playing up to 4 Toontown Rewritten "
            "accounts simultaneously on modern Linux desktops.\n\n"
            "Features: Global key capture, automated keep-alive, robust Wayland/X11 window management."
        )
        desc_font = QFont()
        desc_font.setPointSize(14)
        desc.setFont(desc_font)
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignCenter)
        
        byline = QLabel("Created by flossbud 🐾")
        byline_font = QFont()
        byline_font.setWeight(QFont.Bold)
        byline_font.setPointSize(16)
        byline.setFont(byline_font)
        byline.setAlignment(Qt.AlignCenter)
        
        card_layout.addWidget(title)
        card_layout.addWidget(desc)
        card_layout.addStretch()
        card_layout.addWidget(byline)
        
        from utils.layout import clamp_centered
        clamp_centered(layout, self.card, 720)
        
    def refresh_theme(self):
        c = get_theme_colors(resolve_theme(self.settings_manager) == "dark")
        is_dark = resolve_theme(self.settings_manager) == "dark"

        self.setStyleSheet(f"background: {c['bg_app']}; color: {c['text_primary']};")
        
        self.card.setStyleSheet(f"""
            QFrame#credits_card {{
                background: {c['bg_card_inner']};
                border: 1px solid {c['border_muted']};
                border-radius: 12px;
            }}
        """)
        apply_card_shadow(self.card, is_dark)
