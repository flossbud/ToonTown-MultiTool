from __future__ import annotations

import os
import sys
from pathlib import Path

import psutil
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QApplication, QMessageBox, QFrame,
    QPushButton, QScrollArea, QSizePolicy, QFileDialog,
    QGraphicsDropShadowEffect, QStackedWidget
)
from PySide6.QtCore import Property, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from utils.theme_manager import apply_theme, get_theme_colors, resolve_theme
from utils.shared_widgets import IOSToggle, Switch
from utils.widgets import install_modern_scrollbar
from services.ttr_login_service import find_engine_path, get_engine_executable_name
from services.cc_login_service import (
    find_cc_engine_path,
    get_cc_engine_executable_name,
    discover_cc_installs,
)
from services.wine_runtimes import install_signature
from utils.settings_keys import CC_ENGINE_INSTALL_SIGNATURE, SETTINGS_ACTIVE_CATEGORY

SPECIAL_KEYS = {
    Qt.Key_Space: "space", Qt.Key_Return: "Return", Qt.Key_Enter: "Return",
    Qt.Key_Tab: "Tab", Qt.Key_Backspace: "BackSpace", Qt.Key_Escape: "Escape",
    Qt.Key_Shift: "Shift_L", Qt.Key_Control: "Control_L",
    Qt.Key_Alt: "Alt_L", Qt.Key_Delete: "Delete"
}


def _elevated_control_palette(c: dict, is_dark: bool) -> dict:
    """Resting + hover colors for controls living inside a `SettingsGroup`.

    The block paints at an elevated tone (`#333` in dark, `bg_card_inner`
    in light), so the global `btn_bg` / `border_muted` tokens — sized for
    controls on `bg_app` — collide with the block surface (dark mode:
    identical hex) or leave no visible edge (light mode: border == fill).
    Step the controls one tone clear of the block, and use a tonal-only
    hover (Material state-layer style) instead of a brand-color swap —
    Browse / Auto-detect / etc. are tertiary utility actions, not CTAs.
    """
    if is_dark:
        return {
            "bg": "#3a3a3a",
            "border": "#4a4a4a",
            "hover_bg": "#454545",
            "hover_border": "#5a5a5a",
        }
    return {
        "bg": c["btn_bg"],
        "border": c["border_input"],
        "hover_bg": c["btn_hover"],
        "hover_border": c["border_input"],
    }


# ── New primitives (Settings tab redesign 2026-05-23) ─────────────────────────

class SettingsField(QFrame):
    """One labelled control row inside a SettingsPanel.

    label + optional helper (left), arbitrary control widget (right),
    1px hairline divider painted at the bottom unless `is_last` is True.
    """

    HEIGHT_NO_HELPER = 44
    HEIGHT_WITH_HELPER = 60

    def __init__(self, label: str, helper: str | None = None, parent=None):
        super().__init__(parent)
        self._is_last = False
        self.control_widget = None
        self.setMinimumHeight(
            self.HEIGHT_WITH_HELPER if helper else self.HEIGHT_NO_HELPER
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(14)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.setContentsMargins(0, 0, 0, 0)

        self.label_widget = QLabel(label)
        self.label_widget.setStyleSheet("background: transparent; border: none;")
        text_col.addWidget(self.label_widget)

        if helper:
            self.helper_widget = QLabel(helper)
            self.helper_widget.setStyleSheet(
                "background: transparent; border: none;"
            )
            self.helper_widget.setWordWrap(True)
            text_col.addWidget(self.helper_widget)
        else:
            self.helper_widget = None

        lay.addLayout(text_col, 1)
        self._control_slot = QHBoxLayout()
        self._control_slot.setContentsMargins(0, 0, 0, 0)
        self._control_slot.setSpacing(6)
        lay.addLayout(self._control_slot)

        self._c = None
        self._is_dark = True

    @property
    def is_last(self) -> bool:
        return self._is_last

    def set_is_last(self, value: bool) -> None:
        self._is_last = bool(value)
        self.update()

    def set_control(self, widget) -> None:
        """Replace any existing control with the given widget."""
        while self._control_slot.count():
            item = self._control_slot.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self.control_widget = widget
        widget.setParent(self)
        self._control_slot.addWidget(widget)

    def add_control(self, widget) -> None:
        """Append an additional control widget to the right side (multi-button rows)."""
        widget.setParent(self)
        self._control_slot.addWidget(widget)
        if self.control_widget is None:
            self.control_widget = widget

    def apply_theme(self, c, is_dark: bool) -> None:
        self._c = c
        self._is_dark = is_dark
        self.label_widget.setStyleSheet(
            f"font-size: 12.5px; font-weight: 500; color: {c['text_primary']}; "
            "background: transparent; border: none;"
        )
        if self.helper_widget is not None:
            self.helper_widget.setStyleSheet(
                f"font-size: 11px; color: {c['text_muted']}; "
                "background: transparent; border: none;"
            )
        self.update()

    def paintEvent(self, event):
        if self._c is None or self._is_last:
            return
        p = QPainter(self)
        p.setPen(QColor(self._c.get("border_muted", "#2e2e2e")))
        w = self.width()
        h = self.height()
        p.drawLine(16, h - 1, w - 16, h - 1)
        p.end()


class SettingsPanel(QFrame):
    """Bordered card with a brand-colored top stripe, header (logo + title +
    sub + optional buttons), and a body of SettingsFields.

    `stripe` is one of "ttr", "cc", or "neutral" -- the value is resolved to
    a theme token in apply_theme.
    """

    STRIPE_HEIGHT = 3
    HEADER_HEIGHT_WITH_LOGO = 56
    HEADER_HEIGHT_NEUTRAL = 44

    def __init__(
        self,
        title: str,
        sub: str | None = None,
        stripe: str = "neutral",
        logo_path: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        assert stripe in ("ttr", "cc", "neutral"), f"unknown stripe kind: {stripe!r}"
        self.stripe_kind = stripe
        self.fields: list[SettingsField] = []
        self.header_buttons: list = []
        self._c = None
        self._is_dark = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── header ──
        self.header_widget = QWidget(self)
        head_lay = QHBoxLayout(self.header_widget)
        head_lay.setContentsMargins(16, 10, 16, 10)
        head_lay.setSpacing(12)

        if logo_path is not None:
            from PySide6.QtGui import QPixmap
            self.logo_label = QLabel()
            self.logo_label.setFixedSize(40, 40)
            self.logo_label.setAttribute(Qt.WA_TranslucentBackground)
            self.logo_label.setStyleSheet(
                "background: transparent; border-radius: 8px;"
            )
            pm = QPixmap(logo_path)
            if not pm.isNull():
                self.logo_label.setPixmap(
                    pm.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
            head_lay.addWidget(self.logo_label)
            self.header_widget.setFixedHeight(self.HEADER_HEIGHT_WITH_LOGO)
        else:
            self.logo_label = None
            self.header_widget.setFixedHeight(self.HEADER_HEIGHT_NEUTRAL)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("background: transparent; border: none;")
        text_col.addWidget(self.title_label)
        if sub:
            self.sub_label = QLabel(sub)
            self.sub_label.setStyleSheet("background: transparent; border: none;")
            self.sub_label.setWordWrap(True)
            text_col.addWidget(self.sub_label)
        else:
            self.sub_label = None
        self._text_col = text_col
        head_lay.addLayout(text_col, 1)

        self._header_button_slot = QHBoxLayout()
        self._header_button_slot.setContentsMargins(0, 0, 0, 0)
        self._header_button_slot.setSpacing(6)
        head_lay.addLayout(self._header_button_slot)

        outer.addWidget(self.header_widget)

        # ── body ──
        self._body_widget = QWidget(self)
        self._body_layout = QVBoxLayout(self._body_widget)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(0)
        outer.addWidget(self._body_widget)

    # ── public API ────────────────────────────────────────────────────────

    def add_field(self, field: SettingsField) -> None:
        self.fields.append(field)
        self._body_layout.addWidget(field)
        self._refresh_last_flag()

    def add_header_button(self, button) -> None:
        button.setParent(self.header_widget)
        self._header_button_slot.addWidget(button)
        self.header_buttons.append(button)

    def set_sub(
        self,
        text: str,
        *,
        color_override: str | None = None,
        rich_text: bool = False,
    ) -> None:
        """Replace the sub-label text. If the panel was constructed without
        a sub, create one in-place so live status text (paths, errors) can
        render there without restructuring the panel.

        Pass `rich_text=True` for HTML content (e.g. the CC active-install
        chip suffix); otherwise paths containing literal `<` / `>` would be
        interpreted as markup.
        """
        needs_resize = self.sub_label is None
        if self.sub_label is None:
            self.sub_label = QLabel(self.header_widget)
            self.sub_label.setWordWrap(True)
            self.sub_label.setStyleSheet("background: transparent; border: none;")
            self._text_col.addWidget(self.sub_label)
        if needs_resize:
            new_height = (
                self.HEADER_HEIGHT_WITH_LOGO if self.logo_label is not None else 60
            )
            self.header_widget.setFixedHeight(new_height)
        self.sub_label.setTextFormat(Qt.RichText if rich_text else Qt.PlainText)
        self.sub_label.setText(text)
        if color_override is not None:
            self.sub_label.setStyleSheet(
                f"font-size: 11px; color: {color_override}; "
                "background: transparent; border: none;"
            )
        elif self._c is not None:
            self.sub_label.setStyleSheet(
                f"font-size: 11px; color: {self._c['text_muted']}; "
                "background: transparent; border: none;"
            )

    def _refresh_last_flag(self) -> None:
        for i, f in enumerate(self.fields):
            f.set_is_last(i == len(self.fields) - 1)

    # ── theming + paint ───────────────────────────────────────────────────

    def apply_theme(self, c, is_dark: bool) -> None:
        self._c = c
        self._is_dark = is_dark
        self.title_label.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {c['text_primary']}; "
            "background: transparent; border: none;"
        )
        if self.sub_label is not None:
            self.sub_label.setStyleSheet(
                f"font-size: 11px; color: {c['text_muted']}; "
                "background: transparent; border: none;"
            )
        for f in self.fields:
            f.apply_theme(c, is_dark)
        self.update()

    def _stripe_color(self):
        if self._c is None:
            return "#888888"
        token = {
            "ttr": "game_pill_ttr",
            "cc": "game_pill_cc",
            "neutral": "border_light",
        }[self.stripe_kind]
        return self._c.get(token, "#888888")

    def paintEvent(self, event):
        if self._c is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        radius = 10.0
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)

        # Body fill + outer border.
        p.setPen(QPen(QColor(self._c.get("border_card", "#363636")), 1))
        p.setBrush(QColor(self._c.get("bg_card", "#252525")))
        p.drawRoundedRect(rect, radius, radius)

        # Top stripe -- drawn as a filled rect along the top edge, clipped to
        # the rounded silhouette by drawing inside the border.
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._stripe_color()))
        # Round only the top corners -- paint a rounded rect that extends past
        # the bottom of the stripe so the bottom edge sits inside the panel.
        p.drawRoundedRect(
            QRectF(1, 1, self.width() - 2, self.STRIPE_HEIGHT + radius),
            radius, radius,
        )
        # Cover the lower half of that rounded rect (so only the top remains).
        p.setBrush(QColor(self._c.get("bg_card", "#252525")))
        p.drawRect(QRectF(1, self.STRIPE_HEIGHT + 1, self.width() - 2, radius))

        # Header-bottom divider (drawn at the bottom of the header_widget).
        p.setPen(QColor(self._c.get("border_muted", "#2e2e2e")))
        y = self.header_widget.geometry().bottom()
        p.drawLine(0, y, self.width(), y)

        p.end()


