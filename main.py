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
from utils.platform_qt import qt_platform_for
_qt_plat = qt_platform_for(
    sys.platform,
    os.getenv("XDG_SESSION_TYPE", "").lower(),
    os.getenv("TTMT_USE_WAYLAND") == "1",
)
if _qt_plat is not None:
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
    # macOS returns None from qt_platform_for — Qt defaults to cocoa.
    os.environ.setdefault("QT_QPA_PLATFORM", _qt_plat)
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
from PySide6.QtCore import QRect, Qt, QSize, QEvent, Signal, Slot, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QIcon

# === Internal Imports ===
from tabs.multitoon_tab import MultitoonTab
from tabs.launch_tab import LaunchTab
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
    apply_theme, resolve_theme, get_theme_colors,
    make_hint_icon, font_role,
    SystemThemeWatcher,
)
from utils.build_flavor import window_title, app_name, is_beta
from utils import perf_trace
from utils.window_corner_state import corner_state_signature, should_skip_restyle

# A/B experiment (spec Phase 2): on macOS, run the frameless window OPAQUE with a
# rounded mask instead of WA_TranslucentBackground, to isolate translucent-
# compositing cost. Chosen at startup (translucency cannot be toggled live).
_OPAQUE_MASK_CHROME = (
    sys.platform == "darwin" and os.environ.get("TTMT_OPAQUE_MASK_CHROME") == "1"
)
from utils.widgets.window_chrome_style import (
    RADIUS_NORMAL, RADIUS_MAXIMIZED, BOTTOM_INSET, STROKE_INSET,
    window_edge_colors, card_qss, header_top_radius_qss,
)


# Layout-mode breakpoint and hysteresis. Window must be >= W_FULL x H_FULL
# (plus deadband on the way up) to enter Full UI; Compact resumes once either
# dimension drops below (breakpoint - deadband) on the way down.
#
# H_FULL=800 matches the pre-chip-rail trigger threshold so users who used
# to enter Full at ~860 height (1280+80, 800+60) still can. At the trigger,
# content area = 860 - HEADER_H(112) - NAV_BAND_H(60) = 688, which renders
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
# nav band QFrames so the value lives in one place.
HEADER_H = 112
# Nav band height. The glass dock is 58px tall (segment 36 + container pad 6 +
# glow margin 16); the band adds 1px top/bottom so its total is <= the old
# 64px chip rail, which keeps the Full-UI height threshold math (above) valid.
NAV_BAND_H = 60
APP_DESKTOP_ID = "io.github.flossbud.ToonTownMultiTool"
BETA_DESKTOP_ID = "io.github.flossbud.ToonTownMultiTool-beta"
LEGACY_DESKTOP_ID = "toontown-multitool"


