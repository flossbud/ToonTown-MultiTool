from __future__ import annotations

import os
import sys

# Crash diagnostics: faulthandler dumps a Python traceback for all threads
# on SIGSEGV/SIGBUS/SIGABRT. Python 3.14 + PySide6 6.10 has a known class
# of GC-during-paint races where the C stack alone (from coredumpctl) does
# not name the Python paintEvent or worker call site that triggered the
# crash. Writes to a persistent log so the trace survives terminal close;
# `tail -f ~/.cache/toontown-multitool/faulthandler.log` to follow live.
import faulthandler as _ttmt_faulthandler
import datetime as _ttmt_dt
_ttmt_fault_dir = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
    "toontown-multitool",
)
try:
    os.makedirs(_ttmt_fault_dir, exist_ok=True)
    _ttmt_fault_log = open(
        os.path.join(_ttmt_fault_dir, "faulthandler.log"),
        "a",
        buffering=1,
    )
    _ttmt_fault_log.write(
        f"\n=== ttmt {_ttmt_dt.datetime.now().isoformat()} pid={os.getpid()} ===\n"
    )
    _ttmt_faulthandler.enable(file=_ttmt_fault_log, all_threads=True)
except OSError:
    _ttmt_faulthandler.enable(file=sys.stderr, all_threads=True)
del _ttmt_dt, _ttmt_fault_dir

# Redirect to ./venv/bin/python when invoked via system Python. The
# venv ships pip-installed PySide6 with bundled Qt; system PySide6 may
# link against a broken system Qt6 (e.g. the QFontEngineFT NULL-pointer
# crash on current Arch + Python 3.14). Runs BEFORE the version check
# below so a user on a future Python whose system PySide6 has no wheel
# can still launch via the venv's pinned interpreter. See
# utils/venv_reexec.py for the full skip-condition list.
from utils.venv_reexec import reexec_into_venv
reexec_into_venv(__file__)
del reexec_into_venv

# Diagnostic: trace every Xlib.display.Display open/close so we can
# attribute the X11 client-slot leak (see
# docs/handoff-pynput-x11-client-leak-bug.md) to a specific creation
# site. No-op unless TTMT_TRACE_XLIB=1 is set; installed before any
# Xlib import so the wrap catches every call.
if os.environ.get("TTMT_TRACE_XLIB") == "1":
    from utils._xlib_display_tracer import install as _install_xlib_tracer
    _install_xlib_tracer()
    del _install_xlib_tracer

# Upper bound was previously (3, 14) to mirror the PySide6 6.8.x wheel
# ceiling for pip-installed source runs. Bumped to (3, 15) once
# archlinux:latest started shipping Python 3.14 by default: the AUR
# install path uses the system pyside6 (currently 6.10+) which is built
# for whichever Python Arch ships, so the cap was overly defensive there.
# Self-check verified on 3.14 + PySide6 6.10.2. Source-from-git pip users
# on 3.14 may still need to upgrade the PySide6 pin in requirements.txt.
if not (3, 9) <= sys.version_info[:2] < (3, 15):
    sys.stderr.write(
        "ToonTown MultiTool requires Python 3.9-3.14. "
        f"Detected {sys.version.split()[0]}. "
        "See the 'Run from source' section in README.md for setup.\n"
    )
    sys.exit(1)

# Must run before any keyring / PySide6 import. See utils/keyring_macos_stub.py
# for the full incident write-up — TL;DR: skipping this gives a ~60% SIGABRT
# rate on Linux because shiboken6's signature mapping KeyErrors on a class
# whose module path was removed from sys.modules during a partial import.
from utils.keyring_macos_stub import install_stub as _install_keyring_macos_stub
_install_keyring_macos_stub()
del _install_keyring_macos_stub

# Environment must be configured before any Qt module is imported,
# because PySide6 reads QT_QPA_PLATFORM at first import time.
if sys.platform != "win32":
    _session_type = os.getenv("XDG_SESSION_TYPE", "").lower()
    _force_wayland = os.getenv("TTMT_USE_WAYLAND") == "1"
    # Default the Linux Qt platform to xcb (XWayland on Wayland sessions).
    # This app's input/window plumbing — services.window_manager (xdotool),
    # services.hotkey_manager (pynput), and the broadcast-while-self-focused
    # capture in MultiToonTool._capture_multitool_window_id — is X11-only.
    # Until those subsystems gain native Wayland equivalents (libei,
    # xdg-foreign, etc.), running under XWayland is the correct platform.
    # A side effect of this default is dodging a GNOME 50 native-Wayland
    # bug where the launch cursor sticks compositor-side; that was the
    # symptom that surfaced the platform-default question, but the reason
    # to default to xcb stands on its own. TTMT_USE_WAYLAND=1 opts back
    # into native Wayland for diagnostics.
    os.environ.setdefault(
        "QT_QPA_PLATFORM",
        "wayland" if _force_wayland and _session_type == "wayland" else "xcb",
    )
# On GNOME-like Linux desktops, prefer the xdg-desktop-portal Qt platform
# theme so Qt's styleHints().colorScheme() reflects the OS appearance
# setting. Without this, Qt returns ColorScheme.Light regardless of the
# GNOME org.freedesktop.appearance.color-scheme, and "system" theme
# detection always picks light. We narrow this to GNOME-likes (vs. all
# Linux) so XFCE / MATE / sway users — who never set QT_QPA_PLATFORMTHEME
# — don't unexpectedly get portal-style file dialogs and icons. On those
# desktops the direct portal D-Bus query in utils.theme_manager still
# picks up dark mode without changing any other Qt behavior.
if sys.platform == "linux":
    try:
        from PySide6.QtCore import QLibraryInfo
        from utils.theme_manager import should_set_xdg_portal_platformtheme
        _plugin_path = os.path.join(
            QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath),
            "platformthemes",
            "libqxdgdesktopportal.so",
        )
        if should_set_xdg_portal_platformtheme(_plugin_path):
            os.environ.setdefault("QT_QPA_PLATFORMTHEME", "xdgdesktopportal")
    except Exception:
        pass
if getattr(sys, "frozen", False):
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import subprocess
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QToolButton, QProxyStyle, QStyle, QFrame,
    QSpacerItem, QSizePolicy,
)
from PySide6.QtCore import QObject, QRect, QRectF, Qt, QSize, QEvent, Signal, Slot, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QIcon

# === Internal Imports ===
from tabs.multitoon_tab import MultitoonTab
from tabs.launch_tab import LaunchTab
from tabs.keymap_tab import KeymapTab
from tabs.settings_tab import SettingsTab
from tabs.credits_tab import CreditsTab
from tabs.debug_tab import DebugTab
from utils.version import APP_VERSION
from utils.settings_manager import SettingsManager
import utils.ttr_api as ttr_api
from utils.keymap_manager import KeymapManager
from utils.profile_manager import ProfileManager
from services.window_manager import WindowManager
from utils.game_registry import GameRegistry
from utils.theme_manager import (
    apply_theme, resolve_theme, get_theme_colors, apply_card_shadow,
    make_nav_gamepad, make_nav_power, make_nav_keyboard, make_nav_gear,
    make_hint_icon, font_role,
    SystemThemeWatcher,
)
from utils.build_flavor import window_title, app_name, is_beta


TITLE_ANIM_DURATION_MS = 800
TITLE_ANIM_MAX_WIDTH = 300

