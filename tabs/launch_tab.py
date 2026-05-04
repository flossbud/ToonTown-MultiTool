"""
Launch Tab — Manage TTR and Corporate Clash accounts and launch game instances.

Accounts are tagged per-game ("ttr" or "cc") and displayed in two separate
sections within one scrollable list. Each section has its own "+ Add Account"
button. Workers and launchers are stored per-game so TTR and CC never interfere.
"""

import os
import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QLineEdit, QInputDialog,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QObject, Signal, QThread, Slot
from PySide6.QtGui import QColor, QPainter
from utils.theme_manager import (
    resolve_theme, get_theme_colors, apply_card_shadow, make_trash_icon,
    make_edit_icon, make_section_label,
)
from utils.credentials_manager import CredentialsManager, set_debug_log_callback
from services.ttr_login_service import TTRLoginWorker, LoginState, find_engine_path, get_engine_executable_name
from services.ttr_launcher import TTRLauncher
from services.cc_login_service import CCLoginWorker, find_cc_engine_path, get_cc_engine_executable_name
from services.cc_launcher import CCLauncher
from utils.shared_widgets import PulsingDot


# ── Status colors ──────────────────────────────────────────────────────────

STATUS_COLORS = {
    LoginState.IDLE: "#888888",
    LoginState.LOGGING_IN: "#E8A838",
    LoginState.NEED_2FA: "#C87EE8",
    LoginState.QUEUED: "#E8A838",
    LoginState.LAUNCHING: "#56c856",
    LoginState.RUNNING: "#56c856",
    LoginState.FAILED: "#E05252",
}

STATUS_LABELS = {
    LoginState.IDLE: "",
    LoginState.LOGGING_IN: "Logging in…",
    LoginState.NEED_2FA: "2FA Required",
    LoginState.QUEUED: "In Queue",
    LoginState.LAUNCHING: "Launching…",
    LoginState.RUNNING: "Running",
    LoginState.FAILED: "Failed",
}

# Slot badge colors — distinct per-slot identity
SLOT_COLORS = {
    "ttr": [
        "#4A8FE7", "#E05252", "#E8A838", "#56c856",
        "#C87EE8", "#E08640", "#C4A46C", "#8B6948",
    ],
    "cc": [
        "#F26D21", "#D94E1F", "#E8963A", "#C8551A",
        "#F09030", "#B84A18", "#D97B30", "#A04010",
    ],
}

GAME_LABELS = {
    "ttr": "TOONTOWN REWRITTEN",
    "cc": "CORPORATE CLASH",
}

GAME_ACCENT = {
    "ttr": "#4A8FE7",
    "cc": "#F26D21",
}

MAX_PER_GAME = 8  # hard ceiling
LINUX_KEYRING_HELP_URL = "https://wiki.archlinux.org/title/Secret_Service"


# ── Animated Edit Panel ───────────────────────────────────────────────────

