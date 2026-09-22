"""One account's card on the shelf (handoff §4.1d).

Fixed 148x216. Four controls, each a distinct job: the ribbon adds the account
to the launch party and then shows its place on stage, the star sets the
game-wide main, the pencil opens the appearance editor and the gear opens
account settings. Pencil, gear and the state action reveal on hover *or
focus* so they are keyboard-reachable.

The card always draws the `head` pose regardless of the toon's saved pose, so
the shelf reads as one rank rather than a row of unrelated crops.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QPushButton, QToolButton, QWidget,
)

from utils.shared_widgets import PulsingDot
from utils.toon_renders import AWAITING_RENDER_TOOLTIP, PREVIOUS_LOOK_TOOLTIP, ToonRenders
from utils.toon_silhouette import paint_race_silhouette
from utils.widgets.account_tile import summarize_error
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.model import CARD_POSE, PORTRAIT_RENDER

CARD_W = 148
CARD_H = 216
CARD_RADIUS = 16
PORTRAIT = 128

# Per-species head framing for the `head` pose (handoff §8): (scale, translateY%).
HEAD_FIT = {
    "cat": (0.92, 4), "dog": (1.08, 11), "duck": (1.06, 11), "mouse": (0.95, 10),
    "rabbit": (1.00, 9), "horse": (1.05, 11), "monkey": (1.00, 10),
    "bear": (1.06, 11), "pig": (1.02, 10), "deer": (1.04, 11),
    "crocodile": (1.06, 11),
}
NEUTRAL_FIT = (1.0, 0)

# state -> (action label, signal attribute, enabled). None means "no action".
ACTION_MAP = {
    "idle":       ("Launch", "launch_clicked", True),
    "logging_in": (None, None, False),
    "launching":  (None, None, False),
    "loading":    ("Quit", "quit_clicked", True),
    "queued":     ("Cancel", "cancel_clicked", True),
    "need_2fa":   ("Enter 2FA →", "enter_2fa_clicked", True),
    "running":    ("Quit", "quit_clicked", True),
    "failed":     ("Retry", "retry_clicked", True),
}

# States that need the user. Their action ignores both the hover-reveal rule
# and the checked-defers-to-Play rule (spec Q2, Q7).
URGENT_STATES = frozenset({"need_2fa", "failed"})

# States whose action is about an in-flight session, so party membership is
# irrelevant to it.
_SESSION_STATES = frozenset({"loading", "queued", "running"})


class _Chip(QToolButton):
    """A card control. Click never reaches the card body underneath.

    `on_hover` lets the card restyle this chip from the palette when the
    pointer crosses it — handoff §4.1d gives pencil and gear a brighter
    resting/hover pair, and `palette.control_chip` models exactly that.
    """

    def __init__(self, size: int, parent: QWidget, on_hover=None,
                 on_focus=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self._on_hover = on_hover
        self._on_focus = on_focus
        self.hovered = False

    def enterEvent(self, event) -> None:
        self.hovered = True
        if self._on_hover is not None:
            self._on_hover()

    def leaveEvent(self, event) -> None:
        self.hovered = False
        if self._on_hover is not None:
            self._on_hover()

    def focusInEvent(self, event) -> None:
        if self._on_focus is not None:
            self._on_focus()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        if self._on_focus is not None:
            self._on_focus()
        super().focusOutEvent(event)

    def mousePressEvent(self, event) -> None:
        event.accept()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        event.accept()
        super().mouseReleaseEvent(event)


class _ActionButton(QPushButton):
    """The card's state action (Launch, Retry, Enter 2FA, Quit, Cancel).

    Keyboard-reachable like the pencil and gear: Tab lands on it and it tells
    the card when focus arrives or leaves, so the focus-within reveal keeps it
    on screen while it is the focused control. Return activates it as Space
    does — QPushButton only clicks on Return as a dialog default, and left
    alone the key would fall through to the card body, whose Return toggles
    selection instead.
    """

    def __init__(self, parent: QWidget, on_focus=None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.TabFocus)
        self._on_focus = on_focus

    def focusInEvent(self, event) -> None:
        if self._on_focus is not None:
            self._on_focus()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        if self._on_focus is not None:
            self._on_focus()
        super().focusOutEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)


class RosterCard(QFrame):
    clicked = Signal(str)
    star_clicked = Signal(str)
    edit_clicked = Signal(str)
    gear_clicked = Signal(str)
    launch_clicked = Signal(str)
    cancel_clicked = Signal(str)
    quit_clicked = Signal(str)
    enter_2fa_clicked = Signal(str)
    retry_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(CARD_W, CARD_H)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)

        self._entry = None
        self._selected = False
        self._starred = False
        self._position: Optional[int] = None
        self._hover = False
        self._is_dark = True
        self._pixmap: Optional[QPixmap] = None
        self._state = "idle"
        self._message = ""
        self._raw_error = ""

        self._renders = ToonRenders.instance()
        self._renders.render_landed.connect(self._on_render_landed)
        self._renders.set_promoted.connect(self._on_set_promoted)
        self._tier: Optional[str] = None

        self.ribbon = _Chip(24, self, on_focus=self._refresh_controls)
        self.ribbon.setObjectName("card_ribbon")
        self.ribbon.move(CARD_W - 24 - 9, 9)
        self.ribbon.clicked.connect(self._emit_click)

        self.star = _Chip(26, self, on_focus=self._refresh_controls)
        self.star.setObjectName("card_star")
        self.star.move(8, 8)
        self.star.clicked.connect(lambda: self._emit(self.star_clicked))

        self.pencil = _Chip(24, self, on_hover=self._restyle,
                            on_focus=self._refresh_controls)
        self.pencil.setObjectName("card_pencil")
        self.pencil.move(6, CARD_H - 24 - 6)
        self.pencil.setText("✏")
        self.pencil.clicked.connect(lambda: self._emit(self.edit_clicked))

        self.gear = _Chip(24, self, on_hover=self._restyle,
                          on_focus=self._refresh_controls)
        self.gear.setObjectName("card_gear")
        self.gear.move(CARD_W - 24 - 6, CARD_H - 24 - 6)
        self.gear.setText("⚙")
        self.gear.clicked.connect(lambda: self._emit(self.gear_clicked))

        self.name = QLabel(self)
        self.name.setObjectName("card_name")
        self.name.setGeometry(10, 144, CARD_W - 20, 18)
        self.user = QLabel(self)
        self.user.setObjectName("card_user")
        self.user.setGeometry(10, 162, CARD_W - 20, 14)
        self.footer = QLabel(self)
        self.footer.setObjectName("card_footer")
        self.footer.setGeometry(10, 178, CARD_W - 20, 14)
        footer_font = self.footer.font()
        footer_font.setPixelSize(11)
        self.footer.setFont(footer_font)

        self.action = _ActionButton(self, on_focus=self._refresh_controls)
        self.action.setObjectName("card_action")
        # Pencil and gear occupy x=6..29 and x=118..141. The action owns the
        # clear lane between them whenever the hover/focus cluster is present.
        self.action.setGeometry(34, CARD_H - 30, 80, 24)
        self.action.setCursor(Qt.PointingHandCursor)
        self.action.clicked.connect(self._on_action)
        self.action.setVisible(False)

        # PulsingDot's signature is (size, parent) and it setFixedSize's itself
        # to size+8 for the pulse halo — so pass the 6px dot handoff §4.1d asks
        # for and move it; setGeometry would be overridden by that fixed size.
        self.dot = PulsingDot(6, self)
        self.dot.setObjectName("card_running_dot")
        self.dot.move(10, 184)
        self.dot.setVisible(False)

        # Seed both stateful chips so a card reads correctly before the shelf
        # has told it anything. Must follow the labels: these setters restyle.
        self.ribbon.setText("+")
        self.star.setText("☆")

        self._set_controls_visible(False)
        self.apply_theme(True)

    # ── inbound ────────────────────────────────────────────────────────────

    def entry(self):
        return self._entry

    def account_id(self) -> str:
        return self._entry.account_id if self._entry is not None else ""

    def set_entry(self, entry) -> None:
        self._entry = entry
        self.name.setText(entry.display_name)
        self.user.setText(entry.username)
        self._load_portrait()
        self._restyle()
        self.set_state(entry.state, entry.message, entry.raw_error)
        self.update()

    def set_selected(self, value: bool) -> None:
        self._selected = bool(value)
        self._restyle()
        self._apply_state()
        self.update()

    def is_selected(self) -> bool:
        return self._selected

    def set_position(self, position: Optional[int]) -> None:
        self._position = position
        self.ribbon.setText("+" if position is None else str(position))
        self._restyle()
        self.update()

    def set_starred(self, value: bool) -> None:
        self._starred = bool(value)
        self.star.setText("★" if self._starred else "☆")
        self._restyle()
        self.update()

    def is_starred(self) -> bool:
        return self._starred

    # ── readouts (test surface) ────────────────────────────────────────────

    def name_text(self) -> str:
        return self.name.text()

    def user_text(self) -> str:
        return self.user.text()

    def footer_text(self) -> str:
        return self.footer.text()

    def state(self) -> str:
        return self._state

    def raw_error(self) -> str:
        return self._raw_error

    def set_state(self, state: str, message: str = "", raw: str = "") -> None:
        self._state = state if state in ACTION_MAP else "idle"
        self._message = message or ""
        self._raw_error = raw or message or ""
        self._apply_state()

    def action_label(self) -> str:
        return self.action.text()

    def action_visible(self) -> bool:
        return self.action.isVisibleTo(self)

    def dot_visible(self) -> bool:
        return self.dot.isVisibleTo(self)

    def ribbon_text(self) -> str:
        return self.ribbon.text()

    def requested_pose(self) -> str:
        return CARD_POSE

    def head_fit_for(self, species: Optional[str]) -> tuple[float, int]:
        return HEAD_FIT.get((species or "").lower(), NEUTRAL_FIT)

    def controls_revealed(self) -> bool:
        return self.pencil.isVisibleTo(self)

    def portrait_pixmap(self) -> Optional[QPixmap]:
        return self._pixmap

    # ── portrait ───────────────────────────────────────────────────────────

    def _wants_render(self) -> bool:
        """Only a `render`-mode entry with a toon name draws a Rendition. A
        Corporate Clash account can carry a dna and still be `species` mode —
        `model.portrait_mode` decides, and `model.lineup_entries` branches on
        the same field, so the card and the hero agree by construction. No
        name, no read: the cache is keyed by toon name, and asking it about
        "" would be asking about nobody (mirrors card_preview_widget)."""
        e = self._entry
        return (e is not None and e.portrait_mode == PORTRAIT_RENDER
                and bool(e.dna) and bool(e.toon_name))

    def portrait_tier(self) -> Optional[str]:
        """`"current"`, `"previous"` (older outfit shown while a newer one
        downloads), `"candidate"` (the toon has no complete set; what has
        landed of its newest outfit), or None when nothing is drawn."""
        return self._tier

    def _read_portrait(self) -> Optional[tuple[QPixmap, str]]:
        """One sync read of this entry's head: (pixmap, tier) or None."""
        if not self._wants_render():
            return None
        e = self._entry
        return self._renders.pixmap_for(e.game, e.toon_name, CARD_POSE)

    def _show_portrait(self, hit: Optional[tuple[QPixmap, str]]) -> None:
        self._pixmap, self._tier = hit if hit is not None else (None, None)
        self.setToolTip(self._portrait_tooltip())

    def _portrait_tooltip(self) -> str:
        if self._tier == "previous":
            return PREVIOUS_LOOK_TOOLTIP
        e = self._entry
        if self._pixmap is None and self._wants_render() and e is not None \
                and self._renders.awaiting_render(e.game, e.toon_name):
            return AWAITING_RENDER_TOOLTIP.format(name=e.toon_name)
        return ""

    def _load_portrait(self) -> None:
        """Clear-or-replace: the set-entry and promotion path."""
        self._show_portrait(self._read_portrait())

    def _on_render_landed(self, game: str, name: str, pose: str) -> None:
        # The facade is process-wide, so this fires for every card. Only a
        # landing of THIS card's pose for THIS toon is worth a repaint.
        # A landing never clears: it only ever adds a file, so a miss means
        # the file belongs to an outfit the store cannot serve yet and what
        # is showing is still exactly what the store would serve.
        e = self._entry
        if e is None or pose != CARD_POSE or game != e.game or name != (e.toon_name or ""):
            return
        hit = self._read_portrait()
        if hit is None:
            return
        self._show_portrait(hit)
        self.update()

    def _on_set_promoted(self, game: str, name: str) -> None:
        e = self._entry
        if e is None or game != e.game or name != (e.toon_name or ""):
            return
        self._load_portrait()
        self.update()

    # ── interaction ────────────────────────────────────────────────────────

    def _emit(self, signal) -> None:
        if self._entry is not None:
            signal.emit(self._entry.account_id)

    def _emit_click(self) -> None:
        self._emit(self.clicked)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self._emit_click()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._emit_click()
            event.accept()
            return
        super().keyPressEvent(event)

    def enterEvent(self, event) -> None:
        self._hover = True
        self._refresh_controls()
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover = False
        self._refresh_controls()
        self.update()

    def focusInEvent(self, event) -> None:
        self._refresh_controls()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        # Qt moves QApplication.focusWidget() before delivering FocusOut, so
        # _focus_within() already sees the new owner and can decide now.
        self._refresh_controls()
        super().focusOutEvent(event)

    def _focus_within(self) -> bool:
        """True when this card or any of its chips holds focus. Tabbing from
        the card to its own pencil must not read as leaving the card."""
        focused = QApplication.focusWidget()
        return focused is not None and (focused is self
                                        or self.isAncestorOf(focused))

    def _refresh_controls(self) -> None:
        self._set_controls_visible(self._hover or self._focus_within())

    def _set_controls_visible(self, value: bool) -> None:
        self.pencil.setVisible(value)
        self.gear.setVisible(value)
        self._apply_state()

    def _footer_for_state(self) -> str:
        if self._state == "failed":
            return summarize_error(self._message)
        if self._state == "queued" and self._message:
            return f"In queue · {self._message}"
        if self._state == "running":
            return "Running"
        if self._state in ("logging_in", "launching", "loading"):
            return self._message or {"logging_in": "Logging in…",
                                     "launching": "Launching…",
                                     "loading": "Loading…"}[self._state]
        if self._state == "need_2fa":
            return "2FA required"
        return self._entry.footer if self._entry is not None else ""

    def _set_footer_text(self, text: str, full_text: Optional[str] = None) -> None:
        """Elide to the footer width and retain the full status as a tooltip.

        A 148px card cannot hold an arbitrary error summary, and QLabel would
        otherwise cut it mid-glyph. Geometry must be assigned before calling
        this helper so the metrics use the status band's current width.
        """
        metrics = QFontMetrics(self.footer.font())
        self.footer.setText(metrics.elidedText(
            text, Qt.ElideRight, self.footer.width()))
        tooltip = text if full_text is None else full_text
        self.footer.setToolTip(tooltip if tooltip else "")

    def _should_show_action(self) -> bool:
        label, _, _ = ACTION_MAP[self._state]
        if label is None:
            return False
        if self._state in URGENT_STATES:
            return True                      # spec Q2: never hidden
        if self._state in _SESSION_STATES:
            return self._hover or self._focus_within()
        # idle: a checked card defers its Launch to Play (spec Q7)
        if self._selected:
            return False
        return self._hover or self._focus_within()

    def _apply_state(self) -> None:
        label, _, enabled = ACTION_MAP[self._state]
        self.action.setText(label or "")
        self.action.setEnabled(bool(enabled))
        self.action.setVisible(self._should_show_action())
        act = gp.card_action(
            self._state,
            self._entry.accent if self._entry is not None else gp.game_accent("ttr"),
            self._is_dark)
        self.action.setStyleSheet(
            "QPushButton {"
            f" background: {act['bg'].name()};"
            f" color: {act['ink'].name()};"
            " border: none; border-radius: 8px; font-size: 11px;"
            " font-weight: 700; }")
        running = self._state == "running"
        controls_revealed = self.controls_revealed()
        status_promoted = self.action.isVisibleTo(self) or controls_revealed
        self.user.setVisible(not status_promoted)
        status_y = 162 if status_promoted else 178
        if running:
            # PulsingDot pads the 6px core to a 14x14 halo. It travels with the
            # footer, whose remaining 110px easily holds the word "Running".
            self.dot.move(10, status_y)
            self.footer.setGeometry(28, status_y, CARD_W - 38, 14)
        else:
            self.footer.setGeometry(10, status_y, CARD_W - 20, 14)
        ink = gp.status_ink(self._state, self._is_dark)
        self.footer.setStyleSheet(
            f"color: {ink['text'].name()};"
            " background: transparent;")
        footer_text = self._footer_for_state()
        full_text = self._message if self._state == "failed" and self._message \
            else footer_text
        self._set_footer_text(footer_text, full_text)
        self.dot.set_color(ink["dot"].name(), pulse=running)
        self.dot.setVisible(running)
        self.update()

    def _on_action(self) -> None:
        _, signal_name, _ = ACTION_MAP[self._state]
        if signal_name and self._entry is not None:
            getattr(self, signal_name).emit(self._entry.account_id)

    # ── paint ──────────────────────────────────────────────────────────────

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self._restyle()
        self._apply_state()
        self.update()

    def _restyle(self) -> None:
        ink = gp.card_ink(self._selected, self._is_dark)
        self.name.setStyleSheet(
            f"color: {ink['name'].name()}; font-size: 13px; font-weight: 700;"
            " background: transparent;")
        self.user.setStyleSheet(
            f"color: {ink['user'].name()}; font-size: 10px;"
            " font-family: monospace; background: transparent;")
        # Each chip has its own palette entry — they are not one style. The
        # ribbon turns blue when the card is on stage, the star turns gold when
        # it marks the game-wide main, and pencil/gear brighten on hover.
        for btn, size in ((self.pencil, 13), (self.gear, 14)):
            chip = gp.control_chip(btn.hovered, self._is_dark)
            btn.setStyleSheet(
                "QToolButton {"
                f" background: {chip['bg'].name(QColor.HexArgb)};"
                f" color: {chip['ink'].name()};"
                f" border: none; border-radius: 8px; font-size: {size}px; }}")

        star = gp.card_star(self._starred, self._is_dark)
        self.star.setStyleSheet(
            "QToolButton {"
            f" background: {star['bg'].name(QColor.HexArgb)};"
            f" color: {star['ink'].name()};"
            " border: none; border-radius: 8px; font-size: 14px; }")

        rib = gp.ribbon(self._selected, self._is_dark)
        self.ribbon.setStyleSheet(
            "QToolButton {"
            f" background: {rib['bg'].name(QColor.HexArgb)};"
            f" color: {rib['ink'].name()};"
            f" border: 1px solid {rib['border'].name(QColor.HexArgb)};"
            " border-radius: 8px; font-size: 13px; }")

    def paintEvent(self, event) -> None:
        e = self._entry
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        if e is None:
            # No entry yet: there is no accent to wash with, so paint the plain
            # app surface rather than inventing a colour here.
            base = gp.panel(self._is_dark)
            p.setPen(Qt.NoPen)
            p.setBrush(base["bg"])
            p.drawRoundedRect(r, CARD_RADIUS, CARD_RADIUS)
            p.setBrush(Qt.NoBrush)
            p.setPen(base["border"])
            p.drawRoundedRect(r, CARD_RADIUS, CARD_RADIUS)
            p.end()
            return

        d = gp.card_surface(e.accent, self._selected, self._is_dark)
        # Handoff §4.1d is a 180° wash, not a flat fill: both stops are painted.
        wash = QLinearGradient(QPointF(r.left(), r.top()),
                               QPointF(r.left(), r.bottom()))
        wash.setColorAt(0.0, d["top"])
        wash.setColorAt(1.0, d["bot"])
        p.setPen(Qt.NoPen)
        p.setBrush(wash)
        p.drawRoundedRect(r, CARD_RADIUS, CARD_RADIUS)

        box = QRect((CARD_W - PORTRAIT) // 2, 12, PORTRAIT, PORTRAIT)
        if self._pixmap is not None and not self._pixmap.isNull():
            scale, shift_pct = self.head_fit_for(e.species)
            w = int(PORTRAIT * scale)
            h = int(PORTRAIT * scale)
            x = box.center().x() - w // 2
            y = box.top() + int(PORTRAIT * shift_pct / 100.0)
            p.drawPixmap(QRect(x, y, w, h), self._pixmap)
        else:
            paint_race_silhouette(p, box, e.species, e.accent)

        p.setBrush(Qt.NoBrush)
        p.setPen(d["border"])
        p.drawRoundedRect(r, CARD_RADIUS, CARD_RADIUS)
        p.end()
