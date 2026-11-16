"""Keysets sheet (launchpad handoff section 6), content for SlideSheetHost.

One gold group card per game view (TTR | CC pill in its header), a count
line, one row per keyset, "+ New keyset" and a footer hint. Built on
KeymapManager's set ids, hidden flag and move_set:

- Row: drag grip, the strip's number block (lit when shown on strips, unlit
  when hidden), five keycaps (Forward, Left, Reverse, Right, Jump), and
  Edit / Hide-Show / Delete buttons. No toon names.
- Edit expands a two-column list of every action of the game
  (logical_actions.actions_for); click a keycap and press a key to rebind
  (the existing MovementKeyField capture).
- Keyset 1 is the base set the input engine translates from: it has no grip
  and cannot be deleted, but it can be hidden. Its keys are locked while a
  game config file drives them (the same rule as the Settings Keysets page).
  Keysets 2-8 drag to renumber (move_set). No delete confirm.
- Conflicts: keys bound to two actions in one set are red, with the
  Settings page's banner in the open editor; a key that means different
  actions in two sets is outlined amber and listed in the editor.

The sheet keeps open rows by set id, so they stay open across renumbering.
"""
from __future__ import annotations

import weakref
from typing import Callable

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from utils import logical_actions
from utils.color_math import alpha
from utils.icon_factory import (
    make_dpad_icon, make_edit_icon, make_eye_icon, make_grip_icon, make_trash_icon,
)
from utils.strips import tokens as strip_tokens
from utils.strips.paint import paint_number_block
from utils.theme_manager import get_theme_colors, is_dark_palette
from utils.widgets.keysets.game_meta import GAME_META
from utils.widgets.keysets.movement_key_field import DISPLAY_NAMES, MovementKeyField
from utils.widgets.keysets.palette import conflict_banner_css, field_value
from utils.widgets.keysets.rules import CONFLICT_TEXT as _CONFLICT_TEXT
from utils.widgets.keysets import detect
from utils.widgets.launchpad.material import (
    AddRow, GroupCard, IconButton, ROW_MIN_H, ROW_RADIUS, SecondaryButton,
    SheetSegmented, footer_label, note_label, qcolor, sheet_palette, sheet_stack,
)

IDENTITY = "#DAA520"
TITLE = "Keysets"
SUB = "Numbered movement-key layouts. Each toon picks one from its strip."
FOOTER = ("Bindings can also be changed from any strip: right-click a keyset "
          "number, then Edit keyset.")
ROW_CAPS = ("forward", "left", "reverse", "right", "jump")
NUMBER = 28
GAMES = ("ttr", "cc")
MONO_QSS = '"JetBrains Mono", Consolas, Menlo, "DejaVu Sans Mono", monospace'
WARN_DARK, WARN_LIGHT = "#ffcc99", "#b45309"

_SHORT = {
    "Up": "↑", "Down": "↓", "Left": "←", "Right": "→",
    "space": "Space", "Escape": "Esc", "Delete": "Del", "Return": "Enter",
    "Control_L": "Ctrl", "Control_R": "R Ctrl", "Shift_L": "Shift",
    "Shift_R": "R Shift", "Alt_L": "Alt", "Alt_R": "R Alt", "BackSpace": "Bksp",
    "Prior": "PgUp", "Next": "PgDn",
}


def cap_text(key: str | None) -> str:
    """Short keycap label for a stored key name."""
    if not key:
        return "–"
    if key in _SHORT:
        return _SHORT[key]
    if len(key) == 1:
        return key.upper()
    return DISPLAY_NAMES.get(key, key)


def _action_label(action: str) -> str:
    return logical_actions.ACTION_LABELS.get(action, action.replace("_", " ").title())


def _cap_colors(is_dark: bool, conflict: bool = False, warn: bool = False,
                dim: bool = False) -> tuple[str, str, str]:
    """(fill, border, ink) for a keycap."""
    if conflict:
        bg, border, ink = field_value(True, is_dark)
    elif is_dark:
        bg, border, ink = "#2e2e2e", "#444444", "#ffffff"
    else:
        c = get_theme_colors(False)
        bg, border, ink = c["bg_card_inner"], c["border_light"], c["text_primary"]
    if warn and not conflict:
        border = WARN_DARK if is_dark else WARN_LIGHT
    bg, border, ink = (_qss(bg), _qss(border), _qss(ink))
    if dim:
        bg, border, ink = (_half(bg), _half(border), _half(ink))
    return bg, border, ink