class _SidebarItem(QFrame):
    """One clickable row in the sidebar."""

    clicked = Signal(str)  # emits self.key

    def __init__(self, key: str, label: str, parent=None):
        super().__init__(parent)
        self.key = key
        self._active = False
        self._hovered = False
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(36)
        self._c = None
        self._is_dark = True

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        self.label_widget = QLabel(label)
        self.label_widget.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(self.label_widget, 1)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        # When active, leave room for the 2px left accent border by reducing
        # left padding from 16 to 14.
        margins = (14 if self._active else 16, 0, 16, 0)
        self.layout().setContentsMargins(*margins)
        if self._c is not None:
            self._apply_styles()
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        if self._c is not None:
            self._apply_styles()
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        if self._c is not None:
            self._apply_styles()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
            e.accept()
            return
        super().mousePressEvent(e)

    def apply_theme(self, c, is_dark: bool) -> None:
        self._c = c
        self._is_dark = is_dark
        self._apply_styles()
        self.update()

    def _apply_styles(self) -> None:
        c = self._c
        text_color = c["sidebar_text_sel"] if self._active else c["sidebar_text"]
        weight = "600" if self._active else "400"
        self.label_widget.setStyleSheet(
            f"font-size: 12.5px; font-weight: {weight}; "
            f"color: {text_color}; background: transparent; border: none;"
        )

    def paintEvent(self, e):
        if self._c is None:
            return
        p = QPainter(self)
        # Active background
        if self._active:
            p.fillRect(self.rect(), QColor(self._c["sidebar_btn_sel"]))
        elif self._hovered:
            hover = QColor("#ffffff" if self._is_dark else "#0f172a")
            hover.setAlpha(10 if self._is_dark else 12)
            p.fillRect(self.rect(), hover)
        # Active left border accent (2px)
        if self._active:
            p.fillRect(0, 0, 2, self.height(), QColor(self._c["accent_blue_btn"]))
        p.end()


class Sidebar(QFrame):
    """Vertical category rail. Emits `category_selected(str)` on click."""

    category_selected = Signal(str)

    def __init__(self, categories: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.items: list[_SidebarItem] = []
        self.active_key: str = categories[0][0] if categories else ""
        self._c = None
        self._is_dark = True
        self.setFixedWidth(170)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 14, 0, 14)
        lay.setSpacing(0)

        for key, label in categories:
            item = _SidebarItem(key, label, self)
            item.clicked.connect(self._on_item_clicked)
            self.items.append(item)
            lay.addWidget(item)

        lay.addStretch(1)

        if self.items:
            self.items[0].set_active(True)

    def set_active_category(self, key: str) -> None:
        keys = [item.key for item in self.items]
        if key not in keys:
            key = "general"
            if key not in keys:
                return
        self.active_key = key
        for item in self.items:
            item.set_active(item.key == key)

    def _on_item_clicked(self, key: str) -> None:
        if key == self.active_key:
            return
        self.set_active_category(key)
        self.category_selected.emit(key)

    def apply_theme(self, c, is_dark: bool) -> None:
        self._c = c
        self._is_dark = is_dark
        self.setStyleSheet(
            f"background: {c['sidebar_bg']}; "
            f"border-right: 1px solid {c['sidebar_border']};"
        )
        for item in self.items:
            item.apply_theme(c, is_dark)


# ── Settings Row Types ─────────────────────────────────────────────────────────

