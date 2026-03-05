"""
Keymap Tab — UI for creating and editing movement sets.

Each set is two sibling widgets in the scroll layout:
  1. A ClickableHeader (fully-rounded colored bar, always static)
  2. An AnimatedBody (the gray key-mapping panel that slides open/closed)

The header never moves, resizes, or changes shape.  Only the body animates.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QLineEdit, QSizePolicy, QSpacerItem,
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter
from utils.theme_manager import resolve_theme, get_theme_colors, apply_card_shadow, get_set_color, make_trash_icon
from utils.symbols import S

DIRECTIONS = ("up", "left", "down", "right", "jump", "book")
DIRECTION_LABELS = {"up": "Up", "left": "Left", "down": "Down", "right": "Right", "jump": "Jump", "book": "Book"}

DISPLAY_NAMES = {
    "space": "Space", "Control_L": "L Ctrl", "Control_R": "R Ctrl",
    "Shift_L": "L Shift", "Shift_R": "R Shift",
    "Alt_L": "L Alt", "Alt_R": "R Alt",
    "Up": "Up Arrow", "Down": "Down Arrow", "Left": "Left Arrow", "Right": "Right Arrow",
    "Return": "Enter", "BackSpace": "Backspace", "Tab": "Tab",
    "Escape": "Esc", "Delete": "Delete",
}

SPECIAL_KEYS = {
    Qt.Key_Space: "space", Qt.Key_Return: "Return", Qt.Key_Enter: "Return",
    Qt.Key_Tab: "Tab", Qt.Key_Backspace: "BackSpace", Qt.Key_Escape: "Escape",
    Qt.Key_Shift: "Shift_L", Qt.Key_Control: "Control_L",
    Qt.Key_Alt: "Alt_L", Qt.Key_Delete: "Delete",
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
        self.setFixedHeight(32)
        self.setFixedWidth(110)
        self.setAlignment(Qt.AlignCenter)
        self._update_display()

    def _update_display(self):
        self.setText("Press a key…" if self._awaiting else _display(self._key))

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

    def keyPressEvent(self, e):
        if not self._awaiting:
            return e.ignore()
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
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
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
        # Save expanded states before teardown (keyed by index)
        prev_states = {}
        for entry in self._entries:
            prev_states[entry["index"]] = entry["expanded"]

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

            # Restore previous state, or default to collapsed for new sets
            # Set 0 (Default) starts expanded on first build
            if prev_states:
                expanded = prev_states.get(idx, False)
            else:
                expanded = (idx == 0)

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
        bl.setContentsMargins(16, 12, 16, 12)
        bl.setSpacing(8)

        if index == 0:
            hint = QLabel("These keys are what is sent to all game windows for input.\nMake sure these match with your in-game settings.")
            hint.setObjectName("body_hint")
            hint.setWordWrap(True)
            hint.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.45); background: none; border: none; padding: 0 0 4px 0;")
            bl.addWidget(hint)

        for direction in DIRECTIONS:
            row = QHBoxLayout()
            row.setSpacing(10)
            lbl = QLabel(DIRECTION_LABELS[direction])
            lbl.setObjectName("direction_label")
            lbl.setFixedWidth(50)
            row.addWidget(lbl)

            field = MovementKeyField(set_data.get(direction, ""))
            field.setObjectName(f"key_field_{direction}")
            field.key_captured.connect(
                lambda key, idx=index, d=direction: self._on_key_changed(idx, d, key)
            )
            row.addWidget(field)
            row.addStretch()
            bl.addLayout(row)

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
                """)

        if hasattr(self, "_add_btn"):
            self._add_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {c['btn_bg']};
                    color: {c['text_primary']};
                    border: 1px solid {c['btn_border']};
                    border-radius: 8px; font-weight: bold; font-size: 13px;
                }}
                QPushButton:hover {{
                    background: {c['accent_blue_btn']};
                    color: white;
                    border: 1px solid {c['accent_blue_btn_border']};
                }}
            """)