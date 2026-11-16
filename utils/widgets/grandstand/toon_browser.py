"""Choose-a-toon browser (spec §2, handoff §4.7): the shelf-level surface
that swaps in for the card shelf while the selector and hero stay put.

Standing figures at the `waving` pose, because the task is recognising a
toon, not scanning a list. Picking emits `toon_picked`; the write belongs to
LaunchTab (RecentToonsStore.set_primary), never here. Cards read renders the
way every card does — through the cache, never writing to it.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QScrollArea, QToolButton,
    QVBoxLayout, QWidget,
)

QWIDGETSIZE_MAX = 16777215      # Qt's "no maximum"; PySide does not export it

from utils.toon_customization_resolve import resolve_accent
from utils.toon_renders import AWAITING_RENDER_TOOLTIP, ToonRenders
from utils.toon_silhouette import paint_race_silhouette
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.card_shelf import SHELF_GAP
from utils.widgets.grandstand.draft import shown_record, unique_toons
from utils.widgets.grandstand.model import PORTRAIT_RENDER, portrait_mode
from utils.widgets.grandstand.roster_card import CARD_H, CARD_RADIUS, CARD_W
from utils.widgets.grandstand.sheet import SheetHeader

BROWSE_POSE = "waving"          # handoff §4.7: standing figures
FIGURE_H = 132                  # `.cart` height
FIGURE_MAX_W = 124              # image max-width, no head-fit transform
FIGURE_TOP = 10
EMPTY_MAX_W = 460
BROWSER_MARGINS = (12, 12, 12, 12)
RIBBON_CHECK = "✓"
RIBBON_PLUS = "+"

# Copy, verbatim from handoff §4.7.
EMPTY_TITLE = "No toons discovered on {user} yet"
EMPTY_BODY = ("Launch this account once and play a toon. The launcher records "
              "who you played, then pulls that toon's render. Until then there "
              "is nothing for it to show.")


def title_for(display_name: str) -> str:
    return f"Choose a toon · {display_name}"


def subtitle_for(count: int) -> str:
    found = "1 toon found" if count == 1 else f"{count} toons found"
    return f"Whichever you pick is what this account shows on the launcher · {found}"


def laff_line(rec) -> str:
    """`Laff {n}`; the handoff's `· {last played}` has no source — ToonRecord
    carries no timestamp — so the line ends at the laff."""
    laff = getattr(rec, "laff", None)
    return f"Laff {laff}" if laff is not None else ""


def _transparent(widget: QWidget, name: str) -> None:
    widget.setObjectName(name)
    widget.setStyleSheet(f"#{name} {{ background: transparent; }}")


class _ToonCard(QFrame):
    """One toon, radio-like: the current toon is checked and inert, every
    other card picks on click (Enter/Space pick, arrows move)."""

    picked = Signal(str)
    move_focus = Signal(int)        # -1 / +1, emitted by Task 7's keys

    def __init__(self, parent: QWidget, game: str, rec, checked: bool) -> None:
        super().__init__(parent)
        self.setFixedSize(CARD_W, CARD_H)
        # See RosterCard: the card paints its own rounded wash, so the app's
        # global QWidget background must not fill its square first.
        self.setObjectName("gs_browser_card")
        self.setStyleSheet("#gs_browser_card { background: transparent; }")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor if checked else Qt.PointingHandCursor)
        self.setAccessibleName(rec.toon_name)
        self._game, self._rec, self._checked = game, rec, checked
        self._is_dark = True
        self._pixmap: Optional[QPixmap] = None
        self._renders = ToonRenders.instance()
        self._renders.render_landed.connect(self._on_render_landed)
        self._renders.set_promoted.connect(self._on_set_promoted)

        self.ribbon = QToolButton(self)
        self.ribbon.setObjectName("gs_browser_ribbon")
        self.ribbon.setFixedSize(24, 24)
        self.ribbon.move(CARD_W - 24 - 9, 9)
        self.ribbon.setFocusPolicy(Qt.NoFocus)
        self.ribbon.setCursor(self.cursor())
        self.ribbon.setText(RIBBON_CHECK if checked else RIBBON_PLUS)
        self.ribbon.clicked.connect(self._on_ribbon_clicked)

        self.name = QLabel(rec.toon_name, self)
        self.name.setGeometry(10, 146, CARD_W - 20, 18)
        self.species = QLabel(rec.species or "", self)
        self.species.setGeometry(10, 164, CARD_W - 20, 14)
        self.laff = QLabel(laff_line(rec), self)
        self.laff.setGeometry(10, 180, CARD_W - 20, 14)

        self._load()
        self.apply_theme(True)

    # ── readouts ───────────────────────────────────────────────────────────

    def toon_name(self) -> str:
        return self._rec.toon_name

    def is_checked(self) -> bool:
        return self._checked

    def requested_pose(self) -> str:
        return BROWSE_POSE

    def portrait_pixmap(self) -> Optional[QPixmap]:
        return self._pixmap

    def accent(self) -> str:
        return resolve_accent({"accent": self._rec.accent},
                              QColor(gp.game_accent(self._game))).name()

    # ── render (cache consumer) ────────────────────────────────────────────

    def _wants_render(self) -> bool:
        r = self._rec
        return bool(r.toon_name) and portrait_mode(self._game, bool(r.dna)) == PORTRAIT_RENDER

    def _read(self) -> Optional[QPixmap]:
        if not self._wants_render():
            return None
        hit = self._renders.pixmap_for(self._game, self._rec.toon_name, BROWSE_POSE)
        return hit[0] if hit is not None else None

    def _load(self) -> None:
        self._pixmap = self._read()
        tip = ""
        if (self._pixmap is None and self._wants_render()
                and self._renders.awaiting_render(self._game, self._rec.toon_name)):
            tip = AWAITING_RENDER_TOOLTIP.format(name=self._rec.toon_name)
        self.setToolTip(tip)
        self.update()

    def _on_render_landed(self, game: str, name: str, pose: str) -> None:
        if pose != BROWSE_POSE or game != self._game or name != self._rec.toon_name:
            return
        pm = self._read()
        if pm is None:
            return                      # a landing never clears
        self._pixmap = pm
        self.setToolTip("")
        self.update()

    def _on_set_promoted(self, game: str, name: str) -> None:
        if game != self._game or name != self._rec.toon_name:
            return
        self._load()

    # ── interaction ────────────────────────────────────────────────────────

    def _on_ribbon_clicked(self) -> None:
        """Bound method, never a lambda: a lambda has no receiver QObject, so
        Qt cannot auto-disconnect it when this card is torn down."""
        self._pick()

    def _pick(self) -> None:
        if not self._checked:           # the current toon is inert
            self.picked.emit(self._rec.toon_name)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self._pick()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        """Radio semantics (spec §4): Enter/Space pick, arrows move focus."""
        key = event.key()
        if key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._pick()
            event.accept()
            return
        if key in (Qt.Key_Left, Qt.Key_Up):
            self.move_focus.emit(-1)
            event.accept()
            return
        if key in (Qt.Key_Right, Qt.Key_Down):
            self.move_focus.emit(1)
            event.accept()
            return
        super().keyPressEvent(event)

    # ── paint ──────────────────────────────────────────────────────────────

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        ink = gp.card_ink(self._checked, is_dark)
        self.name.setStyleSheet(
            f"color: {ink['name'].name()}; font-size: 13px; font-weight: 700;"
            " background: transparent;")
        for label in (self.species, self.laff):
            label.setStyleSheet(
                f"color: {ink['user'].name()}; font-size: 10px;"
                " background: transparent;")
        rib = gp.ribbon(self._checked, is_dark)
        self.ribbon.setStyleSheet(
            "QToolButton {"
            f" background: {rib['bg'].name(QColor.HexArgb)};"
            f" color: {rib['ink'].name()};"
            f" border: 1px solid {rib['border'].name(QColor.HexArgb)};"
            " border-radius: 8px; font-size: 13px; }")
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        d = gp.card_surface(self.accent(), self._checked, self._is_dark)
        wash = QLinearGradient(QPointF(r.left(), r.top()), QPointF(r.left(), r.bottom()))
        wash.setColorAt(0.0, d["top"])
        wash.setColorAt(1.0, d["bot"])
        p.setPen(Qt.NoPen)
        p.setBrush(wash)
        p.drawRoundedRect(r, CARD_RADIUS, CARD_RADIUS)

        # `.cart`: 132 high, figure at 100% height / max-width 124, anchored
        # bottom-centre (`place-items: end center`), no head-fit transform.
        box = QRect((CARD_W - FIGURE_MAX_W) // 2, FIGURE_TOP, FIGURE_MAX_W, FIGURE_H)
        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(box.size(), Qt.KeepAspectRatio,
                                         Qt.SmoothTransformation)
            x = box.center().x() - scaled.width() // 2
            y = box.bottom() + 1 - scaled.height()
            p.drawPixmap(x, y, scaled)
        else:
            paint_race_silhouette(p, box, self._rec.species, self.accent())

        p.setBrush(Qt.NoBrush)
        p.setPen(d["border"])
        p.drawRoundedRect(r, CARD_RADIUS, CARD_RADIUS)
        p.end()


class ToonBrowser(QFrame):
    back_requested = Signal()
    toon_picked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("gs_browser")
        # The panel is focusable so an empty browser is not a keyboard dead
        # end: with no cards there is nothing for focus_current() to land on
        # and Esc would never reach keyPressEvent.
        self.setFocusPolicy(Qt.StrongFocus)
        self._is_dark = True
        self._game = "ttr"
        self._cards: list[_ToonCard] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(*BROWSER_MARGINS)
        root.setSpacing(0)

        self.header = SheetHeader(self)
        self.header.back_requested.connect(self.back_requested.emit)
        root.addWidget(self.header)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._strip = QWidget()
        _transparent(self._strip, "gs_browser_strip")
        self._row = QHBoxLayout(self._strip)
        self._row.setContentsMargins(2, 6, 2, 12)      # the shelf's strip
        self._row.setSpacing(SHELF_GAP)
        self._row.setSizeConstraint(QLayout.SetMinimumSize)
        self._row.addStretch()
        self.scroll.setWidget(self._strip)
        root.addWidget(self.scroll, 1)

        # The bar's height comes and goes with its range, and the strip's
        # floor must include it (card_shelf.py:159).
        self.scroll.horizontalScrollBar().rangeChanged.connect(self._fit_strip)

        self.empty = QWidget(self)
        _transparent(self.empty, "gs_browser_empty")
        col = QVBoxLayout(self.empty)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        col.addStretch(1)
        self.empty_title = QLabel(self.empty)
        self.empty_body = QLabel(self.empty)
        for label in (self.empty_title, self.empty_body):
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignCenter)
            col.addWidget(label, 0, Qt.AlignHCenter)
        col.addStretch(1)
        self.empty.setVisible(False)
        root.addWidget(self.empty, 1)

        self.apply_theme(True)
        self._fit_strip()

    # ── inbound ────────────────────────────────────────────────────────────

    def open(self, game: str, account_id: str, display_name: str,
             toons: list, primary_name) -> None:
        """Rebuild the strip for one account. Rename ghosts collapse (spec
        §3); the checked card is the record the account shows now."""
        self._game = game
        records = unique_toons(list(toons))
        current = shown_record(records, primary_name)
        self.header.set_copy(title_for(display_name), subtitle_for(len(records)))
        for card in self._cards:
            self._row.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards = []
        for index, rec in enumerate(records):
            checked = current is not None and rec.toon_name == current.toon_name
            card = _ToonCard(self._strip, game, rec, checked)
            card.picked.connect(self.toon_picked.emit)
            card.move_focus.connect(self._on_card_move_focus)
            card.apply_theme(self._is_dark)
            self._row.insertWidget(index, card)
            self._cards.append(card)
        self.empty_title.setText(EMPTY_TITLE.format(user=display_name))
        self.empty_body.setText(EMPTY_BODY)
        self.scroll.setVisible(bool(records))
        self.empty.setVisible(not records)
        self._fit_empty()
        self._fit_strip()

    def _fit_empty(self) -> None:
        """Give the two wrapped labels the width they wrap at and the height
        that wrapping needs.

        A layout item placed with an alignment is sized from sizeHint(), and a
        word-wrapped QLabel's sizeHint() is a guess that knows neither the
        column it will get nor the stylesheet's font. Seen live on Windows:
        the copy wrapped into a narrow column and was cut off top and bottom.
        """
        # The panel's own width, not self.empty's: during this widget's
        # resizeEvent its children still hold their previous geometry.
        left, _top, right, _bottom = BROWSER_MARGINS
        width = max(120, min(EMPTY_MAX_W, self.width() - left - right))
        for label in (self.empty_title, self.empty_body):
            label.ensurePolished()
            label.setFixedWidth(width)
            # Release the previous height before measuring: QLabel expands
            # heightForWidth() to its own minimum size, so a height fixed
            # while the panel was still narrow (many lines) would otherwise
            # be handed straight back and never shrink.
            label.setMinimumHeight(0)
            label.setMaximumHeight(QWIDGETSIZE_MAX)
            needed = label.heightForWidth(width)
            if needed > 0:
                label.setFixedHeight(needed)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_empty()

    def cards(self) -> list[_ToonCard]:
        return list(self._cards)

    def card_for(self, name: str) -> Optional[_ToonCard]:
        return next((c for c in self._cards if c.toon_name() == name), None)

    def current_card(self) -> Optional[_ToonCard]:
        return next((c for c in self._cards if c.is_checked()), None)

    def is_empty_state(self) -> bool:
        return self.empty.isVisibleTo(self)

    def title_text(self) -> str:
        return self.header.title_text()

    def subtitle_text(self) -> str:
        return self.header.subtitle_text()

    def focus_current(self) -> None:
        """Land focus on the surface. With cards that is the checked one; with
        none it is the panel itself, or an empty browser would be a keyboard
        dead end — nothing focusable, so Esc never reaches keyPressEvent.

        The owner calls this *after* swapping the browser into the shelf's
        slot: setFocus() on a widget the stack still hides is dropped."""
        card = self.current_card() or (self._cards[0] if self._cards else None)
        if card is not None:
            card.setFocus()
            return
        self.setFocus()

    def _on_card_move_focus(self, delta: int) -> None:
        """Bound method, never a lambda: a lambda has no receiver QObject, so
        Qt cannot auto-disconnect it when the strip is rebuilt. The emitting
        card is the sender."""
        card = self.sender()
        if isinstance(card, _ToonCard):
            self._move_focus(card, delta)

    def _move_focus(self, card: _ToonCard, delta: int) -> None:
        """Radio semantics (spec §4): arrows move among the cards, wrapping."""
        if card not in self._cards:
            return
        target = self._cards[(self._cards.index(card) + delta) % len(self._cards)]
        target.setFocus()
        self.scroll.ensureWidgetVisible(target)

    def _fit_strip(self, *_) -> None:
        """Same floor as the shelf: never squeeze the viewport below the cards."""
        bar = self.scroll.horizontalScrollBar()
        bar_h = bar.sizeHint().height() if bar.maximum() > bar.minimum() else 0
        self.scroll.setMinimumHeight(self._strip.minimumSizeHint().height() + bar_h)

    def keyPressEvent(self, event) -> None:
        """Esc = Back, from a card or the panel itself."""
        if event.key() == Qt.Key_Escape:
            self.back_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:
        """StrongFocus lets an empty browser take focus at all (Esc must
        reach keyPressEvent with no card to hold it). With cards present,
        the panel itself is never where focus should sit — a background
        click must not strand the arrow keys and Enter off the checked
        card, so hand focus straight back to it."""
        if self._cards:
            self.focus_current()
        super().focusInEvent(event)

    # ── theme ──────────────────────────────────────────────────────────────

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        s = gp.sheet_surface(is_dark)
        self.setStyleSheet(
            f"QFrame#gs_browser {{ background: {s['bg'].name()};"
            f" border: 1px solid {s['border'].name()}; border-radius: 9px; }}")
        self.header.apply_theme(is_dark)
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
        e = gp.browser_empty_ink(is_dark)
        self.empty_title.setStyleSheet(
            f"color: {e['title'].name()}; font-size: 13px; font-weight: 700;"
            " background: transparent;")
        self.empty_body.setStyleSheet(
            f"color: {e['body'].name()}; font-size: 12px; background: transparent;")
        self._fit_empty()
        for card in self._cards:
            card.apply_theme(is_dark)
