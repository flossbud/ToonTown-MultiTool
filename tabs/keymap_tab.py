"""
Keymap Tab — UI for creating and editing movement sets.

Each set is two sibling widgets in the scroll layout:
  1. A ClickableHeader (fully-rounded colored bar, always static)
  2. An AnimatedBody (the gray key-mapping panel that slides open/closed)

The header never moves, resizes, or changes shape.  Only the body animates.
"""

from __future__ import annotations

import sys
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QLineEdit, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPainterPath, QBrush, QLinearGradient, QPen
from utils.theme_manager import resolve_theme, get_theme_colors, apply_card_shadow, get_set_color, make_trash_icon, get_set_card_styles
from utils.symbols import S
from utils.widgets import install_modern_scrollbar

from utils import logical_actions

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


# ── Clickable header (hover highlight, always fully rounded) ───────────────


class ClickableHeader(QFrame):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._hover:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 22))
            p.drawRoundedRect(self.rect(), 10, 10)
            p.end()

    def mousePressEvent(self, event):
        child = self.childAt(event.pos())
        if child and not isinstance(child, QLabel):
            return super().mousePressEvent(event)
        self.clicked.emit()


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

    def __init__(self, index: int, set_data: dict, parent=None):
        super().__init__(parent)
        self.index = index
        self.set_data = set_data
        self.setAttribute(Qt.WA_StyledBackground, True)
        # Reserve 4px at top so child widgets sit below the painted stripe.
        self.setContentsMargins(0, self.STRIPE_HEIGHT, 0, 0)
        self._styles = get_set_card_styles(index, is_dark=True)
        self.setMinimumHeight(self.STRIPE_HEIGHT + 50)

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


# ── Main Tab ───────────────────────────────────────────────────────────────


