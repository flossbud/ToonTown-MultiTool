"""Account settings body (spec §2, handoff §4.4): live preview | fields.

The preview is the real RosterCard at native size, mouse-transparent and
rebuilt from the draft, so a label edit is judged where it will be seen.
Nothing here writes: the sheet edits an AccountDraft and emits intents; the
view validates and LaunchTab performs the write.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QToolButton, QVBoxLayout, QWidget,
)

from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.draft import MODE_ADD, AccountDraft, shown_record
from utils.widgets.grandstand.model import RosterEntry, roster_entry
from utils.widgets.grandstand.roster_card import RosterCard

# Focus-mode measurements (handoff §4.4).
PREVIEW_COL_W = 184
COL_GAP = 26
GRID_ROW_GAP = 10
GRID_COL_GAP = 16
INPUT_H = 38
INPUT_RADIUS = 6
EYE_SIZE = 22
FROW_H = 64
FROW_RADIUS = 9
FROW_PORTRAIT = 44
LINKBTN_H = 26

GAME_NAMES = {"ttr": "Toontown Rewritten", "cc": "Corporate Clash"}

# Copy, verbatim from handoff §4.4 / §4.5 unless noted.
CAPTION = "Live preview · launcher card"
LABEL_FIELD = "Label (optional)"
LABEL_PLACEHOLDER = "e.g. Gag grind alt"
USERNAME_FIELD = "Username"
PASSWORD_FIELD = "Password"
FROW_FIELD = "Toon this account shows"
DANGER_FIELD = "Danger zone"
CHOOSE_TOON = "Choose toon"
CROSS_LINK = "✏ Customize appearance"
FROW_NO_TOON = "No toon yet"                  # model.footer_text's toonless copy
FROW_SUB_NONE = "play once to discover"
KEYRING_UNREADABLE = "Stored password can't be read right now"   # spec §4
ADD_TITLE = "Add account"                     # spec is silent on add-mode copy
TRASH_GLYPH = "🗑"
EYE_GLYPH = "👁"


def title_for(draft: AccountDraft) -> str:
    if draft.mode == MODE_ADD:
        return ADD_TITLE
    return f"Account · {draft.display_name}"


def subtitle_for(draft: AccountDraft) -> str:
    """An unknown game code falls back to the code itself, upper-cased: a
    header line is not worth a KeyError."""
    game = GAME_NAMES.get(draft.game) or (draft.game or "").upper()
    return f"{game} · changes apply to this account only"


def note_for(count: int) -> str:
    """Footer note on the account surface (handoff §4.4)."""
    if count == 0:
        return "No toons discovered yet"
    if count == 1:
        return "1 toon discovered"
    return f"{count} toons discovered"


def frow_sub_for(count: int) -> str:
    return f"{count} discovered" if count else FROW_SUB_NONE


def remove_label_for(draft: AccountDraft) -> str:
    return f"Remove {draft.display_name} from the launcher"


def _transparent(widget: QWidget, name: str) -> None:
    """Containers are styled-background widgets under the app's global
    `QWidget { background-color }` rule; each must opt out or it paints a
    square of page colour over the sheet surface."""
    widget.setObjectName(name)
    widget.setStyleSheet(f"#{name} {{ background: transparent; }}")


class _PasswordEdit(QLineEdit):
    """Masked input with the 22 px eye toggle inset right (handoff §4.4)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEchoMode(QLineEdit.Password)
        self.eye = QToolButton(self)
        self.eye.setObjectName("gs_eye")
        self.eye.setFixedSize(EYE_SIZE, EYE_SIZE)
        self.eye.setCursor(Qt.PointingHandCursor)
        self.eye.setFocusPolicy(Qt.TabFocus)
        self.eye.setCheckable(True)
        self.eye.setText(EYE_GLYPH)
        self.eye.setToolTip("Show password")
        self.eye.toggled.connect(self._on_toggled)
        self.setTextMargins(0, 0, EYE_SIZE + 8, 0)

    def _on_toggled(self, revealed: bool) -> None:
        self.setEchoMode(QLineEdit.Normal if revealed else QLineEdit.Password)
        self.eye.setToolTip("Hide password" if revealed else "Show password")

    def set_revealed(self, value: bool) -> None:
        self.eye.setChecked(bool(value))

    def is_revealed(self) -> bool:
        return self.echoMode() == QLineEdit.Normal

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.eye.move(self.width() - EYE_SIZE - 8, (self.height() - EYE_SIZE) // 2)


class AccountSheet(QWidget):
    changed = Signal()
    choose_toon_requested = Signal()
    remove_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _transparent(self, "gs_account_sheet")
        self._is_dark = True
        self._draft: Optional[AccountDraft] = None
        self._toons: list = []
        self._primary: Optional[str] = None
        self._base: Optional[RosterEntry] = None
        self._section_labels: list[QLabel] = []
        self._errors: dict[str, str] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(COL_GAP)
        outer.addLayout(row)
        outer.addStretch(1)

        # ── preview column (handoff §4.4: 184 px in focus mode) ────────────
        self.preview_column = QWidget(self)
        _transparent(self.preview_column, "gs_preview_col")
        self.preview_column.setFixedWidth(PREVIEW_COL_W)
        col = QVBoxLayout(self.preview_column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        self.preview = RosterCard(self.preview_column)
        # The card is a picture here: no clicks, no hover reveal, never in
        # the tab chain — on the card and on every chip it owns.
        self.preview.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        for chip in (self.preview, self.preview.ribbon, self.preview.star,
                     self.preview.pencil, self.preview.gear, self.preview.action):
            chip.setFocusPolicy(Qt.NoFocus)
        col.addWidget(self.preview, 0, Qt.AlignHCenter)
        self.caption = QLabel(CAPTION.upper(), self.preview_column)
        self.caption.setWordWrap(True)
        self.caption.setAlignment(Qt.AlignHCenter)
        col.addWidget(self.caption)
        row.addWidget(self.preview_column, 0, Qt.AlignTop)

        # ── fields grid (2 columns, gap 10 16, align-content start) ────────
        self.fields = QWidget(self)
        _transparent(self.fields, "gs_fields")
        grid = QGridLayout(self.fields)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(GRID_COL_GAP)
        grid.setVerticalSpacing(GRID_ROW_GAP)

        self.label_field, self.label_input, _ = self._field(
            "gs_field_label", LABEL_FIELD, with_error=False)
        self.label_input.setPlaceholderText(LABEL_PLACEHOLDER)
        self.username_field, self.username_input, self.username_error = self._field(
            "gs_field_username", USERNAME_FIELD)
        self.password_field, self.password_input, self.password_error = self._field(
            "gs_field_password", PASSWORD_FIELD, password=True)
        self.password_helper = QLabel(self.password_field)
        self.password_helper.setVisible(False)
        self.password_field.layout().addWidget(self.password_helper)

        self.frow_field = QWidget(self.fields)
        _transparent(self.frow_field, "gs_field_frow")
        frow_col = QVBoxLayout(self.frow_field)
        frow_col.setContentsMargins(0, 0, 0, 0)
        frow_col.setSpacing(4)
        frow_col.addWidget(self._section_label(FROW_FIELD, self.frow_field))
        self.frow = QFrame(self.frow_field)
        self.frow.setObjectName("gs_frow")
        self.frow.setFixedHeight(FROW_H)
        frow_row = QHBoxLayout(self.frow)
        frow_row.setContentsMargins(10, 0, 10, 0)
        frow_row.setSpacing(10)
        # Task 5 inserts the 44 px portrait at index 0 of this row.
        names = QVBoxLayout()
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(1)
        self.frow_name = QLabel(self.frow)
        self.frow_sub = QLabel(self.frow)
        names.addWidget(self.frow_name)
        names.addWidget(self.frow_sub)
        frow_row.addLayout(names, 1)
        self.choose_button = QPushButton(CHOOSE_TOON, self.frow)
        self.choose_button.setFixedHeight(LINKBTN_H)
        self.choose_button.setCursor(Qt.PointingHandCursor)
        self.choose_button.setFocusPolicy(Qt.StrongFocus)
        self.choose_button.clicked.connect(self.choose_toon_requested.emit)
        frow_row.addWidget(self.choose_button, 0, Qt.AlignVCenter)
        frow_col.addWidget(self.frow)

        self.danger_field = QWidget(self.fields)
        _transparent(self.danger_field, "gs_field_danger")
        danger_col = QVBoxLayout(self.danger_field)
        danger_col.setContentsMargins(0, 0, 0, 0)
        danger_col.setSpacing(4)
        danger_col.addWidget(self._section_label(DANGER_FIELD, self.danger_field))
        self.remove_button = QPushButton(self.danger_field)
        self.remove_button.setFixedHeight(LINKBTN_H)
        self.remove_button.setCursor(Qt.PointingHandCursor)
        self.remove_button.setFocusPolicy(Qt.StrongFocus)
        self.remove_button.clicked.connect(self.remove_requested.emit)
        danger_col.addWidget(self.remove_button)

        grid.addWidget(self.label_field, 0, 0)
        grid.addWidget(self.username_field, 0, 1)
        grid.addWidget(self.password_field, 1, 0)
        grid.addWidget(self.frow_field, 1, 1)
        grid.addWidget(self.danger_field, 2, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(3, 1)
        row.addWidget(self.fields, 1, Qt.AlignTop)

        # Bound methods, not lambdas: a lambda has no receiver QObject, so
        # Qt can't auto-disconnect it on teardown and the closure holds a
        # strong ref to self.
        self.label_input.textChanged.connect(self._on_label_edited)
        self.username_input.textChanged.connect(self._on_username_edited)
        self.password_input.textChanged.connect(self._on_password_edited)

        self.apply_theme(True)

    # ── construction helpers ───────────────────────────────────────────────

    def _section_label(self, caption: str, parent: QWidget) -> QLabel:
        label = QLabel(caption.upper(), parent)
        self._section_labels.append(label)
        return label

    def _field(self, name: str, caption: str, *, password: bool = False,
               with_error: bool = True):
        block = QWidget(self.fields)
        _transparent(block, name)
        col = QVBoxLayout(block)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        col.addWidget(self._section_label(caption, block))
        edit = _PasswordEdit(block) if password else QLineEdit(block)
        edit.setObjectName(f"{name}_input")
        edit.setFixedHeight(INPUT_H)
        col.addWidget(edit)
        error = None
        if with_error:
            error = QLabel(block)
            error.setVisible(False)
            col.addWidget(error)
        return block, edit, error

    # ── inbound ────────────────────────────────────────────────────────────

    def open(self, draft: AccountDraft, toons: list, primary_name,
             base_entry: Optional[RosterEntry] = None) -> None:
        """Seed the fields from `draft` and the toon row from the account's
        records. `base_entry` is the roster's current entry for the account
        (None in add mode): the preview inherits its live state and accent."""
        self._draft = draft
        self._base = base_entry
        for edit, value in ((self.label_input, draft.label),
                            (self.username_input, draft.username),
                            (self.password_input, draft.password)):
            edit.blockSignals(True)
            edit.setText(value)
            edit.blockSignals(False)
        self.password_input.set_revealed(False)
        self.password_helper.setText("" if draft.keyring_readable else KEYRING_UNREADABLE)
        self.password_helper.setVisible(not draft.keyring_readable)
        add = draft.mode == MODE_ADD
        self.danger_field.setVisible(not add)
        self.remove_button.setText(f"{TRASH_GLYPH}  {remove_label_for(draft)}")
        self.choose_button.setEnabled(not add)
        self._errors = {}
        self._render_errors()
        self.set_toons(toons, primary_name)

    def clear(self) -> None:
        self._draft = None
        self._base = None
        self._toons = []
        self._primary = None
        self._errors = {}
        for edit in (self.label_input, self.username_input, self.password_input):
            edit.blockSignals(True)
            edit.clear()
            edit.blockSignals(False)
        self._render_errors()

    def is_open(self) -> bool:
        return self._draft is not None

    def account_id(self) -> str:
        return self._draft.id if self._draft is not None else ""

    def draft(self) -> Optional[AccountDraft]:
        return self._draft

    def set_toons(self, toons: list, primary_name) -> None:
        """The account's records, newest first (Task 5 adds the rename
        merge and the portrait)."""
        self._toons = list(toons)
        self._primary = primary_name
        rec = self.primary_record()
        self.frow_name.setText(rec.toon_name if rec is not None else FROW_NO_TOON)
        self.frow_sub.setText(frow_sub_for(len(self._toons)))
        self._rebuild_preview()

    def primary_record(self):
        return shown_record(self._toons, self._primary)

    def toon_count(self) -> int:
        return len(self._toons)

    def set_base_entry(self, entry: Optional[RosterEntry]) -> None:
        self._base = entry
        self._rebuild_preview()

    def set_account_state(self, state: str, message: str = "", raw: str = "") -> None:
        """Launch state keeps flowing while the sheet is open (spec §4); the
        base entry carries it too so a later edit's rebuild keeps it."""
        if self._base is not None:
            self._base = dataclasses.replace(
                self._base, state=state, message=message or "", raw_error=raw or "")
        self.preview.set_state(state, message, raw)

    # ── validation feedback (spec §4) ────────────────────────────────────────

    def show_errors(self, errors: dict) -> None:
        """Field -> message from AccountDraft.validate(). Invalid border and
        10 px / 600 message in the error red (handoff §4.4)."""
        self._errors = dict(errors)
        self._render_errors()

    def clear_errors(self) -> None:
        self._errors = {}
        self._render_errors()

    def errors(self) -> dict:
        return dict(self._errors)

    def _render_errors(self) -> None:
        for key, edit, label in (("username", self.username_input, self.username_error),
                                 ("password", self.password_input, self.password_error)):
            message = self._errors.get(key, "")
            label.setText(message)
            label.setVisible(bool(message))
            self._restyle_input(edit, invalid=bool(message))
        self._restyle_input(self.label_input, invalid=False)

    # ── readouts (test surface) ────────────────────────────────────────────

    def preview_entry(self):
        return self.preview.entry()

    def frow_name_text(self) -> str:
        return self.frow_name.text()

    def frow_sub_text(self) -> str:
        return self.frow_sub.text()

    def section_labels(self) -> list[QLabel]:
        return list(self._section_labels)

    def tab_chain(self) -> list[QWidget]:
        """Visual order (spec §4); the shell appends Cancel and Save."""
        return [self.label_input, self.username_input, self.password_input,
                self.password_input.eye, self.choose_button, self.remove_button]

    def focus_first(self) -> None:
        self.label_input.setFocus()

    # ── draft ──────────────────────────────────────────────────────────────

    def _on_label_edited(self, _text: str) -> None:
        self._on_field_changed("label")

    def _on_username_edited(self, _text: str) -> None:
        self._on_field_changed("username")

    def _on_password_edited(self, _text: str) -> None:
        self._on_field_changed("password")

    def _on_field_changed(self, key: str) -> None:
        d = self._draft
        if d is None:
            return
        d.label = self.label_input.text()
        d.username = self.username_input.text()
        d.password = self.password_input.text()
        # An edit clears that field's own error (AccountEditor's semantics);
        # the next Save re-validates the whole draft.
        if key in self._errors:
            del self._errors[key]
            self._render_errors()
        self._rebuild_preview()
        self.changed.emit()

    def _rebuild_preview(self) -> None:
        """The card re-reads text only (spec §3): colour and framing edits
        live in sub-project B, so the accent is the roster's resolved one."""
        d = self._draft
        if d is None:
            return
        rec = self.primary_record()
        base = self._base
        entry = roster_entry(
            account_id=d.id, game=d.game, label=d.label, username=d.username,
            rec=rec, entry={"accent": base.accent} if base is not None else {},
            state=base.state if base is not None else "idle",
            message=base.message if base is not None else "",
            raw_error=base.raw_error if base is not None else "",
            is_primary=(rec is not None and rec.toon_name == self._primary))
        self.preview.set_entry(entry)

    # ── theme ──────────────────────────────────────────────────────────────

    def _restyle_input(self, edit: QLineEdit, invalid: bool) -> None:
        d = gp.sheet_input(invalid, self._is_dark)
        focus = "" if invalid else (
            f" QLineEdit:focus {{ border: 1px solid {d['focus_border'].name()}; }}")
        edit.setStyleSheet(
            "QLineEdit {"
            f" background: {d['bg'].name(QColor.HexArgb)};"
            f" border: 1px solid {d['border'].name(QColor.HexArgb)};"
            f" border-radius: {INPUT_RADIUS}px; padding: 0 10px;"
            f" color: {d['ink'].name()}; font-size: 13px; }}" + focus)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        ink = gp.sheet_ink(is_dark)
        for label in self._section_labels:
            label.setStyleSheet(
                f"color: {ink['label'].name()}; font-size: 10px; font-weight: 800;"
                " letter-spacing: 0.8px; background: transparent;")
        self.caption.setStyleSheet(
            f"color: {ink['caption'].name()}; font-size: 9px; font-weight: 800;"
            " letter-spacing: 0.8px; background: transparent;")
        error_ink = gp.sheet_input(True, is_dark)["error"].name()
        for label in (self.username_error, self.password_error):
            label.setStyleSheet(
                f"color: {error_ink}; font-size: 10px; font-weight: 600;"
                " background: transparent;")
        self.password_helper.setStyleSheet(
            f"color: {ink['sub'].name()}; font-size: 10px; background: transparent;")
        self._render_errors()               # restyles every input, errors kept
        eye_rest = gp.sheet_ink(is_dark)["sub"].name()
        eye_on = gp.sheet_input(False, is_dark)["focus_border"].name()
        self.password_input.eye.setStyleSheet(
            "QToolButton { background: transparent; border: none;"
            f" color: {eye_rest}; font-size: 13px; }}"
            f" QToolButton:checked {{ color: {eye_on}; }}")
        f = gp.frow(is_dark)
        self.frow.setStyleSheet(
            f"QFrame#gs_frow {{ background: {f['bg'].name()};"
            f" border: 1px solid {f['border'].name()};"
            f" border-radius: {FROW_RADIUS}px; }}")
        self.frow_name.setStyleSheet(
            f"color: {f['name'].name()}; font-size: 13px; font-weight: 700;"
            " background: transparent;")
        self.frow_sub.setStyleSheet(
            f"color: {f['sub'].name()}; font-size: 11px; background: transparent;")
        lb = gp.link_button(is_dark)
        self.choose_button.setStyleSheet(
            "QPushButton {"
            f" background: {lb['bg'].name(QColor.HexArgb)};"
            f" border: 1px solid {lb['border'].name()}; border-radius: 8px;"
            f" padding: 0 11px; color: {lb['ink'].name()};"
            " font-size: 11px; font-weight: 600; }")
        rest = gp.danger_button(False, is_dark)
        hover = gp.danger_button(True, is_dark)
        self.remove_button.setStyleSheet(
            "QPushButton {"
            f" background: {rest['bg'].name(QColor.HexArgb)};"
            f" border: 1px solid {rest['border'].name(QColor.HexArgb)};"
            f" border-radius: 8px; padding: 0 11px; color: {rest['ink'].name()};"
            " font-size: 11px; font-weight: 600; text-align: left; }"
            " QPushButton:hover {"
            f" background: {hover['bg'].name(QColor.HexArgb)};"
            f" border: 1px solid {hover['border'].name()};"
            f" color: {hover['ink'].name()}; }}")
        self.preview.apply_theme(is_dark)