class SettingsRow(QFrame):
    """Single flat settings row: label + optional sublabel on the left,
    control widget on the right. Paints a 1px bottom divider unless it is
    the last row in its enclosing block."""

    HEIGHT_NO_SUB = 48
    HEIGHT_WITH_SUB = 60

    def __init__(self, label: str, sublabel: str = "", parent=None):
        super().__init__(parent)
        self._label = label
        self._sublabel = sublabel
        self._is_last_in_block = False
        self._hovered = False
        self.setAttribute(Qt.WA_Hover)
        self.setMinimumHeight(
            self.HEIGHT_WITH_SUB if sublabel else self.HEIGHT_NO_SUB
        )

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(14, 0, 14, 0)
        self._layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.setContentsMargins(0, 0, 0, 0)

        self.label_widget = QLabel(label)
        self.label_widget.setStyleSheet("background: transparent; border: none;")
        self.label_widget.setMinimumWidth(1)
        text_col.addWidget(self.label_widget)

        if sublabel:
            self.sub_widget = QLabel(sublabel)
            self.sub_widget.setStyleSheet("background: transparent; border: none;")
            self.sub_widget.setWordWrap(True)
            self.sub_widget.setMinimumWidth(1)
            text_col.addWidget(self.sub_widget)

        self._layout.addLayout(text_col, 1)

    def add_control(self, widget):
        self._layout.addWidget(widget)

    def set_leading_indicator(self, token_name: str):
        """Insert a colored pill at the start of the row.

        `token_name` is a theme-token key (e.g. "game_pill_ttr"); the pill
        resolves it through the palette on apply_theme."""
        self._leading_pill = _LeadingPill(token_name, self)
        self._layout.insertWidget(0, self._leading_pill)

    def set_last_in_block(self, is_last: bool):
        self._is_last_in_block = is_last
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def apply_theme(self, c, is_dark):
        self.label_widget.setStyleSheet(
            f"font-size: 13px; color: {c['text_primary']}; "
            f"background: transparent; border: none;"
        )
        if hasattr(self, "sub_widget"):
            self.sub_widget.setStyleSheet(
                f"font-size: 11.5px; color: {c['text_muted']}; "
                f"background: transparent; border: none;"
            )
        self._c = c
        self._is_dark = is_dark
        self.update()
        if hasattr(self, "_leading_pill"):
            self._leading_pill.apply_theme(c, is_dark)

    def paintEvent(self, e):
        if not hasattr(self, "_c"):
            return
        p = QPainter(self)
        # Hover overlay: subtle ambient highlight, no cursor change.
        if self._hovered:
            overlay = QColor("#ffffff" if self._is_dark else "#0f172a")
            overlay.setAlpha(8 if self._is_dark else 10)
            p.setRenderHint(QPainter.Antialiasing, False)
            p.fillRect(self.rect(), overlay)
        # Bottom divider (unchanged behavior).
        if not self._is_last_in_block:
            p.setRenderHint(QPainter.Antialiasing, False)
            p.setPen(QColor(self._c.get("border_muted", "#2e2e2e")))
            w, h = self.width(), self.height()
            p.drawLine(14, h - 1, w - 14, h - 1)
        p.end()


class ToggleRow(SettingsRow):
    toggled = Signal(bool)

    def __init__(self, label: str, checked: bool, sublabel: str = "", parent=None):
        super().__init__(label, sublabel, parent)
        self.toggle = IOSToggle(checked)
        self.toggle.toggled.connect(self.toggled.emit)
        self.add_control(self.toggle)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, e):
        self.toggle.mousePressEvent(e)

    def isChecked(self):
        return self.toggle.isChecked()

    def setChecked(self, val):
        self.toggle.setChecked(val)


class DropdownRow(SettingsRow):
    index_changed = Signal(int)

    def __init__(self, label: str, options: list, current_index: int = 0, sublabel: str = "", parent=None):
        super().__init__(label, sublabel, parent)
        self._options = options
        self.combo = QComboBox()
        self.combo.addItems(options)
        self.combo.setCurrentIndex(current_index)
        self.combo.setFixedWidth(150)
        self.combo.currentIndexChanged.connect(self.index_changed.emit)
        self.add_control(self.combo)

    def apply_theme(self, c, is_dark):
        super().apply_theme(c, is_dark)
        p = _elevated_control_palette(c, is_dark)
        self.combo.setStyleSheet(f"""
            QComboBox {{
                background: {p['bg']};
                color: {c['text_primary']};
                border: 1px solid {p['border']};
                border-radius: 8px;
                padding: 5px 10px;
                font-size: 13px;
            }}
            QComboBox:hover {{
                background: {p['hover_bg']};
                border: 1px solid {p['hover_border']};
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{
                background: {c['bg_card_inner']};
                color: {c['text_primary']};
                selection-background-color: {p['bg']};
                border-radius: 8px;
            }}
        """)

    def currentIndex(self):
        return self.combo.currentIndex()

    def setCurrentIndex(self, idx):
        self.combo.setCurrentIndex(idx)

    def findText(self, text):
        return self.combo.findText(text)