def _to_qcolor(css: str) -> QColor:
    """'#rrggbb' or 'rgba(r, g, b, a)' with a either 0-255 (this codebase)
    or a 0-1 fraction (the keysets palette)."""
    if not css.startswith("rgba"):
        return QColor(css)
    r, g, b, a = (x.strip() for x in css[css.index("(") + 1:css.rindex(")")].split(","))
    col = QColor(int(float(r)), int(float(g)), int(float(b)))
    af = float(a)
    col.setAlphaF(af if ("." in a and af <= 1.0) else af / 255.0)
    return col


def _qss(css: str) -> str:
    """One colour form for stylesheets: rgba with 0-255 alpha."""
    col = _to_qcolor(css)
    return f"rgba({col.red()}, {col.green()}, {col.blue()}, {col.alpha()})"


def _half(css: str) -> str:
    col = _to_qcolor(css)
    return alpha(col, col.alphaF() * 0.5)


def _cap_qss(selector: str, is_dark: bool, conflict=False, warn=False, dim=False,
             awaiting_accent: str | None = None) -> str:
    bg, border, ink = _cap_colors(is_dark, conflict, warn, dim)
    qss = (f"{selector} {{ font-family: {MONO_QSS}; font-size: 10px; font-weight: 600;"
           f" background: {bg}; border: 1px solid {border}; border-radius: 4px;"
           f" color: {ink}; padding: 0 5px; }}")
    if awaiting_accent:
        qss += (f'{selector}[awaiting="true"] {{ border: 1px solid {awaiting_accent};'
                f" background: {alpha(awaiting_accent, 0.22)}; }}")
    return qss


class Keycap(QLabel):
    """A static keycap: mono 10/600, h 20, min-w 22, radius 4."""

    def __init__(self, key: str | None, parent=None):
        super().__init__(cap_text(key), parent)
        self.key = key
        self.setObjectName("keycap")
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(20)
        self.setMinimumWidth(22)

    def apply_style(self, is_dark: bool, conflict=False, warn=False, dim=False) -> None:
        self.setStyleSheet(_cap_qss("QLabel#keycap", is_dark, conflict, warn, dim))


class EditKeycap(MovementKeyField):
    """MovementKeyField drawn as a keycap; click, then press a key."""

    def __init__(self, key: str, parent=None):
        super().__init__(key, parent)
        self.setObjectName("edit_keycap")
        self.setMinimumHeight(20)
        self.setFixedHeight(20)
        self._fit_width()

    def _fit_width(self) -> None:
        # Sized to its label like a keycap, not like an input field.
        from PySide6.QtGui import QFont, QFontMetrics
        f = QFont()
        f.setFamilies(list(strip_tokens.MONO_FAMILIES))
        f.setPixelSize(10)
        f.setWeight(QFont.DemiBold)
        self.setFixedWidth(max(30, QFontMetrics(f).horizontalAdvance(self.text()) + 16))

    def _update_display(self):
        self.setText("Press a key…" if self._awaiting else cap_text(self._key))
        self.setProperty("awaiting", self._awaiting)
        from utils.shared_widgets import repolish
        repolish(self)
        if self.objectName() == "edit_keycap":     # not during the base __init__
            self._fit_width()

    def apply_style(self, is_dark: bool, accent: str, conflict=False, warn=False) -> None:
        self.setStyleSheet(_cap_qss("QLineEdit#edit_keycap", is_dark, conflict, warn,
                                    awaiting_accent=accent))


