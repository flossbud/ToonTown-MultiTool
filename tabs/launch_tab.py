"""
Launch Tab — Manage TTR accounts and launch game instances.

Up to 8 account slots with encrypted credential storage.
Handles login, 2FA, queue waiting, and game launch.
"""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QLineEdit, QFileDialog, QInputDialog,
    QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from utils.theme_manager import (
    resolve_theme, get_theme_colors, apply_card_shadow, make_trash_icon,
)
from utils.credentials_manager import CredentialsManager
from services.ttr_login_service import TTRLoginWorker, LoginState, find_engine_path
from services.ttr_launcher import TTRLauncher


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


class LaunchTab(QWidget):
    def __init__(self, settings_manager=None, logger=None, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.logger = logger
        self.cred_manager = CredentialsManager()
        self._workers: list[TTRLoginWorker | None] = [None] * 8
        self._launchers: list[TTRLauncher | None] = [None] * 8
        self._cards: list[dict] = []
        self._engine_dir = None

        # Auto-detect engine path
        saved_path = settings_manager.get("ttr_engine_dir", "") if settings_manager else ""
        if saved_path and os.path.isfile(os.path.join(saved_path, "TTREngine")):
            self._engine_dir = saved_path
        else:
            self._engine_dir = find_engine_path()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
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
        self._layout.setContentsMargins(12, 16, 12, 16)
        self._layout.setSpacing(10)
        self._layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self._scroll.setWidget(self._scroll_widget)
        outer.addWidget(self._scroll)

        self._build_ui()
        self.refresh_theme()

    # ── Build UI ───────────────────────────────────────────────────────────

    def _build_ui(self):
        # Clear layout
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._cards.clear()

        # ── Game path row ──────────────────────────────────────────────
        path_frame = QFrame()
        path_frame.setObjectName("path_frame")
        path_frame.setFixedWidth(420)
        path_lay = QHBoxLayout(path_frame)
        path_lay.setContentsMargins(10, 6, 10, 6)
        path_lay.setSpacing(6)

        path_label = QLabel("Game Path:")
        path_label.setObjectName("path_label")
        path_lay.addWidget(path_label)

        self._path_display = QLabel()
        self._path_display.setObjectName("path_display")
        self._path_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._update_path_display()
        path_lay.addWidget(self._path_display, 1)

        browse_btn = QPushButton("Browse")
        browse_btn.setFixedHeight(28)
        browse_btn.setCursor(Qt.PointingHandCursor)
        browse_btn.setToolTip("Select the folder containing TTREngine")
        browse_btn.clicked.connect(self._browse_engine)
        browse_btn.setObjectName("browse_btn")
        path_lay.addWidget(browse_btn)

        detect_btn = QPushButton("Auto-detect")
        detect_btn.setFixedHeight(28)
        detect_btn.setCursor(Qt.PointingHandCursor)
        detect_btn.setToolTip("Scan common locations for TTREngine")
        detect_btn.clicked.connect(self._auto_detect_engine)
        detect_btn.setObjectName("detect_btn")
        path_lay.addWidget(detect_btn)

        self._layout.addWidget(path_frame, alignment=Qt.AlignHCenter)
        self._layout.addSpacing(4)

        # ── Account cards ──────────────────────────────────────────────
        accounts = self.cred_manager.get_accounts()
        for idx, acct in enumerate(accounts):
            card = self._make_card(idx, acct)
            self._layout.addWidget(card["frame"], alignment=Qt.AlignHCenter)
            self._cards.append(card)

        # ── Add account button ─────────────────────────────────────────
        self._add_btn = QPushButton("+ Add Account")
        self._add_btn.setFixedHeight(38)
        self._add_btn.setMaximumWidth(260)
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.setToolTip("Add a new TTR account (max 8)")
        self._add_btn.clicked.connect(self._on_add_account)
        self._add_btn.setVisible(self.cred_manager.count() < 8)
        self._layout.addWidget(self._add_btn, alignment=Qt.AlignHCenter)

        self._layout.addStretch()

    def _make_card(self, index: int, acct) -> dict:
        """Build an account card. Returns dict of widgets for later reference."""
        frame = QFrame()
        frame.setObjectName("account_card")
        frame.setFixedWidth(420)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        # ── Top row: status dot + label + username subtitle ────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        status_dot = QFrame()
        status_dot.setFixedSize(10, 10)
        status_dot.setObjectName("status_dot")
        status_dot.setStyleSheet("background: #555; border-radius: 5px;")
        top_row.addWidget(status_dot)

        # Name + username stacked
        name_col = QVBoxLayout()
        name_col.setSpacing(0)

        display_name = acct.label or acct.username or f"Account {index + 1}"
        label_display = QLabel(display_name)
        label_display.setObjectName("acct_label")
        label_display.setMaximumWidth(200)
        label_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        label_display.setTextInteractionFlags(Qt.NoTextInteraction)
        name_col.addWidget(label_display)

        username = acct.username
        # Only show username subtitle if there's a label and they differ
        username_lbl = QLabel(username if username and username != display_name else "")
        username_lbl.setObjectName("acct_username")
        username_lbl.setMaximumWidth(200)
        username_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        username_lbl.setTextInteractionFlags(Qt.NoTextInteraction)
        username_lbl.setVisible(bool(username and username != display_name))
        name_col.addWidget(username_lbl)

        top_row.addLayout(name_col)
        top_row.addStretch()

        # ── Buttons: Launch, Edit, Delete ──────────────────────────────
        launch_btn = QPushButton("Launch")
        launch_btn.setFixedHeight(26)
        launch_btn.setCursor(Qt.PointingHandCursor)
        launch_btn.setObjectName("launch_btn")
        launch_btn.setToolTip("Log in and launch this account")
        launch_btn.clicked.connect(lambda _, idx=index: self._on_launch(idx))
        top_row.addWidget(launch_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedHeight(26)
        edit_btn.setCursor(Qt.PointingHandCursor)
        edit_btn.setObjectName("edit_btn")
        edit_btn.setToolTip("Edit account credentials")
        edit_btn.clicked.connect(lambda _, idx=index: self._toggle_edit(idx))
        top_row.addWidget(edit_btn)

        del_btn = QPushButton()
        del_btn.setFixedSize(26, 26)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setObjectName("del_btn")
        del_btn.setToolTip("Remove this account")
        del_btn.clicked.connect(lambda _, idx=index: self._on_delete(idx))
        top_row.addWidget(del_btn)

        lay.addLayout(top_row)

        # ── Status message (hidden when idle) ──────────────────────────
        status_label = QLabel("")
        status_label.setObjectName("acct_status")
        status_label.setVisible(False)
        status_label.setContentsMargins(18, 0, 0, 0)
        lay.addWidget(status_label)

        # ── Edit fields (hidden by default) ────────────────────────────
        edit_frame = QFrame()
        edit_frame.setObjectName("edit_frame")
        edit_frame.setVisible(False)
        edit_lay = QVBoxLayout(edit_frame)
        edit_lay.setContentsMargins(8, 8, 8, 8)
        edit_lay.setSpacing(6)

        label_edit = QLineEdit(acct.label)
        label_edit.setObjectName("label_edit")
        label_edit.setPlaceholderText("Friendly name (optional)")
        label_edit.setFixedHeight(28)
        edit_lay.addWidget(label_edit)

        user_edit = QLineEdit(acct.username)
        user_edit.setObjectName("user_edit")
        user_edit.setPlaceholderText("TTR username")
        user_edit.setFixedHeight(28)
        edit_lay.addWidget(user_edit)

        pass_edit = QLineEdit(acct.password)
        pass_edit.setObjectName("pass_edit")
        pass_edit.setPlaceholderText("TTR password")
        pass_edit.setEchoMode(QLineEdit.Password)
        pass_edit.setFixedHeight(28)
        edit_lay.addWidget(pass_edit)

        save_row = QHBoxLayout()
        save_row.setSpacing(6)
        save_row.addStretch()
        save_btn = QPushButton("Save")
        save_btn.setFixedHeight(26)
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setObjectName("save_btn")
        save_btn.clicked.connect(lambda _, idx=index: self._save_edit(idx))
        save_row.addWidget(save_btn)
        cancel_edit_btn = QPushButton("Cancel")
        cancel_edit_btn.setFixedHeight(26)
        cancel_edit_btn.setCursor(Qt.PointingHandCursor)
        cancel_edit_btn.setObjectName("cancel_edit_btn")
        cancel_edit_btn.clicked.connect(lambda _, idx=index: self._cancel_edit(idx))
        save_row.addWidget(cancel_edit_btn)
        edit_lay.addLayout(save_row)

        lay.addWidget(edit_frame)

        # ── Queue progress (hidden by default) ─────────────────────────
        queue_label = QLabel("")
        queue_label.setObjectName("queue_label")
        queue_label.setVisible(False)
        queue_label.setContentsMargins(18, 0, 0, 0)
        lay.addWidget(queue_label)

        return {
            "frame": frame, "index": index,
            "label_display": label_display, "username_lbl": username_lbl,
            "status_dot": status_dot, "status_label": status_label,
            "edit_frame": edit_frame,
            "label_edit": label_edit, "user_edit": user_edit, "pass_edit": pass_edit,
            "launch_btn": launch_btn, "edit_btn": edit_btn, "del_btn": del_btn,
            "queue_label": queue_label,
        }

    # ── Path management ────────────────────────────────────────────────────

    def _update_path_display(self):
        if self._engine_dir:
            # Show shortened path
            home = os.path.expanduser("~")
            display = self._engine_dir.replace(home, "~")
            self._path_display.setText(display)
            self._path_display.setStyleSheet("font-size: 11px; color: #56c856;")
        else:
            self._path_display.setText("Not found — click Browse or Auto-detect")
            self._path_display.setStyleSheet("font-size: 11px; color: #E05252;")

    def _browse_engine(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select TTR Game Directory",
            os.path.expanduser("~"),
        )
        if dir_path:
            engine = os.path.join(dir_path, "TTREngine")
            if os.path.isfile(engine):
                self._engine_dir = dir_path
                if self.settings_manager:
                    self.settings_manager.set("ttr_engine_dir", dir_path)
                self._update_path_display()
                self.log(f"[Launch] Engine path set: {dir_path}")
            else:
                self._path_display.setText("TTREngine not found in that folder")
                self._path_display.setStyleSheet("font-size: 11px; color: #E05252;")

    def _auto_detect_engine(self):
        path = find_engine_path()
        if path:
            self._engine_dir = path
            if self.settings_manager:
                self.settings_manager.set("ttr_engine_dir", path)
            self._update_path_display()
            self.log(f"[Launch] Auto-detected engine: {path}")
        else:
            self._path_display.setText("Could not auto-detect — click Browse")
            self._path_display.setStyleSheet("font-size: 11px; color: #E05252;")

    # ── Account actions ────────────────────────────────────────────────────

    def _on_add_account(self):
        self.cred_manager.add_account(label="", username="", password="")
        self._build_ui()
        self.refresh_theme()
        # Auto-open edit mode on the new card
        new_idx = self.cred_manager.count() - 1
        if new_idx < len(self._cards):
            self._toggle_edit(new_idx)

    def clear_all_credentials(self):
        for worker in self._workers:
            if worker:
                worker.cancel()
        for launcher in self._launchers:
            if launcher:
                launcher.kill()
        self.cred_manager.clear_all()
        self._build_ui()
        self.refresh_theme()

    def _on_delete(self, index):
        # Cancel any active worker
        if self._workers[index]:
            self._workers[index].cancel()
            self._workers[index] = None
        if self._launchers[index]:
            self._launchers[index].kill()
            self._launchers[index] = None
        self.cred_manager.delete_account(index)
        self._build_ui()
        self.refresh_theme()

    def _toggle_edit(self, index):
        if index >= len(self._cards):
            return
        card = self._cards[index]
        visible = not card["edit_frame"].isVisible()
        card["edit_frame"].setVisible(visible)
        card["edit_btn"].setText("Cancel" if visible else "Edit")

    def _cancel_edit(self, index):
        if index >= len(self._cards):
            return
        card = self._cards[index]
        # Restore original values
        acct = self.cred_manager.get_account(index)
        if acct:
            card["label_edit"].setText(acct.label)
            card["user_edit"].setText(acct.username)
            card["pass_edit"].setText(acct.password)
        card["edit_frame"].setVisible(False)
        card["edit_btn"].setText("Edit")

    def _save_edit(self, index):
        if index >= len(self._cards):
            return
        card = self._cards[index]
        label = card["label_edit"].text().strip()
        username = card["user_edit"].text().strip()
        password = card["pass_edit"].text()

        self.cred_manager.update_account(index, label=label, username=username, password=password)

        # Update display
        display_name = label or username or f"Account {index + 1}"
        card["label_display"].setText(display_name)
        card["username_lbl"].setText(username if username and username != display_name else "")
        card["username_lbl"].setVisible(bool(username and username != display_name))
        card["edit_frame"].setVisible(False)
        card["edit_btn"].setText("Edit")
        self.log(f"[Launch] Account {index + 1} updated.")

    # ── Launch flow ────────────────────────────────────────────────────────

    def _on_launch(self, index):
        if index >= len(self._cards):
            return

        # Check engine path
        if not self._engine_dir or not os.path.isfile(os.path.join(self._engine_dir, "TTREngine")):
            self._update_status(index, LoginState.FAILED, "Game path not set — configure above")
            return

        acct = self.cred_manager.get_account(index)
        if not acct or not acct.username or not acct.password:
            self._update_status(index, LoginState.FAILED, "Missing username or password — click Edit")
            return

        # Check if already running
        launcher = self._launchers[index]
        if launcher and launcher.is_running():
            self._update_status(index, LoginState.RUNNING, "Game already running")
            return

        # Cancel any previous worker for this slot
        worker = self._workers[index]
        if worker:
            worker.cancel()

        # Create new worker
        worker = TTRLoginWorker(self)
        self._workers[index] = worker
        
        # Create new launcher
        launcher = TTRLauncher(self)
        self._launchers[index] = launcher

        # Connect signals
        worker.state_changed.connect(lambda s, m, idx=index: self._update_status(idx, s, m))
        worker.queue_update.connect(lambda p, e, idx=index: self._update_queue(idx, p, e))
        worker.need_2fa.connect(lambda banner, idx=index: self._prompt_2fa(idx, banner))
        worker.login_success.connect(lambda gs, ck, idx=index: self._on_login_success(idx, gs, ck))
        worker.login_failed.connect(lambda msg, idx=index: self._update_status(idx, LoginState.FAILED, msg))

        launcher.game_launched.connect(lambda pid, idx=index: self._on_game_launched(idx, pid))
        launcher.game_exited.connect(lambda rc, idx=index: self._on_game_exited(idx, rc))
        launcher.launch_failed.connect(lambda msg, idx=index: self._update_status(idx, LoginState.FAILED, msg))

        # Start login
        worker.login(acct.username, acct.password)
        self.log(f"[Launch] Logging in account {index + 1}…")

    def _on_login_success(self, index, gameserver, cookie):
        self.log(f"[Launch] Account {index + 1} authenticated. Launching game…")
        launcher = self._launchers[index]
        if launcher:
            launcher.launch(gameserver, cookie, self._engine_dir)

    def _on_game_launched(self, index, pid):
        self.log(f"[Launch] Account {index + 1} game running (PID {pid})")
        if index < len(self._cards):
            card = self._cards[index]
            card["launch_btn"].setText("Running")
            card["launch_btn"].setEnabled(False)

    def _on_game_exited(self, index, retcode):
        self.log(f"[Launch] Account {index + 1} game exited (code {retcode})")
        if index < len(self._cards):
            card = self._cards[index]
            card["launch_btn"].setText("Launch")
            card["launch_btn"].setEnabled(True)

    def _prompt_2fa(self, index, banner):
        """Show 2FA input dialog."""
        self.log(f"[Launch] Account {index + 1} requires 2FA.")
        token, ok = QInputDialog.getText(
            self, "Two-Factor Authentication",
            f"{banner}\n\nEnter your authenticator code:",
        )
        if ok and token.strip():
            worker = self._workers[index]
            if worker:
                worker.submit_2fa(token.strip())
        else:
            # User cancelled 2FA
            worker = self._workers[index]
            if worker:
                worker.cancel()
            self._update_status(index, LoginState.IDLE, "2FA cancelled")

    # ── Status updates ─────────────────────────────────────────────────────

    def _update_status(self, index, state, message):
        if index >= len(self._cards):
            return
        card = self._cards[index]
        color = STATUS_COLORS.get(state, "#555555")

        # Update dot color
        card["status_dot"].setStyleSheet(f"background: {color}; border-radius: 5px;")

        # Show status message only when not idle
        if state == LoginState.IDLE:
            card["status_label"].setVisible(False)
        else:
            card["status_label"].setText(message)
            card["status_label"].setStyleSheet(
                f"font-size: 11px; color: {color}; background: none; border: none;"
            )
            card["status_label"].setVisible(True)

        # Show/hide queue label
        card["queue_label"].setVisible(state == LoginState.QUEUED)

        # Update launch button state
        if state == LoginState.RUNNING:
            card["launch_btn"].setText("Running")
            card["launch_btn"].setEnabled(False)
        elif state in (LoginState.LOGGING_IN, LoginState.QUEUED, LoginState.LAUNCHING):
            card["launch_btn"].setText("Wait…")
            card["launch_btn"].setEnabled(False)
        else:
            card["launch_btn"].setText("Launch")
            card["launch_btn"].setEnabled(True)

    def _update_queue(self, index, position, eta):
        if index >= len(self._cards):
            return
        card = self._cards[index]
        card["queue_label"].setText(f"Position: {position} — Estimated wait: ~{eta}s")
        card["queue_label"].setVisible(True)

    # ── Theme ──────────────────────────────────────────────────────────────

    def _c(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

    def refresh_theme(self):
        c = self._c()
        is_dark = resolve_theme(self.settings_manager) == "dark"

        self.setStyleSheet(f"background: {c['bg_app']}; color: {c['text_primary']};")
        self._scroll.setStyleSheet(self._scroll.styleSheet())
        self._scroll_widget.setStyleSheet(f"background: {c['bg_app']};")

        # Path frame
        for pf in self.findChildren(QFrame, "path_frame"):
            pf.setStyleSheet(f"""
                QFrame#path_frame {{
                    background: {c['bg_card_inner']};
                    border: 1px solid {c['border_muted']};
                    border-radius: 8px;
                }}
            """)

        for lbl in self.findChildren(QLabel, "path_label"):
            lbl.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {c['text_secondary']}; background: none; border: none;")

        btn_style = f"""
            QPushButton {{
                background: {c['btn_bg']}; color: {c['text_primary']};
                border: 1px solid {c['btn_border']}; border-radius: 6px;
                font-size: 11px; font-weight: 600; padding: 4px 10px;
            }}
            QPushButton:hover {{
                background: {c['accent_blue_btn']}; color: white;
                border: 1px solid {c['accent_blue_btn_border']};
            }}
        """
        for btn in self.findChildren(QPushButton, "browse_btn"):
            btn.setStyleSheet(btn_style)
        for btn in self.findChildren(QPushButton, "detect_btn"):
            btn.setStyleSheet(btn_style)

        # Account cards
        for card in self._cards:
            idx = card["index"]
            card["frame"].setStyleSheet(f"""
                QFrame#account_card {{
                    background: {c['bg_card_inner']};
                    border: 1px solid {c['border_muted']};
                    border-radius: 10px;
                }}
            """)
            apply_card_shadow(card["frame"], is_dark)

            card["label_display"].setStyleSheet(
                f"font-size: 13px; font-weight: bold; color: {c['text_primary']}; background: none; border: none;"
            )

            card["username_lbl"].setStyleSheet(
                f"font-size: 11px; color: {c['text_secondary']}; background: none; border: none;"
            )

            # Edit frame
            card["edit_frame"].setStyleSheet(f"""
                QFrame#edit_frame {{
                    background: {c['bg_input']};
                    border: 1px solid {c['border_input']};
                    border-radius: 6px;
                }}
            """)

            edit_input_style = f"""
                QLineEdit {{
                    background: {c['bg_card_inner']};
                    color: {c['text_primary']};
                    border: 1px solid {c['border_input']};
                    border-radius: 4px; font-size: 12px; padding: 2px 6px;
                }}
                QLineEdit:focus {{
                    border: 1px solid {c['accent_blue_btn']};
                }}
            """
            card["label_edit"].setStyleSheet(edit_input_style)
            card["user_edit"].setStyleSheet(edit_input_style)
            card["pass_edit"].setStyleSheet(edit_input_style)

            # Compact button style
            compact_btn = f"""
                QPushButton {{
                    background: {c['accent_blue_btn']}; color: white;
                    font-weight: 600; font-size: 11px;
                    border: 1px solid {c['accent_blue_btn_border']};
                    border-radius: 5px; padding: 2px 10px;
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

            card["edit_btn"].setStyleSheet(f"""
                QPushButton {{
                    background: {c['btn_bg']}; color: {c['text_primary']};
                    font-size: 11px; font-weight: 600;
                    border: 1px solid {c['btn_border']}; border-radius: 5px;
                    padding: 2px 10px;
                }}
                QPushButton:hover {{
                    background: {c['accent_blue_btn']}; color: white;
                    border: 1px solid {c['accent_blue_btn_border']};
                }}
            """)

            card["del_btn"].setIcon(make_trash_icon(14, QColor(c['text_secondary'])))
            card["del_btn"].setStyleSheet(f"""
                QPushButton#del_btn {{
                    background: transparent;
                    border: 1px solid {c['border_muted']};
                    border-radius: 5px;
                }}
                QPushButton#del_btn:hover {{
                    background: {c['accent_red']};
                    border: 1px solid {c['accent_red_border']};
                }}
            """)

            for sb in card["edit_frame"].findChildren(QPushButton, "save_btn"):
                sb.setStyleSheet(f"""
                    QPushButton {{
                        background: {c['accent_blue_btn']}; color: white;
                        font-weight: bold; font-size: 11px;
                        border: 1px solid {c['accent_blue_btn_border']};
                        border-radius: 5px; padding: 2px 10px;
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
                        border-radius: 5px; padding: 2px 10px;
                    }}
                    QPushButton:hover {{
                        background: {c['accent_red']}; color: white;
                        border: 1px solid {c['accent_red_border']};
                    }}
                """)

            card["queue_label"].setStyleSheet(
                f"font-size: 11px; color: #E8A838; background: none; border: none;"
            )

        # Add button
        if hasattr(self, "_add_btn"):
            self._add_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {c['btn_bg']}; color: {c['text_primary']};
                    border: 1px solid {c['btn_border']};
                    border-radius: 8px; font-weight: bold; font-size: 13px;
                }}
                QPushButton:hover {{
                    background: {c['accent_blue_btn']}; color: white;
                    border: 1px solid {c['accent_blue_btn_border']};
                }}
            """)

    # ── Logging ────────────────────────────────────────────────────────────

    def log(self, msg):
        if self.logger:
            self.logger.append_log(msg)
        else:
            print(msg)