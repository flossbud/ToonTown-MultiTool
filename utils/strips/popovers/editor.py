"""The keyset editor: a card under a keyset button for rebinding that set.

Two layouts, one remembered app-wide. "List": every action with its keycap;
click a keycap, press a key. "Keys": pick an action, click a key on a small
keyboard. The card never has focus. For "press a key" it takes the keyboard
the way the hotkey capture does (a real grab, plus the overlay key session
where a platform needs one) and gives it back the moment the key arrives,
the capture is cancelled, or the card goes away.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFontMetricsF, QPainter,
                           QPainterPath, QPen, QPolygonF)
from PySide6.QtWidgets import QWidget

from utils import chord_capture_state
from utils.overlay import key_session
from utils.strips import glyphs, paint, tokens
from utils.strips.tokens import dk, lt, tr
from utils.widgets.keysets.movement_key_field import SPECIAL_KEYS, MovementKeyField

LIST = "list"
KEYS = "keys"

WIDTH = 266.0
MARGIN = 18.0          # room for the Neon card's 16 px halo
ANCHOR_GAP = 9.0 - 8.0  # the caret's tip sits about 1 px under the anchor
CARET = 9.0
CARET_RISE = 8.0       # how far the rotated square's tip stands above the card
BORDER = 2.0
PAD_X = 12.0
HEADER_H = 34.0
ROW_H = 22.0
COL_GAP = 14.0
CAP_H = 18.0
KEY = 18.0
KEY_GAP = 2.0
CONFLICT = "#e05252"
CONFLICT_INK = "#ff9a9a"

# Printed names short enough for an 18 px keycap.
SHORT_NAMES = {
    "space": "Space", "BackSpace": "Bksp", "Delete": "Del", "Escape": "Esc",
    "Return": "Enter", "Tab": "Tab", "Shift_L": "Shift", "Shift_R": "R Shift",
    "Alt_L": "Alt", "Alt_R": "R Alt", "Control_L": "Ctrl", "Control_R": "R Ctrl",
    "Up": "↑", "Down": "↓", "Left": "←", "Right": "→",
}

# The small keyboard: (key code, cap text, width; 0 = takes the rest).
_ROWS = (
    (0.0, [(c, c, KEY) for c in "1234567890-="]),
    (0.0, [(c, c.upper(), KEY) for c in "qwertyuiop[]"]),
    (9.0, [(c, c.upper(), KEY) for c in "asdfghjkl;'"]),
    (18.0, [(c, c.upper(), KEY) for c in "zxcvbnm,./"]),
    (0.0, [("Shift_L", "Shift", 34.0), ("Alt_L", "Alt", 24.0), ("space", "", 0.0),
           ("Left", "←", KEY), ("Up", "↑", KEY), ("Down", "↓", KEY),
           ("Right", "→", KEY), ("BackSpace", "Bksp", 30.0)]),
)


# The card is 266 px wide: an action name has about 60 px.
SHORT_LABELS = {"action": "Action"}


def action_label(action: str, label: str) -> str:
    return SHORT_LABELS.get(action, label)


def key_name(key: str | None) -> str:
    if not key:
        return "–"
    if key in SHORT_NAMES:
        return SHORT_NAMES[key]
    return key.upper() if len(key) == 1 else key


def key_from_event(event) -> str | None:
    """The canonical key name for a key press, by the same rules as the
    Keysets page's capture field."""
    if bool(event.modifiers() & Qt.KeypadModifier):
        return MovementKeyField._NUMPAD_KEYS.get(event.key())
    key = MovementKeyField._side_aware_modifier_key(event)
    if key is None:
        key = SPECIAL_KEYS.get(event.key())
    if key is None:
        text = event.text()
        if text and text.isprintable():
            key = text.lower() if text.isalpha() else text
    return key or None


@dataclass(frozen=True)
class EditorModel:
    number: int
    actions: tuple            # ((action, label), ...) in the game's order
    binds: tuple              # ((action, key), ...)
    conflicts: frozenset = frozenset()   # actions sharing a key inside this set
    note: str = ""            # one line about a conflict, or nothing

    def key_of(self, action: str) -> str:
        return dict(self.binds).get(action, "")

    def action_of(self, key: str) -> str:
        for action, bound in self.binds:
            if bound == key:
                return action
        return ""


