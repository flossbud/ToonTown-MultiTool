"""Footer pager for a LaunchSection: prev/next arrows, dynamic page dots
(current = blue fill, active = green ring), and a persistent '+ Add Account'
button. Emits page_selected(int) and add_clicked().
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton

from utils.theme_manager import get_theme_colors
from utils.widgets.chip_button import QuietChipButton

_SHORT = {"ttr": "TTR", "cc": "CC"}
RING_COLOR = "#56c856"  # matches the tile running-dot color


class _PageDot(QToolButton):
    """A clickable page dot. The `current` (bool) and `active` (bool) dynamic
    properties are the single source of truth; apply_theme() reads them back and
    paints the dot via a per-widget setStyleSheet (blue fill when current, green
    ring when active)."""
    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(16, 16)
        self.setProperty("current", False)
        self.setProperty("active", False)


class PagePager(QFrame):
    page_selected = Signal(int)
    add_clicked = Signal()

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

        self.prev_btn = QToolButton()
        self.prev_btn.setText("‹")
        self.prev_btn.setCursor(Qt.PointingHandCursor)
        self.prev_btn.clicked.connect(self._go_prev)
        lay.addWidget(self.prev_btn)

        self._dots_box = QFrame()
        self._dots_lay = QHBoxLayout(self._dots_box)
        self._dots_lay.setContentsMargins(0, 0, 0, 0)
        self._dots_lay.setSpacing(7)
        lay.addWidget(self._dots_box)

        self.next_btn = QToolButton()
        self.next_btn.setText("›")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.clicked.connect(self._go_next)
        lay.addWidget(self.next_btn)

        lay.addStretch(1)

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
        self.apply_theme(self._theme)

    def apply_theme(self, c: dict) -> None:
        self._theme = c
        for btn in (self.prev_btn, self.next_btn):
            btn.setStyleSheet(
                "QToolButton { background: transparent; border: none;"
                f" color: {c['text_secondary']}; font-size: 16px; padding: 0 4px; }}"
                f"QToolButton:disabled {{ color: {c['border_card']}; }}"
            )
        for dot in self._dots:
            current = bool(dot.property("current"))
            active = bool(dot.property("active"))
            fill = c["accent_blue_btn"] if current else c["border_light"]
            ring = f" border: 2px solid {RING_COLOR};" if active else " border: none;"
            dot.setStyleSheet(
                "QToolButton { border-radius: 8px;"
                f" background: {fill};{ring} }}"
            )
        self.add_btn.setStyleSheet(
            "QToolButton {"
            f" background: {c['accent_blue_btn']}; color: {c['text_on_accent']};"
            " border: none; border-radius: 8px; padding: 7px 13px;"
            " font-size: 12px; font-weight: 600; }"
            "QToolButton:hover {"
            f" background: {c['accent_blue_btn_hover']}; }}"
        )
