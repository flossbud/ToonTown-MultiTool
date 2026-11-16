"""The launchpad window: the launcher, a header, and sheets that slide over it.

This is the app's main window when ``TTMT_NEXT_UI=1``. It builds the same
services the classic window builds, with a headless ``ToonSession`` where
that one has the Multitoon tab, hosts ``LaunchTab`` as its only page, and
opens Accounts, Keysets and Settings as sheets from the header. The toons'
controls live on the float strips, not in this window.

Old and new never run in one process: ``main.py`` picks one window class.
"""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QEvent, QRect, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget,
)

import utils.ttr_api as ttr_api
from services.toon_session import ToonSession
from services.window_manager import WindowManager
from utils import perf_trace
from utils.build_flavor import app_name, window_title
from utils.game_registry import GameRegistry
from utils.keymap_manager import KeymapManager
from utils.profile_manager import ProfileManager
from utils.settings_manager import SettingsManager
from utils.theme_manager import (
    SystemThemeWatcher, apply_theme, get_theme_colors, resolve_theme,
)
from utils.widgets.launchpad.header import (
    HEADER_H, SHEET_ACCOUNTS, SHEET_BUTTONS, SHEET_KEYSETS, SHEET_SETTINGS,
    LaunchpadHeader, next_open_sheet,
)
from utils.widgets.window_chrome_style import (
    BOTTOM_INSET, RADIUS_MAXIMIZED, RADIUS_NORMAL, STROKE_INSET,
    card_qss, header_top_radius_qss, window_edge_colors,
)
from utils.window_corner_state import corner_state_signature, should_skip_restyle
from utils.settings_keys import (
    HIDE_WINDOW_WHEN_TOONS_UP, HIDE_WINDOW_WHEN_TOONS_UP_DEFAULT, TRAY_ICON,
)
from utils.widgets.launchpad import lifecycle

NEXT_UI_ENV = "TTMT_NEXT_UI"
STAMP = "[NextUI] launchpad window + float strips (TTMT_NEXT_UI=1)"

_OPAQUE_MASK_CHROME = (
    sys.platform == "darwin" and os.environ.get("TTMT_OPAQUE_MASK_CHROME") == "1"
)

SHEET_TITLES = {
    SHEET_ACCOUNTS: ("Accounts", "Saved logins and the toons seen on each."),
    SHEET_KEYSETS: ("Keysets", "Numbered movement-key layouts. Each toon picks "
                               "one from its strip."),
    SHEET_SETTINGS: ("Settings", ""),
}
SHEET_IDENTITY = {name: identity for name, _label, identity, _glyph in SHEET_BUTTONS}


def next_ui_enabled(environ=None) -> bool:
    """Whether this run uses the launchpad window. Only an explicit "1"."""
    environ = os.environ if environ is None else environ
    return environ.get(NEXT_UI_ENV, "").strip() == "1"


def _quit_app() -> None:
    """Closing the main window ends the app."""
    app = QApplication.instance()
    if app is not None:
        app.quit()


class _NoFloatMode:
    """What the hotkey dispatch sees where the classic window has its Float
    UI controller: there is no cluster here to tuck or scale."""

    is_active = False
    is_radial_open = False