class KeymapTab(QWidget):
    def __init__(self, keymap_manager, settings_manager=None, parent=None):
        super().__init__(parent)
        self.keymap_manager = keymap_manager
        self.settings_manager = settings_manager
        self._entries = []  # list of {"header", "body", "chevron", "index", "expanded"}

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
            self._segmented = self._build_segmented_control()
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

        # Tear down old widgets
        for entry in self._entries:
            entry["header"].deleteLater()
            entry["body"].deleteLater()
        self._entries.clear()

        # Remove spacers and add button
        while self._scroll_layout.count():
            item = self._scroll_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        sets = self.keymap_manager.get_sets(self._active_game)
        for idx, s in enumerate(sets):
            if idx > 0:
                self._scroll_layout.addSpacing(12)

            expanded = prev_states.get(idx, False)

            header, body, chevron = self._make_pair(idx, s)
            self._scroll_layout.addWidget(header)
            self._scroll_layout.addSpacing(4)
            self._scroll_layout.addWidget(body)

            if not expanded:
                body.setVisible(False)
                chevron.setText(S("▶", ">"))

            self._entries.append({
                "header": header, "body": body, "chevron": chevron,
                "index": idx, "expanded": expanded,
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

    def _make_pair(self, index, set_data):
        """Return (header, body, chevron) as independent widgets."""
        bg, text = get_set_color(index)

        # ── Header ─────────────────────────────────────────────────────
        header = ClickableHeader()
        header.setObjectName("card_header_bar")
        header.setMinimumHeight(28)
        header.setCursor(Qt.PointingHandCursor)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.setSpacing(10)

        chevron = QLabel(S("▼", "v"))
        chevron.setObjectName("chevron")
        chevron.setFixedWidth(18)
        chevron.setAlignment(Qt.AlignCenter)
        chevron.setStyleSheet(
            f"font-size: 14px; color: rgba(255,255,255,0.6); background: none; border: none;"
        )
        hl.addWidget(chevron)

        badge = QLabel(f"SET {index + 1}")
        badge.setFixedHeight(20)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"""
            QLabel {{
                background: rgba(255,255,255,0.25); color: {text};
                font-size: 9px; font-weight: bold;
                padding: 2px 8px; border-radius: 4px; border: none;
            }}
        """)
        hl.addWidget(badge)

        if index == 0:
            title = QLabel("Default")
            title.setStyleSheet(
                f"font-size: 14px; font-weight: bold; color: {text}; background: none; border: none;"
            )
            hl.addWidget(title)
        else:
            name_edit = QLineEdit(set_data.get("name", f"Set {index + 1}"))
            name_edit.setObjectName("card_name_edit")
            name_edit.setFixedHeight(28)
            name_edit.setStyleSheet(f"""
                QLineEdit {{
                    background: transparent; color: {text};
                    border: none; border-radius: 0;
                    padding: 2px 4px; font-size: 14px; font-weight: bold;
                }}
                QLineEdit:focus {{
                    border-bottom: 1px solid rgba(255,255,255,0.5);
                    background: rgba(255,255,255,0.08);
                }}
            """)

            def _resize_to_text(w=name_edit):
                fm = w.fontMetrics()
                text_w = fm.horizontalAdvance(w.text() or "W") + 20  # padding
                w.setFixedWidth(max(40, min(text_w, 180)))

            def _on_finish(idx=index, w=name_edit):
                t = w.text().strip()
                if not t:
                    t = self.keymap_manager.next_default_name(self._active_game, exclude_index=idx)
                    w.setText(t)
                self._on_name_changed(idx, t)
                _resize_to_text(w)

            name_edit.textChanged.connect(lambda _, w=name_edit: _resize_to_text(w))
            name_edit.editingFinished.connect(_on_finish)
            _resize_to_text()
            hl.addWidget(name_edit)

        hl.addStretch()

        if index > 0:
            del_btn = QPushButton()
            del_btn.setFixedSize(32, 32)
            del_btn.setIcon(make_trash_icon(20, QColor(text)))
            del_btn.setToolTip("Delete this movement set")
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255,255,255,0.08);
                    border: 1px solid rgba(255,255,255,0.12);
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background: rgba(0,0,0,0.25);
                    border: 1px solid rgba(255,255,255,0.25);
                }}
            """)
            del_btn.clicked.connect(lambda _, idx=index: self._on_delete_set(idx))
            hl.addWidget(del_btn)

        header.setStyleSheet(f"""
            QFrame#card_header_bar {{
                background: {bg};
                border-radius: 10px;
                border: none;
            }}
        """)

        # ── Body ───────────────────────────────────────────────────────
        body = AnimatedBody()
        body.setObjectName("card_body")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(12, 12, 12, 12)
        bl.setSpacing(8)

        if index == 0:
            hint = QLabel("These keys are what is sent to all game windows for input.\nMake sure these match with your in-game settings.")
            hint.setObjectName("body_hint")
            hint.setWordWrap(True)
            hint.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.45); background: none; border: none; padding: 0 0 4px 0;")
            bl.addWidget(hint)

        two_col = QHBoxLayout()
        two_col.setSpacing(20)

        def _make_key_row(action):
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(ACTION_LABELS.get(action, action.title()))
            lbl.setObjectName("direction_label")
            lbl.setFixedWidth(40)
            row.addWidget(lbl)
            field = MovementKeyField(set_data.get(action, ""))
            field.setObjectName(f"key_field_{action}")
            field.key_captured.connect(
                lambda key, idx=index, d=action: self._on_key_changed(idx, d, key)
            )
            row.addWidget(field)
            row.addStretch()
            return row

        actions = logical_actions.actions_for(self._active_game)
        move_col = QVBoxLayout()
        move_col.setSpacing(6)
        for action in actions:
            if action in ("forward", "reverse", "left", "right", "jump"):
                move_col.addLayout(_make_key_row(action))

        aux_col = QVBoxLayout()
        aux_col.setSpacing(6)
        for action in actions:
            if action in ("book", "gags", "tasks", "map", "sprint"):
                aux_col.addLayout(_make_key_row(action))
        aux_col.addStretch()

        two_col.addLayout(move_col)
        two_col.addLayout(aux_col)
        two_col.addStretch()
        bl.addLayout(two_col)

        if index == 0:
            label = "Detect TTR Settings" if self._active_game == "ttr" else "Detect CC Settings"
            detect_btn = QPushButton(f"{S('🔍 ', '')}{label}")
            detect_btn.setFixedHeight(30)
            detect_btn.setCursor(Qt.PointingHandCursor)
            detect_btn.setToolTip(
                "Read current settings from Toontown Rewritten configuration"
                if self._active_game == "ttr"
                else "Read current settings from Corporate Clash preferences"
            )
            detect_btn.setObjectName("detect_btn")
            detect_btn.clicked.connect(self._on_detect_settings)

            btn_row = QHBoxLayout()
            btn_row.addStretch()
            btn_row.addWidget(detect_btn)
            bl.addLayout(btn_row)

        # Connect header to toggle this entry
        header.clicked.connect(lambda idx=index: self._toggle(idx))

        return header, body, chevron

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

    def _build_segmented_control(self):
        from PySide6.QtWidgets import QPushButton, QHBoxLayout, QFrame
        wrap = QFrame()
        wrap.setObjectName("keymap_segmented_wrap")
        wrap.setFixedHeight(36)
        row = QHBoxLayout(wrap)
        row.setContentsMargins(24, 4, 24, 4)
        row.setSpacing(0)
        row.addStretch()
        self._seg_buttons: dict[str, QPushButton] = {}
        for game, label in (("ttr", "TTR"), ("cc", "CC")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFixedWidth(80)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _, g=game: self._on_segment_clicked(g))
            self._seg_buttons[game] = b
            row.addWidget(b)
        self._seg_buttons[self._active_game].setChecked(True)
        row.addStretch()
        return wrap

    def _on_segment_clicked(self, game: str):
        if game == self._active_game:
            self._seg_buttons[game].setChecked(True)
            return
        self._active_game = game
        for g, btn in self._seg_buttons.items():
            btn.setChecked(g == game)
        self._initialized_expansion = False  # re-read expand state for new game
        self._build_cards()
        self.refresh_theme()

    # ── Toggle ─────────────────────────────────────────────────────────────

    def _toggle(self, index):
        entry = self._entries[index]
        expanded = not entry["expanded"]
        entry["expanded"] = expanded

        entry["chevron"].setText(S("▼", "v") if expanded else S("▶", ">"))

        if expanded:
            entry["body"].expand()
        else:
            entry["body"].collapse()

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
        body = default_entry["body"]
        has, pairs = self.keymap_manager.has_conflicts(self._active_game, 0)
        conflicting_actions: set[str] = set()
        for a, b in pairs:
            conflicting_actions.add(a)
            conflicting_actions.add(b)
        for action in logical_actions.actions_for(self._active_game):
            field = body.findChild(MovementKeyField, f"key_field_{action}")
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

        for entry in self._entries:
            idx = entry["index"]
            set_bg, _ = get_set_color(idx)
            body = entry["body"]
            expanded = entry["expanded"]

            # Header is always fully rounded — style set at creation, no change needed

            # Body
            if not expanded:
                body.setVisible(False)
            body.setStyleSheet(f"""
                AnimatedBody {{
                    background: {c['bg_card_inner']};
                    border: 1px solid {c['border_muted']};
                    border-radius: 10px;
                }}
            """)

            for lbl in body.findChildren(QLabel, "direction_label"):
                lbl.setStyleSheet(
                    f"font-size: 12px; font-weight: 600; color: {c['text_secondary']};"
                    f" background: none; border: none;"
                )

            for field in body.findChildren(MovementKeyField):
                field.setStyleSheet(f"""
                    QLineEdit {{
                        background: {c['bg_input']};
                        color: {c['text_primary']};
                        border: 1px solid {c['border_input']};
                        border-radius: 6px;
                        font-size: 12px; font-weight: 600;
                    }}
                    QLineEdit:focus {{
                        border: 1px solid {set_bg};
                    }}
                    QLineEdit[awaiting="true"] {{
                        background: {set_bg}18;
                        border: 1px solid {set_bg};
                        color: {c['text_muted']};
                    }}
                    QLineEdit[conflict="true"] {{
                        border: 1px solid #d04040;
                        background: rgba(208, 64, 64, 0.10);
                    }}
                """)

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

        # Segmented control (visible only when both games are detected)
        if getattr(self, "_segmented", None) is not None:
            self._segmented.setStyleSheet(f"""
                QFrame#keymap_segmented_wrap {{
                    background: transparent;
                    border: none;
                }}
                QFrame#keymap_segmented_wrap QPushButton {{
                    background: {c['bg_card_inner']};
                    color: {c['text_secondary']};
                    border: 1px solid {c['border_muted']};
                    border-radius: 0;
                    font-weight: 600;
                    font-size: 12px;
                    padding: 4px 0;
                }}
                QFrame#keymap_segmented_wrap QPushButton:first-child {{
                    border-top-left-radius: 8px;
                    border-bottom-left-radius: 8px;
                    border-right: none;
                }}
                QFrame#keymap_segmented_wrap QPushButton:last-child {{
                    border-top-right-radius: 8px;
                    border-bottom-right-radius: 8px;
                }}
                QFrame#keymap_segmented_wrap QPushButton:hover {{
                    background: {c['bg_input']};
                    color: {c['text_primary']};
                }}
                QFrame#keymap_segmented_wrap QPushButton:checked {{
                    background: {c['accent_blue_btn']};
                    color: {c['text_on_accent']};
                    border-color: {c['accent_blue_btn_border']};
                }}
            """)