# Layout-mode breakpoint and hysteresis. Window must be >= W_FULL x H_FULL
# (plus deadband on the way up) to enter Full UI; Compact resumes once either
# dimension drops below (breakpoint - deadband) on the way down.
#
# H_FULL=800 matches the pre-chip-rail trigger threshold so users who used
# to enter Full at ~860 height (1280+80, 800+60) still can. At the trigger,
# content area = 860 - HEADER_H(56) - CHIP_RAIL_H(64) = 740, which renders
# the 2x2 card grid at ~99.5% of its 632x360 reference (744-design). As
# the window grows, cards scale up to 100% and then cap at _MAX_CARD.
# The earlier bump to 852/864 preserved cards-at-100% at the trigger
# but raised the threshold past users' habitual window heights, so we
# accept the 4px (0.5%) card scale-down at the trigger to keep the
# threshold accessible.
#
# After the QGraphicsView wrapping for Full UI cards (May 2026) the
# scale is 1.125x, so the 2x2 grid (2 × 551 × 1.125 + spacing + margins
# ≈ 1272 px) fits within the original 1280 trigger; W_FULL stays at
# 1280. (An earlier iteration ran 1.5x and bumped W_FULL to 1700 before
# the user dialed the scale back.) H_FULL stays at 800; the 2x2
# arrangement uses less vertical room than compact's 1x4 stack.
W_FULL = 1280
H_FULL = 800
DEADBAND_W = 80
DEADBAND_H = 60

# Chrome heights — used by H_FULL math, prewarm hint, and the header /
# chip rail QFrames so the value lives in one place. CHIP_RAIL_H is the
# minimum that lets a chip with text-under-icon at the configured 10pt
# label font render its label without Qt clipping it under layout
# pressure; if the chip sizeHint ever grows past 52px, bump this in
# lockstep or `tests/test_chip_rail.py::test_chip_rail_height_accommodates_chip_sizeHint`
# will fail.
HEADER_H = 112
CHIP_RAIL_H = 64
APP_DESKTOP_ID = "io.github.flossbud.ToonTownMultiTool"
BETA_DESKTOP_ID = "io.github.flossbud.ToonTownMultiTool-beta"
LEGACY_DESKTOP_ID = "toontown-multitool"


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


class _BrandLink(QFrame):
    """Header logo+accent+title wrapper. Click → Credits page (index 5)
    via a vertical push-slide animation."""

    def __init__(self, credits_callback, parent=None):
        super().__init__(parent)
        self._credits_callback = credits_callback
        self.setObjectName("header_brand_link")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("About / Credits")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self._credits_callback()
        super().mouseReleaseEvent(event)


def _desktop_file_exists(desktop_id: str) -> bool:
    filename = f"{desktop_id}.desktop"
    data_dirs = [
        os.path.expanduser("~/.local/share"),
        *os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"),
    ]
    return any(
        os.path.isfile(os.path.join(data_dir, "applications", filename))
        for data_dir in data_dirs
        if data_dir
    )


def _is_packaged_install() -> bool:
    """True when the running process is a packaged install whose XDG theme /
    .desktop registrations belong to *this* instance. False for from-source dev
    runs, where those registrations may belong to a different (e.g. previously
    installed) copy of ourselves and must not be trusted."""
    if getattr(sys, "frozen", False):
        return True
    if os.environ.get("APPIMAGE"):
        return True
    if os.environ.get("FLATPAK_ID") in (APP_DESKTOP_ID, BETA_DESKTOP_ID):
        return True
    # OS package install (AUR/.deb/RPM): script lives in a system path, not $HOME.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    home = os.path.expanduser("~")
    return not (script_dir + os.sep).startswith(home + os.sep)


def _is_appimage_install() -> bool:
    return bool(os.environ.get("APPIMAGE"))


def _select_desktop_file_name() -> str | None:
    override = os.environ.get("TTMT_DESKTOP_FILE_NAME")
    if override:
        if override.lower() in {"0", "false", "none", "off"}:
            return None
        return override

    canonical_id = BETA_DESKTOP_ID if is_beta() else APP_DESKTOP_ID

    if sys.platform != "linux":
        return canonical_id
    # Only trust a system-installed .desktop if we are a packaged install.
    # Otherwise the entry may be from a coexisting Flatpak/AUR/etc. install
    # of ourselves, and using it as the Wayland app_id makes the WM render
    # that foreign install's icon in the taskbar.
    #
    # AppImage returns None deliberately: a host .desktop entry with the
    # canonical id almost always belongs to a different install method's
    # version (current AUR / .deb / Flatpak, or a stale one of those that
    # left files behind), and binding the AppImage to that id makes the WM
    # render the foreign install's icon. The trade-off: the AppImage window
    # no longer groups with any installed .desktop entry, so users who
    # registered the AppImage's bundled .desktop via AppImageLauncher / a
    # manual symlink lose menu integration, jump-list actions, and
    # Categories= grouping for the running window. With None returned, Qt
    # falls back to QCoreApplication::applicationName() ("ToonTown
    # MultiTool" with a space) as the app_id, which is non-conformant per
    # xdg-shell conventions but tolerated by Plasma/GNOME/sway. Acceptable
    # trade-off because the alternative (wrong taskbar icon) is more
    # visible than the lost integration.
    if _is_appimage_install():
        return None
    if _is_packaged_install():
        if _desktop_file_exists(canonical_id):
            return canonical_id
        if not is_beta() and _desktop_file_exists(LEGACY_DESKTOP_ID):
            return LEGACY_DESKTOP_ID
        return canonical_id
    return None


