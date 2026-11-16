"""The pieces the Accounts sheet is built from: portrait disc, account row,
pill buttons, login form, confirm row, login row, toon slot.

Rows, slots and buttons paint themselves, text included: the app stylesheet's
``QWidget { font-size: 12pt }`` overrides ``setFont`` on stylesheet-drawn
widgets, and none of these sizes is 12pt. Only the two text fields and the
form's frame are stylesheet-drawn, with their size in their own stylesheet.

Metrics are the design's, in logical px.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QMimeData, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QDrag, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QSizePolicy, QVBoxLayout, QWidget,
)

from utils import cc_race_assets
from utils.icon_factory import (
    make_check_icon, make_edit_icon, make_eye_icon, make_key_icon, make_star_icon,
)
from utils.toon_renders import ToonRenders
from utils.toon_silhouette import paint_race_silhouette
from utils.widgets.grandstand.look_paint import paint_look_disc
from utils.widgets.launchpad import accounts_model as m
from utils.widgets.launchpad.material import SheetToggle

MONO_FAMILIES = ["JetBrains Mono", "Consolas", "Menlo", "DejaVu Sans Mono", "monospace"]
MONO_QSS = '"JetBrains Mono", Consolas, Menlo, "DejaVu Sans Mono", monospace'
HEAD_POSE = "head"

GOLD = "#e8c14d"
GREEN = "#4fc95c"
RED = "#e05252"
RED_TEXT = "#ff7575"
RED_FILL = "#b34848"
BLUE = "#0077ff"
FORM_BORDER = "#3399ff"

ROW_H = 56
ACCOUNT_MIME = "application/x-ttmt-account"
ROW_RADIUS = 8
ROW_PAD = 12
ROW_DISC = 40
SLOT_H = 150
SLOT_RADIUS = 12
SLOT_DISC = 58
SLOT_BUTTON = 26
BUTTON_H = 28
FIELD_H = 30


def ui_font(pixel_size: float, weight: int = 400) -> QFont:
    font = QFont(QApplication.font())
    font.setPixelSize(max(1, round(pixel_size)))
    font.setWeight(QFont.Weight(weight))
    return font


def mono_font(pixel_size: float, weight: int = 700) -> QFont:
    font = QFont()
    font.setFamilies(MONO_FAMILIES)
    font.setStyleHint(QFont.Monospace)
    font.setPixelSize(max(1, round(pixel_size)))
    font.setWeight(QFont.Weight(weight))
    return font


def _alpha(color: str, value: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(value)
    return c


def palette(is_dark: bool) -> dict:
    """Colours of the parts, for one theme."""
    ink = "#ffffff" if is_dark else "#101418"
    return {
        "ink": QColor(ink),
        "title": QColor("#ffffff" if is_dark else "#101418"),
        "sub": _alpha(ink, 0.60),
        "muted": _alpha(ink, 0.42),
        "row_fill": _alpha("#000000", 0.30) if is_dark else _alpha("#ffffff", 0.72),
        "row_hover": _alpha("#000000", 0.42) if is_dark else _alpha("#ffffff", 0.95),
        "row_border": _alpha("#ffffff", 0.05) if is_dark else _alpha("#000000", 0.10),
        "button_fill": _alpha("#ffffff", 0.05) if is_dark else _alpha("#000000", 0.04),
        "button_hover": _alpha("#ffffff", 0.11) if is_dark else _alpha("#000000", 0.09),
        "button_border": _alpha("#ffffff", 0.16) if is_dark else _alpha("#000000", 0.20),
        "disc_fallback": QColor("#4a4a4a") if is_dark else QColor("#d6dae0"),
        "dash": QColor("#555555") if is_dark else QColor("#a0a6ae"),
        "slot_fade": _alpha("#000000", 0.32) if is_dark else _alpha("#ffffff", 0.55),
        "slot_border": _alpha("#ffffff", 0.08) if is_dark else _alpha("#000000", 0.12),
        "chip": _alpha("#000000", 0.36) if is_dark else _alpha("#ffffff", 0.70),
        "field_fill": "rgba(0,0,0,0.35)" if is_dark else "rgba(255,255,255,0.9)",
        "field_border": "rgba(255,255,255,0.14)" if is_dark else "rgba(0,0,0,0.20)",
        "field_text": "#ffffff" if is_dark else "#101418",
        "caption": "rgba(255,255,255,0.60)" if is_dark else "rgba(16,20,24,0.62)",
        "form_fill": "rgba(0,0,0,0.34)" if is_dark else "rgba(255,255,255,0.80)",
        "red_text": QColor(RED_TEXT if is_dark else "#c62828"),
    }


# ── Portrait disc ──────────────────────────────────────────────────────────

class PortraitDisc(QWidget):
    """A toon's portrait in a circle: its stored backdrop and pattern, its
    head render (Toontown Rewritten) or race icon (Corporate Clash), and an
    accent ring. With no toon it is a dashed empty circle."""

    def __init__(self, diameter: int, ring: float = 2.0, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._ring = ring
        self._toon = None
        self._entry: dict = {}
        self._art: QPixmap | None = None
        self._dark = True
        self._renders = None

    def set_toon(self, toon, entry: dict | None = None) -> None:
        self._toon = toon
        self._entry = dict(entry or {})
        self._load()

    def toon(self):
        return self._toon

    def set_dark(self, is_dark: bool) -> None:
        self._dark = bool(is_dark)
        self.update()

    def _wants_render(self) -> bool:
        toon = self._toon
        return toon is not None and toon.game == "ttr" and bool(toon.dna)

    def _load(self) -> None:
        self._art = None
        toon = self._toon
        if toon is not None:
            if self._wants_render():
                if self._renders is None:
                    self._renders = ToonRenders.instance()
                    self._renders.render_landed.connect(self._on_render_landed)
                    self._renders.set_promoted.connect(self._on_set_promoted)
                hit = self._renders.pixmap_for(toon.game, toon.name, HEAD_POSE)
                self._art = hit[0] if hit is not None else None
            else:
                stem = cc_race_assets.asset_stem_for_species(toon.species)
                self._art = cc_race_assets.load_race_pixmap(stem) if stem else None
        self.update()

    def _on_render_landed(self, game: str, name: str, pose: str) -> None:
        toon = self._toon
        if toon is not None and pose == HEAD_POSE and (game, name) == (toon.game, toon.name):
            self._load()

    def _on_set_promoted(self, game: str, name: str) -> None:
        toon = self._toon
        if toon is not None and (game, name) == (toon.game, toon.name):
            self._load()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = palette(self._dark)
        rect = QRectF(self.rect())
        toon = self._toon
        if toon is None:
            pen = QPen(pal["dash"], 1.5, Qt.DashLine)
            pen.setDashPattern([4, 4])
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(rect.adjusted(1.5, 1.5, -1.5, -1.5))
            p.end()
            return
        accent = QColor(toon.accent or m.GAME_COLORS.get(toon.game, m.IDENTITY))
        is_render = self._wants_render() and self._art is not None
        paint_look_disc(
            p, rect, self._entry, fill_fallback=pal["disc_fallback"],
            accent_fallback=accent, ring_width=self._ring,
            art=self._art if is_render else None, art_scale=1.06, art_shift=0.06)
        if not is_render:
            # A race icon, or a silhouette while the render is on its way.
            inset = rect.width() * 0.2
            box = rect.adjusted(inset, inset, -inset, -inset).toRect()
            if self._art is not None and not self._art.isNull():
                p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                scaled = self._art.scaled(box.size(), Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation)
                p.drawPixmap(box.x() + (box.width() - scaled.width()) // 2,
                             box.y() + (box.height() - scaled.height()) // 2, scaled)
            else:
                paint_race_silhouette(p, box, toon.species, accent.name())
        p.end()


# ── Buttons ────────────────────────────────────────────────────────────────

KIND_NEUTRAL = "neutral"
KIND_DANGER = "danger"          # red outline
KIND_DANGER_FILL = "danger_fill"
KIND_PRIMARY = "primary"


class PillButton(QAbstractButton):
    """A small labelled button: neutral outline, red outline, red fill, or
    the blue primary."""

    def __init__(self, text: str, kind: str = KIND_NEUTRAL,
                 parent: QWidget | None = None, height: int = BUTTON_H):
        super().__init__(parent)
        self._kind = kind
        self._dark = True
        self._h = height
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAccessibleName(text)
        self.setFixedSize(self.sizeHint())

    def setText(self, text: str) -> None:  # noqa: N802 (Qt name)
        super().setText(text)
        self.setFixedSize(self.sizeHint())
        self.update()

    def kind(self) -> str:
        return self._kind

    def set_dark(self, is_dark: bool) -> None:
        self._dark = bool(is_dark)
        self.update()

    def _font(self) -> QFont:
        return ui_font(11.5, 600)

    def sizeHint(self) -> QSize:
        width = QFontMetricsF(self._font()).horizontalAdvance(self.text()) + 24
        return QSize(int(width + 0.999), self._h)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = palette(self._dark)
        hover = self.underMouse() and self.isEnabled()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isDown():
            rect.translate(0, 1)
        if self._kind == KIND_PRIMARY:
            fill = QColor(BLUE).lighter(112) if hover else QColor(BLUE)
            border, text = fill, QColor("#ffffff")
        elif self._kind == KIND_DANGER_FILL:
            fill = QColor(RED_FILL).lighter(115) if hover else QColor(RED_FILL)
            border, text = fill, QColor("#ffffff")
        elif self._kind == KIND_DANGER:
            fill = _alpha(RED, 0.30 if hover else 0.12)
            border = QColor(RED)
            text = QColor("#ffb0b0") if self._dark else QColor("#b3261e")
        else:
            fill = pal["button_hover"] if hover else pal["button_fill"]
            border, text = pal["button_border"], pal["ink"]
        if not self.isEnabled():
            p.setOpacity(0.45)
        p.setPen(QPen(border, 1))
        p.setBrush(fill)
        p.drawRoundedRect(rect, 7, 7)
        if self.hasFocus():
            p.setPen(QPen(QColor(FORM_BORDER), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), 5.5, 5.5)
        p.setFont(self._font())
        p.setPen(text)
        p.drawText(rect, Qt.AlignCenter, self.text())
        p.end()


class _GlyphButton(QAbstractButton):
    """A 26 px icon button on a toon slot: the star and the pencil."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(SLOT_BUTTON, SLOT_BUTTON)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._dark = True

    def set_dark(self, is_dark: bool) -> None:
        self._dark = bool(is_dark)
        self.update()


