import os
import sys
# Environment must be configured before any Qt module is imported,
# because PySide6 reads QT_QPA_PLATFORM at first import time.
if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM",
        "wayland" if os.getenv("XDG_SESSION_TYPE") == "wayland" else "xcb")
if getattr(sys, "frozen", False):
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import subprocess
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QProxyStyle, QStyle, QFrame, QMessageBox,
    QGraphicsOpacityEffect,
)
from PySide6.QtCore import QRect, Qt, QMetaObject, QSize, QEvent, Signal, Slot, QPropertyAnimation, QEasingCurve, QAbstractAnimation, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QIcon

# === Internal Imports ===
from tabs.multitoon_tab import MultitoonTab
from tabs.launch_tab import LaunchTab
from tabs.keymap_tab import KeymapTab
from tabs.settings_tab import SettingsTab
from tabs.credits_tab import CreditsTab
from tabs.invasions_tab import InvasionsTab
from tabs.debug_tab import DebugTab
from utils.settings_manager import SettingsManager
import utils.ttr_api as ttr_api
from utils.keymap_manager import KeymapManager
from utils.profile_manager import ProfileManager
from services.window_manager import WindowManager
from services.hotkey_manager import HotkeyManager
from utils.game_registry import GameRegistry
from utils.theme_manager import (
    apply_theme, resolve_theme, get_theme_colors, apply_card_shadow,
    make_nav_gamepad, make_nav_power,
    make_nav_keyboard, make_nav_gear, make_nav_terminal, make_nav_bookmark,
    make_hint_icon, make_info_icon, font_role,
)


TITLE_ANIM_DURATION_MS = 800
TITLE_ANIM_MAX_WIDTH = 300

# Layout-mode breakpoint and hysteresis. Window must be >= W_FULL x H_FULL
# (plus deadband on the way up) to enter Full UI; Compact resumes once either
# dimension drops below (breakpoint - deadband) on the way down.
W_FULL = 1280
H_FULL = 800
DEADBAND_W = 80
DEADBAND_H = 60


def _decide_layout_mode(current: str, width: int, height: int) -> str:
    """Pure state-machine: return the layout mode for the given size, given the
    current mode. Implements deadband hysteresis so a window dragged across the
    breakpoint does not flicker."""
    if current == "compact":
        if width >= W_FULL + DEADBAND_W and height >= H_FULL + DEADBAND_H:
            return "full"
        return "compact"
    # current == "full"
    if width <= W_FULL - DEADBAND_W or height <= H_FULL - DEADBAND_H:
        return "compact"
    return "full"


class NoFocusProxyStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PE_FrameFocusRect:
            return
        super().drawPrimitive(element, option, painter, widget)


class AnimatedNavButton(QPushButton):
    """Sidebar button that dynamically scales its icon size on mouse hover."""
    def __init__(self, base_size: int = 28, hover_size: int = 32, parent=None):
        super().__init__(parent)
        self._start = QSize(base_size, base_size)
        self._end = QSize(hover_size, hover_size)
        self.setIconSize(self._start)

        self._anim = QPropertyAnimation(self, b"iconSize")
        self._anim.setDuration(150)
        self._anim.setStartValue(self._start)
        self._anim.setEndValue(self._end)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        
    def enterEvent(self, event):
        super().enterEvent(event)
        self._anim.setDirection(QAbstractAnimation.Forward)
        self._anim.start()
        
    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._anim.setDirection(QAbstractAnimation.Backward)
        self._anim.start()


