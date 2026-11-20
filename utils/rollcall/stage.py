"""The stage: the blue background, the crew of toons, the floor of steps and
the copy column. Every Roll Call surface is one of these at one of three
sizes (``tokens.LARGE``, ``SMALL``, ``SHEET``).

The stage only shows what it is told. A surface (installer, update window,
uninstaller, the in-app sheets) sets the copy, the crew and the floor; the
stage animates between what it was showing and what it is told to show.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from utils.rollcall import fonts, motion, paint
from utils.rollcall import tokens as T
from utils.rollcall.controls import PAD, Lights, RcLink

# ── Copy items ─────────────────────────────────────────────────────────────


@dataclass
class Micro:
    text: str
    bad: bool = False


@dataclass
class Headline:
    text: str
    md: bool = False


@dataclass
class Body:
    """A paragraph. ``code`` spans are (start, length) ranges set in the mono
    face; build them with ``Body.with_code``."""

    text: str
    code: list = field(default_factory=list)

    @classmethod
    def with_code(cls, before: str, code: str, after: str = "") -> "Body":
        return cls(before + code + after, [(len(before), len(code))])


@dataclass
class Percent:
    text: str = "0%"


@dataclass
class Actions:
    buttons: list


@dataclass
class Link:
    control: RcLink


@dataclass
class Meta:
    text: str
    code: str = ""


@dataclass
class ErrorLine:
    text: str


@dataclass
class Highlights:
    rows: list          # (title, QColor)


@dataclass
class Control:
    widget: QWidget
    gap: int = 14


COPY_OVERHANG = 150      # the actions row may run wider than the text column


class CopyColumn(QWidget):
    """Micro line, headline, body and actions, vertically centred in the
    copy box. The whole column re-enters on every ``set_items`` (fade in and
    rise 7 px); ``set_headline`` re-enters the headline alone."""

    def __init__(self, variant: T.Variant, parent: QWidget):
        super().__init__(parent)
        self._v = variant
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._items: list = []
        self._blocks: list = []          # (item, y, painter-or-None)
        self._controls: list[QWidget] = []
        self._enter = motion.Tween(1.0)
        self._tick = motion.Tween(1.0)
        self._percent_text = ""
        self._ticker = QTimer(self)
        self._ticker.setInterval(16)
        self._ticker.timeout.connect(self._on_tick)

    # ── Content ────────────────────────────────────────────────────────────

    def set_items(self, items: list, animate: bool = True) -> None:
        for control in self._controls:
            control.hide()
            control.deleteLater()
        self._controls = []
        self._items = list(items)
        for item in self._items:
            if isinstance(item, Actions):
                for button in item.buttons:
                    self._adopt(button)
            elif isinstance(item, Link):
                self._adopt(item.control)
            elif isinstance(item, Control):
                self._adopt(item.widget)
            elif isinstance(item, Percent):
                self._percent_text = item.text
        self._tick.snap(1.0)
        self._relayout()
        if animate:
            self._enter.restart(0.0, 1.0, T.COPY_ENTER_MS, T.EASE_SETTLE)
            self._ticker.start()
        else:
            self._enter.snap(1.0)
        self._apply_enter()
        self.update()

    def _adopt(self, control: QWidget) -> None:
        control.setParent(self)
        control.show()
        self._controls.append(control)

    def set_headline(self, text: str) -> None:
        """Change the headline in place; only its text re-enters."""
        for item in self._items:
            if isinstance(item, Headline):
                if item.text == text:
                    return
                item.text = text
                self._relayout()
                self._tick.restart(0.0, 1.0, T.TICK_ENTER_MS, T.EASE_SETTLE)
                self._ticker.start()
                self.update()
                return

    def set_micro(self, text: str) -> None:
        for item in self._items:
            if isinstance(item, Micro) and item.text != text:
                item.text = text
                self._relayout()
                self.update()
                return

    def set_percent(self, text: str) -> None:
        if text != self._percent_text:
            self._percent_text = text
            self.update()

    def headline_text(self) -> str:
        return next((i.text for i in self._items if isinstance(i, Headline)), "")

    def texts(self) -> list[str]:
        """Every line of copy on screen, top to bottom (tests, accessibility)."""
        out = []
        for item in self._items:
            if isinstance(item, (Micro, Headline, ErrorLine)):
                out.append(item.text)
            elif isinstance(item, Body):
                out.append(item.text)
            elif isinstance(item, Percent):
                out.append(self._percent_text)
            elif isinstance(item, Meta):
                out.append(item.text + item.code)
            elif isinstance(item, Highlights):
                out.extend(title for title, _c in item.rows)
            elif isinstance(item, Actions):
                out.extend(b.text() for b in item.buttons)
            elif isinstance(item, Link):
                out.append(item.control.text())
        return out

    def controls(self) -> list[QWidget]:
        return list(self._controls)

    # ── Layout ─────────────────────────────────────────────────────────────

    def _relayout(self) -> None:
        v = self._v
        width = v.copy_width
        blocks = []
        y = 0.0
        first = True
        for item in self._items:
            gap = 0.0
            block = None
            height = 0.0
            if isinstance(item, Micro):
                font = fonts.ui(10, 800, spacing=0.8)
                block = paint.TextBlock(
                    item.text.upper(), font, T.ERROR_TEXT if item.bad else T.white(0.72),
                    width, 12, single_line=True)
                height = 12
            elif isinstance(item, Headline):
                px = v.headline_md_px if item.md else v.headline_px
                block = paint.TextBlock(
                    item.text, fonts.display(px), QColor("#ffffff"), width, px * 1.04,
                    balance=True, shadow=T.rgba(0, 0, 0, 0.16), shadow_dy=2)
                gap, height = 8, block.height
            elif isinstance(item, Body):
                runs: list = []
                position = 0
                for start, length in item.code:
                    if start > position:
                        runs.append((item.text[position:start], None, None))
                    runs.append((item.text[start:start + length], fonts.mono(12, 500), None))
                    position = start + length
                if position < len(item.text):
                    runs.append((item.text[position:], None, None))
                block = paint.TextBlock(runs or item.text, fonts.ui(13, 400),
                                        T.white(0.84), width, 13 * 1.45)
                gap, height = 10, block.height
            elif isinstance(item, Percent):
                gap, height = 8, 46
            elif isinstance(item, Actions):
                gap = v.actions_gap_top
                height = max((b.height() - 2 * PAD for b in item.buttons), default=0)
            elif isinstance(item, Link):
                gap, height = 12, item.control.height() - 2 * PAD
            elif isinstance(item, Meta):
                gap, height = 12, 14
            elif isinstance(item, ErrorLine):
                block = paint.TextBlock(item.text, fonts.mono(10, 500), T.white(0.70),
                                        width + 40, 13)
                gap, height = 8, block.height
            elif isinstance(item, Highlights):
                gap = 10
                height = len(item.rows) * 15 + max(0, len(item.rows) - 1) * 5
            elif isinstance(item, Control):
                gap, height = item.gap, item.widget.height() - 2 * PAD
            if not first:
                y += gap
            first = False
            blocks.append((item, y, block))
            y += height
        box_h = self.height()
        top = max(0.0, (box_h - y) / 2.0)
        self._blocks = [(item, top + by, block) for item, by, block in blocks]

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()
        self._apply_enter()

    def _rise(self) -> float:
        if motion.is_reduced():
            return 0.0
        return (1.0 - self._enter.value()) * T.RISE_PX

    def _apply_enter(self) -> None:
        """Place and fade the child controls for this frame."""
        alpha = max(0.0, min(1.0, self._enter.value()))
        dy = self._rise()
        for item, y, _block in self._blocks:
            if isinstance(item, Actions):
                x = 0.0
                for button in item.buttons:
                    button.move(round(PAD + x) - PAD, round(y + dy) - PAD)
                    button.set_fade(alpha)
                    x += button.width() - 2 * PAD + 8
            elif isinstance(item, Link):
                item.control.move(0, round(y + dy) - PAD)
                item.control.set_fade(alpha)
            elif isinstance(item, Control):
                item.widget.move(0, round(y + dy) - PAD)
                if hasattr(item.widget, "set_fade"):
                    item.widget.set_fade(alpha)

    def _on_tick(self) -> None:
        self._apply_enter()
        self.update()
        if not (self._enter.active() or self._tick.active()):
            self._ticker.stop()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        alpha = max(0.0, min(1.0, self._enter.value()))
        dy = self._rise()
        p.setOpacity(alpha)
        x0 = float(PAD)
        for item, y, block in self._blocks:
            y += dy
            if isinstance(item, Headline):
                tick = max(0.0, min(1.0, self._tick.value()))
                rise = 0.0 if motion.is_reduced() else (1.0 - self._tick.value()) * T.RISE_PX
                block.draw(p, x0, y + rise, tick)
            elif block is not None:
                block.draw(p, x0, y)
            elif isinstance(item, Percent):
                font = fonts.mono(46, 700, spacing=-0.03 * 46)
                paint.draw_text_line(p, self._percent_text, font, QColor("#ffffff"),
                                     QRectF(x0, y, 320, 46))
            elif isinstance(item, Meta):
                ui = fonts.ui(11, 400)
                lead_w = paint.text_width(item.text, ui)
                paint.draw_text_line(p, item.text, ui, T.white(0.70),
                                     QRectF(x0, y, lead_w + 2, 14))
                if item.code:
                    mono = fonts.mono(10, 500)
                    room = self._v.copy_width - lead_w
                    code = QFontMetricsF(mono).elidedText(item.code, Qt.ElideMiddle, int(room))
                    paint.draw_text_line(p, code, mono, T.white(0.70),
                                         QRectF(x0 + lead_w, y, room + 4, 14))
            elif isinstance(item, Highlights):
                font = fonts.ui(12, 600)
                row_y = y
                for title, color in item.rows:
                    p.setPen(Qt.NoPen)
                    p.setBrush(color)
                    p.drawEllipse(QPointF(x0 + 3.5, row_y + 7.5), 3.5, 3.5)
                    paint.draw_text_line(p, title, font, QColor("#ffffff"),
                                         QRectF(x0 + 15, row_y, self._v.copy_width - 15, 15))
                    row_y += 20
        p.end()


# ── Crew ───────────────────────────────────────────────────────────────────


class _Slot:
    def __init__(self) -> None:
        self.present = False
        self.fade = motion.Tween(0.0)       # the toon's opacity
        self.move = motion.Tween(0.0)       # 0 = dropped and small, 1 = in place

    def set_present(self, present: bool, animate: bool) -> None:
        if present == self.present and not (self.fade.active() or self.move.active()):
            if not animate:
                self.fade.snap(1.0 if present else 0.0)
                self.move.snap(1.0 if present else 0.0)
            return
        self.present = present
        target = 1.0 if present else 0.0
        if animate:
            self.fade.to(target, T.TOON_FADE_MS, T.EASE_SETTLE)
            self.move.to(target, T.TOON_MOVE_MS, T.EASE_ARRIVE)
        else:
            self.fade.snap(target)
            self.move.snap(target)

    def active(self) -> bool:
        return self.fade.active() or self.move.active()


class Stage(QWidget):
    """One Roll Call surface's picture."""

    page_clicked = Signal(int)
    background_pressed = Signal(object)     # QMouseEvent on empty stage (window drag)

    def __init__(self, variant: T.Variant, parent: QWidget | None = None):
        super().__init__(parent)
        self.variant = variant
        if variant.width:
            self.setFixedSize(variant.width, variant.height)
        else:
            self.setFixedHeight(variant.height)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        fonts.ensure_loaded()

        self._slots: list[_Slot] = [_Slot() for _ in range(4)]
        self._count = 4
        self._bad: int | None = None
        self._hop_t0: float | None = None
        self._solo: int | None = None
        self._solo_rise = motion.Tween(1.0)

        self._labels: list[str] = []
        self._fractions: list[float] = []
        self._reverse = False
        self._single = False
        self._failed: int | None = None
        self._tail = ""
        self._all_done = False
        self._follower: motion.RunFollower | None = None

        self._pager: tuple | None = None            # (count, colors, more)
        self._page = 0
        self._pill_w: list[motion.Tween] = []

        self.copy = CopyColumn(variant, self)
        self.lights: Lights | None = Lights(self) if variant.lights else None
        self._place_children()

        self._ticker = QTimer(self)
        self._ticker.setInterval(16)
        self._ticker.timeout.connect(self._on_tick)

    # ── Crew ───────────────────────────────────────────────────────────────

    def set_crew(self, count: int, present: int, *, bad: int | None = None,
                 animate: bool = True) -> None:
        """``count`` slots, the first ``present`` of them filled. ``bad`` is
        the slot whose toon is missing because its step failed."""
        self._solo = None
        self._count = max(0, min(4, count))
        self._bad = bad
        for i, slot in enumerate(self._slots):
            slot.set_present(i < present and i < self._count and i != bad, animate)
        self._kick()

    def crew_present(self) -> int:
        return sum(1 for s in self._slots[:self._count] if s.present)

    def crew_bad(self) -> int | None:
        return self._bad

    def hop(self) -> None:
        """Everyone hops, one after the other."""
        if motion.is_reduced():
            return
        self._hop_t0 = motion.now()
        self._kick()

    def set_solo(self, toon: int | None, animate: bool = True) -> None:
        """One large toon presenting (What's new). ``toon`` is 1-4."""
        self._solo = toon
        if toon is not None:
            if animate:
                self._solo_rise.restart(0.0, 1.0, T.SOLO_RISE_MS, T.EASE_ARRIVE)
            else:
                self._solo_rise.snap(1.0)
        self._kick()

    def solo(self) -> int | None:
        return self._solo

    # ── Floor ──────────────────────────────────────────────────────────────

    def set_steps(self, labels, *, reverse: bool = False, single: bool = False) -> None:
        self._pager = None
        self._labels = list(labels)
        self._reverse = reverse
        self._single = single
        self._fractions = [0.0] * len(self._labels)
        self._failed = None
        self._all_done = False
        self._follower = None
        self.update()

    def set_label(self, text: str, tail: str = "") -> None:
        """The single-segment floor's label and its right-aligned tail."""
        if self._labels != [text] or tail != self._tail:
            self._labels = [text]
            if len(self._fractions) != 1:
                self._fractions = [0.0]
            self._tail = tail
            self.update()

    def set_fractions(self, fractions) -> None:
        self._follower = None
        self._fractions = [max(0.0, min(1.0, float(f))) for f in fractions]
        self._all_done = False
        self.update()

    def follow(self, follower: motion.RunFollower | None) -> None:
        """Paint the floor from a live run until told otherwise."""
        self._follower = follower
        self._all_done = False
        self._kick()

    def set_failed(self, step: int | None) -> None:
        self._failed = step
        self.update()

    def set_all_done(self) -> None:
        self._follower = None
        self._fractions = [1.0] * len(self._labels)
        self._failed = None
        self._all_done = True
        self.update()

    def floor_fractions(self) -> list[float]:
        if self._follower is not None:
            return list(self._follower.shown)
        return list(self._fractions)

    def floor_labels(self) -> list[str]:
        return list(self._labels)

    def floor_tail(self) -> str:
        return self._tail

    def floor_failed(self) -> int | None:
        return self._failed

    def set_pager(self, count: int, colors, more: str, page: int = 0) -> None:
        """Replace the floor with the What's new pager."""
        self._pager = (count, list(colors), more)
        self._page = page
        self._pill_w = [motion.Tween(38.0 if i == page else 22.0) for i in range(count)]
        self.update()

    def set_page(self, page: int) -> None:
        if self._pager is None or page == self._page:
            return
        self._page = page
        for i, tween in enumerate(self._pill_w):
            tween.to(38.0 if i == page else 22.0, 300, T.EASE_SETTLE)
        self._kick()

    def page(self) -> int:
        return self._page

    # ── Animation ──────────────────────────────────────────────────────────

    def _animating(self) -> bool:
        if any(slot.active() for slot in self._slots):
            return True
        if self._hop_t0 is not None:
            if motion.now() - self._hop_t0 < T.HOP_MS + 4 * T.HOP_STAGGER_MS:
                return True
            self._hop_t0 = None
        if self._solo_rise.active() or any(t.active() for t in self._pill_w):
            return True
        return False

    def _kick(self) -> None:
        if not self._ticker.isActive():
            self._ticker.start()
        self.update()

    def _on_tick(self) -> None:
        moving = self._animating()
        if self._follower is not None:
            moving = self._follower.frame() or moving or not self._follower.held
        self.update()
        if not moving:
            self._ticker.stop()

    def is_animating(self) -> bool:
        return self._ticker.isActive()

    # ── Geometry ───────────────────────────────────────────────────────────

    def _place_children(self) -> None:
        v = self.variant
        box_h = self.height() - v.copy_top - v.copy_bottom
        self.copy.setGeometry(v.copy_left - PAD, v.copy_top,
                              v.copy_width + COPY_OVERHANG, max(0, box_h))
        if self.lights is not None:
            self.lights.move(self.width() - T.LIGHT_INSET - self.lights.width(), T.LIGHT_INSET)
            self.lights.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_children()

    def slot_rect(self, index: int) -> QRectF:
        v = self.variant
        size = v.toon_size
        top = self.height() - v.toon_bottom - size
        if v.width:
            left = v.crew_x + v.toon_first_dx + index * v.toon_pitch
        else:
            # The sheet: the crew is pinned right, the last toon's box flush
            # with the sheet's right edge.
            left = self.width() - size - (self._count - 1 - index) * v.toon_pitch
        return QRectF(left, top, size, size)

    def floor_rect(self) -> QRectF:
        h = self.variant.floor_h
        return QRectF(0, self.height() - h, self.width(), h)

    def _pill_rects(self) -> list[QRectF]:
        floor = self.floor_rect()
        x = 22.0
        rects = []
        for tween in self._pill_w:
            w = tween.value()
            rects.append(QRectF(x, floor.center().y() - 4 + 0.5, w, 8))
            x += w + 7
        return rects

    def mousePressEvent(self, event) -> None:
        if self._pager is not None and event.button() == Qt.LeftButton:
            for i, rect in enumerate(self._pill_rects()):
                if rect.adjusted(-3, -8, 3, 8).contains(event.position()):
                    self.page_clicked.emit(i)
                    event.accept()
                    return
        self.background_pressed.emit(event)
        event.accept()

    # ── Painting ───────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        v = self.variant
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        rect = QRectF(self.rect())
        dpr = self.devicePixelRatioF()

        p.drawPixmap(QPointF(0, 0), paint.stage_background(self.size(), dpr, v.radius))

        if v.mark is not None:
            left, top, height = v.mark
            mark = paint.wordmark(height, dpr)
            if not mark.isNull():
                p.drawPixmap(QPointF(left, top), mark)

        if self._solo is not None:
            self._paint_solo(p, dpr)
        else:
            self._paint_crew(p, dpr)

        if self._pager is not None:
            self._paint_pager(p, rect)
        else:
            self._paint_floor(p, rect)

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(T.white(v.border_alpha), 1.0))
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), v.radius - 0.5, v.radius - 0.5)
        p.end()

    def _hop_offset(self, index: int) -> float:
        if self._hop_t0 is None:
            return 0.0
        t = (motion.now() - self._hop_t0 - index * T.HOP_STAGGER_MS) / T.HOP_MS
        if t <= 0.0 or t >= 1.0:
            return 0.0
        if t < 0.4:
            return T.HOP_PX * T.EASE_HOP.valueForProgress(t / 0.4)
        return T.HOP_PX * (1.0 - T.EASE_HOP.valueForProgress((t - 0.4) / 0.6))

    def _paint_crew(self, p: QPainter, dpr: float) -> None:
        v = self.variant
        reduced = motion.is_reduced()
        # Even slots stack above odd ones.
        order = [i for i in range(self._count) if i % 2] + \
                [i for i in range(self._count) if not i % 2]
        for i in order:
            slot = self._slots[i]
            rect = self.slot_rect(i)
            fade = max(0.0, min(1.0, slot.fade.value()))
            is_bad = i == self._bad
            if (v.placeholders or is_bad) and (is_bad or fade < 1.0):
                self._paint_placeholder(p, rect, i, is_bad, 1.0 if is_bad else 1.0 - fade)
            if fade <= 0.0:
                continue
            pixmap = paint.toon_pixmap(i + 1, v.toon_pose, v.toon_size, dpr)
            if pixmap.isNull():
                continue
            move = 1.0 if reduced else slot.move.value()
            p.save()
            p.setOpacity(fade)
            p.translate(rect.center().x(), rect.bottom())
            p.translate(0, T.TOON_DROP_PX * (1.0 - move) - self._hop_offset(i))
            scale = T.TOON_SMALL_SCALE + (1.0 - T.TOON_SMALL_SCALE) * move
            p.scale(scale, scale)
            p.rotate(T.SLOT_TILTS[i])
            p.drawPixmap(QPointF(-v.toon_size / 2.0 - paint.TOON_PAD,
                                 -v.toon_size - paint.TOON_PAD), pixmap)
            p.restore()

    def _paint_placeholder(self, p: QPainter, rect: QRectF, index: int,
                           bad: bool, opacity: float) -> None:
        if opacity <= 0.0:
            return
        p.save()
        p.setOpacity(opacity)
        centre = QPointF(rect.center().x(), rect.bottom() - 0.16 * rect.height() - 38)
        pen = QPen(T.RED_B if bad else T.white(0.40), 2.0)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([3.0, 2.2])
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.setBrush(T.rgba(224, 82, 82, 0.16) if bad else Qt.NoBrush)
        p.drawEllipse(centre, 37, 37)
        paint.draw_text_line(
            p, "!" if bad else str(index + 1), fonts.ui(15, 700),
            T.ERROR_TEXT if bad else T.white(0.62),
            QRectF(centre.x() - 38, centre.y() - 38, 76, 76), Qt.AlignCenter)
        p.restore()

    def _paint_solo(self, p: QPainter, dpr: float) -> None:
        size = T.SOLO_SIZE
        pixmap = paint.toon_pixmap(self._solo, "bust", size, dpr)
        if pixmap.isNull():
            return
        rise = self._solo_rise.value()
        left = self.width() - size - T.SOLO_RIGHT
        top = self.height() - self.variant.toon_bottom - size
        p.save()
        p.setOpacity(max(0.0, min(1.0, self._solo_rise.progress() * 2.0)) if rise < 1.0 else 1.0)
        p.translate(left + size / 2.0, top + size / 2.0)
        if not motion.is_reduced():
            p.translate(0, T.TOON_DROP_PX * (1.0 - rise))
            scale = T.TOON_SMALL_SCALE + (1.0 - T.TOON_SMALL_SCALE) * rise
            p.scale(scale, scale)
        p.drawPixmap(QPointF(-size / 2.0 - paint.TOON_PAD, -size / 2.0 - paint.TOON_PAD), pixmap)
        p.restore()

    def _floor_path(self, rect: QRectF) -> QPainterPath:
        floor = QPainterPath()
        floor.addRect(self.floor_rect())
        return floor.intersected(paint.rounded_path(rect, self.variant.radius))

    def _paint_floor(self, p: QPainter, rect: QRectF) -> None:
        floor = self.floor_rect()
        p.setPen(Qt.NoPen)
        p.setBrush(T.FLOOR_BG)
        p.drawPath(self._floor_path(rect))
        p.fillRect(QRectF(floor.x(), floor.y(), floor.width(), 1), T.white(0.12))
        count = len(self._labels)
        if not count:
            return
        fractions = self.floor_fractions()
        if len(fractions) != count:
            fractions = (fractions + [0.0] * count)[:count]
        top = floor.y() + 1
        seg_w = floor.width() / count
        content_cy = top + 5 + (floor.height() - 1 - 5) / 2.0
        live = self._follower.step if self._follower is not None else None
        for i, label in enumerate(self._labels):
            x = floor.x() + i * seg_w
            d = 1.0 if self._all_done else fractions[i]
            fill = 1.0 - d if self._reverse else d
            failed = self._failed == i
            done = not self._reverse and d >= 1.0 and not failed
            active = failed or (0.0 < d < 1.0) or (live == i and d < 1.0 and not self._all_done)
            if i:
                p.fillRect(QRectF(x, top, 1, floor.height() - 1), T.white(0.08))
            p.fillRect(QRectF(x, top, seg_w, 5), T.white(0.10))
            if fill > 0.0:
                p.fillRect(QRectF(x, top, seg_w * fill, 5), T.RED_B if failed else T.BLUE_B)
            text_x = x + 14 + (1 if i else 0)
            if self._single:
                color = QColor("#ffffff") if (active or failed) else T.white(0.62)
                if self._tail:
                    mono = fonts.mono(11, 500)
                    tail_w = paint.text_width(self._tail, mono) + 2
                    paint.draw_text_line(
                        p, self._tail, mono, T.white(0.80),
                        QRectF(x + seg_w - 14 - tail_w, content_cy - 10, tail_w, 20),
                        Qt.AlignRight | Qt.AlignVCenter)
                paint.draw_text_line(p, label, fonts.ui(12, 600), color,
                                     QRectF(text_x, content_cy - 10, seg_w - 28, 20))
                continue
            centre = QPointF(text_x + 11, content_cy)
            if failed:
                badge_bg, label_color = T.RED, QColor("#ffffff")
            elif done:
                badge_bg, label_color = T.GREEN, T.white(0.86)
            elif active:
                badge_bg, label_color = T.BLUE, QColor("#ffffff")
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(T.rgba(51, 153, 255, 0.4), 2.0))
                p.drawEllipse(centre, 12, 12)
            else:
                badge_bg, label_color = T.white(0.10), T.white(0.62)
            p.setPen(Qt.NoPen)
            p.setBrush(badge_bg)
            p.drawEllipse(centre, 11, 11)
            if done:
                paint.draw_icon(p, "check", QRectF(centre.x() - 6, centre.y() - 6, 12, 12),
                                QColor("#ffffff"))
            else:
                paint.draw_text_line(
                    p, "!" if failed else str(i + 1), fonts.ui(11, 700),
                    QColor("#ffffff") if (failed or active) else T.white(0.80),
                    QRectF(centre.x() - 11, centre.y() - 11, 22, 22), Qt.AlignCenter)
            paint.draw_text_line(p, label, fonts.ui(12, 600), label_color,
                                 QRectF(text_x + 22 + 9, content_cy - 10, seg_w - 50, 20))

    def _paint_pager(self, p: QPainter, rect: QRectF) -> None:
        floor = self.floor_rect()
        count, colors, more = self._pager
        p.setPen(Qt.NoPen)
        p.setBrush(T.FLOOR_BG)
        p.drawPath(self._floor_path(rect))
        p.fillRect(QRectF(floor.x(), floor.y(), floor.width(), 1), T.white(0.12))
        for i, pill in enumerate(self._pill_rects()):
            p.setBrush(colors[i % len(colors)] if i == self._page else T.white(0.22))
            p.drawRoundedRect(pill, 4, 4)
        if more:
            paint.draw_text_line(
                p, more, fonts.ui(11, 400), T.white(0.72),
                QRectF(floor.x(), floor.y() + 1, floor.width() - 22, floor.height() - 1),
                Qt.AlignRight | Qt.AlignVCenter)
