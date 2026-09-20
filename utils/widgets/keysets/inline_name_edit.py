"""InlineNameEdit — a set title that is a label at rest and a line edit
while renaming.

Read-only, frameless and transparent until `begin_edit()` (or a click / the
pencil / a rail gesture) flips it into edit mode with an accent ring. Enter
and focus-out commit (trimmed, non-empty, changed); Esc reverts. A locked
edit (the Default set) never enters edit mode and shows no affordance. Font
is set programmatically, not via QSS, so `sizeHint` can be computed from real
metrics and the box hugs the text like a label would.

Colour rule: everything comes from palette.title_edit_qss.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLineEdit, QSizePolicy

from .game_meta import set_accent
from .palette import title_edit_qss

_MIN_W, _MAX_W, _PAD_W = 80, 320, 26
_MAX_LEN = 32
_TOOLTIP = "Click to rename"


class InlineNameEdit(QLineEdit):
    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._locked = False
        self._editing = False
        self._original = ""
        self._is_dark = True
        _, self._accent_b = set_accent(0)

        f = QFont(self.font())
        f.setPixelSize(16)
        f.setWeight(QFont.Bold)
        self.setFont(f)
        self.setMaxLength(_MAX_LEN)
        self.setFrame(False)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.textChanged.connect(lambda _t: self.updateGeometry())
        self.returnPressed.connect(lambda: self._finish(commit=True))
        self._enter_rest()

    # ── public API ───────────────────────────────────────────────────────
    def is_editing(self) -> bool:
        return self._editing

    def is_locked(self) -> bool:
        return self._locked

    def set_locked(self, locked: bool) -> None:
        locked = bool(locked)
        if locked and self._editing:
            self._drop_edit()
        self._locked = locked
        self._enter_rest()

    def set_text_quiet(self, text: str) -> None:
        """Replace the text without any commit/cancel signal (refresh path)."""
        if self._editing:
            self._drop_edit()
        self.setText(text)
        self._original = text

    def begin_edit(self) -> None:
        if self._locked or self._editing:
            return
        self._editing = True
        self._original = self.text()
        self.setReadOnly(False)
        self._apply_style()
        self.setFocus(Qt.OtherFocusReason)
        self.selectAll()

    def apply_style(self, is_dark: bool, accent_b: str) -> None:
        self._is_dark = is_dark
        self._accent_b = accent_b
        self._apply_style()

    # ── state transitions ────────────────────────────────────────────────
    def _enter_rest(self) -> None:
        self.setReadOnly(True)
        self.setCursor(Qt.ArrowCursor if self._locked else Qt.PointingHandCursor)
        self.setToolTip("" if self._locked else _TOOLTIP)
        self._apply_style()

    def _drop_edit(self) -> None:
        """Leave edit mode restoring the original text, emitting nothing."""
        self._editing = False
        self.setText(self._original)
        self.deselect()
        self._enter_rest()

    def _finish(self, *, commit: bool) -> None:
        if not self._editing:
            return
        self._editing = False
        text = self.text().strip()
        changed = commit and bool(text) and text != self._original
        self.setText(text if changed else self._original)
        self.deselect()
        self._enter_rest()
        self.clearFocus()
        if changed:
            self._original = text
            self.committed.emit(text)
        else:
            self.cancelled.emit()

    def _apply_style(self) -> None:
        self.setStyleSheet(title_edit_qss(self._is_dark, self._accent_b, self._editing))

    # ── geometry ─────────────────────────────────────────────────────────
    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        w = fm.horizontalAdvance(self.text() or "Set name") + _PAD_W
        return QSize(max(_MIN_W, min(_MAX_W, w)), max(super().sizeHint().height(), 28))

    def minimumSizeHint(self) -> QSize:
        return QSize(_MIN_W, self.sizeHint().height())

    # ── events ───────────────────────────────────────────────────────────
    def mousePressEvent(self, e) -> None:
        if self._editing:
            super().mousePressEvent(e)
            return
        if e.button() == Qt.LeftButton and not self._locked:
            self.begin_edit()
        e.accept()

    def mouseDoubleClickEvent(self, e) -> None:
        if self._editing:
            super().mouseDoubleClickEvent(e)
        else:
            e.accept()

    def keyPressEvent(self, e) -> None:
        if self._editing and e.key() == Qt.Key_Escape:
            self._finish(commit=False)
            e.accept()
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e) -> None:
        super().focusOutEvent(e)
        if self._editing:
            self._finish(commit=True)
