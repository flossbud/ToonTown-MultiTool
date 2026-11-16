"""The home block's panel: the quick menu, and the compact launcher it
swaps to. One card in brand blue, left-aligned under the app icon on toon
1's strip."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFontMetricsF, QPainter,
                           QPainterPath, QPen, QPolygonF)
from PySide6.QtWidgets import QWidget

from utils import icon_factory
from utils.strips import glyphs, paint, tokens
from utils.strips.launcher_port import LAUNCHING, RUNNING
from utils.strips.tokens import dk, lt, tr

MENU = "menu"
LAUNCH = "launch"

BLUE = tokens.BRAND_BLUE
RED, GREEN, GREY = "#E05252", "#3da343", "#888888"
GAME_COLOURS = {"ttr": "#4A8FE7", "cc": "#F26D21"}
GAME_NAMES = {"ttr": "TOONTOWN REWRITTEN", "cc": "CORPORATE CLASH"}

MARGIN = 18.0
CARET = 10.0
CARET_RISE = 8.0
BORDER = 2.0
PAD = 6.0
MENU_W = 236.0
LAUNCH_W = 260.0
ROW_H = 34.0
ICON = 24.0
ACCOUNT_H = 26.0

# Row keys.
LAUNCH_ACCOUNTS, SETTINGS, OPEN_WINDOW, TOGGLE_RUNNING, QUIT = (
    "launch", "settings", "window", "toggle", "quit")


class HomePanel(QWidget):
    row_chosen = Signal(str)          # SETTINGS | OPEN_WINDOW | TOGGLE_RUNNING | QUIT
    launch_requested = Signal(str)    # account id
    full_launcher_requested = Signal()
    view_changed = Signal(str)        # MENU | LAUNCH: the card changed size

    # Read by the popover manager.
    ANCHOR_GAP = 10.0 - CARET_RISE    # the card sits 10 px under the block
    LEFT_INSET = MARGIN               # the card, not its halo, lines up with the block

    def __init__(self, style_name: str = tokens.NEON, scale: float = 1.0,
                 running: bool = True, accounts=(), can_launch: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._style = tokens.style_for(style_name)
        self._scale = float(scale) if scale and scale > 0 else 1.0
        self._running = bool(running)
        self._accounts = tuple(accounts)
        self._can_launch = bool(can_launch)   # False: no launcher to drive
        self._view = MENU
        self._caret_x: float | None = None
        self._flipped = False
        self._hover: tuple | None = None
        self._pressed: tuple | None = None
        self._zones: list[tuple[tuple, QRectF]] = []
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)
        self._relayout()

    # -- state --------------------------------------------------------------

    def view(self) -> str:
        return self._view

    def set_view(self, view: str) -> None:
        view = LAUNCH if view == LAUNCH else MENU
        if view != self._view:
            self._view = view
            self._hover = self._pressed = None
            self._relayout()
            self.view_changed.emit(view)

    def set_running(self, running: bool) -> None:
        if bool(running) != self._running:
            self._running = bool(running)
            self._relayout()

    def accounts(self) -> tuple:
        return self._accounts

    def set_accounts(self, accounts) -> None:
        accounts = tuple(accounts)
        if accounts != self._accounts:
            before = self.sizeHint()
            self._accounts = accounts
            self._relayout()
            if self.sizeHint() != before:
                self.view_changed.emit(self._view)

    def running_count(self) -> int:
        return sum(1 for a in self._accounts if a.state == RUNNING)

    def set_caret_x(self, widget_x: float) -> None:
        self._caret_x = widget_x / self._scale
        self.update()

    def set_flipped(self, flipped: bool) -> None:
        if bool(flipped) != self._flipped:
            self._flipped = bool(flipped)
            self.update()

    def rows(self) -> list[tuple[str, str, str, str]]:
        """(key, colour, label, hint) for the quick menu, top to bottom;
        ("", ...) is the divider."""
        hint = ""
        if self._can_launch and self._accounts:
            hint = f"{self.running_count()} running ›"
        return [
            (LAUNCH_ACCOUNTS, RED, "Launch accounts", hint),
            (SETTINGS, GREEN, "Settings", ""),
            (OPEN_WINDOW, BLUE, "Open MultiTool", ""),
            ("", "", "", ""),
            (TOGGLE_RUNNING, GREY,
             "Stop all toons" if self._running else "Start all toons", ""),
            (QUIT, GREY, "Quit MultiTool", ""),
        ]

    # -- geometry -----------------------------------------------------------

    def _fonts(self):
        return {
            "row": paint.strip_font(13, 600),
            "hint": paint.strip_font(11, 400),
            "title": paint.strip_font(13, 700),
            "section": paint.strip_font(10, 600),
            "account": paint.strip_font(13, 600),
            "status": paint.strip_font(11, 400),
            "button": paint.strip_font(11, 700),
            "footer": paint.strip_font(12, 600),
        }

    def _relayout(self) -> None:
        zones: list[tuple[tuple, QRectF]] = []
        left, top = MARGIN, CARET_RISE
        width = MENU_W if self._view == MENU else LAUNCH_W
        x0 = left + BORDER + PAD
        inner = width - 2 * (BORDER + PAD)
        y = top + BORDER + PAD
        self._dividers: list[float] = []
        self._sections: list[tuple[str, float]] = []
        self._account_rows: list[tuple[object, QRectF]] = []
        if self._view == MENU:
            for key, _colour, _label, _hint in self.rows():
                if not key:
                    self._dividers.append(y + 5.0)
                    y += 11.0 + 1.0
                    continue
                zones.append((("row", key), QRectF(x0, y, inner, ROW_H)))
                y += ROW_H + 1.0
            y -= 1.0
        else:
            zones.append((("back",), QRectF(x0, y + 2.0, 24.0, 24.0)))
            self._title_y = y + 2.0
            y += 28.0
            fm = QFontMetricsF(self._fonts()["button"])
            button_w = fm.horizontalAdvance("Launch") + 20.0
            for game in ("ttr", "cc"):
                group = [a for a in self._accounts if a.game == game]
                if not group:
                    continue
                self._sections.append((game, y + 8.0))
                y += 8.0 + 12.0 + 4.0
                for account in group:
                    row = QRectF(x0, y, inner, ACCOUNT_H)
                    self._account_rows.append((account, row))
                    if account.state not in (RUNNING, LAUNCHING) and self._can_launch:
                        zones.append((("go", account.account_id), QRectF(
                            row.right() - 6.0 - button_w, y + 1.0, button_w, 24.0)))
                    y += ACCOUNT_H
            self._dividers.append(y + 8.0)
            y += 8.0 + 1.0 + 4.0
            footer_h = QFontMetricsF(self._fonts()["footer"]).height() + 12.0
            zones.append((("full",), QRectF(x0, y, inner, footer_h)))
            y += footer_h
        y += PAD + BORDER
        self._card = QRectF(left, top, width, y - top)
        self._zones = zones
        self._design = QSize(int(round(width + 2 * MARGIN)), int(round(y + MARGIN)))
        self.setFixedSize(self.sizeHint())
        self.update()

    def sizeHint(self) -> QSize:
        k = self._scale
        return QSize(int(round(self._design.width() * k)),
                     int(round(self._design.height() * k)))

    def _to_widget(self, r: QRectF) -> QRectF:
        k = self._scale
        return QRectF(r.x() * k, r.y() * k, r.width() * k, r.height() * k)

    def zone_rect(self, *key) -> QRectF | None:
        """("row", key), ("back",), ("go", account id) or ("full",)."""
        for zone, rect in self._zones:
            if zone == tuple(key):
                return self._to_widget(rect)
        return None

    def card_rect(self) -> QRectF:
        return self._to_widget(self._card)

    def input_rects(self) -> list[QRect]:
        return [self.card_rect().toAlignedRect()]

    # -- painting -----------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        self.render_panel(p)
        p.end()

    def _lit(self, p: QPainter, rect: QRectF, colour: str, radius: float) -> None:
        """An icon block or button in the lit style of its colour."""
        if self._style.is_neon:
            paint.paint_glow(p, rect, radius, tr(colour, 45), 8.0)
            p.fillPath(paint.rounded(rect, radius), QColor(colour))
            paint._border(p, paint.rounded, rect, radius, 2.0, QColor(lt(colour, 62)))
        else:
            p.fillPath(paint.rounded(rect, radius), QColor(colour))

    def _icon(self, p: QPainter, rect: QRectF, key: str) -> None:
        white = QColor("#ffffff")
        box = glyphs.centred_square(rect, 13.0)
        if key == LAUNCH_ACCOUNTS:
            glyphs.paint_power(p, box, white)
        elif key == QUIT:
            glyphs.paint_close(p, box, white)
        elif key == TOGGLE_RUNNING:
            small = glyphs.centred_square(rect, 12.0)
            p.save()
            p.translate(small.x(), small.y())
            p.scale(small.width() / 24.0, small.height() / 24.0)
            p.setPen(Qt.NoPen)
            p.setBrush(white)
            if self._running:
                p.drawRoundedRect(QRectF(5.0, 5.0, 14.0, 14.0), 2.0, 2.0)
            else:
                p.drawPolygon(QPolygonF([QPointF(6.0, 4.0), QPointF(20.0, 12.0),
                                         QPointF(6.0, 20.0)]))
            p.restore()
        else:
            # The app's own gear and window glyphs, drawn at device size.
            px = max(1, int(round(box.width() * paint._device_scale(p))))
            make = (icon_factory.make_nav_gear if key == SETTINGS
                    else icon_factory.make_window_icon)
            pm = make(px, white).pixmap(px, px)
            p.save()
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawPixmap(box, pm, QRectF(pm.rect()))
            p.restore()

    def render_panel(self, p: QPainter) -> None:
        neon = self._style.is_neon
        white = QColor("#ffffff")
        fonts = self._fonts()
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.scale(self._scale, self._scale)
        card = self._card
        radius = 10.0 if neon else 5.0
        if neon:
            paint.paint_glow(p, card.translated(0, 8), radius, tokens.rgba(0, 0, 0, 0.4), 22.0)
            paint.paint_glow(p, card, radius, tr(BLUE, 42), 16.0)
            fill = QBrush(tokens.css_gradient(card, tokens.BODY_ANGLE, dk(BLUE, 24), dk(BLUE, 11)))
            caret_fill = QColor(dk(BLUE, 22))
        else:
            fill = QBrush(QColor(tokens.POPOVER_BASE))
            caret_fill = QColor(tokens.POPOVER_BASE)
        p.fillPath(paint.rounded(card, radius), fill)
        paint._border(p, paint.rounded, card, radius, BORDER, QColor(BLUE))
        if not self._flipped:
            cx = self._caret_x if self._caret_x is not None else card.left() + 13.0
            cx = max(card.left() + radius + 4.0, min(cx, card.right() - radius - 4.0))
            half = CARET * 0.7071
            tip = QPointF(cx, card.top() - half + BORDER * 0.5)
            p.setPen(Qt.NoPen)
            p.setBrush(caret_fill)
            p.drawPolygon(QPolygonF([tip, QPointF(cx + half, card.top() + BORDER),
                                     QPointF(cx - half, card.top() + BORDER)]))
            pen = QPen(QColor(BLUE), BORDER)
            p.setPen(pen)
            p.drawLine(QPointF(cx - half, card.top() + BORDER * 0.5), tip)
            p.drawLine(tip, QPointF(cx + half, card.top() + BORDER * 0.5))
        inner_l = card.left() + BORDER + PAD
        inner_r = card.right() - BORDER - PAD
        for y in self._dividers:
            p.fillRect(QRectF(inner_l + 6.0, y, inner_r - inner_l - 12.0, 1.0),
                       tokens.rgba(255, 255, 255, 0.14))
        if self._view == MENU:
            self._paint_menu(p, fonts, white)
        else:
            self._paint_launch(p, fonts, white)
        p.restore()

    def _paint_menu(self, p, fonts, white) -> None:
        neon = self._style.is_neon
        rows = {key: (colour, label, hint) for key, colour, label, hint in self.rows() if key}
        for zone, rect in self._zones:
            if zone[0] != "row":
                continue
            colour, label, hint = rows[zone[1]]
            if self._hover == zone:
                p.fillPath(paint.rounded(rect, 7.0 if neon else 4.0),
                           tokens.rgba(255, 255, 255, 0.09))
            icon = QRectF(rect.left() + 6.0, rect.center().y() - ICON / 2.0, ICON, ICON)
            if self._pressed == zone:
                icon.translate(0.0, 1.0)
            self._lit(p, icon, colour, 6.0 if neon else 4.0)
            self._icon(p, icon, zone[1])
            text = QRectF(icon.right() + 10.0, rect.top(), rect.right() - 8.0 - icon.right() - 10.0,
                          rect.height())
            paint._text(p, text, label, fonts["row"], white, Qt.AlignLeft | Qt.AlignVCenter)
            if hint:
                paint._text(p, text, hint, fonts["hint"], QColor("#bbbbbb"),
                            Qt.AlignRight | Qt.AlignVCenter)

    def _paint_launch(self, p, fonts, white) -> None:
        neon = self._style.is_neon
        grey = QColor("#bbbbbb")
        card = self._card
        inner_l = card.left() + BORDER + PAD
        back = next(rect for zone, rect in self._zones if zone == ("back",))
        if self._hover == ("back",):
            p.fillPath(paint.rounded(back, 6.0), tokens.rgba(255, 255, 255, 0.09))
        pen = QPen(white, 2.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        chevron = QPainterPath(QPointF(back.center().x() + 2.5, back.center().y() - 4.5))
        chevron.lineTo(back.center().x() - 2.0, back.center().y())
        chevron.lineTo(back.center().x() + 2.5, back.center().y() + 4.5)
        p.drawPath(chevron)
        paint._text(p, QRectF(back.right() + 4.0, back.top(), 200.0, back.height()),
                    "Launch accounts", fonts["title"], white, Qt.AlignLeft | Qt.AlignVCenter)
        for game, y in self._sections:
            colour = GAME_COLOURS[game]
            p.fillPath(paint.rounded(QRectF(inner_l + 6.0, y + 2.0, 8.0, 8.0), 2.0),
                       QColor(colour))
            font = fonts["section"]
            font.setLetterSpacing(font.SpacingType.PercentageSpacing, 108.0)
            paint._text(p, QRectF(inner_l + 6.0 + 8.0 + 6.0, y, 220.0, 12.0),
                        GAME_NAMES[game], font, QColor(lt(colour, 70)),
                        Qt.AlignLeft | Qt.AlignVCenter)
        buttons = {zone[1]: rect for zone, rect in self._zones if zone[0] == "go"}
        for account, row in self._account_rows:
            label_room = QRectF(row.left() + 6.0, row.top(), row.width() - 12.0, row.height())
            status = QRectF(label_room)
            right_w = 0.0
            if account.state == RUNNING:
                text = account.toon or "Running"
                tw = QFontMetricsF(fonts["status"]).horizontalAdvance(text)
                paint._text(p, status, text, fonts["status"], grey,
                            Qt.AlignRight | Qt.AlignVCenter)
                dot = QPointF(status.right() - tw - 6.0 - 3.5, row.center().y())
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#56c856"))
                p.drawEllipse(dot, 3.5, 3.5)
                right_w = tw + 6.0 + 7.0
            elif account.state == LAUNCHING:
                text = "Launching…"
                right_w = QFontMetricsF(fonts["status"]).horizontalAdvance(text)
                paint._text(p, status, text, fonts["status"], grey,
                            Qt.AlignRight | Qt.AlignVCenter)
            elif account.account_id in buttons:
                button = QRectF(buttons[account.account_id])
                zone = ("go", account.account_id)
                if self._pressed == zone:
                    button.translate(0.0, 1.0)
                self._lit(p, button, GAME_COLOURS.get(account.game, BLUE),
                          6.0 if neon else 4.0)
                if self._hover == zone:
                    p.fillPath(paint.rounded(button, 6.0 if neon else 4.0), paint.HOVER_VEIL)
                paint._text(p, button, "Launch", fonts["button"], white)
                right_w = button.width()
            label_room.setWidth(max(10.0, label_room.width() - right_w - 8.0))
            label = QFontMetricsF(fonts["account"]).elidedText(
                account.label, Qt.ElideRight, label_room.width())
            paint._text(p, label_room, label, fonts["account"], white,
                        Qt.AlignLeft | Qt.AlignVCenter)
        full = next(rect for zone, rect in self._zones if zone == ("full",))
        ink = QColor(lt(BLUE, 60) if self._hover != ("full",) else "#ffffff")
        paint._text(p, full.adjusted(6.0, 0, -6.0, 0), "Open full Launcher ›",
                    fonts["footer"], ink, Qt.AlignLeft | Qt.AlignVCenter)

    # -- pointer ------------------------------------------------------------

    def _zone_at(self, pos) -> tuple | None:
        k = self._scale
        x, y = pos.x() / k, pos.y() / k
        for zone, rect in self._zones:
            if rect.contains(x, y):
                return zone
        return None

    def mouseMoveEvent(self, event) -> None:
        zone = self._zone_at(event.position())
        if zone != self._hover:
            self._hover = zone
            self.setCursor(Qt.PointingHandCursor if zone else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, event) -> None:
        self._hover = self._pressed = None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        event.accept()
        if event.button() == Qt.LeftButton:
            self._pressed = self._zone_at(event.position())
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        pressed, self._pressed = self._pressed, None
        self.update()
        if event.button() != Qt.LeftButton:
            return
        zone = self._zone_at(event.position())
        if zone is None or zone != pressed:
            return
        if zone[0] == "row":
            if zone[1] == LAUNCH_ACCOUNTS:
                if self._can_launch:
                    self.set_view(LAUNCH)
                else:
                    self.full_launcher_requested.emit()
            else:
                self.row_chosen.emit(zone[1])
        elif zone[0] == "back":
            self.set_view(MENU)
        elif zone[0] == "go":
            self.launch_requested.emit(zone[1])
        elif zone[0] == "full":
            self.full_launcher_requested.emit()
