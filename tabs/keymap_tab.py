"""
Keysets Tab — UI for creating and editing per-game movement sets.

Each set is one SetCard(QFrame) that uses token-driven QSS for its chrome
(flat bg_card fill, 1 px border_card on L/R/B, 2 px top stripe in the set's
identity color, 10 px radius), and owns its header (badge + name + chevron +
delete) and a _BodyClip-wrapped key grid internally. The active game is
selected via an icon-only _GameSubRail when both TTR and CC are detected.
"""

from __future__ import annotations

import sys
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QLineEdit, QSizePolicy, QStackedWidget,
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QSize, QPointF, Property, QRectF
from PySide6.QtGui import QColor, QPainter, QIcon, QPixmap, QPolygonF
from utils.theme_manager import resolve_theme, get_theme_colors, get_set_color, make_trash_icon
from utils.symbols import S
from utils.widgets import install_modern_scrollbar
from utils.motion import push_slide_pages

from utils import logical_actions

_GAME_INDEX = {"ttr": 0, "cc": 1}
"""Stack page index per game. TTR sits on the left page, CC on the right,
so push_slide_pages with axis='h' naturally slides TTR out left on a
TTR -> CC switch."""


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
        self.setCursor(Qt.PointingHandCursor)
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


# ── Clipping viewport for body content ────────────────────────────────────