def _decide_layout_mode(current: str, width: int, height: int) -> str:
    """Pure state-machine: return the layout mode for the given size, given the
    current mode. Implements deadband hysteresis so a window dragged across the
    breakpoint does not flicker.

    The Multitoon tab now uses a single fluid pinwheel layout and ignores this
    breakpoint (see MultitoonTab.set_layout_mode), but the Launcher and Settings
    tabs still switch compact/full on it, so the breakpoint is retained.
    """
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

        # One-time-per-launch gate for the Keep-Alive sleep warning dialog.
        self._sleep_warning_shown = False

        self.setWindowTitle(window_title())
        # The Multitoon pinwheel needs room for two cards side by side (each a
        # 172px portrait + a 158px control column + padding), so the window is
        # ~880px wide by default and clamps to a 820px minimum - the design
        # reference is 820x840. Height (~862) fits header 112 + nav band 60 +
        # the pinwheel grid + status bar without clipping. Clamp height to the
        # usable screen so small/scaled displays are not over-sized.
        from utils.window_layout import clamp_window_height
        screen = self.screen() or QGuiApplication.primaryScreen()
        avail_h = screen.availableGeometry().height() if screen else 0
        default_h = clamp_window_height(avail_h)
        self.setGeometry(QRect(100, 100, 880, default_h))
        self.setMinimumWidth(820)
        self._layout_mode = "compact"

        self.pressed_keys = set()
        GameRegistry.instance()  # warm up before any launchers
        self.settings_manager = SettingsManager()
        # Hover-hints flag is read by the global tooltip eventFilter, which is
        # installed before the nav band builds — initialize it here so it
        # always exists regardless of where the hint toggle is constructed.
        self._hints_enabled = bool(self.settings_manager.get("hints_enabled", True))
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
        # Bridge resolved in-world toon names to the launching account's
        # recent_toons record (radial-menu last-toon capture).
        self.multitoon_tab.set_toon_capture_sink(self.launch_tab.capture_toon)
        # Share the Multitoon tab's ToonCustomizationsManager so the Launch tab's
        # primary-toon portraits render the saved pose (matching the radial menu).
        self.launch_tab.set_customizations_manager(self.multitoon_tab.customizations)
        self.settings_tab = SettingsTab(
            self.settings_manager,
            keymap_manager=self.keymap_manager,
            credentials_manager=self.launch_tab.cred_manager,
        )
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
        # Chat-open chords for the chat gate FSM (TTMT_CHAT_FSM=1): follow
        # the client's OWN configured chat/groupChat chords. Same liveness
        # rule as the block list; None -> the FSM's stock enter/alt-enter.
        def _chat_open_chords_provider():
            s = self._refresh_ttr_settings()
            if s is None:
                return None
            return s.chat_open_chords
        self.multitoon_tab.input_service.get_chat_open_chords = _chat_open_chords_provider
        ttr_api.set_debug(logging_on)
        self._api_log.connect(self.debug_tab.append_log)
        ttr_api.set_log_callback(self._api_log.emit)
        self.settings_tab.input_backend_changed.connect(self.on_input_backend_changed)
        self.settings_tab.clear_credentials_requested.connect(self.on_clear_credentials_requested)

        # Chat handling mode: SettingsTab selector -> MultitoonTab visibility.
        # The signal carries the canonical mode string.
        self.settings_tab.chat_handling_mode_changed.connect(
            self.multitoon_tab.apply_chat_handling_mode
        )

        # Apply the persisted Chat Handling mode once at startup so the chat
        # buttons reflect the setting on launch. apply_chat_handling_mode
        # normalizes legacy simple/advanced (and unknown) values, so the raw
        # persisted value is safe to pass directly. Fresh installs default to
        # focused_only (buttons hidden).
        from utils.settings_keys import CHAT_HANDLING_MODE, CHAT_HANDLING_MODE_DEFAULT
        initial_mode = self.settings_manager.get(CHAT_HANDLING_MODE, CHAT_HANDLING_MODE_DEFAULT)
        self.multitoon_tab.apply_chat_handling_mode(initial_mode)

        # ── Build layout: header + banner + nav_band + stacked content ────
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        from utils.widgets.update_banner import UpdateBanner
        self.update_banner = UpdateBanner(parent=self)
        self.update_banner.clicked.connect(self._on_update_banner_clicked)
        self.update_banner.dismissed.connect(self._on_update_banner_dismissed)
        self._pending_update_info = None

        from utils.widgets.admin_notice_banner import AdminNoticeBanner
        self.admin_notice_banner = AdminNoticeBanner(parent=self)
        self.admin_notice_banner.restart_as_admin.connect(self._on_admin_notice_restart)
        self.admin_notice_banner.dismissed.connect(self._on_admin_notice_dismissed)

        self.header = self._build_header()
        root.addWidget(self.header)

        # Banner sits between the header and the tab switcher; in normal flow
        # so show/hide reflows the content below down.
        root.addWidget(self.update_banner)
        root.addWidget(self.admin_notice_banner)

        self.nav_band = self._build_nav_band()
        root.addWidget(self.nav_band)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.launch_tab)       # 0
        self.stack.addWidget(self.multitoon_tab)    # 1
        self.stack.addWidget(self.settings_tab)     # 2
        self.stack.addWidget(self.debug_tab)        # 3
        self.stack.addWidget(self.credits_tab)      # 4
        # Portable Settings panel (Task 12): when the Settings spoke floats the
        # real SettingsTab over the overlay it is reparented OUT of this stack;
        # _restore_settings_to_stack re-inserts it at index 2. These track that
        # transient state so restoration is idempotent across every teardown path.
        self._settings_floating = False
        self._settings_container = None
        self._wire_header_icon_active_state()
        root.addWidget(self.stack, 1)

        self.container = QWidget()
        self.container.setLayout(root)
        self.setCentralWidget(self.container)

        self._apply_full_theme()
        self._apply_window_chrome()
        self._refresh_header_session_status()
        # Demo mode (TTMT_DEMO_LAUNCH_TAB) jumps directly to the Launch tab so
        # the visual verification script can capture it without synthesizing
        # clicks through xdotool.
        # Stack order is Launcher(0) / Multitoon(1) / Settings(2); default
        # landing is Multitoon (middle), demo flag opens the Launch tab.
        _initial_tab = 0 if os.environ.get("TTMT_DEMO_LAUNCH_TAB") else 1
        self.nav_select(_initial_tab)
        self._setup_update_checker()
        self._maybe_kick_off_startup_check()
        self._update_hint_icon()

        # Transparent overlay mode: wire backend + controller, then connect the
        # central emblem so clicking/dragging/scrolling it drives mode transitions.
        from utils.overlay.backend import get_overlay_backend
        from utils.overlay import overlay_entry
        self._overlay_backend = get_overlay_backend()
        # The overlay controller borrows the cluster out of the tab and minimizes
        # this main window while transparent. card_provider is the _CompactLayout
        # it borrows from. overlay_entry.controller_class() selects the
        # single-window ClusterOverlayController by default (fixed-envelope
        # transform scaling), or the legacy multi-window OverlayGroupController
        # when TTMT_OVERLAY_SINGLE_WINDOW is set to a falsey token - the two
        # share this constructor signature + caller surface.
        self._mode_controller = overlay_entry.controller_class()(
            self, self._overlay_backend, self.settings_manager,
            card_provider=self.multitoon_tab._compact,
            # Keep the keep-alive bar/glow repaint timers alive (and reconcile the
            # borrowed bars' paint state) while the cluster is up and this window
            # is minimized.
            on_active_changed=self.multitoon_tab.set_overlay_active,
        )
        # Failure dialogs from menu-triggered launches must sit above the overlay.
        # is_active is a @property, so wrap it in a lambda to read it at call time.
        self.launch_tab.set_overlay_active_provider(lambda: self._mode_controller.is_active)
        # Hover-peek: feed click-sync ghost cursor positions into the overlay so a
        # ghost over a card dims it too (mirrors the real pointer). Guarded - the
        # click-sync service is None on platforms without click-sync.
        _click_sync = getattr(self.multitoon_tab, "click_sync_service", None)
        if _click_sync is not None:
            _click_sync.ghost_pointer_event.connect(self._mode_controller.on_ghost_event)
            _click_sync.ghost_clear.connect(self._mode_controller.on_ghost_clear)
        # Glove echo: confined ghost windows stack BELOW the dock-layer cluster,
        # so the cluster paints its own echo of each glove over the visible
        # cards. The ghost controller (single owner of glove visibility) mirrors
        # into the cluster controller's ghost_echo_* sink; the legacy
        # multi-window controller has no sink, so it is simply not wired.
        _ghosts = getattr(self.multitoon_tab, "ghost_cursor_controller", None)
        if _ghosts is not None and hasattr(self._mode_controller, "ghost_echo_shown"):
            _ghosts.set_echo_sink(self._mode_controller)
        emblem = self.multitoon_tab._compact._emblem
        self._windowed_wheel = None
        from utils.overlay.backend import overlay_trace as _overlay_trace
        if self._overlay_backend.is_available():
            _overlay_trace("main: overlay backend AVAILABLE -> emblem interactive + connected")
            emblem.set_interactive(True)
            self._mode_controller.connect_emblem(emblem)
            emblem.menu_requested.connect(self._open_emblem_wheel)
        else:
            _overlay_trace("main: overlay backend UNAVAILABLE -> emblem inert (transparent mode off)")
            emblem.setToolTip("Float UI is not available on this system")

        # Install event filter to globally block tooltips when hints disabled
        QApplication.instance().installEventFilter(self)

        # Global hotkeys (registry + settings driven; spec 2026-07-02).
        from utils.hotkey_actions import (
            ACTIONS, effective_bindings, make_hotkey_hook,
        )
        from utils.hotkey_dispatch import build_dispatch
        from utils.settings_keys import HOTKEY_BINDINGS
        self._hotkey_dispatch = build_dispatch(
            mode_controller=self._mode_controller,
            launch_tab=self.launch_tab,
            multitoon_tab=self.multitoon_tab,
            settings_manager=self.settings_manager,
            load_profile=self.load_profile_slot,
        )
        self._hotkey_hook = make_hotkey_hook(self.settings_manager)
        repeat_ok_ids = frozenset(a.id for a in ACTIONS if a.repeat_ok)

        from services.hotkey_manager import HotkeyManager
        self.hotkey_manager = HotkeyManager(
            self.window_manager,
            self.multitoon_tab.key_event_queue,
            suppress_predicate=self.multitoon_tab.input_service._suppress_predicate,
            hotkey_hook=self._hotkey_hook,
            fire_hotkeys=not sys.platform.startswith("linux"),
            hotkey_repeat_ok=repeat_ok_ids,
            vk_keysym_lookup=self.multitoon_tab.input_service.grabber_keysym_for_vk,
        )
        # Signal bridge: hotkey_triggered is emitted on the pynput listener
        # thread; the queued connection hops to the GUI thread before any
        # dispatch target touches a widget. Connected unconditionally --
        # emission is gated by fire_hotkeys inside the manager.
        self.hotkey_manager.hotkey_triggered.connect(self._on_hotkey_action)
        self.hotkey_manager.start()

        # Global hotkeys provider (X11 per-chord passive grabs / darwin
        # Carbon RegisterEventHotKey).
        self.global_hotkeys = None
        if sys.platform.startswith("linux"):
            from services.global_hotkeys import X11GlobalHotkeys
            provider = X11GlobalHotkeys(repeat_ok_ids=repeat_ok_ids)
            if provider.start():
                provider.action_triggered.connect(self._on_hotkey_action)
                provider.apply_bindings(
                    effective_bindings(self.settings_manager))
                self.settings_manager.on_change(
                    lambda key, _v: provider.apply_bindings(
                        effective_bindings(self.settings_manager))
                    if key == HOTKEY_BINDINGS else None)
                self.global_hotkeys = provider
        elif sys.platform == "darwin":
            from services.global_hotkeys import MacOSCarbonHotkeys
            provider = MacOSCarbonHotkeys(repeat_ok_ids=repeat_ok_ids)
            if provider.start():
                provider.action_triggered.connect(self._on_hotkey_action)
                provider.apply_bindings(
                    effective_bindings(self.settings_manager))
                self.settings_manager.on_change(
                    lambda key, _v: provider.apply_bindings(
                        effective_bindings(self.settings_manager))
                    if key == HOTKEY_BINDINGS else None)
                self.global_hotkeys = provider
                # CP9: the session tap PRECEDES Carbon dispatch, so the tap
                # keeps ONLY what Carbon can never see (suppressed chords,
                # two-key chords) and stops firing everything else - both
                # firing would double-dispatch every visible chord.
                self.hotkey_manager.set_hotkey_provider_armed(True)

        # Hotkeys card: saved accounts for the launch-slot pickers + provider
        # failure badges. The pushes are delayed so the provider's event
        # thread processes the queued apply before the failures() snapshot.
        self.settings_tab.set_hotkey_accounts_provider(
            lambda: self.launch_tab.cred_manager.get_accounts_basic())
        if self.global_hotkeys is not None:
            def _push_hotkey_status():
                try:
                    self.settings_tab.set_hotkey_status(
                        self.global_hotkeys.failures())
                except Exception:
                    pass
            QTimer.singleShot(1000, _push_hotkey_status)   # startup apply
            self.settings_manager.on_change(
                lambda key, _v: QTimer.singleShot(300, _push_hotkey_status)
                if key == HOTKEY_BINDINGS else None)

        # route_all interop: while the persistent keyboard grab is held it
        # preempts the provider's passive grabs, so the router consults the
        # SAME effective bindings and dispatches matches instead of routing.
        # The grabber is created lazily by InputService.start() (first service
        # start), so wiring retries on focus changes until it exists; the
        # window_manager signal fires before any game window can hold focus
        # with an armed route_all grab. Dispatch hops to the GUI thread by
        # re-emitting through the provider's action_triggered signal (Qt
        # signal emission is thread-safe); no provider (non-Linux) means no
        # route_all grabber either, so wiring is skipped entirely.
        self._grabber_hotkeys_wired = False
        self._grabber_wire_error_logged = False

        def _wire_grabber_hotkeys(*_a):
            if self._grabber_hotkeys_wired or self.global_hotkeys is None:
                return
            try:
                grabber = self.multitoon_tab.input_service._key_grabber
                if grabber is None or not hasattr(grabber, "set_hotkey_lookup"):
                    return
                from services.global_hotkeys import make_event_lookup
                # The lookup builds lazily ON the grabber's event thread from
                # the grabber's OWN display (correct X connection discipline)
                # and is invalidated on any bindings change. is_down is the
                # grabber's physical-state check, passed through so two-key
                # chord members match only while their partner key is held.
                state = {"lookup": None}

                def lookup(keycode, kstate, is_down):
                    if state["lookup"] is None:
                        display = getattr(grabber, "_display", None)
                        if display is None:
                            return None
                        state["lookup"] = make_event_lookup(
                            display, self.settings_manager)
                    return state["lookup"](keycode, kstate, is_down)

                self.settings_manager.on_change(
                    lambda key, _v: state.update(lookup=None)
                    if key == HOTKEY_BINDINGS else None)
                provider = self.global_hotkeys
                grabber.set_hotkey_lookup(
                    lookup,
                    lambda action_id: provider.action_triggered.emit(action_id),
                    repeat_ok_ids=repeat_ok_ids)
                self._grabber_hotkeys_wired = True
            except Exception as e:                    # noqa: BLE001
                if not self._grabber_wire_error_logged:
                    self._grabber_wire_error_logged = True
                    print(f"[GlobalHotkeys] route_all interop wiring failed: {e}")

        _wire_grabber_hotkeys()
        if self.global_hotkeys is not None:
            # Belt and suspenders: the seed callback covers a service start
            # while a game is already focused (route_all can arm before any
            # focus change); the signal covers everything else.
            input_service = getattr(self.multitoon_tab, "input_service", None)
            if input_service is not None:
                input_service.grabber_created_callback = _wire_grabber_hotkeys
            self.window_manager.active_window_changed.connect(
                _wire_grabber_hotkeys)

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
        self.multitoon_tab.keep_alive_inhibit_status.connect(
            self._on_keep_alive_inhibit_status
        )
        self.multitoon_tab.launch_tab_requested.connect(
            lambda: self.nav_select(0)  # Launcher
        )

        self.log(f"[Debug] {app_name()} launched.")
        # The Multitoon tab uses a single fluid pinwheel layout now; there is
        # no separate full layout to warm.
        self._maybe_show_admin_notice()

    def _maybe_enter_float_mode_at_startup(self) -> bool:
        """Enter Float UI once at startup if the user opted in and it is supported.

        Returns True only if it actually entered. No-op (returns False) when the
        setting is off, the overlay backend is unavailable (non-X11 / no Shape
        extension), or the controller is already active. Fully guarded: a startup
        convenience must never block app launch, so any error falls through to
        False.

        Crash-loop breaker: a sentinel is persisted to disk just before the enter
        and cleared right after it returns. A launch that finds the sentinel still
        set means the previous startup enter never returned (hard crash/hang), so
        Float UI is skipped that launch and a one-time notice is armed."""
        from utils.settings_keys import (
            START_IN_FLOAT_UI_MODE, FLOAT_UI_STARTUP_PENDING,
        )
        try:
            if not self.settings_manager.get(START_IN_FLOAT_UI_MODE, False):
                return False
            controller = getattr(self, "_mode_controller", None)
            backend = getattr(self, "_overlay_backend", None)
            if controller is None or backend is None or not backend.is_available():
                return False
            if controller.is_active:
                return False
            if self.settings_manager.get(FLOAT_UI_STARTUP_PENDING, False):
                # Previous auto-enter never cleared this: it crashed/hung. Skip
                # Float UI this launch, clear the flag, and arm the notice.
                self.settings_manager.set(FLOAT_UI_STARTUP_PENDING, False)
                self._float_startup_recovered = True
                return False
            # Persisted to disk now, so a crash inside enter() leaves it set.
            self.settings_manager.set(FLOAT_UI_STARTUP_PENDING, True)
            try:
                return bool(controller.enter())
            finally:
                # Runs on success AND on a (caught) Python exception, but NOT on a
                # hard crash - which is exactly the case the breaker must catch.
                self.settings_manager.set(FLOAT_UI_STARTUP_PENDING, False)
        except Exception:
            try:
                self.settings_manager.set(FLOAT_UI_STARTUP_PENDING, False)
            except Exception:
                pass
            return False

    def _maybe_notify_float_startup_recovered(self) -> None:
        """Show a one-time, non-blocking notice when the crash-loop breaker tripped
        this launch (Float UI was skipped after a prior unclean auto-enter)."""
        if not getattr(self, "_float_startup_recovered", False):
            return
        self._float_startup_recovered = False
        try:
            from PySide6.QtWidgets import QMessageBox
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Information)
            box.setWindowTitle("Float UI")
            box.setText(
                "Float UI didn't start cleanly last time, so the app opened in "
                "the normal window. You can turn 'Start in Float UI mode' back on "
                "in Settings."
            )
            box.setStandardButtons(QMessageBox.Ok)
            box.setWindowModality(Qt.NonModal)
            box.show()
        except Exception:
            pass

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

    # ── Hint Toggle ──────────────────────────────────────────────────────

    def _toggle_hints(self):
        self._hints_enabled = not self._hints_enabled
        self.settings_manager.set("hints_enabled", self._hints_enabled)
        self._update_hint_icon()

    def _update_hint_icon(self):
        if not hasattr(self, "hint_btn") or self.hint_btn is None:
            return
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
        # --self-check is a build oracle (does the frozen app import + build the
        # UI?). It must NOT start the update-check QThread / network / keychain
        # work: that thread can block mid-flight (e.g. a frozen app's keychain
        # read) and abort at interpreter teardown (QThread destroyed while
        # running).
        if os.environ.get("TTMT_SELF_CHECK"):
            return
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

    def _maybe_show_admin_notice(self) -> None:
        """Show the Windows 'run as administrator' banner once (until dismissed)
        when not running elevated. No-op off Windows / when already dismissed."""
        import sys
        from utils.win32_integrity import is_running_elevated, should_show_admin_notice
        from utils.settings_keys import WINDOWS_ADMIN_NOTICE_DISMISSED
        sm = self.settings_manager
        dismissed = bool(sm.get(WINDOWS_ADMIN_NOTICE_DISMISSED, False)) if sm is not None else False
        if should_show_admin_notice(sys.platform == "win32", is_running_elevated(), dismissed):
            self.admin_notice_banner.show()

    def _on_admin_notice_restart(self) -> None:
        """Relaunch MultiTool elevated. On UAC cancel (relaunch returns False),
        keep the app running and re-enable the button so the user can retry."""
        from utils import win32_elevation
        sm = self.settings_manager
        self.admin_notice_banner.set_restart_enabled(False)
        ok = win32_elevation.relaunch_elevated(
            flush_settings=getattr(sm, "save", None) if sm is not None else None,
            on_success_shutdown=self._shutdown_and_quit,
        )
        if not ok:
            self.admin_notice_banner.set_restart_enabled(True)

    def _shutdown_and_quit(self) -> None:
        """Route the elevated-relaunch success path through the authoritative
        main-window cleanup, then quit so the elevated instance takes over."""
        try:
            self.shutdown()
        finally:
            from PySide6.QtWidgets import QApplication
            QApplication.quit()

    def _on_admin_notice_dismissed(self) -> None:
        """Persist 'don't show again' for the admin banner and hide it. Independent
        of the proof modal's UIPI_ELEVATION_PROMPT_DISMISSED key."""
        from utils.settings_keys import WINDOWS_ADMIN_NOTICE_DISMISSED
        sm = self.settings_manager
        if sm is not None:
            sm.set(WINDOWS_ADMIN_NOTICE_DISMISSED, True)
        self.admin_notice_banner.hide()

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
        # one place. The wordmark is the Credits entry point (replaces the
        # removed corner app icon): click brings Credits down, click again
        # returns. It lives in the header, so Credits stays reachable in both
        # frameless AND native-title-bar modes.
        from utils.widgets.clickable_logo import ClickableLogo
        self.header_logo = ClickableLogo()
        self.header_logo.setObjectName("header_logo")
        self.header_logo.setAlignment(Qt.AlignCenter)
        self.header_logo.clicked.connect(self._on_app_icon_clicked)
        outer.addWidget(self.header_logo, 0, Qt.AlignCenter)

        outer.addStretch()

        # Render an initial pixmap so the label is non-empty before theming
        # (tests build the header without _apply_full_theme).
        self._refresh_header_logo(header_width=575)

        # Hover-hints toggle, top-left corner (13,13) — symmetric with the
        # window controls top-right. Moved here from the retired chip rail.
        self.hint_btn = QToolButton(header)
        self.hint_btn.setObjectName("hint_toggle")
        self.hint_btn.move(13, 13)
        self.hint_btn.setFixedSize(34, 34)
        self.hint_btn.setIconSize(QSize(20, 20))
        self.hint_btn.setCursor(Qt.PointingHandCursor)
        self.hint_btn.setFocusPolicy(Qt.NoFocus)
        self.hint_btn.clicked.connect(self._toggle_hints)
        self.hint_btn.raise_()

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
        # Keep the corner hints toggle above the logo after any theme/size
        # refresh. Guarded: the build-time call runs before the toggle exists.
        hint_btn = getattr(self, "hint_btn", None)
        if hint_btn is not None:
            hint_btn.raise_()

    def _apply_window_chrome(self):
        """Apply the frameless flag + custom controls + rounded translucent
        shell, unless the escape-hatch setting requests the native title bar.
        Window flags + translucency are construction-time (set once, before
        show), so the setting takes effect on restart. Sets self._chrome to the
        controller (custom chrome) or None (native)."""
        self._chrome = None
        self.container.setObjectName("app_card")
        self.container.setAttribute(Qt.WA_StyledBackground, True)
        # perf_trace: window-state gestures have no terminal signal, so flush
        # via a short debounce restarted on each WindowStateChange.
        self._perf_state_flush = QTimer(self)
        self._perf_state_flush.setSingleShot(True)
        self._perf_state_flush.setInterval(150)
        self._perf_state_flush.timeout.connect(perf_trace.flush)
        self._perf_state_gid = ""
        self._perf_state_fires = 0
        if bool(self.settings_manager.get("use_system_title_bar", False)):
            self.setAttribute(Qt.WA_TranslucentBackground, False)
            self._apply_window_corner_state(self.isMaximized(), force=True)
            return  # native decorations; no custom controls
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        if _OPAQUE_MASK_CHROME:
            # Opaque experiment: keep an opaque surface, mask the corners.
            self.setAttribute(Qt.WA_TranslucentBackground, False)
            self._mask_cache = None  # (w, h, radius) last applied
        else:
            self.setAttribute(Qt.WA_TranslucentBackground, True)
        from utils.widgets.window_chrome import WindowChromeController
        self._chrome = WindowChromeController(self, self.header)
        self._chrome.reposition()
        self._apply_window_corner_state(self.isMaximized(), force=True)
        self._update_window_mask()
        # Push the current theme now: the earlier _apply_full_theme() in __init__
        # ran before _chrome existed, so without this the unfocused dots would
        # keep the dark-default inactive grey under the light theme until the
        # next theme change.
        self._notify_chrome_theme()

    def _apply_window_corner_state(self, is_maximized: bool, force: bool = False):
        """Apply rounded-card + outline + lit-rim + layout insets for the
        current state. Frameless + not maximized -> 16px rounded card with a
        1px theme-aware uniform outline and a lit top-rim on the header.
        Maximized or native title bar -> square, plain bg, no insets.

        The full-tree QWidget{} cascade is expensive, so skip it when neither
        the corner state nor the theme changed; theme/dark-light changes pass
        force=True to bypass the guard."""
        # (The multi-window overlay MINIMIZES this window while transparent rather
        # than transparentizing the central container, so the old transparent-mode
        # early-return that blanked #app_card here is gone - corner styling simply
        # does not matter on a minimized window.)
        c = self._theme_colors()
        bg = c["bg_app"]
        native = bool(self.settings_manager.get("use_system_title_bar", False))
        new_sig = corner_state_signature(is_maximized, native, bg)
        if should_skip_restyle(getattr(self, "_last_corner_sig", None), new_sig, force):
            return
        self._last_corner_sig = new_sig
        rounded = (not native) and (not is_maximized)
        root = self.container.layout()

        # A bare, unprefixed `QWidget { background }` rule on the container
        # CASCADES bg_app to every descendant QWidget (the long-standing
        # behavior several tabs rely on, e.g. the multitoon portrait
        # placeholders that explicitly set `transparent` to override it). The
        # object-scoped `QWidget#app_card { ... }` rule (rounded bg + uniform
        # outline) is more specific, so the card itself keeps its rounded fill
        # while descendants still inherit bg_app. Emit both.
        cascade = f"\nQWidget {{ background: {bg}; }}"

        _gid = getattr(self, "_perf_state_gid", "")
        with perf_trace.perf_span("apply_corner_state", _gid):
            if rounded:
                edge = window_edge_colors(bg)
                self.container.setStyleSheet(
                    card_qss("app_card", bg, RADIUS_NORMAL, edge["outline"]) + cascade)
                # No header bottom divider: the nav band below owns the single
                # hairline, so header + dock read as one continuous surface.
                self.header.setStyleSheet(
                    header_top_radius_qss(c["header_bg"], None,
                                          RADIUS_NORMAL, top_rim=edge["rim"]))
                if root is not None:
                    root.setContentsMargins(STROKE_INSET, STROKE_INSET, STROKE_INSET, BOTTOM_INSET)
            else:
                self.container.setStyleSheet(
                    card_qss("app_card", bg, RADIUS_MAXIMIZED, None) + cascade)
                self.header.setStyleSheet(
                    header_top_radius_qss(c["header_bg"], None, RADIUS_MAXIMIZED))
                if root is not None:
                    root.setContentsMargins(0, 0, 0, 0)
        self._update_window_mask()

    def _update_window_mask(self):
        """Opaque-chrome experiment only (TTMT_OPAQUE_MASK_CHROME). Mask the
        top-level to rounded corners in normal state / clear it when maximized.
        Rebuilds the QRegion only when (width, height, radius) changes."""
        if not _OPAQUE_MASK_CHROME:
            return
        from utils.window_chrome_mask import rounded_region
        native = bool(self.settings_manager.get("use_system_title_bar", False))
        rounded = (not native) and (not self.isMaximized())
        if not rounded:
            if getattr(self, "_mask_cache", None) is not None:
                self.clearMask()
                self._mask_cache = None
            return
        w, h, radius = self.width(), self.height(), RADIUS_NORMAL
        key = (w, h, radius)
        if key == getattr(self, "_mask_cache", None):
            return
        self.setMask(rounded_region(w, h, radius))
        self._mask_cache = key

    def _notify_chrome_theme(self):
        """Tell the window-chrome controller the current theme so the control
        dots use the right inactive-grey when the window is unfocused."""
        chrome = getattr(self, "_chrome", None)
        if chrome is not None and hasattr(chrome, "set_theme"):
            from utils.widgets.window_chrome_style import is_dark_bg
            chrome.set_theme(is_dark_bg(self._theme_colors()["bg_app"]))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            if getattr(self, "_chrome", None) is not None:
                flush_timer = getattr(self, "_perf_state_flush", None)
                if flush_timer is not None:
                    if not flush_timer.isActive():
                        # First fire of a new gesture: open it, reset the counter.
                        self._perf_state_gid = perf_trace.begin_gesture("window_state")
                        self._perf_state_fires = 0
                    self._perf_state_fires += 1
                    perf_trace.mark("statechange_fires", self._perf_state_gid,
                                    self._perf_state_fires)
                self._apply_window_corner_state(self.isMaximized())
                # Restart the debounce; flush once the gesture settles.
                if flush_timer is not None:
                    flush_timer.start()
            # Re-evaluate the Multitoon repaint timers on minimize/restore (the
            # page gets no hideEvent when the window is minimized).
            mt = getattr(self, "multitoon_tab", None)
            if mt is not None:
                mt._update_glow_timer()

    # ── Nav band ────────────────────────────────────────────────────────────

    def _build_nav_band(self) -> QFrame:
        band = QFrame()
        band.setMinimumHeight(NAV_BAND_H)
        band.setObjectName("app_nav_band")

        is_dark = resolve_theme(self.settings_manager) == "dark"
        from utils.widgets.glass_dock import GlassDock
        nav_items = [
            ("Launcher", "make_nav_power", "launcher"),
            ("Multitoon", "make_nav_gamepad", "multitoon"),
            ("Settings", "make_nav_gear", "settings"),
        ]
        self.nav_dock = GlassDock(nav_items, is_dark=is_dark)
        self.nav_dock.selected.connect(self.nav_select)

        layout = QHBoxLayout(band)
        layout.setContentsMargins(12, 1, 12, 1)
        layout.setSpacing(4)

        # Left phantom balances the right overflow cluster so the dock stays
        # optically centered when the (debug-only) overflow button is visible.
        self.nav_left_phantom = QSpacerItem(0, 0, QSizePolicy.Fixed, QSizePolicy.Minimum)
        layout.addSpacerItem(self.nav_left_phantom)
        layout.addStretch()
        layout.addWidget(self.nav_dock, 0, Qt.AlignVCenter)
        layout.addStretch()

        # Debug overflow (View Logs) — visible only when debug logging is on.
        from utils.widgets.overflow_popup import OverflowPopup
        self.overflow_btn = QToolButton(band)
        self.overflow_btn.setObjectName("rail_overflow")
        self.overflow_btn.setText("⋯")
        self.overflow_btn.setFixedSize(34, 34)
        self.overflow_btn.setToolTip("More")
        self.overflow_btn.setVisible(self.settings_manager.get("show_debug_tab", False))
        self.overflow_popup = OverflowPopup()
        self.overflow_popup.add_action("View Logs", lambda: self.nav_select(3))

        def _toggle_popup():
            from utils.motion import pop_menu
            pop_menu(self.overflow_popup, self.overflow_btn,
                     show=not self.overflow_popup.isVisible())
        self.overflow_btn.clicked.connect(_toggle_popup)
        layout.addWidget(self.overflow_btn)

        self._update_nav_phantom_width()
        return band

    def _update_nav_phantom_width(self):
        """Balance the right overflow cluster so the dock stays centered. The
        overflow button (34) is present-but-hidden when debug is off; only add
        the phantom when it is actually visible."""
        if not hasattr(self, "nav_left_phantom"):
            return
        right = 0
        if self.settings_manager.get("show_debug_tab", False):
            right = 34 + 4  # overflow button + its leading spacing gap
        self.nav_left_phantom.changeSize(right, 0, QSizePolicy.Fixed, QSizePolicy.Minimum)
        if hasattr(self, "nav_band"):
            self.nav_band.layout().invalidate()

    def _on_active_page_changed(self, index: int):
        """Fired by stack.currentChanged on every page switch. Lights the header
        wordmark while Credits (index 4) is active, and — whenever the user
        leaves Credits by ANY path (wordmark toggle-back, dock nav, or animated
        slide finalization) — clears the credits open-flag and releases the
        blurred backdrop pixmap."""
        # currentChanged fires only when a transition has SETTLED on a page, so
        # no Credits slide is in flight any more. Clearing the guard here is the
        # self-heal for the case where a dock nav cancels a Credits slide via
        # push_slide_pages' stop() — Qt does NOT emit `finished` on stop(), so
        # _begin_credits_transition's finished-lambda would otherwise leave
        # _credits_transitioning stuck True and permanently disable the toggle.
        self._credits_transitioning = False
        logo = getattr(self, "header_logo", None)
        if logo is not None and hasattr(logo, "set_active"):
            logo.set_active(index == 4)
        if index != 4:
            self._credits_open = False
            credits_tab = getattr(self, "credits_tab", None)
            if credits_tab is not None:
                credits_tab.clear_backdrop()

    def _wire_header_icon_active_state(self):
        """Drive the wordmark's 'lit while Credits active' state from ONE choke
        point — the stack's currentChanged — so every nav path (dock nav,
        credits nav, slide-animation finalization, direct setCurrentIndex) is
        covered without duplicating logic. Sync once for the page shown at
        startup (currentChanged does not fire retroactively)."""
        self.stack.currentChanged.connect(self._on_active_page_changed)
        self._on_active_page_changed(self.stack.currentIndex())

    def nav_select_credits(self):
        """Open Credits with a vertical push-slide over a blurred snapshot of
        the tab you were on. Reached via the header app icon (which toggles back
        to that tab on the next press).
        """
        prev_index = self.stack.currentIndex()
        if prev_index == 4:
            return

        # Capture the outgoing page as the blurred backdrop BEFORE switching, so
        # the descending Credits page already carries the blurred view. Ordering
        # is load-bearing: push_slide_pages grabs credits.grab() for its proxy.
        self._pre_credits_index = prev_index if 0 <= prev_index < 4 else 1
        self.credits_tab.set_backdrop_source(self.stack.widget(prev_index).grab())
        self._credits_open = True
        self._credits_transitioning = True

        was_initialized = getattr(self, "_initialized_nav", False)
        self._initialized_nav = True
        if not was_initialized:
            self.stack.setCurrentIndex(4)
            self._credits_transitioning = False
        else:
            from utils.motion import push_slide_pages
            self._begin_credits_transition(
                push_slide_pages(self.stack, prev_index, 4, axis="v")
            )

        # Credits (index 4) has no dock segment; leave the dock's selection as
        # it is so returning from Credits restores the prior tab's tint.

    def _on_app_icon_clicked(self):
        """Header app icon: open Credits, or (if already on Credits) return to
        the tab you came from. Ignored while a Credits slide is in flight."""
        if getattr(self, "_credits_transitioning", False):
            return
        if getattr(self, "_credits_open", False):
            self._nav_return_from_credits()
        else:
            self.nav_select_credits()

    def _nav_return_from_credits(self):
        """Reverse-vertical slide from Credits back to the pre-Credits tab."""
        target = getattr(self, "_pre_credits_index", 1)
        if not (0 <= target < 4):
            target = 0
        self._credits_open = False
        self._credits_transitioning = True
        from utils.motion import push_slide_pages
        self._begin_credits_transition(
            push_slide_pages(self.stack, 4, target, axis="v", reverse=True)
        )
        # Drive the dock back to the tab we return to. Targets 0-2 are dock
        # segments; target 3 (debug) has no segment, so the range guard skips it.
        if hasattr(self, "nav_dock") and 0 <= target < len(self.nav_dock.segments):
            self.nav_dock.select(target, animate=True)

    def _begin_credits_transition(self, group):
        """Lower the in-flight guard when the given slide finishes (immediately
        under reduced motion, where push_slide_pages returns None)."""
        if group is None:
            self._credits_transitioning = False
        else:
            group.finished.connect(
                lambda: setattr(self, "_credits_transitioning", False)
            )
        return group

    def _open_emblem_wheel(self):
        """Left-click on the emblem: TOGGLE the radial wheel for the current mode
        (open if closed, close if already open - the emblem stays on top in the
        ring's center, so its click is the natural close affordance). Transparent
        mode uses the X11 overlay path; windowed mode hosts the same widget as an
        in-window child (WindowedWheelHost)."""
        # Second emblem click closes an open wheel (toggle) - the ANIMATED
        # dismiss (spokes fly back into the emblem), not the hard teardown:
        # since the radial input region gained its emblem-disc hole, this click
        # reaches the EMBLEM (not the menu), so the menu-side animated close no
        # longer fires on its own; dismiss_radial_menu routes back through it.
        from utils.overlay.backend import overlay_trace
        overlay_trace(
            f"emblem wheel: mode_active={self._mode_controller.is_active} "
            f"wheel_open={self._windowed_wheel is not None}")
        if self._mode_controller.is_active:
            if self._mode_controller.is_radial_open:
                self._mode_controller.dismiss_radial_menu()
                return
        elif self._windowed_wheel is not None:       # windowed wheel already open
            self._windowed_wheel.dismiss()
            return
        self._prewarm_radial_accounts()
        if self._mode_controller.is_active:          # is_active is a @property
            menu = self._mode_controller.open_radial_menu()
            if menu is None:
                return
            self._wire_radial_menu(menu)
            return
        if self._windowed_wheel is not None:         # already open (race guard)
            return
        from utils.overlay.windowed_wheel import WindowedWheelHost
        emblem = self.multitoon_tab._compact._emblem
        host = WindowedWheelHost(
            parent=self.centralWidget(),
            emblem=emblem,
            emblem_diameter=emblem.disc_diameter(),
            customizations=self.multitoon_tab.customizations)
        self._windowed_wheel = host
        host.menu.accounts_requested.connect(
            lambda: self._populate_radial_accounts(host.menu))
        host.menu.game_selected.connect(
            lambda g, m=host.menu: self._populate_radial_accounts_for_game(m, g))
        host.menu.transparent_requested.connect(self._windowed_go_transparent)
        host.menu.account_clicked.connect(self._radial_launch_account)
        host.closed.connect(lambda: setattr(self, "_windowed_wheel", None))
        host.show_centered()
        overlay_trace(f"windowed wheel: shown geom={host.geometry()} "
                      f"visible={host.isVisible()}")

    def _windowed_go_transparent(self):
        """Go-Transparent spoke: dismiss the windowed wheel, then enter
        transparent mode (the floating emblem then opens the transparent ring)."""
        if self._windowed_wheel is not None:
            self._windowed_wheel.dismiss()
        if not self._mode_controller.is_active:
            self._mode_controller.toggle()           # framed -> transparent

    def _wire_radial_menu(self, menu):
        """Connect a freshly opened RadialMenuWidget's intent signals to the
        coordinator. The widget is owned by the mode controller and torn down on
        close_radial_menu()/leave(), so its connections die with it."""
        menu.accounts_requested.connect(lambda: self._populate_radial_accounts(menu))
        menu.game_selected.connect(
            lambda g, m=menu: self._populate_radial_accounts_for_game(m, g))
        menu.home_requested.connect(self._radial_go_home)
        menu.settings_requested.connect(self._open_portable_settings)
        menu.hide_cards_requested.connect(self._radial_toggle_cards)
        menu.close_requested.connect(self._mode_controller.close_radial_menu)
        menu.exit_requested.connect(self._radial_exit_app)
        menu.account_clicked.connect(self._radial_launch_account)
        # Feed the Hide-Cards toggle's current state so its glyph/label match.
        menu.set_cards_hidden(self._mode_controller.cards_hidden)

    def _radial_exit_app(self):
        """Exit spoke: the sanctioned in-overlay way to quit the whole app
        (now that the emblem/overlay surfaces refuse stray close requests).
        Closes the radial, then runs the main window's normal close -> shutdown
        -> app.quit() path."""
        self._mode_controller.close_radial_menu()
        self.close()

    def _prewarm_radial_accounts(self):
        """Fetch recent-account poses the moment the emblem wheel opens, so the
        Accounts sub-ring is usually warm by the time the user navigates to it.
        Best-effort: never let a pre-warm failure block opening the wheel."""
        try:
            ring = self.launch_tab.recent_account_ring_model(limit=8)
            from utils.overlay.radial_portrait import prewarm_account_poses
            prewarm_account_poses(ring, self.multitoon_tab.customizations)
        except Exception:
            pass

    def _populate_radial_accounts(self, menu):
        """Feed the radial's Accounts flow. With accounts saved for MORE THAN
        ONE game, show the game-selector sub-ring first (one logo disc per
        game; same-username accounts across games are otherwise
        indistinguishable); with a single game, open its ring directly.
        Reuses launch_tab's keyring-free ring builder (which INCLUDES running
        accounts, unlike the flat menu) and supplies the real
        ToonCustomizationsManager so portraits render styled."""
        games = self.launch_tab.account_games()
        if len(games) >= 2:
            menu.set_game_selector(games)
            return
        game = games[0] if games else None
        ring = self.launch_tab.recent_account_ring_model(limit=8, game=game)
        menu.set_accounts(ring, customizations=self.multitoon_tab.customizations)

    def _populate_radial_accounts_for_game(self, menu, game):
        """A game-selector disc was picked: open that game's accounts ring.
        via_games=True routes its Back spoke to the selector, not the main
        ring."""
        ring = self.launch_tab.recent_account_ring_model(limit=8, game=game)
        menu.set_accounts(ring, customizations=self.multitoon_tab.customizations,
                          via_games=True)

    def _radial_go_home(self):
        """Window spoke: close the radial and return to the windowed app view."""
        self._mode_controller.close_radial_menu()
        self._mode_controller.toggle()          # active -> leave() -> windowed

    def _radial_toggle_cards(self):
        """Hide-Cards spoke: dismiss the ring (animated fly-back), then flip the
        cards' visibility with the tuck animation - the cards shrink into the
        emblem in step with the retracting spokes (and grow back out of it on
        Show). The emblem always stays; reopening the ring offers the same
        spoke as "Show Cards" to bring the cards back."""
        self._mode_controller.dismiss_radial_menu()
        self._mode_controller.toggle_cards_hidden(animate=True)

    def _on_hotkey_action(self, action_id: str):
        # Chord-capture holiday: while a Settings capture button is recording,
        # a provider-side fire of the very chord being re-recorded (Carbon
        # never routes through the session tap) must not trigger its action.
        from utils import chord_capture_state
        if chord_capture_state.is_active():
            print(f"[GlobalHotkeys] {action_id} ignored (chord capture recording)")
            return
        handler = self._hotkey_dispatch.get(action_id)
        if handler is None:
            print(f"[GlobalHotkeys] unknown action {action_id!r} (dropped)")
            return
        try:
            handler()
        except Exception as e:                        # noqa: BLE001
            print(f"[GlobalHotkeys] {action_id} handler error: {e}")

    def _radial_launch_account(self, account_id):
        """Account spoke clicked: launch it (the sub-ring stays open so the user
        can fire several). launch_account no-ops a re-launch of a running game."""
        game = self.launch_tab.game_of_account(account_id)
        if game is None:
            return
        self.launch_tab.launch_account(game, account_id)

    def _open_portable_settings(self):
        """Settings spoke: float the real SettingsTab over the overlay (reparented,
        so its existing signal wiring keeps working)."""
        self._mode_controller.close_radial_menu()
        if getattr(self, "_settings_floating", False):
            return
        from utils.overlay.portable_settings import PortableSettingsContainer
        self._settings_container = PortableSettingsContainer(self.settings_tab)
        self._settings_floating = True
        self._settings_container.closed.connect(self._mode_controller.close_panel_surface)
        # on_close runs inside close_panel_surface BEFORE the surface is destroyed.
        surface = self._mode_controller.open_panel_surface(
            self._settings_container, on_close=self._restore_settings_to_stack)
        # Bulletproof: if the surface could not be created (controller inactive),
        # the SettingsTab is already reparented out of the stack but no teardown
        # path (X/Esc/leave) is wired, so restore it immediately rather than
        # stranding it.
        if surface is None:
            self._restore_settings_to_stack()

    def _restore_settings_to_stack(self):
        """Idempotent: put the reparented SettingsTab back in the tab stack."""
        if not getattr(self, "_settings_floating", False):
            return
        self._settings_floating = False
        # Force-cancel any in-progress chord capture BEFORE the SettingsTab is
        # reparented out: a deaf/abandoned capture in the non-activating panel
        # would otherwise leave the input holiday stuck ON (global hotkeys +
        # routing silently disabled). Its focus-out may never fire on Windows.
        from utils import hotkey_capture
        hotkey_capture.cancel_active_capture()
        cont = self._settings_container
        self._settings_container = None
        if cont is not None:
            cont.release_content()
        self.stack.insertWidget(2, self.settings_tab)   # restore at its original index

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

        # Drive the dock's selected segment (0..2 are the dock tabs; index 3/4
        # are Logs/Credits, which have no segment — leave the dock as-is).
        if hasattr(self, "nav_dock") and 0 <= index < len(self.nav_dock.segments):
            self.nav_dock.select(index, animate=was_initialized)

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
        self._update_window_mask()

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
                # prompt. save_clicked and discard_clicked resume the swap;
                # keep_clicked cancels it.
                self._pending_mode_swap = target
                # Disconnect stale one-shot handlers from any previous deferred
                # swap so a later unrelated confirm cannot fire a stale resume.
                for _sig, _slot in [
                    (overlay._confirm_prompt.discard_clicked,
                     self._resume_pending_mode_swap),
                    (overlay._confirm_prompt.save_clicked,
                     self._resume_pending_mode_swap),
                    (overlay._confirm_prompt.keep_clicked,
                     self._cancel_pending_mode_swap),
                ]:
                    try:
                        _sig.disconnect(_slot)
                    except (RuntimeError, TypeError):
                        pass
                overlay._confirm_prompt.discard_clicked.connect(
                    self._resume_pending_mode_swap
                )
                # save_clicked is already permanently wired to close_and_save;
                # additionally resume the swap once the save completes.
                overlay._confirm_prompt.save_clicked.connect(
                    self._resume_pending_mode_swap
                )
                overlay._confirm_prompt.keep_clicked.connect(
                    self._cancel_pending_mode_swap
                )
                overlay._show_confirm_prompt()
                return
            # Clean draft: close immediately, then fall through to swap.
            overlay.close_and_discard()

        self._layout_mode = target
        self.multitoon_tab.set_layout_mode(target)
        if hasattr(self, "launch_tab") and self.launch_tab is not None:
            self.launch_tab.set_layout_mode(target)
        if hasattr(self, "settings_tab") and self.settings_tab is not None:
            self.settings_tab.set_layout_mode(target)

    def _resume_pending_mode_swap(self) -> None:
        target = getattr(self, "_pending_mode_swap", None)
        if target is None:
            return
        self._pending_mode_swap = None
        self._layout_mode = target
        self.multitoon_tab.set_layout_mode(target)
        if hasattr(self, "launch_tab") and self.launch_tab is not None:
            self.launch_tab.set_layout_mode(target)
        if hasattr(self, "settings_tab") and self.settings_tab is not None:
            self.settings_tab.set_layout_mode(target)

    def _cancel_pending_mode_swap(self) -> None:
        self._pending_mode_swap = None

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
            settings=tab.settings_manager,
        )

    # ── Theme ──────────────────────────────────────────────────────────────

    def _theme_colors(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

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
        c = self._theme_colors()

        # Container card + header corners/stroke (rounded vs native/maximized)
        self._apply_window_corner_state(self.isMaximized(), force=True)
        self._notify_chrome_theme()
        self._refresh_header_logo()

        # Nav band: flat window body, NO divider (no hairline above or below the
        # dock) - the header, dock, and content below read as one seamless
        # surface. The dock's own glass border is the only chrome edge.
        self.nav_band.setStyleSheet(f"""
            QFrame#app_nav_band {{
                background: {c['bg_app']};
            }}
        """)
        if hasattr(self, "nav_dock"):
            self.nav_dock.apply_theme(resolve_theme(self.settings_manager) == "dark")
        if hasattr(self, "debug_tab"):
            self.debug_tab.apply_theme(resolve_theme(self.settings_manager) == "dark")
        self.update_banner.apply_theme(c)
        self.admin_notice_banner.apply_theme(c)
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
        # phantom so the dock stays geometrically centered.
        self._update_nav_phantom_width()
        ttr_api.set_debug(show)
        if not show and self.stack.currentIndex() == 3:
            self.nav_select(1)  # back to Multitoon (home)

    def on_clear_credentials_requested(self):
        self.launch_tab.clear_all_credentials()
        self.log("[Credentials] All stored credentials have been cleared from Keyring and session memory.")

    @Slot()
    def _on_keep_alive_help_requested(self):
        """User clicked 'Go to Settings' in the Keep-Alive help popover.
        Navigate to the Settings tab and highlight the Keep-Alive group."""
        self.nav_select(2)  # Settings tab index — see stack widget order in __init__
        self.settings_tab.highlight_keep_alive_group()

    def _on_keep_alive_inhibit_status(self, status):
        """Show a one-time-per-launch warning when Keep-Alive is running but the
        verified sleep guarantee is missing. A held sleep lock (sleep_blocked
        True) never warns; a screen-lock-only shortfall (sleep_blocked True,
        cookie not held) never warns either - only sleep_blocked False does."""
        if status.sleep_blocked or self._sleep_warning_shown:
            return
        self._sleep_warning_shown = True
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Keep-Alive cannot block sleep")
        box.setText(
            "Keep-Alive is running, but this computer's sleep or hibernate "
            "setting could not be held off. Your toons may be disconnected if "
            "the machine sleeps.\n\nThis is unexpected. You can keep the machine "
            "awake in your system's power settings as a workaround."
        )
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()

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
        button in Settings > Keysets: stored ttr_engine_dir first, then
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
            ("global_hotkeys", "global_hotkeys", "stop"),
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

    def log(self, message: str, level: str | None = None):
        if not self.debug_tab.logging_enabled:
            return
        print(message)
        self.debug_tab.append_log(message, level=level)


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


def _detect_wm_name_safe():
    """Best-effort running-WM name for window-mode gating; None on non-Linux
    platforms or if the Xlib connection fails."""
    if sys.platform != "linux":
        return None
    if not os.environ.get("DISPLAY"):
        return None  # no X server (headless / pure Wayland): skip the noisy probe
    try:
        from Xlib import display as _xd
        from utils.x11_frameless_bootstrap import detect_wm_name
        d = _xd.Display()
        try:
            return detect_wm_name(d)
        finally:
            d.close()
    except Exception:
        return None


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
        # utils.xrecord_capture likewise (X RECORD mouse capture for click
        # sync; Linux/X11 only).
        excluded.add("utils.xrecord_capture")
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
        os.environ["TTMT_SELF_CHECK"] = "1"   # gate startup network/keychain work
        _import_all_modules()
        QApplication.setApplicationName(app_name())
        QApplication.setOrganizationName("flossbud")
        app = QApplication(sys.argv)
        settings = SettingsManager()
        apply_theme(app, resolve_theme(settings))
        window = MultiToonTool()
        app.processEvents()
        window.shutdown()        # stop service threads BEFORE the Qt/Python teardown
        window.close()
        app.processEvents()
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


def _self_check_exit(code: int) -> None:
    """Exit after a --self-check run.

    On a SUCCESSFUL frozen macOS build, bypass interpreter finalization via
    os._exit(0): the oracle's result is already known once _run_self_check
    returns 0, and the frozen-bundle macOS teardown has a rare, CI-only native
    finalization crash (Shiboken/PyObjC dtor ordering) that would otherwise fail
    the gate AFTER success. Every other path -- source runs, non-macOS packages,
    and ALL failures -- keeps normal sys.exit so genuine teardown regressions and
    load errors stay visible. stdout/stderr are flushed first because os._exit
    skips the normal buffer flush."""
    sys.stdout.flush()
    sys.stderr.flush()
    if code == 0 and sys.platform == "darwin" and getattr(sys, "frozen", False):
        os._exit(0)
    sys.exit(code)


def _show_or_float_at_startup(window, *, settings, env, _show=None) -> None:
    """Map the main window and/or enter Float UI in the artifact-free order.

    Plain-show window modes (PURE_FRAMELESS / NATIVE_TITLE_BAR) attempt the
    startup Float UI entry BEFORE the first show: a never-mapped main window
    cannot flash on screen (or in the taskbar) on its way to being hidden.
    Only when Float UI does not engage (setting off, backend unavailable,
    enter failed) is the window shown. Bootstrap modes (frame-then-strip /
    border-only) need the window realized+mapped before the strip, so they
    keep the historical show -> enter -> hide order; the brief map there is
    the price of the bootstrap, not a regression.

    `_show` is injectable for tests; defaults to show_with_bootstrap."""
    from utils.x11_frameless_bootstrap import (
        NATIVE_TITLE_BAR, PURE_FRAMELESS, resolve_mode_for_env,
        show_with_bootstrap,
    )
    shower = _show or show_with_bootstrap
    mode = resolve_mode_for_env(settings, env)
    if mode in (PURE_FRAMELESS, NATIVE_TITLE_BAR):
        if window._maybe_enter_float_mode_at_startup():
            return
        shower(window, settings=settings, env=env)
        return
    shower(window, settings=settings, env=env)
    window._maybe_enter_float_mode_at_startup()


if __name__ == "__main__":
    if "--ghost-renderer" in sys.argv:
        # Ghost-renderer helper process (ledger CP17): a dedicated Qt loop
        # for cursor-class glove motion, fed over stdin by the parent app.
        # Dispatched before any app/service initialization.
        from utils.ghost_renderer import run_ghost_renderer
        sys.exit(run_ghost_renderer())

    if "--self-check-keyring" in sys.argv:
        sys.exit(_run_self_check_keyring())

    if "--self-check" in sys.argv:
        _self_check_exit(_run_self_check())

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
    if os.environ.get("TTMT_CLICK_DIAG"):
        # Click/activation delivery diagnostics. Earned its keep in the
        # 2026-07-04 eaten-clicks investigation (exposed window-level
        # delivery vs widget dispatch vs drag classification); opt-in via
        # TTMT_CLICK_DIAG because the per-widget activation lines are loud.
        from PySide6.QtCore import QEvent, QObject
        from PySide6.QtGui import QWindow
        from utils.overlay.backend import overlay_trace as _otrace

        class _ClickDiag(QObject):
            _EVS = {QEvent.MouseButtonPress: "press",
                    QEvent.MouseButtonRelease: "release",
                    QEvent.ApplicationActivate: "APP-ACTIVATE",
                    QEvent.ApplicationDeactivate: "APP-DEACTIVATE",
                    QEvent.WindowActivate: "win-activate",
                    QEvent.WindowDeactivate: "win-deactivate"}

            def eventFilter(self, obj, ev):
                kind = self._EVS.get(ev.type())
                if kind in ("press", "release"):
                    if isinstance(obj, QWindow):
                        popup = QApplication.activePopupWidget()
                        grabber = QWidget.mouseGrabber()
                        _otrace(f"clickdiag {kind} win={obj.objectName() or type(obj).__name__} "
                                f"active={obj.isActive()} btn={ev.button()} "
                                f"popup={type(popup).__name__ if popup else None} "
                                f"grabber={type(grabber).__name__ if grabber else None}")
                    else:
                        # Widget-level receiver: which widget owns each half of
                        # the click, and is it still down/enabled at release.
                        down = getattr(obj, "isDown", lambda: "?")()
                        en = getattr(obj, "isEnabled", lambda: "?")()
                        _otrace(f"clickdiag {kind}@widget {type(obj).__name__} "
                                f"down={down} enabled={en}")
                elif ev.type() == QEvent.EnabledChange and not isinstance(obj, QWindow):
                    _otrace(f"clickdiag ENABLED-CHANGE {type(obj).__name__} "
                            f"-> {getattr(obj, 'isEnabled', lambda: '?')()}")
                elif kind is not None and isinstance(obj, QApplication):
                    _otrace(f"clickdiag {kind}")
                return False

        _click_diag = _ClickDiag(app)
        app.installEventFilter(_click_diag)
    # Bundle-load the UI font (DejaVu Sans) so it renders identically on every
    # OS regardless of what the host has installed, and make it the application
    # default so painter-drawn text (nav/category pills, keycaps, badges) matches
    # the stylesheet text. Shipped under assets/fonts/ (included in every build).
    from PySide6.QtGui import QFont as _QFont, QFontDatabase as _QFontDB
    for _font_file in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        _font_path = os.path.join(_assets_dir(), "fonts", _font_file)
        if os.path.exists(_font_path):
            _QFontDB.addApplicationFont(_font_path)
    _appfont = _QFont("DejaVu Sans")
    if sys.platform == "linux":
        # Explicit colour-emoji fallback (some Linux runtimes won't auto-fall).
        _QFontDB.addApplicationFont("/usr/share/fonts/google-noto-color-emoji-fonts/Noto-COLRv1.ttf")
        _appfont.setFamilies(["DejaVu Sans", "Noto Color Emoji"])
    app.setFont(_appfont)
    settings = SettingsManager()
    apply_theme(app, resolve_theme(settings))
    window = MultiToonTool()
    _wire_app_lifecycle(app, window)
    from PySide6.QtCore import QLibraryInfo as _QLI
    # Show the window and/or honor "Start in Float UI mode". Float-first on
    # plain-show window modes: entering the overlay BEFORE the first show
    # means the main window is never mapped at all on a float launch, so it
    # cannot flash on screen between show() and the overlay's hide().
    _show_or_float_at_startup(window, settings=window.settings_manager, env={
        "platform": sys.platform,
        "session_type": os.getenv("XDG_SESSION_TYPE", "").lower(),
        "qpa_platform": app.platformName(),
        "wm_name": _detect_wm_name_safe(),
        "use_system_title_bar": bool(window.settings_manager.get("use_system_title_bar", False)),
        "qt_version": _QLI.version().toString() if hasattr(_QLI, "version") else "",
    })
    QTimer.singleShot(0, window._maybe_notify_float_startup_recovered)
    _lock_cc_prefs_silently()
    # macOS first-run permission onboarding. Fired POST-show (so --self-check,
    # which exits before this block and never shows the window, never triggers
    # it). Non-blocking .show() keeps the app usable; shows on first run or any
    # later run where a required grant is still missing (nags until granted).
    if sys.platform == "darwin":
        from utils import macos_permissions as _mp
        _pm = _mp.PermissionManager()
        if not settings.get("macos_permissions_onboarding_shown", False) \
                or not _pm.all_granted():
            try:
                import AppKit
                _bundle_path = AppKit.NSBundle.mainBundle().bundlePath()
            except Exception:
                _bundle_path = sys.executable
            from utils.widgets.macos_permissions_dialog import MacOSPermissionsDialog
            _perm_dlg = MacOSPermissionsDialog(
                _pm, location_ok=_mp.is_install_location_ok(_bundle_path),
                parent=window)
            _perm_dlg.show()
            settings.set("macos_permissions_onboarding_shown", True)
    # Fire the multi-install picker on a 0-delay timer so Qt has finished
    # processing the show event before any modal dialog steals focus.
    QTimer.singleShot(0, lambda: _maybe_prompt_for_cc_install(window, window.settings_manager))
    sys.exit(app.exec())
