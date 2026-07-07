"""Footer pager for a LaunchSection: prev/next arrows, dynamic page dots
(current = game-accent fill, active = green ring), a secondary '⇅ Reorder' chip, and a
persistent '+ Add Account' button. Emits page_selected(int), reorder_clicked(),
and add_clicked().

v2 pinwheel reskin: the arrows + dots live inside an inset-colored "dot pill"
(QFrame `dot_pill`, row_bg/row_border tokens, fully rounded). The current dot
fills with the game accent's bright shade (V2_ACCENTS[game]["b"]); idle dots
use a faint theme-relative tint; an active (running-page) dot keeps its 2px
green ring. Reorder stays a ghost pill, Add a solid game-accent pill - both
outside the dot pill, separated by a stretch.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton

from utils.color_math import alpha, lighten_rgb
from utils.theme_manager import V2_ACCENTS, get_theme_colors, get_v2_tokens
from utils.widgets.chip_button import QuietChipButton

_SHORT = {"ttr": "TTR", "cc": "CC"}
RING_COLOR = "#56c856"  # matches the tile running-dot color


class _PageDot(QToolButton):
    """A clickable page dot. The `current` (bool) and `active` (bool) dynamic
    properties are the single source of truth; apply_theme() reads them back and
    paints the dot via a per-widget setStyleSheet (game-accent fill when current,
    green ring when active)."""
    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(13, 13)
        self.setProperty("current", False)
        self.setProperty("active", False)


class PagePager(QFrame):
    page_selected = Signal(int)
    add_clicked = Signal()
    reorder_clicked = Signal()

    def __init__(self, game: str, parent=None):
        super().__init__(parent)
        self._game = game
        self._dots: list[_PageDot] = []
        self._page = 0
        self._page_count = 1
        self._theme = get_theme_colors(True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 12)
        lay.setSpacing(8)

        # ── dot pill: prev arrow + dots + next arrow, wrapped in one inset pill.
        self.dot_pill = QFrame()
        self.dot_pill.setObjectName("dotPill")
        self.dot_pill.setFixedHeight(30)
        pill_lay = QHBoxLayout(self.dot_pill)
        pill_lay.setContentsMargins(2, 0, 2, 0)
        pill_lay.setSpacing(0)

        self.prev_btn = QToolButton()
        self.prev_btn.setText("‹")
        self.prev_btn.setCursor(Qt.PointingHandCursor)
        self.prev_btn.clicked.connect(self._go_prev)
        pill_lay.addWidget(self.prev_btn)

        self._dots_box = QFrame()
        self._dots_box.setObjectName("dotsBox")
        self._dots_lay = QHBoxLayout(self._dots_box)
        self._dots_lay.setContentsMargins(2, 0, 2, 0)
        self._dots_lay.setSpacing(7)
        pill_lay.addWidget(self._dots_box)

        self.next_btn = QToolButton()
        self.next_btn.setText("›")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.clicked.connect(self._go_next)
        pill_lay.addWidget(self.next_btn)

        lay.addWidget(self.dot_pill)
        lay.addStretch(1)

        self.reorder_btn = QuietChipButton()
        self.reorder_btn.setText("⇅ Reorder")
        self.reorder_btn.setCursor(Qt.PointingHandCursor)
        self.reorder_btn.setToolTip("Reorder accounts")
        self.reorder_btn.clicked.connect(self.reorder_clicked.emit)
        self.reorder_btn.setVisible(False)
        lay.addWidget(self.reorder_btn)

        self.add_btn = QuietChipButton()
        self.add_btn.setText(f"+ Add {_SHORT[game]} Account")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self.add_clicked.emit)
        lay.addWidget(self.add_btn)

        self.apply_theme(self._theme)

    @property
    def page(self) -> int:
        return self._page

    @property
    def page_count(self) -> int:
        return self._page_count

    def _go_prev(self):
        if self._page > 0:
            self.page_selected.emit(self._page - 1)

    def _go_next(self):
        if self._page < self._page_count - 1:
            self.page_selected.emit(self._page + 1)

    def set_state(
        self,
        *,
        page: int,
        page_count: int,
        activity: list[bool],
        show_add: bool,
        show_reorder: bool = False,
    ) -> None:
        self._page = page
        self._page_count = page_count
        if len(self._dots) != page_count:
            while self._dots_lay.count():
                item = self._dots_lay.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
            self._dots = []
            for i in range(page_count):
                dot = _PageDot(i)
                dot.clicked.connect(lambda _=False, idx=i: self.page_selected.emit(idx))
                self._dots_lay.addWidget(dot)
                self._dots.append(dot)
        for i, dot in enumerate(self._dots):
            dot.setProperty("current", i == page)
            dot.setProperty("active", bool(activity[i]) if i < len(activity) else False)
        self.prev_btn.setEnabled(page > 0)
        self.next_btn.setEnabled(page < page_count - 1)
        self.add_btn.setVisible(show_add)
        self.reorder_btn.setVisible(show_reorder)
        self.apply_theme(self._theme)

    def apply_theme(self, c: dict) -> None:
        self._theme = c
        is_dark = QColor(c["text_primary"]).lightnessF() > 0.5
        t = get_v2_tokens(is_dark)
        accent = V2_ACCENTS.get(self._game, V2_ACCENTS["blue"])

        self.dot_pill.setStyleSheet(
            "QFrame#dotPill {"
            f" background: {t['row_bg']}; border: 1px solid {t['row_border']};"
            " border-radius: 999px; }"
        )
        self._dots_box.setStyleSheet(
            "QFrame#dotsBox { background: transparent; border: none; }"
        )

        faint = alpha("#ffffff", 0.45) if is_dark else alpha("#0f172a", 0.45)
        for btn in (self.prev_btn, self.next_btn):
            btn.setStyleSheet(
                "QToolButton { background: transparent; border: none;"
                f" color: {t['sub']}; font-size: 15px; padding: 0 8px; }}"
                f"QToolButton:disabled {{ color: {faint}; }}"
            )

        dot_idle = alpha("#ffffff", 0.28) if is_dark else alpha("#0f172a", 0.22)
        for dot in self._dots:
            current = bool(dot.property("current"))
            active = bool(dot.property("active"))
            fill = accent["b"] if current else dot_idle
            ring = f" border: 2px solid {RING_COLOR};" if active else " border: none;"
            dot.setStyleSheet(
                "QToolButton { border-radius: 6px;"
                f" background: {fill};{ring} }}"
            )

        add_hover = lighten_rgb(QColor(accent["c"]), 0.12).name()
        self.add_btn.setStyleSheet(
            "QToolButton {"
            f" background: {accent['c']}; color: #ffffff;"
            f" border: 1px solid {accent['b']};"
            " border-radius: 14px; padding: 7px 13px;"
            " font-size: 12.5px; font-weight: 700; }"
            "QToolButton:hover {"
            f" background: {add_hover}; }}"
        )
        self.reorder_btn.setStyleSheet(
            "QToolButton {"
            f" background: {t['ctrl_bg']};"
            f" border: 1px solid {t['ctrl_border']}; color: {t['ctrl_text']};"
            " border-radius: 14px; padding: 7px 13px; font-size: 12.5px; font-weight: 700; }"
            "QToolButton:hover {"
            f" background: {t['ctrl_hover']}; }}"
        )