class _Grip(QWidget):
    """Six-dot handle; reports a drag in global coordinates."""

    pressed = Signal(QPoint)
    moved = Signal(QPoint)
    released = Signal(QPoint)

    def __init__(self, enabled: bool, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, NUMBER)
        self._enabled = enabled
        self._icon = None
        if enabled:
            self.setCursor(Qt.OpenHandCursor)
            self.setToolTip("Drag to renumber")
        else:
            self.setToolTip("Keyset 1 is the base set: it stays first")

    def set_color(self, color: QColor) -> None:
        self._icon = make_grip_icon(14, color) if self._enabled else None
        self.update()

    def paintEvent(self, _e):
        if self._icon is None:
            return
        p = QPainter(self)
        self._icon.paint(p, 0, (self.height() - 14) // 2, 14, 14)
        p.end()

    def mousePressEvent(self, e):
        if self._enabled and e.button() == Qt.LeftButton:
            self.setCursor(Qt.ClosedHandCursor)
            self.pressed.emit(e.globalPosition().toPoint())
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._enabled and e.buttons() & Qt.LeftButton:
            self.moved.emit(e.globalPosition().toPoint())
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._enabled and e.button() == Qt.LeftButton:
            self.setCursor(Qt.OpenHandCursor)
            self.released.emit(e.globalPosition().toPoint())
            e.accept()
            return
        super().mouseReleaseEvent(e)


class _RowFrame(QFrame):
    """The inset row; paints the strip's number block into its slot."""

    def __init__(self, number: int, lit: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("ks_row")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.number = number
        self.lit = lit
        self.slot = QWidget(self)
        self.slot.setFixedSize(NUMBER, NUMBER)
        self.slot.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def number_rect(self) -> QRectF:
        return QRectF(self.slot.geometry())

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        paint_number_block(p, self.number_rect(), self.number, self.lit,
                           look=strip_tokens.NEON, glow=self.lit)
        p.end()


class KeysetRow(QWidget):
    """One keyset: the inset row, plus the binding editor when open."""

    edit_clicked = Signal(str)
    hide_clicked = Signal(str)
    delete_clicked = Signal(str)
    detect_clicked = Signal(str)
    key_captured = Signal(str, str, str)       # set id, action, key

    def __init__(self, *, set_id: str, number: int, game: str, keys: dict,
                 hidden: bool, can_hide: bool, can_delete: bool, can_drag: bool,
                 expanded: bool, locked: bool, conflicts: set, warn_values: set,
                 cross_notes: list, is_dark: bool, can_detect: bool = False,
                 detect_note: str = "", parent=None):
        super().__init__(parent)
        self.set_id = set_id
        self.number = number
        self.game = game
        self.hidden = hidden
        self.expanded = expanded
        self.locked = locked
        self.can_detect = can_detect
        self._detect_note = detect_note
        self._keys = dict(keys)
        self._conflicts = set(conflicts)
        self._warn = set(warn_values)
        self._is_dark = is_dark
        self.setAttribute(Qt.WA_StyledBackground, False)

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self.frame = _RowFrame(number, not hidden, self)
        self.frame.setMinimumHeight(ROW_MIN_H)
        row = QHBoxLayout(self.frame)
        row.setContentsMargins(12, 7, 12, 7)
        row.setSpacing(11)
        self.grip = _Grip(can_drag, self.frame)
        row.addWidget(self.grip)
        row.addWidget(self.frame.slot)
        caps = QHBoxLayout()
        caps.setSpacing(3)
        self.caps = []
        for action in ROW_CAPS:
            cap = Keycap(keys.get(action), self.frame)
            cap.setToolTip(_action_label(action))
            self.caps.append(cap)
            caps.addWidget(cap)
        row.addLayout(caps)
        self.status = QLabel("Hidden from strips" if hidden else "", self.frame)
        self.status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(self.status, 1)
        grey = QColor("#bbbbbb")
        self.edit_btn = IconButton(make_edit_icon(14, grey), "Edit bindings",
                                   is_dark=is_dark, parent=self.frame)
        self.hide_btn = IconButton(make_eye_icon(14, grey, crossed=hidden),
                                   "Show on strips" if hidden else "Hide from strips",
                                   is_dark=is_dark, parent=self.frame)
        self.delete_btn = IconButton(make_trash_icon(14, grey), "Delete keyset",
                                     danger=True, is_dark=is_dark, parent=self.frame)
        self.hide_btn.setEnabled(can_hide)
        self.delete_btn.setEnabled(can_delete)
        if not can_delete:
            self.delete_btn.setToolTip("Keyset 1 is the base set and can't be deleted")
        if not can_hide and not hidden:
            self.hide_btn.setToolTip("At least one keyset stays on the strips")
        for b in (self.edit_btn, self.hide_btn, self.delete_btn):
            row.addWidget(b)
        self.edit_btn.set_on(expanded)
        self.edit_btn.clicked.connect(lambda: self.edit_clicked.emit(self.set_id))
        self.hide_btn.clicked.connect(lambda: self.hide_clicked.emit(self.set_id))
        self.delete_btn.clicked.connect(lambda: self.delete_clicked.emit(self.set_id))
        col.addWidget(self.frame)

        self.editor = None
        self.edit_caps: dict = {}
        if expanded:
            self.editor = self._build_editor(cross_notes)
            col.addWidget(self.editor)
        self.apply_theme(is_dark)

    def _build_editor(self, cross_notes: list) -> QFrame:
        ed = QFrame(self)
        ed.setObjectName("ks_edit")
        ed.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(ed)
        outer.setContentsMargins(64, 8, 14, 10)
        outer.setSpacing(6)
        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(2)
        self._edit_labels = []
        actions = logical_actions.actions_for(self.game)
        for i, action in enumerate(actions):
            cell = QWidget(ed)
            cell.setFixedHeight(24)
            cell.setStyleSheet("background: transparent;")
            h = QHBoxLayout(cell)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            lbl = QLabel(_action_label(action), cell)
            self._edit_labels.append(lbl)
            h.addWidget(lbl, 1)
            cap = EditKeycap(self._keys.get(action, ""), cell)
            cap.set_locked(self.locked)
            if self.locked:
                cap.setToolTip("Keyset 1 follows your game's own key settings")
            cap.key_captured.connect(
                lambda key, a=action: self.key_captured.emit(self.set_id, a, key))
            self.edit_caps[action] = cap
            h.addWidget(cap)
            grid.addWidget(cell, i // 2, i % 2)
        outer.addLayout(grid)
        self.conflict_banner = QLabel(_CONFLICT_TEXT, ed)
        self.conflict_banner.setWordWrap(True)
        self.conflict_banner.setVisible(bool(self._conflicts))
        outer.addWidget(self.conflict_banner)
        self.cross_label = QLabel("\n".join(cross_notes), ed)
        self.cross_label.setWordWrap(True)
        self.cross_label.setVisible(bool(cross_notes))
        outer.addWidget(self.cross_label)
        if self.locked:
            lock = QLabel("Keyset 1 follows your game's own key settings, so its "
                          "keys are changed in the game.", ed)
            lock.setWordWrap(True)
            self._lock_label = lock
            outer.addWidget(lock)
        else:
            self._lock_label = None
        self.detect_btn = None
        self.detect_label = None
        if self.can_detect:
            # The Settings Keysets page's Detect action: read the game's own
            # settings file onto keyset 1 (utils/widgets/keysets/detect.py).
            line = QHBoxLayout()
            line.setSpacing(10)
            self.detect_btn = SecondaryButton("Detect from game", self._is_dark, ed)
            self.detect_btn.setToolTip(
                "Read your key bindings from the game's own settings file")
            self.detect_btn.clicked.connect(lambda: self.detect_clicked.emit(self.set_id))
            line.addWidget(self.detect_btn)
            self.detect_label = QLabel(self._detect_note, ed)
            self.detect_label.setVisible(bool(self._detect_note))
            line.addWidget(self.detect_label, 1)
            outer.addLayout(line)
        return ed

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        pal = sheet_palette(is_dark)
        k = strip_tokens.set_color(self.number)
        open_radius = (f"border-top-left-radius: {ROW_RADIUS}px;"
                       f" border-top-right-radius: {ROW_RADIUS}px;"
                       " border-bottom-left-radius: 0; border-bottom-right-radius: 0;"
                       " border-bottom-color: transparent;"
                       if self.expanded else f"border-radius: {ROW_RADIUS}px;")
        self.frame.setStyleSheet(
            f"QFrame#ks_row {{ background: {pal['row_bg']};"
            f" border: 1px solid {pal['row_border']}; {open_radius} }}")
        self.status.setStyleSheet(
            f"QLabel {{ font-size: 11px; color: {pal['meta']};"
            " background: transparent; border: none; }")
        self.grip.set_color(qcolor(pal["text_disabled"]))
        for action, cap in zip(ROW_CAPS, self.caps):
            v = self._keys.get(action)
            cap.apply_style(is_dark, conflict=v in self._conflicts,
                            warn=v in self._warn, dim=self.hidden)
        icon_col = qcolor(pal["text_secondary"])
        self.edit_btn.setIcon(make_edit_icon(14, icon_col))
        self.hide_btn.setIcon(make_eye_icon(14, icon_col, crossed=self.hidden))
        self.delete_btn.setIcon(make_trash_icon(14, icon_col))
        for b in (self.edit_btn, self.hide_btn, self.delete_btn):
            b.apply_theme(is_dark)
        if self.editor is not None:
            edit_bg = alpha("#000000", 0.42) if is_dark else alpha("#0f172a", 0.04)
            self.editor.setStyleSheet(
                f"QFrame#ks_edit {{ background: {edit_bg};"
                f" border: 1px solid {pal['row_border']};"
                f" border-top: 1px solid {alpha(k, 0.60)};"
                f" border-bottom-left-radius: {ROW_RADIUS}px;"
                f" border-bottom-right-radius: {ROW_RADIUS}px; }}")
            for lbl in self._edit_labels:
                lbl.setStyleSheet(
                    f"QLabel {{ font-size: 11px; color: {pal['text_secondary']};"
                    " background: transparent; border: none; }")
            for action, cap in self.edit_caps.items():
                v = self._keys.get(action)
                cap.apply_style(is_dark, k, conflict=v in self._conflicts,
                                warn=v in self._warn)
            self.conflict_banner.setStyleSheet(
                "QLabel { " + conflict_banner_css(is_dark, ROW_RADIUS) + " }")
            warn = WARN_DARK if is_dark else WARN_LIGHT
            self.cross_label.setStyleSheet(
                f"QLabel {{ font-size: 10.5px; color: {warn};"
                " background: transparent; border: none; }")
            if self._lock_label is not None:
                self._lock_label.setStyleSheet(
                    f"QLabel {{ font-size: 10.5px; color: {pal['meta']};"
                    " background: transparent; border: none; }")
            if self.detect_btn is not None:
                self.detect_btn.apply_theme(is_dark)
                self.detect_label.setStyleSheet(
                    f"QLabel {{ font-size: 10.5px; color: {pal['meta']};"
                    " background: transparent; border: none; }")


class KeysetsSheet(QWidget):
    """Content widget for the sheet host. Open it with
    host.open(sheet, IDENTITY, TITLE, SUB)."""

    IDENTITY = IDENTITY
    TITLE = TITLE
    SUB = SUB
    game_changed = Signal(str)
    _km_changed = Signal()

    def __init__(self, keymap_manager, settings_manager=None, game: str = "ttr",
                 is_dark: bool | None = None,
                 default_locked: Callable[[str], bool] | None = None,
                 parent=None):
        super().__init__(parent)
        self._km = keymap_manager
        self._sm = settings_manager
        self._game = game if game in GAMES else "ttr"
        self._is_dark = is_dark_palette() if is_dark is None else bool(is_dark)
        if default_locked is None:
            from utils.widgets.keysets.rules import default_set_locked
            default_locked = lambda g, sm=settings_manager: default_set_locked(g, sm)  # noqa: E731
        self._default_locked = default_locked
        self._expanded: set = set()
        self._detect_note: tuple | None = None     # (game, text)
        self._rows: list[KeysetRow] = []
        self._drag = None
        self.setAttribute(Qt.WA_StyledBackground, False)

        lay = sheet_stack(self)
        self.card = GroupCard(IDENTITY, "Keysets", make_dpad_icon(15, QColor("#ffffff")),
                              is_dark=self._is_dark, parent=self)
        self.game_pill = SheetSegmented([GAME_META[g].short for g in GAMES],
                                        GAME_META[self._game].accent_c,
                                        is_dark=self._is_dark)
        self.game_pill.setCurrentIndex(GAMES.index(self._game))
        self.game_pill.index_changed.connect(lambda i: self.set_game(GAMES[i]))
        self.card.add_meta_widget(self.game_pill)
        self.count_label = note_label("", self._is_dark)
        self.card.add_row(self.count_label)
        self.rows_box = QWidget()
        self.rows_box.setStyleSheet("background: transparent;")
        self._rows_layout = QVBoxLayout(self.rows_box)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(8)
        self.card.add_row(self.rows_box)
        self.add_button = AddRow("+  New keyset", is_dark=self._is_dark)
        self.add_button.clicked.connect(self._on_add)
        self.card.add_row(self.add_button)
        lay.addWidget(self.card)
        self.footer = footer_label(FOOTER, self._is_dark)
        lay.addWidget(self.footer)

        self.drop_line = QFrame(self.rows_box)
        self.drop_line.setFixedHeight(2)
        self.drop_line.setStyleSheet(f"background: {IDENTITY}; border: none;")
        self.drop_line.hide()

        self._km_changed.connect(self.refresh)
        ref = weakref.ref(self)

        def _on_km_change():
            me = ref()
            if me is None:
                return
            try:
                me._km_changed.emit()          # queued when off the GUI thread
            except RuntimeError:
                pass                           # widget already deleted
        self._km.on_change(_on_km_change)
        self.refresh()

    # ── public API ──────────────────────────────────────────────────────
    def game(self) -> str:
        return self._game

    def set_game(self, game: str) -> None:
        if game not in GAMES or game == self._game:
            return
        self._game = game
        self._detect_note = None
        self.game_pill.setCurrentIndex(GAMES.index(game))
        self.game_pill.set_fill(GAME_META[game].accent_c)
        self.refresh()
        self.game_changed.emit(game)

    def rows(self) -> list:
        return list(self._rows)

    def expand_index(self, index: int) -> None:
        sid = self._km.id_at(self._game, index)
        if sid is not None:
            self._expanded.add(sid)
            self.refresh()

    def is_expanded(self, set_id: str) -> bool:
        return set_id in self._expanded

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = bool(is_dark)
        pal = sheet_palette(self._is_dark)
        self.card.apply_theme(self._is_dark)
        self.game_pill.apply_sheet_theme(self._is_dark)
        self.add_button.apply_theme(self._is_dark)
        self.count_label.setStyleSheet(
            f"QLabel {{ font-size: 11px; color: {pal['meta']};"
            " background: transparent; border: none; }")
        self.footer.setStyleSheet(
            f"QLabel {{ font-size: 11px; color: {pal['text_disabled']};"
            " background: transparent; border: none; }")
        for row in self._rows:
            row.apply_theme(self._is_dark)

    def refresh(self) -> None:
        game = self._game
        sets = self._km.get_sets(game)
        ids = [s.get("id") for s in sets]
        self._expanded &= set(ids)
        visible = sum(1 for s in sets if s.get("hidden") is not True)
        hidden = len(sets) - visible
        line = f"{visible} shown on strips"
        if hidden:
            line += f" · {hidden} hidden"
        line += f" · {len(sets)} of {self._km.MAX_SETS_PER_GAME} used"
        self.count_label.setText(line)
        self.add_button.setEnabled(len(sets) < self._km.MAX_SETS_PER_GAME)

        cross = self._km.cross_set_conflicts(game)
        try:
            locked0 = bool(self._default_locked(game))
        except Exception:
            locked0 = False

        for row in self._rows:
            self._rows_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._rows = []
        for i, s in enumerate(sets):
            _, pairs = self._km.has_conflicts(game, i)
            conflicts = {s.get(a) for pair in pairs for a in pair if s.get(a)}
            warn, notes = set(), []
            for a_i, a_act, b_i, b_act, key in cross:
                if i not in (a_i, b_i):
                    continue
                here, other_i, other_act = ((a_act, b_i, b_act) if a_i == i
                                            else (b_act, a_i, a_act))
                warn.add(key)
                notes.append(f"{cap_text(key)} is {_action_label(here)} here and "
                             f"{_action_label(other_act)} in keyset {other_i + 1}.")
            is_hidden = s.get("hidden") is True
            row = KeysetRow(
                set_id=s["id"], number=i + 1, game=game, keys=s, hidden=is_hidden,
                can_hide=is_hidden or visible > 1, can_delete=i > 0, can_drag=i > 0,
                expanded=s["id"] in self._expanded, locked=locked0 and i == 0,
                conflicts=conflicts, warn_values=warn, cross_notes=notes,
                can_detect=i == 0,
                detect_note=(self._detect_note[1] if i == 0 and self._detect_note
                             and self._detect_note[0] == game else ""),
                is_dark=self._is_dark, parent=self.rows_box)
            row.edit_clicked.connect(self._on_edit)
            row.hide_clicked.connect(self._on_hide)
            row.delete_clicked.connect(self._on_delete)
            row.key_captured.connect(self._on_key)
            row.detect_clicked.connect(self._on_detect)
            row.grip.pressed.connect(lambda pos, sid=s["id"]: self._drag_start(sid, pos))
            row.grip.moved.connect(self._drag_move)
            row.grip.released.connect(self._drag_end)
            self._rows_layout.addWidget(row)
            self._rows.append(row)
        self.drop_line.raise_()

    # ── handlers ────────────────────────────────────────────────────────
    def _index(self, set_id: str) -> int:
        return self._km.index_of(self._game, set_id)

    def _on_edit(self, set_id: str) -> None:
        if set_id in self._expanded:
            self._expanded.discard(set_id)
        else:
            self._expanded.add(set_id)
        self.refresh()

    def _on_hide(self, set_id: str) -> None:
        self._km.set_hidden(self._game, set_id, not self._km.is_hidden(self._game, set_id))

    def _on_delete(self, set_id: str) -> None:
        i = self._index(set_id)
        if i > 0:
            self._expanded.discard(set_id)
            self._km.delete_set(self._game, i)

    def _on_add(self) -> None:
        self._km.add_set(self._game)

    def _on_detect(self, _set_id: str) -> None:
        """Same call as the Settings Keysets page; the refresh that follows
        re-reads the lock rule, so a newly found settings file locks keyset 1."""
        game = self._game
        try:
            updates = detect.detect_settings_for_game(game, self._km, self._sm)
        except Exception as e:
            print(f"[Keysets] detect failed: {type(e).__name__}: {e}")
            updates = 0
        short = GAME_META[game].short
        if updates:
            text = f"Updated {updates} key{'s' if updates != 1 else ''} from {short}'s settings."
        else:
            text = f"No changes found in {short}'s settings."
        self._detect_note = (game, text)
        self.refresh()

    def _on_key(self, set_id: str, action: str, key: str) -> None:
        i = self._index(set_id)
        if i >= 0:
            self._km.update_set_key(self._game, i, action, key)

    # ── drag to renumber (sets 2-8) ─────────────────────────────────────
    def _drag_start(self, set_id: str, global_pos: QPoint) -> None:
        i = self._index(set_id)
        if i <= 0:
            return
        self._drag = {"id": set_id, "from": i, "to": i}
        self._drag_move(global_pos)

    def drop_index_at(self, y: int) -> int:
        """Target index for a drop at rows_box y, for the dragged set."""
        if self._drag is None:
            return -1
        others = [r for r in self._rows if r.set_id != self._drag["id"]]
        pos = sum(1 for r in others if r.geometry().center().y() < y)
        return max(1, min(pos, len(self._rows) - 1))

    def _drag_move(self, global_pos: QPoint) -> None:
        if self._drag is None:
            return
        y = self.rows_box.mapFromGlobal(global_pos).y()
        to = self.drop_index_at(y)
        self._drag["to"] = to
        others = [r for r in self._rows if r.set_id != self._drag["id"]]
        if to < len(others):
            line_y = others[to].geometry().top() - 5
        else:
            line_y = others[-1].geometry().bottom() + 3 if others else 0
        self.drop_line.setGeometry(0, max(0, line_y), self.rows_box.width(), 2)
        self.drop_line.setVisible(to != self._drag["from"])
        self.drop_line.raise_()

    def _drag_end(self, _global_pos: QPoint) -> None:
        drag, self._drag = self._drag, None
        self.drop_line.hide()
        if drag is None or drag["to"] == drag["from"]:
            return
        self._km.move_set(self._game, drag["id"], drag["to"])
