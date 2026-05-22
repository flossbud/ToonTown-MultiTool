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
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QScrollArea, QLineEdit, QInputDialog,
)
from PySide6.QtCore import Qt, QObject, Signal, QThread, Slot

from utils.theme_manager import resolve_theme, get_theme_colors
from utils.credentials_manager import CredentialsManager, set_debug_log_callback
from utils.open_url import open_url
from services.ttr_login_service import (
    TTRLoginWorker, LoginState, find_engine_path, get_engine_executable_name,
)
from services.ttr_launcher import TTRLauncher
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
)
from utils.widgets import install_modern_scrollbar
from utils.widgets.cc_install_picker import CCInstallPickerDialog  # noqa: F401
from utils.widgets.launch_section import LaunchSection
from utils.widgets.account_editor import AccountEditor
from utils.widgets.confirm_dialog import ConfirmDialog
from utils.widgets.error_modal import ErrorModal
from utils.launch_tab_demo_mode import get_demo_fixtures


MAX_PER_GAME = 8  # hard ceiling
LINUX_KEYRING_HELP_URL = "https://wiki.archlinux.org/title/Secret_Service"


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

    def refresh_theme(self, c, is_dark: bool):
        bg = "#1e1e2e" if is_dark else "#f0f0f0"
        border = "#888888"
        self.setStyleSheet(
            f"QFrame#keyring_pending_banner {{ background: {bg}; border-left: 3px solid {border}; "
            f"border-top: 1px solid {border}55; border-right: 1px solid {border}55; "
            f"border-bottom: 1px solid {border}55; border-radius: 8px; }}"
        )
        self.header_label.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {c['text_secondary']}; background: transparent; border: none;"
        )
        self.body_label.setStyleSheet(
            f"font-size: 11px; color: {c['text_primary']}; background: transparent; border: none;"
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

    def refresh_theme(self, c, is_dark: bool):
        bg = "#3D2800" if is_dark else "#FFF3CD"
        border = "#E8A838"
        self.setStyleSheet(
            f"QFrame#keyring_warning_banner {{ background: {bg}; border-left: 3px solid {border}; "
            f"border-top: 1px solid {border}55; border-right: 1px solid {border}55; "
            f"border-bottom: 1px solid {border}55; border-radius: 8px; }}"
        )
        self.header_label.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {border}; background: transparent; border: none;"
        )
        self.body_label.setStyleSheet(
            f"font-size: 11px; color: {c['text_primary']}; background: transparent; border: none;"
        )
        self.fix_label.setStyleSheet(
            f"font-size: 11px; color: {c['text_secondary']}; background: transparent; border: none;"
        )
        self.link_label.setStyleSheet(
            f"font-size: 10px; color: {c['accent_blue_btn']}; background: transparent; border: none;"
        )
        self.legacy_label.setStyleSheet(
            f"font-size: 10px; color: {c['text_muted']}; background: transparent; border: none;"
        )