class ButtonRow(SettingsRow):
    """Row with a single right-aligned QPushButton. Optional destructive
    styling (red outline) for irreversible actions."""

    clicked = Signal()

    def __init__(self, label: str, sublabel: str = "",
                 button_text: str = "...", destructive: bool = False,
                 parent=None):
        super().__init__(label, sublabel, parent)
        self._destructive = destructive
        self.button = QPushButton(button_text)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setFixedHeight(28)
        self.button.clicked.connect(self.clicked.emit)
        self.add_control(self.button)

    def apply_theme(self, c, is_dark):
        super().apply_theme(c, is_dark)
        if self._destructive:
            self.button.setStyleSheet("""
                QPushButton {
                    color: #ff3b30;
                    font-weight: bold;
                    background: transparent;
                    border: 1px solid #ff3b30;
                    border-radius: 6px;
                    padding: 4px 12px;
                }
                QPushButton:hover {
                    background: rgba(255, 59, 48, 0.1);
                }
            """)
        else:
            p = _elevated_control_palette(c, is_dark)
            self.button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {p['bg']};
                    color: {c['text_secondary']};
                    border: 1px solid {p['border']};
                    border-radius: 6px;
                    padding: 4px 12px;
                }}
                QPushButton:hover {{
                    background-color: {p['hover_bg']};
                    color: {c['text_primary']};
                    border: 1px solid {p['hover_border']};
                }}
            """)


class GamePathRow(SettingsRow):
    """Reusable game path row — parameterized for TTR, CC, or any future game."""

    def __init__(self, settings_manager, settings_key: str,
                 exe_name_fn, find_path_fn, label: str = "Game Path",
                 parent=None):
        super().__init__(label, "Not configured", parent)
        # Game identity pill — TTR violet, CC blue.
        if settings_key == "ttr_engine_dir":
            self.set_leading_indicator("game_pill_ttr")
        elif settings_key == "cc_engine_dir":
            self.set_leading_indicator("game_pill_cc")
        self.settings_manager = settings_manager
        self._settings_key = settings_key
        self._approval_key = f"{settings_key}_approved_custom_dir"
        self._exe_name_fn = exe_name_fn
        self._find_path_fn = find_path_fn

        btn_lay = QHBoxLayout()
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.setSpacing(6)

        self.browse_btn = QPushButton("Browse")
        self.browse_btn.setCursor(Qt.PointingHandCursor)
        self.browse_btn.setFixedHeight(28)
        self.browse_btn.clicked.connect(self._browse)
        btn_lay.addWidget(self.browse_btn)

        self.detect_btn = QPushButton("Auto-detect")
        self.detect_btn.setCursor(Qt.PointingHandCursor)
        self.detect_btn.setFixedHeight(28)
        self.detect_btn.clicked.connect(self._auto_detect)
        btn_lay.addWidget(self.detect_btn)

        btn_container = QWidget()
        btn_container.setStyleSheet("background: transparent;")
        btn_container.setLayout(btn_lay)
        self.add_control(btn_container)

        current_path = self.settings_manager.get(self._settings_key, "")
        if not current_path:
            self._auto_detect()
        else:
            self._refresh_display(current_path)

        self.needs_pick: bool = False
        self._cc_installs: list = []
        if settings_key == "cc_engine_dir":
            self._cc_installs = discover_cc_installs()
            stored_sig = self.settings_manager.get(
                CC_ENGINE_INSTALL_SIGNATURE, ""
            ) if self.settings_manager else ""
            sig_match = any(
                install_signature(i) == stored_sig
                for i in self._cc_installs
            ) if stored_sig else False
            if len(self._cc_installs) > 1 and not sig_match:
                self.needs_pick = True
            # Re-render now that _cc_installs reflects the resolved set so
            # the active-install chip suffix can be appended to the subtitle.
            if current_path:
                self._refresh_display(current_path)

    def apply_theme(self, c, is_dark):
        super().apply_theme(c, is_dark)
        self._palette = c
        self._is_dark = is_dark
        p = _elevated_control_palette(c, is_dark)
        btn_style = f"""
            QPushButton {{
                background-color: {p['bg']};
                color: {c['text_secondary']};
                border: 1px solid {p['border']};
                border-radius: 6px; padding: 0 12px;
            }}
            QPushButton:hover {{
                background-color: {p['hover_bg']};
                color: {c['text_primary']};
                border: 1px solid {p['hover_border']};
            }}
        """
        self.browse_btn.setStyleSheet(btn_style)
        self.detect_btn.setStyleSheet(btn_style)
        if getattr(self, "needs_pick", False):
            orange = c.get("accent_orange", "#c47a2a")
            orange_border = c.get("accent_orange_border", "#e0943a")
            self.detect_btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {p['bg']};
                    color: {orange};
                    border: 1px solid {orange_border};
                    border-radius: 6px; padding: 0 12px;
                }}
                QPushButton:hover {{
                    background-color: {p['hover_bg']};
                    color: {orange};
                    border: 1px solid {orange_border};
                }}
                """
            )

    def _refresh_display(self, path: str, error: bool = False):
        if not path:
            self.sub_widget.setText("Not found. Click Browse or Auto-detect.")
            self.sub_widget.setStyleSheet(
                "font-size: 12px; color: #E05252; background: transparent; border: none;"
            )
            return
        if error:
            self.sub_widget.setText(path)
            self.sub_widget.setStyleSheet(
                "font-size: 12px; color: #E05252; background: transparent; border: none;"
            )
            return
        home = os.path.expanduser("~")
        display = path.replace(home, "~") if path.startswith(home) else path
        subtitle = display
        has_chip = False
        if self._settings_key == "cc_engine_dir":
            chip_suffix = self._active_install_chip()
            if chip_suffix:
                subtitle = f"{display}  ·  {chip_suffix}"
                has_chip = True
        # Rich text for chip-containing subtitles; plain text otherwise so
        # paths with literal `<` or `>` characters render correctly.
        from PySide6.QtCore import Qt as _Qt
        self.sub_widget.setTextFormat(_Qt.RichText if has_chip else _Qt.PlainText)
        self.sub_widget.setText(subtitle)
        self.sub_widget.setStyleSheet(
            "font-size: 12px; color: #56c856; background: transparent; border: none;"
        )

    def _active_install_chip(self) -> str:
        """Return an inline HTML chip + display name for the install matching
        the stored signature, or '' if no match or anything goes wrong.

        The returned string is intended to be embedded in a rich-text QLabel.
        Callers that show it must `setTextFormat(Qt.RichText)` on the label.
        """
        try:
            sig = self.settings_manager.get(
                CC_ENGINE_INSTALL_SIGNATURE, ""
            ) if self.settings_manager else ""
            if not sig:
                return ""
            installs = getattr(self, "_cc_installs", None)
            if not installs:
                return ""
            from utils.widgets.picker_card import PickerChip
            for inst in installs:
                if install_signature(inst) == sig:
                    chip_html = PickerChip.inline_html(inst.launcher)
                    # display_name is plain text; safe to interpolate.
                    return f"{chip_html} {inst.display_name}"
        except Exception:
            return ""
        return ""

    def _browse(self):
        exe_name = self._exe_name_fn()
        dir_path = QFileDialog.getExistingDirectory(
            self, f"Select {exe_name} Folder",
            os.path.expanduser("~"),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if dir_path:
            engine = os.path.join(dir_path, exe_name)
            if os.path.isfile(engine):
                self.settings_manager.set(self._settings_key, dir_path)
                self.settings_manager.set(self._approval_key, os.path.realpath(dir_path))
                self._refresh_display(dir_path)
            else:
                self._refresh_display(f"{exe_name} not found in that folder", error=True)

    def _auto_detect(self):
        if self._settings_key == "cc_engine_dir":
            cc_installs = getattr(self, "_cc_installs", None)
            if cc_installs and len(cc_installs) > 1:
                # Multi-install case — always open the picker so the user
                # can pick (when needs_pick) or change their mind (when not).
                # This is what eliminates the silent cc_engine_dir clobber
                # when re-clicking Auto-detect on a resolved row.
                self._open_picker(cc_installs)
                return
        path = self._find_path_fn()
        if path:
            self.settings_manager.set(self._settings_key, path)
            self.settings_manager.set(self._approval_key, "")
            cc_installs = getattr(self, "_cc_installs", None)
            if (
                self._settings_key == "cc_engine_dir"
                and cc_installs is not None
                and len(cc_installs) == 1
            ):
                # Single-install case — record signature for stability.
                self.settings_manager.set(
                    CC_ENGINE_INSTALL_SIGNATURE,
                    install_signature(cc_installs[0]),
                )
            self._refresh_display(path)
        else:
            self._refresh_display("Could not auto-detect. Click Browse.", error=True)

    def _open_picker(self, installs):
        from utils.widgets.cc_install_picker import CCInstallPickerDialog
        stored = self.settings_manager.get(
            CC_ENGINE_INSTALL_SIGNATURE, ""
        ) if self.settings_manager else ""
        dlg = CCInstallPickerDialog(
            installs, parent=self.window(), active_signature=stored or None,
        )
        if dlg.exec() == dlg.DialogCode.Accepted:
            picked = dlg.selected_install()
            if picked:
                self._apply_picked_install(picked)

    def _apply_picked_install(self, install):
        path = os.path.dirname(install.exe_path)
        self.settings_manager.set(self._settings_key, path)
        self.settings_manager.set(self._approval_key, "")
        self.settings_manager.set(
            CC_ENGINE_INSTALL_SIGNATURE,
            install_signature(install),
        )
        self.needs_pick = False
        try:
            self._cc_installs = discover_cc_installs()
        except Exception:
            pass
        self._refresh_display(path)
        # Force re-application of the standard (non-glow) button style.
        if hasattr(self, "_palette"):
            self.apply_theme(self._palette, getattr(self, "_is_dark", True))


class CompatRuntimeRow(SettingsRow):
    """Row that shows the active CC install's compatibility runtime.

    For steam-proton installs on Linux, a Change button opens the
    compat-picker dialog and persists the user's choice in
    cc_steam_proton_override. For other launcher types, the row is
    read-only (just shows the detected runner). On Windows, the row
    is hidden entirely (native launching only).
    """

    LABEL = "Compatibility runtime"

    def __init__(self, settings_manager, get_active_install, parent=None):
        # Pass a non-empty sublabel so SettingsRow creates self.sub_widget;
        # refresh() rewrites the text before the row is ever shown. The
        # sublabel pattern (label on top, value on a muted second line)
        # mirrors GamePathRow and fits the Settings tab's default width
        # without truncating the main label.
        super().__init__(self.LABEL, " ", parent=parent)
        self.settings_manager = settings_manager
        self._get_active_install = get_active_install
        self.is_platform_hidden = sys.platform == "win32"

        if self.is_platform_hidden:
            self.hide()
            return

        self.change_button = QPushButton("Change…")
        self.change_button.setObjectName("compat_runtime_change")
        self.change_button.setCursor(Qt.PointingHandCursor)
        self.change_button.setFixedHeight(28)
        self.change_button.clicked.connect(self._on_change_clicked)
        self.add_control(self.change_button)

        if self.settings_manager is not None:
            self.settings_manager.on_change(self._on_setting_changed)
        self.refresh()

    def refresh(self):
        """Recompute the row state from the active install + override."""
        if self.is_platform_hidden:
            return
        install = self._get_active_install() if self._get_active_install else None
        if install is None:
            self.hide()
            return
        self.show()

        if install.launcher != "steam-proton":
            self.sub_widget.setText(self._readonly_label(install))
            self.sub_widget.setStyleSheet("")  # let apply_theme handle muted color
            self.change_button.hide()
            return

        self.change_button.show()
        from services.cc_launcher import resolve_effective_proton
        chosen = resolve_effective_proton(install, self.settings_manager)
        if chosen is None:
            self.sub_widget.setText("No Steam Proton found")
            self.sub_widget.setStyleSheet("color: #c0392b;")  # warning
            self.change_button.setEnabled(False)
            return

        self.change_button.setEnabled(True)
        nickname = self._nickname_for(chosen)
        override = (self.settings_manager.get("cc_steam_proton_override", "")
                    if self.settings_manager else "")
        suffix = "custom" if override else "default"
        self.sub_widget.setText(f"{nickname} · {suffix}")
        self.sub_widget.setStyleSheet("")

    @staticmethod
    def _readonly_label(install):
        if install.launcher == "bottles":
            runner = (install.metadata.get("bottle_display_name")
                      or install.metadata.get("bottle_name") or "(unknown)")
            return f"Bottles · {runner}"
        if install.launcher == "lutris":
            # Lutris pins wine version per-game inside its YAML config, but
            # _parse_lutris_yaml only surfaces lutris_slug / lutris_name in
            # metadata today. Show the game name as the next best identifier.
            name = install.metadata.get("lutris_name") or install.metadata.get("lutris_slug") or "(unknown)"
            return f"Lutris · {name}"
        if install.launcher == "wine":
            return "Wine · system wine"
        if install.launcher == "native":
            return "Native (no compatibility layer)"
        return install.launcher

    @staticmethod
    def _nickname_for(proton_dir: str) -> str:
        from services.steam_proton_tools import enumerate_proton_tools
        for tool in enumerate_proton_tools():
            if tool.proton_dir == proton_dir:
                return tool.nickname
        return os.path.basename(proton_dir.rstrip(os.sep))

    def _on_setting_changed(self, key, _value):
        if key == "cc_steam_proton_override" or key == "cc_engine_dir":
            self.refresh()

    def _on_change_clicked(self):
        from services.steam_proton_tools import enumerate_proton_tools
        from utils.widgets.cc_compat_picker import CCCompatPickerDialog
        install = self._get_active_install() if self._get_active_install else None
        if install is None or install.launcher != "steam-proton":
            return
        tools = enumerate_proton_tools()
        override = (self.settings_manager.get("cc_steam_proton_override", "")
                    if self.settings_manager else "")
        from services.cc_launcher import resolve_effective_proton
        resolved = resolve_effective_proton(install, self.settings_manager) or ""
        default_display = self._nickname_for(resolved) if resolved else "(none installed)"
        dlg = CCCompatPickerDialog(
            tools=tools,
            current_override=override,
            steam_default_display=default_display,
            parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        chosen = dlg.chosen_override()
        if chosen is None:
            return
        if self.settings_manager is not None:
            self.settings_manager.set("cc_steam_proton_override", chosen)
        self.refresh()


# ── Section Group ──────────────────────────────────────────────────────────────

class SettingsGroup(QWidget):
    """Soft-surface section block. Paints a rounded fill behind its rows
    and renders an optional sentence-case title above the block."""

    CORNER_RADIUS = 12

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self._title = title
        self._rows = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if title:
            self.title_label = QLabel(title)
            self.title_label.setContentsMargins(2, 0, 0, 8)
            layout.addWidget(self.title_label)

        # Shadow wrapper — `_block_wrapper` hosts a childless shadow caster
        # behind `_block`. The real block stays effect-free so its custom
        # paintEvent and child rows render normally.
        self._block_wrapper = _SectionBlockWrapper(self)
        wrapper_layout = QVBoxLayout(self._block_wrapper)
        wrapper_layout.setContentsMargins(
            _SectionBlockWrapper.MARGIN_X,
            _SectionBlockWrapper.MARGIN_TOP,
            _SectionBlockWrapper.MARGIN_X,
            _SectionBlockWrapper.MARGIN_BOTTOM,
        )
        wrapper_layout.setSpacing(0)

        self._block = _SectionBlock(self._block_wrapper)
        self._rows_layout = QVBoxLayout(self._block)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        wrapper_layout.addWidget(self._block)

        layout.addWidget(self._block_wrapper)

    def add_row(self, row):
        self._rows.append(row)
        self._rows_layout.addWidget(row)
        self._refresh_last_row()

    def _refresh_last_row(self):
        for i, row in enumerate(self._rows):
            row.set_last_in_block(i == len(self._rows) - 1)

    def apply_theme(self, c, is_dark):
        if hasattr(self, "title_label"):
            self.title_label.setStyleSheet(
                f"font-size: 14px; font-weight: 700; font-style: normal; "
                f"letter-spacing: 0.15px; "
                f"color: {c['text_primary']}; background: transparent;"
            )
        self._block_wrapper.apply_theme(c, is_dark)
        self._block.apply_theme(c, is_dark)
        for row in self._rows:
            row.apply_theme(c, is_dark)


class _SectionBlock(QFrame):
    """Inner block widget — paints the rounded soft-surface fill that backs
    the rows. Split out so the rounded fill lives on its own widget and
    doesn't interfere with the group's title-above-block layout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._c = None
        self._is_dark = True

    def apply_theme(self, c, is_dark):
        self._c = c
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, e):
        if self._c is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Override the bg_card_inner / border_card tokens in dark mode —
        # they're only ~8% lighter than bg_app, which doesn't read as a
        # distinct elevated surface against the page. In light mode the
        # tokens work as-is (bg_card_inner is properly darker than bg_app).
        if self._is_dark:
            fill_color = "#333333"
            border_color = "#4a4a4a"
        else:
            fill_color = self._c.get("bg_card_inner", "#f1f5f9")
            border_color = self._c.get("border_card", "#e2e8f0")

        pen = QPen(QColor(border_color))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(QColor(fill_color))
        r = float(SettingsGroup.CORNER_RADIUS)
        p.drawRoundedRect(
            QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), r, r
        )
        p.end()


class _SectionBlockWrapper(QWidget):
    """Transparent wrapper that hosts a blurred shadow behind its inner
    `_SectionBlock` child.

    The effect lives on a simple, childless shadow caster instead of the real
    block. Applying effects to the block itself breaks custom painting with
    child rows, while painting the shadow as filled concentric rects creates
    visible bands. This keeps the real block plain and lets Qt blur one clean
    rounded silhouette.
    """

    MARGIN_X = 28
    MARGIN_TOP = 16
    MARGIN_BOTTOM = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_dark = True
        self._c = None
        self._shadow_live = True
        self.setObjectName("settings_section_wrapper")
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setStyleSheet("background: transparent; border: none;")

        self._shadow = _SectionBlockShadow(self)
        self._shadow.lower()
        self._shadow_effect = QGraphicsDropShadowEffect(self._shadow)
        self._shadow_effect.setBlurRadius(28)
        self._shadow_effect.setOffset(0, 6)
        self._shadow.setGraphicsEffect(self._shadow_effect)

    def apply_theme(self, c, is_dark):
        self._c = c
        self._is_dark = is_dark
        color = QColor(0, 0, 0) if is_dark else QColor(15, 23, 42)
        color.setAlpha(90 if is_dark else 36)
        self._shadow_effect.setColor(color)
        self._shadow.apply_theme(c, is_dark)
        self._sync_shadow_geometry()
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_shadow_geometry()

    def set_shadow_live(self, live: bool):
        self._shadow_live = live
        self._shadow.setVisible(live)
        if live:
            self._sync_shadow_geometry()

    def _sync_shadow_geometry(self):
        # Z-order is set once at construction (shadow is created before the
        # block is added to the layout, so it's naturally below). Calling
        # lower()/raise_() per resize forces full repaints of the block and
        # every row child each animation frame, which destroys the collapse
        # animation's frame budget.
        if not self._shadow_live:
            return
        layout = self.layout()
        if layout is None or layout.count() == 0:
            return
        block_widget = layout.itemAt(0).widget()
        if block_widget is None:
            return
        self._shadow.setGeometry(block_widget.geometry())


class _SectionBlockShadow(QFrame):
    """Childless silhouette used only as the source for the shadow blur."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._c = None
        self._is_dark = True
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent; border: none;")

    def apply_theme(self, c, is_dark):
        self._c = c
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, e):
        if self._c is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        fill_color = (
            "#333333" if self._is_dark
            else self._c.get("bg_card_inner", "#f1f5f9")
        )
        p.setBrush(QColor(fill_color))
        radius = float(SettingsGroup.CORNER_RADIUS)
        p.drawRoundedRect(
            QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), radius, radius
        )
        p.end()


