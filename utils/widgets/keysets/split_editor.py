"""SplitEditor — the master/detail keyset editor for ONE game.

A `SetListPanel` (left master column) plus a rich detail card (right) that
renders the selected movement set: a numbered badge + title + Detect/Delete,
a `VisualKeyboard`, a two-column field grid, and a conflict banner. Reads and
writes movement sets through `keymap_manager`.

Kit law: the detail card body/border and the number badge paint their gradient
in `paintEvent` (mirrors SetListItem's clipped-double-pen border); flat
fills/borders (field rows, banner, keycap field) use QSS on styled widgets.
NEVER attach a QGraphicsEffect to a widget that also custom-paints.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from utils import logical_actions
from utils.color_math import darken_rgb, with_alpha
from utils.widgets.pill_controls import PillButton
from . import keyboard_data
from .game_meta import GAME_META, set_accent
from .movement_key_field import MovementKeyField
from .set_list import SetListPanel
from .visual_keyboard import VisualKeyboard

_ROW_RADIUS = 13

# Fixed display labels for the field-grid rows. Unlisted actions Title-case.
_ROW_LABELS = {
    "forward": "Forward", "reverse": "Reverse", "left": "Left", "right": "Right",
    "jump": "Jump", "book": "Book", "gags": "Gags", "tasks": "Tasks",
    "map": "Map", "sprint": "Sprint", "action": "Perform Action",
}

_CONFLICT_TEXT = ("Some keys are assigned to more than one action - "
                  "highlighted in red.")
_HELPER_TEXT = ("These keys are what is sent to all game windows for input. "
                "Make sure they match your in-game settings.")


def _row_label(action: str) -> str:
    return _ROW_LABELS.get(action, action.replace("_", " ").title())


# ── number badge ────────────────────────────────────────────────────────────
class _NumberBadge(QWidget):
    """40px set-number badge: accent fill, 2px bright border, a 3px inset dark
    ring, centered number. Painted so the inset shadow reads (QSS can't)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._n, self._c, self._b = 1, "#0077ff", "#3399ff"

    def set_data(self, n: int, c: str, b: str) -> None:
        self._n, self._c, self._b = n, c, b
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, QColor(self._c))
        p.save()
        p.setClipPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(self._b), 4))
        p.drawPath(path)
        inset = QRectF(self.rect()).adjusted(3.5, 3.5, -3.5, -3.5)
        p.setPen(QPen(with_alpha("#000000", 0.28), 3))
        p.drawRoundedRect(inset, 9, 9)
        p.restore()
        p.setPen(QColor("#ffffff"))
        f = QFont()
        f.setPixelSize(15)
        f.setBold(True)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, str(self._n))
        p.end()


