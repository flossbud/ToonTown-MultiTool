"""The launchpad window's header: wordmark, hints toggle, the three sheet
buttons and the session status line. The traffic lights are added by the
window's chrome controller, which takes this frame as its header.

Metrics are the design's, in logical px:

* header 112 high;
* button row pinned bottom-left (left 14, bottom 12, 5 between), each button
  32 high, radius 16, padding 10 left / 13 right, a 16 px glyph, 7 to the label;
* status line right-aligned, 62 from the top.

Everything here paints its own text: the app stylesheet's
``QWidget { font-size: 12pt }`` overrides ``setFont`` on stylesheet-drawn
widgets, and these sizes are not 12pt.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QFrame, QLabel, QToolButton, QWidget,
)

from utils.asset_paths import asset_path
from utils.icon_factory import make_dpad_icon, make_nav_gear, make_person_icon
from utils.theme_manager import make_hint_icon

HEADER_H = 112

SHEET_ACCOUNTS = "accounts"
SHEET_KEYSETS = "keysets"
SHEET_SETTINGS = "settings"

# name, label, identity colour, glyph factory. Order is the row's order.
SHEET_BUTTONS = (
    (SHEET_ACCOUNTS, "Accounts", "#0077ff", make_person_icon),
    (SHEET_KEYSETS, "Keysets", "#DAA520", make_dpad_icon),
    (SHEET_SETTINGS, "Settings", "#3da343", make_nav_gear),
)

BUTTON_H = 32
BUTTON_PAD_LEFT = 10
BUTTON_PAD_RIGHT = 13
BUTTON_ICON = 16
BUTTON_GAP = 7
BUTTON_FONT_PX = 13
ROW_LEFT = 14
ROW_BOTTOM = 12
ROW_SPACING = 5
STATUS_TOP = 62
STATUS_RIGHT = 16
STATUS_FONT_PX = 12
STATUS_DOT = 6
# The classic header drew the wordmark 80 high with nothing beside it. Here
# the button row sits to its left, and 80 runs into it; the design draws it
# at about this height. It shrinks further if the window is too narrow to
# keep LOGO_GAP between the row and the wordmark.
LOGO_HEIGHT = 62
LOGO_GAP = 12


def next_open_sheet(current: str | None, clicked: str) -> str | None:
    """Which sheet is open after ``clicked``'s button is pressed: pressing
    the lit button closes its sheet, pressing another swaps to it."""
    return None if current == clicked else clicked


def session_status_text(toon_count: int, running: bool = True) -> str:
    """"N toons" while the broadcast runs, "N toons · stopped" while it is
    stopped, and nothing at all with no toons."""
    if toon_count <= 0:
        return ""
    text = "1 toon" if toon_count == 1 else f"{toon_count} toons"
    return text if running else f"{text} \u00b7 stopped"


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def _ui_font(pixel_size: int, weight: QFont.Weight) -> QFont:
    font = QFont(QApplication.font())
    font.setPixelSize(pixel_size)
    font.setWeight(weight)
    return font


class SheetButton(QAbstractButton):
    """One labelled header button. Icon + name, always; lit while its sheet
    is open."""

    def __init__(self, name: str, label: str, identity: str, glyph,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.name = name
        self._label = label
        self._identity = QColor(identity)
        self._glyph = glyph
        self._open = False
        self._dark = True
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAccessibleName(label)
        self.setFixedSize(self.sizeHint())

    def set_open(self, is_open: bool) -> None:
        if is_open != self._open:
            self._open = is_open
            # Bold is wider than medium: the lit button grows a little, as the
            # dock's selected segment did.
            self.setFixedSize(self.sizeHint())
            self.update()

    def is_open(self) -> bool:
        return self._open

    def set_dark(self, is_dark: bool) -> None:
        if is_dark != self._dark:
            self._dark = is_dark
            self.update()

    def _font(self) -> QFont:
        return _ui_font(BUTTON_FONT_PX,
                        QFont.Weight.Bold if self._open else QFont.Weight.Medium)

    def sizeHint(self) -> QSize:
        text_w = QFontMetricsF(self._font()).horizontalAdvance(self._label)
        width = BUTTON_PAD_LEFT + BUTTON_ICON + BUTTON_GAP + text_w + BUTTON_PAD_RIGHT
        return QSize(int(width + 0.999), BUTTON_H)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        hover = self.underMouse() and self.isEnabled()
        ink = QColor("#ffffff") if self._dark else QColor("#000000")
        if self._open:
            fill = QColor(self._identity)
            # 55% over the dark header; over the light one that washes out
            # under the white label, so it sits nearly solid there.
            fill.setAlphaF(0.55 if self._dark else 0.92)
            border = _mix(self._identity, QColor("#ffffff"), 0.30)
            text = QColor("#ffffff")
            icon_color = QColor("#ffffff")
            # Glow: a soft ring of the identity colour around the pill.
            for spread, alpha in ((3.0, 0.10), (2.0, 0.14), (1.0, 0.20)):
                glow = QColor(self._identity)
                glow.setAlphaF(alpha)
                p.setPen(QPen(glow, spread * 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5),
                                  BUTTON_H / 2 - 1.5, BUTTON_H / 2 - 1.5)
        else:
            fill = QColor(ink)
            fill.setAlphaF(0.09 if hover else 0.045)
            border = QColor(ink)
            border.setAlphaF(0.11)
            if self._dark:
                text = QColor("#ffffff") if hover else QColor("#a8a8a8")
            else:
                text = QColor("#000000") if hover else QColor("#555555")
            icon_color = QColor(self._identity)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isDown():
            rect.translate(0, 1)                    # press: 1 px down
        p.setPen(QPen(border, 1))
        p.setBrush(fill)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

        dpr = self.devicePixelRatioF()
        icon = self._glyph(BUTTON_ICON, icon_color)
        pixmap = icon.pixmap(QSize(BUTTON_ICON, BUTTON_ICON), dpr)
        icon_y = rect.top() + (rect.height() - BUTTON_ICON) / 2
        p.drawPixmap(QPointF(rect.left() + BUTTON_PAD_LEFT - 0.5, icon_y), pixmap)

        p.setFont(self._font())
        p.setPen(text)
        text_rect = QRectF(
            rect.left() + BUTTON_PAD_LEFT - 0.5 + BUTTON_ICON + BUTTON_GAP, rect.top(),
            rect.width(), rect.height())
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self._label)
        p.end()


class SheetButtonRow(QWidget):
    """Accounts / Keysets / Settings. Emits the name of the button pressed;
    the owner decides what opens and tells the row with ``set_open``."""

    pressed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent;")
        self._open: str | None = None
        self.buttons: dict[str, SheetButton] = {}
        for name, label, identity, glyph in SHEET_BUTTONS:
            button = SheetButton(name, label, identity, glyph, self)
            button.clicked.connect(lambda _checked=False, n=name: self.pressed.emit(n))
            self.buttons[name] = button
        self._lay_out()

    def _lay_out(self) -> None:
        x = 0
        for button in self.buttons.values():
            button.move(x, 0)
            x += button.width() + ROW_SPACING
        self.setFixedSize(max(0, x - ROW_SPACING), BUTTON_H)

    def open_sheet(self) -> str | None:
        return self._open

    def widest(self) -> int:
        """The row's width with its widest button lit (a lit label is bold)."""
        rest = {name: b.sizeHint().width() for name, b in self.buttons.items()}
        lit = {}
        for name, button in self.buttons.items():
            was = button._open
            button._open = True
            lit[name] = button.sizeHint().width()
            button._open = was
        base = sum(rest.values()) + ROW_SPACING * (len(rest) - 1)
        return base + max(lit[name] - rest[name] for name in rest)

    def set_open(self, name: str | None) -> None:
        """Light the button whose sheet is open (None: no sheet)."""
        self._open = name if name in self.buttons else None
        for key, button in self.buttons.items():
            button.set_open(key == self._open)
        self._lay_out()

    def set_dark(self, is_dark: bool) -> None:
        for button in self.buttons.values():
            button.set_dark(is_dark)