class MultiToonTool(QMainWindow):
    APP_VERSION = "2.1.0"
    _api_log = Signal(str)

    def __init__(self):
        super().__init__()

        self.setWindowTitle("ToonTown MultiTool")
        # Default 740 height. Threshold for the multitoon tab to render cards
        # without 1-2px compression of the controls pill is 734 (header 48 +
        # tab natural 686). v2.0.3 used a 650 default but Qt auto-grew the
        # window to 734 to fit the central widget; that auto-grow no longer
        # works through the QStackedWidget that hosts Compact + Full layouts,
        # so we set the default high enough to fit content directly.
        self.setGeometry(QRect(100, 100, 560, 740))
        self.setMinimumWidth(575)
        self._layout_mode = "compact"

        self.pressed_keys = set()
        GameRegistry.instance()  # warm up before any launchers
        self.settings_manager = SettingsManager()
        self.keymap_manager = KeymapManager()
        self.profile_manager = ProfileManager()

        self.setObjectName("MultiToonToolMainWindow")
        QTimer.singleShot(0, self._capture_multitool_window_id)

        self.window_manager = WindowManager(self.settings_manager)
        self.window_manager.start()

        self.debug_tab = DebugTab()
        self.logger = self.debug_tab

        self.multitoon_tab = MultitoonTab(
            logger=self.logger,
            settings_manager=self.settings_manager,
            keymap_manager=self.keymap_manager,
            profile_manager=self.profile_manager,
            window_manager=self.window_manager,
        )
        self.launch_tab = LaunchTab(settings_manager=self.settings_manager, logger=self.logger)
        self.keymap_tab = KeymapTab(self.keymap_manager, self.settings_manager)
        self.settings_tab = SettingsTab(self.settings_manager)
        self.credits_tab = CreditsTab(self.settings_manager)
        self.invasions_tab = InvasionsTab(self.settings_manager)

        self.settings_tab.debug_visibility_changed.connect(self.toggle_debug_tab_visibility)
        self.settings_tab.theme_changed.connect(self.on_theme_changed)
        logging_on = self.settings_manager.get("show_debug_tab", False)
        self.debug_tab.logging_enabled = logging_on
        self.multitoon_tab.input_service.logging_enabled = logging_on
        ttr_api.set_debug(logging_on)
        self._api_log.connect(self.debug_tab.append_log)
        ttr_api.set_log_callback(self._api_log.emit)
        self.settings_tab.input_backend_changed.connect(self.on_input_backend_changed)
        self.settings_tab.clear_credentials_requested.connect(self.on_clear_credentials_requested)

        # ── Build layout: header + (sidebar | content) ─────────────────────
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        self.header = self._build_header()
        root.addWidget(self.header)

        # Body: sidebar + stacked content
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = self._build_sidebar()
        body.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.multitoon_tab)   # 0
        self.stack.addWidget(self.launch_tab)       # 1
        self.stack.addWidget(self.keymap_tab)       # 2
        self.stack.addWidget(self.settings_tab)     # 3
        self.stack.addWidget(self.invasions_tab)    # 4
        self.stack.addWidget(self.debug_tab)        # 5
        self.stack.addWidget(self.credits_tab)      # 6
        body.addWidget(self.stack, 1)

        body_widget = QWidget()
        body_widget.setLayout(body)
        root.addWidget(body_widget, 1)

        self.container = QWidget()
        self.container.setLayout(root)
        self.setCentralWidget(self.container)

        self._apply_full_theme()
        self.nav_select(0)
        self._update_hint_icon()

        # Install event filter to globally block tooltips when hints disabled
        QApplication.instance().installEventFilter(self)

        self.hotkey_manager = HotkeyManager(self.window_manager, self.multitoon_tab.key_event_queue)
        self.hotkey_manager.profile_load_requested.connect(self.load_profile_slot)
        self.hotkey_manager.start()

        self.multitoon_tab.dot_state_changed.connect(self.launch_tab.update_dot_state)

        self.log("[Debug] ToonTown MultiTool launched.")
        self.multitoon_tab.prewarm_full_layout(QSize(W_FULL, H_FULL - 48), include_active=True)
        self._animate_launch()

    def _capture_multitool_window_id(self):
        # xdotool is X11-only; on Windows, multitool_window_id is unused
        # (broadcast-while-self-focused isn't wired up on the Win32 backend).
        if sys.platform != "linux":
            return
        try:
            win_id = subprocess.check_output(
                ["xdotool", "search", "--name", "ToonTown MultiTool"],
                stderr=subprocess.DEVNULL,
                timeout=0.5,
            ).decode().strip().split("\n")[0]
            self.settings_manager.set("multitool_window_id", win_id)
        except Exception:
            print("[Main] Warning: Failed to get MultiTool window ID.")

    def _animate_launch(self):
        # Prevent word filtering from causing layout jumps while width is small
        self.title_label.setWordWrap(False)
        self.title_label.setMaximumWidth(0)

        self._launch_anim = QPropertyAnimation(self.title_label, b"maximumWidth")
        self._launch_anim.setDuration(TITLE_ANIM_DURATION_MS)
        self._launch_anim.setStartValue(0)
        self._launch_anim.setEndValue(TITLE_ANIM_MAX_WIDTH)
        self._launch_anim.setEasingCurve(QEasingCurve.OutCubic)

        # After animation, remove the maximum width constraint
        self._launch_anim.finished.connect(lambda: self.title_label.setMaximumWidth(16777215))
        self._launch_anim.start()

    # ── Hint Toggle ──────────────────────────────────────────────────────

    def _toggle_hints(self):
        self._hints_enabled = not self._hints_enabled
        self.settings_manager.set("hints_enabled", self._hints_enabled)
        self._update_hint_icon()

    def _update_hint_icon(self):
        c = self._theme_colors()
        color = QColor(c['sidebar_text'])
        
        # We don't want to reset iconSize dynamically to maintain AnimatedNavButton capability.
        self.hint_btn.setIcon(make_hint_icon(40, color, active=self._hints_enabled))
        state = "on" if self._hints_enabled else "off"
        self.hint_btn.setProperty("_always_tooltip", True)
        self.hint_btn.setToolTip(f"Hover hints are {state} — click to toggle")

        style = f"""
            QPushButton {{
                background: {'rgba(255,255,255,0.08)' if self._hints_enabled else 'transparent'};
                border: 1px solid {'rgba(255,255,255,0.12)' if self._hints_enabled else 'transparent'};
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background: rgba(255,255,255,0.12);
            }}
        """
        self.hint_btn.setStyleSheet(style)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.ToolTip and not self._hints_enabled:
            # Allow the hint button's own tooltip through
            if hasattr(obj, 'property') and obj.property("_always_tooltip"):
                return False
            return True  # Block tooltip
        return False

    # ── Header Bar ─────────────────────────────────────────────────────────

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setMinimumHeight(48)
        header.setObjectName("app_header")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(10)

        # Accent stripe (thin vertical bar)
        accent = QFrame()
        accent.setFixedWidth(4)
        accent.setMinimumHeight(24)
        accent.setObjectName("header_accent")
        layout.addWidget(accent)

        # Title with inline version
        self.title_label = QLabel()
        self.title_label.setObjectName("header_title")
        self.version_label = None  # inline in title_label
        layout.addWidget(self.title_label)

        layout.addStretch()

        return header

    # ── Sidebar ────────────────────────────────────────────────────────────

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setFixedWidth(64)
        sidebar.setObjectName("app_sidebar")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(4)

        self.nav_buttons = []
        nav_items = [
            ("Multitoon", 0),
            ("Launch",    1),
            ("Keymap",    2),
            ("Settings",  3),
            ("Invasions", 4),
        ]
        for label, idx in nav_items:
            btn = AnimatedNavButton(30, 36)
            btn.setFixedSize(48, 48)
            btn.setCheckable(True)
            btn.setToolTip(label)
            btn.setObjectName(f"nav_{label.lower()}")
            btn.clicked.connect(lambda checked, i=idx: self.nav_select(i))
            layout.addWidget(btn, alignment=Qt.AlignHCenter)
            self.nav_buttons.append(btn)

        layout.addStretch()

        # Logs button at bottom
        self.logs_nav_btn = AnimatedNavButton(30, 36)
        self.logs_nav_btn.setFixedSize(48, 48)
        self.logs_nav_btn.setCheckable(True)
        self.logs_nav_btn.setToolTip("Logs")
        self.logs_nav_btn.setObjectName("nav_logs")
        self.logs_nav_btn.clicked.connect(lambda: self.nav_select(5))
        self.logs_nav_btn.setVisible(self.settings_manager.get("show_debug_tab", False))
        layout.addWidget(self.logs_nav_btn, alignment=Qt.AlignHCenter)
        self.nav_buttons.append(self.logs_nav_btn)

        # Credits button
        self.credits_btn = AnimatedNavButton(30, 36)
        self.credits_btn.setFixedSize(48, 48)
        self.credits_btn.setCheckable(True)
        self.credits_btn.setCursor(Qt.PointingHandCursor)
        self.credits_btn.setObjectName("nav_credits")
        self.credits_btn.setToolTip("Credits")
        self.credits_btn.clicked.connect(lambda: self.nav_select(6))
        layout.addWidget(self.credits_btn, alignment=Qt.AlignHCenter)
        self.nav_buttons.append(self.credits_btn)

        # Hint toggle button (always at very bottom)
        self._hints_enabled = self.settings_manager.get("hints_enabled", True)
        self.hint_btn = AnimatedNavButton(30, 36)
        self.hint_btn.setFixedSize(48, 48)
        self.hint_btn.setCursor(Qt.PointingHandCursor)
        self.hint_btn.setObjectName("hint_toggle")
        self.hint_btn.clicked.connect(self._toggle_hints)
        layout.addWidget(self.hint_btn, alignment=Qt.AlignHCenter)

        return sidebar

    def nav_select(self, index: int):
        if self.stack.currentIndex() == index and getattr(self, "_initialized_nav", False):
            return
        self._initialized_nav = True

        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
        self._apply_nav_styles()

        # Fade-in the incoming page
        w = self.stack.currentWidget()
        effect = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(effect)
        self._page_anim = QPropertyAnimation(effect, b"opacity")
        self._page_anim.setDuration(160)
        self._page_anim.setStartValue(0.0)
        self._page_anim.setEndValue(1.0)
        self._page_anim.setEasingCurve(QEasingCurve.OutCubic)
        # Remove the effect after animation so it doesn't interfere with rendering
        self._page_anim.finished.connect(lambda: w.setGraphicsEffect(None))
        self._page_anim.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        size = self.size()
        target = _decide_layout_mode(self._layout_mode, size.width(), size.height())
        if target != self._layout_mode:
            try:
                self._set_layout_mode(target)
            except Exception as e:
                if hasattr(self, "logger") and self.logger:
                    self.logger.append_log(f"[Layout] swap failed: {e}")

    def _set_layout_mode(self, target: str) -> None:
        # Snap layout instantly. Resize events drive the swap (titlebar drag,
        # corner resize, maximize toggle) and fire continuously; a cross-fade
        # via QGraphicsOpacityEffect forces software rendering of the whole
        # multitoon_tab tree, which makes mid-drag resizes laggy and the very
        # first apply takes multiple seconds because the effect path has no
        # warm cache. Instant snap matches the rest of the resize feel.
        self._layout_mode = target
        self.multitoon_tab.set_layout_mode(target)

    def _apply_nav_icons(self):
        c = self._theme_colors()
        icon_size = 28
        for i, btn in enumerate(self.nav_buttons):
            is_sel = btn.isChecked()
            color = QColor(c['sidebar_text_sel'] if is_sel else c['sidebar_text'])
            icons = [make_nav_gamepad, make_nav_power,
                     make_nav_keyboard, make_nav_gear, make_nav_bookmark, make_nav_terminal, make_info_icon]
            if i < len(icons):
                # Render high-res so it doesn't blur on scaling
                btn.setIcon(icons[i](40, color))

    def _apply_nav_styles(self):
        """Update both sidebar button backgrounds/accents and icon colors."""
        c = self._theme_colors()
        for btn in self.nav_buttons:
            is_sel = btn.isChecked()
            if is_sel:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {c['sidebar_btn_sel']};
                        border: none;
                        border-left: 4px solid {c['header_accent']};
                        border-radius: 10px;
                        padding: 8px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {c['sidebar_btn']};
                        border: none;
                        border-radius: 10px;
                        padding: 8px;
                    }}
                    QPushButton:hover {{
                        background: {c['sidebar_btn_sel']};
                    }}
                """)
        self._apply_nav_icons()

    # ── Theme ──────────────────────────────────────────────────────────────

    def _theme_colors(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

    def _apply_full_theme(self):
        theme = resolve_theme(self.settings_manager)
        c = self._theme_colors()
        is_dark = theme == "dark"

        # Container background
        self.container.setStyleSheet(f"QWidget {{ background: {c['bg_app']}; }}")

        # Header
        self.header.setStyleSheet(f"""
            QFrame#app_header {{
                background: {c['header_bg']};
                border-bottom: 1px solid {c['sidebar_border']};
            }}
        """)
        apply_card_shadow(self.header, is_dark, blur=10, offset_y=2)
        tc = c['header_text']
        vc = c['header_accent']
        self.title_label.setStyleSheet(
            f"font-size: {font_role('title')}px; font-weight: bold; background: transparent;"
        )
        self.title_label.setText(
            f'<span style="color:{tc}">ToonTown MultiTool</span>'
            f' <span style="color:{vc}; font-size:{font_role("label")}px; font-weight:bold;">'
            f'v{self.APP_VERSION}</span>'
        )
        # Accent stripe
        accent = self.header.findChild(QFrame, "header_accent")
        if accent:
            accent.setStyleSheet(f"""
                background: {c['header_accent']};
                border-radius: 2px;
            """)

        # Sidebar
        self.sidebar.setStyleSheet(f"""
            QFrame#app_sidebar {{
                background: {c['sidebar_bg']};
                border-right: 1px solid {c['sidebar_border']};
            }}
        """)
        self._apply_nav_styles()
        self._update_hint_icon()

        # Content pages
        self.multitoon_tab.refresh_theme()
        self.multitoon_tab.apply_all_visual_states()
        self.launch_tab.refresh_theme()
        self.keymap_tab.refresh_theme()
        self.settings_tab.refresh_theme()

    def on_theme_changed(self):
        theme = resolve_theme(self.settings_manager)
        apply_theme(QApplication.instance(), theme)
        self._apply_full_theme()

    def on_input_backend_changed(self):
        if self.multitoon_tab.service_running:
            self.multitoon_tab.stop_service()
            self.multitoon_tab.start_service()
            self.log("[Service] Restarted due to input backend change.")

    def toggle_debug_tab_visibility(self, show: bool):
        self.debug_tab.logging_enabled = show
        self.multitoon_tab.input_service.logging_enabled = show
        self.logs_nav_btn.setVisible(show)
        ttr_api.set_debug(show)
        if not show and self.stack.currentIndex() == 5:
            self.nav_select(0)

    def on_clear_credentials_requested(self):
        self.launch_tab.clear_all_credentials()
        self.log("[Credentials] All stored credentials have been cleared from Keyring and session memory.")

    # ── Profiles ────────────────────────────────────────────────────────────

    @Slot(int)
    def load_profile_slot(self, index: int):
        self.multitoon_tab.load_profile(index)
        self.settings_manager.set("active_profile", index)
        self.log(f"[Profile] Loaded profile {index + 1}")

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def closeEvent(self, event):
        try:
            self.hotkey_manager.stop()
            self.launch_tab.shutdown()
            self.multitoon_tab.shutdown()
            self.window_manager.stop()
        except Exception as e:
            print(f"[CloseEvent] Error during shutdown: {e}")
        super().closeEvent(event)

    def log(self, message: str):
        if not self.debug_tab.logging_enabled:
            return
        print(message)
        self.debug_tab.append_log(message)


def _resolve_app_icon() -> QIcon:
    # Linux: AppImage/Flatpak register the icon in the XDG theme.
    # Windows has no theme system, so fromTheme returns a null icon there;
    # fall back to the bundled .ico so setWindowIcon has something to use.
    themed = QIcon.fromTheme("io.github.flossbud.ToonTownMultiTool")
    if not themed.isNull():
        return themed
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return QIcon(os.path.join(base, "assets", "ToonTownMultiTool.ico"))


if __name__ == "__main__":
    # Identity must be set BEFORE QApplication is constructed; Qt reads these
    # at construction time to populate X11 WM_CLASS and Wayland app_id.
    # Without them Qt falls back to argv[0] ("python3" inside the Flatpak)
    # and KDE/GNOME show an orphan taskbar entry with a generic icon.
    QApplication.setApplicationName("ToonTown MultiTool")
    QApplication.setApplicationDisplayName("ToonTown MultiTool")
    QApplication.setOrganizationName("flossbud")
    QGuiApplication.setDesktopFileName("io.github.flossbud.ToonTownMultiTool")
    app = QApplication(sys.argv)
    app.setWindowIcon(_resolve_app_icon())
    app.setStyle(NoFocusProxyStyle(app.style()))
    if sys.platform == "linux":
        from PySide6.QtGui import QFont, QFontDatabase
        QFontDatabase.addApplicationFont("/usr/share/fonts/google-noto-color-emoji-fonts/Noto-COLRv1.ttf")
        _f = app.font()
        _f.setFamilies([_f.family(), "Noto Color Emoji"])
        app.setFont(_f)
    settings = SettingsManager()
    apply_theme(app, resolve_theme(settings))
    window = MultiToonTool()
    window.show()
    sys.exit(app.exec())
