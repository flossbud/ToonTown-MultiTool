import os
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

import sys
import subprocess
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QProxyStyle, QStyle, QFrame
)
from PySide6.QtCore import QRect, Qt, QMetaObject, Q_ARG, QSize, QEvent, Slot
from PySide6.QtGui import QColor

# === Internal Imports ===
from tabs.multitoon_tab import MultitoonTab
from tabs.launch_tab import LaunchTab
from tabs.keymap_tab import KeymapTab
from tabs.settings_tab import SettingsTab
from tabs.debug_tab import DebugTab
from utils.settings_manager import SettingsManager
from utils.keymap_manager import KeymapManager
from utils.profile_manager import ProfileManager
from services.window_manager import WindowManager
from services.hotkey_manager import HotkeyManager
from utils.theme_manager import (
    apply_theme, resolve_theme, get_theme_colors, apply_card_shadow,
    make_nav_gamepad, make_nav_power,
    make_nav_keyboard, make_nav_gear, make_nav_terminal,
    make_hint_icon,
)


class NoFocusProxyStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PE_FrameFocusRect:
            return
        super().drawPrimitive(element, option, painter, widget)


class MultiToonTool(QMainWindow):
    APP_VERSION = "2.0"

    def __init__(self):
        super().__init__()

        self.setWindowTitle("ToonTown MultiTool")
        self.setGeometry(QRect(100, 100, 560, 650))
        self.setMinimumWidth(520)

        self.pressed_keys = set()
        self.settings_manager = SettingsManager()
        self.keymap_manager = KeymapManager()
        self.profile_manager = ProfileManager()

        self.setObjectName("MultiToonToolMainWindow")
        try:
            win_id = subprocess.check_output(
                ["xdotool", "search", "--name", "ToonTown MultiTool"],
                stderr=subprocess.DEVNULL
            ).decode().strip().split("\n")[0]
            self.settings_manager.set("multitool_window_id", win_id)
        except Exception:
            print("[Main] Warning: Failed to get MultiTool window ID.")

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

        self.settings_tab.debug_visibility_changed.connect(self.toggle_debug_tab_visibility)
        self.settings_tab.theme_changed.connect(self.on_theme_changed)
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
        self.stack.addWidget(self.debug_tab)        # 4
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

        self.log("[Debug] ToonTown MultiTool launched.")

    # ── Hint Toggle ──────────────────────────────────────────────────────

    def _toggle_hints(self):
        self._hints_enabled = not self._hints_enabled
        self.settings_manager.set("hints_enabled", self._hints_enabled)
        self._update_hint_icon()

    def _update_hint_icon(self):
        c = self._theme_colors()
        color = QColor(c['sidebar_text'])
        self.hint_btn.setIcon(make_hint_icon(20, color, active=self._hints_enabled))
        self.hint_btn.setIconSize(QSize(20, 20))

        # The hint button itself always has a tooltip regardless of global state
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
                border: 1px solid rgba(255,255,255,0.2);
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
        header.setFixedHeight(52)
        header.setObjectName("app_header")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(10)

        # Accent stripe (thin vertical bar)
        accent = QFrame()
        accent.setFixedSize(4, 28)
        accent.setObjectName("header_accent")
        layout.addWidget(accent)

        # Title with inline version
        self.title_label = QLabel()
        self.title_label.setObjectName("header_title")
        self.version_label = None  # inline in title_label
        layout.addWidget(self.title_label)

        layout.addStretch()

        # Byline
        self.byline_label = QLabel("by flossbud")
        self.byline_label.setObjectName("header_byline")
        layout.addWidget(self.byline_label)

        return header

    # ── Sidebar ────────────────────────────────────────────────────────────

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setFixedWidth(56)
        sidebar.setObjectName("app_sidebar")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(6, 10, 6, 10)
        layout.setSpacing(4)

        self.nav_buttons = []
        nav_items = [
            ("Multitoon", 0),
            ("Launch",    1),
            ("Keymap",    2),
            ("Settings",  3),
        ]
        for label, idx in nav_items:
            btn = QPushButton()
            btn.setFixedSize(44, 44)
            btn.setCheckable(True)
            btn.setToolTip(label)
            btn.setObjectName(f"nav_{label.lower()}")
            btn.clicked.connect(lambda checked, i=idx: self.nav_select(i))
            layout.addWidget(btn, alignment=Qt.AlignHCenter)
            self.nav_buttons.append(btn)

        layout.addStretch()

        # Logs button at bottom
        self.logs_nav_btn = QPushButton()
        self.logs_nav_btn.setFixedSize(44, 44)
        self.logs_nav_btn.setCheckable(True)
        self.logs_nav_btn.setToolTip("Logs")
        self.logs_nav_btn.setObjectName("nav_logs")
        self.logs_nav_btn.clicked.connect(lambda: self.nav_select(4))
        self.logs_nav_btn.setVisible(self.settings_manager.get("show_debug_tab", False))
        layout.addWidget(self.logs_nav_btn, alignment=Qt.AlignHCenter)
        self.nav_buttons.append(self.logs_nav_btn)

        # Hint toggle button (info icon, always at very bottom)
        self._hints_enabled = self.settings_manager.get("hints_enabled", True)
        self.hint_btn = QPushButton()
        self.hint_btn.setFixedSize(36, 36)
        self.hint_btn.setCursor(Qt.PointingHandCursor)
        self.hint_btn.setObjectName("hint_toggle")
        self.hint_btn.clicked.connect(self._toggle_hints)
        layout.addWidget(self.hint_btn, alignment=Qt.AlignHCenter)

        return sidebar

    def nav_select(self, index: int):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
        self._apply_nav_styles()

    def _apply_nav_icons(self):
        c = self._theme_colors()
        icon_size = 28
        for i, btn in enumerate(self.nav_buttons):
            is_sel = btn.isChecked()
            color = QColor(c['sidebar_text_sel'] if is_sel else c['sidebar_text'])
            icons = [make_nav_gamepad, make_nav_power,
                     make_nav_keyboard, make_nav_gear, make_nav_terminal]
            if i < len(icons):
                btn.setIcon(icons[i](icon_size, color))
                btn.setIconSize(QSize(icon_size, icon_size))

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
                        border-left: 3px solid {c['header_accent']};
                        border-radius: 8px;
                        padding: 8px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {c['sidebar_btn']};
                        border: none;
                        border-radius: 8px;
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
        bg = "#1b1b1b" if is_dark else "#e8e8e8"
        self.container.setStyleSheet(f"QWidget {{ background: {bg}; }}")

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
        self.title_label.setStyleSheet("font-size: 17px; font-weight: bold; background: transparent;")
        self.title_label.setText(
            f'<span style="color:{tc}">ToonTown MultiTool</span>'
            f' <span style="color:{vc}; font-size:11px; font-weight:bold;">v{self.APP_VERSION}</span>'
        )
        self.byline_label.setStyleSheet(f"""
            font-size: 11px; color: {c['header_sub']}; background: transparent;
        """)
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
        self.logs_nav_btn.setVisible(show)
        if not show and self.stack.currentIndex() == 4:
            self.nav_select(0)

    def on_clear_credentials_requested(self):
        self.launch_tab.clear_all_credentials()
        self.log("[Credentials] All stored credentials have been cleared from Keyring.")

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
            self.window_manager.stop()
            self.multitoon_tab._stop_keep_alive()
            self.multitoon_tab.input_service.shutdown()
        except Exception as e:
            print(f"[CloseEvent] Error during shutdown: {e}")
        super().closeEvent(event)

    def log(self, message: str):
        print(message)
        self.debug_tab.append_log(message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle(NoFocusProxyStyle(app.style()))
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