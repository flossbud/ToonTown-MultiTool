"""
Keymap Tab — UI for creating and editing movement sets.

Each set is two sibling widgets in the scroll layout:
  1. A ClickableHeader (fully-rounded colored bar, always static)
  2. An AnimatedBody (the gray key-mapping panel that slides open/closed)

The header never moves, resizes, or changes shape.  Only the body animates.
"""

import sys

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QLineEdit, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter
from utils.theme_manager import resolve_theme, get_theme_colors, apply_card_shadow, get_set_color, make_trash_icon
from utils.symbols import S

DIRECTIONS = ("up", "left", "down", "right", "jump", "book", "gags", "tasks", "map")
DIRECTION_LABELS = {"up": "Up", "left": "Left", "down": "Down", "right": "Right", "jump": "Jump", "book": "Book", "gags": "Gags", "tasks": "Tasks", "map": "Map"}

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
        self.setFixedHeight(30)
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

        # Overlay scrollbar so it doesn't shrink content width
        self._scroll.setStyleSheet("""
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.15);
                border-radius: 3px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255,255,255,0.25);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)

        self._scroll_widget = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_widget)
        self._scroll_layout.setContentsMargins(24, 20, 30, 20)  # extra right margin for scrollbar overlay
        self._scroll_layout.setSpacing(0)
        self._scroll_layout.setAlignment(Qt.AlignTop)

        self._scroll.setWidget(self._scroll_widget)
        outer.addWidget(self._scroll)

        self._build_cards()
        self.refresh_theme()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build_cards(self):
        if not hasattr(self, "_initialized_expansion"):
            self._initialized_expansion = True
            expanded_list = self.settings_manager.get("keymap_expanded_states", [0]) if self.settings_manager else [0]
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

        sets = self.keymap_manager.get_sets()
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
        self._add_btn.setFixedHeight(38)
        self._add_btn.setMaximumWidth(260)
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.clicked.connect(self._on_add_set)
        self._add_btn.setVisible(len(sets) < self.keymap_manager.MAX_SETS)
        self._scroll_layout.addWidget(self._add_btn, alignment=Qt.AlignHCenter)
        self._scroll_layout.addStretch()

    def _make_pair(self, index, set_data):
        """Return (header, body, chevron) as independent widgets."""
        bg, text = get_set_color(index)

        # ── Header ─────────────────────────────────────────────────────
        header = ClickableHeader()
        header.setObjectName("card_header_bar")
        header.setFixedHeight(40)
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
                    t = self.keymap_manager.next_default_name(exclude_index=idx)
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

        def _make_key_row(direction):
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(DIRECTION_LABELS[direction])
            lbl.setObjectName("direction_label")
            lbl.setFixedWidth(40)
            row.addWidget(lbl)
            field = MovementKeyField(set_data.get(direction, ""))
            field.setObjectName(f"key_field_{direction}")
            field.key_captured.connect(
                lambda key, idx=index, d=direction: self._on_key_changed(idx, d, key)
            )
            row.addWidget(field)
            row.addStretch()
            return row

        move_col = QVBoxLayout()
        move_col.setSpacing(6)
        for direction in ("up", "left", "down", "right", "jump"):
            move_col.addLayout(_make_key_row(direction))

        aux_col = QVBoxLayout()
        aux_col.setSpacing(6)
        for direction in ("book", "gags", "tasks", "map"):
            aux_col.addLayout(_make_key_row(direction))
        aux_col.addStretch()

        two_col.addLayout(move_col)
        two_col.addLayout(aux_col)
        two_col.addStretch()
        bl.addLayout(two_col)

        if index == 0:
            detect_btn = QPushButton(f"{S('🔍 ', '')}Detect Game Settings")
            detect_btn.setFixedHeight(30)
            detect_btn.setCursor(Qt.PointingHandCursor)
            detect_btn.setToolTip("Read current settings from Toontown Rewritten configuration")
            detect_btn.setObjectName("detect_btn")
            detect_btn.clicked.connect(self._on_detect_settings)
            
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            btn_row.addWidget(detect_btn)
            bl.addLayout(btn_row)

        # Connect header to toggle this entry
        header.clicked.connect(lambda idx=index: self._toggle(idx))

        return header, body, chevron

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
            expanded_list = [e["index"] for e in self._entries if e["expanded"]]
            self.settings_manager.set("keymap_expanded_states", expanded_list)

    # ── Callbacks ──────────────────────────────────────────────────────────

    def _on_name_changed(self, index, name):
        self.keymap_manager.update_set_name(index, name)

    def _on_key_changed(self, set_index, direction, key):
        self.keymap_manager.update_set_key(set_index, direction, key)

    def _on_add_set(self):
        self.keymap_manager.add_set()
        self._build_cards()
        self.refresh_theme()

    def _on_delete_set(self, index):
        self.keymap_manager.delete_set(index)
        self._build_cards()
        self.refresh_theme()

    def _on_detect_settings(self):
        import os, json
        from services.ttr_login_service import find_engine_path
        
        engine_path = None
        if self.settings_manager:
            engine_path = self.settings_manager.get("ttr_engine_dir", "")
        if not engine_path or not os.path.exists(engine_path):
            engine_path = find_engine_path()
            
        settings_file = None
        if engine_path and os.path.exists(os.path.join(engine_path, "settings.json")):
            settings_file = os.path.join(engine_path, "settings.json")
        elif os.path.exists(os.path.expanduser("~/.var/app/com.toontownrewritten.Launcher/data/settings.json")):
            settings_file = os.path.expanduser("~/.var/app/com.toontownrewritten.Launcher/data/settings.json")
            
        if not settings_file:
            print("[KeymapTab] Could not find settings.json")
            return
            
        try:
            with open(settings_file, "r") as f:
                data = json.load(f)
                
            controls = data.get("controls", {})
            mapping = {
                "forward": "up",
                "reverse": "down",
                "left": "left",
                "right": "right",
                "jump": "jump",
                "stickerBook": "book",
                "showGags": "gags",
                "showTasks": "tasks",
                "showMap": "map"
            }
            
            ttr_to_keymap = {
                "shift": "Shift_L",
                "control": "Control_L",
                "alt": "Alt_L",
                "space": "space",
                "escape": "Escape",
                "enter": "Return",
                "tab": "Tab",
                "backspace": "BackSpace",
                "delete": "Delete",
                "up": "Up",
                "down": "Down",
                "left": "Left",
                "right": "Right"
            }
            
            updates = 0
            for ttr_key, my_dir in mapping.items():
                if ttr_key in controls:
                    val = controls[ttr_key]
                    parsed_val = ttr_to_keymap.get(val, val)
                    self.keymap_manager.update_set_key(0, my_dir, parsed_val)
                    updates += 1
                    
            if updates > 0:
                self._build_cards()
                self.refresh_theme()
                print(f"[KeymapTab] Detected {updates} settings from {settings_file}")
        except Exception as e:
            print(f"[KeymapTab] Failed to parse settings.json: {e}")

    # ── Theme ──────────────────────────────────────────────────────────────

    def _c(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

    def refresh_theme(self):
        c = self._c()

        self.setStyleSheet(f"background: {c['bg_app']}; color: {c['text_primary']};")
        self._scroll.setStyleSheet(f"background: {c['bg_app']};")
        self._scroll_widget.setStyleSheet(f"background: {c['bg_app']};")

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
                    color: white;
                    border: 1px solid {c['accent_blue_btn_border']};
                }}
            """)