class _LeadingPill(QWidget):
    """Small colored circle with a translucent halo. Used as a leading
    indicator on rows that carry an identity color (e.g. game path rows
    showing TTR violet or CC blue)."""

    SIZE = 10
    HALO = 2

    def __init__(self, token_name: str, parent=None):
        super().__init__(parent)
        self._token = token_name
        self._resolved_color: str | None = None
        side = self.SIZE + self.HALO * 2
        self.setFixedSize(side, side)

    def apply_theme(self, c, is_dark):
        self._resolved_color = c.get(self._token, "#888888")
        self.update()

    def paintEvent(self, e):
        if self._resolved_color is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        # Halo — 25% alpha of the dot color, full widget size.
        halo = QColor(self._resolved_color)
        halo.setAlpha(64)
        p.setBrush(halo)
        side = self.SIZE + self.HALO * 2
        p.drawEllipse(QRectF(0, 0, side, side))

        # Dot — full-alpha core, centered, SIZE×SIZE.
        p.setBrush(QColor(self._resolved_color))
        p.drawEllipse(QRectF(self.HALO, self.HALO, self.SIZE, self.SIZE))
        p.end()


class _ChevronWidget(QWidget):
    """A small right-pointing triangle that rotates around its center.
    Exposes a `rotation` Qt property (degrees) so it can be animated."""

    SIZE = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rotation = 0.0
        self._color = None
        self.setFixedSize(self.SIZE, self.SIZE)

    def _get_rotation(self) -> float:
        return self._rotation

    def _set_rotation(self, value: float):
        self._rotation = float(value)
        self.update()

    rotation = Property(float, _get_rotation, _set_rotation)

    def apply_theme(self, c, is_dark):
        self._color = c.get("text_muted", "#888")
        self.update()

    def paintEvent(self, e):
        if self._color is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        p.translate(cx, cy)
        p.rotate(self._rotation)
        # Right-pointing triangle at rotation=0, centered on origin.
        tri = QPolygonF([
            QPointF(-2.5, -3.5),
            QPointF(-2.5,  3.5),
            QPointF( 3.5,  0.0),
        ])
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._color))
        p.drawPolygon(tri)
        p.end()


