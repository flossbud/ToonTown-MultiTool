"""The update sheet and the What's new sheet: a Roll Call stage that drops
in under the header, over a scrim.

One host, two kinds of content:

* the update sheet shows an ``UpdateFlow``'s current ``view()`` (offer,
  downloading, paused, ready, toons in game);
* What's new pages through a release's three highlights, one toon each.

The scrim covers everything below the header. Clicking it hides the sheet;
it never cancels anything.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from utils.rollcall import motion, paint
from utils.rollcall import tokens as T
from utils.rollcall.controls import RcButton, RcLink
from utils.rollcall.stage import (
    Actions, Body, Headline, Highlights, Link, Micro, Stage,
)

UPDATE, WHATS_NEW = "update", "whats_new"

SCRIM = T.rgba(0, 0, 0, 0.55)
SHADOW_BLUR = 44
SHADOW_DROP = 18
SHADOW_ALPHA = 0.60
SHUT_DROP = -20
SHUT_SCALE = 0.95


class UpdateSheetHost(QWidget):
    """Child of the window's content area; covers it below ``top``."""

    opened = Signal(str)          # UPDATE | WHATS_NEW
    closed = Signal(str)
    open_url = Signal(str)

    def __init__(self, parent: QWidget, top: int):
        super().__init__(parent)
        self._top = int(top)
        self._flow = None
        self._mode = ""
        self._open = False
        self._view_key = ""
        self._notes = None
        self._notes_url = ""
        self._page = 0
        self._scrim = motion.Tween(0.0)
        self._fade = motion.Tween(0.0)
        self._move = motion.Tween(0.0)
        self._proxy: QPixmap | None = None
        self.stage = Stage(T.SHEET, self)
        self.stage.page_clicked.connect(self._go_to_page)
        self.stage.hide()
        self.setFocusPolicy(Qt.StrongFocus)
        self._ticker = QTimer(self)
        self._ticker.setInterval(16)
        self._ticker.timeout.connect(self._on_tick)
        self.hide()
        parent.installEventFilter(self)
        self._sync_geometry()

    # ── Public ─────────────────────────────────────────────────────────────

    def set_flow(self, flow) -> None:
        self._flow = flow
        flow.changed.connect(self._on_flow_changed)

    def is_open(self) -> bool:
        return self._open

    def mode(self) -> str:
        return self._mode if self._open else ""

    def show_update(self) -> None:
        """Open on the flow's current state (or switch to it)."""
        if self._flow is None or self._flow.view() is None:
            return
        was_whats_new = self._open and self._mode == WHATS_NEW
        self._mode = UPDATE
        self._view_key = ""
        self._render_update(animate=self._open)
        if was_whats_new:
            self.closed.emit(WHATS_NEW)
        self._set_open(True)

    def show_whats_new(self, notes, release_url: str = "") -> None:
        """Open What's new at its first page."""
        if notes is None or not notes:
            return
        self._mode = WHATS_NEW
        self._notes = notes
        self._notes_url = release_url
        self._page = 0
        self.stage.set_pager(len(notes.highlights), T.HIGHLIGHT_COLORS, notes.more_text(), 0)
        self._render_page(animate=self._open, first=True)
        self._set_open(True)

    def hide_sheet(self) -> None:
        self._set_open(False)

    def toggle_update(self) -> None:
        if self._open and self._mode == UPDATE:
            self.hide_sheet()
        else:
            self.show_update()

    def texts(self) -> list[str]:
        return self.stage.copy.texts()

    # ── Update content ─────────────────────────────────────────────────────

    def _on_flow_changed(self) -> None:
        if not self._open or self._mode != UPDATE:
            return
        if self._flow.view() is None:
            self.hide_sheet()
            return
        self._render_update(animate=True)

    def _render_update(self, animate: bool) -> None:
        view = self._flow.view()
        if view is None:
            return
        stage = self.stage
        new_state = view.key != self._view_key
        if new_state:
            self._view_key = view.key
            variant = T.SHEET
            items = [Micro(view.micro, bad=view.micro_bad), Headline(view.headline)]
            if view.highlights:
                items.append(Highlights([
                    (title, T.HIGHLIGHT_COLORS[i % len(T.HIGHLIGHT_COLORS)])
                    for i, title in enumerate(view.highlights)]))
            if view.body:
                items.append(Body(view.body))
            buttons = []
            if view.primary is not None:
                gold = RcButton.gold(view.primary[0], variant)
                gold.clicked.connect(self._action(view.primary[1]))
                buttons.append(gold)
            if view.secondary is not None:
                ghost = RcButton.ghost(view.secondary[0], variant)
                ghost.clicked.connect(self._action(view.secondary[1]))
                buttons.append(ghost)
            if buttons:
                items.append(Actions(buttons))
            if view.link is not None:
                link = RcLink(view.link[0])
                link.clicked.connect(self._action(view.link[1]))
                items.append(Link(link))
            stage.copy.set_items(items, animate=animate)
            stage.set_steps([view.floor_label], single=True)
            stage.set_crew(2, view.crew_present, bad=view.crew_bad, animate=animate)
            if view.hop and animate:
                QTimer.singleShot(T.TOON_MOVE_MS, stage.hop)
        stage.set_label(view.floor_label, view.floor_tail)
        stage.set_fractions([view.fraction])
        stage.set_failed(0 if view.floor_bad else None)

    def _action(self, name: str):
        def run():
            method = getattr(self._flow, name, None)
            if method is not None:
                method()
        return run

    # ── What's new content ─────────────────────────────────────────────────

    def _render_page(self, animate: bool, first: bool = False) -> None:
        notes = self._notes
        count = len(notes.highlights)
        highlight = notes.highlights[self._page]
        last = self._page >= count - 1
        gold = RcButton.gold("Got it" if last else "Next", T.SHEET)
        gold.clicked.connect(self.hide_sheet if last else self._next_page)
        buttons = [gold]
        if self._notes_url:
            notes_button = RcButton.ghost("Release notes", T.SHEET, trail="ext")
            notes_button.clicked.connect(lambda: self.open_url.emit(self._notes_url))
            buttons.append(notes_button)
        self.stage.copy.set_items([
            Micro(f"New in {notes.version} · {self._page + 1} of {count}"),
            Headline(highlight.title),
            Body(highlight.text),
            Actions(buttons),
        ], animate=animate)
        # Toons 2, 3 and 4 present highlights 1, 2 and 3.
        self.stage.set_solo(min(4, self._page + 2), animate=animate)
        if not first:
            self.stage.set_page(self._page)

    def _next_page(self) -> None:
        self._go_to_page(self._page + 1)

    def _go_to_page(self, page: int) -> None:
        if self._mode != WHATS_NEW or self._notes is None:
            return
        page = max(0, min(len(self._notes.highlights) - 1, page))
        if page != self._page:
            self._page = page
            self._render_page(animate=True)

    def page(self) -> int:
        return self._page

    # ── Open and close ─────────────────────────────────────────────────────

    def _set_open(self, is_open: bool) -> None:
        if is_open == self._open:
            if is_open:
                self.raise_()
            return
        self._open = is_open
        self._sync_geometry()
        reduced = motion.is_reduced()
        if is_open:
            self.show()
            self.raise_()
            self.setFocus(Qt.OtherFocusReason)
            self.opened.emit(self._mode)
        else:
            # Hand the keyboard back to the window rather than letting Qt
            # pass it to the next widget in the chain (the header chip).
            parent = self.parentWidget()
            if parent is not None:
                parent.setFocus(Qt.OtherFocusReason)
        # The stage moves as a picture of itself, then the real one takes over.
        self.stage.ensurePolished()
        self._proxy = self.stage.grab()
        self.stage.hide()
        target = 1.0 if is_open else 0.0
        self._scrim.to(target, T.SCRIM_MS, T.EASE_SETTLE)
        self._fade.to(target, T.SHEET_FADE_MS, T.EASE_SETTLE)
        if reduced:
            self._move.snap(target)
        else:
            self._move.to(target, T.SHEET_MOVE_MS, T.EASE_ARRIVE)
        self._settling = True
        self._ticker.start()
        self.update()

    _settling = False

    def _on_tick(self) -> None:
        self.update()
        if self._scrim.active() or self._fade.active() or self._move.active():
            return
        self._ticker.stop()
        if not self._settling:
            return
        self._settling = False
        self._proxy = None
        if self._open:
            self.stage.show()
            self.stage.raise_()
        else:
            self.hide()
            self.closed.emit(self._mode)

    def is_animating(self) -> bool:
        return self._ticker.isActive()

    # ── Geometry and painting ──────────────────────────────────────────────

    def _sheet_rect(self) -> QRectF:
        return QRectF(T.SHEET_INSET, T.SHEET_INSET,
                      max(0, self.width() - 2 * T.SHEET_INSET), T.SHEET.height)

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(0, self._top, parent.width(), max(0, parent.height() - self._top))
        rect = self._sheet_rect()
        self.stage.setGeometry(int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height()))

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Resize:
            self._sync_geometry()
        return super().eventFilter(obj, event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        scrim = QColor(SCRIM)
        scrim.setAlphaF(SCRIM.alphaF() * max(0.0, min(1.0, self._scrim.value())))
        p.fillRect(self.rect(), scrim)
        rect = self._sheet_rect()
        fade = max(0.0, min(1.0, self._fade.value()))
        move = self._move.value()
        if fade <= 0.0:
            p.end()
            return
        p.setOpacity(fade)
        # From translateY(-20px) scale(.95), about the top centre.
        p.translate(rect.center().x(), rect.y())
        p.translate(0, SHUT_DROP * (1.0 - move))
        scale = SHUT_SCALE + (1.0 - SHUT_SCALE) * move
        p.scale(scale, scale)
        p.translate(-rect.center().x(), -rect.y())
        shadow, margin = paint.box_shadow(
            int(rect.width()), int(rect.height()), T.SHEET.radius, SHADOW_BLUR,
            SHADOW_ALPHA, self.devicePixelRatioF())
        p.drawPixmap(QPointF(rect.x() - margin, rect.y() - margin + SHADOW_DROP), shadow)
        if self._proxy is not None:
            p.drawPixmap(QPointF(rect.x(), rect.y()), self._proxy)
        p.end()

    # ── Input ──────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        # Anything that reaches the host missed the sheet: that is the scrim.
        if event.button() == Qt.LeftButton and self._open:
            self.hide_sheet()
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape and self._open:
            self.hide_sheet()
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            for control in self.stage.copy.controls():
                if getattr(control, "kind", "") == "gold":
                    control.click()
                    event.accept()
                    return
        super().keyPressEvent(event)