class SessionStatus(QWidget):
    """"N toons" with a green dot while the broadcast runs, "N toons ·
    stopped" with a grey one while it is stopped; hidden with no toons."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._count = 0
        self._running = True
        self._dark = True
        self._resize()
        self.setVisible(False)

    def _font(self) -> QFont:
        return _ui_font(STATUS_FONT_PX, QFont.Weight.Normal)

    def text(self) -> str:
        return session_status_text(self._count, self._running)

    def is_running(self) -> bool:
        return self._running

    def set_running(self, running: bool) -> None:
        running = bool(running)
        if running != self._running:
            self._running = running
            self._resize()
            self.update()

    def toon_count(self) -> int:
        return self._count

    def set_toon_count(self, count: int) -> None:
        count = max(0, int(count))
        if count != self._count:
            self._count = count
            self._resize()
            self.update()
        self.setVisible(count > 0)

    def set_dark(self, is_dark: bool) -> None:
        if is_dark != self._dark:
            self._dark = is_dark
            self.update()

    def _resize(self) -> None:
        metrics = QFontMetricsF(self._font())
        width = STATUS_DOT + 7 + metrics.horizontalAdvance(self.text()) + 2
        self.setFixedSize(int(width + 0.999), int(max(metrics.height(), STATUS_DOT) + 2.999))
        self.setAccessibleName(self.text())

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        running = self._count > 0 and self._running
        dot = QColor("#4fc95c") if running else QColor("#777777")
        p.setPen(Qt.NoPen)
        p.setBrush(dot)
        cy = self.height() / 2
        p.drawEllipse(QPointF(STATUS_DOT / 2, cy), STATUS_DOT / 2, STATUS_DOT / 2)
        p.setFont(self._font())
        p.setPen(QColor("#888888") if self._dark else QColor("#666666"))
        p.drawText(QRectF(STATUS_DOT + 7, 0, self.width(), self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


class LaunchpadHeader(QFrame):
    """The header frame. Object name ``app_header``: the window styles its
    fill and top corners by that name."""

    sheet_pressed = Signal(str)       # a sheet button was pressed
    hints_toggled = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("app_header")
        self.setMinimumHeight(HEADER_H)
        self._dark = True
        self._hints_enabled = True
        self._logo_source: QPixmap | None = None

        self.logo = QLabel(self)
        self.logo.setObjectName("header_logo")
        self.logo.setAlignment(Qt.AlignCenter)
        self.logo.setStyleSheet("background: transparent;")
        self.logo.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.hint_btn = QToolButton(self)
        self.hint_btn.setObjectName("hint_toggle")
        self.hint_btn.setFixedSize(34, 34)
        self.hint_btn.setIconSize(QSize(20, 20))
        self.hint_btn.setCursor(Qt.PointingHandCursor)
        self.hint_btn.setFocusPolicy(Qt.NoFocus)
        self.hint_btn.setProperty("_always_tooltip", True)
        self.hint_btn.setStyleSheet(
            "QToolButton { background: transparent; border: 1px solid transparent;"
            " border-radius: 8px; }"
            "QToolButton:hover { background: rgba(127,127,127,0.16); }")
        self.hint_btn.clicked.connect(self.hints_toggled.emit)

        self.buttons = SheetButtonRow(self)
        self.buttons.pressed.connect(self.sheet_pressed.emit)
        self.status = SessionStatus(self)

        self.apply_theme(True, QColor("#bbbbbb"))
        self._place()

    # ── State ──────────────────────────────────────────────────────────────

    def set_open_sheet(self, name: str | None) -> None:
        self.buttons.set_open(name)

    def open_sheet(self) -> str | None:
        return self.buttons.open_sheet()

    def set_toon_count(self, count: int) -> None:
        self.status.set_toon_count(count)
        self._place()

    def set_running(self, running: bool) -> None:
        """The broadcast service's state: "N toons" or "N toons · stopped"."""
        self.status.set_running(running)
        self._place()

    def set_hints_enabled(self, enabled: bool) -> None:
        self._hints_enabled = bool(enabled)
        self._refresh_hint_icon()

    def apply_theme(self, is_dark: bool, icon_color: QColor) -> None:
        self._dark = bool(is_dark)
        self._icon_color = QColor(icon_color)
        self.buttons.set_dark(self._dark)
        self.status.set_dark(self._dark)
        self._refresh_hint_icon()
        self._refresh_logo()

    # ── Internals ──────────────────────────────────────────────────────────

    def _refresh_hint_icon(self) -> None:
        size = self.hint_btn.iconSize().width()
        self.hint_btn.setIcon(
            make_hint_icon(size, self._icon_color, active=self._hints_enabled))
        state = "on" if self._hints_enabled else "off"
        self.hint_btn.setToolTip(f"Hover hints are {state}. Click to toggle.")

    def _refresh_logo(self, force: bool = True) -> None:
        name = "ttmt_logo_textonly.png" if self._dark else "ttmt_logo_textonly_shadow.png"
        if force or self._logo_source is None:
            self._logo_source = QPixmap(asset_path(f"logos/{name}"))
        source = self._logo_source
        if source.isNull():
            return
        # A header that has not been laid out yet reports a placeholder width.
        width = self.width() if self.isVisible() or self.width() >= 400 else 880
        # Centred in the header, clear of the button row at its widest.
        room = 2 * (width / 2 - (ROW_LEFT + self.buttons.widest() + LOGO_GAP))
        aspect = source.width() / source.height()
        th = LOGO_HEIGHT
        tw = th * aspect
        if tw > room:
            tw, th = room, room / aspect
        tw, th = int(tw), int(th)
        if tw <= 0 or th <= 0:
            return
        if not force and self.logo.size() == QSize(tw, th):
            return
        dpr = self.devicePixelRatioF()
        scaled = source.scaled(int(tw * dpr), int(th * dpr),
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        self.logo.setPixmap(scaled)
        self.logo.setFixedSize(tw, th)
        self._place()

    def _place(self) -> None:
        width, height = self.width(), max(self.height(), HEADER_H)
        self.hint_btn.move(13, 13)
        self.logo.move((width - self.logo.width()) // 2,
                       (height - self.logo.height()) // 2)
        self.buttons.move(ROW_LEFT, height - ROW_BOTTOM - self.buttons.height())
        self.status.move(width - STATUS_RIGHT - self.status.width(), STATUS_TOP)
        self.hint_btn.raise_()
        self.buttons.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_logo(force=False)      # the wordmark's size follows the width
        self._place()
