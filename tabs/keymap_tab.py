"""
Keysets Tab — UI for creating and editing per-game movement sets.

Each set is one SetCard(QFrame) that paints its own rounded card background
gradient and 4px top stripe in a single paintEvent, and owns its header
(badge + name + chevron + delete) and an AnimatedBody (key-mapping grid)
internally. The active game is selected via an icon-only _SegmentedSwitch
when both TTR and CC are detected.
"""

from __future__ import annotations

import sys
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QLineEdit,
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtGui import QColor, QPainter, QPainterPath, QBrush, QLinearGradient, QPen, QIcon, QPixmap
from utils.theme_manager import resolve_theme, get_theme_colors, apply_card_shadow, get_set_color, make_trash_icon, get_set_card_styles
from utils.symbols import S, M
from utils.widgets import install_modern_scrollbar

from utils import logical_actions


def _asset_path(name: str) -> str:
    """Resolve a bundled asset relative to the repo root / PyInstaller _MEIPASS.
    Mirrors the same pattern in tabs/launch_tab.py and tabs/credits_tab.py."""
    base = getattr(
        sys, "_MEIPASS",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    return os.path.join(base, "assets", name)


ACTION_LABELS = {
    "forward": "Forward",
    "reverse": "Reverse",
    "left":    "Left",
    "right":   "Right",
    "jump":    "Jump",
    "book":    "Book",
    "gags":    "Gags",
    "tasks":   "Tasks",
    "map":     "Map",
    "sprint":  "Sprint",
}

DISPLAY_NAMES = {
    "space": "Space", "Control_L": "L Ctrl", "Control_R": "R Ctrl",
    "Shift_L": "L Shift", "Shift_R": "R Shift",
    "Alt_L": "L Alt", "Alt_R": "R Alt",
    "Up": "Up Arrow", "Down": "Down Arrow", "Left": "Left Arrow", "Right": "Right Arrow",
    "Return": "Enter", "BackSpace": "Backspace", "Tab": "Tab",
    "Escape": "Esc", "Delete": "Delete",
    # Numpad keys
    "KP_0": "NP 0", "KP_1": "NP 1", "KP_2": "NP 2", "KP_3": "NP 3",
    "KP_4": "NP 4", "KP_5": "NP 5", "KP_6": "NP 6", "KP_7": "NP 7",
    "KP_8": "NP 8", "KP_9": "NP 9",
    "KP_Decimal": "NP .", "KP_Enter": "NP Enter",
    "KP_Add": "NP +", "KP_Subtract": "NP -",
    "KP_Multiply": "NP *", "KP_Divide": "NP /",
}

SPECIAL_KEYS = {
    Qt.Key_Space: "space", Qt.Key_Return: "Return", Qt.Key_Enter: "Return",
    Qt.Key_Tab: "Tab", Qt.Key_Backspace: "BackSpace", Qt.Key_Escape: "Escape",
    Qt.Key_Delete: "Delete",
    Qt.Key_Up: "Up", Qt.Key_Down: "Down", Qt.Key_Left: "Left", Qt.Key_Right: "Right",
}


def _display(key: str) -> str:
    if not key:
        return "Unset"
    return DISPLAY_NAMES.get(key, key.upper() if len(key) == 1 else key)


# ── Key capture field ──────────────────────────────────────────────────────


class MovementKeyField(QLineEdit):
    key_captured = Signal(str)

    def __init__(self, initial_key: str = "", parent=None):
        super().__init__(parent)
        self._key = initial_key
        self._awaiting = False
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMinimumHeight(28)
        self.setFixedWidth(88)
        self.setAlignment(Qt.AlignCenter)
        self._update_display()

    def _update_display(self):
        self.setText("Press a key…" if self._awaiting else _display(self._key))
        self.setProperty("awaiting", self._awaiting)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_key(self, key: str):
        self._key = key
        self._awaiting = False
        self._update_display()

    def get_key(self) -> str:
        return self._key

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self._awaiting = True
        self._update_display()

    # Map Qt key codes to KP_* keysym names when numpad modifier is active
    _NUMPAD_KEYS = {
        Qt.Key_0: "KP_0", Qt.Key_1: "KP_1", Qt.Key_2: "KP_2",
        Qt.Key_3: "KP_3", Qt.Key_4: "KP_4", Qt.Key_5: "KP_5",
        Qt.Key_6: "KP_6", Qt.Key_7: "KP_7", Qt.Key_8: "KP_8",
        Qt.Key_9: "KP_9",
        Qt.Key_Period: "KP_Decimal",
        Qt.Key_Enter: "KP_Enter",
        Qt.Key_Plus: "KP_Add", Qt.Key_Minus: "KP_Subtract",
        Qt.Key_Asterisk: "KP_Multiply", Qt.Key_Slash: "KP_Divide",
    }

    @staticmethod
    def _vk_is_down(vk: int) -> bool:
        """Windows-only helper: check if a virtual key is currently pressed."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
        except Exception:
            return False

    @staticmethod
    def _side_aware_modifier_key(event) -> str | None:
        """Return side-specific modifier names when available (e.g. Control_R)."""
        k = event.key()
        if k not in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt):
            return None

        if sys.platform == "win32":
            vk = int(event.nativeVirtualKey()) if hasattr(event, "nativeVirtualKey") else 0
            sc = int(event.nativeScanCode()) if hasattr(event, "nativeScanCode") else 0

            # Prefer explicit right/left virtual keys when present.
            if k == Qt.Key_Control:
                # Most reliable on Windows: query actual key state.
                if MovementKeyField._vk_is_down(0xA3):  # VK_RCONTROL
                    return "Control_R"
                if MovementKeyField._vk_is_down(0xA2):  # VK_LCONTROL
                    return "Control_L"
                if vk == 0xA3:
                    return "Control_R"
                if vk == 0xA2:
                    return "Control_L"
                # Fallback via scancode (extended right ctrl often reports 0x11D / 285).
                if sc in (0x11D, 285):
                    return "Control_R"
                return "Control_L"

            if k == Qt.Key_Shift:
                if MovementKeyField._vk_is_down(0xA1):  # VK_RSHIFT
                    return "Shift_R"
                if MovementKeyField._vk_is_down(0xA0):  # VK_LSHIFT
                    return "Shift_L"
                if vk == 0xA1:
                    return "Shift_R"
                if vk == 0xA0:
                    return "Shift_L"
                # Typical shift scancodes: left=42, right=54
                if sc == 54:
                    return "Shift_R"
                return "Shift_L"

            if k == Qt.Key_Alt:
                if MovementKeyField._vk_is_down(0xA5):  # VK_RMENU
                    return "Alt_R"
                if MovementKeyField._vk_is_down(0xA4):  # VK_LMENU
                    return "Alt_L"
                if vk == 0xA5:
                    return "Alt_R"
                if vk == 0xA4:
                    return "Alt_L"
                # Extended right alt often reports 0x138 / 312.
                if sc in (0x138, 312):
                    return "Alt_R"
                return "Alt_L"

        # Cross-platform fallback when side info is unavailable.
        if k == Qt.Key_Control:
            return "Control_L"
        if k == Qt.Key_Shift:
            return "Shift_L"
        if k == Qt.Key_Alt:
            return "Alt_L"
        return None

    def keyPressEvent(self, e):
        if not self._awaiting:
            return e.ignore()
        is_numpad = bool(e.modifiers() & Qt.KeypadModifier)
        if is_numpad:
            key = self._NUMPAD_KEYS.get(e.key())
        else:
            key = self._side_aware_modifier_key(e)
            if key is None:
                key = SPECIAL_KEYS.get(e.key())
        if key is None:
            text = e.text()
            if text and text.isprintable():
                key = text.lower() if text.isalpha() else text
        if key:
            self._key = key
            self._awaiting = False
            self._update_display()
            self.clearFocus()
            self.key_captured.emit(key)
        e.accept()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if self._awaiting:
            self._awaiting = False
            self._update_display()


# ── Animated body (slides open / closed) ───────────────────────────────────


class AnimatedBody(QFrame):
    expand_finished = Signal()
    collapse_finished = Signal()

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
        self.expand_finished.emit()

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
        self.collapse_finished.emit()


# ── SetCard widget ─────────────────────────────────────────────────────────


class SetCard(QFrame):
    """One movement set rendered as a single card. Owns its own paintEvent
    (rounded background + 4px top stripe inside one QPainterPath) so the
    stripe rounds with the card without manual masking. Owns the body
    (AnimatedBody) and the header row internally; consumers wire signals
    instead of poking widget internals.
    """

    CORNER_RADIUS = 10
    STRIPE_HEIGHT = 4

    toggle_requested = Signal()
    name_changed     = Signal(str)
    delete_requested = Signal()
    key_changed       = Signal(str, str)   # (action_name, captured_key)
    detect_requested  = Signal()

    def __init__(self, index: int, set_data: dict, active_game: str = "ttr", parent=None):
        super().__init__(parent)
        self.index = index
        self.set_data = set_data
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._styles = get_set_card_styles(index, is_dark=True)
        self._header = None  # set before installEventFilter so eventFilter is safe

        # Reserve STRIPE_HEIGHT at the top via the layout margin so child
        # widgets sit below the painted stripe. Setting both QWidget AND
        # layout contents-margins stacks the inset (double-margin bug).
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, self.STRIPE_HEIGHT, 0, 0)
        outer.setSpacing(0)

        # ── Header row (badge + name + chevron + [delete]) ──────────
        header = QFrame()
        header.setObjectName("set_card_header")
        header.setCursor(Qt.PointingHandCursor)
        # Transparent bg so the SetCard's painted gradient shows through.
        # Without this, Qt fills the QFrame opaquely from the palette window
        # color and covers the painted card body.
        header.setStyleSheet("QFrame#set_card_header { background: transparent; border: none; }")
        header.installEventFilter(self)  # forwards clicks to mousePressEvent
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 12, 14, 12)
        hl.setSpacing(10)

        badge = QLabel(f"SET {index + 1}")
        badge.setObjectName("set_card_badge")
        badge.setStyleSheet(self._badge_qss())
        hl.addWidget(badge)

        if index == 0:
            name_widget = QLabel(set_data.get("name", "Default"))
            name_widget.setObjectName("set_name_label")
        else:
            name_widget = QLineEdit(set_data.get("name", f"Set {index + 1}"))
            name_widget.setObjectName("set_name_edit")
            name_widget.editingFinished.connect(
                lambda w=name_widget: self.name_changed.emit(w.text())
            )
        name_widget.setStyleSheet(self._name_qss())
        hl.addWidget(name_widget, 1)

        self._chevron = QLabel(M("▼", "v"))
        self._chevron.setStyleSheet("color: rgba(255,255,255,0.7); font-size: 13px;")
        hl.addWidget(self._chevron)

        if index > 0:
            del_btn = QPushButton()
            del_btn.setFixedSize(28, 28)
            del_btn.setToolTip("Delete this movement set")
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.setIcon(make_trash_icon(16, QColor("#8a9bb8")))
            del_btn.setStyleSheet(self._delete_qss())
            del_btn.clicked.connect(self.delete_requested.emit)
            hl.addWidget(del_btn)

        outer.addWidget(header)
        self._header = header
        self._name_widget = name_widget

        # ── Body (AnimatedBody — same animation as today's pattern) ──
        self._active_game = active_game
        self._body = AnimatedBody()
        self._body.setObjectName("set_card_body")
        # Transparent for the same reason as the header above — otherwise
        # the body's opaque QFrame paint covers the card gradient when expanded.
        self._body.setStyleSheet("QFrame#set_card_body { background: transparent; border: none; }")
        bl = QVBoxLayout(self._body)
        bl.setContentsMargins(14, 12, 14, 14)
        bl.setSpacing(8)

        if index == 0:
            hint = QLabel(
                "These keys are what is sent to all game windows for input.\n"
                "Make sure these match with your in-game settings."
            )
            hint.setObjectName("set_body_hint")
            hint.setWordWrap(True)
            hint.setStyleSheet(
                "font-size: 11px; color: rgba(255,255,255,0.45); "
                "background: none; border: none; padding: 0 0 4px 0;"
            )
            bl.addWidget(hint)

        two_col = QHBoxLayout()
        two_col.setSpacing(20)
        move_col = QVBoxLayout()
        move_col.setSpacing(6)
        aux_col = QVBoxLayout()
        aux_col.setSpacing(6)

        def _make_key_row(action):
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(ACTION_LABELS.get(action, action.title()))
            lbl.setObjectName("direction_label")
            lbl.setFixedWidth(50)
            row.addWidget(lbl)
            field = MovementKeyField(set_data.get(action, ""))
            field.setObjectName(f"key_field_{action}")
            field.key_captured.connect(
                lambda key, a=action: self.key_changed.emit(a, key)
            )
            row.addWidget(field)
            row.addStretch()
            return row

        actions = logical_actions.actions_for(active_game)
        for action in actions:
            if action in ("forward", "reverse", "left", "right", "jump"):
                move_col.addLayout(_make_key_row(action))
        for action in actions:
            if action in ("book", "gags", "tasks", "map", "sprint"):
                aux_col.addLayout(_make_key_row(action))
        aux_col.addStretch()
        two_col.addLayout(move_col)
        two_col.addLayout(aux_col)
        two_col.addStretch()
        bl.addLayout(two_col)

        if index == 0:
            label = "Detect TTR Settings" if active_game == "ttr" else "Detect CC Settings"
            detect_btn = QPushButton(f"{S('🔍 ', '')}{label}")
            detect_btn.setObjectName("detect_btn")
            detect_btn.setFixedHeight(30)
            detect_btn.setCursor(Qt.PointingHandCursor)
            detect_btn.setToolTip(
                "Read current settings from Toontown Rewritten configuration"
                if active_game == "ttr"
                else "Read current settings from Corporate Clash preferences"
            )
            detect_btn.clicked.connect(self.detect_requested.emit)
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            btn_row.addWidget(detect_btn)
            bl.addLayout(btn_row)

        outer.addWidget(self._body)
        self.setMinimumHeight(self.STRIPE_HEIGHT + header.sizeHint().height())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, self.CORNER_RADIUS, self.CORNER_RADIUS)
        p.setClipPath(path)

        # 1) Card background gradient (top stop -> bottom stop)
        bg_grad = QLinearGradient(0, 0, 0, rect.height())
        bg_grad.setColorAt(0, self._rgba_to_qcolor(self._styles["card_grad_top"]))
        bg_grad.setColorAt(1, self._rgba_to_qcolor(self._styles["card_grad_bottom"]))
        p.fillPath(path, QBrush(bg_grad))

        # 2) 4px top stripe with white-edge gloss + horizontal color band
        stripe_rect = rect.adjusted(0, 0, 0, -(rect.height() - self.STRIPE_HEIGHT))
        color_band = QLinearGradient(stripe_rect.left(), 0, stripe_rect.right(), 0)
        color_band.setColorAt(0.0, QColor(self._styles["stripe_edge"]))
        color_band.setColorAt(0.5, QColor(self._styles["stripe_center"]))
        color_band.setColorAt(1.0, QColor(self._styles["stripe_edge"]))
        p.fillRect(stripe_rect, QBrush(color_band))
        gloss = QLinearGradient(0, stripe_rect.top(), 0, stripe_rect.bottom())
        gloss.setColorAt(0.0, QColor(255, 255, 255, 76))   # 0.30 alpha
        gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(stripe_rect, QBrush(gloss))

        # 3) Card border (matches stylesheet rgba pattern)
        pen = QPen(self._rgba_to_qcolor(self._styles["card_border"]))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.end()

    @staticmethod
    def _rgba_to_qcolor(rgba: str) -> QColor:
        """Parse our `rgba(r, g, b, a)` style strings into a QColor."""
        inner = rgba[rgba.index("(") + 1: rgba.rindex(")")]
        parts = [s.strip() for s in inner.split(",")]
        r, g, b = (int(parts[0]), int(parts[1]), int(parts[2]))
        a = int(float(parts[3]) * 255)
        return QColor(r, g, b, a)

    def eventFilter(self, obj, ev):
        # Header row click toggles. Clicks on the name QLineEdit / delete
        # button propagate naturally and DON'T reach this filter.
        from PySide6.QtCore import QEvent
        if self._header is not None and obj is self._header and ev.type() == QEvent.Type.MouseButtonPress:
            self.toggle_requested.emit()
            return True
        return super().eventFilter(obj, ev)

    def mousePressEvent(self, ev):
        # Direct click on the card (e.g. from tests). Forwarded to toggle.
        self.toggle_requested.emit()
        super().mousePressEvent(ev)

    def _badge_qss(self) -> str:
        s = self._styles
        return (
            f"QLabel#set_card_badge {{ "
            f"background: {s['badge_bg']}; color: {s['badge_text']}; "
            f"font-size: 9px; font-weight: 700; letter-spacing: 0.5px; "
            f"border-radius: 4px; padding: 3px 8px; "
            f"border: 1px solid {s['badge_ring']}; "
            f"}}"
        )

    def _name_qss(self) -> str:
        s = self._styles
        if self.index == 0:
            return (
                f"QLabel#set_name_label {{ "
                f"color: {s['name_color']}; font-size: 14px; font-weight: 800; "
                f"letter-spacing: 0.2px; background: transparent; "
                f"}}"
            )
        return (
            f"QLineEdit#set_name_edit {{ "
            f"color: {s['name_color']}; font-size: 14px; font-weight: 800; "
            f"letter-spacing: 0.2px; background: transparent; border: none; padding: 2px 4px; "
            f"}}"
            f"QLineEdit#set_name_edit:focus {{ "
            f"background: rgba(255,255,255,0.06); "
            f"border-bottom: 1px solid {s['head_divider']}; "
            f"}}"
        )

    def _delete_qss(self) -> str:
        s = self._styles
        return (
            f"QPushButton {{ background: rgba(255,255,255,0.04); "
            f"border: 1px solid rgba(255,255,255,0.12); border-radius: 6px; "
            f"color: #8a9bb8; }} "
            f"QPushButton:hover {{ background: rgba(255,255,255,0.08); "
            f"color: {s['name_color']}; border-color: rgba(255,255,255,0.25); }}"
        )

    def set_expanded(self, expanded: bool, *, animate: bool = True):
        if expanded:
            if animate:
                self._body.expand()
            else:
                self._body.setVisible(True)
            self._chevron.setText(M("▼", "v"))
        else:
            if animate:
                self._body.collapse()
            else:
                self._body.setVisible(False)
            self._chevron.setText(M("▶", ">"))


class _SegmentedSwitch(QFrame):
    """Icon-only TTR/CC switch. Inactive buttons are dimmed; active button
    is tinted by per-game accent (TTR blue, CC orange) to match the
    Launch tab's per-game card identity colors."""

    game_changed = Signal(str)

    _ACTIVE_BG = {
        "ttr": "rgba(74, 143, 231, 0.18)",
        "cc":  "rgba(242, 109, 33, 0.18)",
    }
    _ACTIVE_RING = {
        "ttr": "rgba(74, 143, 231, 0.45)",
        "cc":  "rgba(242, 109, 33, 0.45)",
    }
    _TITLES = {"ttr": "Toontown Rewritten", "cc": "Corporate Clash"}

    def __init__(self, active_game: str, parent=None):
        super().__init__(parent)
        self.setObjectName("seg_switch_wrap")
        self._active = active_game
        self._buttons: dict[str, QPushButton] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(0)
        outer.addStretch()

        bar = QFrame()
        bar.setObjectName("seg_switch_bar")
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(4, 4, 4, 4)
        bar_lay.setSpacing(4)

        self._icons: dict[str, dict[str, QIcon]] = {}
        for game in ("ttr", "cc"):
            b = QPushButton()
            b.setFixedSize(56, 40)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(self._TITLES[game])
            pm = QPixmap(_asset_path(f"{game}.png"))
            if not pm.isNull():
                self._icons[game] = {
                    "active":   QIcon(pm),
                    "inactive": QIcon(self._dim_pixmap(pm, 0.55)),
                }
                b.setIconSize(QSize(28, 28))
            b.clicked.connect(lambda _, g=game: self._on_click(g))
            bar_lay.addWidget(b)
            self._buttons[game] = b

        outer.addWidget(bar)
        outer.addStretch()
        self._apply_styles()

    @staticmethod
    def _dim_pixmap(pm: QPixmap, opacity: float) -> QPixmap:
        """Return a copy of `pm` rendered at the given opacity (0.0-1.0)."""
        out = QPixmap(pm.size())
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setOpacity(opacity)
        p.drawPixmap(0, 0, pm)
        p.end()
        return out

    def _on_click(self, game: str):
        if game == self._active:
            return
        self._active = game
        self._apply_styles()
        self.game_changed.emit(game)

    def set_active(self, game: str):
        if game == self._active:
            return
        self._active = game
        self._apply_styles()

    def _apply_styles(self):
        wrap_qss = (
            "QFrame#seg_switch_bar { background: rgba(255,255,255,0.04); "
            "border: 1px solid rgba(255,255,255,0.10); border-radius: 10px; }"
        )
        for game, btn in self._buttons.items():
            icons = self._icons.get(game)
            if game == self._active:
                if icons is not None:
                    btn.setIcon(icons["active"])
                btn.setStyleSheet(
                    f"QPushButton {{ background: {self._ACTIVE_BG[game]}; "
                    f"border: 1px solid {self._ACTIVE_RING[game]}; "
                    f"border-radius: 7px; }}"
                )
            else:
                if icons is not None:
                    btn.setIcon(icons["inactive"])
                btn.setStyleSheet(
                    "QPushButton { background: transparent; border: none; "
                    "border-radius: 7px; } "
                    "QPushButton:hover { background: rgba(255,255,255,0.04); }"
                )
        self.setStyleSheet(wrap_qss)


# ── Main Tab ───────────────────────────────────────────────────────────────


class KeymapTab(QWidget):
    def __init__(self, keymap_manager, settings_manager=None, parent=None):
        super().__init__(parent)
        self.keymap_manager = keymap_manager
        self.settings_manager = settings_manager
        self._entries = []  # list of {"card", "index", "expanded"}

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

        from utils.layout import clamp_centered

        scroll_inner = QWidget()
        scroll_inner_layout = QHBoxLayout(scroll_inner)
        scroll_inner_layout.setContentsMargins(0, 0, 0, 0)

        self._scroll_widget = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_widget)
        self._scroll_layout.setContentsMargins(24, 20, 24, 20)
        self._scroll_layout.setSpacing(0)
        self._scroll_layout.setAlignment(Qt.AlignTop)

        clamp_centered(scroll_inner_layout, self._scroll_widget, 720)

        self._scroll.setWidget(scroll_inner)
        outer.addWidget(self._scroll)

        # Scope to the first detected game; default to TTR if neither or both are detected.
        if self._cc_detected() and not self._ttr_detected():
            self._active_game: str = "cc"
        else:
            self._active_game: str = "ttr"
        self._segmented = None
        # Detection is intentionally cached at construction. Live re-evaluation on
        # settings_manager.on_change is queued as a v2 followup; users currently
        # need to restart TTMT after adding a game install path in Settings.
        self._show_segmented = self._both_games_detected()
        if self._show_segmented:
            self._segmented = _SegmentedSwitch(self._active_game, parent=self)
            self._segmented.game_changed.connect(self._on_segment_clicked)
            outer.insertWidget(0, self._segmented)

        self._build_cards()
        self.refresh_theme()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build_cards(self):
        if not hasattr(self, "_initialized_expansion") or not self._initialized_expansion:
            self._initialized_expansion = True
            key = f"keymap_expanded_states_{self._active_game}"
            legacy = self.settings_manager.get("keymap_expanded_states", None) if self.settings_manager else None
            expanded_list = self.settings_manager.get(key, legacy if legacy is not None else [0]) if self.settings_manager else [0]
            prev_states = {i: (i in expanded_list) for i in range(16)}
        else:
            prev_states = {entry["index"]: entry["expanded"] for entry in self._entries}

        for entry in self._entries:
            entry["card"].deleteLater()
        self._entries.clear()

        while self._scroll_layout.count():
            item = self._scroll_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        is_dark = resolve_theme(self.settings_manager) == "dark"

        sets = self.keymap_manager.get_sets(self._active_game)
        for idx, s in enumerate(sets):
            if idx > 0:
                self._scroll_layout.addSpacing(10)
            card = SetCard(index=idx, set_data=s, active_game=self._active_game, parent=self)
            card.toggle_requested.connect(lambda i=idx: self._toggle(i))
            card.name_changed.connect(lambda name, i=idx: self._on_name_changed(i, name))
            card.key_changed.connect(lambda action, key, i=idx: self._on_key_changed(i, action, key))
            card.delete_requested.connect(lambda i=idx: self._on_delete_set(i))
            card.detect_requested.connect(self._on_detect_settings)

            expanded = prev_states.get(idx, False)
            card.set_expanded(expanded, animate=False)
            apply_card_shadow(card, is_dark, blur=14, offset_y=4)

            self._scroll_layout.addWidget(card)
            self._entries.append({
                "card": card, "index": idx, "expanded": expanded,
            })

        self._scroll_layout.addSpacing(16)
        self._add_btn = QPushButton(f"{S('➕', '+')} Add Movement Set")
        self._add_btn.setMinimumHeight(28)
        self._add_btn.setMaximumWidth(260)
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.clicked.connect(self._on_add_set)
        self._add_btn.setVisible(len(sets) < self.keymap_manager.MAX_SETS_PER_GAME)
        self._scroll_layout.addWidget(self._add_btn, alignment=Qt.AlignHCenter)
        self._scroll_layout.addStretch()

        self._refresh_default_conflict_markers()

    # ── Game detection + segmented control ────────────────────────────────

    def _both_games_detected(self) -> bool:
        """True when both TTR and CC are findable on this machine."""
        return self._ttr_detected() and self._cc_detected()

    def _ttr_detected(self) -> bool:
        if self.settings_manager is None:
            return False
        engine = self.settings_manager.get("ttr_engine_dir", "")
        if engine and os.path.exists(engine):
            return True
        try:
            from services.ttr_login_service import find_engine_path
            return bool(find_engine_path())
        except Exception:
            return False

    def _cc_detected(self) -> bool:
        if self.settings_manager is None:
            return False
        engine = self.settings_manager.get("cc_engine_dir", "")
        if engine and os.path.exists(engine):
            return True
        try:
            from services.wine_runtimes import discover_cc_installs
            return bool(discover_cc_installs())
        except Exception:
            return False

    def _on_segment_clicked(self, game: str):
        if game == self._active_game:
            return
        self._active_game = game
        if self._segmented is not None:
            self._segmented.set_active(game)
        self._initialized_expansion = False  # re-read expand state for new game
        self._build_cards()
        self.refresh_theme()

    # ── Toggle ─────────────────────────────────────────────────────────────

    def _toggle(self, index):
        entry = self._entries[index]
        expanded = not entry["expanded"]
        entry["expanded"] = expanded
        entry["card"].set_expanded(expanded, animate=True)

        if self.settings_manager:
            key = f"keymap_expanded_states_{self._active_game}"
            expanded_list = [e["index"] for e in self._entries if e["expanded"]]
            self.settings_manager.set(key, expanded_list)

    # ── Callbacks ──────────────────────────────────────────────────────────

    def _on_name_changed(self, index, name):
        self.keymap_manager.update_set_name(self._active_game, index, name)

    def _refresh_default_conflict_markers(self):
        """Recompute conflicts in this game's Default set and paint affected fields red."""
        if not self._entries:
            return
        default_entry = self._entries[0]
        card = default_entry["card"]
        has, pairs = self.keymap_manager.has_conflicts(self._active_game, 0)
        conflicting_actions: set[str] = set()
        for a, b in pairs:
            conflicting_actions.add(a)
            conflicting_actions.add(b)
        for action in logical_actions.actions_for(self._active_game):
            field = card.findChild(MovementKeyField, f"key_field_{action}")
            if field is None:
                continue
            in_conflict = action in conflicting_actions
            field.setProperty("conflict", "true" if in_conflict else "false")
            field.style().unpolish(field)
            field.style().polish(field)
            if in_conflict:
                others = set()
                for x, y in pairs:
                    if x == action:
                        others.add(y)
                    elif y == action:
                        others.add(x)
                pretty = ", ".join(ACTION_LABELS.get(o, o.title()) for o in sorted(others))
                field.setToolTip(f"Conflicts with: {pretty}")
            else:
                field.setToolTip("")

    def _on_key_changed(self, set_index, action, key):
        self.keymap_manager.update_set_key(self._active_game, set_index, action, key)
        self._refresh_default_conflict_markers()

    def _on_add_set(self):
        self.keymap_manager.add_set(self._active_game)
        self._build_cards()
        self.refresh_theme()

    def _on_delete_set(self, index):
        self.keymap_manager.delete_set(self._active_game, index)
        self._build_cards()
        self.refresh_theme()

    def _on_detect_settings(self):
        if self._active_game == "ttr":
            self._on_detect_ttr_settings()
        else:
            self._on_detect_cc_settings()

    def _on_detect_ttr_settings(self):
        from utils.ttr_settings import locate_settings_file, parse_ttr_settings, apply_ttr_controls_to_set
        from services.ttr_login_service import find_engine_path

        engine_path = None
        if self.settings_manager:
            engine_path = self.settings_manager.get("ttr_engine_dir", "")
        if not engine_path or not os.path.exists(engine_path):
            engine_path = find_engine_path()

        path = locate_settings_file(engine_dir=engine_path)
        if not path:
            print("[KeymapTab] Could not find TTR settings.json")
            return

        try:
            settings = parse_ttr_settings(path)
        except Exception as e:
            print(f"[KeymapTab] Failed to parse TTR settings.json: {e}")
            return

        updates = apply_ttr_controls_to_set(self.keymap_manager, 0, settings.controls)
        if updates > 0:
            self._build_cards()
            self.refresh_theme()
            print(f"[KeymapTab] Detected {updates} TTR settings from {path}")

    def _on_detect_cc_settings(self):
        from utils.cc_settings import locate_cc_preferences, parse_cc_preferences, apply_cc_controls_to_set
        try:
            from services.wine_runtimes import discover_cc_installs
        except Exception:
            discover_cc_installs = None

        install = None
        installs = []
        if discover_cc_installs is not None:
            try:
                installs = discover_cc_installs() or []
            except Exception as e:
                print(f"[KeymapTab] CC install discovery failed: {e}")

        # Prefer the install currently active in Settings if it's discoverable.
        cc_dir = self.settings_manager.get("cc_engine_dir", "") if self.settings_manager else ""
        if cc_dir:
            for cand in installs:
                exe = getattr(cand, "exe_path", None)
                if exe and os.path.dirname(exe) == cc_dir:
                    install = cand
                    break
        if install is None and installs:
            install = installs[0]
        if install is None:
            print("[KeymapTab] No CC install detected")
            return

        path = locate_cc_preferences(install)
        if not path:
            print("[KeymapTab] Could not find CC preferences.json")
            return

        try:
            settings = parse_cc_preferences(path)
        except Exception as e:
            print(f"[KeymapTab] Failed to parse CC preferences.json: {e}")
            return

        updates = apply_cc_controls_to_set(self.keymap_manager, 0, settings)
        if updates > 0:
            self._build_cards()
            self.refresh_theme()
            print(f"[KeymapTab] Detected {updates} CC settings from {path}")

    # ── Theme ──────────────────────────────────────────────────────────────

    def _c(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

    def refresh_theme(self):
        is_dark = resolve_theme(self.settings_manager) == "dark"
        c = self._c()

        self.setStyleSheet(f"background: {c['bg_app']}; color: {c['text_primary']};")
        self._scroll.setStyleSheet(f"background: {c['bg_app']};")
        self._scroll_widget.setStyleSheet(f"background: {c['bg_app']};")

        bar = getattr(self._scroll, "_auto_hide_scrollbar", None)
        if bar is not None:
            bar.set_theme(is_dark)

        # SetCard owns its background, stripe, badge, name, and delete-button
        # styling — those work against either theme by design (RGBA against
        # the underlying bg). The Default set's hint label uses a palette
        # token, so it must be re-styled here on theme change. The detect
        # and add-set buttons further below are re-styled the same way.
        hint_qss = (
            "font-size: 11px; "
            f"color: {c['text_muted']}; "
            "background: none; border: none; padding: 0 0 4px 0;"
        )
        for hint in self.findChildren(QLabel, "set_body_hint"):
            hint.setStyleSheet(hint_qss)
        for entry in self._entries:
            entry["card"].update()

        if hasattr(self, "_add_btn"):
            self._add_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {c['text_muted']};
                    border: 2px dashed {c['border_muted']};
                    border-radius: 10px; font-weight: 600; font-size: 12px;
                }}
                QPushButton:hover {{
                    color: {c['text_primary']};
                    border-color: {c['text_secondary']};
                    background: {c['bg_card_inner']};
                }}
            """)

        for btn in self.findChildren(QPushButton, "detect_btn"):
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {c['btn_bg']};
                    color: {c['text_primary']};
                    border: 1px solid {c['btn_border']};
                    border-radius: 6px; font-weight: bold; font-size: 11px;
                    padding: 0 12px;
                }}
                QPushButton:hover {{
                    background: {c['accent_blue_btn']};
                    color: {c['text_on_accent']};
                    border: 1px solid {c['accent_blue_btn_border']};
                }}
            """)
