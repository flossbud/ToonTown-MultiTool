from __future__ import annotations

import os
import sys
from pathlib import Path

import psutil
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QApplication, QMessageBox, QFrame,
    QScrollArea, QFileDialog,
    QStackedWidget
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from utils.asset_paths import asset_path
from utils.icon_factory import (
    make_download_icon, make_sliders_icon,
)
from utils.theme_manager import (
    V2_ACCENTS, apply_theme, get_theme_colors, resolve_theme,
)
from utils.shared_widgets import Switch
from utils.widgets import install_modern_scrollbar
from utils.widgets.card_surface import CardSurface
from utils.widgets.inset_row import InsetRow
from utils.widgets.pill_controls import (
    DropdownPill, GhostExpander, PillButton, SegmentedPill,
)
from utils.widgets.portrait_badge import _qcolor_from_rgba
from services.ttr_login_service import (
    engine_binary_path,
    find_engine_path,
    get_engine_executable_name,
)
from services.cc_login_service import (
    find_cc_engine_path,
    get_cc_engine_executable_name,
    discover_cc_installs,
)
from services.wine_runtimes import install_signature
from utils.widgets.settings_rows import SettingsRowsMixin
from utils.settings_keys import (
    CC_ENGINE_INSTALL_SIGNATURE, SETTINGS_ACTIVE_CATEGORY, STRICT_TTR_SEPARATION,
    CLICK_SYNC_ENABLED, GHOST_CURSORS_ENABLED, GHOST_CURSORS_CONTROL_CARDS,
    KEEP_ALIVE_ENABLED, KEEP_ALIVE_CONSENT_ACKNOWLEDGED,
)


# v2 content column: 720px card column + 2 x 24px page padding, centered by
# the scroll area's alignment. Engages whenever the content area is wider.
SETTINGS_CONTENT_MAX_W = 768

# Keysets is a master/detail editor plus a 2-up game picker, both wider than the
# card column: two 360px picker cards + gap need ~736px of content, and the set
# list + keyboard-bearing detail card want ~772px. Give that one page a wider
# envelope so the picker lays out side-by-side and the keyboard centers. Window
# minimum width is 820, so this clamps to the viewport on the narrowest window.
KEYSETS_CONTENT_MAX_W = 880

# ── Category pill rail (v2 shell, replaces Sidebar) ───────────────────────────

CATEGORY_META = {
    # key: (accent fill, bright border, icon maker name)
    # Pill identity colors, left to right: blue, red, yellow, green, purple.
    "general":  ("#0077ff", "#3399ff", "make_nav_gear"),         # blue
    "games":    ("#b34848", "#e05252", "make_nav_gamepad"),      # red
    "keysets":  ("#d4a017", "#e8c14d", "make_nav_keyboard"),     # yellow
    "features": ("#3da343", "#56d66a", "make_radio_waves_icon"), # green
    "advanced": ("#8B4FD6", "#a97ce6", "make_wrench_icon"),      # purple
}


class _CategoryPill(QWidget):
    """One identity pill: 15px line icon + 13px label. Active = identity fill
    + bright 1px border + painted glow; idle = translucent neutral."""

    clicked = Signal(str)
    H = 36
    PAD_X = 16
    GLOW = 6              # painted halo budget per side

    def __init__(self, key: str, label: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.label = label
        self.fill, self.border, icon_name = CATEGORY_META[key]
        self._active = False
        self._hovered = False
        self._is_dark = True
        import utils.icon_factory as icon_factory
        self._icon_maker = getattr(icon_factory, icon_name)
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        from PySide6.QtGui import QFont, QFontMetrics
        f = QFont()
        f.setPixelSize(13)
        f.setWeight(QFont.Bold)
        w = (2 * self.PAD_X + 15 + 8 + QFontMetrics(f).horizontalAdvance(label)
             + 2 * self.GLOW)
        self.setFixedSize(w, self.H + 2 * self.GLOW)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self.update()

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def _activate(self) -> None:
        self.clicked.emit(self.key)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._activate()
            e.accept()
            return
        super().mousePressEvent(e)

    def paintEvent(self, e):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QFont
        from utils.theme_manager import get_v2_tokens
        from utils.widgets.portrait_badge import _qcolor_from_rgba
        t = get_v2_tokens(self._is_dark)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(self.GLOW, self.GLOW, -self.GLOW, -self.GLOW)
        radius = r.height() / 2

        if self._active:
            glow = QColor(self.border)
            for w, a in ((10, 0.06), (6, 0.12), (3, 0.20)):
                glow.setAlphaF(a)
                p.setPen(QPen(glow, w))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r, radius, radius)
            p.setPen(QPen(QColor(self.border), 1))
            p.setBrush(QColor(self.fill))
            text_col = QColor("#ffffff")
        else:
            bg = _qcolor_from_rgba(
                t["nav_hover"] if self._hovered else t["nav_idle_bg"])
            p.setPen(QPen(_qcolor_from_rgba(t["nav_idle_border"]), 1))
            p.setBrush(bg)
            text_col = QColor(t["nav_idle_text"])
        p.drawRoundedRect(r, radius, radius)

        icon = self._icon_maker(15, text_col)
        p.drawPixmap(int(r.x() + self.PAD_X), int(r.center().y() - 7.5),
                     icon.pixmap(15, 15))
        f = QFont()
        f.setPixelSize(13)
        f.setWeight(QFont.Bold if self._active else QFont.Medium)
        p.setFont(f)
        p.setPen(text_col)
        p.drawText(r.adjusted(self.PAD_X + 15 + 8, 0, -self.PAD_X, 0),
                   Qt.AlignVCenter | Qt.AlignLeft, self.label)
        p.end()