class _SheetPlaceholder(QWidget):
    """Stands in for a sheet whose content has not been mounted yet."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("sheet_placeholder")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 18, 12, 18)
        self._label = QLabel(f"{title} will appear here.", self)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)
        layout.addStretch(1)
        self.apply_theme(True)

    def apply_theme(self, is_dark: bool) -> None:
        color = "#b0b0b0" if is_dark else "#555555"
        self._label.setStyleSheet(
            f"background: transparent; color: {color}; font-size: 13px;")


class LaunchpadWindow(QMainWindow):
    _api_log = Signal(str)
    # A chat capture started or ended in the focused game (InputService).
    chat_active_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        print(STAMP)

        self._sleep_warning_shown = False
        self._shutdown_complete = False
        self._chat_active = False
        self._chrome = None
        self._uipi_dialog = None
        self._quitting = False
        self._launch_states: dict[str, str] = {}

        self.setWindowTitle(window_title())
        self.setObjectName("MultiToonToolMainWindow")
        from utils.window_layout import clamp_window_height
        screen = self.screen() or QGuiApplication.primaryScreen()
        avail_h = screen.availableGeometry().height() if screen else 0
        self.setGeometry(QRect(100, 100, 880, clamp_window_height(avail_h, target=860)))
        self.setMinimumWidth(820)

        GameRegistry.instance()          # warm up before any launcher
        self.settings_manager = SettingsManager()
        self._hints_enabled = bool(self.settings_manager.get("hints_enabled", True))
        from utils.update_defaults import apply_first_launch_defaults
        apply_first_launch_defaults(self.settings_manager)

        import utils.motion as motion
        motion.set_settings_manager(self.settings_manager)
        self.settings_manager.on_change(motion.on_settings_change)

        self.keymap_manager = KeymapManager()
        self.profile_manager = ProfileManager()
        self.hotkeys = None

        # The default keyset follows the user's TTR config without a manual
        # "Detect" press.
        self._apply_startup_ttr_keymap()

        QTimer.singleShot(0, self._capture_multitool_window_id)

        self.window_manager = WindowManager(self.settings_manager)
        self.window_manager.start()

        # The logs console is the logger; it mounts in the Settings sheet.
        from tabs.debug_tab import DebugTab
        self.debug_tab = DebugTab()
        self.logger = self.debug_tab

        self.session = ToonSession(
            self.window_manager,
            settings_manager=self.settings_manager,
            keymap_manager=self.keymap_manager,
            profile_manager=self.profile_manager,
            logger=self.logger,
        )

        # The launchpad hosts the Grandstand launcher only; the previous
        # launcher's pages have no place in this window.
        from utils.widgets.grandstand import view as grandstand_view
        if not grandstand_view.grandstand_enabled():
            print(f"[NextUI] {grandstand_view._FLAG}=0 is ignored: the launchpad "
                  "window hosts the Grandstand launcher only")
            os.environ[grandstand_view._FLAG] = "1"

        from tabs.launch_tab import LaunchTab
        self.launch_tab = LaunchTab(
            settings_manager=self.settings_manager, logger=self.logger,
            window_manager=self.window_manager)
        # Toons the game APIs resolve update the launching account's record.
        self.session.set_toon_capture_sink(self.launch_tab.capture_toon)
        # One looks store: the launcher's portraits and the strips' accents.
        self.launch_tab.set_customizations_manager(self.session.customizations)
        self.launch_tab.look_saved.connect(self._on_look_saved)

        self._wire_input_service()

        # The launcher as the strips' compact launcher sees it.
        from utils.launcher_port import LauncherPort
        self.launcher_port = LauncherPort(self.launch_tab, parent=self)
        self.strips = self._build_strips()

        # ── Layout: header, banners, the launcher ─────────────────────────
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = LaunchpadHeader()
        self.header.hints_toggled.connect(self._toggle_hints)
        self.header.sheet_pressed.connect(self._on_sheet_button)
        root.addWidget(self.header)

        from utils.widgets.update_banner import UpdateBanner
        self.update_banner = UpdateBanner(parent=self)
        self.update_banner.clicked.connect(self._on_update_banner_clicked)
        self._pending_update_info = None
        root.addWidget(self.update_banner)

        from utils.widgets.admin_notice_banner import AdminNoticeBanner
        self.admin_notice_banner = AdminNoticeBanner(parent=self)
        self.admin_notice_banner.restart_as_admin.connect(self._on_admin_notice_restart)
        self.admin_notice_banner.dismissed.connect(self._on_admin_notice_dismissed)
        root.addWidget(self.admin_notice_banner)

        root.addWidget(self.launch_tab, 1)

        self.container = QWidget()
        self.container.setLayout(root)
        self.setCentralWidget(self.container)

        # Sheets slide over everything below the header.
        from utils.widgets.launchpad.slide_sheet import SlideSheetHost
        self.sheet_host = SlideSheetHost(self.container, top=HEADER_H,
                                         is_dark=self._is_dark())
        self.sheet_host.content_changed.connect(self._on_sheet_content_changed)
        self.sheet_host.closed.connect(self._on_sheet_closed)
        self._sheets: dict[str, QWidget] = {}
        self._sheet_names: dict[int, str] = {}

        self._apply_full_theme()
        self._apply_window_chrome()
        self._refresh_session_status()

        self._system_theme_watcher = SystemThemeWatcher(self)
        self._system_theme_watcher.system_theme_changed.connect(
            self._on_system_color_scheme_changed)
        self.settings_manager.on_change(self._on_setting_changed)

        self._setup_update_checker()
        self._maybe_kick_off_startup_check()

        # Tooltips are blocked app-wide while hover hints are off.
        QApplication.instance().installEventFilter(self)

        self._wire_hotkeys()
        self._build_settings_sheet()
        self._build_accounts_sheet()

        self.session.toons_changed.connect(self._refresh_session_status)
        self.session.keep_alive_inhibit_status.connect(self._on_keep_alive_inhibit_status)

        if self.strips is not None:
            self.strips.start()

        self._build_lifecycle_and_tray()

        self.log(f"[Debug] {app_name()} launched.")
        self._maybe_show_admin_notice()

    # ── What main.py asks of a main window ─────────────────────────────────

    def _maybe_enter_float_mode_at_startup(self) -> bool:
        """The launchpad has no Float UI mode to start in: the strips are not
        a mode of this window."""
        return False

    def _maybe_notify_float_startup_recovered(self) -> None:
        """Nothing to recover: see _maybe_enter_float_mode_at_startup."""

    def log(self, message: str, level: str | None = None) -> None:
        if not self.debug_tab.logging_enabled:
            return
        print(message)
        self.debug_tab.append_log(message, level=level)

    # ── InputService wiring ────────────────────────────────────────────────

    def _wire_input_service(self) -> None:
        input_service = self.session.input_service
        logging_on = bool(self.settings_manager.get("show_debug_tab", False))
        self.debug_tab.logging_enabled = logging_on
        input_service.logging_enabled = logging_on

        # Asked per key event, so edits to TTR's settings.json are honoured
        # without restarting: a small JSON read buys liveness.
        from utils.ttr_settings import resolve_chat_block_list

        def chat_block_list():
            settings = self._refresh_ttr_settings()
            if settings is None:
                return {"Return", "Escape"}
            return resolve_chat_block_list(settings)

        def chat_open_chords():
            # The client's OWN chat / group-chat chords; None means the
            # stock enter / alt-enter.
            settings = self._refresh_ttr_settings()
            return None if settings is None else settings.chat_open_chords

        input_service.get_chat_block_list = chat_block_list
        input_service.get_chat_open_chords = chat_open_chords

        ttr_api.set_debug(logging_on)
        self._api_log.connect(self.debug_tab.append_log)
        ttr_api.set_log_callback(self._api_log.emit)

        input_service.chat_state_changed.connect(self._on_chat_state_changed)
        input_service.uipi_blocked_movement_detected.connect(self._on_uipi_blocked)

    @Slot(bool)
    def _on_chat_state_changed(self, active: bool) -> None:
        active = bool(active)
        if active != self._chat_active:
            self._chat_active = active
            self.chat_active_changed.emit(active)

    def chat_active(self) -> bool:
        return self._chat_active

    def _on_uipi_blocked(self, details: dict) -> None:
        """Windows: input to a background toon is provably being dropped
        because the game runs elevated and this app does not. Offer to
        restart elevated, once per session unless dismissed for good."""
        from utils.settings_keys import UIPI_ELEVATION_PROMPT_DISMISSED
        settings = self.settings_manager
        if settings.get(UIPI_ELEVATION_PROMPT_DISMISSED, False):
            return
        from utils.widgets.uipi_elevation_dialog import UipiElevationDialog
        targets = details.get("targets") or [details]
        toons = [f"Toon {t.get('toon_index', -1) + 1}"
                 for t in targets if t.get("toon_index", -1) >= 0]
        dialog = UipiElevationDialog(affected_toons=toons, parent=self)
        self._uipi_dialog = dialog
        dialog.restart_as_admin.connect(self._restart_elevated_from_prompt)
        dialog.dont_ask_again.connect(
            lambda: settings.set(UIPI_ELEVATION_PROMPT_DISMISSED, True))
        dialog.exec()

    def _restart_elevated_from_prompt(self) -> None:
        """Relaunch elevated. If the prompt is cancelled the app keeps
        running and the detection is re-armed so the user can try again."""
        from utils import win32_elevation
        ok = win32_elevation.relaunch_elevated(
            flush_settings=getattr(self.settings_manager, "save", None),
            on_success_shutdown=self._shutdown_and_quit,
        )
        if not ok:
            try:
                self.session.input_service.reset_uipi_latch()
            except Exception:  # noqa: BLE001
                pass

    # ── Hotkeys ────────────────────────────────────────────────────────────

    def _wire_hotkeys(self) -> None:
        from utils.hotkey_dispatch import build_dispatch
        from utils.hotkey_wiring import HotkeyWiring
        self._hotkey_dispatch = build_dispatch(
            mode_controller=_NoFloatMode(),
            launch_tab=self.launch_tab,
            session=self.session,
            settings_manager=self.settings_manager,
            load_profile=self.load_profile_slot,
        )
        self.hotkeys = HotkeyWiring(
            window_manager=self.window_manager,
            settings_manager=self.settings_manager,
            input_service=self.session.input_service,
            key_event_queue=self.session.key_event_queue,
            on_action=self._on_hotkey_action,
            parent=self,
        )

    def _on_hotkey_action(self, action_id: str) -> None:
        # While a settings capture button is recording, a provider-side fire
        # of the very chord being re-recorded must not trigger its action.
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
        except Exception as e:  # noqa: BLE001
            print(f"[GlobalHotkeys] {action_id} handler error: {e}")

    @Slot(int)
    def load_profile_slot(self, index: int) -> None:
        self.session.load_profile(index)
        self.settings_manager.set("active_profile", index)
        self.log(f"[Profile] Loaded profile {index + 1}")

    # ── Looks ──────────────────────────────────────────────────────────────

    def _on_look_saved(self, game: str, toon_name: str) -> None:
        """A look was saved in the launcher's appearance editor, which has
        already repainted its own cards. The session re-resolves the accent
        of the toons playing it, for the strips."""
        self.session.customization_changed(game, toon_name)
        if self.strips is not None:
            self.strips.customization_changed(game, toon_name)

    # ── Strips ─────────────────────────────────────────────────────────────

    def _build_strips(self):
        """One float strip per toon, driven by the session. Built here and
        started once the window is assembled; None if they cannot be built
        (the window still works as a launcher)."""
        try:
            import inspect
            from utils.strips.controller import StripController
            kwargs = {"keymap_manager": self.keymap_manager,
                      "settings_manager": self.settings_manager, "parent": self}
            if "launcher" in inspect.signature(StripController.__init__).parameters:
                kwargs["launcher"] = self.launcher_port
            strips = StripController(self.session, **kwargs)
        except Exception as e:  # noqa: BLE001
            print(f"[NextUI] float strips unavailable: {e!r}")
            return None
        strips.appearance_requested.connect(self._on_strip_appearance)
        strips.open_window_requested.connect(self._on_strip_open_window)
        quit_requested = getattr(strips, "quit_requested", None)
        if quit_requested is not None:
            quit_requested.connect(self.quit_app)
        set_chat = getattr(strips, "set_chat_active", None)
        if set_chat is not None:
            self.chat_active_changed.connect(set_chat)
        return strips

    def show_window(self) -> None:
        """Bring the window in front of the user, from hidden or minimized."""
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _on_strip_open_window(self, target: str) -> None:
        """The home block's Settings / Open MultiTool / Open full Launcher."""
        if target == "settings":
            self.request_window(lifecycle.SETTINGS)
        elif target == "launcher":
            self.request_window(lifecycle.LAUNCHER)
        else:                                   # "main": as it was left
            self.request_window(lifecycle.CURRENT)

    def _on_strip_appearance(self, game: str, toon_name: str) -> None:
        """A strip's "Change color": this window, on that toon's look."""
        self.request_window(lifecycle.LAUNCHER)
        if not self.launch_tab.open_appearance_for_toon(game, toon_name):
            self.log(f"[NextUI] no saved account has {toon_name}: "
                     "its look opens once it has been seen on an account")

    def quit_app(self) -> None:
        """Quit for good, whatever the lifecycle would do with a close: the
        home menu's and the tray's Quit. Same shutdown order as closing the
        window with nothing running (strips first)."""
        self._quitting = True
        if not self.close():
            # A close that did not reach closeEvent (the window was never
            # shown) still ends the app.
            self._shutdown_and_quit()

    # ── Lifecycle and tray ─────────────────────────────────────────────────

    def _build_lifecycle_and_tray(self) -> None:
        """One authority on when this window shows, hides, minimizes or
        quits (utils/widgets/launchpad/lifecycle.py), and the tray icon that
        brings it back."""
        from utils.widgets.launchpad.tray import LaunchpadTray
        self.tray = LaunchpadTray(self.settings_manager, parent=self)
        self.tray.launch_accounts_requested.connect(
            lambda: self.request_window(lifecycle.LAUNCHER))
        self.tray.settings_requested.connect(
            lambda: self.request_window(lifecycle.SETTINGS))
        # Open MultiTool brings the window back as it was left: hiding does
        # not close a sheet, so whatever was open is still open.
        self.tray.open_requested.connect(
            lambda: self.request_window(lifecycle.CURRENT))
        self.tray.stop_all_requested.connect(self.session.stop)
        self.tray.start_all_requested.connect(self.session.start)
        self.tray.quit_requested.connect(self.quit_app)
        self.session.running_changed.connect(self.tray.set_running)
        self.tray.set_running(self.session.is_running())

        self.lifecycle = lifecycle.WindowLifecycle(
            hide_when_toons_up=bool(self.settings_manager.get(
                HIDE_WINDOW_WHEN_TOONS_UP, HIDE_WINDOW_WHEN_TOONS_UP_DEFAULT)),
            tray_available=self.tray.reachable())
        # main.py shows the window right after building it, so the start's
        # "show on the launcher" is already what happens.
        self.lifecycle.started(live_windows=len(self.session.toons()))
        self._launch_states = self._read_launch_states()
        self._refresh_tray_count()
        self.launch_tab.launch_states_changed.connect(self._on_launch_states_changed)
        self.launcher_port.changed.connect(self._refresh_tray_count)
        self.session.toons_changed.connect(self._on_live_toons_changed)

    def request_window(self, target: str = lifecycle.LAUNCHER,
                       account_id: str | None = None) -> None:
        """Show this window on `target` (the launcher, a sheet or an
        account): the home block's and the tray's way in."""
        self._run_lifecycle(self.lifecycle.requested(target, account_id))

    def _sync_tray_reachability(self) -> None:
        """The tray can come and go (setting, a panel restarting): tell the
        lifecycle before it decides between hiding and minimizing."""
        self._run_lifecycle(self.lifecycle.tray_changed(self.tray.reachable()),
                            "no tray to bring it back")

    def _run_lifecycle(self, commands, reason: str = "") -> None:
        """Carry out the lifecycle's commands. The one place this window is
        shown, hidden, minimized or quit on the lifecycle's say."""
        for cmd in commands:
            if cmd.kind == lifecycle.SHOW:
                self.show_window()
                if cmd.target == lifecycle.LAUNCHER:
                    self.open_sheet(None)
                elif cmd.target == lifecycle.ACCOUNTS:
                    self.open_sheet(SHEET_ACCOUNTS)
                elif cmd.target == lifecycle.KEYSETS:
                    self.open_sheet(SHEET_KEYSETS)
                elif cmd.target == lifecycle.SETTINGS:
                    self.open_sheet(SHEET_SETTINGS)
                elif cmd.target == lifecycle.ACCOUNT:
                    self.open_sheet(SHEET_ACCOUNTS)
                    sheet = self._sheets.get(SHEET_ACCOUNTS)
                    if sheet is not None and hasattr(sheet, "open_account"):
                        sheet.open_account(cmd.account_id)
                if reason:
                    print(f"[NextUI] window shown: {reason}")
            elif cmd.kind == lifecycle.HIDE:
                self.hide()
                print(f"[NextUI] window hidden: {reason}")
            elif cmd.kind == lifecycle.MINIMIZE:
                self.showMinimized()
                print(f"[NextUI] window minimized (no tray to bring it back): {reason}")
            elif cmd.kind == lifecycle.QUIT:
                print(f"[NextUI] quitting: {reason}")
                self.quit_app()

    def _read_launch_states(self) -> dict[str, str]:
        """idle | launching | running | failed per account. Accounts waiting
        in a staggered party launch count as launching."""
        from utils.launcher_port import STATE_LAUNCHING, STATE_RUNNING, port_state
        from services.ttr_login_service import LoginState
        staged = self.launch_tab.staged_launches()
        out = {}
        for item in self.launch_tab.launch_overview():
            aid, raw = item["account_id"], item["state"]
            state = port_state(raw)
            if aid in staged or state == STATE_LAUNCHING:
                out[aid] = "launching"
            elif state == STATE_RUNNING:
                out[aid] = "running"
            elif raw == LoginState.FAILED:
                out[aid] = "failed"
            else:
                out[aid] = "idle"
        return out

    def _on_launch_states_changed(self) -> None:
        """Turn the launcher's state changes into pending / landed / failed.
        A launch that falls back to idle (cancelled) counts as failed: it
        ended without a game window, so the window stays up."""
        before, now = self._launch_states, self._read_launch_states()
        self._launch_states = now
        self._sync_tray_reachability()
        commands = []
        for aid in set(before) | set(now):
            was, is_ = before.get(aid, "idle"), now.get(aid, "idle")
            if is_ == "launching" and was != "launching":
                commands += self.lifecycle.launch_pending(aid)
            elif was == "launching" and is_ == "running":
                commands += self.lifecycle.launch_landed(aid)
            elif was == "launching" and is_ != "launching":
                commands += self.lifecycle.launch_failed(aid)
        self._run_lifecycle(commands, "all launches landed")
        self._refresh_tray_count()

    def _on_live_toons_changed(self) -> None:
        self._run_lifecycle(self.lifecycle.windows(len(self.session.toons())),
                            "last game window closed")

    def _refresh_tray_count(self) -> None:
        from utils.launcher_port import STATE_RUNNING
        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.set_running_count(sum(
                1 for a in self.launcher_port.accounts() if a.state == STATE_RUNNING))

    # ── Settings sheet ─────────────────────────────────────────────────────

    def _build_settings_sheet(self) -> None:
        """The Settings sheet, wired the way the classic window wires its
        Settings tab."""
        from utils.widgets.launchpad.settings_sheet import SettingsSheet
        sheet = SettingsSheet(
            self.settings_manager, self.keymap_manager,
            self.launch_tab.cred_manager,
            logs_widget=getattr(self.debug_tab, "card", None),
            is_dark=self._is_dark())
        self.settings_sheet = sheet
        rows = sheet.rows
        # main.py reaches the settings rows through this name (the Corporate
        # Clash install picker refreshes them after a pick).
        self.settings_tab = rows
        self.register_sheet(SHEET_SETTINGS, sheet)
        sheet.header_changed.connect(self._on_settings_header)

        # Theme and verbose logging are written to settings by the rows and
        # handled once in _on_setting_changed; connecting the rows' own
        # signals as well would run each handler twice.
        rows.input_backend_changed.connect(self.session.restart_router)
        rows.clear_credentials_requested.connect(self._on_clear_credentials)
        # chat_handling_mode_changed has no listener: the session reads the
        # mode from settings on every keystroke, and there are no chat
        # buttons here to show or hide.
        rows.set_hotkey_accounts_provider(
            lambda: self.launch_tab.cred_manager.get_accounts_basic())
        if self.hotkeys is not None:
            self.hotkeys.status_changed.connect(self._on_hotkey_status)
        if hasattr(rows, "set_update_checker"):
            rows.set_update_checker(self.update_checker)

    # ── Accounts sheet ─────────────────────────────────────────────────────

    def _build_accounts_sheet(self) -> None:
        """The Accounts sheet over the launcher's accounts, and the routes
        into it: the launcher's "Accounts" link, a card's gear, "Add
        account", and an account launched with no saved login."""
        from utils.widgets.launchpad.accounts_launcher_backend import (
            LauncherAccountsBackend,
        )
        from utils.widgets.launchpad.accounts_sheet import AccountsSheet
        self.accounts_backend = LauncherAccountsBackend(
            self.launch_tab, customizations=self.session.customizations,
            appearance_opener=self._open_look_from_account, parent=self)
        self.accounts_sheet = AccountsSheet(self.accounts_backend, is_dark=self._is_dark())
        self.register_sheet(SHEET_ACCOUNTS, self.accounts_sheet)
        self.accounts_sheet.launch_login_finished.connect(self._on_launch_login_finished)
        # Accounts whose launch is waiting for a password, in the order they
        # were launched; the first is the one being asked for.
        self._login_requests: list[str] = []
        self._return_to_account: str | None = None
        self.launch_tab.launcher_sheet_closed.connect(self._on_launcher_sheet_closed)
        self.launch_tab.set_accounts_router(self)

    # The launcher's router (LaunchTab.set_accounts_router).

    def show_for(self, target: str, account_id: str | None = None) -> None:
        """Bring the window in front of the user because something needs
        them here: ``target`` says what ("accounts", "account",
        "add_account", "fix_login", "launch_login"), ``account_id`` whose.
        The one place the Accounts routes show the window from."""
        del target, account_id
        self.show_window()

    def open_list(self) -> None:
        self.show_for("accounts")
        self.accounts_sheet.show_list()
        self.open_sheet(SHEET_ACCOUNTS)

    def open_account(self, account_id: str) -> None:
        self.show_for("account", account_id)
        self.open_sheet(SHEET_ACCOUNTS)
        account = self.accounts_backend.account(account_id)
        if account is not None and account.login == "failed" and not account.running:
            self.accounts_sheet.open_fix_login(account_id)
        else:
            self.accounts_sheet.open_account(account_id)

    def open_add(self, game: str) -> None:
        self.show_for("add_account")
        self.open_sheet(SHEET_ACCOUNTS)
        self.accounts_sheet.open_add_form(game)

    def open_fix(self, account_id: str) -> None:
        self.show_for("fix_login", account_id)
        self.open_sheet(SHEET_ACCOUNTS)
        self.accounts_sheet.open_fix_login(account_id)

    def request_login(self, game: str, account_id: str) -> None:
        """An account was launched with nothing to sign in with: ask for its
        password. Several at once (a party) are asked one after another;
        the accounts that have a login launch meanwhile."""
        del game
        if account_id not in self._login_requests:
            self._login_requests.append(account_id)
        if self.accounts_sheet.launch_login_account() is None:
            self._ask_next_login()

    def _ask_next_login(self) -> None:
        while self._login_requests:
            account_id = self._login_requests[0]
            self.show_for("launch_login", account_id)
            self.open_sheet(SHEET_ACCOUNTS)
            if self.accounts_sheet.open_launch_login(account_id):
                return
            self._login_requests.pop(0)         # the account is gone

    def _on_launch_login_finished(self, account_id: str, launched: bool) -> None:
        if account_id in self._login_requests:
            self._login_requests.remove(account_id)
        if self._login_requests:
            # After this answer has finished being handled.
            QTimer.singleShot(0, self._ask_next_login)
        elif launched and self.open_sheet_name() == SHEET_ACCOUNTS:
            self.open_sheet(None)               # back to the launcher, logging in

    def _open_look_from_account(self, account_id: str, game: str, toon_name: str) -> None:
        """A toon slot's pencil: the launcher's Appearance editor on that
        toon. Closing the editor comes back to the account's page."""
        self._return_to_account = account_id
        self.open_sheet(None)
        if not self.launch_tab.open_appearance_for_toon(game, toon_name, account_id):
            self._return_to_account = None

    def _on_launcher_sheet_closed(self) -> None:
        account_id, self._return_to_account = self._return_to_account, None
        if account_id is not None and self.accounts_backend.account(account_id) is not None:
            self.open_sheet(SHEET_ACCOUNTS)
            self.accounts_sheet.open_account(account_id)

    def _on_settings_header(self, title: str, sub: str) -> None:
        if self.open_sheet_name() == SHEET_SETTINGS:
            self.sheet_host.set_header(title, sub)

    def _on_hotkey_status(self, failures) -> None:
        try:
            self.settings_sheet.rows.set_hotkey_status(failures)
        except Exception:  # noqa: BLE001
            pass

    def _on_clear_credentials(self) -> None:
        self.launch_tab.clear_all_credentials()
        self.log("[Credentials] All stored credentials have been cleared from "
                 "Keyring and session memory.")

    # ── Sheets ─────────────────────────────────────────────────────────────

    def register_sheet(self, name: str, content: QWidget) -> None:
        """Mount ``content`` as the sheet behind the header button ``name``
        (one of SHEET_ACCOUNTS / SHEET_KEYSETS / SHEET_SETTINGS)."""
        if name not in SHEET_TITLES:
            raise ValueError(f"unknown sheet {name!r}")
        was_open = self.open_sheet_name() == name
        if content.parent() is None:
            # Owned by the window from the start (the host adopts it when it
            # is first opened), so it goes when the window goes.
            content.setParent(self.sheet_host)
            content.hide()
        self._sheets[name] = content
        self._sheet_names = {id(widget): key for key, widget in self._sheets.items()}
        if was_open:
            self.open_sheet(name)

    def _launcher_game(self) -> str:
        """The game the launcher is showing."""
        view = getattr(self.launch_tab, "grandstand", None)
        try:
            game = view.active_game() if view is not None else None
        except Exception:  # noqa: BLE001
            game = None
        return game if game in ("ttr", "cc") else "ttr"

    def _build_sheet(self, name: str) -> QWidget:
        if name == SHEET_KEYSETS:
            from utils.widgets.launchpad.keysets_sheet import KeysetsSheet
            return KeysetsSheet(self.keymap_manager, self.settings_manager,
                                game=self._launcher_game(), is_dark=self._is_dark())
        placeholder = _SheetPlaceholder(SHEET_TITLES[name][0])
        placeholder.apply_theme(self._is_dark())
        return placeholder

    def _sheet_content(self, name: str) -> QWidget:
        content = self._sheets.get(name)
        if content is None:
            content = self._build_sheet(name)
            if content.parent() is None:
                content.setParent(self.sheet_host)
                content.hide()
            self._sheets[name] = content
            self._sheet_names[id(content)] = name
        return content

    def open_sheet_name(self) -> str | None:
        """The sheet that is showing, or None."""
        if not self.sheet_host.is_open():
            return None
        return self._sheet_names.get(id(self.sheet_host.current_content()))

    def open_sheet(self, name: str | None) -> None:
        """Show sheet ``name``; None closes whatever is open."""
        if name is None:
            self.sheet_host.close()
            return
        content = self._sheet_content(name)
        if name == SHEET_KEYSETS and self.open_sheet_name() != name \
                and hasattr(content, "set_game"):
            # Opens on the game the launcher is showing.
            content.set_game(self._launcher_game())
        title, sub = SHEET_TITLES[name]
        sub_of = getattr(content, "sub", None)
        title_of = getattr(content, "title", None)
        self.sheet_host.open(
            content,
            getattr(content, "IDENTITY", SHEET_IDENTITY[name]),
            title_of() if callable(title_of) else getattr(content, "TITLE", title),
            sub_of() if callable(sub_of) else getattr(content, "SUB", sub))
        attach = getattr(content, "attach_host", None)
        if callable(attach):
            # The sheet drives its own header and back button from here on.
            attach(self.sheet_host)
        else:
            self.sheet_host.set_back(None)

    def _on_sheet_button(self, name: str) -> None:
        target = next_open_sheet(self.open_sheet_name(), name)
        if target == SHEET_ACCOUNTS and hasattr(self, "accounts_sheet"):
            self.accounts_sheet.show_list()     # the button opens the list
        self.open_sheet(target)

    def _on_sheet_content_changed(self, content) -> None:
        # The lit button is the one whose sheet is open.
        self.header.set_open_sheet(
            self._sheet_names.get(id(content)) if content is not None else None)

    def _on_sheet_closed(self) -> None:
        self.header.set_open_sheet(None)
        sheet = getattr(self, "accounts_sheet", None)
        if sheet is not None and sheet.launch_login_account() is not None:
            # Closing the sheet on a launch question is a Cancel.
            sheet.cancel_launch_login()

    # ── Header state ───────────────────────────────────────────────────────

    def _refresh_session_status(self) -> None:
        self.header.set_toon_count(len(self.session.toons()))

    def _toggle_hints(self) -> None:
        self._hints_enabled = not self._hints_enabled
        self.settings_manager.set("hints_enabled", self._hints_enabled)
        self.header.set_hints_enabled(self._hints_enabled)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.ToolTip and not self._hints_enabled:
            # The hints toggle's own tooltip always shows.
            if hasattr(obj, "property") and obj.property("_always_tooltip"):
                return False
            return True
        return False

    # ── Theme ──────────────────────────────────────────────────────────────

    def _is_dark(self) -> bool:
        return resolve_theme(self.settings_manager) == "dark"

    def _theme_colors(self):
        return get_theme_colors(self._is_dark())

    def _apply_full_theme(self) -> None:
        colors = self._theme_colors()
        is_dark = self._is_dark()
        self._apply_window_corner_state(self.isMaximized(), force=True)
        self._notify_chrome_theme()
        self.header.apply_theme(is_dark, QColor(colors["sidebar_text"]))
        self.header.set_hints_enabled(self._hints_enabled)
        self.debug_tab.apply_theme(is_dark)
        self.update_banner.apply_theme(colors)
        self.admin_notice_banner.apply_theme(colors)
        self.launch_tab.refresh_theme()
        self.sheet_host.apply_theme(is_dark)
        for content in self._sheets.values():
            if content is not self.sheet_host.current_content() \
                    and hasattr(content, "apply_theme"):
                content.apply_theme(is_dark)

    def on_theme_changed(self) -> None:
        apply_theme(QApplication.instance(), resolve_theme(self.settings_manager))
        self._apply_full_theme()

    @Slot(str)
    def _on_system_color_scheme_changed(self, _value: str) -> None:
        # Only "system" follows the OS; an explicit light or dark stays put.
        if self.settings_manager.get("theme", "system") == "system":
            self.on_theme_changed()

    def _on_setting_changed(self, key, value) -> None:
        if key == HIDE_WINDOW_WHEN_TOONS_UP and getattr(self, "lifecycle", None):
            self.lifecycle.setting_changed(bool(value))
        elif key == TRAY_ICON and getattr(self, "lifecycle", None):
            self._sync_tray_reachability()
        if key == "theme":
            self.on_theme_changed()
        elif key == "show_debug_tab":
            show = bool(value)
            self.debug_tab.logging_enabled = show
            self.session.input_service.logging_enabled = show
            ttr_api.set_debug(show)

    # ── Window chrome ──────────────────────────────────────────────────────

    def _apply_window_chrome(self) -> None:
        """Frameless window with custom controls and a rounded translucent
        shell, unless the setting asks for the native title bar. Window flags
        and translucency are set once, before the first show, so the setting
        takes effect on restart."""
        self.container.setObjectName("app_card")
        self.container.setAttribute(Qt.WA_StyledBackground, True)
        # Window-state gestures have no end signal: flush the perf trace on a
        # short debounce restarted by each state change.
        self._perf_state_flush = QTimer(self)
        self._perf_state_flush.setSingleShot(True)
        self._perf_state_flush.setInterval(150)
        self._perf_state_flush.timeout.connect(perf_trace.flush)
        self._perf_state_gid = ""
        self._perf_state_fires = 0
        if bool(self.settings_manager.get("use_system_title_bar", False)):
            self.setAttribute(Qt.WA_TranslucentBackground, False)
            self._apply_window_corner_state(self.isMaximized(), force=True)
            return
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        if _OPAQUE_MASK_CHROME:
            self.setAttribute(Qt.WA_TranslucentBackground, False)
            self._mask_cache = None
        else:
            self.setAttribute(Qt.WA_TranslucentBackground, True)
        from utils.widgets.window_chrome import WindowChromeController
        self._chrome = WindowChromeController(self, self.header)
        self._chrome.reposition()
        self._apply_window_corner_state(self.isMaximized(), force=True)
        self._update_window_mask()
        # The theme pass above ran before the controller existed.
        self._notify_chrome_theme()

    def _apply_window_corner_state(self, is_maximized: bool, force: bool = False) -> None:
        """Rounded card, outline, lit rim and layout insets for the current
        state: frameless and not maximized is a 16 px rounded card; maximized
        or native title bar is square with no insets. The full-tree restyle
        is expensive, so it is skipped when neither state nor theme changed."""
        colors = self._theme_colors()
        bg = colors["bg_app"]
        native = bool(self.settings_manager.get("use_system_title_bar", False))
        signature = corner_state_signature(is_maximized, native, bg)
        if should_skip_restyle(getattr(self, "_last_corner_sig", None), signature, force):
            return
        self._last_corner_sig = signature
        rounded = (not native) and (not is_maximized)
        root = self.container.layout()
        # The unprefixed QWidget rule cascades bg_app to every descendant (the
        # launcher relies on it); the object-scoped card rule is more
        # specific, so the card keeps its rounded fill.
        cascade = f"\nQWidget {{ background: {bg}; }}"
        gid = getattr(self, "_perf_state_gid", "")
        with perf_trace.perf_span("apply_corner_state", gid):
            if rounded:
                edge = window_edge_colors(bg)
                self.container.setStyleSheet(
                    card_qss("app_card", bg, RADIUS_NORMAL, edge["outline"]) + cascade)
                self.header.setStyleSheet(header_top_radius_qss(
                    colors["header_bg"], None, RADIUS_NORMAL, top_rim=edge["rim"]))
                if root is not None:
                    root.setContentsMargins(
                        STROKE_INSET, STROKE_INSET, STROKE_INSET, BOTTOM_INSET)
                self._frame_sheet_host(STROKE_INSET, RADIUS_NORMAL - STROKE_INSET)
            else:
                self.container.setStyleSheet(
                    card_qss("app_card", bg, RADIUS_MAXIMIZED, None) + cascade)
                self.header.setStyleSheet(
                    header_top_radius_qss(colors["header_bg"], None, RADIUS_MAXIMIZED))
                if root is not None:
                    root.setContentsMargins(0, 0, 0, 0)
                self._frame_sheet_host(0, 0)
        self._update_window_mask()

    def _frame_sheet_host(self, inset: int, bottom_radius: int) -> None:
        """The sheet and its scrim follow the card's rounded bottom corners."""
        host = getattr(self, "sheet_host", None)
        if host is not None and hasattr(host, "set_frame"):
            host.set_frame(inset, bottom_radius)

    def _update_window_mask(self) -> None:
        """Opaque-chrome experiment only (TTMT_OPAQUE_MASK_CHROME): mask the
        top-level to rounded corners, or clear the mask when maximized."""
        if not _OPAQUE_MASK_CHROME:
            return
        from utils.window_chrome_mask import rounded_region
        native = bool(self.settings_manager.get("use_system_title_bar", False))
        if native or self.isMaximized():
            if getattr(self, "_mask_cache", None) is not None:
                self.clearMask()
                self._mask_cache = None
            return
        key = (self.width(), self.height(), RADIUS_NORMAL)
        if key == getattr(self, "_mask_cache", None):
            return
        self.setMask(rounded_region(*key))
        self._mask_cache = key

    def _notify_chrome_theme(self) -> None:
        chrome = getattr(self, "_chrome", None)
        if chrome is not None and hasattr(chrome, "set_theme"):
            from utils.widgets.window_chrome_style import is_dark_bg
            chrome.set_theme(is_dark_bg(self._theme_colors()["bg_app"]))

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            self._observe_window()
        if event.type() != QEvent.WindowStateChange or self._chrome is None:
            return
        flush_timer = getattr(self, "_perf_state_flush", None)
        if flush_timer is not None:
            if not flush_timer.isActive():
                self._perf_state_gid = perf_trace.begin_gesture("window_state")
                self._perf_state_fires = 0
            self._perf_state_fires += 1
            perf_trace.mark("statechange_fires", self._perf_state_gid,
                            self._perf_state_fires)
        self._apply_window_corner_state(self.isMaximized())
        if flush_timer is not None:
            flush_timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_window_mask()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._observe_window()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._observe_window()

    def _observe_window(self) -> None:
        """The user minimized or restored the window (or the lifecycle did):
        keep the lifecycle's idea of it true."""
        lc = getattr(self, "lifecycle", None)
        if lc is None:
            return
        if self.isMinimized():
            lc.observed(lifecycle.MINIMIZED)
        elif self.isVisible():
            lc.observed(lifecycle.VISIBLE)
        else:
            lc.observed(lifecycle.HIDDEN)

    def _capture_multitool_window_id(self) -> None:
        # xdotool is X11-only; the gate is the Qt platform, not the session
        # type: under the default xcb platform a Wayland session runs this
        # window through XWayland, which xdotool can drive.
        if sys.platform != "linux":
            return
        if os.environ.get("QT_QPA_PLATFORM", "").lower() == "wayland":
            return
        try:
            win_id = subprocess.check_output(
                ["xdotool", "search", "--name", "ToonTown MultiTool"],
                stderr=subprocess.DEVNULL, timeout=0.5,
            ).decode().strip().split("\n")[0]
            self.settings_manager.set("multitool_window_id", win_id)
        except Exception:  # noqa: BLE001
            print("[Main] Warning: Failed to get MultiTool window ID.")

    # ── Updates ────────────────────────────────────────────────────────────

    def _setup_update_checker(self) -> None:
        from utils.update_checker import UpdateChecker
        from utils.update_runner import UpdateRunner
        self.update_checker = UpdateChecker(self.settings_manager, parent=self)
        self.update_runner = UpdateRunner(self)
        self.update_checker.update_available.connect(self._on_update_available)

    def _maybe_kick_off_startup_check(self) -> None:
        # --self-check must not start the update thread: it can block
        # mid-flight and abort at interpreter teardown.
        if os.environ.get("TTMT_SELF_CHECK"):
            return
        if not bool(self.settings_manager.get("check_for_updates_at_startup", False)):
            return
        self.update_checker.check_async(manual=False)

    def _on_update_available(self, info) -> None:
        self._pending_update_info = info
        self.update_banner.show_for_release(info)

    def _on_update_banner_clicked(self) -> None:
        info = self._pending_update_info
        if info is None:
            return
        from utils import build_info
        from utils.widgets.update_dialog import UpdateDialog
        dialog = UpdateDialog(info, local_version_string=build_info.version_string(),
                              parent=self)
        dialog.update_now.connect(lambda: self.update_runner.run_update(info))
        dialog.skip_version.connect(
            lambda: self.settings_manager.set("update_skipped_version", info["tag_name"]))
        dialog.skip_version.connect(self.update_banner.hide)
        dialog.exec()

    # ── Administrator notice (Windows) ─────────────────────────────────────

    def _maybe_show_admin_notice(self) -> None:
        from utils.settings_keys import WINDOWS_ADMIN_NOTICE_DISMISSED
        from utils.win32_elevation import startup_prompt_declined
        from utils.win32_integrity import is_running_elevated, should_show_admin_notice
        dismissed = bool(self.settings_manager.get(WINDOWS_ADMIN_NOTICE_DISMISSED, False))
        # A launch that just declined the administrator prompt always gets
        # the warning, even if the banner was dismissed on an earlier launch.
        dismissed = dismissed and not startup_prompt_declined()
        if should_show_admin_notice(sys.platform == "win32", is_running_elevated(), dismissed):
            self.admin_notice_banner.show()

    def _on_admin_notice_restart(self) -> None:
        from utils import win32_elevation
        self.admin_notice_banner.set_restart_enabled(False)
        ok = win32_elevation.relaunch_elevated(
            flush_settings=getattr(self.settings_manager, "save", None),
            on_success_shutdown=self._shutdown_and_quit,
        )
        if not ok:
            self.admin_notice_banner.set_restart_enabled(True)

    def _on_admin_notice_dismissed(self) -> None:
        from utils.settings_keys import WINDOWS_ADMIN_NOTICE_DISMISSED
        self.settings_manager.set(WINDOWS_ADMIN_NOTICE_DISMISSED, True)
        self.admin_notice_banner.hide()

    def _shutdown_and_quit(self) -> None:
        try:
            self.shutdown()
        finally:
            _quit_app()

    # ── Keep-alive ─────────────────────────────────────────────────────────

    def _on_keep_alive_inhibit_status(self, status) -> None:
        """Warn once per launch when keep-alive runs but the machine's sleep
        could not be held off. A held sleep lock never warns."""
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

    # ── TTR settings ───────────────────────────────────────────────────────

    def _apply_startup_ttr_keymap(self) -> int:
        """Fill keyset 0 from TTR's settings.json, or from the copy cached by
        the last run that could read it. Returns the number of controls
        applied."""
        from utils.ttr_settings import apply_ttr_controls_to_set
        live = self._refresh_ttr_settings()
        if live is not None:
            count = apply_ttr_controls_to_set(self.keymap_manager, 0, live.controls)
            self.settings_manager.set("last_detected_keymap", live.controls)
            print(f"[main] TTR settings auto-detected from {live.source_path} "
                  f"({count} controls)")
            return count
        cached = self.settings_manager.get("last_detected_keymap", None)
        if isinstance(cached, dict) and cached:
            count = apply_ttr_controls_to_set(self.keymap_manager, 0, cached)
            print(f"[main] TTR settings.json unreadable; applied cached keymap "
                  f"({count} controls)")
            return count
        return 0

    def _refresh_ttr_settings(self):
        """Locate and parse TTR's settings.json; None when it cannot be read.
        Tries the stored engine directory, then auto-detection."""
        from services.ttr_login_service import find_engine_path
        from utils.ttr_settings import locate_settings_file, parse_ttr_settings
        engine_dir = self.settings_manager.get("ttr_engine_dir", "") or None
        if not engine_dir:
            engine_dir = find_engine_path() or None
        path = locate_settings_file(engine_dir=engine_dir)
        if not path:
            return None
        try:
            return parse_ttr_settings(path)
        except Exception as e:  # noqa: BLE001
            print(f"[main] TTR settings parse failed: {e}")
            return None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        print(f"[shutdown] entered pid={os.getpid()} complete={self._shutdown_complete}")
        if self._shutdown_complete:
            return
        self._shutdown_complete = True
        # Each step is isolated so one failure cannot skip the rest: leaving
        # the window manager's poll thread alive locks the terminal. The
        # getattr guard covers a quit that lands while __init__ is still
        # partway through.
        for label, attribute, method in (
            ("strips", "strips", "shutdown"),
            ("tray", "tray", "shutdown"),
            ("hotkeys", "hotkeys", "stop"),
            ("launch_tab", "launch_tab", "shutdown"),
            ("session", "session", "shutdown"),
            ("window_manager", "window_manager", "stop"),
            ("update_checker", "update_checker", "shutdown"),
        ):
            target = getattr(self, attribute, None)
            if target is None:
                print(f"[shutdown]    skipped: {attribute} not set yet")
                continue
            print(f"[shutdown] -> {label}.{method}()")
            try:
                getattr(target, method)()
                print(f"[shutdown]    {label}.{method}() returned")
            except Exception as e:  # noqa: BLE001
                print(f"[CloseEvent] {label} shutdown error: {e}")
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)     # installed app-wide for hover hints
        print(f"[shutdown] complete pid={os.getpid()}")

    def closeEvent(self, event) -> None:
        print(f"[closeEvent] entered pid={os.getpid()}")
        lc = getattr(self, "lifecycle", None)
        if not self._quitting and lc is not None and not self._shutdown_complete:
            self._sync_tray_reachability()
            commands = lc.close_requested()
            if not any(c.kind == lifecycle.QUIT for c in commands):
                # Game windows (or launches) are still up: the window steps
                # aside, the app keeps running behind the strips and tray.
                event.ignore()
                self._run_lifecycle(commands, "closed while toons are up")
                print(f"[closeEvent] kept running pid={os.getpid()}")
                return
            self._quitting = True
            print("[NextUI] quitting: closed with no game windows and nothing launching")
        self.shutdown()
        super().closeEvent(event)
        if event.isAccepted():
            _quit_app()
        print(f"[closeEvent] exiting pid={os.getpid()}")