class StarButton(_GlyphButton):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._primary = False

    def set_primary(self, primary: bool) -> None:
        self._primary = bool(primary)
        self.setCursor(Qt.ArrowCursor if primary else Qt.PointingHandCursor)
        self.setToolTip("This account's toon on the launcher" if primary
                        else "Show this toon on the launcher")
        self.setAccessibleName("Primary toon" if primary else "Make primary")
        self.update()

    def is_primary(self) -> bool:
        return self._primary

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if self._primary:
            color = QColor(GOLD)
        else:
            color = _alpha("#ffffff" if self._dark else "#101418",
                           0.80 if self.underMouse() else 0.42)
        icon = make_star_icon(16, color, filled=self._primary)
        dpr = self.devicePixelRatioF()
        p.drawPixmap(QPointF(5, 5), icon.pixmap(QSize(16, 16), dpr))
        p.end()


class PencilButton(_GlyphButton):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setToolTip("Change this toon's look")
        self.setAccessibleName("Edit look")

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = palette(self._dark)
        fill = QColor(pal["chip"])
        if self.underMouse():
            fill.setAlphaF(min(1.0, fill.alphaF() + 0.25))
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(self.rect()), 7, 7)
        icon = make_edit_icon(14, pal["ink"])
        p.drawPixmap(QPointF(6, 6), icon.pixmap(QSize(14, 14), self.devicePixelRatioF()))
        p.end()