# ── detail card (painted gradient body + border) ─────────────────────────────
class _DetailCard(QWidget):
    """Rich-tint detail body: 158deg darken(c,0.30)->darken(c,0.15) gradient,
    2px alpha(b,0.55) border, radius 20 (mirrors SetListItem's technique)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._c, self._b = "#0077ff", "#3399ff"
        self.setAttribute(Qt.WA_StyledBackground, False)

    def set_accent(self, c: str, b: str) -> None:
        self._c, self._b = c, b
        self.update()

    def paintEvent(self, _e) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 20, 20)
        c = QColor(self._c)
        grad = QLinearGradient(r.topLeft(),
                               QPointF(r.x() + r.width() * 0.38, r.y() + r.height()))
        grad.setColorAt(0.0, darken_rgb(c, 0.30))
        grad.setColorAt(1.0, darken_rgb(c, 0.15))
        p.fillPath(path, grad)
        p.save()
        p.setClipPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(with_alpha(self._b, 0.55), 4))
        p.drawPath(path)
        p.restore()
        p.end()


# ── field row ────────────────────────────────────────────────────────────────
class FieldRow(QFrame):
    """One inset field row: a label + an embedded MovementKeyField keycap.
    Clicking the row BODY toggles the action's keyboard spotlight; clicking the
    field enters key-capture. Carries an active-background state InsetRow lacks."""

    def __init__(self, editor: "SplitEditor", action: str, label_text: str,
                 parent=None):
        super().__init__(parent)
        self._editor = editor
        self._action = action
        self._active = False
        self.setCursor(Qt.PointingHandCursor)

        h = QHBoxLayout(self)
        h.setContentsMargins(11, 7, 11, 7)
        h.setSpacing(12)
        self._label = QLabel(label_text)
        self._label.setStyleSheet(
            "background: transparent; border: none; color: #ffffff; "
            "font-size: 13px; font-weight: 600;")
        h.addWidget(self._label, 1)
        self._field = MovementKeyField(parent=self)
        self._field.key_captured.connect(
            lambda v, a=action: self._editor._apply_capture(a, v))
        h.addWidget(self._field, 0)

        self._apply_row_style()

    # ── input ────────────────────────────────────────────────────────────────
    def _emit_click(self) -> None:
        self._editor._toggle_spotlight(self._action)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self._emit_click()
        e.accept()

    # ── state ────────────────────────────────────────────────────────────────
    def set_active(self, active: bool) -> None:
        active = bool(active)
        if active == self._active:
            return
        self._active = active
        self._apply_row_style()

    def set_field(self, value: str, conflict: bool, mac: bool, locked: bool) -> None:
        self._field.set_key(value)
        self._field.set_locked(locked)
        self._style_field(conflict)

    def _apply_row_style(self) -> None:
        b = self._editor._accent_b
        if self._active:
            bg = with_alpha(b, 0.12).name(QColor.HexArgb)
            border = with_alpha(b, 0.5).name(QColor.HexArgb)
        else:
            bg, border = "rgba(0,0,0,0.24)", "rgba(0,0,0,0.30)"
        self.setStyleSheet(
            "FieldRow { background: %s; border: 1px solid %s; border-radius: %dpx; }"
            % (bg, border, _ROW_RADIUS))

    def _style_field(self, conflict: bool) -> None:
        if conflict:
            bg, border, txt = "rgba(224,82,82,0.16)", "#e05252", "#ff9a9a"
        else:
            bg, border, txt = "rgba(0,0,0,0.35)", "rgba(255,255,255,0.14)", "#ffffff"
        self._field.setStyleSheet(
            "QLineEdit { min-width: 72px; border-radius: 8px; padding: 0 9px; "
            "font-family: 'JetBrains Mono','Cascadia Mono',monospace; "
            "font-size: 11.5px; font-weight: 600; "
            "background: %s; border: 1px solid %s; color: %s; }" % (bg, border, txt))


# ── section label ────────────────────────────────────────────────────────────
def _section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    f = QFont()
    f.setPixelSize(10)
    f.setWeight(QFont.Bold)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 0.9)
    lbl.setFont(f)
    lbl.setStyleSheet(
        "background: transparent; border: none; color: rgba(255,255,255,0.5);")
    lbl.setContentsMargins(2, 0, 2, 6)
    return lbl


# ── the editor ───────────────────────────────────────────────────────────────
class SplitEditor(QWidget):
    """Master/detail movement-set editor for one game."""

    def __init__(self, keymap_manager, is_dark: bool = True, parent=None):
        super().__init__(parent)
        self._km = keymap_manager
        self._is_dark = is_dark
        self._mac = sys.platform == "darwin"
        self._game: str | None = None
        self._default_locked = False
        self._idx = 0
        self._active_action: str | None = None
        self._actions: list[str] = []
        self._accent_c, self._accent_b = set_accent(0)
        self._detect_cb = None
        self._rows: dict[str, FieldRow] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)

        # ── left master panel ──
        self._panel = SetListPanel(is_dark, self)
        self._panel.set_selected.connect(self._select)
        self._panel.add_requested.connect(self._on_add)
        outer.addWidget(self._panel, 0, Qt.AlignTop)

        # ── right detail card ──
        self._card = _DetailCard(self)
        outer.addWidget(self._card, 1)
        cv = QVBoxLayout(self._card)
        cv.setContentsMargins(20, 18, 20, 20)
        cv.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        self._badge = _NumberBadge(self._card)
        header.addWidget(self._badge, 0)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(7)
        self._title = QLabel("")
        self._title.setStyleSheet(
            "background: transparent; border: none; color: #ffffff; "
            "font-size: 16px; font-weight: 700;")
        title_row.addWidget(self._title, 0)
        self._pencil = QPushButton("✎")
        self._pencil.setCursor(Qt.PointingHandCursor)
        self._pencil.setFixedSize(20, 20)
        self._pencil.setStyleSheet(
            "QPushButton { background: transparent; border: none; "
            "color: rgba(255,255,255,0.55); font-size: 13px; }"
            "QPushButton:hover { color: #ffffff; }")
        self._pencil.clicked.connect(self._rename)
        title_row.addWidget(self._pencil, 0)
        title_row.addStretch(1)
        title_col.addLayout(title_row)
        self._sub = QLabel("")
        self._sub.setStyleSheet(
            "background: transparent; border: none; "
            "color: rgba(255,255,255,0.62); font-size: 11px;")
        title_col.addWidget(self._sub)
        header.addLayout(title_col, 1)

        self._detect_btn = PillButton("Detect")
        self._detect_btn.clicked.connect(self._on_detect)
        header.addWidget(self._detect_btn, 0)
        self._delete_btn = PillButton("Delete", tone="danger")
        self._delete_btn.clicked.connect(self._on_delete)
        header.addWidget(self._delete_btn, 0)
        cv.addLayout(header)
        cv.addSpacing(14)

        kb_row = QHBoxLayout()
        kb_row.setContentsMargins(0, 0, 0, 0)
        kb_row.addStretch(1)
        self._keyboard = VisualKeyboard(is_dark, self._card)
        kb_row.addWidget(self._keyboard, 0)
        kb_row.addStretch(1)
        cv.addLayout(kb_row)
        cv.addSpacing(16)

        grid = QHBoxLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(16)
        self._move_rows = self._make_column(grid, "Movement")
        self._act_rows = self._make_column(grid, "Actions")
        cv.addLayout(grid)
        cv.addSpacing(12)

        self._conflict_banner = QLabel(_CONFLICT_TEXT)
        self._conflict_banner.setWordWrap(True)
        self._conflict_banner.setStyleSheet(
            "background: rgba(224,82,82,0.14); border: 1px solid #e05252; "
            "border-radius: %dpx; color: #ff9a9a; font-size: 11.5px; "
            "padding: 8px 12px;" % _ROW_RADIUS)
        self._conflict_banner.setVisible(False)
        cv.addWidget(self._conflict_banner)

        self._helper = QLabel(_HELPER_TEXT)
        self._helper.setWordWrap(True)
        self._helper.setStyleSheet(
            "background: transparent; border: none; "
            "color: rgba(255,255,255,0.62); font-size: 11px;")
        self._helper.setVisible(False)
        cv.addWidget(self._helper)
        cv.addStretch(1)

        self.apply_theme(is_dark)

    def _make_column(self, grid: QHBoxLayout, title: str) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(_section_label(title))
        rows = QVBoxLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(6)
        col.addLayout(rows)
        col.addStretch(1)
        grid.addLayout(col, 1)
        return rows

    # ── public API ───────────────────────────────────────────────────────────
    def set_game(self, game: str, *, default_locked: bool) -> None:
        """Load the game's sets; reset selection to 0; clear spotlight."""
        self._game = game
        self._default_locked = bool(default_locked)
        self._idx = 0
        self._active_action = None
        self._actions = logical_actions.actions_for(game)
        self._detect_btn.setText(f"Detect {GAME_META[game].short}")
        self._build_rows()
        self._refresh_left()
        self._refresh_detail()

    def set_detect_callback(self, cb) -> None:
        self._detect_cb = cb

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self._panel.apply_theme(is_dark)
        self._keyboard.apply_theme(is_dark)
        self._detect_btn.apply_theme(is_dark)
        self._delete_btn.apply_theme(is_dark)

    # ── build ────────────────────────────────────────────────────────────────
    def _build_rows(self) -> None:
        for row in self._rows.values():
            row.setParent(None)
            row.deleteLater()
        self._rows = {}
        for layout in (self._move_rows, self._act_rows):
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget() if item is not None else None
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
        move = [a for a in self._actions if a in keyboard_data.MOVEMENT_ACTIONS]
        aux = [a for a in self._actions if a not in keyboard_data.MOVEMENT_ACTIONS]
        for action in move:
            row = FieldRow(self, action, _row_label(action), self._card)
            self._move_rows.addWidget(row)
            self._rows[action] = row
        for action in aux:
            row = FieldRow(self, action, _row_label(action), self._card)
            self._act_rows.addWidget(row)
            self._rows[action] = row

    # ── selection / mutation ───────────────────────────────────────────────
    def _select(self, i: int) -> None:
        n = self._km.num_sets(self._game)
        if n == 0:
            return
        self._idx = max(0, min(int(i), n - 1))
        self._active_action = None
        self._refresh_left()
        self._refresh_detail()

    def _on_add(self) -> None:
        if self._km.num_sets(self._game) >= self._km.MAX_SETS_PER_GAME:
            return
        self._km.add_set(self._game)
        self._refresh_left()
        self._select(self._km.num_sets(self._game) - 1)

    def _on_delete(self) -> None:
        if self._idx <= 0:
            return
        self._km.delete_set(self._game, self._idx)
        self._active_action = None
        self._idx = max(0, min(self._idx, self._km.num_sets(self._game) - 1))
        self._refresh_left()
        self._refresh_detail()

    def _on_detect(self) -> None:
        if self._detect_cb is not None:
            self._detect_cb(self._game)
        self._refresh_detail()

    def _rename(self) -> None:
        if self._game is None or self._idx <= 0:
            return
        names = self._km.get_set_names(self._game)
        current = names[self._idx] if self._idx < len(names) else ""
        name, ok = QInputDialog.getText(
            self, "Rename set", "Set name:", text=current)
        if ok and name.strip():
            self._km.update_set_name(self._game, self._idx, name.strip())
            self._refresh_left()
            self._refresh_detail()

    def _apply_capture(self, action: str, value: str) -> None:
        """The path MovementKeyField.key_captured drives: persist, then reload
        + refresh keyboard/rows/conflict banner."""
        self._km.update_set_key(self._game, self._idx, action, value)
        self._refresh_detail()

    def _toggle_spotlight(self, action: str) -> None:
        self._active_action = None if self._active_action == action else action
        self._refresh_detail()

    # ── refresh ──────────────────────────────────────────────────────────────
    def _refresh_left(self) -> None:
        game = self._game
        self._panel.set_data(
            game_short=GAME_META[game].short,
            game_accent=GAME_META[game].accent_b,
            sets=self._km.get_sets(game),
            set_names=self._km.get_set_names(game),
            selected_index=self._idx)

    def _refresh_detail(self) -> None:
        game, idx = self._game, self._idx
        set_dict = self._km.get_set(game, idx) or {}
        c, b = set_accent(idx)
        self._accent_c, self._accent_b = c, b
        self._card.set_accent(c, b)
        self._badge.set_data(idx + 1, c, b)

        names = self._km.get_set_names(game)
        name = names[idx] if idx < len(names) else f"Set {idx + 1}"
        self._title.setText(name)
        self._sub.setText(f"{GAME_META[game].title} · movement set {idx + 1}")
        self._pencil.setVisible(idx > 0)
        self._detect_btn.setVisible(idx == 0)
        self._delete_btn.setVisible(idx > 0)

        actions = self._actions
        assign = keyboard_data.assignment_map(set_dict, actions)
        conflict_vals = keyboard_data.conflict_values(set_dict, actions)
        self._keyboard.set_state(
            assign=assign, conflict_vals=conflict_vals, accent_c=c, accent_b=b,
            active_code=set_dict.get(self._active_action), mac=self._mac)

        locked = self._default_locked and idx == 0
        for action, row in self._rows.items():
            value = set_dict.get(action, "")
            row.set_field(value, value in conflict_vals, self._mac, locked)
            row.set_active(action == self._active_action)

        has, _ = self._km.has_conflicts(game, idx)
        self._conflict_banner.setVisible(has)
        self._helper.setVisible((not has) and idx == 0)