class CategoryPillRail(QFrame):
    """Centered horizontal identity-pill row. Same signal contract as the
    old Sidebar (category_selected on user click)."""

    category_selected = Signal(str)
    category_reselected = Signal(str)   # active pill re-clicked (no category change)

    def __init__(self, categories: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("settings_pill_rail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.pills: list[_CategoryPill] = []
        self.active_key = categories[0][0] if categories else ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 10, 24, 0)     # pill GLOW pads the rest
        lay.setSpacing(0)
        lay.addStretch(1)
        for key, label in categories:
            pill = _CategoryPill(key, label, self)
            pill.clicked.connect(self._on_pill_clicked)
            self.pills.append(pill)
            lay.addWidget(pill)
        lay.addStretch(1)
        if self.pills:
            self.pills[0].set_active(True)

    def set_active_category(self, key: str) -> None:
        keys = [p.key for p in self.pills]
        if key not in keys:
            key = "general"
            if key not in keys:
                return
        self.active_key = key
        for p in self.pills:
            p.set_active(p.key == key)

    def _on_pill_clicked(self, key: str) -> None:
        if key == self.active_key:
            # Re-clicking the active pill does not switch category, but the host
            # may still want to act on it (e.g. Keysets -> back to the picker).
            self.category_reselected.emit(key)
            return
        self.set_active_category(key)
        self.category_selected.emit(key)

    def apply_theme(self, c, is_dark: bool) -> None:
        self.setStyleSheet(
            "QFrame#settings_pill_rail { background: transparent; border: none; }")
        for p in self.pills:
            p.apply_theme(is_dark)


# ── Main Settings Tab ──────────────────────────────────────────────────────────

class SettingsTab(SettingsRowsMixin, QWidget):
    # ── Public signals (unchanged contract) ───────────────────────────────
    debug_visibility_changed = Signal(bool)
    theme_changed = Signal()
    input_backend_changed = Signal()
    clear_credentials_requested = Signal()
    chat_handling_mode_changed = Signal(str)

    CATEGORIES = [
        ("general", "General"),
        ("games", "Games"),
        ("keysets", "Keysets"),
        ("features", "Features"),
        ("advanced", "Advanced"),
    ]

    def __init__(self, settings_manager, keymap_manager=None, credentials_manager=None):
        super().__init__()
        self.settings_manager = settings_manager
        self.keymap_manager = keymap_manager
        self.credentials_manager = credentials_manager
        self.pages: dict[str, QWidget] = {}
        self._cards: list[CardSurface] = []          # v2 cards
        self._v2_rows: list[InsetRow] = []           # v2 inset rows
        self._v2_switches: list[tuple[Switch, str]] = []   # (switch, accent key)
        self._v2_segments: list[tuple[SegmentedPill, str]] = []
        self._v2_buttons: list[PillButton] = []
        self._v2_tile_grids: list = []        # (OptionTileGrid, accent key)
        self._current_page_key: str = "general"
        self._layout_mode: str = "compact"
        self._update_checker = None
        self._check_now_field = None
        self._check_now_btn = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.rail = CategoryPillRail(self.CATEGORIES)
        outer.addWidget(self.rail)

        self._stack = QStackedWidget(self)
        outer.addWidget(self._stack, 1)

        for key, label in self.CATEGORIES:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            install_modern_scrollbar(
                scroll,
                is_dark=resolve_theme(self.settings_manager) == "dark",
            )

            # KeysetsPage's initial gate touches self.keymap_manager
            # unconditionally, so it can't be built with None (old single-arg
            # callers, pre-Task-11 main.py wiring). Fall through to the
            # generic empty-card page below instead of crashing.
            if key == "keysets" and self.keymap_manager is not None:
                from utils.widgets.keysets.keysets_page import KeysetsPage
                page = KeysetsPage(
                    self.keymap_manager, self.settings_manager, self.credentials_manager)
                page._panel_layout = page.layout()   # satisfy _animate_page_in's margin hook
            else:
                page = QWidget()
                page_lay = QVBoxLayout(page)
                page_lay.setContentsMargins(24, 12, 24, 28)
                # Card gap: cards carry an EDGE_PAD shadow margin on every side,
                # so the layout gap stays small to keep the visual rhythm tight
                # (operator call, 2026-07-06: was 16 with the old glow budget).
                page_lay.setSpacing(4)
                page_lay.setAlignment(Qt.AlignTop)

                page._panel_layout = page_lay      # type: ignore[attr-defined]
                page_lay.addStretch(1)

            page.setMaximumWidth(
                KEYSETS_CONTENT_MAX_W if key == "keysets"
                else SETTINGS_CONTENT_MAX_W)
            scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            scroll.setWidget(page)
            self.pages[key] = page
            self._stack.addWidget(scroll)

        self._build_general_page(self.pages["general"])
        self._build_games_page(self.pages["games"])
        self._build_features_page(self.pages["features"])
        self._build_advanced_page(self.pages["advanced"])

        persisted = self.settings_manager.get(SETTINGS_ACTIVE_CATEGORY, "general")
        self._show_category(persisted, animate=False)
        self.rail.category_selected.connect(self._on_category_selected)
        self.rail.category_reselected.connect(self._on_category_reselected)

        self.refresh_theme()

    # Dialogs and file pickers opened by the shared row handlers.
    def _dialog_parent(self):
        return self

    def _dialog_window(self):
        return self.window()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Accounts can be added or renamed while Settings is hidden, so the
        # launch-slot pickers repopulate on every show. Safe and cheap: the
        # rebuild is signal-blocked and preselect-preserving, and
        # get_accounts_basic never touches the keyring.
        if getattr(self, "_hotkey_accounts_provider", None) is not None:
            self._rebuild_hotkey_slot_rows()

    # ── Category routing ──────────────────────────────────────────────────
    def _on_category_selected(self, key: str):
        self._show_category(key)
        self.settings_manager.set(SETTINGS_ACTIVE_CATEGORY, key)

    def _on_category_reselected(self, key: str):
        # Re-clicking the already-active Keysets chip returns to the game
        # picker - the same action as the editor's "All games" back button.
        # (The active pill emits category_reselected, not category_selected.)
        if key == "keysets":
            page = self.pages.get("keysets")
            if hasattr(page, "show_picker_if_available"):
                page.show_picker_if_available()

    def _show_category(self, key: str, animate: bool = True):
        # Back-compat: the "Keep-Alive" sidebar category was renamed to
        # "Features" on 2026-05-26; old persisted keys rewrite on read.
        if key == "keep_alive":
            key = "features"
        keys = [k for k, _ in self.CATEGORIES]
        if key not in keys:
            key = "general"
        self._current_page_key = key
        self.rail.set_active_category(key)
        idx = keys.index(key)
        self._stack.setCurrentIndex(idx)
        if animate:
            self._animate_page_in(self.pages[key])

    def _animate_page_in(self, page) -> None:
        """200ms fade + 6px upward slide on category switch (cubic-out).
        The opacity effect attaches to the plain-QWidget page CONTAINER, not to
        any custom-paintEvent child, so the painter-conflict law is not tripped
        even for the Keysets page (whose subtree paints itself). Never attach an
        effect directly to a child that overrides paintEvent."""
        import utils.motion as motion
        if motion.is_reduced():
            return
        from PySide6.QtCore import QEasingCurve, QVariantAnimation
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.0)
        page.setGraphicsEffect(effect)
        lay = page._panel_layout
        base = lay.contentsMargins()
        anim = QVariantAnimation(page)
        anim.setDuration(200)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _tick(v):
            try:
                effect.setOpacity(v)
                lay.setContentsMargins(base.left(), base.top() + round(6 * (1 - v)),
                                       base.right(), base.bottom())
            except RuntimeError:
                # Page/effect torn down mid-animation (e.g. the tab was
                # destroyed while this switch was still running). Nothing left
                # to animate. Mirrors motion.push_slide_pages._finalize.
                pass

        def _done():
            try:
                page.setGraphicsEffect(None)
                lay.setContentsMargins(base)
            except RuntimeError:
                pass
        anim.valueChanged.connect(_tick)
        anim.finished.connect(_done)
        self._page_anim = anim          # keep a ref; restarts replace it
        anim.start()

    # ── Public API ────────────────────────────────────────────────────────
    def set_layout_mode(self, mode: str) -> None:
        """Compact<->full swap participant (contract kept for main.py). The
        v2 shell is identical in both modes - the rail centers itself and the
        content column is width-capped unconditionally."""
        if mode not in ("compact", "full"):
            return
        self._layout_mode = mode

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
        # Category pill rail
        self.rail.apply_theme(c, is_dark)
        # Keysets page (only present when mounted as a real KeysetsPage;
        # the None-manager fallback is a plain QWidget with no refresh_theme)
        keysets_page = self.pages.get("keysets")
        if hasattr(keysets_page, "refresh_theme"):
            keysets_page.refresh_theme()
        # v2 kit propagation
        self._apply_rows_theme(is_dark)
