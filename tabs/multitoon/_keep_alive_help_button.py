"""Per-slot Keep-Alive discovery affordance.

A QToolButton-based help icon that surfaces the existence of Keep-Alive
when the master setting is disabled. Click opens an explanatory popover
with a "Go to Settings" CTA that emits help_requested; the consuming
MultitoonTab connects that signal to a tab-level signal which the main
window uses to navigate to Settings and highlight the Keep-Alive group.
"""

from PySide6.QtCore import Qt, QPropertyAnimation, QSize, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from utils.icon_factory import make_help_icon
from utils.theme_manager import font_role, get_theme_colors, is_dark_palette


_POPOVER_TITLE = "Keep-Alive"
_POPOVER_BODY = (
    "Sends periodic input to your toons so they don't go AFK while you "
    "focus another window.\n\n"
    "Disabled by default — Toontown Rewritten and Corporate Clash discourage "
    "tools of this kind in their Terms of Service. Use at your own risk. "
    "You can enable it in Settings."
)


class KeepAliveHelpButton(QToolButton):
    """Help-icon button surfacing the now-opt-in Keep-Alive feature."""

    help_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self.setIconSize(self._icon_size())
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("Keep-Alive help")
        self.setAccessibleDescription(
            "Keep-Alive is currently disabled. Click to learn how to enable it in Settings."
        )
        self.setToolTip("Keep-Alive is disabled. Click to learn more.")
        self.setIcon(make_help_icon(self._icon_size().width(), QColor("#bbbbbb")))
        self._popover: QMenu | None = None
        self._popover_title_label: QLabel | None = None
        self._popover_body_label: QLabel | None = None
        self._go_to_settings_button: QPushButton | None = None
        self._dismiss_button: QPushButton | None = None
        self._fade_anim: QPropertyAnimation | None = None
        self.clicked.connect(self._on_clicked)

    def _icon_size(self) -> QSize:
        return QSize(14, 14)

    def refresh_theme(self, theme_colors: dict):
        """Update the icon stroke colour for the active theme.

        Re-bakes the icon at the current iconSize() (NOT the constructor's
        initial _icon_size()) so a theme change in Full UI doesn't downsample
        the icon to 14px and let Qt upscale it to the slot's display rect.

        Also restyles the popover body if it has been created already; the
        popover styles are applied lazily on first show otherwise.
        """
        color = QColor(theme_colors.get("text_secondary", "#bbbbbb"))
        self.setIcon(make_help_icon(self.iconSize().width(), color))
        if self._popover is not None:
            self._apply_popover_styles(theme_colors)

    def _on_clicked(self):
        self._ensure_popover()
        # Anchor below the button. QMenu.popup() is non-blocking; click-outside
        # and Esc dismiss are handled natively.
        self._apply_popover_styles(get_theme_colors(is_dark_palette()))
        below = self.mapToGlobal(self.rect().bottomLeft())
        self._popover.popup(below)
        self._fade_in_popover()

    def _ensure_popover(self):
        if self._popover is not None:
            return
        menu = QMenu(self)
        menu.setAccessibleName("About Keep-Alive")
        action = QWidgetAction(menu)
        widget = self._build_popover_widget()
        action.setDefaultWidget(widget)
        menu.addAction(action)
        self._popover = menu

    def _build_popover_widget(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("ka_help_popover_frame")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        self._popover_title_label = QLabel(_POPOVER_TITLE)
        self._popover_title_label.setObjectName("ka_help_popover_title")
        outer.addWidget(self._popover_title_label)

        self._popover_body_label = QLabel(_POPOVER_BODY)
        self._popover_body_label.setObjectName("ka_help_popover_body")
        self._popover_body_label.setWordWrap(True)
        self._popover_body_label.setMaximumWidth(320)
        outer.addWidget(self._popover_body_label)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        button_row.addStretch(1)

        self._dismiss_button = QPushButton("Dismiss")
        self._dismiss_button.setObjectName("ka_help_dismiss_button")
        self._dismiss_button.setCursor(Qt.PointingHandCursor)
        self._dismiss_button.clicked.connect(self._on_dismiss_clicked)
        button_row.addWidget(self._dismiss_button)

        self._go_to_settings_button = QPushButton("Go to Settings")
        self._go_to_settings_button.setObjectName("ka_help_go_to_settings_button")
        self._go_to_settings_button.setCursor(Qt.PointingHandCursor)
        self._go_to_settings_button.setDefault(True)
        self._go_to_settings_button.clicked.connect(self._on_go_to_settings_clicked)
        button_row.addWidget(self._go_to_settings_button)

        outer.addLayout(button_row)
        return frame

    def _on_go_to_settings_clicked(self):
        if self._popover is not None:
            self._popover.close()
        self.help_requested.emit()

    def _on_dismiss_clicked(self):
        if self._popover is not None:
            self._popover.close()

    def _fade_in_popover(self):
        if self._popover is None:
            return
        effect = QGraphicsOpacityEffect(self._popover)
        self._popover.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(160)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.finished.connect(lambda: self._popover.setGraphicsEffect(None))
        anim.start()
        self._fade_anim = anim

    def _apply_popover_styles(self, theme_colors: dict):
        if self._popover is None:
            return
        c = theme_colors
        title_size = font_role("title")
        body_size = font_role("body")
        accent = c.get("accent_blue_btn", "#0077ff")
        accent_hover = c.get("accent_blue_btn_hover", "#1a88ff")
        on_accent = c.get("text_on_accent", "#ffffff")
        bg_card = c.get("bg_card", "#252525")
        text_primary = c.get("text_primary", "#ffffff")
        text_secondary = c.get("text_secondary", "#bbbbbb")
        border = c.get("border_input", "#3a3a3a")
        btn_hover = c.get("btn_hover", "#3e3e3e")
        self._popover.setStyleSheet(
            f"""
            QMenu {{
                background: {bg_card};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 0;
            }}
            QFrame#ka_help_popover_frame {{
                background: transparent;
            }}
            QLabel#ka_help_popover_title {{
                color: {text_primary};
                font-size: {title_size}px;
                font-weight: 600;
                background: transparent;
            }}
            QLabel#ka_help_popover_body {{
                color: {text_secondary};
                font-size: {body_size}px;
                background: transparent;
            }}
            QPushButton#ka_help_go_to_settings_button {{
                background: {accent};
                color: {on_accent};
                border: 1px solid {accent};
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 600;
            }}
            QPushButton#ka_help_go_to_settings_button:hover {{
                background: {accent_hover};
                border-color: {accent_hover};
            }}
            QPushButton#ka_help_go_to_settings_button:focus {{
                border: 2px solid {accent_hover};
            }}
            QPushButton#ka_help_dismiss_button {{
                background: transparent;
                color: {text_primary};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px 14px;
            }}
            QPushButton#ka_help_dismiss_button:hover {{
                background: {btn_hover};
            }}
            QPushButton#ka_help_dismiss_button:focus {{
                border: 2px solid {accent};
            }}
            """
        )
