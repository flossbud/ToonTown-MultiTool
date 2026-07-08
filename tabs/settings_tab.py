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
from utils.settings_keys import (
    CC_ENGINE_INSTALL_SIGNATURE, SETTINGS_ACTIVE_CATEGORY, STRICT_TTR_SEPARATION,
    CLICK_SYNC_ENABLED, GHOST_CURSORS_ENABLED, GHOST_CURSORS_CONTROL_CARDS,
)


# v2 content column: 720px card column + 2 x 24px page padding, centered by
# the scroll area's alignment. Engages whenever the content area is wider.
SETTINGS_CONTENT_MAX_W = 768

# ── Category pill rail (v2 shell, replaces Sidebar) ───────────────────────────

CATEGORY_META = {
    # key: (accent fill, bright border, icon maker name)
    "general":  ("#0077ff", "#3399ff", "make_nav_gear"),
    "games":    ("#3da343", "#56d66a", "make_nav_gamepad"),
    "keysets":  ("#1fb8a6", "#4dd2c3", "make_nav_keyboard"),
    "features": ("#ff9500", "#ffb04d", "make_radio_waves_icon"),
    "advanced": ("#b34848", "#e05252", "make_wrench_icon"),
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
            return
        self.set_active_category(key)
        self.category_selected.emit(key)

    def apply_theme(self, c, is_dark: bool) -> None:
        self.setStyleSheet(
            "QFrame#settings_pill_rail { background: transparent; border: none; }")
        for p in self.pills:
            p.apply_theme(is_dark)


# ── Main Settings Tab ──────────────────────────────────────────────────────────

class SettingsTab(QWidget):
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

            page.setMaximumWidth(SETTINGS_CONTENT_MAX_W)
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

        self.refresh_theme()

    # ── v2 kit factories (register for theme propagation) ────────────────
    def _v2_switch(self, checked: bool, accent_key: str) -> Switch:
        sw = Switch(checked)
        self._v2_switches.append((sw, accent_key))
        return sw

    def _v2_row(self, label: str, helper: str | None = None) -> InsetRow:
        row = InsetRow(label, helper)
        self._v2_rows.append(row)
        return row

    def _v2_button(self, text: str, tone: str = "neutral") -> PillButton:
        btn = PillButton(text, tone)
        self._v2_buttons.append(btn)
        return btn

    def _v2_segment(self, options, accent_key: str, stretch: bool = False) -> SegmentedPill:
        seg = SegmentedPill(options, stretch=stretch)
        self._v2_segments.append((seg, accent_key))
        return seg

    # ── Page builders ─────────────────────────────────────────────────────
    def _build_general_page(self, page):
        from utils import build_info
        lay = page._panel_layout
        insert_at = lay.count() - 1

        # ── Appearance & behavior ────────────────────────────────────────
        appearance = CardSurface("blue", title="Appearance & behavior",
                                 icon=make_sliders_icon(20))
        self._cards.append(appearance)

        theme_value = self.settings_manager.get("theme", "system")
        theme_idx = (["system", "light", "dark"].index(theme_value)
                     if theme_value in ("system", "light", "dark") else 0)
        theme_row = self._v2_row("Theme")
        self._theme_segment = self._v2_segment(["System", "Light", "Dark"], "blue")
        self._theme_segment.setCurrentIndex(theme_idx)
        self._theme_segment.index_changed.connect(self._on_theme_changed)
        theme_row.set_control(self._theme_segment)
        appearance.add_row(theme_row)

        import utils.motion as motion
        motion.set_settings_manager(self.settings_manager)
        explicit = self.settings_manager.get("reduce_motion_set_explicitly", False)
        rm_idx = 0 if not explicit else (
            1 if self.settings_manager.get("reduce_motion", False) else 2)
        rm_row = self._v2_row(
            "Reduce motion",
            helper=("System default follows your desktop's reduce-motion "
                    "setting. Choose On or Off to override."))
        self._rm_segment = self._v2_segment(["System", "On", "Off"], "blue")
        self._rm_segment.setCurrentIndex(rm_idx)
        self._rm_segment.index_changed.connect(self._on_reduce_motion_changed)
        rm_row.set_control(self._rm_segment)
        appearance.add_row(rm_row)

        tb_row = self._v2_row(
            "Use system title bar",
            helper="Show your OS window frame instead of the in-app controls. "
                   "Restart required to take effect.")
        tb_switch = self._v2_switch(
            bool(self.settings_manager.get("use_system_title_bar", False)), "blue")
        tb_switch.toggled.connect(
            lambda v: self.settings_manager.set("use_system_title_bar", v))
        tb_row.set_control(tb_switch)
        appearance.add_row(tb_row)

        from utils.settings_keys import START_IN_FLOAT_UI_MODE
        from utils.overlay.backend import get_overlay_backend
        try:
            float_available = bool(get_overlay_backend().is_available())
        except Exception:
            float_available = False
        float_row = self._v2_row(
            "Start in Float UI mode",
            helper="Open straight into the floating overlay instead of the "
                   "windowed UI when the app launches.")
        float_switch = self._v2_switch(
            bool(self.settings_manager.get(START_IN_FLOAT_UI_MODE, False)), "blue")
        float_switch.setObjectName("start_in_float_ui_switch")
        if float_available:
            float_switch.toggled.connect(
                lambda v: self.settings_manager.set(START_IN_FLOAT_UI_MODE, v))
        else:
            float_switch.setEnabled(False)
            float_switch.setToolTip("Float UI is not available on this system")
            float_row.setToolTip("Float UI is not available on this system")
        float_row.set_control(float_switch)
        appearance.add_row(float_row)

        lay.insertWidget(insert_at, appearance)
        insert_at += 1

        # ── Updates ──────────────────────────────────────────────────────
        updates = CardSurface("yellow", title="Updates", icon=make_download_icon(20))
        self._cards.append(updates)

        upd_row = self._v2_row(
            "Check for updates on startup",
            helper="Look for new releases when the app launches.")
        upd_switch = self._v2_switch(
            bool(self.settings_manager.get("check_for_updates_at_startup", False)),
            "yellow")
        upd_switch.toggled.connect(
            lambda v: self.settings_manager.set("check_for_updates_at_startup", v))
        upd_row.set_control(upd_switch)
        updates.add_row(upd_row)

        check_now_row = self._v2_row(
            "Check for updates now",
            helper=f"Current build: {build_info.version_string()}")
        self._check_now_btn = self._v2_button("Check now")
        self._check_now_btn.clicked.connect(self._on_check_now_clicked)
        check_now_row.set_control(self._check_now_btn)
        self._check_now_field = check_now_row      # completion handlers use .helper_widget
        updates.add_row(check_now_row)

        lay.insertWidget(insert_at, updates)

        # ── macOS permissions (darwin only) ──────────────────────────────
        if sys.platform == "darwin":
            insert_at += 1
            from utils.icon_factory import make_nav_gear
            macos = CardSurface("blue", title="macOS", icon=make_nav_gear(20, None))
            self._cards.append(macos)
            perms_row = self._v2_row(
                "Permissions",
                helper="Accessibility and Input Monitoring let the app control "
                       "your background toons. Open the setup guide to grant them.")
            perms_btn = self._v2_button("Open guide...")
            perms_btn.clicked.connect(self._open_macos_permissions)
            perms_row.set_control(perms_btn)
            macos.add_row(perms_row)
            lay.insertWidget(insert_at, macos)

    def _open_macos_permissions(self):
        import sys
        from utils import macos_permissions as _mp
        from utils.widgets.macos_permissions_dialog import MacOSPermissionsDialog
        pm = _mp.PermissionManager()
        try:
            import AppKit
            bp = AppKit.NSBundle.mainBundle().bundlePath()
        except Exception:
            bp = sys.executable
        MacOSPermissionsDialog(
            pm, location_ok=_mp.is_install_location_ok(bp), parent=self).show()

    def _build_games_page(self, page):
        from utils.settings_keys import (
            CC_ENGINE_INSTALL_SIGNATURE,
            CC_HIDE_LAUNCH_CONSOLE,
            CC_EXTERNAL_LOG_DIR,
        )
        lay = page._panel_layout
        insert_at = lay.count() - 1

        # ── TTR ──────────────────────────────────────────────────────────
        ttr_card = CardSurface("ttr", title="Toontown Rewritten", sub=" ",
                               logo_path=self._asset_path("ttr.png"))
        self._cards.append(ttr_card)
        self._ttr_panel = ttr_card

        ttr_browse = self._v2_button("Browse")
        ttr_browse.clicked.connect(lambda: self._game_path_browse("ttr"))
        ttr_card.add_header_button(ttr_browse)
        ttr_detect = self._v2_button("Auto-detect")
        ttr_detect.clicked.connect(lambda: self._game_path_auto_detect("ttr"))
        ttr_card.add_header_button(ttr_detect)

        comp_row = self._v2_row("TTR Companion App",
                                helper="Show toon names and portraits (TTR only).")
        comp_switch = self._v2_switch(
            self.settings_manager.get("enable_companion_app", True), "ttr")
        comp_switch.toggled.connect(
            lambda v: self.settings_manager.set("enable_companion_app", v))
        comp_row.set_control(comp_switch)
        ttr_card.add_row(comp_row)

        strict_row = self._v2_row(
            "Strict keyset separation (TTR)",
            helper=("Keep each toon controlled by its own assigned keys no matter "
                    "which window is in front. Turn off to control the front window "
                    "with the default keys."))
        strict_switch = self._v2_switch(
            self.settings_manager.get(STRICT_TTR_SEPARATION, True), "ttr")
        strict_switch.toggled.connect(
            lambda v: self.settings_manager.set(STRICT_TTR_SEPARATION, v))
        strict_row.set_control(strict_switch)
        ttr_card.add_row(strict_row)

        lay.insertWidget(insert_at, ttr_card)
        insert_at += 1

        current_ttr = self.settings_manager.get("ttr_engine_dir", "")
        if not current_ttr:
            self._game_path_auto_detect("ttr", silent=True)
        else:
            self._refresh_game_path_display("ttr", current_ttr)

        # ── CC ───────────────────────────────────────────────────────────
        cc_card = CardSurface("cc", title="Corporate Clash", sub=" ",
                              logo_path=self._asset_path("cc.png"))
        self._cards.append(cc_card)
        self._cc_panel = cc_card

        cc_browse = self._v2_button("Browse")
        cc_browse.clicked.connect(lambda: self._game_path_browse("cc"))
        cc_card.add_header_button(cc_browse)
        cc_detect = self._v2_button("Auto-detect")
        cc_detect.clicked.connect(lambda: self._game_path_auto_detect("cc"))
        cc_card.add_header_button(cc_detect)

        compat_row = self._v2_row("Compatibility runtime", helper=" ")
        compat_change_btn = self._v2_button("Change...")
        compat_change_btn.clicked.connect(self._on_compat_change_clicked)
        compat_row.set_control(compat_change_btn)
        self._compat_field = compat_row
        self._compat_change_btn = compat_change_btn
        if sys.platform != "win32":
            cc_card.add_row(compat_row)
            self._refresh_compat_runtime_row()
            self.settings_manager.on_change(self._on_setting_changed_compat)

        hide_row = self._v2_row(
            "Hide CC launch console",
            helper="Turn off to see TTCCLauncher stdout when debugging.")
        hide_switch = self._v2_switch(
            self.settings_manager.get(CC_HIDE_LAUNCH_CONSOLE, True), "cc")
        hide_switch.toggled.connect(
            lambda v: self.settings_manager.set(CC_HIDE_LAUNCH_CONSOLE, v))
        hide_row.set_control(hide_switch)
        cc_card.add_row(hide_row)

        ext_row = self._v2_row("External CC log directory (advanced)",
                               helper="Leave blank for auto-detection.")
        self._ext_log_field = ext_row
        self._set_ext_log_helper_with_path(
            self.settings_manager.get(CC_EXTERNAL_LOG_DIR, "") or "")
        ext_browse = self._v2_button("Browse")
        ext_browse.clicked.connect(self._on_ext_log_browse)
        ext_clear = self._v2_button("Clear")
        ext_clear.clicked.connect(self._on_ext_log_clear)
        ext_detect = self._v2_button("Detect")
        ext_detect.setToolTip(
            "Walk currently-running CC processes and report what discovery finds.")
        ext_detect.clicked.connect(self._on_ext_log_detect)
        ext_row.add_control(ext_browse)
        ext_row.add_control(ext_clear)
        ext_row.add_control(ext_detect)
        cc_card.add_row(ext_row)

        lay.insertWidget(insert_at, cc_card)

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

    def _engine_binary_in(self, game: str, dir_path: str) -> str:
        """Absolute path to the game's engine binary inside dir_path. TTR routes
        through engine_binary_path so the macOS .app nesting is honored; CC keeps
        the flat layout (no macOS CC client)."""
        if game == "ttr":
            return engine_binary_path(dir_path)
        return os.path.join(dir_path, self._exe_name(game))

    def _find_path(self, game: str):
        if game == "ttr":
            return find_engine_path()
        return find_cc_engine_path()

    def _settings_key_for(self, game: str) -> str:
        return "ttr_engine_dir" if game == "ttr" else "cc_engine_dir"

    def _approval_key_for(self, game: str) -> str:
        return f"{self._settings_key_for(game)}_approved_custom_dir"

    def _panel_for(self, game: str) -> CardSurface:
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
        is_dark = resolve_theme(self.settings_manager) == "dark"
        ok_green = "#7de392" if is_dark else "#15803d"
        panel.set_sub(subtitle, color_override=ok_green, rich_text=has_chip,
                      mono=not has_chip)

    def _game_path_browse(self, game: str):
        exe_name = self._exe_name(game)
        dir_path = QFileDialog.getExistingDirectory(
            self, f"Select {exe_name} Folder",
            os.path.expanduser("~"),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not dir_path:
            return
        engine = self._engine_binary_in(game, dir_path)
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

    def apply_picked_install(self, install) -> None:
        """Refresh the CC panel after the boot-time picker has accepted an install.

        Called by main.py when the CCInstallPickerDialog shown at startup is
        accepted. Persists the relevant settings keys (idempotent with what
        main.py already wrote), re-discovers installs so chip resolution stays
        accurate, clears the needs-pick flag, and re-renders the sub-label and
        chip via _refresh_game_path_display.
        """
        from utils.settings_keys import CC_ENGINE_INSTALL_SIGNATURE
        from services.wine_runtimes import install_signature as _sig

        path = os.path.dirname(install.exe_path)
        self.settings_manager.set("cc_engine_dir", path)
        self.settings_manager.set("cc_engine_dir_approved_custom_dir", "")
        self.settings_manager.set(CC_ENGINE_INSTALL_SIGNATURE, _sig(install))
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

    def _build_features_page(self, page):
        self._build_keep_alive_card(page)
        self._build_click_sync_card(page)
        self._build_hotkeys_card(page)
        self._build_chat_handling_card(page)

    def _build_keep_alive_card(self, page):
        from utils.icon_factory import make_lightning_icon
        lay = page._panel_layout
        insert_at = lay.count() - 1

        card = CardSurface("orange", title="Keep-Alive", icon=make_lightning_icon(20))
        self._cards.append(card)
        self._keep_alive_panel = card

        master_initial = bool(self.settings_manager.get("keep_alive_enabled", False))
        master_row = self._v2_row(
            "Enable Keep-Alive",
            helper=("Disabled by default. Both games' Terms of Service prohibit "
                    "automation tools. Your previous per-toon Keep-Alive selections "
                    "are preserved."))
        master_switch = self._v2_switch(master_initial, "orange")
        master_switch.toggled.connect(self._on_keep_alive_master_toggle)
        master_row.set_control(master_switch)
        self._ka_master_switch = master_switch
        card.add_row(master_row)

        self._ka_actions = [
            ("Jump", "jump"),
            ("Open / Close Book", "book"),
            ("Move Forward", "up"),
        ]
        saved_action = self.settings_manager.get("keep_alive_action", "jump")
        action_idx = next(
            (i for i, (_, v) in enumerate(self._ka_actions) if v == saved_action), 0)
        action_row = self._v2_row("Action")
        action_seg = self._v2_segment([d for d, _ in self._ka_actions], "orange")
        action_seg.setCurrentIndex(action_idx)
        action_seg.index_changed.connect(self._on_keep_alive_action_changed)
        action_row.set_control(action_seg)
        self._ka_action_row = action_row
        card.add_row(action_row)

        # Interval - "10 min" removed 2026-07-06 (product decision); persisted
        # values migrate to "5 min" on read.
        self._ka_delay_options = [
            "Rapid Fire", "1 sec", "5 sec", "10 sec", "30 sec",
            "1 min", "3 min", "5 min",
        ]
        saved_delay = self.settings_manager.get("keep_alive_delay", "30 sec")
        if saved_delay == "10 min":
            saved_delay = "5 min"
            self.settings_manager.set("keep_alive_delay", saved_delay)
        delay_idx = (self._ka_delay_options.index(saved_delay)
                     if saved_delay in self._ka_delay_options else 4)
        delay_row = self._v2_row("Interval")
        delay_seg = self._v2_segment(self._ka_delay_options, "orange", stretch=True)
        delay_seg.setCurrentIndex(delay_idx)
        delay_seg.index_changed.connect(self._on_keep_alive_delay_changed)
        delay_row.set_full_width_control(delay_seg)
        self._ka_delay_row = delay_row
        self._ka_delay_segment = delay_seg
        card.add_row(delay_row)

        self._refresh_keep_alive_enabled_state(master_initial)
        lay.insertWidget(insert_at, card)

    def _build_click_sync_card(self, page):
        from utils.icon_factory import make_mouse_icon
        lay = page._panel_layout
        insert_at = lay.count() - 1

        card = CardSurface("pink", title="Click Sync", icon=make_mouse_icon(20))
        self._cards.append(card)
        self._click_sync_panel = card

        row = self._v2_row(
            "Enable Click Sync",
            helper=(
                "Mirror your mouse clicks in one Toontown Rewritten window to "
                "your other selected toons. Choose the toons with the click "
                "sync button on each toon. Works when the windows have "
                "matching proportions."
            ),
        )
        switch = self._v2_switch(
            self.settings_manager.get(CLICK_SYNC_ENABLED, False), "pink")
        switch.toggled.connect(
            lambda v: self.settings_manager.set(CLICK_SYNC_ENABLED, v)
        )
        row.set_control(switch)
        card.add_row(row)
        self._click_sync_switch = switch

        # External flips (the clicksync.toggle hotkey, another Settings
        # surface) must move this switch too. The isChecked guard breaks the
        # set -> on_change -> setChecked -> toggled -> set loop.
        on_change = getattr(self.settings_manager, "on_change", None)
        if on_change is not None:
            on_change(
                lambda key, value: switch.setChecked(bool(value))
                if key == CLICK_SYNC_ENABLED and switch.isChecked() != bool(value)
                else None)

        ghost_row = self._v2_row(
            "Show ghost cursors",
            helper=(
                "Show each toon's glove cursor on their window while click "
                "sync mirrors your mouse there."
            ),
        )
        ghost_switch = self._v2_switch(
            self.settings_manager.get(GHOST_CURSORS_ENABLED, True), "pink")
        ghost_switch.toggled.connect(
            lambda v: self.settings_manager.set(GHOST_CURSORS_ENABLED, v)
        )
        ghost_row.set_control(ghost_switch)
        card.add_row(ghost_row)

        control_row = self._v2_row(
            "Ghost cursors can use card controls",
            helper=(
                "When click sync moves a toon's ghost cursor over its card, let "
                "it press the card's buttons, just like your own cursor can."
            ),
        )
        control_switch = self._v2_switch(
            self.settings_manager.get(GHOST_CURSORS_CONTROL_CARDS, True), "pink")
        control_switch.toggled.connect(
            lambda v: self.settings_manager.set(GHOST_CURSORS_CONTROL_CARDS, v)
        )
        control_row.set_control(control_switch)
        card.add_row(control_row)
        self._ghost_control_field = control_row
        self._ghost_switch = ghost_switch

        # Grey out the control-cards row whenever ghost cursors are off: the
        # feature is meaningless without ghosts, and the runtime gate ANDs the two.
        def _sync_ghost_control_enabled(on):
            control_row.set_row_disabled(not bool(on))
        self._sync_ghost_control_enabled = _sync_ghost_control_enabled
        ghost_switch.toggled.connect(_sync_ghost_control_enabled)
        _sync_ghost_control_enabled(
            self.settings_manager.get(GHOST_CURSORS_ENABLED, True))

        lay.insertWidget(insert_at, card)

    def _build_hotkeys_card(self, page):
        from utils.hotkey_actions import ACTIONS
        from utils.icon_factory import make_nav_keyboard
        from utils.widgets.pill_controls import ChordPill

        lay = page._panel_layout
        insert_at = lay.count() - 1

        card = CardSurface(
            "green", title="Hotkeys",
            sub=("Trigger app actions from anywhere with keyboard shortcuts. "
                 "Shortcuts are grabbed system-wide while the app runs."),
            icon=make_nav_keyboard(20, None))
        self._cards.append(card)
        self._hotkeys_panel = card
        self._hotkey_rows: dict = {}
        self._hotkey_status: dict = {}
        self._hotkey_slot_combos: dict = {}
        self._hotkey_accounts_provider = None
        self._v2_dropdowns: list = []

        # One capture row per registry action, grouped by category.
        categories: list[str] = []
        for action in ACTIONS:
            if action.category not in categories:
                categories.append(action.category)
        first_category = categories[0]

        # The card is tall (16 rows), so only the first category shows by
        # default; every later row lives in this collapsible container,
        # revealed by the Show more toggle added below. Collapsed is the
        # default on every construction - no persistence by design.
        more_container = QWidget()
        more_container.setStyleSheet("background: transparent;")
        more_lay = QVBoxLayout(more_container)
        more_lay.setContentsMargins(0, 0, 0, 0)
        more_lay.setSpacing(12)
        self._hotkey_more_container = more_container

        for category in categories:
            for action in ACTIONS:
                if action.category != category:
                    continue
                # Skip the prefix when the label already leads with the
                # category name ("Launch account slot 1" under Launch):
                # prefixing would double the word.
                if action.label.lower().startswith(category.lower()):
                    field_label = action.label
                else:
                    field_label = f"{category} - {action.label}"
                row = self._v2_row(field_label)
                button = ChordPill(
                    self._hotkey_stored_chord(action.id),
                    lambda text, aid=action.id: self._on_hotkey_chord(aid, text),
                    on_capture_end=self._refresh_hotkey_status,
                )
                if action.id.startswith("launch.slot_"):
                    # The slot's account picker sits inline between the
                    # label and the chord button. Built empty here; main
                    # wires the accounts provider after tab construction
                    # and the combos repopulate then (and on every show).
                    slot = action.id.rsplit("_", 1)[-1]
                    combo = DropdownPill()
                    combo.setFixedWidth(200)
                    combo.currentIndexChanged.connect(
                        lambda _i, s=slot, c=combo:
                        self._on_hotkey_slot_selected(s, c.currentData()))
                    self._v2_dropdowns.append(combo)
                    row.add_control(combo)
                    row.add_control(button)
                    self._hotkey_slot_combos[slot] = combo
                else:
                    row.set_control(button)
                if category == first_category:
                    card.add_row(row)
                else:
                    more_lay.addWidget(row)
                self._hotkey_rows[action.id] = button

        self._hotkey_more_count = sum(
            1 for a in ACTIONS if a.category != first_category)

        toggle = GhostExpander()
        toggle.set_state(expanded=False, more_count=self._hotkey_more_count)
        toggle.clicked.connect(self._on_hotkey_more_toggled)
        self._hotkey_more_toggle = toggle
        toggle_row = QWidget()
        toggle_row.setStyleSheet("background: transparent;")
        toggle_lay = QHBoxLayout(toggle_row)
        toggle_lay.setContentsMargins(0, 0, 0, 0)
        toggle_lay.addStretch(1)
        toggle_lay.addWidget(toggle)
        toggle_lay.addStretch(1)
        card.add_row(toggle_row)
        card.add_row(more_container)
        more_container.hide()

        self._rebuild_hotkey_slot_rows()

        lay.insertWidget(insert_at, card)

    def _on_hotkey_more_toggled(self) -> None:
        """Expand/collapse the below-the-fold hotkey rows. Collapsed is the
        default on every construction - no persistence by design."""
        container = self._hotkey_more_container
        show = container.isHidden()
        container.setVisible(show)
        self._hotkey_more_toggle.set_state(
            expanded=show, more_count=self._hotkey_more_count)

    def _hotkey_stored_chord(self, action_id):
        """The chord this row should DISPLAY: stored override (None = cleared)
        or the registry default when the id is absent from the store."""
        from utils.hotkey_actions import action_by_id
        from utils.settings_keys import HOTKEY_BINDINGS
        stored = self.settings_manager.get(HOTKEY_BINDINGS, {}) or {}
        if not isinstance(stored, dict):
            stored = {}
        if action_id in stored:
            return stored[action_id]
        return action_by_id(action_id).default_chord

    def _on_hotkey_chord(self, action_id, chord_text):
        """Persist a capture-row change. Binding an in-use chord (stored OR
        registry default) prompts steal-or-cancel; stealing clears the other
        action's binding explicitly (None) so the default cannot re-arm it."""
        from utils.hotkey_actions import ACTIONS, action_by_id
        from utils.hotkey_capture import display_chord
        from utils.hotkey_chords import format_chord, parse_chord
        from utils.settings_keys import HOTKEY_BINDINGS
        raw = self.settings_manager.get(HOTKEY_BINDINGS, {}) or {}
        stored = dict(raw) if isinstance(raw, dict) else {}
        if chord_text is not None:
            holder = None
            for action in ACTIONS:
                if action.id == action_id:
                    continue
                current = (stored[action.id] if action.id in stored
                           else action.default_chord)
                if current is not None:
                    # Canonicalize before comparing: a hand-edited store can
                    # hold "alt+ctrl+H" for the same chord as "ctrl+alt+h".
                    try:
                        current = format_chord(parse_chord(current))
                    except ValueError:
                        pass                     # garbage: compare raw
                if current == chord_text:
                    holder = action.id
                    break
            if holder is not None:
                answer = QMessageBox.question(
                    self, "Hotkey in use",
                    f"'{display_chord(chord_text)}' is already bound to "
                    f"{action_by_id(holder).label}. Move it here?")
                if answer != QMessageBox.Yes:
                    self._hotkey_rows[action_id].set_chord(
                        self._hotkey_stored_chord(action_id))
                    return
                stored[holder] = None
                self._hotkey_rows[holder].set_chord(None)
        stored[action_id] = chord_text
        self.settings_manager.set(HOTKEY_BINDINGS, stored)

    def set_hotkey_accounts_provider(self, fn) -> None:
        """Late-bound accounts source for the launch-slot pickers: a callable
        returning [(account_id, game, label), ...] (get_accounts_basic shape).
        main wires this after tab construction."""
        self._hotkey_accounts_provider = fn
        if self._hotkey_slot_combos:
            self._rebuild_hotkey_slot_rows()

    def _rebuild_hotkey_slot_rows(self) -> None:
        """Repopulate the four launch-slot pickers from the accounts provider,
        preselecting the persisted assignment. Signal-blocked: repopulating
        must never fire a spurious _on_hotkey_slot_selected persist."""
        from utils.settings_keys import HOTKEY_LAUNCH_SLOTS
        accounts = []
        if self._hotkey_accounts_provider is not None:
            try:
                accounts = list(self._hotkey_accounts_provider() or [])
            except Exception:
                accounts = []
        raw = self.settings_manager.get(HOTKEY_LAUNCH_SLOTS, {}) or {}
        assigned = raw if isinstance(raw, dict) else {}
        for slot, combo in self._hotkey_slot_combos.items():
            combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItem("(none)", None)
                for account_id, game, label in accounts:
                    combo.addItem(f"{label} ({str(game).upper()})", account_id)
                idx = combo.findData(assigned.get(slot))
                combo.setCurrentIndex(idx if idx >= 0 else 0)
            finally:
                combo.blockSignals(False)

    def _on_hotkey_slot_selected(self, slot, account_id) -> None:
        from utils.settings_keys import HOTKEY_LAUNCH_SLOTS
        raw = self.settings_manager.get(HOTKEY_LAUNCH_SLOTS, {}) or {}
        assigned = dict(raw) if isinstance(raw, dict) else {}
        assigned[slot] = account_id
        self.settings_manager.set(HOTKEY_LAUNCH_SLOTS, assigned)

    def set_hotkey_status(self, failures: dict) -> None:
        """Push the provider's failure map. Rows mid-capture are left alone
        (the prompt text must not be clobbered); the status re-applies when
        the capture ends: cancelled captures fire the button's
        on_capture_end (_refresh_hotkey_status), successful ones write
        settings, which triggers main's delayed status push."""
        self._hotkey_status = dict(failures or {})
        self._refresh_hotkey_status()

    def _refresh_hotkey_status(self) -> None:
        for action_id, btn in self._hotkey_rows.items():
            if btn.is_capturing():
                continue
            btn.set_chord(self._hotkey_stored_chord(action_id))  # base text
            reason = self._hotkey_status.get(action_id)
            if reason:
                btn.setText(btn.text() + " - " + reason)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Accounts can be added or renamed while Settings is hidden, so the
        # launch-slot pickers repopulate on every show. Safe and cheap: the
        # rebuild is signal-blocked and preselect-preserving, and
        # get_accounts_basic never touches the keyring.
        if getattr(self, "_hotkey_accounts_provider", None) is not None:
            self._rebuild_hotkey_slot_rows()

    def _build_chat_handling_card(self, page):
        from utils.settings_keys import (
            CHAT_HANDLING_MODE, CHAT_HANDLING_MODE_DEFAULT,
            CHAT_HANDLING_FOCUSED_ONLY, CHAT_HANDLING_ALL_TOONS,
            CHAT_HANDLING_KEYSET_DYNAMIC, CHAT_HANDLING_PER_TOON,
            normalize_chat_handling_mode,
        )
        from utils.icon_factory import make_chat_icon
        from utils.widgets.option_tiles import OptionTileGrid

        lay = page._panel_layout
        insert_at = lay.count() - 1

        card = CardSurface("blue", title="Chat Handling",
                           sub="How chat input is forwarded to your toons.",
                           icon=make_chat_icon(20))
        self._cards.append(card)
        self._chat_handling_panel = card

        items = [
            (CHAT_HANDLING_FOCUSED_ONLY, "Focused Toon Only",
             "Chat affects only the toon you are playing"),
            (CHAT_HANDLING_ALL_TOONS, "All Toons",
             "Mirror chat to every active toon"),
            (CHAT_HANDLING_KEYSET_DYNAMIC, "Keyset Dynamic",
             "Mirror to toons on the default keyset"),
            (CHAT_HANDLING_PER_TOON, "Per-Toon (manual)",
             "Pick per toon with a chat button on each card"),
        ]
        tiles = OptionTileGrid(items)
        # Initial selection BEFORE connecting: building the card must never
        # write the setting (set_value is silent by contract).
        tiles.set_value(normalize_chat_handling_mode(
            self.settings_manager.get(CHAT_HANDLING_MODE,
                                      CHAT_HANDLING_MODE_DEFAULT)))
        tiles.value_changed.connect(self._on_chat_handling_mode_changed)
        card.add_row(tiles)
        self._chat_handling_tiles = tiles
        self._v2_tile_grids = getattr(self, "_v2_tile_grids", [])
        self._v2_tile_grids.append((tiles, "blue"))

        lay.insertWidget(insert_at, card)

    # ── Keep-Alive handlers ───────────────────────────────────────────────

    def _refresh_keep_alive_enabled_state(self, enabled: bool):
        self._ka_action_row.set_row_disabled(not enabled)
        self._ka_delay_row.set_row_disabled(not enabled)

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
        if 0 <= i < len(self._ka_delay_options):
            self.settings_manager.set("keep_alive_delay", self._ka_delay_options[i])

    # ── Chat Handling handler ────────────────────────────────────────────

    def _on_chat_handling_mode_changed(self, value: str):
        from utils.settings_keys import CHAT_HANDLING_MODE, CHAT_HANDLING_MODE_VALUES
        if value not in CHAT_HANDLING_MODE_VALUES:
            return
        self.settings_manager.set(CHAT_HANDLING_MODE, value)
        self.chat_handling_mode_changed.emit(value)

    def _build_advanced_page(self, page):
        from utils.icon_factory import make_activity_icon, make_database_icon
        lay = page._panel_layout
        insert_at = lay.count() - 1

        # ── Diagnostics & input ──────────────────────────────────────────
        diag = CardSurface("teal", title="Diagnostics & input",
                           icon=make_activity_icon(20))
        self._cards.append(diag)

        log_row = self._v2_row("Enable Logging")
        log_switch = self._v2_switch(
            self.settings_manager.get("show_debug_tab", False), "teal")
        log_switch.toggled.connect(self._on_logging_toggled)
        log_row.set_control(log_switch)
        diag.add_row(log_row)

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
        backend_row = self._v2_row("Input Backend", helper=backend_helper)
        backend_seg = self._v2_segment(backend_options, "teal")
        backend_seg.setCurrentIndex(backend_idx)
        backend_seg.index_changed.connect(self._on_input_backend_changed)
        backend_row.set_control(backend_seg)
        self._backend_segment = backend_seg
        diag.add_row(backend_row)

        lay.insertWidget(insert_at, diag)
        insert_at += 1

        # ── Storage ──────────────────────────────────────────────────────
        maint = CardSurface("red", title="Storage", icon=make_database_icon(20))
        self._cards.append(maint)

        clr_row = self._v2_row(
            "Clear Stored Credentials",
            helper="Delete all saved TTR and CC passwords from Keyring and session memory.")
        clr_btn = self._v2_button("Clear", tone="danger")
        clr_btn.clicked.connect(self._on_clear_credentials_clicked)
        clr_row.set_control(clr_btn)
        maint.add_row(clr_row)

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
                self._backend_segment.setCurrentIndex(0)   # silent by contract
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
        Pages are plain QSS-painted QWidgets, so QGraphicsOpacityEffect is
        safe here (the painter-conflict law only bites custom paintEvents)."""
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

    # ── General handlers ──────────────────────────────────────────────────
    def _on_theme_changed(self, idx):
        theme = ["system", "light", "dark"][idx]
        self.settings_manager.set("theme", theme)
        apply_theme(QApplication.instance(), resolve_theme(self.settings_manager))
        self.theme_changed.emit()

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
    def set_layout_mode(self, mode: str) -> None:
        """Compact<->full swap participant (contract kept for main.py). The
        v2 shell is identical in both modes - the rail centers itself and the
        content column is width-capped unconditionally."""
        if mode not in ("compact", "full"):
            return
        self._layout_mode = mode

    def set_update_checker(self, checker):
        self._update_checker = checker
        checker.update_available.connect(self._on_check_complete_update)
        checker.no_update.connect(self._on_check_complete_no_update)
        checker.check_failed.connect(self._on_check_complete_failed)

    def highlight_keep_alive_group(self):
        """Switch to the Features page and pulse the Keep-Alive card's border.
        Called by Launch-tab's per-slot help affordance."""
        self._show_category("features")
        self.settings_manager.set(SETTINGS_ACTIVE_CATEGORY, "features")
        card = getattr(self, "_keep_alive_panel", None)
        if card is not None:
            card.pulse_highlight()

    _KA_DELAY_SECONDS = {
        "Rapid Fire": 0.25, "1 sec": 1, "5 sec": 5, "10 sec": 10,
        "30 sec": 30, "1 min": 60, "3 min": 180, "5 min": 300,
    }

    def get_keep_alive_delay_seconds(self) -> float:
        if not hasattr(self, "_ka_delay_segment"):
            return 60.0
        label = self._ka_delay_options[self._ka_delay_segment.currentIndex()]
        return float(self._KA_DELAY_SECONDS.get(label, 60.0))

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
        for card in self._cards:
            card.apply_theme(is_dark, animate=True)
        for row in self._v2_rows:
            row.apply_theme(is_dark)
        from utils.theme_manager import get_v2_tokens
        t2 = get_v2_tokens(is_dark)
        for sw, key in self._v2_switches:
            a = V2_ACCENTS[key]
            on = a["b"] if key == "red" else a["c"]
            sw.set_theme_colors(track_on=on,
                                track_off=_qcolor_from_rgba(t2["sw_off"]),
                                thumb="#ffffff")
            sw.set_accent(on, a["b"])
        for seg, key in self._v2_segments:
            seg.apply_theme(is_dark, accent_key=key)
        for btn in self._v2_buttons:
            btn.apply_theme(is_dark)
        for grid, key in getattr(self, "_v2_tile_grids", []):
            grid.apply_theme(is_dark, accent_key=key)
        for pill in self._hotkey_rows.values():
            pill.apply_theme(is_dark)
        for combo in getattr(self, "_v2_dropdowns", []):
            combo.apply_theme(is_dark)
        toggle = getattr(self, "_hotkey_more_toggle", None)
        if toggle is not None:
            toggle.apply_theme(is_dark)

