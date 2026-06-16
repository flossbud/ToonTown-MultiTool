"""
Launch Tab - Manage TTR and Corporate Clash accounts and launch game instances.

Accounts are tagged per-game ("ttr" or "cc") and displayed in two LaunchSection
widgets (TTR + CC) stacked inside a single scroll area. Each section owns a
2-column tile grid plus its own launcher-button + add-account UI. Workers and
launchers are stored per-game so TTR and CC never interfere.
"""
from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt, QObject, Signal, QThread, Slot, QTimer

from utils.theme_manager import resolve_theme, get_theme_colors
from utils.credentials_manager import CredentialsManager, set_debug_log_callback
from utils.open_url import open_url
from services.ttr_login_service import (
    TTRLoginWorker, LoginState, find_engine_path, get_engine_executable_name,
    engine_binary_path,
)
from services.ttr_launcher import TTRLauncher
from services.ttr_patcher import TTRPatcher
from services.cc_patcher import CCPatcher
from services.cc_login_service import (
    CCLoginWorker,
    find_cc_engine_path,
    get_cc_engine_executable_name,
    revoke_launcher_token,
)
from services.cc_launcher import CCLauncher
from services.wine_runtimes import (
    classify_path,
    discover_cc_installs,
    install_signature,
    WineInstall,
)
from services.launcher_runners import (
    run_official_ttr_launcher,
    run_official_cc_launcher,
)
from utils.settings_keys import (
    CC_ENGINE_INSTALL_SIGNATURE,
    LAUNCH_QUIT_CONFIRM_DISMISSED,
    LAUNCH_SECTION_TTR_COLLAPSED,
    LAUNCH_SECTION_CC_COLLAPSED,
)
from utils.widgets import install_modern_scrollbar
from utils.widgets.cc_install_picker import CCInstallPickerDialog  # noqa: F401
from utils.widgets.launch_section import LaunchSection, PAGE_SIZE, page_count
from utils.widgets.account_editor import AccountEditor
from utils.widgets.account_reorder_dialog import AccountReorderDialog
from utils.widgets.confirm_dialog import ConfirmDialog
from utils.widgets.error_modal import ErrorModal
from utils.launch_tab_demo_mode import get_demo_fixtures


MAX_PER_GAME = 16  # hard ceiling per game (TTR / CC)
LINUX_KEYRING_HELP_URL = "https://wiki.archlinux.org/title/Secret_Service"


@dataclass
class AccountSlot:
    """Per-account runtime state, keyed by stable account id."""
    account_id: str
    state: str = LoginState.IDLE
    message: str = ""
    raw_error: str = ""
    worker: object = None
    launcher: object = None
    loading_timer: object = None   # QTimer or None; non-None == active pending
    dot_state: str = ""