class _BodyClip(QWidget):
    """Clipping viewport for a SetCard's body content.

    Holds a content widget at full natural geometry at all times, and
    exposes a content_height Qt Property that clamps the clip's effective
    height. Only the top content_height pixels of the content widget are
    visible. Modeled on tabs/settings_tab.py:_CollapsibleContentClip;
    eliminates the overshoot bug that AnimatedBody had from animating
    maximumHeight while the content's sizeHint was drifting underneath.
    """

    expand_finished = Signal()
    collapse_finished = Signal()

    DURATION_MS = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self._content: QWidget | None = None
        self._animated_height: int = 0
        self._forced_height: int | None = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent; border: none;")
        self._anim = QPropertyAnimation(self, b"content_height")
        self._anim.setDuration(self.DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def set_content_widget(self, widget: QWidget) -> None:
        """Parent the body content widget and lay it out at full natural size."""
        self._content = widget
        widget.setParent(self)
        self._sync_content_geometry()

    def natural_height(self) -> int:
        """Return the content widget's layout minimumSize().height(), or 0."""
        if self._content is None or self._content.layout() is None:
            return 0
        return self._content.layout().minimumSize().height()

    def sizeHint(self) -> QSize:
        # Propagate the content widget's natural width so the SetCard's
        # own sizeHint (max of header and body widths) reflects what the
        # body needs. Without this, _BodyClip reported width=0 and the
        # scroll widget's clamp_centered sized everything to the header
        # width alone - leaving the two-column key grid no room and
        # spilling chips past the card's right edge.
        width = self._content.sizeHint().width() if self._content is not None else 0
        return QSize(width, self._height_hint())

    def minimumSizeHint(self) -> QSize:
        width = self._content.minimumSizeHint().width() if self._content is not None else 0
        return QSize(width, self._height_hint())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_content_geometry()

    def _height_hint(self) -> int:
        if self._forced_height is not None:
            return self._forced_height
        return self.natural_height()

    def _sync_content_geometry(self) -> None:
        if self._content is None:
            return
        # Lay the content out at full natural size, regardless of how much
        # the clip is currently showing. The clip's own size limits how
        # much of the content is actually visible.
        height = max(self.natural_height(), self.height(), self._height_hint())
        self._content.setGeometry(0, 0, self.width(), height)

    def _set_forced_height(self, height: int) -> None:
        self._forced_height = max(0, int(height))
        self.setMinimumHeight(self._forced_height)
        self.setMaximumHeight(self._forced_height)
        self._sync_content_geometry()
        self.updateGeometry()

    def _release_forced_height(self) -> None:
        self._forced_height = None
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self._sync_content_geometry()
        self.updateGeometry()

    def _get_content_height(self) -> int:
        return self._animated_height

    def _set_content_height(self, value: int) -> None:
        self._animated_height = max(0, int(value))
        self._set_forced_height(self._animated_height)

    content_height = Property(int, _get_content_height, _set_content_height)

    def _detach_finished_handlers(self) -> None:
        """Disconnect both expand and collapse finished handlers from the
        animation's finished signal. Uses slot-specific disconnect so a
        fresh _BodyClip (no handler connected yet) doesn't emit the spurious
        'Failed to disconnect (None)' RuntimeWarning that the no-arg
        .disconnect() emits."""
        for handler in (self._on_expand_finished, self._on_collapse_finished):
            try:
                self._anim.finished.disconnect(handler)
            except (RuntimeError, TypeError):
                pass

    def show_instant(self) -> None:
        """Snap the clip to full natural height without animating.
        Used for restoring persisted expand state on first render."""
        if self._content is None:
            return
        # Stop any in-flight animation so its tick can't override our snap.
        self._anim.stop()
        self._content.setVisible(True)
        target = self.natural_height()
        self._animated_height = target
        self._release_forced_height()

    def hide_instant(self) -> None:
        """Snap the clip to zero height without animating."""
        # Stop any in-flight animation so its tick can't override our snap.
        self._anim.stop()
        self._animated_height = 0
        self._set_forced_height(0)
        if self._content is not None:
            self._content.setVisible(False)

    def expand(self) -> None:
        """Animate from the current content_height to natural_height.

        If reduced-motion is active OR the test-only duration scale is 0,
        snap to the target without animating.
        """
        if self._content is None:
            return
        self._content.setVisible(True)
        target = self.natural_height()
        import utils.motion as motion
        scaled_duration = self.DURATION_MS * motion._TEST_DURATION_SCALE
        if motion.is_reduced() or scaled_duration == 0:
            self._anim.stop()
            self._animated_height = target
            self._release_forced_height()
            self.expand_finished.emit()
            return
        self._anim.stop()
        self._anim.setStartValue(self._animated_height)
        self._anim.setEndValue(target)
        self._detach_finished_handlers()
        self._anim.finished.connect(self._on_expand_finished)
        self._anim.start()

    def collapse(self) -> None:
        """Animate from the current content_height to 0.

        Reduced-motion path snaps to 0 without animating.
        """
        import utils.motion as motion
        scaled_duration = self.DURATION_MS * motion._TEST_DURATION_SCALE
        if motion.is_reduced() or scaled_duration == 0:
            self._anim.stop()
            self._animated_height = 0
            self._set_forced_height(0)
            if self._content is not None:
                self._content.setVisible(False)
            self.collapse_finished.emit()
            return
        self._anim.stop()
        self._anim.setStartValue(self._animated_height)
        self._anim.setEndValue(0)
        self._detach_finished_handlers()
        self._anim.finished.connect(self._on_collapse_finished)
        self._anim.start()

    def _on_expand_finished(self) -> None:
        # Release the height clamp so the body can settle to whatever
        # natural height the layout produces post-animation.
        self._release_forced_height()
        self.expand_finished.emit()

    def _on_collapse_finished(self) -> None:
        if self._content is not None:
            self._content.setVisible(False)
        self.collapse_finished.emit()


# ── Chevron arrow (vector-painted, font-independent) ─────────────────────


class _ChevronArrow(QWidget):
    """Small vector-painted chevron arrow for expand/collapse indication.

    Painted via QPainter so it doesn't depend on the system font having BMP
    triangle glyphs. The previous QLabel-text approach was vulnerable to
    fonts that render missing glyphs as a 'tofu' box, which `_can_render`
    can't reliably detect.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._color = QColor(255, 255, 255, 220)
        self.setFixedSize(14, 14)

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self.update()

    def setColor(self, color: QColor) -> None:
        self._color = color
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        r = self.rect()
        cx, cy = r.width() / 2.0, r.height() / 2.0
        if self._expanded:
            # Down-pointing triangle.
            poly = QPolygonF([
                QPointF(cx - 4.5, cy - 2.5),
                QPointF(cx + 4.5, cy - 2.5),
                QPointF(cx, cy + 3.5),
            ])
        else:
            # Right-pointing triangle.
            poly = QPolygonF([
                QPointF(cx - 2.5, cy - 4.5),
                QPointF(cx - 2.5, cy + 4.5),
                QPointF(cx + 3.5, cy),
            ])
        p.drawPolygon(poly)
        p.end()


# ── SetCard widget ─────────────────────────────────────────────────────────


class SetCard(QFrame):
    """One movement set rendered as a single card. Token-driven QSS provides
    the card surface (flat bg_card fill, 1 px border_card on L/R/B, 2 px top
    stripe in the set's identity color, 10 px radius). Owns the body
    (_BodyClip) and the header row internally; consumers wire signals
    instead of poking widget internals.
    """

    toggle_requested = Signal()
    name_changed     = Signal(str)
    delete_requested = Signal()
    key_changed       = Signal(str, str)   # (action_name, captured_key)
    detect_requested  = Signal()

    def __init__(self, index: int, set_data: dict, active_game: str = "ttr", is_dark: bool = True, parent=None):
        super().__init__(parent)
        self.index = index
        self.set_data = set_data
        self.setObjectName("set_card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._is_dark = is_dark
        self._set_bg, self._set_text = get_set_color(index)
        self._header = None  # set before installEventFilter so eventFilter is safe
        self._del_btn = None  # set in __init__ for alternate sets; stays None for the default set

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header row (badge + name + chevron + [delete]) ──────────
        header = QFrame()
        header.setObjectName("set_card_header")
        header.setCursor(Qt.PointingHandCursor)
        # Transparent initial state; _apply_chrome will set the final header QSS.
        header.setStyleSheet("QFrame#set_card_header { background: transparent; border: none; }")
        header.installEventFilter(self)  # forwards clicks to mousePressEvent
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 12, 14, 12)
        hl.setSpacing(10)

        badge = QLabel(f"SET {index + 1}")
        badge.setObjectName("set_card_badge")
        # QSS applied via _apply_chrome.
        self._badge = badge
        badge.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
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
        hl.addWidget(name_widget, 1)

        self._chevron = _ChevronArrow()
        hl.addWidget(self._chevron)

        if index > 0:
            del_btn = QPushButton()
            del_btn.setObjectName("set_card_delete")
            del_btn.setFixedSize(28, 28)
            del_btn.setToolTip("Delete this movement set")
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.setIcon(make_trash_icon(16, QColor("#888888")))
            # QSS applied via _apply_chrome.
            del_btn.clicked.connect(self.delete_requested.emit)
            hl.addWidget(del_btn)
            self._del_btn = del_btn

        outer.addWidget(header)
        # Lock the header's height to its natural sizeHint AFTER it's been
        # laid out (children added + parent layout assigned). Without this,
        # Qt redistributes vertical space among children when the card's
        # total height fluctuates during body animations, briefly stretching
        # the header (and the SET # badge inside it) before snapping back.
        header.setFixedHeight(header.sizeHint().height())
        self._header = header
        self._name_widget = name_widget

        # ── Body content widget (held inside _BodyClip for animation) ──
        self._active_game = active_game
        body_content = QWidget()
        body_content.setObjectName("set_card_body")
        body_content.setStyleSheet("QWidget#set_card_body { background: transparent; border: none; }")
        bl = QVBoxLayout(body_content)
        bl.setContentsMargins(14, 12, 14, 14)
        bl.setSpacing(8)

        if index == 0:
            hint = QLabel(
                "These keys are what is sent to all game windows for input.\n"
                "Make sure these match with your in-game settings."
            )
            hint.setObjectName("set_body_hint")
            hint.setWordWrap(True)
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
            lbl.setFixedWidth(72)
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

        self._body = _BodyClip()
        self._body.set_content_widget(body_content)
        outer.addWidget(self._body)
        self.setMinimumHeight(header.sizeHint().height())
        self._apply_chrome()

    def _apply_chrome(self) -> None:
        """Build and apply token-driven QSS for the card surface, header,
        badge, name, chevron, delete button, and contained MovementKeyFields.
        Called once on construction and on every theme switch via
        `set_theme(is_dark)`."""
        c = get_theme_colors(self._is_dark)
        # ── Card surface ──────────────────────────────────────────
        self.setStyleSheet(
            "QFrame#set_card {"
            f" background: {c['bg_card']};"
            f" border-left: 1px solid {c['border_card']};"
            f" border-right: 1px solid {c['border_card']};"
            f" border-bottom: 1px solid {c['border_card']};"
            f" border-top: 2px solid {self._set_bg};"
            " border-radius: 10px;"
            "}"
        )
        # ── Header divider ────────────────────────────────────────
        if self._header is not None:
            self._header.setStyleSheet(
                "QFrame#set_card_header {"
                " background: transparent;"
                f" border-bottom: 1px solid {c['border_muted']};"
                "}"
            )
        # ── Badge ─────────────────────────────────────────────────
        self._badge.setStyleSheet(
            "QLabel#set_card_badge {"
            f" background: {self._set_bg};"
            f" color: {self._set_text};"
            " font-size: 11px; font-weight: 700;"
            " border-radius: 8px; padding: 4px 8px;"
            "}"
        )
        # ── Name (QLabel for default set, QLineEdit for others) ───
        name_qss = (
            f"color: {c['text_primary']};"
            " font-size: 15px; font-weight: 700;"
            " background: transparent;"
        )
        if self.index == 0:
            self._name_widget.setStyleSheet(
                f"QLabel#set_name_label {{ {name_qss} }}"
            )
        else:
            self._name_widget.setStyleSheet(
                f"QLineEdit#set_name_edit {{ {name_qss} border: none; padding: 2px 4px; }}"
                f"QLineEdit#set_name_edit:focus {{"
                f" background: {c['bg_card_inner_hover']};"
                f" border: 1px solid {c['border_card']};"
                f" border-radius: 6px;"
                f"}}"
            )
        # ── Chevron color ─────────────────────────────────────────
        self._chevron.setColor(QColor(c['text_muted']))
        # ── Delete button (alternate sets only) ───────────────────
        if self._del_btn is not None:
            self._del_btn.setStyleSheet(
                "QPushButton#set_card_delete {"
                " background: transparent;"
                f" border: 1px solid {c['border_muted']};"
                " border-radius: 6px;"
                f" color: {c['text_muted']};"
                "}"
                "QPushButton#set_card_delete:hover {"
                f" background: {c['bg_card_inner_hover']};"
                f" border: 1px solid {c['border_card']};"
                f" color: {c['accent_red_border']};"
                "}"
            )
        # ── Default-set hint label ────────────────────────────────
        for hint in self.findChildren(QLabel, "set_body_hint"):
            hint.setStyleSheet(
                f"font-size: 11px; color: {c['text_muted']};"
                f" background: none; border: none; padding: 0 0 4px 0;"
            )
        # ── Direction labels (Forward / Reverse / Left / etc) ────
        direction_qss = (
            f"QLabel#direction_label {{"
            f" color: {c['text_secondary']};"
            f" font-size: 12px;"
            f" background: transparent;"
            f"}}"
        )
        for lbl in self.findChildren(QLabel, "direction_label"):
            lbl.setStyleSheet(direction_qss)
        # ── MovementKeyFields (default + awaiting per-set color) ──
        field_qss = (
            f"QLineEdit {{"
            f" background: transparent;"
            f" border: 1px solid {c['border_muted']};"
            f" border-radius: 6px;"
            f" color: {c['text_primary']};"
            f" padding: 0 8px;"
            f" font-weight: 600; font-size: 11.5px;"
            f"}}"
            f"QLineEdit:hover {{"
            f" background: {c['bg_card_inner_hover']};"
            f" border: 1px solid {c['border_card']};"
            f"}}"
            f"QLineEdit[awaiting=\"true\"] {{"
            f" background: {c['bg_card_inner_hover']};"
            f" border: 1px solid {self._set_bg};"
            f" color: {self._set_bg};"
            f"}}"
            f"QLineEdit[conflict=\"true\"] {{"
            f" border: 1px solid {c['accent_red_border']};"
            f" background: rgba(208, 64, 64, 0.10);"
            f"}}"
        )
        for field in self.findChildren(MovementKeyField):
            field.setStyleSheet(field_qss)

    def set_theme(self, is_dark: bool):
        """Update which theme this card paints against. Re-applies QSS so the
        chrome retints. Idempotent on no-op."""
        if is_dark == self._is_dark:
            return
        self._is_dark = is_dark
        self._apply_chrome()

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

    def set_expanded(self, expanded: bool, *, animate: bool = True):
        self._chevron.set_expanded(expanded)
        if expanded:
            if animate:
                self._body.expand()
            else:
                self._body.show_instant()
        else:
            if animate:
                self._body.collapse()
            else:
                self._body.hide_instant()


# -- TTR / CC game sub-rail ────────────────────────────────────────────────


class _GameSubRail(QFrame):
    """TTR/CC switch as a small chip rail.

    Built from the same primitives the top app chip_rail uses:
    `ChipButton` instances for the two icons + a `PillIndicator` overlay
    that slides between them on switch and retints its border per game
    accent (TTR blue, CC orange).
    """

    game_changed = Signal(str)

    _BORDER_FOR = {
        "ttr": "game_pill_ttr",   # theme token, resolved in _apply_pill_color
        "cc":  "game_pill_cc",
    }

    def __init__(self, active_game: str, parent=None):
        super().__init__(parent)
        self.setObjectName("game_sub_rail")
        self._active = active_game

        from utils.widgets.chip_button import ChipButton
        from utils.widgets.pill_indicator import PillIndicator
        from PySide6.QtCore import QEvent, QObject

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(0)
        outer.addStretch()

        bar = QFrame(self)
        bar.setObjectName("game_sub_rail_bar")
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(4, 4, 4, 4)
        bar_lay.setSpacing(4)

        # Pill overlay parented to the bar (so its coordinates match the
        # chips inside the bar, not the outer stretched layout).
        self._pill = PillIndicator(bar)
        self._pill.lower()

        self._buttons: dict[str, ChipButton] = {}
        for game in ("ttr", "cc"):
            chip = ChipButton(bar)
            chip.setObjectName(f"game_sub_rail_chip_{game}")
            chip.setToolButtonStyle(Qt.ToolButtonIconOnly)
            chip.setMinimumSize(QSize(56, 40))
            chip.setMaximumSize(QSize(56, 40))
            chip.setCheckable(True)
            chip.setCursor(Qt.PointingHandCursor)
            pm = QPixmap(_asset_path(f"{game}.png"))
            if not pm.isNull():
                chip.setIcon(QIcon(pm))
                chip.setIconSize(QSize(28, 28))
            # Transparent background so the PillIndicator (parented to `bar`
            # and lowered to the back) is visible through the chip rect.
            # Matches main.py._apply_chip_styles' transparent-chip recipe.
            chip.setStyleSheet(
                f"QToolButton#{chip.objectName()} {{"
                f" background: transparent;"
                f" border: 1px solid transparent;"
                f" border-radius: 8px;"
                f"}}"
                f"QToolButton#{chip.objectName()}:focus {{"
                f" outline: none;"
                f"}}"
            )
            chip.clicked.connect(lambda _checked, g=game: self._on_click(g))
            bar_lay.addWidget(chip)
            self._buttons[game] = chip

        # Resize filter so the pill matches the bar size and snaps onto the
        # active chip whenever layout changes. Same pattern main.py uses for
        # the top chip rail.
        pill_ref = self._pill
        outer_self = self

        class _RailResizeFilter(QObject):
            def eventFilter(self_, watched, event):  # noqa: N805
                if event.type() == QEvent.Type.Resize:
                    pill_ref.resize(watched.size())
                    active_btn = outer_self._buttons.get(outer_self._active)
                    if active_btn is not None and not active_btn.geometry().isEmpty():
                        pill_ref.cancel_animation()
                        pill_ref.set_pill_rect(QRectF(active_btn.geometry()))
                return False

        self._resize_filter = _RailResizeFilter(bar)
        bar.installEventFilter(self._resize_filter)

        outer.addWidget(bar)
        outer.addStretch()

        self._buttons[self._active].setChecked(True)
        self._apply_pill_color()

    def _on_click(self, game: str) -> None:
        if game == self._active:
            # Re-check it (click toggled it off).
            self._buttons[game].setChecked(True)
            return
        self.set_active(game)
        self.game_changed.emit(game)

    def set_active(self, game: str) -> None:
        if game == self._active:
            return
        self._active = game
        for g, btn in self._buttons.items():
            btn.setChecked(g == game)
        target = self._buttons[game].geometry()
        if not target.isEmpty():
            self._pill.slide_to(QRectF(target))
        self._apply_pill_color()

    def _apply_pill_color(self) -> None:
        from utils.theme_manager import get_theme_colors
        # Theme accessor lives at module level; using the dark default here is
        # safe because the pill color is set per-active-game from the theme
        # tokens (game_pill_ttr / game_pill_cc) which are identical in both
        # light and dark themes (same brand hex).
        c = get_theme_colors(True)
        self._pill.set_colors(border_hex=c[self._BORDER_FOR[self._active]])


# ── Main Tab ───────────────────────────────────────────────────────────────


class KeymapTab(QWidget):
    def __init__(self, keymap_manager, settings_manager=None,
                 credentials_manager=None, parent=None):
        super().__init__(parent)
        self.keymap_manager = keymap_manager
        self.settings_manager = settings_manager
        self.credentials_manager = credentials_manager

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

        # One QStackedWidget with one page per game. push_slide_pages
        # animates between pages using grabbed pixmaps so no layout
        # reflow happens during the slide.
        self._game_stack = QStackedWidget()

        # Per-game page widgets, layouts, and bookkeeping. Built later
        # via _build_page_for_game.
        self._pages: dict[str, QWidget] = {}
        self._page_layouts: dict[str, QVBoxLayout] = {}
        self._add_btns: dict[str, QPushButton] = {}
        self._entries_by_game: dict[str, list] = {"ttr": [], "cc": []}
        self._expansion_initialized_for: set = set()

        for game in ("ttr", "cc"):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(24, 20, 24, 20)
            page_layout.setSpacing(0)
            page_layout.setAlignment(Qt.AlignTop)
            self._game_stack.insertWidget(_GAME_INDEX[game], page)
            self._pages[game] = page
            self._page_layouts[game] = page_layout

        clamp_centered(scroll_inner_layout, self._game_stack, 720)

        self._scroll.setWidget(scroll_inner)
        outer.addWidget(self._scroll)

        # Active game starts at the first member of _active_games. When both
        # are active, default to TTR (matches the pre-existing behavior).
        active = self._active_games()
        if active == {"cc"}:
            self._active_game: str = "cc"
        else:
            self._active_game: str = "ttr"

        # Sub-rail lives in `outer` ABOVE the scroll area. Built lazily on
        # first 2-active transition; toggled via setVisible thereafter so
        # 2 -> 1 -> 2 sequences don't rebuild it.
        self._segmented = None

        # Cache the prior active set + sub-rail visibility for the no-change
        # short-circuit in _refresh_visibility.
        self._prev_active_games: set = set()
        self._prev_segmented_visible: bool = False

        # Build both pages eagerly so the animation source-pixmaps are
        # always available and the inactive page doesn't flash on first
        # switch.
        self._build_cards_for_game("ttr")
        self._build_cards_for_game("cc")

        # Initial stack page is the active game.
        self._game_stack.setCurrentIndex(_GAME_INDEX[self._active_game])

        # Build / show the sub-rail iff both games are active right now.
        # Subscribe to settings + credentials changes for live updates.
        self._refresh_visibility()
        if self.settings_manager is not None:
            self.settings_manager.on_change(self._on_settings_change)
        if self.credentials_manager is not None:
            self.credentials_manager.on_change(self._refresh_visibility)

        self.refresh_theme()

    # ── Build ──────────────────────────────────────────────────────────────

    @property
    def _entries(self) -> list:
        """Active game's entries list. Most read sites use this; writes
        target self._entries_by_game[game] directly so each callback is
        explicit about which game it touches."""
        return self._entries_by_game[self._active_game]

    def _build_cards_for_game(self, game: str) -> None:
        """Rebuild the card list (header + cards + add button + stretch)
        for one game's page. Idempotent: clears the page layout first.
        Targets self._page_layouts[game] and self._entries_by_game[game].
        Signal bindings carry the game name so cards on the inactive page
        still write to the correct game's data if invoked."""
        page_layout = self._page_layouts[game]

        # Read prior expand state (from settings on first build, from
        # in-memory entries on subsequent rebuilds).
        if game not in self._expansion_initialized_for:
            self._expansion_initialized_for.add(game)
            key = f"keymap_expanded_states_{game}"
            legacy = (
                self.settings_manager.get("keymap_expanded_states", None)
                if self.settings_manager else None
            )
            expanded_list = (
                self.settings_manager.get(key, legacy if legacy is not None else [0])
                if self.settings_manager else [0]
            )
            prev_states = {i: (i in expanded_list) for i in range(16)}
        else:
            prev_states = {
                entry["index"]: entry["expanded"]
                for entry in self._entries_by_game[game]
            }

        # Tear down existing cards + layout items.
        for entry in self._entries_by_game[game]:
            entry["card"].deleteLater()
        self._entries_by_game[game].clear()

        while page_layout.count():
            item = page_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        is_dark = resolve_theme(self.settings_manager) == "dark"
        c = get_theme_colors(is_dark)

        # ── Per-game header (label + divider) ──────────────────────────
        title = (
            "ToonTown Rewritten Keysets" if game == "ttr"
            else "Corporate Clash Keysets"
        )
        accent_token = "game_pill_ttr" if game == "ttr" else "game_pill_cc"
        header_label = QLabel(title)
        header_label.setObjectName(f"header_label_{game}")
        header_label.setStyleSheet(
            f"QLabel#header_label_{game} {{"
            f" font-size: 10px;"
            f" font-weight: 600;"
            f" color: {c[accent_token]};"
            f" background: transparent;"
            f" letter-spacing: 0.8px;"
            f" border: none;"
            f"}}"
        )
        page_layout.addWidget(header_label)

        header_divider = QFrame()
        header_divider.setObjectName(f"header_divider_{game}")
        header_divider.setFixedHeight(2)
        header_divider.setMaximumWidth(320)
        header_divider.setStyleSheet(
            f"QFrame#header_divider_{game} {{"
            f" background: {c[accent_token]};"
            f" border: none;"
            f" border-radius: 1px;"
            f"}}"
        )
        page_layout.addWidget(header_divider)
        page_layout.addSpacing(10)

        # ── SetCards ───────────────────────────────────────────────────
        sets = self.keymap_manager.get_sets(game)
        for idx, s in enumerate(sets):
            if idx > 0:
                page_layout.addSpacing(10)
            card = SetCard(index=idx, set_data=s, active_game=game,
                           is_dark=is_dark, parent=self._pages[game])
            card.toggle_requested.connect(
                lambda i=idx, g=game: self._toggle_for_game(g, i)
            )
            card.name_changed.connect(
                lambda name, i=idx, g=game: self._on_name_changed_for_game(g, i, name)
            )
            card.key_changed.connect(
                lambda action, key, i=idx, g=game: self._on_key_changed_for_game(g, i, action, key)
            )
            card.delete_requested.connect(
                lambda i=idx, g=game: self._on_delete_set_for_game(g, i)
            )
            card.detect_requested.connect(
                lambda g=game: self._on_detect_settings_for_game(g)
            )

            expanded = prev_states.get(idx, False)
            card.set_expanded(expanded, animate=False)

            page_layout.addWidget(card)
            self._entries_by_game[game].append({
                "card": card, "index": idx, "expanded": expanded,
            })

        page_layout.addSpacing(16)
        add_btn = QPushButton(f"{S('➕', '+')} Add Movement Set")
        add_btn.setObjectName(f"add_btn_{game}")
        add_btn.setMinimumHeight(28)
        add_btn.setMaximumWidth(260)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(lambda g=game: self._on_add_set_for_game(g))
        add_btn.setVisible(len(sets) < self.keymap_manager.MAX_SETS_PER_GAME)
        page_layout.addWidget(add_btn, alignment=Qt.AlignHCenter)
        page_layout.addStretch()
        self._add_btns[game] = add_btn

        # Refresh conflict markers only for the active game's page (cheap
        # and idempotent; safe to skip for inactive pages until they
        # become active).
        if game == self._active_game:
            self._refresh_default_conflict_markers()

    # ── Game detection + segmented control ────────────────────────────────

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

    def _has_accounts(self, game: str) -> bool:
        """True when credentials_manager reports at least one account for
        the given game. Returns False when no credentials_manager is wired
        (e.g., tests that don't pass one)."""
        if self.credentials_manager is None:
            return False
        return bool(self.credentials_manager.get_accounts_metadata(game=game))

    def _active_games(self) -> set:
        """The set of games to expose in the keysets tab. A game is active
        when its install is detected OR the user has any accounts for it.
        Drives sub-rail visibility via _refresh_visibility."""
        games = set()
        if self._ttr_detected() or self._has_accounts("ttr"):
            games.add("ttr")
        if self._cc_detected() or self._has_accounts("cc"):
            games.add("cc")
        return games

    def _on_segment_clicked(self, game: str):
        if game == self._active_game:
            return
        prev_idx = _GAME_INDEX[self._active_game]
        new_idx = _GAME_INDEX[game]
        self._active_game = game
        if self._segmented is not None:
            self._segmented.set_active(game)
        push_slide_pages(self._game_stack, prev_idx, new_idx, axis="h")
        self._refresh_default_conflict_markers()

    # ── Per-game callbacks ─────────────────────────────────────────────────

    def _toggle_for_game(self, game: str, index: int) -> None:
        entry = self._entries_by_game[game][index]
        expanded = not entry["expanded"]
        entry["expanded"] = expanded
        entry["card"].set_expanded(expanded, animate=True)
        if self.settings_manager:
            key = f"keymap_expanded_states_{game}"
            expanded_list = [
                e["index"] for e in self._entries_by_game[game] if e["expanded"]
            ]
            self.settings_manager.set(key, expanded_list)

    def _on_name_changed_for_game(self, game: str, index: int, name: str) -> None:
        self.keymap_manager.update_set_name(game, index, name)

    def _on_key_changed_for_game(self, game: str, set_index: int, action: str, key: str) -> None:
        self.keymap_manager.update_set_key(game, set_index, action, key)
        if game == self._active_game:
            self._refresh_default_conflict_markers()

    def _on_add_set_for_game(self, game: str) -> None:
        self.keymap_manager.add_set(game)
        self._build_cards_for_game(game)

    def _on_delete_set_for_game(self, game: str, index: int) -> None:
        self.keymap_manager.delete_set(game, index)
        self._build_cards_for_game(game)

    def _on_detect_settings_for_game(self, game: str) -> None:
        """Dispatch to the per-game detect routine. The existing
        _on_detect_settings read self._active_game; here the game arrives
        via the signal-binding-with-game-name lambda."""
        if game == "ttr":
            self._on_detect_ttr_settings()
        else:
            self._on_detect_cc_settings()

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
            self._build_cards_for_game("ttr")
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
            self._build_cards_for_game("cc")
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
        for game in ("ttr", "cc"):
            if game in self._pages:
                self._pages[game].setStyleSheet(f"background: {c['bg_app']};")

        bar = getattr(self._scroll, "_auto_hide_scrollbar", None)
        if bar is not None:
            bar.set_theme(is_dark)

        # SetCard._apply_chrome owns badge, name, hint, direction-label,
        # MovementKeyField, and delete-button QSS. Calling set_theme on each
        # card re-invokes _apply_chrome with the new is_dark value.
        for game in ("ttr", "cc"):
            for entry in self._entries_by_game[game]:
                entry["card"].set_theme(is_dark)

        # Per-game add buttons.
        add_btn_qss = f"""
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
        """
        for game in ("ttr", "cc"):
            btn = self._add_btns.get(game)
            if btn is not None:
                btn.setStyleSheet(add_btn_qss)

        # Per-game header banners (one per page, always present).
        for game in ("ttr", "cc"):
            accent_token = "game_pill_ttr" if game == "ttr" else "game_pill_cc"
            lbl = self.findChild(QLabel, f"header_label_{game}")
            if lbl is not None:
                lbl.setStyleSheet(
                    f"QLabel#header_label_{game} {{"
                    f" font-size: 10px;"
                    f" font-weight: 600;"
                    f" color: {c[accent_token]};"
                    f" background: transparent;"
                    f" letter-spacing: 0.8px;"
                    f" border: none;"
                    f"}}"
                )
            div = self.findChild(QFrame, f"header_divider_{game}")
            if div is not None:
                div.setStyleSheet(
                    f"QFrame#header_divider_{game} {{"
                    f" background: {c[accent_token]};"
                    f" border: none;"
                    f" border-radius: 1px;"
                    f"}}"
                )

        # Detect button hover accent is per-page (TTR=blue, CC=orange) so
        # the inactive page's detect button keeps its own game's tint.
        for game in ("ttr", "cc"):
            hover_accent = (
                c['accent_blue_btn'] if game == "ttr"
                else c['accent_orange_border']
            )
            for btn in self._pages[game].findChildren(QPushButton, "detect_btn"):
                btn.setStyleSheet(
                    "QPushButton#detect_btn {"
                    " background: transparent;"
                    f" border: 1px solid {c['border_muted']};"
                    f" color: {c['text_secondary']};"
                    " border-radius: 8px; padding: 0 14px;"
                    " font-weight: 600; font-size: 11px;"
                    "}"
                    "QPushButton#detect_btn:hover {"
                    f" background: {c['bg_card_inner_hover']};"
                    f" border: 1px solid {hover_accent};"
                    f" color: {hover_accent};"
                    "}"
                )

    # ── Visibility refresh ───────────────────────────────────────────────────

    def _refresh_visibility(self) -> None:
        """Recompute active games and update sub-rail visibility + current
        page. Called on construction, on settings_manager.on_change for
        engine-dir keys, and on credentials_manager.on_change.

        - Sub-rail is hide-don't-destroy: built lazily on first 2-active
          transition, toggled via setVisible thereafter.
        - If the current page is no longer in the active set, animate to
          the remaining game.
        - Short-circuits when nothing relevant changed (renames, etc).
        """
        active = self._active_games()
        want_subrail_visible = len(active) == 2

        # ── Build sub-rail lazily on first need ─────────────────────────
        if want_subrail_visible and self._segmented is None:
            self._segmented = _GameSubRail(self._active_game, parent=self)
            self._segmented.game_changed.connect(self._on_segment_clicked)
            self.layout().insertWidget(0, self._segmented)

        # ── Page-validity check ─────────────────────────────────────────
        # If current active game is no longer in `active`, pick the
        # remaining game. Only fires when active is non-empty AND current
        # is not in it (a game just became inactive).
        if active and self._active_game not in active:
            new_game = next(iter(active))
            prev_idx = _GAME_INDEX[self._active_game]
            new_idx = _GAME_INDEX[new_game]
            self._active_game = new_game
            if self._segmented is not None:
                self._segmented.set_active(new_game)
            push_slide_pages(self._game_stack, prev_idx, new_idx, axis="h")

        # ── No-change short-circuit ─────────────────────────────────────
        # Visibility hasn't changed AND active set is the same => done.
        if (active == self._prev_active_games
                and want_subrail_visible == self._prev_segmented_visible):
            return

        # ── Apply visibility ────────────────────────────────────────────
        if self._segmented is not None:
            self._segmented.setVisible(want_subrail_visible)

        # ── Update caches ───────────────────────────────────────────────
        self._prev_active_games = active
        self._prev_segmented_visible = want_subrail_visible

    def _on_settings_change(self, key: str, value) -> None:
        """Re-evaluate active games when an engine-dir setting changes."""
        if key in ("ttr_engine_dir", "cc_engine_dir"):
            self._refresh_visibility()