class _CollapsibleContentClip(QWidget):
    """Fixed-height viewport that clips a full-height settings row container."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._content = None
        self._forced_height = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent; border: none;")

    def set_content_widget(self, widget):
        self._content = widget
        widget.setParent(self)
        self._sync_content_geometry()

    def natural_height(self) -> int:
        if self._content is None or self._content.layout() is None:
            return 0
        return self._content.layout().minimumSize().height()

    def set_forced_height(self, height: int):
        self._forced_height = max(0, int(height))
        self.setMinimumHeight(self._forced_height)
        self.setMaximumHeight(self._forced_height)
        self._sync_content_geometry()
        self.updateGeometry()

    def release_height(self):
        self._forced_height = None
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self._sync_content_geometry()
        self.updateGeometry()

    def sizeHint(self):
        return QSize(0, self._height_hint())

    def minimumSizeHint(self):
        return QSize(0, self._height_hint())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_content_geometry()

    def _height_hint(self) -> int:
        if self._forced_height is not None:
            return self._forced_height
        return self.natural_height()

    def _sync_content_geometry(self):
        if self._content is None:
            return
        height = max(self.natural_height(), self.height(), self._height_hint())
        self._content.setGeometry(0, 0, self.width(), height)


class CollapsibleSettingsGroup(SettingsGroup):
    """Section block whose first row is a clickable header (title + chevron).
    Clicking the header toggles visibility of the remaining rows and persists
    the collapsed state via `settings_manager.set(persist_key, bool)`.

    Unlike `SettingsGroup`, the section title is rendered *inside* the block
    as the first row, not above it. This keeps the collapsed state looking
    like a single coherent control instead of an empty section beneath a
    floating title.
    """

    scroll_reserve_changed = Signal(int)

    def __init__(self, title: str, settings_manager, persist_key: str,
                 parent=None):
        # Don't render the title above the block — we own the header instead.
        super().__init__(title="", parent=parent)
        self._title_text = title
        self._settings_manager = settings_manager
        self._persist_key = persist_key
        self._collapsed = bool(
            settings_manager.get(persist_key, True)
        )
        self._collapse_anim = None
        self._chevron_anim = None
        self._animated_content_height = 0
        self._scroll_reserve_base = 0

        self._header = _CollapsibleHeader(title, self._collapsed, self)
        self._header.clicked.connect(self.toggle)

        # The clip animates height while the inner content container keeps its
        # natural row layout. That prevents labels/buttons from being squeezed
        # while the Advanced body opens or closes.
        self._content_clip = _CollapsibleContentClip(self._block)
        self._content_container = QWidget(self._content_clip)
        self._content_container.setStyleSheet(
            "background: transparent; border: none;"
        )
        self._content_clip.set_content_widget(self._content_container)
        self._rows_layout = QVBoxLayout(self._content_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)

        # SettingsGroup.__init__ already installed a QVBoxLayout on self._block
        # for rows. Detach that layout (Qt requires reparenting it to a
        # throwaway widget — you cannot setLayout(None) on a widget that
        # already has a layout). Then install a fresh layout with header + container.
        old_block_layout = self._block.layout()
        if old_block_layout is not None:
            tmp = QWidget()
            tmp.setLayout(old_block_layout)
            tmp.deleteLater()
        block_layout = QVBoxLayout(self._block)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(0)
        block_layout.addWidget(self._header)
        block_layout.addWidget(self._content_clip)

        # Apply initial collapsed state to the container.
        if self._collapsed:
            self._content_clip.set_forced_height(0)

    def add_row(self, row):
        self._rows.append(row)
        self._rows_layout.addWidget(row)
        self._refresh_last_row()
        # If we're collapsed, hide the row so initial layout is right and
        # it doesn't briefly render before the next collapse animation.
        if self._collapsed:
            row.setVisible(False)
        else:
            self._content_clip.release_height()

    def is_collapsed(self) -> bool:
        return self._collapsed

    def _get_content_height(self) -> int:
        return self._animated_content_height

    def _set_content_height(self, value: int):
        height = max(0, int(value))
        self._animated_content_height = height
        self._content_clip.set_forced_height(height)
        self._block.updateGeometry()
        self._block_wrapper.updateGeometry()
        self.updateGeometry()
        parent = self.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().invalidate()
        self._emit_scroll_reserve(height)

    content_height = Property(int, _get_content_height, _set_content_height)

    def _content_natural_height(self) -> int:
        # Settings rows declare minimum heights for the polished row rhythm;
        # their Qt sizeHint can be taller/shorter depending on label content.
        # The settled layout uses the minimum height, so animate to that value
        # to avoid a final snap when the fixed animation height is released.
        return self._content_container.layout().minimumSize().height()

    def _release_content_height(self):
        self._content_clip.release_height()
        self._block.updateGeometry()
        self._block_wrapper.updateGeometry()
        self.updateGeometry()

    def _emit_scroll_reserve(self, content_height: int):
        if self._scroll_reserve_base <= 0:
            self.scroll_reserve_changed.emit(0)
            return
        reserve = max(0, self._scroll_reserve_base - content_height)
        self.scroll_reserve_changed.emit(reserve)

    def toggle(self):
        self._collapsed = not self._collapsed
        self._settings_manager.set(self._persist_key, self._collapsed)
        self._header.set_collapsed(self._collapsed)

        # Interrupt any in-flight animation.
        if self._collapse_anim is not None:
            self._collapse_anim.stop()
            self._collapse_anim = None
            self.scroll_reserve_changed.emit(0)
            self._scroll_reserve_base = 0

        # Interrupt any in-flight chevron animation.
        if self._chevron_anim is not None:
            self._chevron_anim.stop()
            self._chevron_anim = None

        from PySide6.QtCore import QEasingCurve, QPropertyAnimation
        import utils.motion as motion

        # Resolve target content height. Note: rows must remain visible during
        # a collapse animation, otherwise the layout's preferred height drops
        # to 0 immediately and there's nothing to animate.
        if self._collapsed:
            start_h = self._content_clip.height()
            if start_h <= 0:
                start_h = self._content_natural_height()
            end_h = 0
            self._scroll_reserve_base = start_h
        else:
            # Rows need to be visible during the expand animation so the
            # container has a non-zero sizeHint to animate toward.
            for row in self._rows:
                row.setVisible(True)
            end_h = self._content_natural_height()
            start_h = 0
            self._scroll_reserve_base = 0
            self.scroll_reserve_changed.emit(0)

        # Reduced motion: snap to the final state synchronously.
        if motion.is_reduced():
            self._block_wrapper.set_shadow_live(True)
            if self._collapsed:
                self._set_content_height(0)
                for row in self._rows:
                    row.setVisible(False)
            else:
                self._release_content_height()
            self.scroll_reserve_changed.emit(0)
            self._scroll_reserve_base = 0
            return

        # Animate.
        raw_duration = motion.DURATION_PAGE * motion._TEST_DURATION_SCALE
        duration = 0 if raw_duration == 0.0 else max(1, int(raw_duration))
        self._block_wrapper.set_shadow_live(False)

        anim = QPropertyAnimation(self, b"content_height")
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.setStartValue(start_h)
        anim.setEndValue(end_h)

        def _on_finished():
            # After collapse: hide rows so the layout doesn't reserve space
            # if/when maxHeight is lifted again.
            # After expand: lift the maximumHeight cap so the container can
            # grow if the user resizes or rows are added later.
            if self._collapsed:
                self._set_content_height(0)
                for row in self._rows:
                    row.setVisible(False)
            else:
                self._release_content_height()
            self._block_wrapper.set_shadow_live(True)
            self.scroll_reserve_changed.emit(0)
            self._scroll_reserve_base = 0
            self._collapse_anim = None

        anim.finished.connect(_on_finished)
        self._collapse_anim = anim
        # Pre-set the start value before starting so the first frame is correct.
        self.content_height = start_h
        anim.start()

        # Parallel chevron rotation animation.
        chevron_anim = QPropertyAnimation(self._header._chevron, b"rotation")
        chevron_anim.setDuration(duration)
        chevron_anim.setEasingCurve(QEasingCurve.InOutCubic)
        # Reverse the snap that set_collapsed already applied — start from
        # the previous angle and animate to the new one.
        chevron_anim.setStartValue(90.0 if self._collapsed else 0.0)
        chevron_anim.setEndValue(0.0 if self._collapsed else 90.0)

        def _on_chevron_done():
            self._chevron_anim = None

        chevron_anim.finished.connect(_on_chevron_done)
        self._chevron_anim = chevron_anim
        # Pre-set the start frame so the visual is consistent.
        self._header._chevron.rotation = 90.0 if self._collapsed else 0.0
        chevron_anim.start()

    def apply_theme(self, c, is_dark):
        super().apply_theme(c, is_dark)
        self._header.apply_theme(c, is_dark)


class _CollapsibleHeader(QFrame):
    """Clickable header row used inside a `CollapsibleSettingsGroup`.
    Same height as a no-sublabel SettingsRow (48px), with the section title
    on the left and a chevron on the right."""

    clicked = Signal()

    def __init__(self, title: str, collapsed: bool, parent=None):
        super().__init__(parent)
        self._collapsed = collapsed
        self.setFixedHeight(SettingsRow.HEIGHT_NO_SUB)
        self.setCursor(Qt.PointingHandCursor)
        self._hovered = False
        self.setAttribute(Qt.WA_Hover)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(12)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(self.title_label, 1)

        self._chevron = _ChevronWidget(self)
        self._chevron.rotation = 90.0 if not collapsed else 0.0
        lay.addWidget(self._chevron)

    def set_collapsed(self, collapsed: bool):
        self._collapsed = collapsed
        # Snap the chevron rotation. The animated case in
        # CollapsibleSettingsGroup.toggle pre-sets this to the start value
        # before starting the animation, then animates over duration.
        self._chevron.rotation = 0.0 if collapsed else 90.0
        self.update()

    def apply_theme(self, c, is_dark):
        self._c = c
        self._is_dark = is_dark
        self.title_label.setStyleSheet(
            f"font-size: 14px; font-weight: 700; font-style: normal; "
            f"letter-spacing: 0.15px; "
            f"color: {c['text_primary']}; background: transparent; border: none;"
        )
        self._chevron.apply_theme(c, is_dark)
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
            e.accept()
            return
        super().mousePressEvent(e)

    def paintEvent(self, e):
        if not hasattr(self, "_c"):
            return
        p = QPainter(self)
        # Header hover overlay — slightly stronger than SettingsRow's so this
        # row reads as clickable.
        if self._hovered:
            overlay = QColor("#ffffff" if self._is_dark else "#0f172a")
            overlay.setAlpha(13 if self._is_dark else 15)
            p.fillRect(self.rect(), overlay)
        # Divider only when expanded.
        if not self._collapsed:
            p.setRenderHint(QPainter.Antialiasing, False)
            p.setPen(QColor(self._c.get("border_muted", "#2e2e2e")))
            w, h = self.width(), self.height()
            p.drawLine(14, h - 1, w - 14, h - 1)
        p.end()


# ── Main Settings Tab ──────────────────────────────────────────────────────────

class SettingsTab(QWidget):
    # ── Public signals (unchanged contract) ───────────────────────────────
    debug_visibility_changed = Signal(bool)
    theme_changed = Signal()
    input_backend_changed = Signal()
    clear_credentials_requested = Signal()
    max_accounts_changed = Signal(int)

    CATEGORIES = [
        ("general", "General"),
        ("games", "Games"),
        ("keep_alive", "Keep-Alive"),
        ("advanced", "Advanced"),
    ]

    def __init__(self, settings_manager):
        super().__init__()
        self.settings_manager = settings_manager
        self.pages: dict[str, QWidget] = {}
        self._panels: list[SettingsPanel] = []
        self._current_page_key: str = "general"
        self._update_checker = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = Sidebar(self.CATEGORIES)
        outer.addWidget(self.sidebar)

        # Content stack: a single QStackedWidget holding one scroll-area per page.
        self._stack = QStackedWidget(self)
        outer.addWidget(self._stack, 1)

        for key, _label in self.CATEGORIES:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            install_modern_scrollbar(
                scroll,
                is_dark=resolve_theme(self.settings_manager) == "dark",
            )

            page = QWidget()
            page_lay = QVBoxLayout(page)
            page_lay.setContentsMargins(28, 22, 28, 28)
            page_lay.setSpacing(14)
            page_lay.setAlignment(Qt.AlignTop)

            # Page title + subtitle scaffolding (text filled by category builder).
            title = QLabel()
            title.setObjectName("settings_page_title")
            page_lay.addWidget(title)
            sub = QLabel()
            sub.setObjectName("settings_page_subtitle")
            sub.setWordWrap(True)
            page_lay.addWidget(sub)
            # Builder methods populate panels below the subtitle; we expose
            # the layout via attribute so they can append to it.
            page._title_label = title  # type: ignore[attr-defined]
            page._sub_label = sub      # type: ignore[attr-defined]
            page._panel_layout = page_lay  # type: ignore[attr-defined]
            page_lay.addStretch(1)

            scroll.setWidget(page)
            self.pages[key] = page
            self._stack.addWidget(scroll)

        # Builder methods fill each page in. (Stubs in this task — Tasks 5-8 fill
        # the real content.)
        self._build_general_page(self.pages["general"])
        self._build_games_page(self.pages["games"])
        self._build_keep_alive_page(self.pages["keep_alive"])
        self._build_advanced_page(self.pages["advanced"])

        # Restore persisted category.
        persisted = self.settings_manager.get(SETTINGS_ACTIVE_CATEGORY, "general")
        self._show_category(persisted)
        self.sidebar.category_selected.connect(self._on_category_selected)

        self.refresh_theme()

    # ── Page builders ─────────────────────────────────────────────────────
    def _build_general_page(self, page):
        from utils import build_info
        page._title_label.setText("General")
        page._sub_label.setText("App-wide preferences.")

        # Insertion point: the page layout currently has [title, sub, <stretch>].
        # Insert panels at index 2 (just before the stretch).
        lay = page._panel_layout
        insert_at = lay.count() - 1  # before the stretch

        # ── Appearance & behavior ────────────────────────────────────────
        appearance = SettingsPanel(title="Appearance & behavior")
        self._panels.append(appearance)

        # Theme
        theme_value = self.settings_manager.get("theme", "system")
        theme_idx = (
            ["system", "light", "dark"].index(theme_value)
            if theme_value in ("system", "light", "dark")
            else 0
        )
        theme_field = SettingsField("Appearance")
        theme_combo = QComboBox()
        theme_combo.addItems(["System", "Light", "Dark"])
        theme_combo.setCurrentIndex(theme_idx)
        theme_combo.setFixedWidth(150)
        theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_field.set_control(theme_combo)
        appearance.add_field(theme_field)

        # Max accounts per game
        saved_max = self.settings_manager.get("max_accounts_per_game", 4)
        max_idx = max(0, min(saved_max - 4, 4))
        max_field = SettingsField(
            "Max accounts per game",
            helper="How many account slots per game (TTR / CC).",
        )
        max_combo = QComboBox()
        max_combo.addItems(["4", "5", "6", "7", "8"])
        max_combo.setCurrentIndex(max_idx)
        max_combo.setFixedWidth(150)
        max_combo.currentIndexChanged.connect(self._on_max_accounts_changed)
        max_field.set_control(max_combo)
        appearance.add_field(max_field)

        # Reduce motion (tri-state)
        import utils.motion as motion
        motion.set_settings_manager(self.settings_manager)
        explicit = self.settings_manager.get("reduce_motion_set_explicitly", False)
        if not explicit:
            rm_idx = 0
            # Write the canonical "system default" state so settings always
            # reflect the UI, even when the combo hasn't been interacted with.
            self.settings_manager.set("reduce_motion_set_explicitly", False)
        elif self.settings_manager.get("reduce_motion", False):
            rm_idx = 1
        else:
            rm_idx = 2
        rm_field = SettingsField(
            "Reduce motion",
            helper=(
                "System default follows your desktop's reduce-motion setting. "
                "Choose On or Off to override."
            ),
        )
        rm_combo = QComboBox()
        rm_combo.addItems(["System default", "On", "Off"])
        rm_combo.setCurrentIndex(rm_idx)
        rm_combo.setFixedWidth(150)
        rm_combo.currentIndexChanged.connect(self._on_reduce_motion_changed)
        rm_field.set_control(rm_combo)
        appearance.add_field(rm_field)

        lay.insertWidget(insert_at, appearance)
        insert_at += 1

        # ── Updates ──────────────────────────────────────────────────────
        updates = SettingsPanel(title="Updates")
        self._panels.append(updates)

        upd_enabled = bool(self.settings_manager.get("check_for_updates_at_startup", False))
        upd_field = SettingsField(
            "Check for updates on startup",
            helper="Look for new releases when the app launches.",
        )
        upd_switch = Switch(upd_enabled)
        upd_switch.toggled.connect(
            lambda v: self.settings_manager.set("check_for_updates_at_startup", v)
        )
        upd_field.set_control(upd_switch)
        updates.add_field(upd_field)

        check_now_field = SettingsField(
            "Check for updates now",
            helper=f"Current build: {build_info.version_string()}",
        )
        self._check_now_btn = QPushButton("Check now")
        self._check_now_btn.setCursor(Qt.PointingHandCursor)
        self._check_now_btn.setFixedHeight(28)
        self._check_now_btn.clicked.connect(self._on_check_now_clicked)
        check_now_field.set_control(self._check_now_btn)
        self._check_now_field = check_now_field  # for completion handlers
        updates.add_field(check_now_field)

        lay.insertWidget(insert_at, updates)

    def _build_games_page(self, page):
        pass

    def _build_keep_alive_page(self, page):
        pass

    def _build_advanced_page(self, page):
        pass

    # ── Category routing ──────────────────────────────────────────────────
    def _on_category_selected(self, key: str):
        self._show_category(key)
        self.settings_manager.set(SETTINGS_ACTIVE_CATEGORY, key)

    def _show_category(self, key: str):
        keys = [k for k, _ in self.CATEGORIES]
        if key not in keys:
            key = "general"
        self._current_page_key = key
        self.sidebar.set_active_category(key)
        idx = keys.index(key)
        self._stack.setCurrentIndex(idx)

    # ── General handlers ──────────────────────────────────────────────────
    def _on_theme_changed(self, idx):
        theme = ["system", "light", "dark"][idx]
        self.settings_manager.set("theme", theme)
        apply_theme(QApplication.instance(), resolve_theme(self.settings_manager))
        self.theme_changed.emit()

    def _on_max_accounts_changed(self, idx):
        value = idx + 4
        self.settings_manager.set("max_accounts_per_game", value)
        self.max_accounts_changed.emit(value)

    def _on_reduce_motion_changed(self, idx):
        if idx == 0:
            self.settings_manager.set("reduce_motion_set_explicitly", False)
            self.settings_manager.set("reduce_motion", False)
        elif idx == 1:
            self.settings_manager.set("reduce_motion_set_explicitly", True)
            self.settings_manager.set("reduce_motion", True)
        else:
            self.settings_manager.set("reduce_motion_set_explicitly", True)
            self.settings_manager.set("reduce_motion", False)

    def _on_check_now_clicked(self):
        if self._update_checker is None:
            return
        self._check_now_btn.setEnabled(False)
        self._check_now_btn.setText("Checking...")
        self._update_checker.check_async(manual=True)

    def _restore_check_button(self):
        self._check_now_btn.setEnabled(True)
        self._check_now_btn.setText("Check now")

    def _on_check_complete_update(self, info):
        self._restore_check_button()

    def _on_check_complete_no_update(self):
        from PySide6.QtCore import QTimer
        from utils import build_info
        self._restore_check_button()
        helper = self._check_now_field.helper_widget
        if helper is not None:
            helper.setText("You're on the latest version.")
            default_text = f"Current build: {build_info.version_string()}"
            QTimer.singleShot(5000, lambda: helper.setText(default_text))

    def _on_check_complete_failed(self, reason):
        from PySide6.QtCore import QTimer
        from utils import build_info
        self._restore_check_button()
        helper = self._check_now_field.helper_widget
        if helper is not None:
            short = reason[:80]
            helper.setText(f"Couldn't reach GitHub: {short}")
            default_text = f"Current build: {build_info.version_string()}"
            QTimer.singleShot(10000, lambda: helper.setText(default_text))

    # ── Public API ────────────────────────────────────────────────────────
    def set_update_checker(self, checker):
        self._update_checker = checker
        checker.update_available.connect(self._on_check_complete_update)
        checker.no_update.connect(self._on_check_complete_no_update)
        checker.check_failed.connect(self._on_check_complete_failed)

    def highlight_keep_alive_group(self):
        # Implementation completed in Task 7 (Keep-Alive page).
        self._show_category("keep_alive")

    def get_keep_alive_delay_seconds(self) -> float:
        # Filled in Task 7 once the delay row is built.
        return 60.0

    # ── Theming ───────────────────────────────────────────────────────────
    def refresh_theme(self):
        is_dark = resolve_theme(self.settings_manager) == "dark"
        c = get_theme_colors(is_dark)
        self.setStyleSheet(f"background: {c['bg_app']}; color: {c['text_primary']};")
        # Scroll areas + scrollbars
        for child in self.findChildren(QScrollArea):
            child.setStyleSheet(
                f"QScrollArea {{ background: {c['bg_app']}; border: none; }}"
            )
            if child.widget():
                child.widget().setStyleSheet(f"background: {c['bg_app']};")
            bar = getattr(child, "_auto_hide_scrollbar", None)
            if bar is not None:
                bar.set_theme(is_dark)
        # Sidebar
        self.sidebar.apply_theme(c, is_dark)
        # Page headers (title + subtitle for every page)
        for page in self.pages.values():
            page._title_label.setStyleSheet(
                f"font-size: 18px; font-weight: 700; color: {c['text_primary']}; "
                "background: transparent;"
            )
            page._sub_label.setStyleSheet(
                f"font-size: 12px; color: {c['text_muted']}; "
                "background: transparent; margin-bottom: 6px;"
            )
        # Panels
        for panel in self._panels:
            panel.apply_theme(c, is_dark)
        # Switches
        for s in self.findChildren(Switch):
            s.set_theme_colors(
                track_on=c["accent_blue_btn"],
                track_off=c["border_input"] if is_dark else "#d1d1d6",
                thumb="#ffffff",
            )