def _paint_warning(p: QPainter, x: float, y: float, size: float, color: QColor) -> None:
    """A warning triangle with its bar and dot, ``size`` square at (x, y)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    path = QPainterPath()
    path.moveTo(x + size / 2, y + 1)
    path.lineTo(x + size - 0.5, y + size - 1.5)
    path.lineTo(x + 0.5, y + size - 1.5)
    path.closeSubpath()
    pen = QPen(color, 1.4)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.drawLine(QPointF(x + size / 2, y + size * 0.42), QPointF(x + size / 2, y + size * 0.62))
    p.drawPoint(QPointF(x + size / 2, y + size * 0.78))
    p.restore()


def _paint_chevron(p: QPainter, x: float, cy: float, color: QColor) -> None:
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color, 1.6)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    path = QPainterPath()
    path.moveTo(x, cy - 4)
    path.lineTo(x + 4, cy)
    path.lineTo(x, cy + 4)
    p.drawPath(path)
    p.restore()


# ── Account row ────────────────────────────────────────────────────────────

class AccountRow(QAbstractButton):
    """One account in the list. The whole row opens the account; a failed
    login adds a Fix login button that opens it on the login form."""

    opened = Signal(str)
    fix_requested = Signal(str)
    reorder_requested = Signal(str, str, bool)   # source id, target id, before

    def __init__(self, account, look_entry: dict | None = None, is_dark: bool = True,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._account = account
        self._dark = bool(is_dark)
        self._reorder_enabled = False
        self._drag_origin = None
        self._drop_before = None
        self.setFixedHeight(ROW_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAccessibleName(f"{account.title}, {m.status_text(account)}")
        self.clicked.connect(lambda: self.opened.emit(self._account.id))

        self.disc = PortraitDisc(ROW_DISC, 2.0, self)
        self.disc.set_toon(account.primary, look_entry)
        self.disc.set_dark(self._dark)
        self.disc.move(ROW_PAD, (ROW_H - ROW_DISC) // 2)

        self.fix_button = None
        if account.login == m.LOGIN_FAILED and not account.running:
            self.fix_button = PillButton("Fix login", KIND_DANGER, self, height=26)
            self.fix_button.set_dark(self._dark)
            self.fix_button.clicked.connect(
                lambda: self.fix_requested.emit(self._account.id))

    def account(self):
        return self._account

    def set_reorder_enabled(self, enabled: bool) -> None:
        self._reorder_enabled = bool(enabled)
        self.setAcceptDrops(self._reorder_enabled)
        self.setToolTip("Click to open. Drag to reorder accounts." if enabled else "")
        self.update()

    def _drag_source(self, mime):
        if not self._reorder_enabled or not mime.hasFormat(ACCOUNT_MIME):
            return None
        try:
            source = json.loads(bytes(mime.data(ACCOUNT_MIME)).decode("utf-8"))
            if (source["game"] == self._account.game
                    and isinstance(source["id"], str) and source["id"]
                    and source["id"] != self._account.id):
                return source["id"]
        except (KeyError, TypeError, ValueError, UnicodeError):
            pass
        return None

    def mousePressEvent(self, event) -> None:
        self._drag_origin = (event.position().toPoint()
                             if self._reorder_enabled and event.button() == Qt.LeftButton else None)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (self._drag_origin is not None and event.buttons() & Qt.LeftButton
                and (event.position().toPoint() - self._drag_origin).manhattanLength()
                >= QApplication.startDragDistance()):
            self._drag_origin = None
            self.setDown(False)       # a completed drag must never open the account
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(ACCOUNT_MIME, json.dumps({
                "game": self._account.game, "id": self._account.id}).encode("utf-8"))
            drag.setMimeData(mime)
            drag.setPixmap(self.grab())
            drag.setHotSpot(event.position().toPoint())
            try:
                drag.exec(Qt.MoveAction)
            except RuntimeError:
                pass              # the source row disappeared during the drag
            finally:
                try:
                    drag.deleteLater()
                except RuntimeError:
                    pass          # a roster refresh may have destroyed the source
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event) -> None:
        if self._drag_source(event.mimeData()) is None:
            event.ignore()
            return
        self._drop_before = event.position().y() < self.height() / 2
        event.setDropAction(Qt.MoveAction)
        event.accept()
        self.update()

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._drop_before = None
        self.update()
        event.accept()

    def dropEvent(self, event) -> None:
        source_id = self._drag_source(event.mimeData())
        self._drop_before = None
        self.update()
        if source_id is None:
            event.ignore()
            return
        event.setDropAction(Qt.MoveAction)
        event.accept()
        self.reorder_requested.emit(source_id, self._account.id,
                                     event.position().y() < self.height() / 2)

    def title_text(self) -> str:
        return self._account.title

    def sub_text(self) -> str:
        return m.account_sub(self._account)

    def status_text(self) -> str:
        return m.status_text(self._account)

    def is_failed(self) -> bool:
        return self._account.login == m.LOGIN_FAILED and not self._account.running

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.fix_button is not None:
            self.fix_button.move(self.width() - ROW_PAD - 22 - self.fix_button.width(),
                                 (ROW_H - self.fix_button.height()) // 2)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = palette(self._dark)
        account = self._account
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hover = self.underMouse()
        border = _alpha(RED, 0.60) if self.is_failed() else pal["row_border"]
        p.setPen(QPen(border, 1))
        p.setBrush(pal["row_hover"] if hover else pal["row_fill"])
        p.drawRoundedRect(rect, ROW_RADIUS, ROW_RADIUS)
        if self.hasFocus():
            p.setPen(QPen(QColor(FORM_BORDER), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), ROW_RADIUS - 1, ROW_RADIUS - 1)

        # Right side first, so the text knows where to stop.
        right = self.width() - ROW_PAD
        _paint_chevron(p, right - 8, self.height() / 2, pal["muted"])
        right -= 22
        if self.fix_button is not None:
            right = self.fix_button.x() - 12
        status = self.status_text()
        if account.running:
            font, color, glyph = ui_font(15, 700), QColor(GREEN), "dot"
        elif account.login == m.LOGIN_FAILED:
            font, color, glyph = ui_font(11.5, 600), pal["red_text"], "warning"
        elif account.login == m.LOGIN_SAVED:
            font, color, glyph = ui_font(11.5, 400), pal["sub"], "check"
        else:
            font, color, glyph = ui_font(11.5, 400), pal["sub"], None
        metrics = QFontMetricsF(font)
        text_w = metrics.horizontalAdvance(status)
        text_x = right - text_w
        cy = self.height() / 2
        p.setFont(font)
        p.setPen(color)
        p.drawText(QRectF(text_x, 0, text_w + 2, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, status)
        glyph_x = text_x - 18
        if glyph == "dot":
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(QPointF(text_x - 8, cy + 1), 3, 3)
        elif glyph == "warning":
            _paint_warning(p, glyph_x, cy - 7, 14, color)
        elif glyph == "check":
            icon = make_check_icon(13, QColor(GREEN))
            p.drawPixmap(QPointF(glyph_x + 1, cy - 6.5),
                         icon.pixmap(QSize(13, 13), self.devicePixelRatioF()))
        status_left = glyph_x - 10 if glyph else text_x - 10

        # Title and sub line.
        left = ROW_PAD + ROW_DISC + 12
        avail = max(20.0, status_left - left)
        title_font = mono_font(12.5, 700)
        p.setFont(title_font)
        p.setPen(pal["title"])
        title = QFontMetricsF(title_font).elidedText(self.title_text(), Qt.ElideRight, avail)
        p.drawText(QRectF(left, 10, avail, 18), Qt.AlignVCenter | Qt.AlignLeft, title)
        sub_font = ui_font(10.5, 400)
        sub_x = left
        if account.primary is not None:
            star = make_star_icon(11, QColor(GOLD), filled=True)
            p.drawPixmap(QPointF(left, 31), star.pixmap(QSize(11, 11), self.devicePixelRatioF()))
            sub_x = left + 16
        p.setFont(sub_font)
        p.setPen(pal["sub"])
        sub = QFontMetricsF(sub_font).elidedText(
            self.sub_text(), Qt.ElideRight, max(10.0, avail - (sub_x - left)))
        p.drawText(QRectF(sub_x, 28, avail, 18), Qt.AlignVCenter | Qt.AlignLeft, sub)
        if self._reorder_enabled:
            p.setPen(Qt.NoPen)
            p.setBrush(pal["muted"])
            for x in (ROW_PAD + ROW_DISC + 3, ROW_PAD + ROW_DISC + 7):
                for y in (self.height() / 2 - 4, self.height() / 2, self.height() / 2 + 4):
                    p.drawEllipse(QPointF(x, y), .8, .8)
        if self._drop_before is not None:
            y = 2 if self._drop_before else self.height() - 2
            p.setPen(QPen(QColor(FORM_BORDER), 2))
            p.drawLine(ROW_PAD, y, self.width() - ROW_PAD, y)
        p.end()


# ── Login form ─────────────────────────────────────────────────────────────

class LoginForm(QFrame):
    """One form for Add account, Edit login, Fix login and Add login."""

    cancelled = Signal()
    submitted = Signal(str, str, bool)      # username, password, keep in keyring

    def __init__(self, mode: str, game: str, *, username: str = "",
                 keyring_available: bool = True, is_dark: bool = True,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("login_form")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._mode, self._game = mode, game
        self._keyring = bool(keyring_available)
        self._dark = bool(is_dark)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)
        self.title_label = QLabel(m.form_title(mode, game), self)
        outer.addWidget(self.title_label)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(5)
        self.username_caption = QLabel("USERNAME", self)
        self.password_caption = QLabel("PASSWORD", self)
        self.username = QLineEdit(self)
        self.username.setObjectName("login_username")
        self.username.setText(username)
        self.username.setFixedHeight(FIELD_H)
        # Asked for at launch, the account is already chosen.
        self.username.setReadOnly(mode == m.FORM_LAUNCH)
        self.password = QLineEdit(self)
        self.password.setObjectName("login_password")
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setFixedHeight(FIELD_H)
        self._eye = self.password.addAction(make_eye_icon(16), QLineEdit.TrailingPosition)
        self._eye.setCheckable(True)
        self._eye.toggled.connect(self._on_eye)
        self._eye.setToolTip("Show password")
        grid.addWidget(self.username_caption, 0, 0)
        grid.addWidget(self.password_caption, 0, 1)
        grid.addWidget(self.username, 1, 0)
        grid.addWidget(self.password, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)

        self.error_label = QLabel("", self)
        self.error_label.hide()
        outer.addWidget(self.error_label)

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 2, 0, 0)
        foot.setSpacing(9)
        self.keep_toggle = SheetToggle(self._keyring, BLUE, is_dark=self._dark, parent=self)
        self.keep_toggle.setEnabled(self._keyring)
        self.keep_label = QLabel(
            m.KEEP_IN_KEYRING if self._keyring else m.KEYRING_UNAVAILABLE, self)
        foot.addWidget(self.keep_toggle)
        foot.addWidget(self.keep_label, 1)
        self.cancel_button = PillButton("Cancel", KIND_NEUTRAL, self, height=32)
        self.submit_button = PillButton(m.form_primary_text(mode), KIND_PRIMARY, self,
                                        height=32)
        foot.addWidget(self.cancel_button)
        foot.addWidget(self.submit_button)
        outer.addLayout(foot)

        self.cancel_button.clicked.connect(self.cancelled.emit)
        self.submit_button.clicked.connect(self.submit)
        self.username.returnPressed.connect(self.submit)
        self.password.returnPressed.connect(self.submit)
        self.username.textEdited.connect(self._clear_error)
        self.password.textEdited.connect(self._clear_error)
        self.apply_theme(self._dark)

    def mode(self) -> str:
        return self._mode

    def game(self) -> str:
        return self._game

    def keep(self) -> bool:
        return self._keyring and self.keep_toggle.isChecked()

    def focus_first(self) -> None:
        target = self.password if self.username.text().strip() else self.username
        target.setFocus(Qt.OtherFocusReason)

    def error_text(self) -> str:
        return self.error_label.text() if not self.error_label.isHidden() else ""

    def submit(self) -> None:
        username = self.username.text().strip()
        if not username:
            self.error_label.setText(m.USERNAME_REQUIRED)
            self.error_label.show()
            self._style_fields()
            self.username.setFocus(Qt.OtherFocusReason)
            return
        if self._mode == m.FORM_LAUNCH and not self.password.text():
            self.error_label.setText(m.PASSWORD_REQUIRED)
            self.error_label.show()
            self._style_fields()
            self.password.setFocus(Qt.OtherFocusReason)
            return
        self.submitted.emit(username, self.password.text(), self.keep())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _clear_error(self, _text: str = "") -> None:
        if not self.error_label.isHidden():
            self.error_label.hide()
            self._style_fields()

    def _on_eye(self, shown: bool) -> None:
        self.password.setEchoMode(QLineEdit.Normal if shown else QLineEdit.Password)
        self._eye.setIcon(make_eye_icon(16, crossed=shown))
        self._eye.setToolTip("Hide password" if shown else "Show password")

    def _field_qss(self, name: str, invalid: bool = False) -> str:
        pal = palette(self._dark)
        border = RED if invalid else pal["field_border"]
        return (
            f"QLineEdit#{name} {{ background: {pal['field_fill']};"
            f" border: 1px solid {border}; border-radius: 5px; padding: 0 9px;"
            f" color: {pal['field_text']}; font-size: 12.5px;"
            f" selection-background-color: {BLUE}; }}"
            f"QLineEdit#{name}:focus {{ border: 1px solid {FORM_BORDER}; }}")

    def _style_fields(self) -> None:
        error = self.error_text()
        self.username.setStyleSheet(self._field_qss(
            "login_username", error == m.USERNAME_REQUIRED))
        self.password.setStyleSheet(self._field_qss(
            "login_password", error == m.PASSWORD_REQUIRED))

    def apply_theme(self, is_dark: bool) -> None:
        self._dark = bool(is_dark)
        pal = palette(self._dark)
        self.setStyleSheet(
            f"QFrame#login_form {{ background: {pal['form_fill']};"
            f" border: 1px solid {FORM_BORDER}; border-radius: 8px; }}")
        text = pal["field_text"]
        self.title_label.setStyleSheet(
            f"background: transparent; border: none; color: {text};"
            " font-size: 12.5px; font-weight: 700;")
        caption = (f"background: transparent; border: none; color: {pal['caption']};"
                   " font-size: 9.5px; font-weight: 700; letter-spacing: 0.8px;")
        self.username_caption.setStyleSheet(caption)
        self.password_caption.setStyleSheet(caption)
        self.keep_label.setStyleSheet(
            f"background: transparent; border: none; color: {pal['caption']};"
            " font-size: 11.5px;")
        self.error_label.setStyleSheet(
            f"background: transparent; border: none; color: {pal['red_text'].name()};"
            " font-size: 11px; font-weight: 600;")
        self.keep_toggle.apply_theme(self._dark)
        self.cancel_button.set_dark(self._dark)
        self.submit_button.set_dark(self._dark)
        self._eye.setIcon(make_eye_icon(16, QColor(text),
                                        crossed=self._eye.isChecked()))
        self._style_fields()


# ── Confirm row ────────────────────────────────────────────────────────────

class ConfirmRow(QFrame):
    """A question in place, under the row it is about: Reset's "Forget the
    saved login?" and Remove's "Remove this account?"."""

    confirmed = Signal()
    dismissed = Signal()

    def __init__(self, question: str, detail: str, keep_text: str, confirm_text: str,
                 is_dark: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("confirm_row")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.question_label = QLabel(question, self)
        self.detail_label = QLabel(detail, self)
        self.detail_label.setWordWrap(True)
        text.addWidget(self.question_label)
        text.addWidget(self.detail_label)
        row.addLayout(text, 1)
        self.keep_button = PillButton(keep_text, KIND_NEUTRAL, self)
        self.confirm_button = PillButton(confirm_text, KIND_DANGER_FILL, self)
        row.addWidget(self.keep_button, 0, Qt.AlignVCenter)
        row.addWidget(self.confirm_button, 0, Qt.AlignVCenter)
        self.keep_button.clicked.connect(self.dismissed.emit)
        self.confirm_button.clicked.connect(self.confirmed.emit)
        self.apply_theme(is_dark)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.dismissed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def apply_theme(self, is_dark: bool) -> None:
        pal = palette(is_dark)
        self.setStyleSheet(
            "QFrame#confirm_row { background: rgba(224,82,82,0.10);"
            f" border: 1px solid {RED}; border-radius: 8px; }}")
        self.question_label.setStyleSheet(
            f"background: transparent; border: none; color: {pal['field_text']};"
            " font-size: 12.5px; font-weight: 700;")
        self.detail_label.setStyleSheet(
            f"background: transparent; border: none; color: {pal['caption']};"
            " font-size: 10.5px;")
        self.keep_button.set_dark(is_dark)
        self.confirm_button.set_dark(is_dark)


# ── Login row (one account) ────────────────────────────────────────────────

class LoginRow(QWidget):
    """The account's login as an inset row: key disc, username, a status
    line, and the buttons for its state."""

    edit_requested = Signal(str)        # the form mode to open
    reset_requested = Signal()

    def __init__(self, account, is_dark: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self._account = account
        self._dark = bool(is_dark)
        self.setFixedHeight(50)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        label, mode, has_reset = m.login_buttons(account)
        self._mode = mode
        self.edit_button = PillButton(
            label, KIND_DANGER if mode == m.FORM_FIX else KIND_NEUTRAL, self)
        self.edit_button.clicked.connect(lambda: self.edit_requested.emit(self._mode))
        self.reset_button = None
        if has_reset:
            self.reset_button = PillButton("Reset", KIND_DANGER, self)
            self.reset_button.clicked.connect(self.reset_requested.emit)
        self.set_dark(self._dark)

    def status_line(self) -> str:
        return m.login_line(self._account)

    def set_dark(self, is_dark: bool) -> None:
        self._dark = bool(is_dark)
        self.edit_button.set_dark(self._dark)
        if self.reset_button is not None:
            self.reset_button.set_dark(self._dark)
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        x = self.width() - ROW_PAD
        for button in (self.reset_button, self.edit_button):
            if button is None:
                continue
            x -= button.width()
            button.move(x, (self.height() - button.height()) // 2)
            x -= 8

    def _text_right(self) -> int:
        return self.edit_button.x() - 12

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = palette(self._dark)
        failed = self._account.login == m.LOGIN_FAILED
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(_alpha(RED, 0.60) if failed else pal["row_border"], 1))
        p.setBrush(pal["row_fill"])
        p.drawRoundedRect(rect, ROW_RADIUS, ROW_RADIUS)
        # Key disc.
        disc = QRectF(ROW_PAD, (self.height() - 30) / 2, 30, 30)
        p.setPen(Qt.NoPen)
        p.setBrush(pal["button_hover"])
        p.drawEllipse(disc)
        icon = make_key_icon(15, pal["sub"])
        p.drawPixmap(QPointF(disc.x() + 7.5, disc.y() + 7.5),
                     icon.pixmap(QSize(15, 15), self.devicePixelRatioF()))
        left = disc.right() + 11
        avail = max(20.0, self._text_right() - left)
        font = mono_font(12.5, 700)
        p.setFont(font)
        p.setPen(pal["title"])
        p.drawText(QRectF(left, 8, avail, 18), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetricsF(font).elidedText(self._account.username,
                                                  Qt.ElideRight, avail))
        sub_x = left
        color = pal["red_text"] if failed else pal["sub"]
        if failed:
            _paint_warning(p, left, 27, 12, color)
            sub_x = left + 17
        font = ui_font(10.5, 400)
        p.setFont(font)
        p.setPen(color)
        p.drawText(QRectF(sub_x, 24, avail, 18), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetricsF(font).elidedText(self.status_line(), Qt.ElideRight,
                                                  max(10.0, avail - (sub_x - left))))
        p.end()


# ── Toon slot ──────────────────────────────────────────────────────────────

class ToonSlot(QWidget):
    """One of the six slots: a toon seen on the account, or an empty slot.
    The star makes it the account's primary; the pencil opens its look."""

    primary_requested = Signal(str)
    edit_requested = Signal(str)

    def __init__(self, toon=None, *, is_primary: bool = False,
                 look_entry: dict | None = None, is_dark: bool = True,
                 now: float | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._toon = toon
        self._primary = bool(is_primary) and toon is not None
        self._dark = bool(is_dark)
        self._now = now
        self.setFixedHeight(SLOT_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.disc = self.star = self.pencil = None
        if toon is None:
            self.setAccessibleName(m.EMPTY_SLOT)
            return
        self.setAccessibleName(toon.name)
        self.disc = PortraitDisc(SLOT_DISC, 3.0, self)
        self.disc.set_toon(toon, look_entry)
        self.disc.set_dark(self._dark)
        self.star = StarButton(self)
        self.star.set_primary(self._primary)
        self.star.set_dark(self._dark)
        self.star.move(8, 8)
        self.star.clicked.connect(self._on_star)
        self.pencil = PencilButton(self)
        self.pencil.set_dark(self._dark)
        self.pencil.clicked.connect(lambda: self.edit_requested.emit(self._toon.name))

    def toon(self):
        return self._toon

    def is_primary(self) -> bool:
        return self._primary

    def is_empty(self) -> bool:
        return self._toon is None

    def name_text(self) -> str:
        return self._toon.name if self._toon is not None else m.EMPTY_SLOT

    def line_text(self) -> str:
        return m.toon_line(self._toon) if self._toon is not None else m.EMPTY_SLOT_SUB

    def played_text(self) -> str:
        if self._toon is None:
            return ""
        return m.toon_played_line(self._toon, self._primary, self._now)

    def _on_star(self) -> None:
        # The current primary's star does nothing: there is always exactly one.
        if not self._primary:
            self.primary_requested.emit(self._toon.name)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.disc is not None:
            self.disc.move((self.width() - SLOT_DISC) // 2, 12)
            self.pencil.move(self.width() - 8 - SLOT_BUTTON, 8)

    def paintEvent(self, _event) -> None:
        from PySide6.QtGui import QLinearGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = palette(self._dark)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        toon = self._toon
        if toon is None:
            pen = QPen(pal["dash"], 1, Qt.DashLine)
            pen.setDashPattern([4, 4])
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect, SLOT_RADIUS, SLOT_RADIUS)
            circle = QRectF((self.width() - 44) / 2, 34, 44, 44)
            pen = QPen(pal["dash"], 1.5, Qt.DashLine)
            pen.setDashPattern([4, 4])
            p.setPen(pen)
            p.drawEllipse(circle)
            p.setFont(ui_font(12.5, 700))
            p.setPen(pal["muted"])
            p.drawText(QRectF(4, 90, self.width() - 8, 18), Qt.AlignCenter, m.EMPTY_SLOT)
            p.setFont(ui_font(10.5, 400))
            p.drawText(QRectF(4, 108, self.width() - 8, 16), Qt.AlignCenter,
                       m.EMPTY_SLOT_SUB)
            p.end()
            return

        accent = QColor(toon.accent or m.GAME_COLORS.get(toon.game, m.IDENTITY))
        gradient = QLinearGradient(0, 0, 0, self.height())
        top = QColor(accent)
        top.setAlphaF(0.24)
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, pal["slot_fade"])
        p.setPen(QPen(QColor(GOLD) if self._primary else pal["slot_border"], 1))
        p.setBrush(gradient)
        p.drawRoundedRect(rect, SLOT_RADIUS, SLOT_RADIUS)
        if self._primary:
            p.setPen(QPen(_alpha(GOLD, 0.40), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), SLOT_RADIUS - 1, SLOT_RADIUS - 1)

        width = self.width() - 12
        name_font = ui_font(12.5, 700)
        p.setFont(name_font)
        p.setPen(pal["title"])
        p.drawText(QRectF(6, 78, width, 18), Qt.AlignCenter,
                   QFontMetricsF(name_font).elidedText(toon.name, Qt.ElideRight, width))
        small = ui_font(10.5, 400)
        p.setFont(small)
        p.setPen(pal["sub"])
        p.drawText(QRectF(6, 96, width, 16), Qt.AlignCenter, self.line_text())
        played = self.played_text()
        if played:
            if self._primary:
                p.setFont(ui_font(10.5, 600))
                p.setPen(QColor(GOLD) if self._dark else QColor("#8a6d00"))
            p.drawText(QRectF(6, 112, width, 16), Qt.AlignCenter, played)
        p.end()
