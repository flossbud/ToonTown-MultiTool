"""The Accounts sheet: every saved account by game, and one account's page.

Content for ``SlideSheetHost``. Everything it shows comes from an
``AccountsBackend`` and every change goes back through it; the sheet keeps
only what is on screen (which page, which form or question is open).

Two pages share the sheet: the list, and one account. The host's header
follows the page (``header_changed``, and a back button on the account page
once the sheet is attached to its host).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from utils.asset_paths import asset_path
from utils.icon_factory import make_key_icon, make_person_icon
from utils.widgets.launchpad import accounts_model as m
from utils.widgets.launchpad.accounts_parts import (
    BLUE, KIND_DANGER, AccountRow, ConfirmRow, LoginForm, LoginRow, PillButton,
    ToonSlot, palette,
)
from utils.widgets.launchpad.material import (
    AddRow, GroupCard, PlainCard, SheetRow, note_label, sheet_stack,
)

IDENTITY = m.IDENTITY
TITLE = "Accounts"
GAME_LOGO = {"ttr": "ttr.png", "cc": "cc.png"}
LOGO_PX = 30
LABEL_FIELD_W = 210


class _GameCard(GroupCard):
    """A game's accounts: the game's logo where other cards have a disc."""

    def __init__(self, game: str, is_dark: bool, parent=None):
        super().__init__(m.GAME_COLORS[game], m.GAME_NAMES[game], None,
                         meta=m.card_meta(0), is_dark=is_dark, parent=parent)
        self.game = game
        self.disc.hide()
        self.logo = QLabel(self._head)
        self.logo.setFixedSize(LOGO_PX, LOGO_PX)
        self.logo.setStyleSheet("background: transparent;")
        source = QPixmap(asset_path(GAME_LOGO[game]))
        if not source.isNull():
            dpr = self.devicePixelRatioF()
            scaled = source.scaled(int(LOGO_PX * dpr), int(LOGO_PX * dpr),
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            self.logo.setPixmap(scaled)
            self.logo.setAlignment(Qt.AlignCenter)
        self._head.layout().insertWidget(0, self.logo)


class AccountsSheet(QWidget):
    IDENTITY = IDENTITY
    TITLE = TITLE
    header_changed = Signal(str, str)        # title, sub
    page_changed = Signal(str)               # "" for the list, else the account id
    # A password asked for at launch was answered: account id, and whether
    # the launch went ahead (False: cancelled, or the account went away).
    launch_login_finished = Signal(str, bool)

    def __init__(self, backend, is_dark: bool = True, parent: QWidget | None = None,
                 clock=None):
        """``clock()`` gives the time "played 4d ago" is measured from; the
        system clock when omitted."""
        super().__init__(parent)
        self._backend = backend
        self._dark = bool(is_dark)
        self._clock = clock
        self._host = None
        self._account_id: str | None = None
        self._launch_login_for: str | None = None
        self._stale = False

        # What is open on the list page.
        self._add_game: str | None = None
        self._add_form: LoginForm | None = None
        # What is open on the account page.
        self._login_form: LoginForm | None = None
        self._confirm: str | None = None        # "forget" | "remove" | None
        self._label_edit: QLineEdit | None = None

        self._layout = sheet_stack(self)
        self._page: QWidget | None = None
        self.rows: dict[str, AccountRow] = {}
        self.cards: dict[str, _GameCard] = {}
        self.add_rows: dict[str, AddRow] = {}
        self.slots: list[ToonSlot] = []

        backend.changed.connect(self.refresh)
        self._build()

    # ── Public API ─────────────────────────────────────────────────────────

    def sub(self) -> str:
        """The header's sub line for the page that is showing."""
        return self._header()[1]

    def title(self) -> str:
        return self._header()[0]

    def account_id(self) -> str | None:
        """The account whose page is showing, or None on the list."""
        return self._account_id

    def attach_host(self, host) -> None:
        """Let the sheet drive its host's header and back button."""
        self._host = host
        self._sync_host()

    def show_list(self) -> None:
        self._account_id = None
        self._login_form = None
        self._confirm = None
        self._build()
        self._finish_launch_login(False)

    def open_account(self, account_id: str, form: str | None = None) -> bool:
        """Show one account's page; with ``form`` (a FORM_* mode) on its
        login form. False for an account that is not there."""
        account = self._backend.account(account_id)
        if account is None:
            return False
        self._account_id = account_id
        self._add_game = None
        self._add_form = None
        self._login_form = None
        self._confirm = None
        self._build()
        if form is not None:
            self._open_login_form(form)
        return True

    def open_fix_login(self, account_id: str) -> bool:
        """An account with a rejected sign-in, on its login form."""
        account = self._backend.account(account_id)
        if account is None:
            return False
        return self.open_account(account_id, m.login_buttons(account)[1])

    def open_launch_login(self, account_id: str) -> bool:
        """An account launched with no saved login: its page, on the form
        that takes the password and launches."""
        if self._backend.account(account_id) is None:
            return False
        self._finish_launch_login(False)        # one question at a time
        if not self.open_account(account_id, m.FORM_LAUNCH):
            return False
        self._launch_login_for = account_id
        return True

    def launch_login_account(self) -> str | None:
        """The account whose launch is waiting for a password, or None."""
        return self._launch_login_for

    def cancel_launch_login(self) -> None:
        """Drop a launch question without answering it (the sheet was
        closed): the account stays idle."""
        if self._launch_login_for is None:
            return
        form, self._login_form = self._login_form, None
        self._build()
        if form is not None:
            form.deleteLater()
        self._finish_launch_login(False)

    def _finish_launch_login(self, launched: bool) -> None:
        account_id, self._launch_login_for = self._launch_login_for, None
        if account_id is not None:
            self.launch_login_finished.emit(account_id, launched)

    def open_add_form(self, game: str) -> bool:
        """The list, with the add form open in ``game``'s card."""
        if game not in m.GAMES:
            return False
        self._account_id = None
        self._login_form = None
        self._confirm = None
        if len(self._backend.accounts(game)) >= m.MAX_ACCOUNTS_PER_GAME:
            self._add_game = None
            self._build()
            return False
        self._add_game = game
        self._add_form = None
        self._build()
        if self._add_form is not None:
            self._add_form.focus_first()
        return True

    def add_form(self) -> LoginForm | None:
        return self._add_form

    def login_form(self) -> LoginForm | None:
        return self._login_form

    def confirm_row(self) -> ConfirmRow | None:
        return getattr(self, "_confirm_row", None) if self._confirm else None

    def apply_theme(self, is_dark: bool) -> None:
        if bool(is_dark) != self._dark:
            self._dark = bool(is_dark)
            self._build()

    def refresh(self) -> None:
        """The backend changed: show it, keeping whatever the user has open
        (a form keeps the text typed into it)."""
        gone = False
        if self._account_id is not None and self._backend.account(self._account_id) is None:
            self._account_id = None             # removed underneath
            self._login_form = None
            self._confirm = None
            gone = True
        if self._add_game is not None and \
                len(self._backend.accounts(self._add_game)) >= m.MAX_ACCOUNTS_PER_GAME:
            self._add_game = None
            self._add_form = None
        if not self.isVisible() and self._page is not None:
            # Nobody is looking: rebuild when the sheet is shown again.
            self._stale = True
        else:
            self._build()
        if gone:
            self._finish_launch_login(False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._backend.set_active(True)          # may announce what it missed
        if self._stale:
            self._build()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._backend.set_active(False)

    # ── Header ─────────────────────────────────────────────────────────────

    def _header(self) -> tuple:
        account = self._backend.account(self._account_id) if self._account_id else None
        if account is not None:
            return account.title, m.account_page_sub(account)
        total = sum(len(self._backend.accounts(game)) for game in m.GAMES)
        return TITLE, m.sheet_sub(total, self._backend.keyring_available())

    def _sync_host(self) -> None:
        title, sub = self._header()
        self.header_changed.emit(title, sub)
        host = self._host
        if host is None or host.current_content() is not self:
            return
        host.set_header(title, sub)
        host.set_back(self.show_list if self._account_id is not None else None)

    # ── Building ───────────────────────────────────────────────────────────

    def _build(self) -> None:
        """Rebuild the visible page from the backend. Open forms are kept as
        they are (same widget, same typed text) and placed back."""
        self._stale = False
        keep_add = self._add_form
        keep_login = self._login_form
        label_text, label_focus = None, False
        if self._label_edit is not None:
            try:
                label_text = self._label_edit.text()
                label_focus = self._label_edit.hasFocus()
            except RuntimeError:
                label_text = None
        for form in (keep_add, keep_login):
            if form is not None:
                form.setParent(self)            # out of the page about to go
                form.hide()
        old = self._page
        self.rows, self.cards, self.add_rows, self.slots = {}, {}, {}, []
        self._label_edit = None
        self._confirm_row = None

        page = QWidget(self)
        page.setStyleSheet("background: transparent;")
        stack = sheet_stack(page)
        if self._account_id is not None:
            self._build_account_page(stack, page, keep_login, label_text, label_focus)
        else:
            self._build_list_page(stack, page, keep_add)
        self._page = page
        self._layout.addWidget(page)
        if old is not None:
            self._layout.removeWidget(old)
            old.hide()
            old.deleteLater()
        page.show()
        self.page_changed.emit(self._account_id or "")
        self._sync_host()

    # ── List page ──────────────────────────────────────────────────────────

    def _build_list_page(self, stack, page, keep_add) -> None:
        if self._add_game is None:
            keep_add = None
        for game in m.GAMES:
            accounts = self._backend.accounts(game)
            card = _GameCard(game, self._dark, page)
            card.set_meta(m.card_meta(len(accounts)))
            self.cards[game] = card
            for account in accounts:
                look = {}
                if account.primary is not None:
                    look = self._backend.look_entry(account.game, account.primary.name)
                row = AccountRow(account, look, self._dark, card)
                row.set_reorder_enabled(len(accounts) > 1)
                row.opened.connect(self._on_row_opened)
                row.fix_requested.connect(self.open_fix_login)
                row.reorder_requested.connect(self._on_account_reordered, Qt.QueuedConnection)
                self.rows[account.id] = row
                card.add_row(row)
            if self._add_game == game:
                form = keep_add if (keep_add is not None and keep_add.game() == game) \
                    else self._new_add_form(game)
                self._add_form = form
                card.add_row(form)
                form.show()
            else:
                add = AddRow(f"+  {m.add_account_text(game)}", is_dark=self._dark,
                             parent=card)
                add.setEnabled(len(accounts) < m.MAX_ACCOUNTS_PER_GAME)
                add.clicked.connect(lambda _=False, g=game: self.open_add_form(g))
                self.add_rows[game] = add
                card.add_row(add)
            stack.addWidget(card)
        if self._add_game is None:
            self._add_form = None
        if keep_add is not None and keep_add is not self._add_form:
            keep_add.deleteLater()
        stack.addStretch(1)

    def _on_account_reordered(self, source_id: str, target_id: str, before: bool) -> None:
        # Re-read after the drag: another account may have appeared or gone.
        if self._account_id is not None or source_id == target_id:
            return
        source, target = self._backend.account(source_id), self._backend.account(target_id)
        if source is None or target is None or source.game != target.game:
            return
        current = [a.id for a in self._backend.accounts(source.game) if a.id]
        if source_id not in current or target_id not in current:
            return
        ordered = list(current)
        ordered.remove(source_id)
        ordered.insert(ordered.index(target_id) + (0 if before else 1), source_id)
        if ordered != current:
            self._backend.reorder_accounts(source.game, ordered)

    def _new_add_form(self, game: str) -> LoginForm:
        form = LoginForm(m.FORM_ADD_ACCOUNT, game,
                         keyring_available=self._backend.keyring_available(),
                         is_dark=self._dark, parent=self)
        form.cancelled.connect(self._close_add_form)
        form.submitted.connect(self._on_add_submitted)
        return form

    def _close_add_form(self) -> None:
        self._add_game = None
        self._build()

    def _on_add_submitted(self, username: str, password: str, keep: bool) -> None:
        game = self._add_game
        if game is None:
            return
        form = self._add_form
        new_id = self._backend.add_account(game, username, password, keep)
        if new_id is None:
            if form is not None:
                form.error_label.setText("The account could not be added.")
                form.error_label.show()
            return
        self._add_game = None
        self._add_form = None
        self.refresh()

    def _on_row_opened(self, account_id: str) -> None:
        account = self._backend.account(account_id)
        if account is not None and account.login == m.LOGIN_FAILED and not account.running:
            # A rejected login is the one thing to do on that account.
            self.open_fix_login(account_id)
        else:
            self.open_account(account_id)

    # ── Account page ───────────────────────────────────────────────────────

    def _build_account_page(self, stack, page, keep_login, label_text, label_focus) -> None:
        account = self._backend.account(self._account_id)
        pal = palette(self._dark)

        # Login.
        login = GroupCard(BLUE, "Login", make_key_icon(15, QColor("#ffffff")),
                          is_dark=self._dark, parent=page)
        self.login_card = login
        if self._login_form is not None and keep_login is not None:
            login.add_row(keep_login)
            keep_login.show()
            self.login_row = None
        else:
            self._login_form = None
            if keep_login is not None:
                keep_login.deleteLater()
            row = LoginRow(account, self._dark, login)
            row.edit_requested.connect(self._open_login_form)
            row.reset_requested.connect(lambda: self._ask("forget"))
            self.login_row = row
            login.add_row(row)
            if account.login == m.LOGIN_FAILED and account.failed_reason:
                # The server's own words, when it gave any.
                self.reason_label = note_label(account.failed_reason, self._dark, login)
                self.reason_label.setStyleSheet(
                    self.reason_label.styleSheet()
                    + f" QLabel {{ color: {pal['red_text'].name()}; }}")
                login.add_row(self.reason_label)
            if self._confirm == "forget":
                self._confirm_row = ConfirmRow(
                    m.forget_question(account), m.FORGET_DETAIL, "Keep it",
                    "Forget login", self._dark, login)
                self._confirm_row.dismissed.connect(lambda: self._ask(None))
                self._confirm_row.confirmed.connect(self._forget_login)
                login.add_row(self._confirm_row)
        stack.addWidget(login)

        # Toons.
        shown = account.shown_toons
        toons = GroupCard(m.GAME_COLORS[account.game], "Toons on this account",
                          make_person_icon(15, QColor("#ffffff")),
                          meta=m.toons_meta(len(shown)), is_dark=self._dark, parent=page)
        self.toons_card = toons
        self.toons_note = note_label(m.TOONS_NOTE if shown else m.NO_TOONS_NOTE,
                                     self._dark, toons)
        toons.add_row(self.toons_note)
        grid_host = QWidget(toons)
        grid_host.setStyleSheet("background: transparent;")
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        primary = account.primary
        for index in range(m.TOON_SLOTS):
            toon = shown[index] if index < len(shown) else None
            look = self._backend.look_entry(toon.game, toon.name) if toon else {}
            slot = ToonSlot(toon, is_primary=(toon is not None and toon is primary),
                            look_entry=look, is_dark=self._dark,
                            now=self._clock() if self._clock is not None else None,
                            parent=grid_host)
            slot.primary_requested.connect(self._on_primary)
            slot.edit_requested.connect(self._on_edit_look)
            self.slots.append(slot)
            grid.addWidget(slot, index // 3, index % 3)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        toons.add_row(grid_host)
        stack.addWidget(toons)

        # Account.
        plain = PlainCard(self._dark, page)
        self.account_card = plain
        label_row = SheetRow("Label", m.LABEL_HELP, self._dark, plain)
        edit = QLineEdit(label_row)
        edit.setObjectName("account_label")
        edit.setPlaceholderText(m.LABEL_PLACEHOLDER)
        edit.setFixedSize(LABEL_FIELD_W, 30)
        edit.setMaxLength(48)
        edit.setText(label_text if label_text is not None and label_focus
                     else account.label)
        edit.setStyleSheet(
            f"QLineEdit#account_label {{ background: {pal['field_fill']};"
            f" border: 1px solid {pal['field_border']}; border-radius: 5px;"
            f" padding: 0 9px; color: {pal['field_text']}; font-size: 12.5px; }}"
            f"QLineEdit#account_label:focus {{ border: 1px solid #3399ff; }}")
        edit.editingFinished.connect(self._commit_label)
        label_row.set_control(edit)
        self._label_edit = edit
        self.label_edit = edit
        plain.add_row(label_row)

        remove_row = SheetRow("Remove account", m.REMOVE_HELP, self._dark, plain)
        self.remove_button = PillButton("Remove", KIND_DANGER, remove_row)
        self.remove_button.set_dark(self._dark)
        self.remove_button.clicked.connect(lambda: self._ask("remove"))
        remove_row.set_control(self.remove_button)
        plain.add_row(remove_row)
        if self._confirm == "remove":
            self._confirm_row = ConfirmRow(
                m.remove_question(account), m.REMOVE_DETAIL, "Keep it",
                "Remove account", self._dark, plain)
            self._confirm_row.dismissed.connect(lambda: self._ask(None))
            self._confirm_row.confirmed.connect(self._remove_account)
            plain.add_row(self._confirm_row)
        stack.addWidget(plain)
        stack.addStretch(1)
        if label_focus:
            edit.setFocus(Qt.OtherFocusReason)

    def _open_login_form(self, mode: str) -> None:
        account = self._backend.account(self._account_id) if self._account_id else None
        if account is None:
            return
        old = self._login_form
        self._confirm = None
        form = LoginForm(mode, account.game, username=account.username,
                         keyring_available=self._backend.keyring_available(),
                         is_dark=self._dark, parent=self)
        form.cancelled.connect(self._close_login_form)
        form.submitted.connect(self._on_login_submitted)
        self._login_form = form
        if old is not None:
            old.deleteLater()
        self._build()
        form.focus_first()

    def _close_login_form(self) -> None:
        form = self._login_form
        self._login_form = None
        self._build()
        if form is not None:
            form.deleteLater()
        self._finish_launch_login(False)        # cancelled: the account stays idle

    def _on_login_submitted(self, username: str, password: str, keep: bool) -> None:
        if self._account_id is None:
            return
        form = self._login_form
        if form is not None and form.mode() == m.FORM_LAUNCH:
            ok = self._backend.launch_with_password(self._account_id, password, keep)
            self._login_form = None
            self.refresh()
            form.deleteLater()
            self._finish_launch_login(bool(ok))
            return
        if not self._backend.save_login(self._account_id, username, password, keep):
            if form is not None:
                form.error_label.setText("The login could not be saved.")
                form.error_label.show()
            return
        self._login_form = None
        self.refresh()
        if form is not None:
            form.deleteLater()

    def _ask(self, what: str | None) -> None:
        self._confirm = what
        self._build()

    def _forget_login(self) -> None:
        self._confirm = None
        account_id = self._account_id
        self._backend.forget_login(account_id)
        self.refresh()

    def _remove_account(self) -> None:
        self._confirm = None
        account_id = self._account_id
        self._account_id = None
        self._login_form = None
        self._backend.remove_account(account_id)
        self.refresh()

    def _commit_label(self) -> None:
        edit = self._label_edit
        if edit is None or self._account_id is None:
            return
        account = self._backend.account(self._account_id)
        text = edit.text().strip()
        if account is not None and text != account.label:
            self._backend.set_label(self._account_id, text)

    def _on_primary(self, toon_name: str) -> None:
        if self._account_id is not None:
            self._backend.set_primary(self._account_id, toon_name)

    def _on_edit_look(self, toon_name: str) -> None:
        if self._account_id is not None:
            self._backend.open_appearance(self._account_id, toon_name)

    def sizeHint(self) -> QSize:
        return self._layout.sizeHint()