class KeysetEditor(QWidget):
    bind_requested = Signal(str, str)     # action, key
    layout_changed = Signal(str)          # LIST | KEYS
    close_requested = Signal()
    capture_changed = Signal(bool)        # the card holds the keyboard

    ANCHOR_GAP = ANCHOR_GAP

    def __init__(self, model: EditorModel, kind: str = LIST,
                 style_name: str = tokens.NEON, scale: float = 1.0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._kind = KEYS if kind == KEYS else LIST
        self._style = tokens.style_for(style_name)
        self._scale = float(scale) if scale and scale > 0 else 1.0
        self._colour = tokens.set_color(model.number)
        self._caret_x: float | None = None
        self._flipped = False
        self._listening = ""              # action waiting for a key, if any
        self._selected = model.actions[0][0] if model.actions else ""
        self._hover: tuple | None = None
        self._zones: list[tuple[tuple, QRectF]] = []
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)
        self._relayout()

    # -- state --------------------------------------------------------------

    def model(self) -> EditorModel:
        return self._model

    def set_model(self, model: EditorModel) -> None:
        if model == self._model:
            return
        self._model = model
        self._colour = tokens.set_color(model.number)
        known = [a for a, _label in model.actions]
        if self._selected not in known:
            self._selected = known[0] if known else ""
        self._relayout()

    def kind(self) -> str:
        return self._kind

    def set_kind(self, kind: str) -> None:
        kind = KEYS if kind == KEYS else LIST
        if kind == self._kind:
            return
        self.cancel_capture()
        self._kind = kind
        self._relayout()
        self.layout_changed.emit(kind)

    def selected_action(self) -> str:
        return self._selected

    def listening(self) -> str:
        return self._listening

    def set_caret_x(self, widget_x: float) -> None:
        self._caret_x = widget_x / self._scale
        self.update()

    def set_flipped(self, flipped: bool) -> None:
        """Opened above its anchor: the upward caret is left out."""
        if bool(flipped) != self._flipped:
            self._flipped = bool(flipped)
            self.update()

    # -- capture: the one time the card takes the keyboard --------------------

    def begin_capture(self, action: str) -> None:
        if self._listening == action:
            return
        self.cancel_capture()
        self._listening = action
        # Same order as the hotkey capture: stand the app's own key handling
        # down first, then the key session, then the grab.
        chord_capture_state.set_active(True)
        key_session.begin(self)
        self.grabKeyboard()
        self.capture_changed.emit(True)
        self._relayout()           # the keycap now reads as an ellipsis

    def cancel_capture(self) -> None:
        """Give the keyboard back. Safe to call at any time."""
        if not self._listening:
            return
        self._listening = ""
        self.releaseKeyboard()
        key_session.end(self)
        chord_capture_state.set_active(False)
        self.capture_changed.emit(False)
        self._relayout()

    def keyPressEvent(self, event) -> None:
        if not self._listening:
            event.ignore()
            return
        event.accept()
        if event.isAutoRepeat():
            return
        if event.key() == Qt.Key_Escape:
            self.cancel_capture()
            return
        key = key_from_event(event)
        if not key:
            return                 # a key with no name: keep waiting
        action = self._listening
        self.cancel_capture()
        self.bind_requested.emit(action, key)

    def hideEvent(self, event) -> None:
        self.cancel_capture()
        super().hideEvent(event)

    # -- geometry (design px; the card starts at MARGIN, CARET_RISE) ----------

    def _fonts(self):
        return {
            "title": paint.strip_font(12, 700),
            "seg": paint.strip_font(10, 600),
            "label": paint.strip_font(11, 400),
            "cap": paint.strip_font(10, 600, tokens.MONO_FAMILIES),
            "key": paint.strip_font(9, 600, tokens.MONO_FAMILIES),
            "chip": paint.strip_font(10, 600),
            "hint": paint.strip_font(10, 400),
        }

    def _relayout(self) -> None:
        m = self._model
        fonts = self._fonts()
        zones: list[tuple[tuple, QRectF]] = []
        left, top = MARGIN, CARET_RISE
        inner_l = left + BORDER + PAD_X
        inner_w = WIDTH - 2 * (BORDER + PAD_X)
        y = top + BORDER

        # Header: dot, title, [List | Keys], close.
        close = QRectF(left + WIDTH - BORDER - 8.0 - 20.0, y + 8.0, 20.0, 20.0)
        zones.append((("close",), close))
        seg_fm = QFontMetricsF(fonts["seg"])
        keys_w = seg_fm.horizontalAdvance("Keys") + 14.0
        list_w = seg_fm.horizontalAdvance("List") + 14.0
        seg_h = seg_fm.height() + 6.0
        seg_y = close.center().y() - seg_h / 2.0
        keys_r = QRectF(close.left() - 6.0 - 1.0 - keys_w, seg_y, keys_w, seg_h)
        list_r = QRectF(keys_r.left() - 1.0 - list_w, seg_y, list_w, seg_h)
        zones.append((("kind", LIST), list_r))
        zones.append((("kind", KEYS), keys_r))
        self._seg_box = QRectF(list_r.left() - 1.0, seg_y - 1.0,
                               list_w + keys_w + 3.0, seg_h + 2.0)
        self._header_mid = close.center().y()
        y += HEADER_H + 2.0

        self._label_rects: dict[str, QRectF] = {}
        self._chip_rects: dict[str, QRectF] = {}
        self._keys: list[tuple[str, str, QRectF]] = []
        self._hint_rect = QRectF()
        if self._kind == LIST:
            rows = (len(m.actions) + 1) // 2
            col_w = (inner_w - COL_GAP) / 2.0
            cap_fm = QFontMetricsF(fonts["cap"])
            for i, (action, _label) in enumerate(m.actions):
                col, row = divmod(i, rows)
                x0 = inner_l + col * (col_w + COL_GAP)
                ry = y + row * ROW_H
                text = "…" if action == self._listening else key_name(m.key_of(action))
                cap_w = max(20.0, cap_fm.horizontalAdvance(text) + 12.0)
                cap = QRectF(x0 + col_w - cap_w, ry + (ROW_H - CAP_H) / 2.0, cap_w, CAP_H)
                self._label_rects[action] = QRectF(x0, ry, col_w - cap_w - 6.0, ROW_H)
                zones.append((("cap", action), cap))
            y += rows * ROW_H
        else:
            chip_fm = QFontMetricsF(fonts["chip"])
            cx, cy = inner_l, y
            chip_h = chip_fm.height() + 6.0
            for action, label in m.actions:
                w = chip_fm.horizontalAdvance(label) + 12.0
                if cx + w > inner_l + inner_w + 0.5:
                    cx, cy = inner_l, cy + chip_h + 3.0
                rect = QRectF(cx, cy, w, chip_h)
                self._chip_rects[action] = rect
                zones.append((("chip", action), rect))
                cx += w + 3.0
            y = cy + chip_h + 8.0
            for offset, row in _ROWS:
                fixed = sum(w for _c, _l, w in row) + KEY_GAP * (len(row) - 1)
                kx = inner_l + offset
                for code, label, w in row:
                    if w == 0.0:
                        w = inner_w - fixed
                    rect = QRectF(kx, y, w, KEY)
                    self._keys.append((code, label, rect))
                    zones.append((("key", code), rect))
                    kx += w + KEY_GAP
                y += KEY + KEY_GAP
            y += 8.0 - KEY_GAP
            hint_h = QFontMetricsF(fonts["hint"]).height()
            self._hint_rect = QRectF(inner_l, y, inner_w, hint_h)
            y += hint_h
        self._note_rect = QRectF()
        if m.note:
            note_h = QFontMetricsF(fonts["hint"]).height()
            y += 6.0
            self._note_rect = QRectF(inner_l, y, inner_w, note_h)
            y += note_h
        y += 12.0 + BORDER
        self._card = QRectF(left, top, WIDTH, y - top)
        self._zones = zones
        self._design = QSize(int(round(WIDTH + 2 * MARGIN)), int(round(y + MARGIN)))
        self.setFixedSize(self.sizeHint())
        self.update()

    def sizeHint(self) -> QSize:
        k = self._scale
        return QSize(int(round(self._design.width() * k)),
                     int(round(self._design.height() * k)))

    def _to_widget(self, r: QRectF) -> QRectF:
        k = self._scale
        return QRectF(r.x() * k, r.y() * k, r.width() * k, r.height() * k)

    def zone_rect(self, *key) -> QRectF | None:
        """A clickable part in widget px: ("cap", action), ("chip", action),
        ("key", code), ("kind", LIST | KEYS) or ("close",)."""
        for zone, rect in self._zones:
            if zone == tuple(key):
                return self._to_widget(rect)
        return None

    def card_rect(self) -> QRectF:
        return self._to_widget(self._card)

    def input_rects(self) -> list[QRect]:
        return [self.card_rect().toAlignedRect()]

    # -- painting -----------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        self.render_editor(p)
        p.end()

    def render_editor(self, p: QPainter) -> None:
        m, c, neon = self._model, self._colour, self._style.is_neon
        fonts = self._fonts()
        white = QColor("#ffffff")
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.scale(self._scale, self._scale)
        card = self._card
        radius = 10.0 if neon else 5.0

        # Card: halo, fill, caret, border.
        if neon:
            paint.paint_glow(p, card.translated(0, 8), radius,
                             tokens.rgba(0, 0, 0, 0.4), 22.0)
            paint.paint_glow(p, card, radius, tr(c, 42), 16.0)
            fill = QBrush(tokens.css_gradient(card, tokens.BODY_ANGLE,
                                              dk(c, 24), dk(c, 11)))
            caret_fill = QColor(dk(c, 22))
        else:
            fill = QBrush(QColor(tokens.POPOVER_BASE))
            caret_fill = QColor(tokens.POPOVER_BASE)
        cx = self._caret_x if self._caret_x is not None else card.center().x()
        cx = max(card.left() + radius + CARET, min(cx, card.right() - radius - CARET))
        tip = QPointF(cx, card.top() - CARET * 0.7071 + BORDER * 0.5)
        half = CARET * 0.7071
        caret = QPolygonF([tip, QPointF(cx + half, card.top() + BORDER),
                           QPointF(cx - half, card.top() + BORDER)])
        p.fillPath(paint.rounded(card, radius), fill)
        paint._border(p, paint.rounded, card, radius, BORDER, QColor(c))
        if not self._flipped:
            p.setPen(Qt.NoPen)
            p.setBrush(caret_fill)
            p.drawPolygon(caret)
            pen = QPen(QColor(c), BORDER)
            pen.setJoinStyle(Qt.MiterJoin)
            p.setPen(pen)
            p.drawLine(QPointF(cx - half, card.top() + BORDER * 0.5), tip)
            p.drawLine(tip, QPointF(cx + half, card.top() + BORDER * 0.5))

        # Header.
        mid = self._header_mid
        dot_x = card.left() + BORDER + PAD_X
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c))
        p.drawEllipse(QPointF(dot_x + 4.5, mid), 4.5, 4.5)
        title = QRectF(dot_x + 9.0 + 6.0, mid - 10.0, 120.0, 20.0)
        paint._text(p, title, f"Keyset {m.number}", fonts["title"], white,
                    Qt.AlignLeft | Qt.AlignVCenter)
        p.fillPath(paint.rounded(self._seg_box, 5.0), tokens.rgba(0, 0, 0, 0.35))
        for zone, rect in self._zones:
            if zone[0] == "kind":
                on = zone[1] == self._kind
                if on:
                    p.fillPath(paint.rounded(rect, 4.0), tokens.rgba(255, 255, 255, 0.14))
                elif self._hover == zone:
                    p.fillPath(paint.rounded(rect, 4.0), tokens.rgba(255, 255, 255, 0.07))
                paint._text(p, rect, "List" if zone[1] == LIST else "Keys",
                            fonts["seg"], white if on else QColor("#999999"))
            elif zone[0] == "close":
                if self._hover == zone:
                    p.fillPath(paint.rounded(rect, 4.0), tokens.rgba(255, 255, 255, 0.09))
                glyphs.paint_close(p, glyphs.centred_square(rect, 12.0),
                                   QColor(lt(c, 60)))

        if self._kind == LIST:
            self._paint_list(p, fonts, white)
        else:
            self._paint_keys(p, fonts, white)
        if m.note:
            paint._text(p, self._note_rect, m.note, fonts["hint"], QColor(CONFLICT_INK),
                        Qt.AlignLeft | Qt.AlignVCenter)
        p.restore()

    def _cap(self, p, rect, text, font, hot: bool, conflict: bool, hover: bool):
        c = self._colour
        if hot:
            fill, edge, ink = QColor(c), QColor(lt(c, 70)), QColor("#ffffff")
        elif conflict:
            fill = tokens.rgba(224, 82, 82, 0.16)
            edge, ink = QColor(CONFLICT), QColor(CONFLICT_INK)
        else:
            fill, edge, ink = QColor("#2e2e2e"), QColor("#444444"), QColor("#ffffff")
        path = paint.rounded(rect, 4.0)
        p.fillPath(path, fill)
        if hover and not hot:
            p.fillPath(path, paint.HOVER_VEIL)
        paint._border(p, paint.rounded, rect, 4.0, 1.0, edge)
        paint._text(p, rect, text, font, ink)

    def _paint_list(self, p, fonts, white) -> None:
        m = self._model
        grey = QColor("#bbbbbb")
        labels = dict(m.actions)
        for zone, rect in self._zones:
            if zone[0] != "cap":
                continue
            action = zone[1]
            room = self._label_rects[action]
            label = QFontMetricsF(fonts["label"]).elidedText(
                labels.get(action, action), Qt.ElideRight, room.width())
            paint._text(p, room, label, fonts["label"], grey,
                        Qt.AlignLeft | Qt.AlignVCenter)
            hot = action == self._listening
            text = "…" if hot else key_name(m.key_of(action))
            self._cap(p, rect, text, fonts["cap"], hot,
                      action in m.conflicts, self._hover == zone)

    def _paint_keys(self, p, fonts, white) -> None:
        m, c = self._model, self._colour
        labels = dict(m.actions)
        for action, rect in self._chip_rects.items():
            on = action == self._selected
            path = paint.rounded(rect, 4.0)
            if on:
                p.fillPath(path, QColor(c))
            else:
                p.fillPath(path, tokens.rgba(255, 255, 255, 0.07))
                if self._hover == ("chip", action):
                    p.fillPath(path, paint.HOVER_VEIL)
            ink = white if on else QColor(CONFLICT_INK if action in m.conflicts
                                          else "#bbbbbb")
            paint._text(p, rect, labels.get(action, action), fonts["chip"], ink)
        selected_key = m.key_of(self._selected)
        bound = {key for _a, key in m.binds if key}
        for code, label, rect in self._keys:
            hot = bool(selected_key) and code == selected_key
            path = paint.rounded(rect, 4.0)
            if hot:
                fill, edge = QColor(c), QColor(lt(c, 70))
            elif code in bound:
                fill, edge = tr(c, 34), tr(c, 70)
            else:
                fill, edge = QColor("#2e2e2e"), QColor("#444444")
            p.fillPath(path, fill)
            if self._hover == ("key", code) and not hot:
                p.fillPath(path, paint.HOVER_VEIL)
            paint._border(p, paint.rounded, rect, 4.0, 1.0, edge)
            if label:
                paint._text(p, rect, label, fonts["key"], white)
        # "<Action> is <key> . click a key to rebind"
        fm = QFontMetricsF(fonts["hint"])
        mono_fm = QFontMetricsF(fonts["cap"])
        x, r = self._hint_rect.left(), self._hint_rect
        flags = Qt.AlignLeft | Qt.AlignVCenter
        lead = f"{labels.get(self._selected, self._selected)} is "
        paint._text(p, QRectF(x, r.top(), r.width(), r.height()), lead,
                    fonts["hint"], QColor("#999999"), flags)
        x += fm.horizontalAdvance(lead)
        key_text = key_name(selected_key)
        paint._text(p, QRectF(x, r.top(), r.width(), r.height()), key_text,
                    fonts["cap"], white, flags)
        x += mono_fm.horizontalAdvance(key_text)
        paint._text(p, QRectF(x, r.top(), r.width(), r.height()),
                    " · click a key to rebind", fonts["hint"],
                    QColor("#999999"), flags)

    # -- pointer ------------------------------------------------------------

    def _zone_at(self, pos) -> tuple | None:
        k = self._scale
        x, y = pos.x() / k, pos.y() / k
        for zone, rect in self._zones:
            if rect.contains(x, y):
                return zone
        return None

    def mouseMoveEvent(self, event) -> None:
        zone = self._zone_at(event.position())
        if zone != self._hover:
            self._hover = zone
            self.setCursor(Qt.PointingHandCursor if zone else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, event) -> None:
        if self._hover is not None:
            self._hover = None
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        event.accept()
        if event.button() != Qt.LeftButton:
            return
        zone = self._zone_at(event.position())
        if zone is None:
            self.cancel_capture()       # a click on the card's body
            return
        if zone[0] == "close":
            self.cancel_capture()
            self.close_requested.emit()
        elif zone[0] == "kind":
            self.set_kind(zone[1])
        elif zone[0] == "cap":
            if self._listening == zone[1]:
                self.cancel_capture()
            else:
                self.begin_capture(zone[1])
        elif zone[0] == "chip":
            if zone[1] != self._selected:
                self._selected = zone[1]
                self.update()
        elif zone[0] == "key":
            if self._selected and self._model.key_of(self._selected) != zone[1]:
                self.bind_requested.emit(self._selected, zone[1])
