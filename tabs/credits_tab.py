import os
import sys

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from utils.theme_manager import resolve_theme, get_theme_colors
from utils.version import APP_VERSION

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
        card_layout.setSpacing(12)

        # Title: version pulled from utils/version so it never goes stale
        title = QLabel(f"ToonTown MultiTool v{APP_VERSION}")
        title_font = QFont()
        title_font.setWeight(QFont.Bold)
        title_font.setPointSize(24)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)

        # Hook: one-line personality opener
        hook = QLabel("For when one toon isn't enough.")
        hook_font = QFont()
        hook_font.setWeight(QFont.DemiBold)
        hook_font.setPointSize(16)
        hook.setFont(hook_font)
        hook.setAlignment(Qt.AlignCenter)
        hook.setWordWrap(True)

        # Tagline: factual product description
        tagline = QLabel(
            "A multitoon controller for Toontown Rewritten and Corporate Clash, "
            "on Linux and Windows."
        )
        tagline_font = QFont()
        tagline_font.setPointSize(14)
        tagline.setFont(tagline_font)
        tagline.setWordWrap(True)
        tagline.setAlignment(Qt.AlignCenter)

        # Centerpiece image: assets/flossbud.webp scaled to 400x400.
        # setMinimumSize prevents the parent layout from squeezing the
        # label below the pixmap's size, which would clip the image.
        # Falls back to an empty label if the asset is missing or unreadable;
        # the rest of the card still renders.
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignCenter)
        # _MEIPASS is set by PyInstaller's bootloader to the runtime extraction
        # root; falls back to two dirname() walks from tabs/credits_tab.py to
        # reach the repo root in dev. Same idiom as main.py:_resolve_app_icon.
        base = getattr(
            sys, "_MEIPASS",
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        asset_path = os.path.join(base, "assets", "flossbud.webp")
        pixmap = QPixmap(asset_path)
        if not pixmap.isNull():
            image_label.setPixmap(
                pixmap.scaled(
                    400, 400,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
            image_label.setMinimumSize(400, 400)

        # Byline: emoji font fallback chain so the paw glyph renders on
        # systems whose default font lacks U+1F43E coverage (e.g. Fedora
        # without google-noto-emoji-fonts installed).
        byline = QLabel("by flossbud \U0001F43E")
        byline_font = QFont()
        byline_font.setWeight(QFont.Bold)
        byline_font.setPointSize(16)
        default_family = QApplication.font().family()
        byline_font.setFamilies([default_family, "Noto Color Emoji", "Noto Emoji"])
        byline.setFont(byline_font)
        byline.setAlignment(Qt.AlignCenter)

        # Footer link row: GitHub | Report a bug | Privacy Policy.
        # Single QLabel with rich-text HTML so we get one centered line
        # with three independent anchor tags. Theme color is applied in
        # refresh_theme() via QPalette.Link so it follows light/dark
        # without rebuilding the label text.
        self.footer_links = QLabel(
            '<a href="https://github.com/flossbud/ToonTown-MultiTool">GitHub</a>'
            ' &nbsp;|&nbsp; '
            '<a href="https://github.com/flossbud/ToonTown-MultiTool/issues/new">Report a bug</a>'
            ' &nbsp;|&nbsp; '
            '<a href="https://github.com/flossbud/ToonTown-MultiTool/blob/main/PRIVACY.md">Privacy Policy</a>'
        )
        self.footer_links.setTextFormat(Qt.RichText)
        self.footer_links.setOpenExternalLinks(True)
        self.footer_links.setTextInteractionFlags(Qt.TextBrowserInteraction)
        footer_font = QFont()
        footer_font.setPointSize(11)
        self.footer_links.setFont(footer_font)
        self.footer_links.setAlignment(Qt.AlignCenter)

        card_layout.addWidget(title)
        card_layout.addWidget(hook)
        card_layout.addWidget(tagline)
        card_layout.addSpacing(40)
        card_layout.addWidget(image_label, alignment=Qt.AlignCenter)
        card_layout.addStretch()
        card_layout.addWidget(byline)
        card_layout.addSpacing(12)
        card_layout.addWidget(self.footer_links, alignment=Qt.AlignCenter)

        from utils.layout import clamp_centered
        clamp_centered(layout, self.card, 720)
        
    def refresh_theme(self):
        is_dark = resolve_theme(self.settings_manager) == "dark"
        c = get_theme_colors(is_dark)

        # Tab uses bg_app like every other tab. Labels inherit bg_app via
        # Qt's stylesheet cascade, so we explicitly transparent them below
        # to avoid them painting bg_app chips on top of any backdrop.
        self.setStyleSheet(
            f"background: {c['bg_app']}; color: {c['text_primary']};"
        )

        # Card frame is invisible: same color as the surrounding app
        # background, no border, no shadow. The QFrame is kept only as a
        # layout container for clamp_centered. The QLabel rule clears any
        # inherited background so labels float on whatever's behind them.
        self.card.setStyleSheet(f"""
            QFrame#credits_card {{
                background: {c['bg_app']};
                border: none;
            }}
            QLabel {{
                background: transparent;
            }}
        """)