def _asset_path(name: str) -> str:
    """Resolve a bundled asset relative to the repo root / PyInstaller _MEIPASS.
    Mirrors tabs/credits_tab.py and main.py:_resolve_app_icon."""
    base = getattr(
        sys, "_MEIPASS",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    return os.path.join(base, "assets", name)


# ── CC multi-install launch gate ──────────────────────────────────────────

def _cc_launch_gate(settings_manager, parent) -> bool:
    """Decide whether a CC launch can proceed.

    Returns True if the launch may proceed. Returns False when multiple
    installs are detected and the user did not pick one via the inline
    picker.
    """
    installs = discover_cc_installs()
    stored_sig = settings_manager.get(CC_ENGINE_INSTALL_SIGNATURE, "")
    if len(installs) > 1:
        sig_match = any(install_signature(i) == stored_sig for i in installs)
        if not sig_match:
            return _prompt_inline_picker(parent, installs, settings_manager)
    elif len(installs) == 1:
        expected = install_signature(installs[0])
        if stored_sig != expected:
            settings_manager.set(CC_ENGINE_INSTALL_SIGNATURE, expected)
    return True


def _prompt_inline_picker(parent, installs, settings_manager) -> bool:
    """Open the install picker directly. Persist the user's choice on
    accept and return True; return False on cancel."""
    stored = settings_manager.get(CC_ENGINE_INSTALL_SIGNATURE, "")
    dlg = CCInstallPickerDialog(
        installs, parent=parent, active_signature=stored or None,
    )
    if dlg.exec() != dlg.DialogCode.Accepted:
        return False
    picked = dlg.selected_install()
    if picked is None:
        return False
    settings_manager.set("cc_engine_dir", os.path.dirname(picked.exe_path))
    settings_manager.set(
        CC_ENGINE_INSTALL_SIGNATURE,
        install_signature(picked),
    )
    settings_manager.set("cc_engine_dir_approved_custom_dir", "")
    return True


# ── Keyring banners ────────────────────────────────────────────────────────

class KeyringProbeWorker(QObject):
    probe_complete = Signal(bool)

    def __init__(self, cred_manager, parent=None):
        super().__init__(parent)
        self._cred_manager = cred_manager

    def run(self):
        self.probe_complete.emit(self._cred_manager.run_probe(timeout=45.0))


class KeyringPendingBanner(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("keyring_pending_banner")
        self.setMaximumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self.header_label = QLabel("⏳  Checking credential storage...")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        self.body_label = QLabel(
            "Waiting for your wallet to respond. You may need to enter\n"
            "your wallet password in the dialog that appeared."
        )
        self.body_label.setWordWrap(True)
        layout.addWidget(self.body_label)

        self.apply_theme(get_theme_colors(True))

    def apply_theme(self, c: dict) -> None:
        """Rebuild QSS from the theme dict `c`."""
        self.setStyleSheet(
            "QFrame#keyring_pending_banner {"
            f" background: {c['bg_card']};"
            f" border: 1px solid {c['border_card']};"
            f" border-left: 3px solid {c['accent_blue']};"
            " border-radius: 10px;"
            "}"
        )
        self.header_label.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {c['text_primary']};"
            " background: transparent; border: none;"
        )
        self.body_label.setStyleSheet(
            f"font-size: 11px; color: {c['text_secondary']};"
            " background: transparent; border: none;"
        )


class KeyringWarningBanner(QFrame):
    def __init__(self, cred_manager, parent=None):
        super().__init__(parent)
        self.cred_manager = cred_manager
        self.setObjectName("keyring_warning_banner")
        self.setMaximumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self.header_label = QLabel("⚠  Credential Storage Unavailable")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        self.body_label = QLabel(
            "No system wallet service was detected. Your account usernames are saved,\n"
            "but passwords will not be remembered between sessions - you'll need to\n"
            "re-enter them each time you launch TTMT."
        )
        self.body_label.setWordWrap(True)
        layout.addWidget(self.body_label)

        self.fix_label = QLabel(self._instruction_text())
        self.fix_label.setWordWrap(True)
        layout.addWidget(self.fix_label)

        self.link_label = QLabel("")
        self.link_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.link_label.linkActivated.connect(open_url)
        self.link_label.setVisible(sys.platform not in ("win32", "darwin"))
        if self.link_label.isVisible():
            self.link_label.setText(f'<a href="{LINUX_KEYRING_HELP_URL}">Open Secret Service setup resources</a>')
            layout.addWidget(self.link_label)

        self.legacy_label = QLabel(
            "A previous insecure credential file was found and deleted. Please re-enter your passwords."
        )
        self.legacy_label.setWordWrap(True)
        self.legacy_label.setVisible(bool(getattr(self.cred_manager, "_legacy_fallback_deleted", False)))
        if self.legacy_label.isVisible():
            layout.addWidget(self.legacy_label)

        self.apply_theme(get_theme_colors(True))

    def _instruction_text(self) -> str:
        if sys.platform == "win32":
            return (
                "Windows Credential Locker stopped responding. Try restarting TTMT.\n"
                "If it keeps happening, please share the keyring-debug.log file when\n"
                "reporting."
            )
        if sys.platform == "darwin":
            return (
                "macOS Keychain was unavailable. Check Keychain Access and ensure\n"
                "your login keychain is unlocked."
            )
        return (
            "To enable password saving, set up a Secret Service wallet:\n\n"
            "• KDE Plasma:   Enable KWallet in System Settings -> KDE Wallet\n"
            "• GNOME:        Install gnome-keyring (usually pre-installed)\n"
            "• Other:        KeePassXC with Secret Service integration enabled,\n"
            "                or Seahorse (GNOME Passwords & Keys)"
        )

    def apply_theme(self, c: dict) -> None:
        """Rebuild QSS from the theme dict `c`."""
        self.setStyleSheet(
            "QFrame#keyring_warning_banner {"
            f" background: {c['bg_card']};"
            f" border: 1px solid {c['border_card']};"
            f" border-left: 3px solid {c['accent_orange_border']};"
            " border-radius: 10px;"
            "}"
        )
        self.header_label.setStyleSheet(
            f"font-size: 13px; font-weight: 700;"
            f" color: {c['accent_orange_border']};"
            " background: transparent; border: none;"
        )
        self.body_label.setStyleSheet(
            f"font-size: 11px; color: {c['text_primary']};"
            " background: transparent; border: none;"
        )
        self.fix_label.setStyleSheet(
            f"font-size: 11px; color: {c['text_secondary']};"
            " background: transparent; border: none;"
        )
        self.link_label.setStyleSheet(
            f"font-size: 10px; color: {c['accent_blue_btn']};"
            " background: transparent; border: none;"
        )
        self.legacy_label.setStyleSheet(
            f"font-size: 10px; color: {c['text_muted']};"
            " background: transparent; border: none;"
        )


class LaunchTab(QWidget):
    # Cross-thread bridge for credential-manager debug messages. Emitted
    # from the keyring probe worker thread; auto-connected to the main-
    # thread DebugTab.append_log slot. See the __init__ comment below.
    _log_to_debug_tab = Signal(str)

    LOADING_WINDOW_TIMEOUT_MS = 30000

    def __init__(self, settings_manager=None, logger=None, parent=None,
                 credentials_manager=None, cred_manager=None,
                 window_manager=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.logger = logger
        if self.logger is not None:
            # Tee credential diagnostics into the in-app log. The keyring
            # probe runs on a worker thread, so the callback fires off the
            # main thread. Cross-thread Qt updates must be signal-queued;
            # see the original launch_tab.py for the full incident note.
            self._log_to_debug_tab.connect(self.logger.append_log)
            set_debug_log_callback(self._log_to_debug_tab.emit)
        # Accept either kwarg name; `cred_manager` is the newer alias.
        self.cred_manager = (
            credentials_manager or cred_manager or CredentialsManager()
        )

        from services.wine_console_hider import WineConsoleHider
        self._wine_console_hider = WineConsoleHider(
            self.settings_manager, parent=self
        )

        # Per-account runtime state, keyed by stable account id. Workers,
        # launchers, and loading timers all live on the AccountSlot.
        self._slots: dict[str, dict[str, AccountSlot]] = {"ttr": {}, "cc": {}}
        self._visible_tiles: dict[str, dict[str, object]] = {"ttr": {}, "cc": {}}
        self._page: dict[str, int] = {"ttr": 0, "cc": 0}
        self._keyring_banner = None
        self._probe_thread = None
        self._probe_worker = None
        self._pending_2fa: set = set()

        # Loading-state orchestration. _loading[game] is a launch-ordered list
        # of account_ids (the timer itself lives on each slot.loading_timer);
        # _window_credit[game] is the count of windows already accounted for at
        # the start of the current loading episode (so pre-existing/other
        # windows don't false-promote a loader).
        self.window_manager = window_manager
        self._loading: dict[str, list] = {"ttr": [], "cc": []}
        self._window_credit: dict[str, int] = {"ttr": 0, "cc": 0}
        if self.window_manager is not None:
            self.window_manager.window_ids_updated.connect(self._on_windows_changed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.NoFrame)

        is_dark = resolve_theme(self.settings_manager) == "dark"
        install_modern_scrollbar(self._scroll, is_dark=is_dark)

        self._scroll_widget = QWidget()
        self._layout = QVBoxLayout(self._scroll_widget)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(12)
        self._layout.setAlignment(Qt.AlignTop)

        self._scroll.setWidget(self._scroll_widget)
        outer.addWidget(self._scroll)

        # Construct the two LaunchSection widgets up front so external code
        # (and tests) can address them as ttr_section / cc_section.
        self.ttr_section = LaunchSection(
            game="ttr", icon_path=_asset_path("ttr.png"),
            parent=self._scroll_widget,
        )
        self.cc_section = LaunchSection(
            game="cc", icon_path=_asset_path("cc.png"),
            parent=self._scroll_widget,
        )
        self._sections = {"ttr": self.ttr_section, "cc": self.cc_section}
        self._layout_mode = "compact"
        self._sections_container: QWidget | None = None

        self._wire_section(self.ttr_section, "ttr")
        self._wire_section(self.cc_section, "cc")

        self._build_ui()
        self.refresh_theme()
        # Restore persisted collapsed state. animate=False to avoid a flash
        # on startup. set_collapsed is a no-op when the value already
        # matches the section's default (expanded), so this is cheap.
        if self.settings_manager is not None:
            self.ttr_section.set_collapsed(
                bool(self.settings_manager.get(LAUNCH_SECTION_TTR_COLLAPSED, False)),
                animate=False,
            )
            self.cc_section.set_collapsed(
                bool(self.settings_manager.get(LAUNCH_SECTION_CC_COLLAPSED, False)),
                animate=False,
            )
        # Diagnostics are logged from _on_keyring_probe_complete after the
        # timed/threaded probe has finished. Calling them here would hit
        # format_backend_diagnostics on the main thread before app.exec(),
        # which can hang on a locked/uninitialized SecretService collection.
        self._start_keyring_probe()

    # ── Helpers ────────────────────────────────────────────────────────────

    def _max_per_game(self) -> int:
        return MAX_PER_GAME

    def _get_engine_dir(self, game: str) -> str:
        """Read the engine directory for a game from settings, with auto-detect fallback."""
        if game == "ttr":
            key, exe_fn, find_fn = "ttr_engine_dir", get_engine_executable_name, find_engine_path
        else:
            key, exe_fn, find_fn = "cc_engine_dir", get_cc_engine_executable_name, find_cc_engine_path

        path = self.settings_manager.get(key, "") if self.settings_manager else ""
        if path:
            engine_bin = (engine_binary_path(path) if game == "ttr"
                          else os.path.join(path, exe_fn()))
            if os.path.isfile(engine_bin):
                return path
        detected = find_fn()
        return detected or ""

    def _build_cc_install(self) -> "WineInstall | None":
        """Construct a WineInstall record for the current CC engine_dir setting.

        Returns None when the setting is empty or the path no longer points at
        a real CorporateClash.exe.
        """
        engine_dir = self.settings_manager.get("cc_engine_dir", "") if self.settings_manager else ""
        print(f"[Launch] _build_cc_install: cc_engine_dir setting={engine_dir!r}")
        if not engine_dir:
            print("[Launch] _build_cc_install: engine_dir empty -> None")
            return None
        exe = os.path.join(engine_dir, get_cc_engine_executable_name())
        if not os.path.isfile(exe):
            print(f"[Launch] _build_cc_install: exe missing at {exe!r} -> None")
            return None
        classified = classify_path(exe)
        print(f"[Launch] _build_cc_install: classify_path -> {classified!r}")
        if classified is not None:
            return classified
        print("[Launch] _build_cc_install: falling back to native WineInstall")
        return WineInstall(
            exe_path=exe,
            launcher="native",
            prefix_path=None,
            display_name=f"Corporate Clash ({engine_dir})",
            metadata={},
        )

    def _ordered_accounts(self, game: str):
        """Accounts for one game in flat cred order (metadata objects)."""
        return [a for a in self.cred_manager.get_accounts_metadata() if a.game == game]

    def _reconcile_slots(self) -> None:
        """Ensure a slot exists for each current account (by id) and drop
        slots whose account is gone. Existing slots (with live workers/
        launchers/timers) are preserved by id."""
        for game in ("ttr", "cc"):
            current = {a.id for a in self._ordered_accounts(game)}
            slots = self._slots[game]
            for aid in current:
                if aid not in slots:
                    slots[aid] = AccountSlot(account_id=aid)
            for aid in list(slots):
                if aid not in current:
                    # Drop any pending loader for a removed account so a stale id
                    # can't linger in _loading[game] (which would spin
                    # _on_windows_changed's promote loop forever).
                    self._discard_loader(game, aid)
                    del slots[aid]

    def _discard_loader(self, game: str, account_id: str) -> None:
        """Stop+clear a slot's loading timer and remove the id from the loading
        queue. Safe whether or not the slot/timer exists."""
        slot = self._slots[game].get(account_id)
        if slot is not None and slot.loading_timer is not None:
            slot.loading_timer.stop()
            slot.loading_timer.deleteLater()
            slot.loading_timer = None
        self._loading_remove(game, account_id)

    def _global_index_of(self, account_id: str) -> int | None:
        for i, a in enumerate(self.cred_manager.get_accounts_metadata()):
            if a.id == account_id:
                return i
        return None

    def _position_of(self, game: str, account_id: str) -> int:
        """1-based position within the game (for 'Account N' user-facing text)."""
        for i, a in enumerate(self._ordered_accounts(game)):
            if a.id == account_id:
                return i + 1
        return 0

    def _loading_add(self, game, account_id):
        if account_id not in self._loading[game]:
            self._loading[game].append(account_id)

    def _loading_remove(self, game, account_id):
        self._loading[game] = [a for a in self._loading[game] if a != account_id]

    def _refresh_activity(self, game: str) -> None:
        ordered = self._ordered_accounts(game)
        pc = page_count(len(ordered))
        self._sections[game].set_activity(self._page_activity(game, ordered, pc))

    def _disconnect_worker_signals(self, worker):
        if not worker:
            return
        for signal_name in ("state_changed", "queue_update", "need_2fa",
                            "login_success", "login_failed",
                            "launcher_token_obtained"):
            try:
                getattr(worker, signal_name).disconnect()
            except Exception:
                pass

    def _disconnect_launcher_signals(self, launcher):
        if not launcher:
            return
        for signal_name in ("game_launched", "game_exited", "launch_failed"):
            try:
                getattr(launcher, signal_name).disconnect()
            except Exception:
                pass

    def _start_keyring_probe(self):
        # --self-check (build oracle) must not touch the keychain: a frozen app's
        # keychain read can BLOCK (different code identity than the dev Python),
        # leaving this probe QThread running at interpreter teardown -> abort
        # (QThread destroyed while running).
        if os.environ.get("TTMT_SELF_CHECK"):
            return
        if self._probe_thread is not None:
            return
        self._probe_thread = QThread(self)
        self._probe_worker = KeyringProbeWorker(self.cred_manager)
        self._probe_worker.moveToThread(self._probe_thread)
        self._probe_thread.started.connect(self._probe_worker.run)
        self._probe_worker.probe_complete.connect(self._on_keyring_probe_complete)
        self._probe_worker.probe_complete.connect(self._probe_thread.quit)
        # Block on the worker thread's true exit before dropping refs to
        # avoid double-delete in QObject::~QObject(); see prior implementation
        # for the full lifecycle commentary.
        self._probe_thread.finished.connect(self._on_probe_thread_finished)
        self._probe_thread.start()

    def _log_keyring_backend_state(self, stage: str):
        from utils.credentials_manager import _dbg
        lines = [f"[Credentials] Keyring diagnostics ({stage})"]
        lines.extend(self.cred_manager.format_backend_diagnostics())
        for line in lines:
            _dbg(line)

    def _on_probe_thread_finished(self):
        if self._probe_thread is not None:
            self._probe_thread.wait(2000)
        self._probe_thread = None
        self._probe_worker = None

    def _set_launch_buttons_enabled(self, enabled: bool):
        # Only visible tiles carry buttons; off-page tiles don't exist and
        # their buttons are created enabled on the next render.
        for game in ("ttr", "cc"):
            for account_id, tile in self._visible_tiles[game].items():
                slot = self._slots[game].get(account_id)
                if slot is not None and slot.state in (
                    LoginState.LOGGING_IN, LoginState.QUEUED, LoginState.LAUNCHING
                ):
                    continue
                btn = getattr(tile, "primary_button", None)
                if btn is None:
                    continue
                btn.setEnabled(enabled)
                if enabled:
                    btn.setToolTip("Log in and launch this account")
                else:
                    btn.setToolTip("Waiting for credential storage...")

    # ── Build UI ───────────────────────────────────────────────────────────

    def _wire_section(self, section: LaunchSection, game: str) -> None:
        # Resolve the runner lazily at click time. Looking the function up on
        # the module each click means monkeypatched tests can swap the
        # implementation between construction and the actual click.
        section.launcher_clicked.connect(lambda g=game: self._on_launcher_clicked(g))
        section.add_account_clicked.connect(lambda g=game: self._on_add_account(g))
        section.tile_launch.connect(lambda a, g=game: self._on_launch(g, a))
        section.tile_quit.connect(lambda a, g=game: self._on_tile_quit(g, a))
        section.tile_cancel.connect(lambda a, g=game: self._on_tile_cancel(g, a))
        section.tile_retry.connect(lambda a, g=game: self._on_launch(g, a))
        section.tile_enter_2fa.connect(lambda a, g=game: self._on_tile_enter_2fa(g, a))
        section.tile_edit.connect(lambda a, g=game: self._on_tile_edit(g, a))
        section.tile_delete.connect(lambda a, g=game: self._on_delete(g, a))
        section.tile_expand_error.connect(lambda a, g=game: self._on_tile_expand_error(g, a))
        section.page_changed.connect(lambda p, g=game: self._on_page_changed(g, p))
        section.reorder_clicked.connect(lambda g=game: self._on_reorder(g))
        # When a section's natural size changes (e.g. resize bumped its
        # content_scale and grew tile min-heights), re-equalize sibling
        # heights in compact mode so the populated card doesn't outgrow
        # the empty card.
        section.content_size_changed.connect(self._sync_compact_section_heights)
        # Persist collapsed-state changes triggered by the user clicking
        # the header. set_collapsed(...) calls from this tab's own
        # restore-on-init path do NOT emit, so the loop is one-directional.
        section.collapsed_changed.connect(
            lambda v, g=game: self._on_section_collapsed_changed(g, v)
        )

    def _on_section_collapsed_changed(self, game: str, value: bool) -> None:
        """Persist the section's new collapsed state. Triggered by the
        section emitting `collapsed_changed` on a user header click."""
        if self.settings_manager is None:
            return
        key = (LAUNCH_SECTION_TTR_COLLAPSED if game == "ttr"
               else LAUNCH_SECTION_CC_COLLAPSED)
        self.settings_manager.set(key, value)
        # Collapsed sections must drop out of the compact-mode height match
        # so a populated sibling can take its natural taller height.
        self._sync_compact_section_heights()

    def _on_launcher_clicked(self, game: str) -> None:
        """Invoke the runner for the section-header 'Launch X Launcher' button.
        Resolved through the module namespace so tests can monkeypatch it.

        For CC, run the same multi-install gate used by per-account launches so
        the button respects the user's chosen install method
        (Faugus/Bottles/Wine/Lutris/Steam-Proton/Native) instead of always
        picking the first discovered install."""
        import tabs.launch_tab as _m
        if game == "cc":
            if not _m._cc_launch_gate(self.settings_manager, parent=self.window()):
                return
            runner = _m.run_official_cc_launcher
            runner_kwargs = {"settings_manager": self.settings_manager}
        else:
            runner = _m.run_official_ttr_launcher
            runner_kwargs = {}
        ok = False
        try:
            ok = bool(runner(**runner_kwargs))
        except Exception as exc:  # noqa: BLE001
            self.log(f"[Launch] launcher_runner({game}) raised: {exc!r}")
        if not ok:
            self.log(f"[Launch] Official {game.upper()} launcher could not be started.")

    def _effective_state(self, game: str, slot) -> tuple[str, str, str]:
        """Rehydration precedence: live launcher -> active loading timer ->
        stored slot state (stored-RUNNING-but-dead falls back to IDLE)."""
        if slot.launcher is not None and slot.launcher.is_running():
            return LoginState.RUNNING, "Game running", ""
        if slot.loading_timer is not None:
            return LoginState.LOADING, "", ""
        if slot.state == LoginState.RUNNING and (
                slot.launcher is None or not slot.launcher.is_running()):
            return LoginState.IDLE, "", ""
        return slot.state, slot.message, slot.raw_error

    def _page_activity(self, game: str, ordered, pc: int) -> list[bool]:
        flags = [False] * pc
        for idx, acct in enumerate(ordered):
            slot = self._slots[game].get(acct.id)
            if slot is None:
                continue
            st, _, _ = self._effective_state(game, slot)
            if st in (LoginState.RUNNING, LoginState.LOADING):
                p = idx // PAGE_SIZE
                # Guard is load-bearing: clamps any out-of-range page (e.g. if
                # account count ever exceeded the ceiling) to the dot count.
                if p < pc:
                    flags[p] = True
        return flags

    def _render_section(self, game: str) -> None:
        section = self._sections[game]
        ordered = self._ordered_accounts(game)
        n = len(ordered)
        pc = page_count(n)
        self._page[game] = max(0, min(self._page[game], pc - 1))
        page = self._page[game]
        base = page * PAGE_SIZE
        slice_ = ordered[base:base + PAGE_SIZE]
        dicts = []
        self._visible_tiles[game] = {}
        for acct in slice_:
            slot = self._slots[game].get(acct.id)
            if slot is None:
                slot = AccountSlot(account_id=acct.id)
                self._slots[game][acct.id] = slot
            st, msg, raw = self._effective_state(game, slot)
            dicts.append({"label": acct.label or "", "username": acct.username or "",
                          "id": acct.id, "state": st, "message": msg, "raw_error": raw})
        activity = self._page_activity(game, ordered, pc)
        section.set_page(dicts, page=page, page_count=pc, base_index=base,
                         activity=activity, show_empty_state=(n == 0),
                         at_ceiling=(n >= MAX_PER_GAME), show_reorder=(n >= 2))
        for local, acct in enumerate(slice_):
            if local < len(section.tiles):
                self._visible_tiles[game][acct.id] = section.tiles[local]

    def _reapply_visible_dots(self, game: str) -> None:
        """Re-apply each visible running account's last Multitoon dot_state.
        Must run AFTER refresh_theme(): AccountTile.apply_theme re-runs set_state
        for non-idle tiles, which resets the status dot to the plain running
        color and would clobber an earlier dot override."""
        for account_id, tile in self._visible_tiles[game].items():
            slot = self._slots[game].get(account_id)
            if (slot is not None and slot.dot_state
                    and slot.launcher is not None and slot.launcher.is_running()):
                self._apply_dot_color(tile, slot.dot_state)

    def _on_page_changed(self, game: str, page: int) -> None:
        # Demo mode renders fixtures (not cred_manager); _render_section would
        # replace them with real/empty account data, so pagination is a no-op
        # there. Demo fixtures are single-page anyway.
        if get_demo_fixtures() is not None:
            return
        self._page[game] = page
        self._render_section(game)
        self.refresh_theme()  # re-applies Multitoon dot_state last (see refresh_theme)

    def _build_demo(self, demo):
        for game in ("ttr", "cc"):
            self._slots[game] = {}
            self._loading[game] = []
            accounts = demo.get(game, [])
            dicts = []
            for i, acct in enumerate(accounts):
                aid = acct.get("id", f"demo_{game}_{i}")
                slot = AccountSlot(account_id=aid, state=acct.get("state", "idle"),
                                   message=acct.get("message", ""),
                                   raw_error=acct.get("raw", ""))
                self._slots[game][aid] = slot
                dicts.append({"label": acct.get("label", ""), "username": acct.get("username", ""),
                              "id": aid, "state": slot.state, "message": slot.message,
                              "raw_error": slot.raw_error})
            pc = page_count(len(accounts))
            self._sections[game].set_page(dicts[:PAGE_SIZE], page=0, page_count=pc,
                base_index=0, activity=[False] * pc,
                show_empty_state=(len(accounts) == 0),
                at_ceiling=(len(accounts) >= MAX_PER_GAME))

    def _build_ui(self):
        # Drop any old children from the scroll layout so we can re-add the
        # banner + sections in the right order.
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is None:
                continue
            if w is self._sections_container:
                # Detach sections from the old container before it is
                # destroyed, so external attribute references survive.
                self.ttr_section.setParent(None)
                self.cc_section.setParent(None)
                w.deleteLater()
                self._sections_container = None
            else:
                w.deleteLater()
        self._keyring_banner = None

        # Keyring banner (pending or warning) at top.
        if getattr(self.cred_manager, "keyring_probe_pending", False):
            self._keyring_banner = KeyringPendingBanner(parent=self)
            self._layout.addWidget(self._keyring_banner, alignment=Qt.AlignHCenter)
        elif not getattr(self.cred_manager, "keyring_available", True):
            self._keyring_banner = KeyringWarningBanner(self.cred_manager, parent=self)
            self._layout.addWidget(self._keyring_banner, alignment=Qt.AlignHCenter)

        demo = get_demo_fixtures()
        if demo is not None:
            self._build_demo(demo)
            self._rebuild_sections_container()
            self._layout.addStretch()
            return

        self._reconcile_slots()
        self._rebuild_sections_container()
        self._render_section("ttr")
        self._render_section("cc")
        self._layout.addStretch()

    # ── Layout mode ────────────────────────────────────────────────────────

    def set_layout_mode(self, mode: str) -> None:
        """Switch between compact (stacked) and full (side-by-side) layouts.
        Cheap to call repeatedly: if mode matches the current state, no-op.
        """
        if mode not in ("compact", "full"):
            return
        if mode == self._layout_mode and self._sections_container is not None:
            return
        self._layout_mode = mode
        self.ttr_section.set_layout_mode(mode)
        self.cc_section.set_layout_mode(mode)
        self._rebuild_sections_container()

    def _rebuild_sections_container(self) -> None:
        """(Re)build the widget that holds the two sections. In compact
        mode it's a QVBoxLayout; in full mode it's a QHBoxLayout. We
        re-parent the section widgets without destroying them, so all
        signals and child-tile state survive the swap."""
        # Find the current position of the container in self._layout so we
        # can re-insert the replacement at the same slot. Default to the
        # current count (appended) when no container exists yet; addStretch
        # hasn't been called yet during the _build_ui first-init path.
        insert_index = self._layout.count()
        if self._sections_container is not None:
            insert_index = self._layout.indexOf(self._sections_container)
            # Rescue the sections from the about-to-be-destroyed container
            # BEFORE scheduling the container's deleteLater, matching the
            # ordering used in _build_ui's cleanup loop.
            self.ttr_section.setParent(None)
            self.cc_section.setParent(None)
            self._sections_container.setParent(None)
            self._sections_container.deleteLater()
            self._sections_container = None
        else:
            # First-init path: sections still have their original parent.
            self.ttr_section.setParent(None)
            self.cc_section.setParent(None)

        container = QWidget()
        if self._layout_mode == "full":
            lay = QHBoxLayout(container)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(12)
            # AlignTop on each section prevents Qt's QHBoxLayout default
            # of vertically centering items whose sizeHint is smaller
            # than the row height. Without it, a collapsed section (which
            # has vertical sizePolicy=Preferred and sizeHint=header_height)
            # would float in the middle of its column, making the collapse
            # animation appear to grow/shrink from the center instead of
            # downward from the header.
            lay.addWidget(self.ttr_section, 1, Qt.AlignTop)
            lay.addWidget(self.cc_section, 1, Qt.AlignTop)
        else:
            # Compact: sections stack vertically. Use a centered max-width
            # inner wrapper so both sections fill the SAME width (the
            # wrapper's width, capped at 720). Without the wrapper, adding
            # sections with alignment=Qt.AlignHCenter would give each
            # section its own sizeHint width — and since populated +
            # empty sections have different content, their hints differ,
            # producing visibly different card widths.
            outer_lay = QHBoxLayout(container)
            outer_lay.setContentsMargins(0, 0, 0, 0)
            outer_lay.setSpacing(0)
            inner = QWidget()
            inner.setMaximumWidth(720)
            inner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            inner_lay = QVBoxLayout(inner)
            inner_lay.setContentsMargins(0, 0, 0, 0)
            inner_lay.setSpacing(12)
            inner_lay.addWidget(self.ttr_section)
            inner_lay.addWidget(self.cc_section)
            # Terminal stretch absorbs any spare vertical space in the
            # viewport. Without it, both sections (Preferred vertical
            # policy) share the extra space equally — so when one section
            # grows during the collapse animation, the other gets squeezed
            # to maintain the split. The stretch keeps both cards at their
            # natural sizeHint and parks empty space below.
            inner_lay.addStretch(1)
            # Stretch factor 100 vs side stretches 1 lets the inner card
            # column fill almost all available space until it hits its
            # 720 cap, then the side stretches absorb the remainder and
            # the inner is centered. Same pattern used by MultiToon's
            # compact layout (_compact_layout.py:71-79).
            outer_lay.addStretch(1)
            outer_lay.addWidget(inner, 100)
            outer_lay.addStretch(1)
        self._sections_container = container
        self._layout.insertWidget(insert_index, container)
        self._sync_compact_section_heights()

    def _sync_compact_section_heights(self) -> None:
        """In compact mode, expanded cards must share a height so a
        populated TTR card and an empty CC card don't look uneven.
        Collapsed cards are excluded from the match — they shrink to
        their header bar (min-height 0).

        QVBoxLayout with alignment=AlignHCenter gives each section its
        own sizeHint, so without intervention the empty card collapses
        to its content height while the populated card grows. Force
        expanded sections' min-height up to the taller expanded
        sibling's hint (or the per-section absolute floor of 380,
        whichever is greater)."""
        if self._layout_mode != "compact":
            return
        expanded = [s for s in (self.ttr_section, self.cc_section)
                    if not s.is_collapsed]
        if expanded:
            target = max(
                max(s.sizeHint().height() for s in expanded),
                380,
            )
        else:
            target = 0
        for s in (self.ttr_section, self.cc_section):
            if s.is_collapsed:
                s.setMinimumHeight(0)
            else:
                s.setMinimumHeight(target)

    # ── Account actions ────────────────────────────────────────────────────

    def _navigate_to_account(self, game: str, account_id: str) -> None:
        ordered = self._ordered_accounts(game)
        for i, a in enumerate(ordered):
            if a.id == account_id:
                self._page[game] = i // PAGE_SIZE
                break
        self._reconcile_slots()
        self._render_section(game)
        self.refresh_theme()

    def _newest_account_id(self, game: str) -> str | None:
        ordered = self._ordered_accounts(game)
        return ordered[-1].id if ordered else None

    def _on_add_account(self, game: str):
        if len(self._ordered_accounts(game)) >= MAX_PER_GAME:
            return  # hard ceiling (the footer Add button is also hidden at 16)
        editor = AccountEditor(game=game, mode="add", parent=self.window())

        def _save(label: str, username: str, password: str):
            ok = self.cred_manager.add_account(
                label=label, username=username, password=password, game=game,
            )
            if ok is False:
                # add_account refused (e.g. its own capacity guard or a storage
                # failure). Do NOT navigate — _newest_account_id would point at a
                # pre-existing account as if the add succeeded.
                self.log(f"[Launch] Could not add {game.upper()} account.")
                return
            self._reconcile_slots()
            target = self._newest_account_id(game)
            if target is not None:
                self._navigate_to_account(game, target)
            else:
                self._render_section(game)
                self.refresh_theme()

        editor.account_saved.connect(_save)
        editor.exec()

    def _on_reorder(self, game: str) -> None:
        # Only id-bearing accounts are reorderable. reorder_game validates
        # against id-bearing entries, so the dialog must offer exactly those —
        # otherwise an id-less legacy entry would make ordered_ids() mismatch
        # the validation set and the reorder would be silently rejected.
        ordered = [a for a in self._ordered_accounts(game) if a.id]
        if len(ordered) < 2:
            return
        accounts = [{"id": a.id, "label": a.label or "", "username": a.username or ""}
                    for a in ordered]
        dlg = AccountReorderDialog(game=game, accounts=accounts, parent=self.window())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_ids = dlg.ordered_ids()
        if not self.cred_manager.reorder_game(game, new_ids):
            self.log(f"[Launch] Reorder of {game.upper()} accounts was rejected.")
            return
        self._reconcile_slots()
        self._render_section(game)
        self.refresh_theme()

    def _on_tile_edit(self, game: str, account_id: str):
        global_idx = self._global_index_of(account_id)
        if global_idx is None:
            return
        acct = self.cred_manager.get_account(global_idx)
        if acct is None:
            return
        initial_password = getattr(acct, "password", "") or ""
        editor = AccountEditor(
            game=game, mode="edit",
            initial_label=acct.label or "",
            initial_username=acct.username or "",
            initial_password=initial_password,
            parent=self.window(),
        )

        def _save(label: str, username: str, password: str):
            # Empty password means "keep current"; pass None to preserve
            # the existing stored password.
            pw = password if password else None
            self.cred_manager.update_account(
                global_idx, label=label, username=username, password=pw,
            )
            self._reconcile_slots()
            self._render_section(game)
            self.refresh_theme()
            game_label = "TTR" if game == "ttr" else "CC"
            self.log(f"[Launch] {game_label} account {self._position_of(game, account_id)} updated.")

        editor.account_saved.connect(_save)
        editor.exec()

    def clear_all_credentials(self):
        for game in ("ttr", "cc"):
            for slot in self._slots[game].values():
                if slot.worker:
                    self._disconnect_worker_signals(slot.worker)
                    slot.worker.cancel()
                    slot.worker = None
                if slot.launcher:
                    self._disconnect_launcher_signals(slot.launcher)
                    slot.launcher.kill()
                    slot.launcher = None
                if slot.loading_timer is not None:
                    slot.loading_timer.stop()
                    slot.loading_timer.deleteLater()
                    slot.loading_timer = None
            # Drop the loading queue too, so no orphaned id survives the rebuild.
            self._loading[game] = []
        tokens = self.cred_manager.clear_all()
        for token in tokens:
            threading.Thread(
                target=revoke_launcher_token,
                args=(token,),
                daemon=True,
            ).start()
        self._build_ui()
        self.refresh_theme()

    def _on_delete(self, game: str, account_id: str):
        global_idx = self._global_index_of(account_id)
        if global_idx is None:
            return
        acct = self.cred_manager.get_account_metadata(global_idx)
        name = (acct.label or acct.username) if acct else f"account {self._position_of(game, account_id)}"

        dlg = ConfirmDialog(
            title=f"Delete {name}?",
            body=(
                "Credentials for this account will be removed from this "
                "computer. This cannot be undone."
            ),
            confirm_label="Delete",
            show_dont_ask_again=False,
            parent=self.window(),
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        # Cancel any active worker/launcher and drop a pending loading timer.
        slot = self._slots[game].get(account_id)
        if slot is not None:
            if slot.worker:
                self._disconnect_worker_signals(slot.worker)
                slot.worker.cancel()
                slot.worker = None
            if slot.launcher:
                self._disconnect_launcher_signals(slot.launcher)
                try:
                    slot.launcher.kill()
                except Exception as exc:  # noqa: BLE001
                    self.log(f"[Launch] kill on delete failed: {exc!r}")
                slot.launcher = None
            if slot.loading_timer is not None:
                slot.loading_timer.stop()
                slot.loading_timer.deleteLater()
                slot.loading_timer = None
            self._loading_remove(game, account_id)

        result = self.cred_manager.delete_account(global_idx)
        if result is not None:
            _account_id, token = result
            if token:
                threading.Thread(
                    target=revoke_launcher_token,
                    args=(token,),
                    daemon=True,
                ).start()
        self._reconcile_slots()
        self._render_section(game)
        self.refresh_theme()

    def _on_tile_quit(self, game: str, account_id: str):
        """Quit the running launcher for this slot, with optional confirm."""
        slot = self._slots[game].get(account_id)
        launcher = slot.launcher if slot is not None else None
        if launcher is None or not launcher.is_running():
            return
        dismissed = False
        if self.settings_manager is not None:
            dismissed = bool(self.settings_manager.get(LAUNCH_QUIT_CONFIRM_DISMISSED, False))
        if not dismissed:
            dlg = ConfirmDialog(
                title="Quit this game?",
                body="The running game window will be closed immediately.",
                confirm_label="Quit",
                show_dont_ask_again=True,
                parent=self.window(),
            )
            if dlg.exec() != dlg.DialogCode.Accepted:
                return
            if dlg.dont_ask_again_checked() and self.settings_manager is not None:
                self.settings_manager.set(LAUNCH_QUIT_CONFIRM_DISMISSED, True)
        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] Terminating {game_label} game {self._position_of(game, account_id)}…")
        launcher.kill()

    def _on_tile_cancel(self, game: str, account_id: str):
        slot = self._slots[game].get(account_id)
        worker = slot.worker if slot is not None else None
        if worker is not None:
            try:
                worker.cancel()
            except Exception:  # noqa: BLE001
                pass
            # Detach the cancelled worker so any already-queued late signal
            # (e.g. a login_success that beat the cancel) fails the
            # `slot.worker is worker` guard and can't launch/mutate state.
            self._disconnect_worker_signals(worker)
            if slot is not None:
                slot.worker = None
        self._update_status(game, account_id, LoginState.IDLE, "")

    def _on_tile_enter_2fa(self, game: str, account_id: str):
        slot = self._slots[game].get(account_id)
        worker = slot.worker if slot is not None else None
        if worker is None:
            self.log(f"[2fa] no active worker for {game}/{account_id}; nothing to prompt")
            return
        banner = "Two-Factor Authentication required"
        self._prompt_2fa(game, account_id, banner)

    def _on_tile_expand_error(self, game: str, account_id: str):
        global_idx = self._global_index_of(account_id)
        slot = self._slots[game].get(account_id)
        acct = self.cred_manager.get_account_metadata(global_idx) if global_idx is not None else None
        name = (acct.label or acct.username) if acct else f"Account {self._position_of(game, account_id)}"
        raw = (slot.raw_error if slot is not None else "")
        if not raw:
            tile = self._visible_tiles[game].get(account_id)
            raw = getattr(tile, "raw_error_message", "") if tile is not None else ""
        raw = raw or "No additional detail."
        ErrorModal(
            account_name=name, game=game, raw_message=raw, parent=self.window(),
        ).exec()

    # ── Launch flow ────────────────────────────────────────────────────────

    def _on_launch(self, game: str, account_id: str):
        from utils.credentials_manager import _dbg
        _dbg(f"[Credentials] _on_launch click: game={game} account={account_id} "
             f"probe_pending={getattr(self.cred_manager, 'keyring_probe_pending', False)} "
             f"available={getattr(self.cred_manager, 'keyring_available', True)}")
        slot = self._slots[game].get(account_id)
        if slot is None:
            _dbg(f"[Credentials] _on_launch: no slot for {game}/{account_id}")
            return
        global_idx = self._global_index_of(account_id)
        if global_idx is None:
            _dbg(f"[Credentials] _on_launch: no global index for {account_id}")
            return

        # CC: block launch when multi-install is ambiguous (no stored pick).
        if game == "cc":
            if not _cc_launch_gate(self.settings_manager, parent=self.window()):
                return

        # Check engine path
        engine_dir = self._get_engine_dir(game)
        exe_fn = get_engine_executable_name if game == "ttr" else get_cc_engine_executable_name
        if not engine_dir:
            engine_bin = ""
        elif game == "ttr":
            engine_bin = engine_binary_path(engine_dir)
        else:
            engine_bin = os.path.join(engine_dir, exe_fn())
        if not engine_dir or not os.path.isfile(engine_bin):
            _dbg(f"[Credentials] _on_launch: engine not found (dir='{engine_dir}' bin='{engine_bin}')")
            msg = "Game path not set. Configure in Settings."
            self._update_status(game, account_id, LoginState.FAILED, msg)
            self._show_failure_dialog(game, account_id, msg)
            return

        acct = self.cred_manager.get_account(global_idx)
        acct_desc = (
            f"acct_exists={acct is not None} "
            f"username={'present' if (acct and acct.username) else 'empty'} "
            f"password={'present' if (acct and acct.password) else 'empty'}"
            if acct is not None else "acct_exists=False"
        )
        _dbg(f"[Credentials] _on_launch account={account_id} {acct_desc}")
        if not acct or not acct.username:
            msg = "Missing username. Click Edit."
            self._update_status(game, account_id, LoginState.FAILED, msg)
            self._show_failure_dialog(game, account_id, msg)
            return
        # TTR still requires a password up front. CC accounts may legitimately
        # have no password (token-only model after register_and_login).
        if game == "ttr" and not acct.password:
            msg = "Missing username or password. Click Edit."
            self._update_status(game, account_id, LoginState.FAILED, msg)
            self._show_failure_dialog(game, account_id, msg)
            return

        # Check if already running
        if slot.launcher and slot.launcher.is_running():
            game_label = "TTR" if game == "ttr" else "CC"
            self.log(f"[Launch] Terminating {game_label} game {self._position_of(game, account_id)}…")
            slot.launcher.kill()
            return

        # Cancel any previous worker/launcher
        if slot.worker:
            self._disconnect_worker_signals(slot.worker)
            slot.worker.cancel()
            slot.worker = None
        if slot.launcher:
            self._disconnect_launcher_signals(slot.launcher)
            slot.launcher = None

        # Create game-specific worker and launcher, wire signals.
        self._make_launchers(game, account_id)

        # Start login
        if game == "ttr":
            slot.worker.login(acct.username, acct.password)
        else:
            # CC: dispatch by stored credential shape.
            print(f"[Launch] CC dispatch account={account_id} "
                  f"has_token={bool(acct.launcher_token)} has_password={bool(acct.password)}")
            if acct.launcher_token:
                print("[Launch] CC dispatch: -> login_with_token (token-only path)")
                slot.worker.login_with_token(acct.launcher_token)
            elif acct.password:
                print("[Launch] CC dispatch: -> register_and_login (legacy migration path)")
                slot.worker.launcher_token_obtained.connect(
                    lambda tok, aid=acct.id, w=slot.worker:
                        self._on_token_obtained("cc", aid, w, tok)
                )
                slot.worker.register_and_login(acct.username, acct.password,
                                               label=acct.label or "")
            else:
                print("[Launch] CC dispatch: -> error branch, no credentials")
                msg = "No CC credentials stored. Click Edit on this account."
                self._update_status(game, account_id, LoginState.FAILED, msg)
                self._show_failure_dialog(game, account_id, msg)
                return
        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] Logging in {game_label} account {self._position_of(game, account_id)}…")

    def _make_launchers(self, game: str, account_id: str):
        """Create a fresh worker/launcher pair for *game*/*account_id*, store
        them on the slot, connect their signals, and return ``(worker,
        launcher)``. Signal handlers carry the worker/launcher object so a
        superseded attempt's late signals can be ignored (object-identity
        stale guards).
        """
        slot = self._slots[game][account_id]
        if game == "ttr":
            worker = TTRLoginWorker(self)
            launcher = TTRLauncher(self, settings_manager=self.settings_manager)
        else:
            worker = CCLoginWorker(self)
            launcher = CCLauncher(self, settings_manager=self.settings_manager)
            self._wine_console_hider.attach(launcher)

        slot.worker, slot.launcher = worker, launcher

        # Connect signals (worker/launcher passed for stale-signal guards).
        worker.state_changed.connect(lambda s, m, g=game, a=account_id, w=worker: self._on_worker_state(g, a, w, s, m))
        worker.queue_update.connect(lambda p, e, g=game, a=account_id, w=worker: self._on_worker_queue(g, a, w, p, e))
        worker.need_2fa.connect(lambda b, g=game, a=account_id, w=worker: self._on_worker_2fa(g, a, w, b))
        worker.login_success.connect(lambda gs, ck, g=game, a=account_id, w=worker: self._on_login_success(g, a, w, gs, ck))
        worker.login_failed.connect(lambda msg, g=game, a=account_id, w=worker: self._on_login_failed(g, a, w, msg))

        launcher.game_launched.connect(lambda pid, g=game, a=account_id, l=launcher: self._on_game_launched(g, a, l, pid))
        launcher.game_exited.connect(lambda rc, raw, g=game, a=account_id, l=launcher: self._on_game_exited(g, a, l, rc, raw))
        launcher.launch_failed.connect(lambda msg, g=game, a=account_id, l=launcher: self._on_launcher_failed(g, a, l, msg))

        return worker, launcher

    def _on_worker_state(self, game, account_id, worker, state, message):
        slot = self._slots[game].get(account_id)
        if slot is None or slot.worker is not worker:
            return  # stale signal from a superseded/cancelled attempt
        self._update_status(game, account_id, state, message)

    def _on_worker_queue(self, game, account_id, worker, position, eta):
        slot = self._slots[game].get(account_id)
        if slot is None or slot.worker is not worker:
            return
        self._update_queue(game, account_id, position, eta)

    def _on_worker_2fa(self, game, account_id, worker, banner):
        slot = self._slots[game].get(account_id)
        if slot is None or slot.worker is not worker:
            return
        self._prompt_2fa(game, account_id, banner)

    def _on_token_obtained(self, game, account_id, worker, token):
        """Guarded launcher_token_obtained handler: ignore a token from a
        superseded/cancelled register worker so it can't persist a token and
        clear the password after the attempt was replaced."""
        slot = self._slots[game].get(account_id)
        if slot is None or slot.worker is not worker:
            return
        self._persist_launcher_token(account_id, token)

    def _persist_launcher_token(self, account_id: str, token: str) -> None:
        """Save a CC launcher token to keyring AND clear the now-redundant
        password (token-only model). Best-effort: keyring errors are logged
        but don't block the launch.
        """
        print(f"[Launch] _persist_launcher_token: aid={account_id[:8]} token_len={len(token) if token else 0}")
        try:
            self.cred_manager.set_launcher_token(account_id, token)
            print(f"[Launch] _persist_launcher_token: set_launcher_token ok")
            idx = self._global_index_of(account_id)
            print(f"[Launch] _persist_launcher_token: account index={idx}")
            if idx is not None:
                self.cred_manager.update_account(idx, password="")
                print(f"[Launch] _persist_launcher_token: cleared password for idx={idx}")
        except Exception as e:
            from utils.credentials_manager import _dbg
            print(f"[Launch] _persist_launcher_token: FAILED {type(e).__name__}: {e}")
            _dbg(f"[Credentials] _persist_launcher_token({account_id[:8]}) failed: {type(e).__name__}: {e}")

    def _on_login_success(self, game, account_id, worker, gameserver, token):
        slot = self._slots[game].get(account_id)
        if slot is None or slot.worker is not worker:
            return  # stale signal from a superseded/cancelled attempt
        game_label = "TTR" if game == "ttr" else "CC"
        print(f"[Launch] _on_login_success: game={game} account={account_id} "
              f"gameserver='{gameserver}' token_len={len(token) if token else 0}")
        self.log(f"[Launch] {game_label} account {self._position_of(game, account_id)} "
                 f"authenticated. Launching game…")
        launcher = slot.launcher
        print(f"[Launch] _on_login_success: launcher_ref={launcher!r}")
        if launcher:
            if game == "cc":
                install = self._build_cc_install()
                print(f"[Launch] _on_login_success: cc install={install!r}")
                if install is None:
                    msg = "Game path not set. Configure in Settings."
                    self._update_status(game, account_id, LoginState.FAILED, msg)
                    self._show_failure_dialog(game, account_id, msg)
                    return
                username = ""
                for acct in self._ordered_accounts("cc"):
                    if acct.id == account_id:
                        username = acct.username or ""
                        break
                print(f"[Launch] _on_login_success: invoking CC patch+launch username_len={len(username)}")
                from services.cc_login_service import CC_DEFAULT_REALM
                self._launch_cc_with_patch(account_id, gameserver, token,
                                           install, username, CC_DEFAULT_REALM, launcher)
            else:
                engine_dir = self._get_engine_dir(game)
                self._launch_ttr_with_patch(account_id, gameserver, token, engine_dir, launcher)

    def _launch_ttr_with_patch(self, account_id, gameserver, token, engine_dir, launcher):
        """Verify/repair TTR game files against the official manifest, then
        launch on success. A stale phase file would otherwise fail the engine's
        integrity check. See docs/superpowers/specs/2026-05-28-ttr-game-file-patching-design.md.
        """
        patcher = TTRPatcher(self)
        # Keep the patcher alive through its background thread two ways: Qt
        # parents it to this tab (TTRPatcher(self)), and a Python strong ref is
        # held on the retained launcher so it can't be GC'd before it finishes.
        launcher._ttr_patcher = patcher

        def _go():
            # Stale-guard: a superseded patcher (the slot was relaunched) must
            # not launch the old launcher after slot.launcher was reassigned.
            slot = self._slots["ttr"].get(account_id)
            if slot is None or slot.launcher is not launcher:
                return
            launcher.launch(gameserver, token, engine_dir)

        patcher.progress.connect(
            lambda msg, pct, a=account_id, l=launcher: self._patch_progress("ttr", a, l, msg)
        )
        patcher.up_to_date.connect(_go)
        patcher.patched.connect(
            lambda files: (self.log(f"[Launch] Updated TTR game files: {', '.join(files)}"), _go())
        )
        patcher.failed.connect(
            lambda msg, a=account_id, l=launcher: self._on_launcher_failed("ttr", a, l, msg)
        )
        patcher.verify_and_patch(engine_dir)

    def _patch_progress(self, game, account_id, launcher, msg):
        """Guarded patcher-progress update: drop progress from a patcher whose
        launcher was superseded by a relaunch (stale-signal guard)."""
        slot = self._slots[game].get(account_id)
        if slot is None or slot.launcher is not launcher:
            return
        self._update_status(game, account_id, LoginState.LAUNCHING, msg)

    def _launch_cc_with_patch(self, account_id, gameserver, token, install,
                              username, realm_slug, launcher):
        """Verify/repair CC game files against CC's official manifest, then
        launch on success. On hard failure, block the launch and offer the
        official CC launcher (which patches via CC's own flow).
        See docs/superpowers/specs/2026-05-29-cc-verify-repair-design.md.
        """
        patcher = CCPatcher(self)
        launcher._cc_patcher = patcher   # strong ref through the bg thread

        def _go():
            # Stale-guard: a superseded patcher must not launch the old launcher.
            slot = self._slots["cc"].get(account_id)
            if slot is None or slot.launcher is not launcher:
                return
            launcher.launch(gameserver, token, install,
                            username=username, realm_slug=realm_slug)

        patcher.progress.connect(
            lambda msg, pct, a=account_id, l=launcher: self._patch_progress("cc", a, l, msg)
        )
        patcher.up_to_date.connect(_go)
        patcher.patched.connect(
            lambda files: (self.log(f"[Launch] Updated CC game files: {', '.join(files)}"), _go())
        )
        patcher.failed.connect(
            lambda msg, a=account_id, l=launcher: self._offer_cc_launcher_fallback(a, msg, l)
        )
        game_dir = os.path.dirname(install.exe_path)
        patcher.verify_and_patch(game_dir, token, realm_slug)

    def _offer_cc_launcher_fallback(self, account_id, msg, launcher=None):
        """Hard patch failure: mark the slot failed and offer to open CC's
        official launcher, which performs CC's own update flow. Guarded against a
        superseded launcher (relaunch) so a stale patcher can't clobber state."""
        from PySide6.QtWidgets import QMessageBox
        slot = self._slots["cc"].get(account_id)
        if slot is None or (launcher is not None and slot.launcher is not launcher):
            return
        self._update_status("cc", account_id, LoginState.FAILED, msg)
        box = QMessageBox(self.window())
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Corporate Clash update failed")
        box.setText("Could not update Corporate Clash automatically.")
        box.setInformativeText(
            f"{msg}\n\nOpen the official Corporate Clash launcher to update?"
        )
        open_btn = box.addButton("Open official launcher", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            if not run_official_cc_launcher(self.settings_manager):
                self.log("[Launch] Could not start the official CC launcher.")

    def _on_login_failed(self, game, account_id, worker, msg):
        slot = self._slots[game].get(account_id)
        if slot is None or slot.worker is not worker:
            return  # stale signal from a superseded/cancelled attempt
        game_label = "TTR" if game == "ttr" else "CC"
        print(f"[Launch] _on_login_failed: game={game} account={account_id} msg={msg!r}")
        self.log(f"[Launch] {game_label} account {self._position_of(game, account_id)} login failed: {msg}")
        self._update_status(game, account_id, LoginState.FAILED, msg)
        self._show_failure_dialog(game, account_id, msg)

    def _on_launcher_failed(self, game, account_id, launcher, msg):
        slot = self._slots[game].get(account_id)
        if slot is None or slot.launcher is not launcher:
            return  # stale signal from a superseded/cancelled attempt
        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] {game_label} account {self._position_of(game, account_id)} launch failed: {msg}")
        self._update_status(game, account_id, LoginState.FAILED, msg)
        self._show_failure_dialog(game, account_id, msg)

    def _show_failure_dialog(self, game, account_id, msg):
        """Pop a modal warning dialog with the full failure message.

        Called from every terminal failure dispatch site. See spec
        docs/superpowers/specs/2026-05-17-login-failure-dialog-design.md.
        """
        from PySide6.QtWidgets import QMessageBox
        game_label = "Toontown Rewritten" if game == "ttr" else "Corporate Clash"
        box = QMessageBox(self.window())
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(f"{game_label} login failed")
        box.setText(f"Account {self._position_of(game, account_id)} couldn't sign in.")
        box.setInformativeText(msg)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()

    def _on_game_launched(self, game, account_id, launcher, pid):
        slot = self._slots[game].get(account_id)
        if slot is None or slot.launcher is not launcher:
            return  # stale signal from a superseded/cancelled attempt
        game_label = "TTR" if game == "ttr" else "CC"
        pos = self._position_of(game, account_id)
        if self.window_manager is None:
            self.log(f"[Launch] {game_label} account {pos} game running (PID {pid})")
            self._update_status(game, account_id, LoginState.RUNNING, "Game running")
            return
        self.log(f"[Launch] {game_label} account {pos} process started "
                 f"(PID {pid}); waiting for window")
        # Ensure the shared detector is active even if the Multitoon tab was
        # never opened (its only other caller). Idempotent; nothing disables it.
        self.window_manager.enable_detection()
        # Relaunch into a slot already loading: drop the stale timer first.
        if slot.loading_timer is not None:
            slot.loading_timer.stop()
            slot.loading_timer.deleteLater()
            slot.loading_timer = None
            self._loading_remove(game, account_id)
        # Start of a loading episode -> baseline the windows already present.
        if not self._loading[game]:
            self._window_credit[game] = self.window_manager.count_for_game(game)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(
            lambda g=game, a=account_id: self._promote_loader(g, a, "timeout")
        )
        slot.loading_timer = timer
        self._loading_add(game, account_id)
        self._update_status(game, account_id, LoginState.LOADING, "")
        timer.start(self.LOADING_WINDOW_TIMEOUT_MS)

    def _promote_loader(self, game, account_id, reason):
        """Flip a loading slot to RUNNING. Consumes one window credit so a later
        phantom window cannot double-promote and a timeout-promoted slot's
        eventual real window is a no-op."""
        slot = self._slots[game].get(account_id)
        if slot is None:
            # The account was deleted/cleared while loading. Drop the orphaned
            # id so _on_windows_changed's promote loop can make progress instead
            # of spinning on a stale entry forever.
            self._loading_remove(game, account_id)
            return
        if account_id not in self._loading[game]:
            return  # already promoted or exited
        if slot.loading_timer is not None:
            slot.loading_timer.stop()
            slot.loading_timer.deleteLater()
            slot.loading_timer = None
        self._loading_remove(game, account_id)
        self._window_credit[game] += 1
        game_label = "TTR" if game == "ttr" else "CC"
        detail = "window detected" if reason == "window" else "window wait timed out"
        self.log(f"[Launch] {game_label} account {self._position_of(game, account_id)} "
                 f"{detail}; marking running")
        self._update_status(game, account_id, LoginState.RUNNING, "Game running")

    def _on_windows_changed(self, _ids):
        """A WindowManager detection pass changed the window set. Promote the
        oldest loading slot of each game for every window beyond the baseline."""
        if self.window_manager is None:
            return
        for game in ("ttr", "cc"):
            while self._loading[game] and (
                self.window_manager.count_for_game(game) - self._window_credit[game] > 0
            ):
                self._promote_loader(game, self._loading[game][0], "window")

    def _on_game_exited(self, game, account_id, launcher, retcode, raw_log=""):
        # Stale-signal guard: a superseded launcher (the slot was relaunched and
        # reassigned) can still be alive and fire game_exited later; ignore it so
        # it can't reset the new launcher's live RUNNING/LOADING state.
        slot = self._slots[game].get(account_id)
        if slot is None or slot.launcher is not launcher:
            return
        # If the process exits while still loading, drop its pending timer so it
        # cannot later flip a re-used slot to running. Do NOT touch the window
        # credit -- no window was consumed.
        if slot.loading_timer is not None:
            slot.loading_timer.stop()
            slot.loading_timer.deleteLater()
            slot.loading_timer = None
            self._loading_remove(game, account_id)
        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] {game_label} account {self._position_of(game, account_id)} "
                 f"game exited (code {retcode})")
        # game crash / kill: status band carries the exit code; no login-failure dialog (post-launch is out of scope)
        if retcode not in (0, -9, -15, None):
            # Pass raw_log as BOTH the band message and the modal raw:
            # the band's summarize_error() heuristics ("not installed" →
            # "Runtime missing", "network" → "Network error", etc.)
            # categorize the failure for the user, and the modal shows
            # the full stderr/stdout tail for diagnosis. When the launcher
            # has no captured log (TTRLauncher uses DEVNULL), fall back
            # to the bare "Failed: code N" string.
            payload = raw_log or f"Failed: code {retcode}"
            self._update_status(game, account_id, LoginState.FAILED,
                                payload, raw=payload)
        else:
            self._update_status(game, account_id, LoginState.IDLE, "")

    def _prompt_2fa(self, game, account_id, banner):
        """Show 2FA input dialog."""
        key = (game, account_id)
        if key in self._pending_2fa:
            return
        self._pending_2fa.add(key)

        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] {game_label} account {self._position_of(game, account_id)} requires 2FA.")
        token, ok = QInputDialog.getText(
            self, "Two-Factor Authentication",
            f"{banner}\n\nEnter your authenticator code:",
            QLineEdit.Password,
        )
        self._pending_2fa.discard(key)
        slot = self._slots[game].get(account_id)
        worker = slot.worker if slot is not None else None
        if ok and token.strip():
            if worker:
                worker.submit_2fa(token.strip())
        else:
            if worker:
                worker.cancel()
            self._update_status(game, account_id, LoginState.IDLE, "2FA cancelled")

    @Slot(bool)
    def _on_keyring_probe_complete(self, available: bool):
        if available:
            self.cred_manager.run_deferred_v1_migration()
        self._build_ui()
        self.refresh_theme()
        self._set_launch_buttons_enabled(True)
        from utils.credentials_manager import _dbg
        _dbg(f"[Credentials] Keyring probe completed: available={available}")
        self._log_keyring_backend_state("post-probe")

    # ── Status updates ─────────────────────────────────────────────────────

    def _update_status(self, game, account_id, state, message, raw=None):
        slot = self._slots[game].get(account_id)
        if slot is None:
            return
        if raw is None:
            raw = message if state == LoginState.FAILED else ""
        slot.state, slot.message, slot.raw_error = state, message or "", raw
        # AccountTile expects the same lowercase string used by LoginState's
        # class attributes (idle/logging_in/queued/launching/running/failed/
        # need_2fa).
        tile = self._visible_tiles[game].get(account_id)
        if tile is not None:
            tile.set_state(state, message or "", raw)
        self._refresh_activity(game)

    def update_dot_state(self, index: int, state_str: str):
        """Called from multitoon tab - index is the global TTR slot position.

        For now, only TTR slots are updated since CC has no companion API.
        The new AccountTile drives its own running-state pulse; this stamps
        the sync_state onto the slot and, when the slot's launcher is alive
        and the tile is on the visible page, drives the status dot.
        """
        ordered = self._ordered_accounts("ttr")
        if index < 0 or index >= len(ordered):
            return  # out of range (e.g. after a delete) -> ignore safely
        account_id = ordered[index].id
        slot = self._slots["ttr"].get(account_id)
        if slot is None:
            return
        slot.dot_state = state_str

        if slot.launcher and slot.launcher.is_running():
            tile = self._visible_tiles["ttr"].get(account_id)
            if tile is not None:
                self._apply_dot_color(tile, state_str)

    def _apply_dot_color(self, tile, state_str: str) -> None:
        """Paint a tile's status dot for a Multitoon sync state. Shared by
        update_dot_state and the render path (so a flip back to an off-page
        running account re-applies its last dot_state)."""
        dot = getattr(tile, "status_dot", None)
        if dot is None:
            return
        color = {
            "active": "#56c856",
            "idle":   "#888888",
            "warn":   "#E8A838",
            "error":  "#E05252",
        }.get(state_str, "#56c856")
        dot.set_color(color, pulse=(state_str == "active"))

    def _update_queue(self, game, account_id, position, eta):
        slot = self._slots[game].get(account_id)
        if slot is None:
            return
        msg = f"#{position} (~{eta}s)"
        slot.state = LoginState.QUEUED
        # Store the queue detail on the slot so flipping to an off-page queued
        # account rehydrates the position/ETA, not a bare "In queue".
        slot.message = msg
        tile = self._visible_tiles[game].get(account_id)
        if tile is not None:
            tile.set_state(LoginState.QUEUED, msg)

    # ── Theme ──────────────────────────────────────────────────────────────

    def _c(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

    def refresh_theme(self):
        c = self._c()
        is_dark = resolve_theme(self.settings_manager) == "dark"

        self.setStyleSheet(f"background: {c['bg_app']}; color: {c['text_primary']};")
        self._scroll.setStyleSheet(self._scroll.styleSheet())
        bar = getattr(self._scroll, "_auto_hide_scrollbar", None)
        if bar is not None:
            bar.set_theme(is_dark)
        self._scroll_widget.setStyleSheet(f"background: {c['bg_app']};")

        # Propagate the theme dict to every theme-aware child.
        for section in (self.ttr_section, self.cc_section):
            if section is not None and hasattr(section, "apply_theme"):
                section.apply_theme(c)

        if self._keyring_banner is not None:
            if hasattr(self._keyring_banner, "apply_theme"):
                self._keyring_banner.apply_theme(c)

        # AccountTile.apply_theme re-runs set_state for non-idle tiles, resetting
        # the status dot to the plain running color. Re-apply any Multitoon
        # dot_state LAST so a theme change (from anywhere) doesn't clobber it.
        for game in ("ttr", "cc"):
            self._reapply_visible_dots(game)

    # ── Logging ────────────────────────────────────────────────────────────

    def log(self, msg):
        if self.logger:
            self.logger.append_log(msg)
        else:
            print(msg)

    def shutdown(self):
        # Tear down the tab's own transient resources. Deliberately does NOT
        # kill running game launchers: closing the TTMT UI leaves already-running
        # games alive (a multitoon launcher you can close while still playing).
        for game in ("ttr", "cc"):
            for slot in self._slots[game].values():
                if slot.loading_timer is not None:
                    slot.loading_timer.stop()
                    slot.loading_timer.deleteLater()
                    slot.loading_timer = None
                if slot.worker is not None:
                    # Cancel + detach an in-flight login (not a running game) so a
                    # request that completes after shutdown fails the
                    # `slot.worker is worker` guard and can't mutate UI / launch.
                    self._disconnect_worker_signals(slot.worker)
                    try:
                        slot.worker.cancel()
                    except Exception:  # noqa: BLE001
                        pass
                    slot.worker = None
            self._loading[game] = []
        if self._probe_thread is not None and self._probe_thread.isRunning():
            self._probe_thread.quit()
            self._probe_thread.wait(2000)