class MultiToonTool(QMainWindow):
    _api_log = Signal(str)

    def __init__(self):
        super().__init__()

        self.setWindowTitle(window_title())
        # Default 748 height. Threshold for the multitoon tab to render cards
        # without 1-2px compression of the controls pill is 742 (header 56 +
        # tab natural 686). v2.0.3 used a 650 default but Qt auto-grew the
        # window to fit the central widget; that auto-grow no longer works
        # through the QStackedWidget that hosts Compact + Full layouts, so we
        # set the default high enough to fit content directly.
        self.setGeometry(QRect(100, 100, 560, 770))
        self.setMinimumWidth(575)
        self._layout_mode = "compact"

        self.pressed_keys = set()
        GameRegistry.instance()  # warm up before any launchers
        self.settings_manager = SettingsManager()
        from utils.update_defaults import apply_first_launch_defaults
        apply_first_launch_defaults(self.settings_manager)

        # Hook motion module into the app's settings.
        import utils.motion as motion
        motion.set_settings_manager(self.settings_manager)
        self.settings_manager.on_change(motion.on_settings_change)

        self.keymap_manager = KeymapManager()
        self.profile_manager = ProfileManager()
        self.hotkey_manager = None

        # Auto-detect TTR settings at startup so the default keyset reflects
        # the user's TTR config without requiring a manual "Detect" press.
        # Cached on settings_manager so the result survives if settings.json
        # is unreadable on a later run.
        self._apply_startup_ttr_keymap()

        self.setObjectName("MultiToonToolMainWindow")
        self._shutdown_complete = False
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
        self.customization_overlay: ToonCustomizationOverlay | None = None
        self.launch_tab = LaunchTab(settings_manager=self.settings_manager, logger=self.logger, window_manager=self.window_manager)
        self.keymap_tab = KeymapTab(
            self.keymap_manager,
            self.settings_manager,
            credentials_manager=self.launch_tab.cred_manager,
        )
        self.settings_tab = SettingsTab(self.settings_manager)
        self.credits_tab = CreditsTab(self.settings_manager)

        self.settings_tab.debug_visibility_changed.connect(self.toggle_debug_tab_visibility)
        self.settings_tab.theme_changed.connect(self.on_theme_changed)
        self._system_theme_watcher = SystemThemeWatcher(self)
        self._system_theme_watcher.system_theme_changed.connect(
            self._on_system_color_scheme_changed
        )
        # Credits tab also needs to repaint on OS theme changes when the
        # user's pref is "system". Late-bound here because the watcher
        # exists after CreditsTab is constructed.
        self._system_theme_watcher.system_theme_changed.connect(
            self.credits_tab._on_system_theme_changed
        )
        logging_on = self.settings_manager.get("show_debug_tab", False)
        self.debug_tab.logging_enabled = logging_on
        self.multitoon_tab.input_service.logging_enabled = logging_on
        # Wire the chat-aware key-block resolver into the input service. The
        # callable is invoked per key event so settings.json edits are honored
        # without restarting TTMT. Re-parse on each call rather than caching:
        # the cost is a small JSON read; the win is liveness.
        from utils.ttr_settings import resolve_chat_block_list
        def _chat_block_list_provider():
            s = self._refresh_ttr_settings()
            if s is None:
                return {"Return", "Escape"}
            return resolve_chat_block_list(s)
        self.multitoon_tab.input_service.get_chat_block_list = _chat_block_list_provider
        ttr_api.set_debug(logging_on)
        self._api_log.connect(self.debug_tab.append_log)
        ttr_api.set_log_callback(self._api_log.emit)
        self.settings_tab.input_backend_changed.connect(self.on_input_backend_changed)
        self.settings_tab.clear_credentials_requested.connect(self.on_clear_credentials_requested)

        # Chat handling mode: SettingsTab toggle -> MultitoonTab visibility.
        # The signal carries the new mode string ("simple"|"advanced").
        self.settings_tab.chat_handling_mode_changed.connect(
            self.multitoon_tab.apply_chat_handling_mode
        )

        # Apply the persisted Chat Handling mode once at startup so the
        # chat buttons reflect the setting on launch without waiting for
        # a user toggle. Default "simple" -> buttons hidden.
        from utils.settings_keys import CHAT_HANDLING_MODE, CHAT_HANDLING_MODE_DEFAULT
        initial_mode = self.settings_manager.get(CHAT_HANDLING_MODE, CHAT_HANDLING_MODE_DEFAULT)
        self.multitoon_tab.apply_chat_handling_mode(initial_mode)

        # ── Build layout: header + banner + chip_rail + stacked content ────
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        from utils.widgets.update_banner import UpdateBanner
        self.update_banner = UpdateBanner(parent=self)
        self.update_banner.clicked.connect(self._on_update_banner_clicked)
        self.update_banner.dismissed.connect(self._on_update_banner_dismissed)
        self._pending_update_info = None

        self.header = self._build_header()
        root.addWidget(self.header)

        # Banner sits between the header and the tab switcher; in normal flow
        # so show/hide reflows the content below down.
        root.addWidget(self.update_banner)

        self.chip_rail = self._build_chip_rail()
        root.addWidget(self.chip_rail)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.multitoon_tab)   # 0
        self.stack.addWidget(self.launch_tab)       # 1
        self.stack.addWidget(self.keymap_tab)       # 2
        self.stack.addWidget(self.settings_tab)     # 3
        self.stack.addWidget(self.debug_tab)        # 4
        self.stack.addWidget(self.credits_tab)      # 5
        root.addWidget(self.stack, 1)

        self.container = QWidget()
        self.container.setLayout(root)
        self.setCentralWidget(self.container)

        self._apply_full_theme()
        self._refresh_header_session_status()
        # Demo mode (TTMT_DEMO_LAUNCH_TAB) jumps directly to the Launch tab so
        # the visual verification script can capture it without synthesizing
        # clicks through xdotool.
        _initial_tab = 1 if os.environ.get("TTMT_DEMO_LAUNCH_TAB") else 0
        self.nav_select(_initial_tab)
        self._setup_update_checker()
        self._maybe_kick_off_startup_check()
        self._update_hint_icon()

        # Install event filter to globally block tooltips when hints disabled
        QApplication.instance().installEventFilter(self)

        from services.hotkey_manager import HotkeyManager
        self.hotkey_manager = HotkeyManager(
            self.window_manager,
            self.multitoon_tab.key_event_queue,
            suppress_predicate=self.multitoon_tab.input_service._suppress_predicate,
        )
        self.hotkey_manager.profile_load_requested.connect(self.load_profile_slot)
        self.hotkey_manager.start()

        self.multitoon_tab.dot_state_changed.connect(self.launch_tab.update_dot_state)
        self.multitoon_tab.dot_state_changed.connect(
            lambda *_: self._refresh_header_session_status()
        )
        # Also refresh on service-button click — toggle_service can complete
        # without emitting dot_state_changed (e.g. when no toons are enabled),
        # which would leave the header stuck on the previous Running/Idle.
        self.multitoon_tab.toggle_service_button.clicked.connect(
            lambda _checked=False: self._refresh_header_session_status()
        )
        self.multitoon_tab.keep_alive_help_requested.connect(
            self._on_keep_alive_help_requested
        )
        self.multitoon_tab.launch_tab_requested.connect(
            lambda: self.nav_select(1)
        )

        self.log(f"[Debug] {app_name()} launched.")
        self.multitoon_tab.prewarm_full_layout(
            QSize(W_FULL, H_FULL - HEADER_H - CHIP_RAIL_H),
            include_active=True,
        )
        self._animate_launch()

    def _capture_multitool_window_id(self):
        # xdotool is X11-only; the gate is on the Qt platform, not the
        # session type. With the default QT_QPA_PLATFORM=xcb on Linux,
        # Wayland-session users actually run under XWayland, which xdotool
        # can drive. Skipping when XDG_SESSION_TYPE=wayland would silently
        # break those users' broadcast-while-self-focused capture.
        if sys.platform != "linux":
            return
        if os.environ.get("QT_QPA_PLATFORM", "").lower() == "wayland":
            return
        try:
            # TODO(beta): when both stable and beta run side-by-side, this substring
            # match returns BOTH windows. Revisit if it becomes a problem.
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

        icon_size = self.hint_btn.iconSize().width()
        self.hint_btn.setIcon(make_hint_icon(icon_size, color, active=self._hints_enabled))
        state = "on" if self._hints_enabled else "off"
        self.hint_btn.setProperty("_always_tooltip", True)
        self.hint_btn.setToolTip(f"Hover hints are {state}. Click to toggle.")

        # The button itself is bare — the on/off state is carried by the
        # icon's own active styling (see make_hint_icon's `active` arg).
        # An always-on background+border (the pre-header sidebar treatment)
        # boxed the button and pulled the eye in the otherwise-minimal
        # header. No :focus rule because the button is set NoFocus in
        # _build_header — a stray :focus border would never fire anyway
        # and just risked confusing future readers.
        style = """
            QPushButton, QToolButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
            }
            QPushButton:hover, QToolButton:hover {
                background: rgba(255,255,255,0.06);
            }
        """
        self.hint_btn.setStyleSheet(style)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.ToolTip and not self._hints_enabled:
            # Allow the hint button's own tooltip through
            if hasattr(obj, 'property') and obj.property("_always_tooltip"):
                return False
            return True  # Block tooltip
        return False

    # ── Update flow ────────────────────────────────────────────────────────

    def _setup_update_checker(self):
        from utils.update_checker import UpdateChecker
        from utils.update_runner import UpdateRunner
        self.update_checker = UpdateChecker(self.settings_manager, parent=self)
        self.update_runner = UpdateRunner(self)
        self.update_checker.update_available.connect(self._on_update_available)
        if hasattr(self.settings_tab, "set_update_checker"):
            self.settings_tab.set_update_checker(self.update_checker)

    def _maybe_kick_off_startup_check(self):
        if not bool(self.settings_manager.get("check_for_updates_at_startup", False)):
            return
        self.update_checker.check_async(manual=False)

    def _on_update_available(self, info):
        self._pending_update_info = info
        self.update_banner.show_for_release(info)

    def _on_update_banner_clicked(self):
        info = getattr(self, "_pending_update_info", None)
        if info is None:
            return
        from utils.widgets.update_dialog import UpdateDialog
        from utils import build_info
        dlg = UpdateDialog(info, local_version_string=build_info.version_string(), parent=self)
        dlg.update_now.connect(lambda: self.update_runner.run_update(info))
        dlg.skip_version.connect(lambda: self.settings_manager.set("update_skipped_version", info["tag_name"]))
        dlg.skip_version.connect(self.update_banner.hide)
        dlg.exec()

    def _on_update_banner_dismissed(self):
        # Session-only dismiss; nothing to persist.
        pass

    # ── Header Bar ─────────────────────────────────────────────────────────

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setMinimumHeight(HEADER_H)
        header.setObjectName("app_header")

        outer = QHBoxLayout(header)
        # 1px bottom margin reserves the QSS border-bottom row (Qt does not
        # shrink contentsRect for a partial border).
        outer.setContentsMargins(0, 0, 0, 1)
        outer.setSpacing(0)
        outer.addStretch()

        # Centered wordmark. The pixmap (and its theme variant) is assigned in
        # _apply_full_theme via _refresh_header_logo so theme + sizing live in
        # one place.
        self.header_logo = QLabel()
        self.header_logo.setObjectName("header_logo")
        self.header_logo.setAlignment(Qt.AlignCenter)
        self.header_logo.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        outer.addWidget(self.header_logo, 0, Qt.AlignCenter)

        outer.addStretch()

        # Render an initial pixmap so the label is non-empty before theming
        # (tests build the header without _apply_full_theme).
        self._refresh_header_logo(header_width=575)
        return header

    def _refresh_header_logo(self, header_width=None):
        from PySide6.QtGui import QPixmap
        from utils.window_layout import compute_logo_size
        is_dark = True
        if hasattr(self, "settings_manager"):
            from utils.theme_manager import resolve_theme
            is_dark = resolve_theme(self.settings_manager) == "dark"
        fname = "ttmt_logo_textonly.png" if is_dark else "ttmt_logo_textonly_shadow.png"
        path = os.path.join(_assets_dir(), "logos", fname)
        src = QPixmap(path)
        if src.isNull():
            return
        w = header_width if header_width is not None else (
            self.header.width() if hasattr(self, "header") and self.header.width() else 575
        )
        tw, th = compute_logo_size(w, src.width(), src.height(), target_height=80)
        if tw <= 0 or th <= 0:
            return
        scaled = src.scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.header_logo.setPixmap(scaled)

    # ── Chip Rail ──────────────────────────────────────────────────────────

    def _build_chip_rail(self) -> QFrame:
        rail = QFrame()
        rail.setMinimumHeight(CHIP_RAIL_H)
        rail.setObjectName("app_chip_rail")

        from utils.widgets.pill_indicator import PillIndicator
        self.chip_pill = PillIndicator(rail)
        self.chip_pill.lower()
        # Install a lightweight QObject event filter (parented to rail so it
        # is garbage-collected with the rail). Using a dedicated QObject
        # rather than `self` keeps the test harness working — tests build via
        # __new__, which doesn't call QMainWindow.__init__, so `self` is not
        # a valid QObject for installEventFilter.
        chip_pill_ref = self.chip_pill
        outer_self = self  # captured for the nested class to access chip_buttons/stack

        class _RailResizeFilter(QObject):
            def eventFilter(self_, watched, event):  # noqa: N805
                if event.type() == QEvent.Resize:
                    chip_pill_ref.resize(watched.size())
                    # Place the pill on the currently-selected chip whenever
                    # the rail re-lays-out (initial show after __init__,
                    # window resize, compact↔full layout swap). nav_select
                    # runs during __init__ before chip geometries are
                    # computed, so this filter is the source of truth for
                    # initial placement and resize tracking.
                    if not hasattr(outer_self, "chip_buttons"):
                        return False
                    # Use isChecked() — NOT stack.currentIndex() — because
                    # during an in-flight push_slide_pages animation,
                    # currentIndex is still the OUTGOING page (setCurrentIndex
                    # is deferred to _finalize). chip.setChecked is applied
                    # synchronously in nav_select so it reflects the truth.
                    checked_idx = None
                    for i, c in enumerate(outer_self.chip_buttons):
                        if c.isChecked():
                            checked_idx = i
                            break
                    if checked_idx is None:
                        # No chip checked (e.g., user is on Credits via the
                        # brand-click path) — leave the pill where it is.
                        return False
                    target_geom = outer_self.chip_buttons[checked_idx].geometry()
                    if target_geom.isEmpty():
                        return False
                    # Cancel any in-flight slide_to — its end value points
                    # at the chip's pre-resize geometry and is now stale.
                    chip_pill_ref.cancel_animation()
                    chip_pill_ref.set_pill_rect(QRectF(target_geom))
                return False

        self._chip_rail_resize_filter = _RailResizeFilter(rail)
        rail.installEventFilter(self._chip_rail_resize_filter)

        layout = QHBoxLayout(rail)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(4)

        # Left phantom: invisible spacer whose width mirrors the right
        # utility cluster (divider + hint + optional overflow). Without
        # this counterbalance, the two addStretch() items around the chips
        # only center them in the rail width minus the utility cluster —
        # which appears visibly off-center. QSpacerItem (not QWidget) so
        # there's nothing to paint. Sized in _update_chip_rail_phantom_width
        # after the utility widgets exist.
        self.chip_rail_left_phantom = QSpacerItem(
            0, 0, QSizePolicy.Fixed, QSizePolicy.Minimum
        )
        layout.addSpacerItem(self.chip_rail_left_phantom)

        self.chip_buttons = []
        nav_items = [
            ("Multitoon", 0),
            ("Launcher",  1),
            ("Keysets",   2),
            ("Settings",  3),
        ]
        # 10pt explicitly so chips fit in CHIP_RAIL_H without Qt clipping the
        # label. Inheriting the global 12pt makes chip sizeHint ~63px, which
        # the chip rail's minimum cannot accommodate under window pressure —
        # the result is icon-only chips, which the design rejects.
        # QApplication.font() (not self.font()) so tests that build via
        # __new__ — bypassing QMainWindow.__init__ — still work.
        chip_font = QApplication.font()
        chip_font.setPointSize(10)
        from utils.widgets.chip_button import ChipButton
        layout.addStretch()
        for label, idx in nav_items:
            chip = ChipButton()
            chip.setObjectName(f"chip_{label.lower()}")
            chip.setText(label)
            chip.setFont(chip_font)
            chip.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            chip.setIconSize(QSize(22, 22))
            chip.setCheckable(True)
            chip.setMinimumWidth(60)
            # StrongFocus so mouse clicks transfer keyboard focus to the
            # clicked chip. QToolButton defaults to TabFocus (Tab-only),
            # which leaves focus stranded on whichever chip Qt assigned
            # initial focus to — and the QSS `:focus` rule then paints a
            # stale focus ring on a now-unselected chip.
            chip.setFocusPolicy(Qt.StrongFocus)
            chip.clicked.connect(lambda _checked, i=idx: self.nav_select(i))
            # Hover and press animations are handled by ChipButton itself
            # (paint_scale state machine driven by enterEvent/leaveEvent and
            # the pressed/released signals). No external wiring needed.
            layout.addWidget(chip)
            self.chip_buttons.append(chip)

        layout.addStretch()

        # Overflow menu — visible only when debug logging is enabled.
        # Uses a custom OverflowPopup (replaces Qt's QMenu so we can
        # animate the open/close).
        from utils.widgets.overflow_popup import OverflowPopup
        self.overflow_btn = QToolButton(rail)
        self.overflow_btn.setObjectName("rail_overflow")
        self.overflow_btn.setText("⋯")
        self.overflow_btn.setFixedSize(34, 34)
        self.overflow_btn.setToolTip("More")
        self.overflow_btn.setVisible(self.settings_manager.get("show_debug_tab", False))

        self.overflow_popup = OverflowPopup()
        self.overflow_popup.add_action("View Logs", lambda: self.nav_select(4))

        def _toggle_popup():
            from utils.motion import pop_menu
            if self.overflow_popup.isVisible():
                pop_menu(self.overflow_popup, self.overflow_btn, show=False)
            else:
                pop_menu(self.overflow_popup, self.overflow_btn, show=True)
        self.overflow_btn.clicked.connect(_toggle_popup)
        layout.addWidget(self.overflow_btn)

        # Phantom width matches the now-built utility cluster.
        self._update_chip_rail_phantom_width()

        return rail

    def _update_chip_rail_phantom_width(self):
        """Size the left phantom spacer to match the visible right utility
        cluster (only the debug-gated overflow menu now — the hint button
        moved to the header), so the four chips sit at the geometric center
        of the chip rail. Called at build time and whenever overflow
        visibility changes (debug toggle). Reads show_debug_tab directly
        rather than isVisible() because the widget may not yet be shown
        when this runs at construction time."""
        if not hasattr(self, "chip_rail_left_phantom"):
            return
        # Right utility cluster is empty unless debug is on; in that case
        # only the overflow button (34 px) plus its 4 px leading spacing.
        if self.settings_manager.get("show_debug_tab", False):
            width = 4 + 34
        else:
            width = 0
        self.chip_rail_left_phantom.changeSize(
            width, 0, QSizePolicy.Fixed, QSizePolicy.Minimum
        )
        if hasattr(self, "chip_rail"):
            self.chip_rail.layout().invalidate()

    def nav_select_credits(self):
        """Navigate to the Credits tab with a vertical push-slide.

        The brand lives in the header (not the chip rail), so its
        transition deliberately uses vertical motion to feel distinct
        from chip nav. Credits enters from above (modal-motion principle:
        animate from the trigger source).
        """
        prev_index = self.stack.currentIndex()
        if prev_index == 5:
            return
        was_initialized = getattr(self, "_initialized_nav", False)
        self._initialized_nav = True

        if not was_initialized:
            self.stack.setCurrentIndex(5)
        else:
            from utils.motion import push_slide_pages
            push_slide_pages(self.stack, prev_index, 5, axis="v")

        for chip in self.chip_buttons:
            chip.setChecked(False)
        self._apply_chip_styles()

    def nav_select(self, index: int):
        if self.stack.currentIndex() == index and getattr(self, "_initialized_nav", False):
            return
        was_initialized = getattr(self, "_initialized_nav", False)
        prev_index = self.stack.currentIndex()
        self._initialized_nav = True

        # First-time nav (during init): snap, no animation.
        if not was_initialized:
            self.stack.setCurrentIndex(index)
        else:
            from utils.motion import push_slide_pages
            push_slide_pages(self.stack, prev_index, index, axis="h")

        for i, chip in enumerate(self.chip_buttons):
            chip.setChecked(i == index)
        self._apply_chip_styles()

        # Slide the pill to the new chip's geometry (in rail coordinates).
        # Skip on the first call: chip geometries aren't yet computed at this
        # point in __init__, and the chip rail's resize event filter places
        # the pill correctly on first layout activation.
        if (
            was_initialized
            and 0 <= index < len(self.chip_buttons)
            and hasattr(self, "chip_pill")
        ):
            target = self.chip_buttons[index].geometry()
            self.chip_pill.slide_to(QRectF(target))

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
        #
        # Mode-switch guard: if the customization overlay is open, defer or
        # abandon the swap based on whether the draft is dirty.
        overlay = self.customization_overlay
        if overlay is not None and overlay.isVisible():
            if overlay._is_dirty():
                # Defer: remember the requested target, surface the confirm
                # prompt. discard_clicked resumes the swap; keep_clicked
                # abandons it.
                self._pending_mode_swap = target
                try:
                    overlay._confirm_prompt.discard_clicked.disconnect(
                        self._resume_pending_mode_swap
                    )
                except (RuntimeError, TypeError):
                    pass  # not connected yet, fine
                overlay._confirm_prompt.discard_clicked.connect(
                    self._resume_pending_mode_swap
                )
                overlay._show_confirm_prompt()
                return
            # Clean draft: close immediately, then fall through to swap.
            overlay.close_and_discard()

        self._layout_mode = target
        self.multitoon_tab.set_layout_mode(target)
        if hasattr(self, "launch_tab") and self.launch_tab is not None:
            self.launch_tab.set_layout_mode(target)

    def _resume_pending_mode_swap(self) -> None:
        target = getattr(self, "_pending_mode_swap", None)
        if target is None:
            return
        self._pending_mode_swap = None
        self._layout_mode = target
        self.multitoon_tab.set_layout_mode(target)
        if hasattr(self, "launch_tab") and self.launch_tab is not None:
            self.launch_tab.set_layout_mode(target)

    def open_customization(self, slot: int) -> None:
        """Open the customization overlay for the given slot. Lazy-
        constructs the overlay on first call; subsequent calls reuse
        the same instance. Returns immediately (no-op) if the overlay
        is already visible."""
        from utils.widgets.customization_overlay import ToonCustomizationOverlay

        if (
            self.customization_overlay is not None
            and self.customization_overlay.isVisible()
        ):
            return

        tab = self.multitoon_tab
        if slot < 0 or slot >= len(tab.slot_badges):
            return
        badge = tab.slot_badges[slot]
        toon_name = badge.toon_name
        game = badge.game
        if not toon_name or game not in ("cc", "ttr"):
            return

        from utils import cc_race_assets
        auto_stem = (
            cc_race_assets.asset_stem_for_species(badge.cc_auto_species)
            if game == "cc" else None
        )
        skin = badge.cc_skin if game == "cc" else None

        if self.customization_overlay is None:
            self.customization_overlay = ToonCustomizationOverlay(
                self.centralWidget()
            )
            self.customization_overlay.customization_changed.connect(
                tab._on_customization_saved
            )

        self.customization_overlay.open_for(
            slot=slot, game=game, toon_name=toon_name,
            manager=tab.customizations,
            dna=badge._dna, skin_color=skin, auto_stem=auto_stem,
        )

    def _apply_chip_styles(self):
        """Apply theme-aware QSS + icon rendering to the chip rail's nav chips.

        Selection is rendered entirely by the PillIndicator (a hollow accent
        border that slides between chips on nav change). The chips themselves
        are transparent buttons — they only carry hover-tint feedback and an
        icon/text color tweak for the selected one.
        """
        c = self._theme_colors()
        icon_factories = [
            make_nav_gamepad, make_nav_power,
            make_nav_keyboard, make_nav_gear,
        ]
        # Update the pill border color from the current theme accent.
        if hasattr(self, "chip_pill"):
            self.chip_pill.set_colors(c['header_accent'])
        # Fixed icon size for ALL chips. Selection is indicated by:
        #   - the PillIndicator (animated border around the selected chip)
        #   - icon color (accent for selected, muted for default)
        #   - text color (sidebar_text_sel vs sidebar_text)
        # Animated hover/press scaling is uniform across the whole chip and
        # is owned by ChipButton.paint_scale — so the icon size must stay
        # constant or the per-frame iconSize change fights the paint_scale
        # animation.
        ICON_SIZE = 22
        for i, chip in enumerate(self.chip_buttons):
            is_sel = chip.isChecked()
            chip.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            color = QColor(c['header_accent'] if is_sel else c['sidebar_text'])
            if i < len(icon_factories):
                chip.setIcon(icon_factories[i](ICON_SIZE + 4, color))
            text_color = c['sidebar_text_sel'] if is_sel else c['sidebar_text']
            chip.setStyleSheet(f"""
                QToolButton#{chip.objectName()} {{
                    background: transparent;
                    color: {text_color};
                    border: 1px solid transparent;
                    border-radius: 8px;
                    font-size: 10pt;
                    padding: 4px 10px;
                }}
                QToolButton#{chip.objectName()}:hover {{
                    background: {c['sidebar_btn_sel']};
                }}
                QToolButton#{chip.objectName()}:focus {{
                    outline: none;
                }}
            """)

    # ── Theme ──────────────────────────────────────────────────────────────

    def _theme_colors(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

    def _set_header_title(self, tc: str, vc: str) -> None:
        """Render the header title label with the app name and an inline
        accent-colored version string. Extracted so tests can exercise the
        title-build path without wiring up the full theme machinery."""
        self.title_label.setText(
            f'<span style="color:{tc}">{app_name()}</span>'
            f' <span style="color:{vc}; font-size:{font_role("label")}px; '
            f'font-weight:bold;">v{APP_VERSION}</span>'
        )

    def _refresh_header_session_status(self):
        """Update the header's right-aligned status label from the live
        multitoon state. Called from __init__ once and re-fired on
        service start/stop and enabled-toon changes."""
        if not hasattr(self, "header_session_status"):
            return
        running = getattr(self.multitoon_tab, "service_running", False)
        enabled = getattr(self.multitoon_tab, "enabled_toons", [False] * 4)
        active = sum(1 for e in enabled if e)
        prefix = "Running" if running else "Idle"
        self.header_session_status.setText(
            f"{prefix}  •  {active}/4 toons active"
        )

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
        self._set_header_title(tc, vc)
        if hasattr(self, "header_session_status"):
            self.header_session_status.setStyleSheet(
                f"font-size: {font_role('label')}px; color: {c['text_muted']}; "
                f"background: transparent; padding-right: 12px;"
            )
        # Accent stripe
        accent = self.header.findChild(QFrame, "header_accent")
        if accent:
            accent.setStyleSheet(f"""
                background: {c['header_accent']};
                border-radius: 2px;
            """)

        # Chip rail
        self.chip_rail.setStyleSheet(f"""
            QFrame#app_chip_rail {{
                background: {c['sidebar_bg']};
                border-bottom: 1px solid {c['sidebar_border']};
            }}
        """)
        self.update_banner.apply_theme(c)
        self._apply_chip_styles()
        if hasattr(self, "overflow_popup"):
            self.overflow_popup.set_theme_colors(
                bg_hex=c['bg_card'],
                border_hex=c['header_accent'],
            )
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

    @Slot(str)
    def _on_system_color_scheme_changed(self, _value: str):
        # Re-theme only when the user has chosen "system"; explicit "light"
        # or "dark" should not get overwritten by an OS toggle.
        if self.settings_manager.get("theme", "system") == "system":
            self.on_theme_changed()

    def on_input_backend_changed(self):
        # Note: get_chat_block_list (wired in __init__) is preserved here
        # because stop_service/start_service reuses the same InputService
        # instance — they only toggle its event loop. If toggle_service ever
        # constructs a new InputService, the late-bind injection in __init__
        # would need to be repeated here.
        if self.multitoon_tab.service_running:
            self.multitoon_tab.stop_service()
            self.multitoon_tab.start_service()
            self.log("[Service] Restarted due to input backend change.")

    def toggle_debug_tab_visibility(self, show: bool):
        self.debug_tab.logging_enabled = show
        self.multitoon_tab.input_service.logging_enabled = show
        self.overflow_btn.setVisible(show)
        # Right utility cluster width changed — re-mirror it on the left
        # phantom so chips stay geometrically centered.
        self._update_chip_rail_phantom_width()
        ttr_api.set_debug(show)
        if not show and self.stack.currentIndex() == 4:
            self.nav_select(0)

    def on_clear_credentials_requested(self):
        self.launch_tab.clear_all_credentials()
        self.log("[Credentials] All stored credentials have been cleared from Keyring and session memory.")

    @Slot()
    def _on_keep_alive_help_requested(self):
        """User clicked 'Go to Settings' in the Keep-Alive help popover.
        Navigate to the Settings tab and highlight the Keep-Alive group."""
        self.nav_select(3)  # Settings tab index — see stack widget order in __init__
        self.settings_tab.highlight_keep_alive_group()

    # ── TTR settings ──────────────────────────────────────────────────────────

    def _apply_startup_ttr_keymap(self) -> int:
        """At startup, populate keymap set 0 from TTR's settings.json. If
        the live read fails (TTR mid-update, engine dir moved, etc.), fall
        back to the last_detected_keymap cache stored on the previous
        successful run.

        Returns the number of control fields applied (0 if neither source
        produced any), so callers / tests can verify *something* happened.
        """
        from utils.ttr_settings import apply_ttr_controls_to_set

        live = self._refresh_ttr_settings()
        if live is not None:
            n = apply_ttr_controls_to_set(self.keymap_manager, 0, live.controls)
            self.settings_manager.set("last_detected_keymap", live.controls)
            print(f"[main] TTR settings auto-detected from {live.source_path} ({n} controls)")
            return n

        cached = self.settings_manager.get("last_detected_keymap", None)
        if isinstance(cached, dict) and cached:
            n = apply_ttr_controls_to_set(self.keymap_manager, 0, cached)
            print(f"[main] TTR settings.json unreadable; applied cached keymap ({n} controls)")
            return n

        return 0

    def _refresh_ttr_settings(self):
        """Locate and parse TTR's settings.json. Returns TtrSettings or None.

        Used at startup (apply controls + persist cache) and as the source
        for the chat-aware key-block list. Per-call so settings.json edits
        made while TTMT is open are honored on the next key event.

        Mirrors the engine-dir fallback chain used by the manual 'Detect'
        button in keymap_tab: stored ttr_engine_dir first, then
        find_engine_path() so a Linux native install with no stored dir
        still auto-detects."""
        from utils.ttr_settings import locate_settings_file, parse_ttr_settings
        from services.ttr_login_service import find_engine_path
        engine_dir = self.settings_manager.get("ttr_engine_dir", "") or None
        if not engine_dir:
            engine_dir = find_engine_path() or None
        path = locate_settings_file(engine_dir=engine_dir)
        if not path:
            return None
        try:
            return parse_ttr_settings(path)
        except Exception as e:
            print(f"[main] TTR settings parse failed: {e}")
            return None

    # ── Profiles ────────────────────────────────────────────────────────────

    @Slot(int)
    def load_profile_slot(self, index: int):
        self.multitoon_tab.load_profile(index)
        self.settings_manager.set("active_profile", index)
        self.log(f"[Profile] Loaded profile {index + 1}")

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def shutdown(self):
        # DIAG: this print stays in until we have confirmation from a real
        # AppImage run that the close-path is actually reached and each
        # sub-shutdown returns. Per docs/handoff-appimage-icon-and-close-leak-bug.md
        # the open question is which (if any) of these calls hangs on close.
        # Output goes to AppImage stderr (visible from terminal launch) and
        # to ~/.cache/toontown-multitool/faulthandler.log via main.py:11.
        print(f"[shutdown] entered pid={os.getpid()} complete={getattr(self, '_shutdown_complete', False)}")
        if getattr(self, "_shutdown_complete", False):
            return
        self._shutdown_complete = True
        # Each shutdown call is wrapped independently so a failure in one
        # (e.g. pynput's listener.stop() racing its own initialization)
        # does not prevent the others from running. Skipping
        # window_manager.stop() leaves its poll thread alive and locks
        # the terminal.
        #
        # The `getattr(self, obj_name, None)` guard is defensive against the
        # dual call-site introduced by `_wire_app_lifecycle`: shutdown can
        # fire from either `closeEvent` (normal user close) or `aboutToQuit`
        # (e.g. signal-handled exit), and in the rare case that __init__ is
        # still partway through when aboutToQuit fires, half-constructed
        # attributes may be missing. Don't strip this guard under the
        # "no defensive bloat" rule.
        for label, obj_name, method_name in (
            ("hotkey_manager", "hotkey_manager", "stop"),
            ("launch_tab", "launch_tab", "shutdown"),
            ("multitoon_tab", "multitoon_tab", "shutdown"),
            ("window_manager", "window_manager", "stop"),
        ):
            print(f"[shutdown] -> {label}.{method_name}()")
            try:
                obj = getattr(self, obj_name, None)
                if obj is None:
                    print(f"[shutdown]    skipped: {obj_name} not set yet")
                    continue
                fn = getattr(obj, method_name)
                fn()
                print(f"[shutdown]    {label}.{method_name}() returned")
            except Exception as e:
                print(f"[CloseEvent] {label} shutdown error: {e}")
        try:
            if hasattr(self, "update_checker"):
                print("[shutdown] -> update_checker.shutdown()")
                self.update_checker.shutdown()
                print("[shutdown]    update_checker.shutdown() returned")
        except Exception as e:
            print(f"[Main] update_checker shutdown error: {e}")
        print(f"[shutdown] complete pid={os.getpid()}")

    def closeEvent(self, event):
        # DIAG: see comment in shutdown(). Confirms whether closeEvent itself
        # is reached on AppImage close (the highest-value open question per
        # the handoff doc).
        print(f"[closeEvent] entered pid={os.getpid()}")
        self.shutdown()
        super().closeEvent(event)
        print(f"[closeEvent] super returned, accepted={event.isAccepted()}")
        if event.isAccepted():
            _quit_app_after_main_window_close()
        print(f"[closeEvent] exiting pid={os.getpid()}")

    def log(self, message: str):
        if not self.debug_tab.logging_enabled:
            return
        print(message)
        self.debug_tab.append_log(message)


def _assets_dir() -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets")


def _resolve_icon_path() -> str:
    # Disk fallback used when theme lookup misses or is intentionally skipped
    # (e.g. Windows, dev runs, AppImage).
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    filename = "ToonTownMultiTool-beta.png" if is_beta() else "ToonTownMultiTool.ico"
    return os.path.join(base, "assets", filename)


def _resolve_app_icon() -> QIcon:
    # Theme lookup is used by AUR, .deb, and Flatpak installs, all of which
    # register their own (current) icon files in the XDG icon theme at
    # install time, so QIcon.fromTheme() returns the right icon for that
    # install. Skipped for:
    #   - Windows: no XDG theme system; fromTheme returns null.
    #   - Dev-from-source: a coexisting packaged install of ourselves may
    #     have registered an older icon under the same id, which would
    #     shadow the bundled new one.
    #   - AppImage: portable bundle; even if the system theme has an entry
    #     from a prior AUR/Flatpak/.deb install on the same machine, that
    #     entry may be stale (different version, removed package, etc).
    #     The bundled icon inside the AppImage is the authoritative one.
    if _is_packaged_install() and not _is_appimage_install():
        theme_id = BETA_DESKTOP_ID if is_beta() else APP_DESKTOP_ID
        themed = QIcon.fromTheme(theme_id)
        if not themed.isNull():
            return themed
    return QIcon(_resolve_icon_path())


def _quit_app_after_main_window_close() -> None:
    # DIAG: see shutdown() comment. This print confirms whether the close
    # path actually reaches app.quit(), which is the prerequisite for
    # aboutToQuit firing.
    app = QApplication.instance()
    print(f"[quit_after_close] app_instance={app is not None}")
    if app is not None:
        app.quit()
        print("[quit_after_close] app.quit() called")


def _wire_app_lifecycle(app: QApplication, window: MultiToonTool) -> None:
    app.aboutToQuit.connect(window.shutdown)


def _platform_only_modules(platform: str) -> set[str]:
    """Modules whose top-level body imports a platform-specific library and
    therefore cannot be imported on every interpreter. `platform` is a
    `sys.platform` string ("win32", "linux", "darwin"). The normal launch
    path only touches these behind a `sys.platform` gate, but the
    `--self-check` import sweep imports everything and must skip the ones
    that would raise here."""
    excluded: set[str] = set()
    if platform != "win32":
        # utils.win32_backend imports pywin32.
        excluded.add("utils.win32_backend")
    if platform != "linux":
        # utils.kwallet_jeepney raises ImportError on non-Linux at import time.
        excluded.add("utils.kwallet_jeepney")
        # utils.xlib_backend does an unguarded top-level `from Xlib import`;
        # Xlib is not bundled on non-Linux builds.
        excluded.add("utils.xlib_backend")
    return excluded


def _import_all_modules() -> None:
    """Import every module under tabs/, services/, utils/ so a syntax or
    import-time error on the running interpreter surfaces immediately.

    Recurses explicitly (iter_modules + manual descent) rather than via
    walk_packages: walk_packages silently swallows ImportErrors raised while
    importing a package to recurse into it, and tabs/ + services/ are
    namespace packages — explicit recursion guarantees every submodule is
    reached regardless of __init__.py re-exports.
    """
    import importlib
    import pkgutil

    platform_only = _platform_only_modules(sys.platform)

    def import_package(package_name: str) -> None:
        package = importlib.import_module(package_name)
        package_path = getattr(package, "__path__", None)
        if package_path is None:
            return
        for module_info in pkgutil.iter_modules(package_path):
            full_name = f"{package_name}.{module_info.name}"
            if full_name in platform_only:
                continue
            if module_info.ispkg:
                import_package(full_name)
            else:
                importlib.import_module(full_name)

    for top_level in ("tabs", "services", "utils"):
        import_package(top_level)


def _run_self_check() -> int:
    """Headless startup oracle. Imports everything, builds the main window,
    pumps the event loop briefly, and reports success/failure via exit code.
    CI runs this under xvfb with the real xcb platform."""
    try:
        _import_all_modules()
        QApplication.setApplicationName(app_name())
        QApplication.setOrganizationName("flossbud")
        app = QApplication(sys.argv)
        settings = SettingsManager()
        apply_theme(app, resolve_theme(settings))
        window = MultiToonTool()
        app.processEvents()
        window.close()
        sys.stdout.write("self-check OK\n")
        return 0
    except Exception:
        import traceback

        traceback.print_exc()
        return 1


def _run_self_check_keyring() -> int:
    """Keyring backend oracle. Resolves the active `keyring` backend, asserts
    it is a functional Secret Service backend (not the null/fail backend), and
    performs a store->retrieve->delete roundtrip. CI runs this under
    dbus-run-session with gnome-keyring-daemon. KWallet is intentionally not
    covered here -- it stays a manual smoke-test item."""
    try:
        import keyring
        from keyring.backends import SecretService

        backend = keyring.get_keyring()
        sys.stdout.write(f"keyring backend: {type(backend).__module__}.{type(backend).__name__}\n")
        if not isinstance(backend, SecretService.Keyring):
            sys.stderr.write(
                "self-check-keyring FAIL: active backend is not Secret Service\n"
            )
            return 1

        service = "ttmt-self-check"
        username = "probe"
        secret = "roundtrip-value"
        keyring.set_password(service, username, secret)
        try:
            got = keyring.get_password(service, username)
        finally:
            keyring.delete_password(service, username)
        if got != secret:
            sys.stderr.write(
                f"self-check-keyring FAIL: roundtrip mismatch (got {got!r})\n"
            )
            return 1

        sys.stdout.write("self-check-keyring OK\n")
        return 0
    except Exception:
        import traceback

        traceback.print_exc()
        return 1


def _should_prompt_for_cc_install(
    installs, stored_signature: str, stored_set_hash: str
) -> bool:
    """Return True when the boot prompt should fire.

    Fires when there are multiple installs AND any of:
      - no stored signature
      - stored signature doesn't match any discovered install
      - the install set has changed since last seen (catches "user installed
        a new launcher while we already had a satisfying pick")

    A missing ``stored_set_hash`` (empty string) is treated as a hash
    mismatch so users upgrading from a TTMT build without this feature
    see the picker once on their first boot in multi-install state.
    """
    if len(installs) <= 1:
        return False
    from services.wine_runtimes import install_signature, install_set_hash
    if not stored_signature:
        return True
    if not any(install_signature(i) == stored_signature for i in installs):
        return True
    if stored_set_hash != install_set_hash(installs):
        return True
    return False


def _lock_cc_prefs_silently():
    """Auto-write CC's preferences.json to lock movement to WASD.

    CC's default keymap accepts both WASD and arrow keys for movement,
    which breaks per-toon keyset assignments (the focused window catches
    both keysets natively). Locking CC to WASD lets TTMT route the other
    keyset's keys via the wine bridge without focused-window cross-talk.

    Silent: no UI, no toast. The backup at preferences.json.ttmt-backup
    preserves the original prefs for recovery; the writer is idempotent
    so this is safe to call on every startup.
    """
    try:
        from services.wine_runtimes import discover_cc_installs
        from utils import cc_settings, cc_isolation
        installs = discover_cc_installs()
        if not installs:
            return
        results = cc_settings.write_canonical_to_all_installs(
            installs, cc_isolation.DEFAULT_CANONICAL
        )
        failed = [r.error for r in results if not r.ok and r.error]
        if failed:
            print(f"[main] CC prefs auto-lock partial failure: {failed}")
    except Exception as e:
        print(f"[main] CC prefs auto-lock skipped: {e}")


def _maybe_prompt_for_cc_install(main_window, settings_manager):
    """Show the picker on boot when multiple CC installs are ambiguous.

    Records the current install-set hash at the end (whether or not the
    prompt fired or the user picked) so the next boot can detect "the set
    has changed" by comparing the freshly-computed hash against the stored
    one. Idempotent when the set is unchanged.
    """
    from services.wine_runtimes import (
        discover_cc_installs, install_signature, install_set_hash,
    )
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    from utils.settings_keys import (
        CC_ENGINE_INSTALL_SIGNATURE, CC_ENGINE_INSTALL_SET_HASH,
    )

    installs = discover_cc_installs()
    stored = settings_manager.get(CC_ENGINE_INSTALL_SIGNATURE, "")
    stored_set_hash = settings_manager.get(CC_ENGINE_INSTALL_SET_HASH, "")
    current_set_hash = install_set_hash(installs)

    if _should_prompt_for_cc_install(installs, stored, stored_set_hash):
        dlg = CCInstallPickerDialog(
            installs, parent=main_window, active_signature=stored or None,
        )
        if dlg.exec() == dlg.DialogCode.Accepted:
            picked = dlg.selected_install()
            if picked is not None:
                settings_manager.set("cc_engine_dir", os.path.dirname(picked.exe_path))
                settings_manager.set(CC_ENGINE_INSTALL_SIGNATURE, install_signature(picked))
                settings_manager.set("cc_engine_dir_approved_custom_dir", "")
                # Refresh the open SettingsTab's CC panel so the chip/path text reflect
                # the freshly-picked install. Without this the panel displays the
                # construction-time state until the user navigates elsewhere.
                settings_tab = getattr(main_window, "settings_tab", None)
                if settings_tab is not None and hasattr(settings_tab, "apply_picked_install"):
                    try:
                        settings_tab.apply_picked_install(picked)
                    except Exception as e:
                        from utils.credentials_manager import _dbg
                        _dbg(f"[CC] boot-pick refresh failed: {e}")

    # Record the current install-set hash so subsequent boots can detect
    # changes. Written even when no prompt fired so the hash always
    # reflects the most-recently-observed set.
    if current_set_hash != stored_set_hash:
        settings_manager.set(CC_ENGINE_INSTALL_SET_HASH, current_set_hash)


if __name__ == "__main__":
    if "--self-check-keyring" in sys.argv:
        sys.exit(_run_self_check_keyring())

    if "--self-check" in sys.argv:
        sys.exit(_run_self_check())

    if "--apply-installer-config" in sys.argv:
        # Invoked by the Windows Inno Setup installer's [Run] section to
        # persist the user's wizard choices into settings.json. Runs headless,
        # exits before any Qt or service initialization.
        def _flag(name: str, default: bool = False) -> bool:
            for arg in sys.argv:
                if arg.startswith(f"--{name}="):
                    return arg.split("=", 1)[1].lower() in ("1", "true")
            return default

        from utils.build_flavor import config_dir as _config_dir
        from utils.installer_merge import merge_installer_config
        target = os.path.join(_config_dir(), "settings.json")
        ok = merge_installer_config(
            target,
            check_updates=_flag("check-updates", default=True),
            keep_alive=_flag("keep-alive", default=False),
        )
        sys.exit(0 if ok else 1)

    # Identity must be set BEFORE QApplication is constructed; Qt reads these
    # at construction time to populate X11 WM_CLASS and Wayland app_id.
    # Without them Qt falls back to argv[0] ("python3" inside the Flatpak)
    # and KDE/GNOME show an orphan taskbar entry with a generic icon.
    QApplication.setApplicationName(app_name())
    QApplication.setApplicationDisplayName(app_name())
    QApplication.setOrganizationName("flossbud")
    desktop_file_name = _select_desktop_file_name()
    if desktop_file_name is not None:
        QGuiApplication.setDesktopFileName(desktop_file_name)
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
    _wire_app_lifecycle(app, window)
    window.show()
    _lock_cc_prefs_silently()
    # Fire the multi-install picker on a 0-delay timer so Qt has finished
    # processing the show event before any modal dialog steals focus.
    QTimer.singleShot(0, lambda: _maybe_prompt_for_cc_install(window, window.settings_manager))
    sys.exit(app.exec())
