"""The roster shelf (handoff §4.1c): head row, scrolling cards, Add tile.

The shelf owns presentation only. It is told which accounts exist and which are
selected; it never decides either. That keeps the cap rule in LaunchParty,
where it is testable without a widget.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPointF, QPropertyAnimation, Qt, Signal,
)
from PySide6.QtGui import QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QScrollArea, QToolButton,
    QVBoxLayout, QWidget,
)

import utils.motion as motion
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.roster_card import CARD_H, CARD_W, RosterCard

SHELF_GAP = 11
FADE_W = 36
HEAD_H = 34

TITLE = "CHOOSE YOUR TOONS"


class _AddTile(QToolButton):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setText("+\nAdd\naccount")


class _EdgeFades(QWidget):
    """The 36px masks from handoff §4.1c, drawn ABOVE the scrolling strip.

    A parent paints before its children, so the shelf cannot draw these itself —
    the cards would cover them. This sits over the viewport instead and is
    transparent to mouse and wheel events, so the strip underneath still
    scrolls normally.
    """

    def __init__(self, shelf: "CardShelf") -> None:
        super().__init__(shelf)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._shelf = shelf

    def paintEvent(self, event) -> None:
        sides = self._shelf.fade_sides()
        if not sides:
            return
        d = gp.shelf_scroll(self._shelf.is_dark())
        p = QPainter(self)
        h = self.height()
        if "left" in sides:
            g = QLinearGradient(QPointF(0.0, 0.0), QPointF(float(FADE_W), 0.0))
            g.setColorAt(0.0, d["fade_in"])
            g.setColorAt(1.0, d["fade_out"])
            p.fillRect(0, 0, FADE_W, h, g)
        if "right" in sides:
            g = QLinearGradient(QPointF(float(self.width() - FADE_W), 0.0),
                                QPointF(float(self.width()), 0.0))
            g.setColorAt(0.0, d["fade_out"])
            g.setColorAt(1.0, d["fade_in"])
            p.fillRect(self.width() - FADE_W, 0, FADE_W, h, g)
        p.end()


class CardShelf(QWidget):
    card_clicked = Signal(str)
    star_clicked = Signal(str)
    edit_clicked = Signal(str)
    gear_clicked = Signal(str)
    launch_clicked = Signal(str)
    cancel_clicked = Signal(str)
    quit_clicked = Signal(str)
    enter_2fa_clicked = Signal(str)
    retry_clicked = Signal(str)
    add_account_clicked = Signal()
    manage_clicked = Signal()
    clear_selection_clicked = Signal()
    clear_main_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("gs_shelf")
        # A plain QWidget subclass paints its stylesheet background only as a
        # top-level window. Embedded in the view it painted nothing, so the
        # chooser panel and its border never appeared and the edge fades drew
        # a panel-coloured stripe over the bare app background.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._is_dark = True
        self._cards: dict[str, RosterCard] = {}
        self._order: list[str] = []
        self._shake_anim: Optional[QPropertyAnimation] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        # The head row is a fixed 34px (handoff §4.1c). The shelf is the only
        # band that stretches inside the 688px content area, so letting this
        # row size itself would eat the cards' height.
        self.head = QWidget(self)
        self.head.setObjectName("gs_shelf_head")
        self.head.setStyleSheet(
            "#gs_shelf_head { background: transparent; }")
        self.head.setFixedHeight(HEAD_H)
        head = QHBoxLayout(self.head)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(14)
        self.title = QLabel(TITLE, self)
        head.addWidget(self.title, 1, Qt.AlignVCenter)

        self.clear_selection_link = QPushButton("Clear selection", self)
        self.clear_main_link = QPushButton("Clear main", self)
        self.manage_link = QPushButton("Manage", self)
        for btn, sig in ((self.clear_selection_link, self.clear_selection_clicked),
                         (self.clear_main_link, self.clear_main_clicked),
                         (self.manage_link, self.manage_clicked)):
            btn.setFlat(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(sig.emit)
            head.addWidget(btn, 0, Qt.AlignVCenter)
        root.addWidget(self.head)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._strip = QWidget()
        self._strip.setObjectName("gs_shelf_strip")
        self._strip.setStyleSheet(
            "#gs_shelf_strip { background: transparent; }")
        self._row = QHBoxLayout(self._strip)
        self._row.setContentsMargins(2, 6, 2, 12)
        self._row.setSpacing(SHELF_GAP)
        # The strip must never be squeezed below its cards. QScrollArea with
        # widgetResizable=True otherwise resizes the strip down to the viewport
        # and the fixed 148px cards overlap instead of overflowing, so nothing
        # ever scrolls and the edge fades never appear.
        self._row.setSizeConstraint(QLayout.SetMinimumSize)
        self._row.addStretch()
        self.scroll.setWidget(self._strip)

        root.addWidget(self.scroll, 1)

        self._fades = _EdgeFades(self)

        # The fades depend on scroll position and on how much there is to
        # scroll, so both have to repaint the overlay.
        bar = self.scroll.horizontalScrollBar()
        bar.valueChanged.connect(self._fades.update)
        bar.rangeChanged.connect(lambda *_: self._fades.update())
        # The bar's height comes and goes with its range, and the strip's
        # floor must include it.
        bar.rangeChanged.connect(self._fit_strip)

        self.add_tile = _AddTile(self._strip)
        self.add_tile.clicked.connect(self.add_account_clicked.emit)
        self._row.insertWidget(self._row.count() - 1, self.add_tile)

        self.apply_theme(True)
        self._fit_strip()
        self._fades.setGeometry(self.scroll.geometry())
        self._fades.raise_()

    # ── inbound ────────────────────────────────────────────────────────────

    def cards(self) -> list[RosterCard]:
        return [self._cards[aid] for aid in self._order if aid in self._cards]

    def card_for(self, account_id: str) -> Optional[RosterCard]:
        return self._cards.get(account_id)

    def is_dark(self) -> bool:
        return self._is_dark

    def strip_widgets(self) -> list:
        """Left-to-right contents of the scrolling strip: each card as its
        account id, then the Add tile. Test surface for shelf ordering."""
        out = []
        for i in range(self._row.count()):
            w = self._row.itemAt(i).widget()
            if w is self.add_tile:
                out.append(w)
            elif isinstance(w, RosterCard):
                out.append(w.account_id())
        return out

    def set_entries(self, entries: list) -> None:
        """Rebuild the strip. Cards are cheap and identity changes are rare, so
        this is a rebuild rather than a diff — the *lineup* is what animates."""
        for card in self._cards.values():
            self._row.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        self._order = []

        for index, entry in enumerate(entries):
            card = RosterCard(self._strip)
            card.set_entry(entry)
            card.clicked.connect(self.card_clicked.emit)
            card.star_clicked.connect(self.star_clicked.emit)
            card.edit_clicked.connect(self.edit_clicked.emit)
            card.gear_clicked.connect(self.gear_clicked.emit)
            card.launch_clicked.connect(self.launch_clicked.emit)
            card.cancel_clicked.connect(self.cancel_clicked.emit)
            card.quit_clicked.connect(self.quit_clicked.emit)
            card.enter_2fa_clicked.connect(self.enter_2fa_clicked.emit)
            card.retry_clicked.connect(self.retry_clicked.emit)
            card.apply_theme(self._is_dark)
            self._row.insertWidget(index, card)
            self._cards[entry.account_id] = card
            self._order.append(entry.account_id)

    def set_empty(self, empty: bool) -> None:
        """Clear roster cards for an explicitly empty account source.

        The Add tile is permanent, including for populated rosters, so leaving
        empty mode needs no reconstruction; the next ``set_entries`` call owns
        that transition.
        """
        if empty:
            self.set_entries([])
        self.add_tile.setVisible(True)

    def set_state(self, account_id: str, state: str, message: str = "",
                  raw: str = "") -> None:
        card = self._cards.get(account_id)
        if card is not None:
            card.set_state(state, message, raw)

    def set_selection(self, selected_ids: list, star_id: Optional[str]) -> None:
        """Paint membership and stage position. Position is 1-based and follows
        `selected_ids` as given — the caller passes the stage order (the
        party's launch order, star first); the shelf never reorders it."""
        for aid, card in self._cards.items():
            selected = aid in selected_ids
            card.set_selected(selected)
            card.set_position(selected_ids.index(aid) + 1 if selected else None)
            card.set_starred(aid == star_id)

    def set_links_enabled(self, clear_selection: bool, clear_main: bool) -> None:
        self.clear_selection_link.setEnabled(bool(clear_selection))
        self.clear_main_link.setEnabled(bool(clear_main))
        self._restyle_links()

    def shake(self, account_id: str) -> bool:
        """Refuse feedback for a rejected fifth selection. The cap is a stage
        fact, not an error worth a modal (spec §7). Returns whether an
        animation actually started — an unknown id and reduced motion both
        decline, and callers must not care which."""
        card = self._cards.get(account_id)
        if card is None or motion.is_reduced():
            return False
        anim = QPropertyAnimation(card, b"pos", self)
        start = card.pos()
        anim.setDuration(220)
        anim.setEasingCurve(QEasingCurve.OutQuad)
        anim.setKeyValueAt(0.0, start)
        anim.setKeyValueAt(0.25, start + QPoint(6, 0))
        anim.setKeyValueAt(0.55, start + QPoint(-5, 0))
        anim.setKeyValueAt(0.8, start + QPoint(3, 0))
        anim.setKeyValueAt(1.0, start)
        # Held only so the animation is not garbage-collected mid-run; cleared
        # on finish so the attribute never points at a deleted C++ object.
        anim.finished.connect(lambda: setattr(self, "_shake_anim", None))
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._shake_anim = anim
        return True

    def _fit_strip(self, *_) -> None:
        """The scroll area is never shorter than its strip. Its own minimum
        size hint is a few rows of nothing (its vertical bar is off), so a
        short window would squeeze the viewport below the cards and cut their
        bottoms; with this floor the launch tab's outer scroll area scrolls
        instead. The horizontal bar, when it shows, sits inside the area's
        height, so it counts."""
        bar = self.scroll.horizontalScrollBar()
        bar_h = bar.sizeHint().height() if bar.maximum() > bar.minimum() else 0
        self.scroll.setMinimumHeight(
            self._strip.minimumSizeHint().height() + bar_h)

    # ── edge fades ─────────────────────────────────────────────────────────

    def fade_sides(self) -> tuple:
        """Which 36px masks are showing (handoff §4.1c: 'when content is
        off-screen either side'). Empty when everything already fits."""
        bar = self.scroll.horizontalScrollBar()
        sides = []
        if bar.value() > bar.minimum():
            sides.append("left")
        if bar.value() < bar.maximum():
            sides.append("right")
        return tuple(sides)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fades.setGeometry(self.scroll.geometry())
        self._fades.raise_()

    # ── theme ──────────────────────────────────────────────────────────────

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        p = gp.panel(is_dark)
        self.setStyleSheet(
            f"QWidget#gs_shelf {{ background: {p['bg'].name()};"
            f" border: 1px solid {p['border'].name()}; border-radius: 9px; }}")
        head = gp.shelf_head_ink(is_dark)
        self.title.setStyleSheet(
            f"color: {head['title'].name()}; font-size: 10px; font-weight: 800;"
            " letter-spacing: 0.8px; background: transparent;")
        # Handoff §4.1c: 6px thumb in --border-light, no arrows, no trough.
        scroll = gp.shelf_scroll(is_dark)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            " QScrollArea > QWidget#qt_scrollarea_viewport {"
            " background: transparent; }"
            " QScrollBar:horizontal { height: 6px; background: transparent;"
            " margin: 0; }"
            " QScrollBar::handle:horizontal { border-radius: 3px;"
            f" background: {scroll['thumb'].name()}; }}"
            " QScrollBar::add-line:horizontal,"
            " QScrollBar::sub-line:horizontal { width: 0; }"
            " QScrollBar::add-page:horizontal,"
            " QScrollBar::sub-page:horizontal { background: transparent; }")
        tile = gp.add_tile(is_dark)
        self.add_tile.setStyleSheet(
            "QToolButton { background: transparent;"
            f" color: {tile['ink'].name()};"
            f" border: 1px dashed {tile['border'].name()};"
            " border-radius: 16px; font-size: 12px; }")
        self._restyle_links()
        for card in self._cards.values():
            card.apply_theme(is_dark)

    def _restyle_links(self) -> None:
        for btn, gold in ((self.clear_selection_link, False),
                          (self.clear_main_link, True),
                          (self.manage_link, False)):
            colour = gp.head_link(btn.isEnabled(), gold, self._is_dark)
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none;"
                " padding: 0; min-height: 0;"
                f" color: {colour.name()}; font-size: 11px; font-weight: 500; }}")
