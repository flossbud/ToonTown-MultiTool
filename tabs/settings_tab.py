from __future__ import annotations

import os
import sys
from pathlib import Path

import psutil
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QApplication, QMessageBox, QFrame,
    QPushButton, QScrollArea, QFileDialog,
    QStackedWidget
)
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from utils.theme_manager import apply_theme, get_theme_colors, resolve_theme
from utils.shared_widgets import Switch
from utils.widgets import install_modern_scrollbar
from services.ttr_login_service import find_engine_path, get_engine_executable_name
from services.cc_login_service import (
    find_cc_engine_path,
    get_cc_engine_executable_name,
    discover_cc_installs,
)
from services.wine_runtimes import install_signature
from utils.settings_keys import CC_ENGINE_INSTALL_SIGNATURE, SETTINGS_ACTIVE_CATEGORY


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
        self._check_now_field = None
        self._check_now_btn = None

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
        from utils.settings_keys import (
            CC_ENGINE_INSTALL_SIGNATURE,
            CC_HIDE_LAUNCH_CONSOLE,
            CC_EXTERNAL_LOG_DIR,
        )
        page._title_label.setText("Games")
        page._sub_label.setText("Locations and runtime settings for each game.")

        lay = page._panel_layout
        insert_at = lay.count() - 1

        # ── TTR ──────────────────────────────────────────────────────────
        ttr_logo = self._asset_path("ttr.png")
        ttr_panel = SettingsPanel(
            title="Toontown Rewritten", stripe="ttr",
            sub=" ", logo_path=ttr_logo,
        )
        self._panels.append(ttr_panel)
        self._ttr_panel = ttr_panel

        # Header buttons: Browse + Auto-detect (path-row pattern).
        ttr_browse = QPushButton("Browse")
        ttr_browse.setCursor(Qt.PointingHandCursor)
        ttr_browse.setFixedHeight(28)
        ttr_browse.clicked.connect(lambda: self._game_path_browse("ttr"))
        ttr_panel.add_header_button(ttr_browse)

        ttr_detect = QPushButton("Auto-detect")
        ttr_detect.setCursor(Qt.PointingHandCursor)
        ttr_detect.setFixedHeight(28)
        ttr_detect.clicked.connect(lambda: self._game_path_auto_detect("ttr"))
        ttr_panel.add_header_button(ttr_detect)

        # Companion app body row.
        comp_field = SettingsField(
            "TTR Companion App",
            helper="Show toon names and portraits (TTR only).",
        )
        comp_switch = Switch(self.settings_manager.get("enable_companion_app", True))
        comp_switch.toggled.connect(
            lambda v: self.settings_manager.set("enable_companion_app", v)
        )
        comp_field.set_control(comp_switch)
        ttr_panel.add_field(comp_field)

        lay.insertWidget(insert_at, ttr_panel)
        insert_at += 1

        # Resolve TTR path on first display.
        current_ttr = self.settings_manager.get("ttr_engine_dir", "")
        if not current_ttr:
            self._game_path_auto_detect("ttr", silent=True)
        else:
            self._refresh_game_path_display("ttr", current_ttr)

        # ── CC ───────────────────────────────────────────────────────────
        cc_logo = self._asset_path("cc.png")
        cc_panel = SettingsPanel(
            title="Corporate Clash", stripe="cc",
            sub=" ", logo_path=cc_logo,
        )
        self._panels.append(cc_panel)
        self._cc_panel = cc_panel

        cc_browse = QPushButton("Browse")
        cc_browse.setCursor(Qt.PointingHandCursor)
        cc_browse.setFixedHeight(28)
        cc_browse.clicked.connect(lambda: self._game_path_browse("cc"))
        cc_panel.add_header_button(cc_browse)

        cc_detect = QPushButton("Auto-detect")
        cc_detect.setCursor(Qt.PointingHandCursor)
        cc_detect.setFixedHeight(28)
        cc_detect.clicked.connect(lambda: self._game_path_auto_detect("cc"))
        cc_panel.add_header_button(cc_detect)

        # Compatibility runtime body row.
        compat_field = SettingsField(
            "Compatibility runtime", helper=" ",
        )
        compat_change_btn = QPushButton("Change…")
        compat_change_btn.setCursor(Qt.PointingHandCursor)
        compat_change_btn.setFixedHeight(28)
        compat_change_btn.clicked.connect(self._on_compat_change_clicked)
        compat_field.set_control(compat_change_btn)
        self._compat_field = compat_field
        self._compat_change_btn = compat_change_btn
        if sys.platform != "win32":
            cc_panel.add_field(compat_field)
            self._refresh_compat_runtime_row()
            self.settings_manager.on_change(self._on_setting_changed_compat)

        # Hide CC launch console
        hide_field = SettingsField(
            "Hide CC launch console",
            helper="Turn off to see TTCCLauncher stdout when debugging.",
        )
        hide_switch = Switch(self.settings_manager.get(CC_HIDE_LAUNCH_CONSOLE, True))
        hide_switch.toggled.connect(
            lambda v: self.settings_manager.set(CC_HIDE_LAUNCH_CONSOLE, v)
        )
        hide_field.set_control(hide_switch)
        cc_panel.add_field(hide_field)

        # External CC log directory (advanced)
        ext_field = SettingsField(
            "External CC log directory (advanced)",
            helper="Leave blank for auto-detection.",
        )
        self._ext_log_field = ext_field
        # Seed the helper with the current value so users see where logs come from.
        self._set_ext_log_helper_with_path(
            self.settings_manager.get(CC_EXTERNAL_LOG_DIR, "") or ""
        )
        ext_browse = QPushButton("Browse")
        ext_browse.setFixedHeight(28)
        ext_browse.setCursor(Qt.PointingHandCursor)
        ext_browse.clicked.connect(self._on_ext_log_browse)
        ext_clear = QPushButton("Clear")
        ext_clear.setFixedHeight(28)
        ext_clear.setCursor(Qt.PointingHandCursor)
        ext_clear.clicked.connect(self._on_ext_log_clear)
        ext_detect = QPushButton("Detect")
        ext_detect.setFixedHeight(28)
        ext_detect.setCursor(Qt.PointingHandCursor)
        ext_detect.setToolTip(
            "Walk currently-running CC processes and report what discovery finds."
        )
        ext_detect.clicked.connect(self._on_ext_log_detect)
        ext_field.add_control(ext_browse)
        ext_field.add_control(ext_clear)
        ext_field.add_control(ext_detect)
        cc_panel.add_field(ext_field)

        lay.insertWidget(insert_at, cc_panel)

        # Resolve CC path on first display BEFORE populating _cc_installs.
        # Order matters: _game_path_auto_detect opens the install picker when
        # len(_cc_installs) > 1; running the first resolution with the attr
        # unset short-circuits that branch on construction so the dialog only
        # opens when the user actually clicks Auto-detect. See commit 2358572.
        current_cc = self.settings_manager.get("cc_engine_dir", "")
        if not current_cc:
            self._game_path_auto_detect("cc", silent=True)
        # Now populate the install set so the chip suffix + needs-pick state
        # are available for subsequent interactions.
        self._cc_installs: list = []
        from services.cc_login_service import discover_cc_installs
        try:
            self._cc_installs = discover_cc_installs()
        except Exception:
            self._cc_installs = []
        stored_sig = self.settings_manager.get(CC_ENGINE_INSTALL_SIGNATURE, "")
        from services.wine_runtimes import install_signature
        sig_match = (
            any(install_signature(i) == stored_sig for i in self._cc_installs)
            if stored_sig else False
        )
        self._cc_needs_pick = bool(
            len(self._cc_installs) > 1 and not sig_match
        )
        # Re-render now that _cc_installs reflects the resolved set so the
        # active-install chip suffix can be appended to the subtitle.
        if current_cc:
            self._refresh_game_path_display("cc", current_cc)

    # ── Game path helpers ─────────────────────────────────────────────────

    def _asset_path(self, name: str) -> str:
        """Resolve a bundled asset relative to repo root / PyInstaller _MEIPASS."""
        base = getattr(
            sys, "_MEIPASS",
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        return os.path.join(base, "assets", name)

    def _exe_name(self, game: str) -> str:
        if game == "ttr":
            return get_engine_executable_name()
        return get_cc_engine_executable_name()

    def _find_path(self, game: str):
        if game == "ttr":
            return find_engine_path()
        return find_cc_engine_path()

    def _settings_key_for(self, game: str) -> str:
        return "ttr_engine_dir" if game == "ttr" else "cc_engine_dir"

    def _approval_key_for(self, game: str) -> str:
        return f"{self._settings_key_for(game)}_approved_custom_dir"

    def _panel_for(self, game: str) -> SettingsPanel:
        return self._ttr_panel if game == "ttr" else self._cc_panel

    def _refresh_game_path_display(self, game: str, path: str, error: bool = False):
        from utils.settings_keys import CC_ENGINE_INSTALL_SIGNATURE
        from services.wine_runtimes import install_signature
        panel = self._panel_for(game)
        if not path:
            panel.set_sub("Not found. Click Browse or Auto-detect.", color_override="#E05252")
            return
        if error:
            panel.set_sub(path, color_override="#E05252")
            return
        home = os.path.expanduser("~")
        display = path.replace(home, "~") if path.startswith(home) else path
        subtitle = display
        has_chip = False
        if game == "cc":
            stored_sig = self.settings_manager.get(CC_ENGINE_INSTALL_SIGNATURE, "")
            for inst in getattr(self, "_cc_installs", []):
                if install_signature(inst) == stored_sig:
                    from utils.widgets.picker_card import PickerChip
                    chip_html = PickerChip.inline_html(inst.launcher)
                    subtitle = f"{display}  ·  {chip_html} {inst.display_name}"
                    has_chip = True
                    break
        panel.set_sub(subtitle, color_override="#56c856", rich_text=has_chip)

    def _game_path_browse(self, game: str):
        exe_name = self._exe_name(game)
        dir_path = QFileDialog.getExistingDirectory(
            self, f"Select {exe_name} Folder",
            os.path.expanduser("~"),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not dir_path:
            return
        engine = os.path.join(dir_path, exe_name)
        if os.path.isfile(engine):
            self.settings_manager.set(self._settings_key_for(game), dir_path)
            self.settings_manager.set(self._approval_key_for(game), os.path.realpath(dir_path))
            self._refresh_game_path_display(game, dir_path)
        else:
            self._refresh_game_path_display(
                game, f"{exe_name} not found in that folder. Try Auto-detect.", error=True,
            )

    def _game_path_auto_detect(self, game: str, silent: bool = False):
        from utils.settings_keys import CC_ENGINE_INSTALL_SIGNATURE
        from services.wine_runtimes import install_signature
        if game == "cc":
            cc_installs = getattr(self, "_cc_installs", None) or []
            if len(cc_installs) > 1:
                self._open_cc_install_picker(cc_installs)
                return
        path = self._find_path(game)
        if path:
            self.settings_manager.set(self._settings_key_for(game), path)
            self.settings_manager.set(self._approval_key_for(game), "")
            if game == "cc":
                cc_installs = getattr(self, "_cc_installs", None) or []
                if len(cc_installs) == 1:
                    self.settings_manager.set(
                        CC_ENGINE_INSTALL_SIGNATURE,
                        install_signature(cc_installs[0]),
                    )
            self._refresh_game_path_display(game, path)
        elif not silent:
            self._refresh_game_path_display(
                game, "Could not auto-detect. Click Browse.", error=True,
            )

    def _open_cc_install_picker(self, installs):
        from utils.settings_keys import CC_ENGINE_INSTALL_SIGNATURE
        from services.wine_runtimes import install_signature
        from utils.widgets.cc_install_picker import CCInstallPickerDialog
        stored = self.settings_manager.get(CC_ENGINE_INSTALL_SIGNATURE, "")
        dlg = CCInstallPickerDialog(
            installs, parent=self.window(), active_signature=stored or None,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        picked = dlg.selected_install()
        if picked is None:
            return
        path = os.path.dirname(picked.exe_path)
        self.settings_manager.set("cc_engine_dir", path)
        self.settings_manager.set("cc_engine_dir_approved_custom_dir", "")
        self.settings_manager.set(CC_ENGINE_INSTALL_SIGNATURE, install_signature(picked))
        try:
            from services.cc_login_service import discover_cc_installs
            self._cc_installs = discover_cc_installs()
        except Exception:
            pass
        self._cc_needs_pick = False
        self._refresh_game_path_display("cc", path)

    # ── Compat runtime helpers ────────────────────────────────────────────

    def _get_active_cc_install(self):
        from services.cc_login_service import get_cc_engine_executable_name
        from services.wine_runtimes import WineInstall, classify_path
        engine_dir = self.settings_manager.get("cc_engine_dir", "")
        if not engine_dir:
            return None
        exe = os.path.join(engine_dir, get_cc_engine_executable_name())
        if not os.path.isfile(exe):
            return None
        try:
            classified = classify_path(exe)
        except Exception:
            return None
        if classified is not None:
            return classified
        return WineInstall(
            exe_path=exe, launcher="native", prefix_path=None,
            display_name="Corporate Clash", metadata={},
        )

    def _refresh_compat_runtime_row(self):
        if not hasattr(self, "_compat_field"):
            return
        install = self._get_active_cc_install()
        if install is None:
            self._compat_field.hide()
            return
        self._compat_field.show()
        if install.launcher != "steam-proton":
            self._compat_field.helper_widget.setText(self._compat_readonly_label(install))
            self._compat_change_btn.hide()
            return
        self._compat_change_btn.show()
        from services.cc_launcher import resolve_effective_proton
        chosen = resolve_effective_proton(install, self.settings_manager)
        if chosen is None:
            self._compat_field.helper_widget.setText("No Steam Proton found")
            self._compat_change_btn.setEnabled(False)
            return
        self._compat_change_btn.setEnabled(True)
        nickname = self._compat_nickname_for(chosen)
        override = self.settings_manager.get("cc_steam_proton_override", "")
        suffix = "custom" if override else "default"
        self._compat_field.helper_widget.setText(f"{nickname} · {suffix}")

    @staticmethod
    def _compat_readonly_label(install):
        if install.launcher == "bottles":
            runner = (install.metadata.get("bottle_display_name")
                      or install.metadata.get("bottle_name") or "(unknown)")
            return f"Bottles · {runner}"
        if install.launcher == "lutris":
            name = (install.metadata.get("lutris_name")
                    or install.metadata.get("lutris_slug") or "(unknown)")
            return f"Lutris · {name}"
        if install.launcher == "wine":
            return "Wine · system wine"
        if install.launcher == "native":
            return "Native (no compatibility layer)"
        return install.launcher

    @staticmethod
    def _compat_nickname_for(proton_dir: str) -> str:
        from services.steam_proton_tools import enumerate_proton_tools
        for tool in enumerate_proton_tools():
            if tool.proton_dir == proton_dir:
                return tool.nickname
        return os.path.basename(proton_dir.rstrip(os.sep))

    def _on_setting_changed_compat(self, key, _value):
        if key in ("cc_steam_proton_override", "cc_engine_dir"):
            self._refresh_compat_runtime_row()

    def _on_compat_change_clicked(self):
        from services.steam_proton_tools import enumerate_proton_tools
        from utils.widgets.cc_compat_picker import CCCompatPickerDialog
        install = self._get_active_cc_install()
        if install is None or install.launcher != "steam-proton":
            return
        tools = enumerate_proton_tools()
        override = self.settings_manager.get("cc_steam_proton_override", "")
        from services.cc_launcher import resolve_effective_proton
        resolved = resolve_effective_proton(install, self.settings_manager) or ""
        default_display = (
            self._compat_nickname_for(resolved) if resolved else "(none installed)"
        )
        dlg = CCCompatPickerDialog(
            tools=tools, current_override=override,
            steam_default_display=default_display, parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        chosen = dlg.chosen_override()
        if chosen is None:
            return
        self.settings_manager.set("cc_steam_proton_override", chosen)
        self._refresh_compat_runtime_row()

    # ── External CC log dir handlers ──────────────────────────────────────

    def _set_ext_log_helper_with_path(self, path: str):
        """Update the external-log-dir field's helper with the current path."""
        if (
            not hasattr(self, "_ext_log_field")
            or self._ext_log_field.helper_widget is None
        ):
            return
        display = path or "(auto)"
        self._ext_log_field.helper_widget.setText(
            f"Leave blank for auto-detection. Current: {display}"
        )

    def _on_ext_log_browse(self):
        from utils.settings_keys import CC_EXTERNAL_LOG_DIR
        current = self.settings_manager.get(CC_EXTERNAL_LOG_DIR, "") or ""
        picked = QFileDialog.getExistingDirectory(
            self, "Select Corporate Clash logs directory", current,
        )
        if picked:
            self.settings_manager.set(CC_EXTERNAL_LOG_DIR, picked)
            self._set_ext_log_helper_with_path(picked)

    def _on_ext_log_clear(self):
        from utils.settings_keys import CC_EXTERNAL_LOG_DIR
        self.settings_manager.set(CC_EXTERNAL_LOG_DIR, "")
        self._set_ext_log_helper_with_path("")

    def _on_ext_log_detect(self):
        from pathlib import Path
        from utils import cc_log_discovery
        from utils.settings_keys import CC_EXTERNAL_LOG_DIR
        manual_raw = self.settings_manager.get(CC_EXTERNAL_LOG_DIR, "") or ""
        manual_dir = Path(manual_raw.strip()) if manual_raw.strip() else None
        results: list[str] = []
        for proc in psutil.process_iter(attrs=["pid", "name"]):
            name = (proc.info.get("name") or "").lower()
            if "corporateclash" not in name:
                continue
            pid = proc.info["pid"]
            try:
                path = cc_log_discovery.find_log_for_pid(pid, manual_dir=manual_dir)
            except Exception as exc:
                results.append(f"pid {pid}: error {exc!r}")
                continue
            results.append(
                f"pid {pid}: {'(found) ' + str(path) if path else '(not found)'}"
            )
        if not results:
            results.append("No running CC processes detected.")
        QMessageBox.information(
            self, "External CC log discovery", "\n".join(results),
        )

    def _build_keep_alive_page(self, page):
        page._title_label.setText("Keep-Alive")
        page._sub_label.setText(
            "Periodically send a keystroke to keep toons logged in. "
            "See the warning before enabling."
        )

        lay = page._panel_layout
        insert_at = lay.count() - 1

        panel = SettingsPanel(title="Keep-Alive")
        self._panels.append(panel)
        self._keep_alive_panel = panel

        # Master toggle
        master_initial = bool(self.settings_manager.get("keep_alive_enabled", False))
        master_field = SettingsField(
            "Enable Keep-Alive",
            helper=(
                "Disabled by default. Both games' Terms of Service prohibit "
                "automation tools. Your previous per-toon Keep-Alive selections "
                "are preserved."
            ),
        )
        master_switch = Switch(master_initial)
        master_switch.toggled.connect(self._on_keep_alive_master_toggle)
        master_field.set_control(master_switch)
        self._ka_master_switch = master_switch
        panel.add_field(master_field)

        # Action
        self._ka_actions = [
            ("Jump", "jump"),
            ("Open / Close Book", "book"),
            ("Move Forward", "up"),
        ]
        saved_action = self.settings_manager.get("keep_alive_action", "jump")
        action_idx = next(
            (i for i, (_, v) in enumerate(self._ka_actions) if v == saved_action), 0,
        )
        action_field = SettingsField("Action")
        action_combo = QComboBox()
        action_combo.addItems([d for d, _ in self._ka_actions])
        action_combo.setCurrentIndex(action_idx)
        action_combo.setFixedWidth(180)
        action_combo.currentIndexChanged.connect(self._on_keep_alive_action_changed)
        action_field.set_control(action_combo)
        self._ka_action_field = action_field
        panel.add_field(action_field)

        # Interval
        delay_options = [
            "Rapid Fire", "1 sec", "5 sec", "10 sec", "30 sec",
            "1 min", "3 min", "5 min", "10 min",
        ]
        saved_delay = self.settings_manager.get("keep_alive_delay", "30 sec")
        delay_idx = delay_options.index(saved_delay) if saved_delay in delay_options else 4
        delay_field = SettingsField("Interval")
        delay_combo = QComboBox()
        delay_combo.addItems(delay_options)
        delay_combo.setCurrentIndex(delay_idx)
        delay_combo.setFixedWidth(180)
        delay_combo.currentIndexChanged.connect(self._on_keep_alive_delay_changed)
        delay_field.set_control(delay_combo)
        self._ka_delay_field = delay_field
        self._ka_delay_combo = delay_combo
        panel.add_field(delay_field)

        self._refresh_keep_alive_enabled_state(master_initial)

        lay.insertWidget(insert_at, panel)

    # ── Keep-Alive handlers ───────────────────────────────────────────────

    def _refresh_keep_alive_enabled_state(self, enabled: bool):
        self._ka_action_field.control_widget.setEnabled(enabled)
        self._ka_delay_field.control_widget.setEnabled(enabled)

    def _on_keep_alive_master_toggle(self, checked: bool):
        if not checked:
            self.settings_manager.set("keep_alive_enabled", False)
            self._refresh_keep_alive_enabled_state(False)
            return
        if self.settings_manager.get("keep_alive_consent_acknowledged", False):
            self.settings_manager.set("keep_alive_enabled", True)
            self._refresh_keep_alive_enabled_state(True)
            return
        if self._show_keep_alive_warning_dialog():
            self.settings_manager.set("keep_alive_enabled", True)
            self._refresh_keep_alive_enabled_state(True)
        else:
            # Revert visual without re-firing toggled.
            sw = self._ka_master_switch
            sw.blockSignals(True)
            sw.setChecked(False)
            sw.blockSignals(False)

    def _show_keep_alive_warning_dialog(self) -> bool:
        """Returns True if the user clicked Enable, False otherwise. Factored
        so tests can monkeypatch."""
        box = QMessageBox(self.window())
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Enable Keep-Alive?")
        box.setText(
            "Keep-Alive sends periodic input to your toon windows even while "
            "you are not actively playing.\n\n"
            "Both Toontown Rewritten and Corporate Clash prohibit automation "
            "tools of this kind in their Terms of Service. Use of Keep-Alive, "
            "particularly in public areas of either game, may result in "
            "warnings, account suspension, or permanent termination at the "
            "discretion of those games' moderation teams.\n\n"
            "ToonTown MultiTool is provided as-is and accepts no responsibility "
            "for any consequences arising from its use."
        )
        enable_btn = box.addButton("Enable", QMessageBox.DestructiveRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.setEscapeButton(cancel_btn)
        box.exec()
        return box.clickedButton() is enable_btn

    def _on_keep_alive_action_changed(self, i: int):
        if i < len(self._ka_actions):
            _, value = self._ka_actions[i]
            self.settings_manager.set("keep_alive_action", value)

    def _on_keep_alive_delay_changed(self, i: int):
        delay = self._ka_delay_combo.itemText(i)
        self.settings_manager.set("keep_alive_delay", delay)

    def _build_advanced_page(self, page):
        page._title_label.setText("Advanced")
        page._sub_label.setText(
            "Lower-level controls. Most users should not need to change these."
        )

        lay = page._panel_layout
        insert_at = lay.count() - 1

        # ── Diagnostics & input ──────────────────────────────────────────
        diag = SettingsPanel(title="Diagnostics & input")
        self._panels.append(diag)

        log_field = SettingsField("Enable Logging")
        log_switch = Switch(self.settings_manager.get("show_debug_tab", False))
        log_switch.toggled.connect(self._on_logging_toggled)
        log_field.set_control(log_switch)
        diag.add_field(log_field)

        # Input backend
        if sys.platform == "win32":
            backend_options = ["Windows API (recommended)"]
            self.settings_manager.set("input_backend", "win32")
            backend_idx = 0
            backend_helper = "Native Windows Input"
        else:
            backend_options = ["Xlib (recommended)", "xdotool"]
            current_backend = self.settings_manager.get("input_backend", "xlib")
            if current_backend not in ("xlib", "xdotool"):
                current_backend = "xlib"
                self.settings_manager.set("input_backend", "xlib")
            backend_idx = 0 if current_backend == "xlib" else 1
            backend_helper = "Restart required on change."
        backend_field = SettingsField("Input Backend", helper=backend_helper)
        backend_combo = QComboBox()
        backend_combo.addItems(backend_options)
        backend_combo.setCurrentIndex(backend_idx)
        backend_combo.setFixedWidth(220)
        backend_combo.currentIndexChanged.connect(self._on_input_backend_changed)
        backend_field.set_control(backend_combo)
        self._backend_combo = backend_combo
        diag.add_field(backend_field)

        lay.insertWidget(insert_at, diag)
        insert_at += 1

        # ── Maintenance ──────────────────────────────────────────────────
        maint = SettingsPanel(title="Maintenance")
        self._panels.append(maint)

        clr_field = SettingsField(
            "Clear Stored Credentials",
            helper="Delete all saved TTR and CC passwords from Keyring and session memory.",
        )
        clr_btn = QPushButton("Clear")
        clr_btn.setCursor(Qt.PointingHandCursor)
        clr_btn.setFixedHeight(28)
        clr_btn.clicked.connect(self._on_clear_credentials_clicked)
        # Destructive styling — red outline.
        clr_btn.setStyleSheet("""
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
        clr_field.set_control(clr_btn)
        maint.add_field(clr_field)

        lay.insertWidget(insert_at, maint)

    # ── Advanced handlers ─────────────────────────────────────────────────

    def _on_logging_toggled(self, val: bool):
        self.settings_manager.set("show_debug_tab", val)
        self.debug_visibility_changed.emit(val)

    def _on_input_backend_changed(self, idx: int):
        if sys.platform == "win32":
            self.settings_manager.set("input_backend", "win32")
            self.input_backend_changed.emit()
            return
        backend = "xlib" if idx == 0 else "xdotool"
        if backend == "xdotool" and self._is_gnome_wayland():
            dlg = QMessageBox(self)
            dlg.setWindowTitle("Warning: xdotool on GNOME Wayland")
            dlg.setIcon(QMessageBox.Warning)
            dlg.setText(
                "xdotool on GNOME Wayland will trigger repeated Remote Desktop "
                "authorization prompts and will likely break input sending.\n\n"
                "Xlib is strongly recommended for GNOME Wayland.\n\n"
                "This will restart the service.\n\nSwitch to xdotool anyway?"
            )
            dlg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            dlg.setDefaultButton(QMessageBox.Cancel)
            if dlg.exec() != QMessageBox.Ok:
                self._backend_combo.blockSignals(True)
                self._backend_combo.setCurrentIndex(0)
                self._backend_combo.blockSignals(False)
                return
        self.settings_manager.set("input_backend", backend)
        self.input_backend_changed.emit()

    def _is_gnome_wayland(self) -> bool:
        return (
            os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            and "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        )

    def _on_clear_credentials_clicked(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Clear Stored Credentials")
        dlg.setIcon(QMessageBox.Warning)
        dlg.setText(
            "Are you sure you want to clear all stored TTR and Corporate Clash "
            "account credentials? This will delete them from your system keyring permanently."
        )
        dlg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        dlg.setDefaultButton(QMessageBox.Cancel)
        if dlg.exec() == QMessageBox.Yes:
            self.clear_credentials_requested.emit()

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
        if self._update_checker is None or self._check_now_btn is None:
            return
        self._check_now_btn.setEnabled(False)
        self._check_now_btn.setText("Checking...")
        self._update_checker.check_async(manual=True)

    def _restore_check_button(self):
        if self._check_now_btn is None:
            return
        self._check_now_btn.setEnabled(True)
        self._check_now_btn.setText("Check now")

    def _on_check_complete_update(self, info):
        self._restore_check_button()

    def _on_check_complete_no_update(self):
        from PySide6.QtCore import QTimer
        from utils import build_info
        self._restore_check_button()
        if self._check_now_field is None:
            return
        helper = self._check_now_field.helper_widget
        if helper is not None:
            helper.setText("You're on the latest version.")
            default_text = f"Current build: {build_info.version_string()}"
            QTimer.singleShot(5000, lambda: helper.setText(default_text))

    def _on_check_complete_failed(self, reason):
        from PySide6.QtCore import QTimer
        from utils import build_info
        self._restore_check_button()
        if self._check_now_field is None:
            return
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
        """Switch to the Keep-Alive page and run a one-shot accent pulse on
        its panel widget. Called by Launch-tab's per-slot help affordance."""
        from PySide6.QtCore import QEasingCurve, QPropertyAnimation
        from PySide6.QtWidgets import QGraphicsColorizeEffect
        from PySide6.QtGui import QColor
        self._show_category("keep_alive")
        self.settings_manager.set(SETTINGS_ACTIVE_CATEGORY, "keep_alive")
        panel = getattr(self, "_keep_alive_panel", None)
        if panel is None:
            return
        prior = getattr(self, "_keepalive_highlight_anim", None)
        if prior is not None:
            try:
                prior.stop()
            except RuntimeError:
                pass
        from utils.theme_manager import get_theme_colors, is_dark_palette
        c = get_theme_colors(is_dark_palette())
        accent = QColor(c.get("accent_blue_btn", "#0077ff"))
        effect = QGraphicsColorizeEffect(panel)
        effect.setColor(accent)
        effect.setStrength(0.0)
        panel.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"strength", panel)
        anim.setDuration(600)
        anim.setStartValue(0.30)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: panel.setGraphicsEffect(None))
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._keepalive_highlight_anim = anim

    def get_keep_alive_delay_seconds(self) -> float:
        if not hasattr(self, "_ka_delay_combo"):
            return 60.0
        return {
            "Rapid Fire": 0.25, "1 sec": 1, "5 sec": 5, "10 sec": 10,
            "30 sec": 30, "1 min": 60, "3 min": 180, "5 min": 300,
            "10 min": 600,
        }.get(self._ka_delay_combo.currentText(), 60.0)

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