class AnimatedEditPanel(QFrame):
    """Edit panel that smoothly expands/collapses with height animation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anim = QPropertyAnimation(self, b"maximumHeight")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def expand(self):
        self.setVisible(True)
        target = self.sizeHint().height()
        self._anim.stop()
        self._anim.setStartValue(0)
        self._anim.setEndValue(target)
        self._anim.finished.connect(self._on_expand_done)
        self._anim.start()

    def _on_expand_done(self):
        try:
            self._anim.finished.disconnect(self._on_expand_done)
        except RuntimeError:
            pass
        self.setMaximumHeight(16777215)

    def collapse(self):
        self._anim.stop()
        self._anim.setStartValue(self.height())
        self._anim.setEndValue(0)
        self._anim.finished.connect(self._on_collapse_done)
        self._anim.start()

    def _on_collapse_done(self):
        try:
            self._anim.finished.disconnect(self._on_collapse_done)
        except RuntimeError:
            pass
        self.setVisible(False)
        self.setMaximumHeight(16777215)


# ── Slot Badge ────────────────────────────────────────────────────────────

class SlotBadge(QWidget):
    """Small colored circle with slot number."""

    def __init__(self, index: int, game: str = "ttr", parent=None):
        super().__init__(parent)
        self._index = index
        colors = SLOT_COLORS.get(game, SLOT_COLORS["ttr"])
        self._color = QColor(colors[index % len(colors)])
        self.setFixedSize(24, 24)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Circle
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(2, 2, 20, 20)
        # Number
        p.setPen(QColor("#ffffff"))
        font = p.font()
        font.setPixelSize(11)
        font.setBold(True)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignCenter, str(self._index + 1))
        p.end()


# ── Status Chip ───────────────────────────────────────────────────────────

class StatusChip(QLabel):
    """Small pill label showing login/run status."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(20)
        self.hide()

    def set_status(self, state, message=""):
        color = STATUS_COLORS.get(state, "#888888")
        label = message or STATUS_LABELS.get(state, "")
        if state == LoginState.IDLE or not label:
            self.hide()
            return
        self.setText(label)
        self.setToolTip(label)
        self.setStyleSheet(
            f"font-size: 10px; font-weight: 600; color: {color}; "
            f"background: {color}22; border: 1px solid {color}44; "
            f"border-radius: 10px; padding: 1px 8px;"
        )
        self.setFixedWidth(max(self.fontMetrics().horizontalAdvance(label) + 20, 60))


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
        self.link_label.setOpenExternalLinks(True)
        self.link_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
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
                "Windows Credential Locker was unavailable. Try running TTMT as your\n"
                "normal user (not as Administrator)."
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
    def __init__(self, settings_manager=None, logger=None, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.logger = logger
        # Tee credential diagnostics into the in-app log via the debug tab.
        # This uses a QTimer trampoline so the callback is safe to fire from
        # the keyring probe thread.
        if self.logger is not None:
            from PySide6.QtCore import QTimer
            def _tee(msg, _log=self.logger.append_log):
                QTimer.singleShot(0, lambda m=msg: _log(m))
            set_debug_log_callback(_tee)
        self.cred_manager = CredentialsManager()

        # Per-game workers and launchers
        self._workers = {"ttr": [None] * MAX_PER_GAME, "cc": [None] * MAX_PER_GAME}
        self._launchers = {"ttr": [None] * MAX_PER_GAME, "cc": [None] * MAX_PER_GAME}
        self._cards = {"ttr": [], "cc": []}
        self._section_labels = {}
        self._add_btns = {}
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
        self._scroll.setStyleSheet("""
            QScrollBar:vertical {
                background: transparent; width: 6px; margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.15); border-radius: 3px; min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.25); }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)

        self._scroll_widget = QWidget()
        self._layout = QVBoxLayout(self._scroll_widget)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(0)
        self._layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self._scroll.setWidget(self._scroll_widget)
        outer.addWidget(self._scroll)

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
            return min(self.settings_manager.get("max_accounts_per_game", 4), MAX_PER_GAME)
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
        for signal_name in ("state_changed", "queue_update", "need_2fa", "login_success", "login_failed"):
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
        self._probe_thread.finished.connect(self._probe_worker.deleteLater)
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
            self._probe_thread.deleteLater()
        self._probe_thread = None
        self._probe_worker = None

    def _set_launch_buttons_enabled(self, enabled: bool):
        for game in ("ttr", "cc"):
            for card in self._cards[game]:
                if card.get("state") in (LoginState.LOGGING_IN, LoginState.QUEUED, LoginState.LAUNCHING):
                    continue
                card["launch_btn"].setEnabled(enabled)
                if enabled:
                    card["launch_btn"].setToolTip("Log in and launch this account")
                else:
                    card["launch_btn"].setToolTip("Waiting for credential storage...")

    # ── Build UI ───────────────────────────────────────────────────────────

    def _build_ui(self):
        # Clear layout
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._cards = {"ttr": [], "cc": []}
        self._section_labels.clear()
        self._add_btns.clear()
        self._keyring_banner = None

        if self.cred_manager.keyring_probe_pending:
            self._keyring_banner = KeyringPendingBanner(parent=self)
            self._layout.addWidget(self._keyring_banner, alignment=Qt.AlignHCenter)
            self._layout.addSpacing(12)
        elif not self.cred_manager.keyring_available:
            self._keyring_banner = KeyringWarningBanner(self.cred_manager, parent=self)
            self._layout.addWidget(self._keyring_banner, alignment=Qt.AlignHCenter)
            self._layout.addSpacing(12)

        max_per = self._max_per_game()

        for game in ("ttr", "cc"):
            self._build_game_section(game, max_per)

        self._layout.addStretch()

    def _build_game_section(self, game: str, max_per: int):
        c = self._c()

        # Section header
        label_text = GAME_LABELS[game]
        section_lbl = make_section_label(label_text, c)
        self._section_labels[game] = section_lbl
        self._layout.addWidget(section_lbl)
        self._layout.addSpacing(8)

        # Account rows
        accounts = self._game_accounts_with_indices(game)
        for section_idx, (global_idx, acct) in enumerate(accounts):
            card = self._make_row(game, section_idx, global_idx, acct)
            self._layout.addWidget(card["frame"], alignment=Qt.AlignHCenter)
            self._layout.addSpacing(6)
            self._cards[game].append(card)

        # Add account button
        game_upper = "TTR" if game == "ttr" else "CC"
        add_btn = QPushButton(f"+ Add {game_upper} Account")
        add_btn.setObjectName(f"add_account_btn_{game}")
        add_btn.setFixedHeight(44)
        add_btn.setMaximumWidth(480)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setToolTip(f"Add a new {GAME_LABELS[game].title()} account")
        add_btn.clicked.connect(lambda _, g=game: self._on_add_account(g))
        add_btn.setVisible(len(accounts) < max_per)
        self._add_btns[game] = add_btn
        self._layout.addWidget(add_btn, alignment=Qt.AlignHCenter)

        self._layout.addSpacing(20)

    def _make_row(self, game: str, section_index: int, global_index: int, acct) -> dict:
        """Build a compact account row with expandable edit panel."""
        # ── Outer container (row + edit panel stacked vertically) ──────
        frame = QFrame()
        frame.setObjectName("account_row")
        frame.setMaximumWidth(480)
        # Layout-only container; the inner row_inner owns the visible card
        # shape (rounded). Without this, the outer frame inherits the global
        # QWidget gradient and paints a mini-gradient that bleeds through at
        # the inner widget's rounded corners.
        frame.setStyleSheet("QFrame#account_row { background: transparent; }")
        frame_lay = QVBoxLayout(frame)
        frame_lay.setContentsMargins(0, 0, 0, 0)
        frame_lay.setSpacing(0)

        # ── Main row ──────────────────────────────────────────────────
        row_widget = QWidget()
        row_widget.setObjectName("row_inner")
        row_widget.setFixedHeight(52)
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(10)

        # Slot badge (numbered per section, colored per game)
        badge = SlotBadge(section_index, game)
        row.addWidget(badge)

        # Name column
        name_col = QVBoxLayout()
        name_col.setSpacing(0)
        name_col.setContentsMargins(0, 0, 0, 0)

        display_name = acct.label or acct.username or f"Account {section_index + 1}"
        label_display = QLabel(display_name)
        label_display.setObjectName("acct_label")
        label_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        label_display.setTextInteractionFlags(Qt.NoTextInteraction)
        name_col.addWidget(label_display)

        username = acct.username
        username_lbl = QLabel(username if username and username != display_name else "")
        username_lbl.setObjectName("acct_username")
        username_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        username_lbl.setTextInteractionFlags(Qt.NoTextInteraction)
        username_lbl.setVisible(bool(username and username != display_name))
        name_col.addWidget(username_lbl)

        row.addLayout(name_col, 1)

        # Status chip
        status_chip = StatusChip()
        row.addWidget(status_chip)

        # Status dot (small, for pulsing active indicator)
        status_dot = PulsingDot(8)
        status_dot.setObjectName("status_dot")
        row.addWidget(status_dot)

        # Launch button
        launch_btn = QPushButton("Launch")
        launch_btn.setFixedSize(68, 28)
        launch_btn.setCursor(Qt.PointingHandCursor)
        launch_btn.setObjectName("launch_btn")
        if self.cred_manager.keyring_probe_pending:
            launch_btn.setEnabled(False)
            launch_btn.setToolTip("Waiting for credential storage...")
        else:
            launch_btn.setToolTip("Log in and launch this account")
        launch_btn.clicked.connect(lambda _, g=game, si=section_index: self._on_launch(g, si))
        row.addWidget(launch_btn)

        # Edit button (icon)
        edit_btn = QPushButton()
        edit_btn.setFixedSize(28, 28)
        edit_btn.setCursor(Qt.PointingHandCursor)
        edit_btn.setObjectName("edit_btn")
        edit_btn.setToolTip("Edit account credentials")
        edit_btn.clicked.connect(lambda _, g=game, si=section_index: self._toggle_edit(g, si))
        row.addWidget(edit_btn)

        # Delete button
        del_btn = QPushButton()
        del_btn.setFixedSize(28, 28)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setObjectName("del_btn")
        del_btn.setToolTip("Remove this account")
        del_btn.clicked.connect(lambda _, g=game, si=section_index: self._on_delete(g, si))
        row.addWidget(del_btn)

        frame_lay.addWidget(row_widget)

        # ── Animated edit panel ───────────────────────────────────────
        edit_frame = AnimatedEditPanel()
        edit_frame.setObjectName("edit_frame")
        edit_frame.setVisible(False)
        edit_frame.setMaximumHeight(0)
        edit_lay = QVBoxLayout(edit_frame)
        edit_lay.setContentsMargins(12, 10, 12, 10)
        edit_lay.setSpacing(8)

        game_label = "TTR" if game == "ttr" else "CC"

        label_edit = QLineEdit(acct.label)
        label_edit.setObjectName("label_edit")
        label_edit.setPlaceholderText("Friendly name (optional)")
        label_edit.setFixedHeight(30)
        edit_lay.addWidget(label_edit)

        user_edit = QLineEdit(acct.username)
        user_edit.setObjectName("user_edit")
        user_edit.setPlaceholderText(f"{game_label} username")
        user_edit.setFixedHeight(30)
        edit_lay.addWidget(user_edit)

        pass_edit = QLineEdit()
        pass_edit.setObjectName("pass_edit")
        pass_edit.setPlaceholderText(f"{game_label} password (leave blank to keep current)")
        pass_edit.setEchoMode(QLineEdit.Password)
        pass_edit.setFixedHeight(30)
        edit_lay.addWidget(pass_edit)

        save_row = QHBoxLayout()
        save_row.setSpacing(6)
        save_row.addStretch()
        save_btn = QPushButton("Save")
        save_btn.setFixedHeight(28)
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setObjectName("save_btn")
        save_btn.clicked.connect(lambda _, g=game, si=section_index: self._save_edit(g, si))
        save_row.addWidget(save_btn)
        cancel_edit_btn = QPushButton("Cancel")
        cancel_edit_btn.setFixedHeight(28)
        cancel_edit_btn.setCursor(Qt.PointingHandCursor)
        cancel_edit_btn.setObjectName("cancel_edit_btn")
        cancel_edit_btn.clicked.connect(lambda _, g=game, si=section_index: self._cancel_edit(g, si))
        save_row.addWidget(cancel_edit_btn)
        edit_lay.addLayout(save_row)

        frame_lay.addWidget(edit_frame)

        return {
            "frame": frame, "game": game,
            "section_index": section_index, "global_index": global_index,
            "row_widget": row_widget,
            "label_display": label_display, "username_lbl": username_lbl,
            "status_dot": status_dot, "status_chip": status_chip,
            "edit_frame": edit_frame,
            "label_edit": label_edit, "user_edit": user_edit, "pass_edit": pass_edit,
            "launch_btn": launch_btn, "edit_btn": edit_btn, "del_btn": del_btn,
            "state": LoginState.IDLE,
        }

    # ── Account actions ────────────────────────────────────────────────────

    def _on_add_account(self, game: str):
        self.cred_manager.add_account(label="", username="", password="", game=game)
        self._build_ui()
        self.refresh_theme()
        # Auto-open edit mode on the new card
        cards = self._cards[game]
        if cards:
            self._toggle_edit(game, len(cards) - 1)

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
        self.cred_manager.clear_all()
        self._build_ui()
        self.refresh_theme()

    def _on_delete(self, game: str, section_index: int):
        cards = self._cards[game]
        if section_index >= len(cards):
            return
        card = cards[section_index]
        global_idx = card["global_index"]

        # Cancel any active worker/launcher
        if self._workers[game][section_index]:
            self._disconnect_worker_signals(self._workers[game][section_index])
            self._workers[game][section_index].cancel()
            self._workers[game][section_index] = None
        if self._launchers[game][section_index]:
            self._disconnect_launcher_signals(self._launchers[game][section_index])
            self._launchers[game][section_index].kill()
            self._launchers[game][section_index] = None

        self.cred_manager.delete_account(global_idx)
        self._build_ui()
        self.refresh_theme()

    def _toggle_edit(self, game: str, section_index: int):
        cards = self._cards[game]
        if section_index >= len(cards):
            return
        card = cards[section_index]
        if card["edit_frame"].isVisible():
            card["edit_frame"].collapse()
        else:
            card["edit_frame"].expand()

    def _cancel_edit(self, game: str, section_index: int):
        cards = self._cards[game]
        if section_index >= len(cards):
            return
        card = cards[section_index]
        acct = self.cred_manager.get_account_metadata(card["global_index"])
        if acct:
            card["label_edit"].setText(acct.label)
            card["user_edit"].setText(acct.username)
        card["pass_edit"].clear()
        card["edit_frame"].collapse()

    def _save_edit(self, game: str, section_index: int):
        cards = self._cards[game]
        if section_index >= len(cards):
            return
        card = cards[section_index]
        global_idx = card["global_index"]

        label = card["label_edit"].text().strip()
        username = card["user_edit"].text().strip()

        if not username:
            card["user_edit"].setPlaceholderText("Username is required")
            return

        new_password = card["pass_edit"].text()
        password = new_password if new_password else None

        self.cred_manager.update_account(global_idx, label=label, username=username, password=password)

        display_name = label or username or f"Account {section_index + 1}"
        card["label_display"].setText(display_name)
        card["username_lbl"].setText(username if username and username != display_name else "")
        card["username_lbl"].setVisible(bool(username and username != display_name))
        card["pass_edit"].clear()
        card["edit_frame"].collapse()

        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] {game_label} account {section_index + 1} updated.")

    # ── Launch flow ────────────────────────────────────────────────────────

    def _on_launch(self, game: str, section_index: int):
        from utils.credentials_manager import _dbg
        _dbg(f"[Credentials] _on_launch click: game={game} slot={section_index} "
             f"probe_pending={self.cred_manager.keyring_probe_pending} "
             f"available={self.cred_manager.keyring_available}")
        cards = self._cards[game]
        if section_index >= len(cards):
            _dbg(f"[Credentials] _on_launch: section_index {section_index} out of range ({len(cards)})")
            return
        card = cards[section_index]
        global_idx = card["global_index"]

        # Check engine path
        engine_dir = self._get_engine_dir(game)
        exe_fn = get_engine_executable_name if game == "ttr" else get_cc_engine_executable_name
        engine_bin = os.path.join(engine_dir, exe_fn()) if engine_dir else ""
        if not engine_dir or not os.path.isfile(engine_bin):
            _dbg(f"[Credentials] _on_launch: engine not found (dir='{engine_dir}' bin='{engine_bin}')")
            self._update_status(game, section_index, LoginState.FAILED, "Game path not set — configure in Settings")
            return

        acct = self.cred_manager.get_account(global_idx)
        acct_desc = (
            f"acct_exists={acct is not None} "
            f"username={'present' if (acct and acct.username) else 'empty'} "
            f"password={'present' if (acct and acct.password) else 'empty'}"
            if acct is not None else "acct_exists=False"
        )
        _dbg(f"[Credentials] _on_launch slot={section_index} {acct_desc}")
        if not acct or not acct.username or not acct.password:
            self._update_status(game, section_index, LoginState.FAILED, "Missing username or password — click Edit")
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

        # Create game-specific worker and launcher
        if game == "ttr":
            worker = TTRLoginWorker(self)
            launcher = TTRLauncher(self, settings_manager=self.settings_manager)
        else:
            worker = CCLoginWorker(self)
            launcher = CCLauncher(self, settings_manager=self.settings_manager)

        self._workers[game][section_index] = worker
        self._launchers[game][section_index] = launcher

        # Connect signals
        worker.state_changed.connect(lambda s, m, g=game, si=section_index: self._update_status(g, si, s, m))
        worker.queue_update.connect(lambda p, e, g=game, si=section_index: self._update_queue(g, si, p, e))
        worker.need_2fa.connect(lambda banner, g=game, si=section_index: self._prompt_2fa(g, si, banner))
        worker.login_success.connect(lambda gs, ck, g=game, si=section_index: self._on_login_success(g, si, gs, ck))
        worker.login_failed.connect(lambda msg, g=game, si=section_index: self._update_status(g, si, LoginState.FAILED, msg))

        launcher.game_launched.connect(lambda pid, g=game, si=section_index: self._on_game_launched(g, si, pid))
        launcher.game_exited.connect(lambda rc, g=game, si=section_index: self._on_game_exited(g, si, rc))
        launcher.launch_failed.connect(lambda msg, g=game, si=section_index: self._update_status(g, si, LoginState.FAILED, msg))

        # Start login
        worker.login(acct.username, acct.password)
        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] Logging in {game_label} account {section_index + 1}…")

    def _on_login_success(self, game, section_index, gameserver, token):
        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] {game_label} account {section_index + 1} authenticated. Launching game…")
        launcher = self._launchers[game][section_index]
        if launcher:
            engine_dir = self._get_engine_dir(game)
            launcher.launch(gameserver, token, engine_dir)

    def _on_game_launched(self, game, section_index, pid):
        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] {game_label} account {section_index + 1} game running (PID {pid})")
        self._update_status(game, section_index, LoginState.RUNNING, "Game running")

    def _on_game_exited(self, game, section_index, retcode):
        game_label = "TTR" if game == "ttr" else "CC"
        self.log(f"[Launch] {game_label} account {section_index + 1} game exited (code {retcode})")
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
        if ok and token.strip():
            worker = self._workers[game][section_index]
            if worker:
                worker.submit_2fa(token.strip())
        else:
            worker = self._workers[game][section_index]
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
        color = STATUS_COLORS.get(state, "#555555")

        # Update dot
        if state == LoginState.RUNNING:
            sync_state = card.get("sync_state", "active")
            card["status_dot"].set_state(sync_state)
        elif state == LoginState.IDLE:
            card["status_dot"].set_color(self._c()["border_light"], pulse=False)
        else:
            pulse = state in (LoginState.LOGGING_IN, LoginState.LAUNCHING)
            card["status_dot"].set_color(color, pulse=pulse)

        # Update status chip
        chip_text = message or STATUS_LABELS.get(state, "")
        card["status_chip"].set_status(state, chip_text)

        # Update row tint
        self._apply_row_style(card)

        # Update launch button state
        if state == LoginState.RUNNING:
            card["launch_btn"].setText("Quit")
            card["launch_btn"].setEnabled(True)
            card["launch_btn"].setStyleSheet(
                "QPushButton { background-color: #E05252; color: white; "
                "border: 1px solid #c0392b; border-radius: 6px; font-weight: 600; font-size: 11px; }"
                "QPushButton:hover { background-color: #c0392b; }"
            )
        else:
            c = self._c()
            compact_btn = f"""
                QPushButton {{
                    background: {c['accent_blue_btn']}; color: {c['text_on_accent']};
                    font-weight: 600; font-size: 11px;
                    border: 1px solid {c['accent_blue_btn_border']};
                    border-radius: 6px; padding: 2px 10px;
                }}
                QPushButton:hover {{
                    background: {c['accent_blue_btn_hover']};
                }}
                QPushButton:disabled {{
                    background: {c['btn_bg']}; color: {c['text_secondary']};
                    border: 1px solid {c['border_muted']};
                }}
            """
            card["launch_btn"].setStyleSheet(compact_btn)
            if state in (LoginState.LOGGING_IN, LoginState.QUEUED, LoginState.LAUNCHING):
                card["launch_btn"].setText("Wait…")
                card["launch_btn"].setEnabled(False)
            else:
                card["launch_btn"].setText("Launch")
                card["launch_btn"].setEnabled(True)

    def update_dot_state(self, index: int, state_str: str):
        """Called from multitoon tab — index is global slot position.

        For now, only TTR cards are updated since CC has no companion API.
        """
        cards = self._cards["ttr"]
        if index >= len(cards):
            return
        card = cards[index]
        card["sync_state"] = state_str

        launcher = self._launchers["ttr"][index] if index < len(self._launchers["ttr"]) else None
        if launcher and launcher.is_running():
            card["status_dot"].set_state(state_str)

    def _update_queue(self, game, section_index, position, eta):
        cards = self._cards[game]
        if section_index >= len(cards):
            return
        card = cards[section_index]
        card["status_chip"].set_status(
            LoginState.QUEUED,
            f"Queue: #{position} (~{eta}s)"
        )

    # ── Settings callback ──────────────────────────────────────────────────

    def on_max_accounts_changed(self, value: int):
        """Called when the max accounts per game setting changes."""
        self._build_ui()
        self.refresh_theme()

    # ── Theme ──────────────────────────────────────────────────────────────

    def _c(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

    def _apply_row_style(self, card):
        """Apply the correct row_inner background based on state."""
        c = self._c()
        state = card.get("state", LoginState.IDLE)
        if state == LoginState.RUNNING:
            bg = "#1a2e1a" if resolve_theme(self.settings_manager) == "dark" else "#e8f5e8"
            border = "#2d5a2d" if resolve_theme(self.settings_manager) == "dark" else "#a8d5a8"
        else:
            bg = c['bg_card_inner']
            border = c['border_muted']

        card["row_widget"].setStyleSheet(f"""
            QWidget#row_inner {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 10px;
            }}
        """)

    def refresh_theme(self):
        c = self._c()
        is_dark = resolve_theme(self.settings_manager) == "dark"

        self.setStyleSheet(f"background: {c['bg_app']}; color: {c['text_primary']};")
        self._scroll.setStyleSheet(self._scroll.styleSheet())
        self._scroll_widget.setStyleSheet(f"background: {c['bg_app']};")

        if self._keyring_banner is not None:
            if hasattr(self._keyring_banner, "refresh_theme"):
                self._keyring_banner.refresh_theme(c, is_dark)

        # Section labels
        for game, lbl in self._section_labels.items():
            accent = GAME_ACCENT[game]
            lbl.setStyleSheet(
                f"font-size: 10px; font-weight: 600; color: {accent}; "
                f"background: transparent; border: none; letter-spacing: 0.8px;"
            )

        # Account rows (both games)
        for game in ("ttr", "cc"):
            for card in self._cards[game]:
                self._apply_row_style(card)
                apply_card_shadow(card["frame"], is_dark)

                # Re-color idle status dots so theme toggle takes effect live
                if card.get("state", LoginState.IDLE) == LoginState.IDLE:
                    card["status_dot"].set_color(c["border_light"], pulse=False)

                card["label_display"].setStyleSheet(
                    f"font-size: 13px; font-weight: bold; color: {c['text_primary']}; "
                    f"background: none; border: none;"
                )

                card["username_lbl"].setStyleSheet(
                    f"font-size: 10px; color: {c['text_secondary']}; "
                    f"background: none; border: none;"
                )

                # Edit frame
                card["edit_frame"].setStyleSheet(f"""
                    QFrame#edit_frame {{
                        background: {c['bg_input']};
                        border: 1px solid {c['border_input']};
                        border-top: none;
                        border-radius: 0 0 10px 10px;
                    }}
                """)

                edit_input_style = f"""
                    QLineEdit {{
                        background: {c['bg_card_inner']};
                        color: {c['text_primary']};
                        border: 1px solid {c['border_input']};
                        border-radius: 6px; font-size: 12px; padding: 4px 8px;
                    }}
                    QLineEdit:focus {{
                        border: 1px solid {c['accent_blue_btn']};
                    }}
                """
                card["label_edit"].setStyleSheet(edit_input_style)
                card["user_edit"].setStyleSheet(edit_input_style)
                card["pass_edit"].setStyleSheet(edit_input_style)

                # Launch button — re-apply only if not in running state
                state = card.get("state", LoginState.IDLE)
                if state != LoginState.RUNNING:
                    compact_btn = f"""
                        QPushButton {{
                            background: {c['accent_blue_btn']}; color: {c['text_on_accent']};
                            font-weight: 600; font-size: 11px;
                            border: 1px solid {c['accent_blue_btn_border']};
                            border-radius: 6px; padding: 2px 10px;
                        }}
                        QPushButton:hover {{
                            background: {c['accent_blue_btn_hover']};
                        }}
                        QPushButton:disabled {{
                            background: {c['btn_bg']}; color: {c['text_secondary']};
                            border: 1px solid {c['border_muted']};
                        }}
                    """
                    card["launch_btn"].setStyleSheet(compact_btn)

                # Edit button (icon)
                card["edit_btn"].setIcon(make_edit_icon(14, QColor(c['text_secondary'])))
                card["edit_btn"].setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        border: 1px solid {c['border_muted']}; border-radius: 6px;
                    }}
                    QPushButton:hover {{
                        background: {c['accent_blue_btn']};
                        border: 1px solid {c['accent_blue_btn_border']};
                    }}
                """)

                card["del_btn"].setIcon(make_trash_icon(14, QColor(c['text_secondary'])))
                card["del_btn"].setStyleSheet(f"""
                    QPushButton#del_btn {{
                        background: transparent;
                        border: 1px solid {c['border_muted']};
                        border-radius: 6px;
                    }}
                    QPushButton#del_btn:hover {{
                        background: {c['accent_red']};
                        border: 1px solid {c['accent_red_border']};
                    }}
                """)

                for sb in card["edit_frame"].findChildren(QPushButton, "save_btn"):
                    sb.setStyleSheet(f"""
                        QPushButton {{
                            background: {c['accent_blue_btn']}; color: {c['text_on_accent']};
                            font-weight: bold; font-size: 11px;
                            border: 1px solid {c['accent_blue_btn_border']};
                            border-radius: 6px; padding: 2px 12px;
                        }}
                        QPushButton:hover {{
                            background: {c['accent_blue_btn_hover']};
                        }}
                    """)
                for cb in card["edit_frame"].findChildren(QPushButton, "cancel_edit_btn"):
                    cb.setStyleSheet(f"""
                        QPushButton {{
                            background: {c['btn_bg']}; color: {c['text_primary']};
                            font-size: 11px; border: 1px solid {c['btn_border']};
                            border-radius: 6px; padding: 2px 12px;
                        }}
                        QPushButton:hover {{
                            background: {c['accent_red']}; color: {c['text_on_accent']};
                            border: 1px solid {c['accent_red_border']};
                        }}
                    """)

        # Add buttons — dashed border placeholder style
        for game, btn in self._add_btns.items():
            accent = GAME_ACCENT[game]
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {c['text_muted']};
                    border: 2px dashed {c['border_muted']};
                    border-radius: 10px; font-weight: 600; font-size: 12px;
                }}
                QPushButton:hover {{
                    color: {accent};
                    border-color: {accent};
                    background: {c['bg_card_inner']};
                }}
            """)

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