class LaunchTab(QWidget):
    # Cross-thread bridge for credential-manager debug messages. Emitted
    # from the keyring probe worker thread; auto-connected to the main-
    # thread DebugTab.append_log slot. See the __init__ comment below.
    _log_to_debug_tab = Signal(str)

    def __init__(self, settings_manager=None, logger=None, parent=None,
                 credentials_manager=None, cred_manager=None):
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

        # Per-game workers and launchers, plus _cards mirror used by
        # update_dot_state / _restore_running_state_from_launchers /
        # external callers from main.py.
        self._workers = {"ttr": [None] * MAX_PER_GAME, "cc": [None] * MAX_PER_GAME}
        self._launchers = {"ttr": [None] * MAX_PER_GAME, "cc": [None] * MAX_PER_GAME}
        self._cards: dict[str, list[dict]] = {"ttr": [], "cc": []}
        self._keyring_banner = None
        self._probe_thread = None
        self._probe_worker = None
        self._pending_2fa: set = set()

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
        max_per = self._max_per_game()
        self.ttr_section = LaunchSection(
            game="ttr", icon_path=_asset_path("ttr.png"), max_accounts=max_per,
            parent=self._scroll_widget,
        )
        self.cc_section = LaunchSection(
            game="cc", icon_path=_asset_path("cc.png"), max_accounts=max_per,
            parent=self._scroll_widget,
        )
        self._sections = {"ttr": self.ttr_section, "cc": self.cc_section}
        self._layout_mode = "compact"
        self._sections_container: QWidget | None = None

        self._wire_section(self.ttr_section, "ttr")
        self._wire_section(self.cc_section, "cc")

        self._build_ui()
        self.refresh_theme()
        # Diagnostics are logged from _on_keyring_probe_complete after the
        # timed/threaded probe has finished. Calling them here would hit
        # format_backend_diagnostics on the main thread before app.exec(),
        # which can hang on a locked/uninitialized SecretService collection.
        self._start_keyring_probe()

    # ── Helpers ────────────────────────────────────────────────────────────

    def _max_per_game(self) -> int:
        if self.settings_manager:
            v = self.settings_manager.get("max_accounts_per_game", 4)
            try:
                v = int(v)
            except (TypeError, ValueError):
                v = 4
            return min(v, MAX_PER_GAME)
        return 4

    def _get_engine_dir(self, game: str) -> str:
        """Read the engine directory for a game from settings, with auto-detect fallback."""
        if game == "ttr":
            key, exe_fn, find_fn = "ttr_engine_dir", get_engine_executable_name, find_engine_path
        else:
            key, exe_fn, find_fn = "cc_engine_dir", get_cc_engine_executable_name, find_cc_engine_path

        path = self.settings_manager.get(key, "") if self.settings_manager else ""
        if path and os.path.isfile(os.path.join(path, exe_fn())):
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

    def _game_accounts_with_indices(self, game: str) -> list[tuple[int, object]]:
        """Return [(global_flat_index, AccountCredential), ...] for one game."""
        result = []
        all_accounts = self.cred_manager.get_accounts_metadata()
        for flat_idx, acct in enumerate(all_accounts):
            if acct.game == game:
                result.append((flat_idx, acct))
        return result

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
        for game in ("ttr", "cc"):
            for card in self._cards[game]:
                if card.get("state") in (LoginState.LOGGING_IN, LoginState.QUEUED, LoginState.LAUNCHING):
                    continue
                btn = card.get("launch_btn")
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
        section.tile_launch.connect(lambda i, g=game: self._on_launch(g, i))
        section.tile_quit.connect(lambda i, g=game: self._on_tile_quit(g, i))
        section.tile_cancel.connect(lambda i, g=game: self._on_tile_cancel(g, i))
        section.tile_retry.connect(lambda i, g=game: self._on_launch(g, i))
        section.tile_enter_2fa.connect(lambda i, g=game: self._on_tile_enter_2fa(g, i))
        section.tile_edit.connect(lambda i, g=game: self._on_tile_edit(g, i))
        section.tile_delete.connect(lambda i, g=game: self._on_delete(g, i))
        section.tile_expand_error.connect(lambda i, g=game: self._on_tile_expand_error(g, i))

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
        self._cards = {"ttr": [], "cc": []}
        self._keyring_banner = None

        # Keyring banner (pending or warning) at top.
        if getattr(self.cred_manager, "keyring_probe_pending", False):
            self._keyring_banner = KeyringPendingBanner(parent=self)
            self._layout.addWidget(self._keyring_banner, alignment=Qt.AlignHCenter)
        elif not getattr(self.cred_manager, "keyring_available", True):
            self._keyring_banner = KeyringWarningBanner(self.cred_manager, parent=self)
            self._layout.addWidget(self._keyring_banner, alignment=Qt.AlignHCenter)

        # Demo mode: bypass the cred_manager path entirely and force tiles
        # into the fixture states for screenshot capture.
        demo = get_demo_fixtures()
        if demo is not None:
            for game in ("ttr", "cc"):
                accounts = demo.get(game, [])
                section = self._sections[game]
                section.set_accounts(accounts)
                # Build _cards mirror so update_dot_state / etc don't blow
                # up, even though demo mode never runs the launch flow.
                self._cards[game] = []
                for i, acct in enumerate(accounts):
                    tile = section.tile_at(i)
                    if tile is None:
                        continue
                    state = acct.get("state", "idle")
                    msg = acct.get("message", "")
                    raw = acct.get("raw", "")
                    tile.set_state(state, msg, raw)
                    self._cards[game].append({
                        "section_index": i,
                        "global_index": i,
                        "tile": tile,
                        "launch_btn": tile.primary_button,
                        "state": state,
                    })
            self._rebuild_sections_container()
            self._layout.addStretch()
            return

        # Real mode: pull accounts from cred_manager and populate sections.
        for game in ("ttr", "cc"):
            section = self._sections[game]
            accounts = self._game_accounts_with_indices(game)
            account_dicts = []
            for _global_idx, acct in accounts:
                account_dicts.append({
                    "label": getattr(acct, "label", "") or "",
                    "username": getattr(acct, "username", "") or "",
                })
            section.set_accounts(account_dicts)

            for section_idx, (global_idx, acct) in enumerate(accounts):
                tile = section.tile_at(section_idx)
                if tile is None:
                    continue
                self._cards[game].append({
                    "section_index": section_idx,
                    "global_index": global_idx,
                    "tile": tile,
                    "launch_btn": tile.primary_button,
                    "state": LoginState.IDLE,
                })

        self._rebuild_sections_container()
        self._layout.addStretch()

        # Re-apply the RUNNING state to any slot whose launcher is still
        # alive. Same v2.1.3-issue-5 mitigation as the previous version.
        self._restore_running_state_from_launchers()

    def _restore_running_state_from_launchers(self):
        for game in ("ttr", "cc"):
            for section_idx, launcher in enumerate(self._launchers[game]):
                if launcher is None or not launcher.is_running():
                    continue
                if section_idx >= len(self._cards[game]):
                    continue
                self._update_status(game, section_idx, LoginState.RUNNING, "Game running")

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
        from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
        # Find the current position of the container in self._layout so we
        # can re-insert the replacement at the same slot. Default to the
        # current count (appended) when no container exists yet; addStretch
        # hasn't been called yet during the _build_ui first-init path.
        insert_index = self._layout.count()
        if self._sections_container is not None:
            insert_index = self._layout.indexOf(self._sections_container)
            self._sections_container.setParent(None)
            self._sections_container.deleteLater()
            self._sections_container = None
        # Detach sections from their current parent before adopting them.
        self.ttr_section.setParent(None)
        self.cc_section.setParent(None)

        container = QWidget()
        if self._layout_mode == "full":
            lay = QHBoxLayout(container)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(12)
            lay.addWidget(self.ttr_section, 1)
            lay.addWidget(self.cc_section, 1)
        else:
            lay = QVBoxLayout(container)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(12)
            lay.addWidget(self.ttr_section, alignment=Qt.AlignHCenter)
            lay.addWidget(self.cc_section, alignment=Qt.AlignHCenter)
        self._sections_container = container
        self._layout.insertWidget(insert_index, container)

    # ── Account actions ────────────────────────────────────────────────────

    def _on_add_account(self, game: str):
        editor = AccountEditor(game=game, mode="add", parent=self.window())

        def _save(label: str, username: str, password: str):
            self.cred_manager.add_account(
                label=label, username=username, password=password, game=game,
            )
            self._build_ui()
            self.refresh_theme()

        editor.account_saved.connect(_save)
        editor.exec()

    def _on_tile_edit(self, game: str, section_index: int):
        cards = self._cards[game]
        if section_index >= len(cards):
            return
        card = cards[section_index]
        global_idx = card["global_index"]
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
            self._build_ui()
            self.refresh_theme()
            game_label = "TTR" if game == "ttr" else "CC"
            self.log(f"[Launch] {game_label} account {section_index + 1} updated.")

        editor.account_saved.connect(_save)
        editor.exec()

    def clear_all_credentials(self):
        for game in ("ttr", "cc"):
            for worker in self._workers[game]:
                if worker:
                    self._disconnect_worker_signals(worker)
                    worker.cancel()
            for launcher in self._launchers[game]:
                if launcher:
                    self._disconnect_launcher_signals(launcher)
                    launcher.kill()
        tokens = self.cred_manager.clear_all()
        for token in tokens:
            threading.Thread(
                target=revoke_launcher_token,
                args=(token,),
                daemon=True,
            ).start()
        self._build_ui()
        self.refresh_theme()

    def _on_delete(self, game: str, section_index: int):
        cards = self._cards[game]
        if section_index >= len(cards):
            return
        card = cards[section_index]
        global_idx = card["global_index"]
        acct = self.cred_manager.get_account_metadata(global_idx)
        name = (acct.label or acct.username) if acct else f"account {section_index + 1}"

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

        # Cancel any active worker/launcher
        if self._workers[game][section_index]:
            self._disconnect_worker_signals(self._workers[game][section_index])
            self._workers[game][section_index].cancel()
            self._workers[game][section_index] = None
        if self._launchers[game][section_index]:
            self._disconnect_launcher_signals(self._launchers[game][section_index])
            self._launchers[game][section_index].kill()
            self._launchers[game][section_index] = None

        result = self.cred_manager.delete_account(global_idx)
        if result is not None:
            _account_id, token = result
            if token:
                threading.Thread(
                    target=revoke_launcher_token,
                    args=(token,),
                    daemon=True,
                ).start()
        self._build_ui()
        self.refresh_theme()

    def _on_tile_quit(self, game: str, section_index: int):
        """Quit the running launcher for this slot, with optional confirm."""
        launcher = self._launchers[game][section_index] if section_index < len(self._launchers[game]) else None
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
        self.log(f"[Launch] Terminating {game_label} game {section_index + 1}…")
        launcher.kill()

    def _on_tile_cancel(self, game: str, section_index: int):
        worker = self._workers[game][section_index] if section_index < len(self._workers[game]) else None
        if worker is None:
            return
        try:
            worker.cancel()
        except Exception:  # noqa: BLE001
            pass
        self._update_status(game, section_index, LoginState.IDLE, "")

    def _on_tile_enter_2fa(self, game: str, section_index: int):
        worker = self._workers[game][section_index] if section_index < len(self._workers[game]) else None
        if worker is None:
            self.log(f"[2fa] no active worker for {game}/{section_index}; nothing to prompt")
            return
        banner = "Two-Factor Authentication required"
        self._prompt_2fa(game, section_index, banner)

    def _on_tile_expand_error(self, game: str, section_index: int):
        cards = self._cards[game]
        if section_index >= len(cards):
            return
        card = cards[section_index]
        tile = card.get("tile")
        if tile is None:
            return
        acct = self.cred_manager.get_account_metadata(card["global_index"])
        name = (acct.label or acct.username) if acct else f"Account {section_index + 1}"
        raw = getattr(tile, "raw_error_message", "") or "No additional detail."
        ErrorModal(
            account_name=name, game=game, raw_message=raw, parent=self.window(),
        ).exec()

    # ── Launch flow ────────────────────────────────────────────────────────

    def _on_launch(self, game: str, section_index: int):
        from utils.credentials_manager import _dbg
        _dbg(f"[Credentials] _on_launch click: game={game} slot={section_index} "
             f"probe_pending={getattr(self.cred_manager, 'keyring_probe_pending', False)} "
             f"available={getattr(self.cred_manager, 'keyring_available', True)}")
        cards = self._cards[game]
        if section_index >= len(cards):
            _dbg(f"[Credentials] _on_launch: section_index {section_index} out of range ({len(cards)})")
            return
        card = cards[section_index]
        global_idx = card["global_index"]

        # CC: block launch when multi-install is ambiguous (no stored pick).
        if game == "cc":
            if not _cc_launch_gate(self.settings_manager, parent=self.window()):
                return

        # Check engine path
        engine_dir = self._get_engine_dir(game)
        exe_fn = get_engine_executable_name if game == "ttr" else get_cc_engine_executable_name
        engine_bin = os.path.join(engine_dir, exe_fn()) if engine_dir else ""
        if not engine_dir or not os.path.isfile(engine_bin):
            _dbg(f"[Credentials] _on_launch: engine not found (dir='{engine_dir}' bin='{engine_bin}')")
            msg = "Game path not set. Configure in Settings."
            self._update_status(game, section_index, LoginState.FAILED, msg)
            self._show_failure_dialog(game, section_index, msg)
            return

        acct = self.cred_manager.get_account(global_idx)
        acct_desc = (
            f"acct_exists={acct is not None} "
            f"username={'present' if (acct and acct.username) else 'empty'} "
            f"password={'present' if (acct and acct.password) else 'empty'}"
            if acct is not None else "acct_exists=False"
        )
        _dbg(f"[Credentials] _on_launch slot={section_index} {acct_desc}")
        if not acct or not acct.username:
            msg = "Missing username. Click Edit."
            self._update_status(game, section_index, LoginState.FAILED, msg)
            self._show_failure_dialog(game, section_index, msg)
            return
        # TTR still requires a password up front. CC accounts may legitimately
        # have no password (token-only model after register_and_login).
        if game == "ttr" and not acct.password:
            msg = "Missing username or password. Click Edit."
            self._update_status(game, section_index, LoginState.FAILED, msg)
            self._show_failure_dialog(game, section_index, msg)
            return

        # Check if already running
        launcher = self._launchers[game][section_index]
        if launcher and launcher.is_running():
            game_label = "TTR" if game == "ttr" else "CC"
            self.log(f"[Launch] Terminating {game_label} game {section_index + 1}…")
            launcher.kill()
            return

        # Cancel any previous worker
        worker = self._workers[game][section_index]
        if worker:
            self._disconnect_worker_signals(worker)
            worker.cancel()
            self._workers[game][section_index] = None
        launcher = self._launchers[game][section_index]
        if launcher:
            self._disconnect_launcher_signals(launcher)
            self._launchers[game][section_index] = None

        # Create game-specific worker and launcher, wire signals.
        worker, launcher = self._make_launchers(game, section_index)

        # Start login
        if game == "ttr":
            worker.login(acct.username, acct.password)
        else:
            # CC: dispatch by stored credential shape.
            print(f"[Launch] CC dispatch slot={section_index} "
                  f"has_token={bool(acct.launcher_token)} has_password={bool(acct.password)}")
            if acct.launcher_token:
                print("[Launch] CC dispatch: -> login_with_token (token-only path)")
                worker.login_with_token(acct.launcher_token)
            elif acct.password:
                print("[Launch] CC dispatch: -> register_and_login (legacy migration path)")
                worker.launcher_token_obtained.connect(
                    lambda tok, aid=acct.id: self._persist_launcher_token(aid, tok)
                )
                worker.register_and_login(acct.username, acct.password,
                                          label=acct.label or "")
            else:
                print("[Launch] CC dispatch: -> error branch, no credentials")
                msg = "No CC credentials stored. Click Edit on this account."
                self._update_status(game, section_index, LoginState.FAILED, msg)
                self._show_failure_dialog(game, section_index, msg)
                return
        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] Logging in {game_label} account {section_index + 1}…")

    def _make_launchers(self, game: str, section_index: int):
        """Create a fresh worker/launcher pair for *game* at *section_index*,
        store them in the internal registries, connect their signals, and
        return ``(worker, launcher)``.
        """
        if game == "ttr":
            worker = TTRLoginWorker(self)
            launcher = TTRLauncher(self, settings_manager=self.settings_manager)
        else:
            worker = CCLoginWorker(self)
            launcher = CCLauncher(self, settings_manager=self.settings_manager)

        if game == "cc":
            self._wine_console_hider.attach(launcher)

        self._workers[game][section_index] = worker
        self._launchers[game][section_index] = launcher

        # Connect signals
        worker.state_changed.connect(lambda s, m, g=game, si=section_index: self._update_status(g, si, s, m))
        worker.queue_update.connect(lambda p, e, g=game, si=section_index: self._update_queue(g, si, p, e))
        worker.need_2fa.connect(lambda banner, g=game, si=section_index: self._prompt_2fa(g, si, banner))
        worker.login_success.connect(lambda gs, ck, g=game, si=section_index: self._on_login_success(g, si, gs, ck))
        worker.login_failed.connect(lambda msg, g=game, si=section_index: self._on_login_failed(g, si, msg))

        launcher.game_launched.connect(lambda pid, g=game, si=section_index: self._on_game_launched(g, si, pid))
        launcher.game_exited.connect(lambda rc, g=game, si=section_index: self._on_game_exited(g, si, rc))
        launcher.launch_failed.connect(lambda msg, g=game, si=section_index: self._on_launcher_failed(g, si, msg))

        return worker, launcher

    def _persist_launcher_token(self, account_id: str, token: str) -> None:
        """Save a CC launcher token to keyring AND clear the now-redundant
        password (token-only model). Best-effort: keyring errors are logged
        but don't block the launch.
        """
        print(f"[Launch] _persist_launcher_token: aid={account_id[:8]} token_len={len(token) if token else 0}")
        try:
            self.cred_manager.set_launcher_token(account_id, token)
            print(f"[Launch] _persist_launcher_token: set_launcher_token ok")
            idx = self._index_of_account_id(account_id)
            print(f"[Launch] _persist_launcher_token: account index={idx}")
            if idx is not None:
                self.cred_manager.update_account(idx, password="")
                print(f"[Launch] _persist_launcher_token: cleared password for idx={idx}")
        except Exception as e:
            from utils.credentials_manager import _dbg
            print(f"[Launch] _persist_launcher_token: FAILED {type(e).__name__}: {e}")
            _dbg(f"[Credentials] _persist_launcher_token({account_id[:8]}) failed: {type(e).__name__}: {e}")

    def _index_of_account_id(self, account_id: str) -> int | None:
        for i, a in enumerate(self.cred_manager.get_accounts_metadata()):
            if a.id == account_id:
                return i
        return None

    def _on_login_success(self, game, section_index, gameserver, token):
        game_label = "TTR" if game == "ttr" else "CC"
        print(f"[Launch] _on_login_success: game={game} slot={section_index} "
              f"gameserver='{gameserver}' token_len={len(token) if token else 0}")
        self.log(f"[Launch] {game_label} account {section_index + 1} authenticated. Launching game…")
        launcher = self._launchers[game][section_index]
        print(f"[Launch] _on_login_success: launcher_ref={launcher!r}")
        if launcher:
            if game == "cc":
                install = self._build_cc_install()
                print(f"[Launch] _on_login_success: cc install={install!r}")
                if install is None:
                    msg = "Game path not set. Configure in Settings."
                    self._update_status(game, section_index, LoginState.FAILED, msg)
                    self._show_failure_dialog(game, section_index, msg)
                    return
                cc_accounts = self._game_accounts_with_indices("cc")
                username = ""
                if section_index < len(cc_accounts):
                    _flat_idx, acct = cc_accounts[section_index]
                    username = acct.username or ""
                print(f"[Launch] _on_login_success: invoking CCLauncher.launch username_len={len(username)}")
                from services.cc_login_service import CC_DEFAULT_REALM
                launcher.launch(gameserver, token, install,
                                username=username, realm_slug=CC_DEFAULT_REALM)
            else:
                engine_dir = self._get_engine_dir(game)
                launcher.launch(gameserver, token, engine_dir)

    def _on_login_failed(self, game, section_index, msg):
        game_label = "TTR" if game == "ttr" else "CC"
        print(f"[Launch] _on_login_failed: game={game} slot={section_index} msg={msg!r}")
        self.log(f"[Launch] {game_label} account {section_index + 1} login failed: {msg}")
        self._update_status(game, section_index, LoginState.FAILED, msg)
        self._show_failure_dialog(game, section_index, msg)

    def _on_launcher_failed(self, game, section_index, msg):
        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] {game_label} account {section_index + 1} launch failed: {msg}")
        self._update_status(game, section_index, LoginState.FAILED, msg)
        self._show_failure_dialog(game, section_index, msg)

    def _show_failure_dialog(self, game, section_index, msg):
        """Pop a modal warning dialog with the full failure message.

        Called from every terminal failure dispatch site. See spec
        docs/superpowers/specs/2026-05-17-login-failure-dialog-design.md.
        """
        from PySide6.QtWidgets import QMessageBox
        game_label = "Toontown Rewritten" if game == "ttr" else "Corporate Clash"
        box = QMessageBox(self.window())
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(f"{game_label} login failed")
        box.setText(f"Account {section_index + 1} couldn't sign in.")
        box.setInformativeText(msg)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()

    def _on_game_launched(self, game, section_index, pid):
        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] {game_label} account {section_index + 1} game running (PID {pid})")
        self._update_status(game, section_index, LoginState.RUNNING, "Game running")

    def _on_game_exited(self, game, section_index, retcode):
        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] {game_label} account {section_index + 1} game exited (code {retcode})")
        # game crash / kill: status band carries the exit code; no login-failure dialog (post-launch is out of scope)
        if retcode not in (0, -9, -15, None):
            self._update_status(game, section_index, LoginState.FAILED, f"Failed: code {retcode}")
        else:
            self._update_status(game, section_index, LoginState.IDLE, "")

    def _prompt_2fa(self, game, section_index, banner):
        """Show 2FA input dialog."""
        key = (game, section_index)
        if key in self._pending_2fa:
            return
        self._pending_2fa.add(key)

        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] {game_label} account {section_index + 1} requires 2FA.")
        token, ok = QInputDialog.getText(
            self, "Two-Factor Authentication",
            f"{banner}\n\nEnter your authenticator code:",
            QLineEdit.Password,
        )
        self._pending_2fa.discard(key)
        worker = self._workers[game][section_index] if section_index < len(self._workers[game]) else None
        if ok and token.strip():
            if worker:
                worker.submit_2fa(token.strip())
        else:
            if worker:
                worker.cancel()
            self._update_status(game, section_index, LoginState.IDLE, "2FA cancelled")

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

    def _update_status(self, game, section_index, state, message):
        cards = self._cards[game]
        if section_index >= len(cards):
            return
        card = cards[section_index]
        card["state"] = state
        tile = card.get("tile")
        if tile is None:
            return
        # AccountTile expects the same lowercase string used by LoginState's
        # class attributes (idle/logging_in/queued/launching/running/failed/
        # need_2fa).
        raw = message if state == LoginState.FAILED else ""
        tile.set_state(state, message or "", raw)

    def update_dot_state(self, index: int, state_str: str):
        """Called from multitoon tab - index is global slot position.

        For now, only TTR cards are updated since CC has no companion API.
        The new AccountTile drives its own running-state pulse; this method
        only stamps the sync_state into the card record so visual code that
        consults `card['sync_state']` keeps working.
        """
        cards = self._cards["ttr"]
        if index >= len(cards):
            return
        card = cards[index]
        card["sync_state"] = state_str

        launcher = self._launchers["ttr"][index] if index < len(self._launchers["ttr"]) else None
        if launcher and launcher.is_running():
            tile = card.get("tile")
            if tile is not None and getattr(tile, "status_dot", None) is not None:
                color = {
                    "active": "#56c856",
                    "idle":   "#888888",
                    "warn":   "#E8A838",
                    "error":  "#E05252",
                }.get(state_str, "#56c856")
                tile.status_dot.set_color(color, pulse=(state_str == "active"))

    def _update_queue(self, game, section_index, position, eta):
        cards = self._cards[game]
        if section_index >= len(cards):
            return
        card = cards[section_index]
        tile = card.get("tile")
        if tile is None:
            return
        tile.set_state(LoginState.QUEUED, f"#{position} (~{eta}s)")

    # ── Settings callback ──────────────────────────────────────────────────

    def on_max_accounts_changed(self, value: int):
        """Called when the max accounts per game setting changes."""
        max_per = self._max_per_game()
        self.ttr_section._max = max_per
        self.cc_section._max = max_per
        self._build_ui()
        self.refresh_theme()

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

        if self._keyring_banner is not None:
            if hasattr(self._keyring_banner, "refresh_theme"):
                self._keyring_banner.refresh_theme(c, is_dark)

    # ── Logging ────────────────────────────────────────────────────────────

    def log(self, msg):
        if self.logger:
            self.logger.append_log(msg)
        else:
            print(msg)

    def shutdown(self):
        if self._probe_thread is not None and self._probe_thread.isRunning():
            self._probe_thread.quit()
            self._probe_thread.wait(2000)
