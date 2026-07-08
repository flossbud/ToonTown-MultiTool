"""GamePickerView — the Keysets entry screen shown when more than one game is
installed: a title/subtitle over a wrapping, centered row of `GameBannerCard`
banner cards. Picking a card emits `game_chosen(game_key)`.

This is a VIEW: it renders installed games and emits a selection signal; it
never mutates keymaps or launches anything itself.

Kit law: paint the banner image/scrim/gradients/border in paintEvent (mirrors
SetListItem's technique); the footer text/dot/chevron are transparent-
background child widgets laid out on top. NEVER attach a QGraphicsEffect to
a widget that also custom-paints.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLayout, QSizePolicy, QVBoxLayout, QWidget,
)

from utils.color_math import darken_rgb, with_alpha
from ._assets import asset_path
from .game_meta import GAME_META

_CARD_W = 360
_CARD_RADIUS = 18
_BANNER_H = round(_CARD_W * 0.49)
_FOOTER_H = 60
_CARD_H = _BANNER_H + _FOOTER_H
_ROW_GAP = 16


class _CenteredFlowLayout(QLayout):
    """Wraps children left-to-right with `gap` spacing, centering each
    completed row within the available width (fixed-size items only)."""

    def __init__(self, gap: int, parent=None):
        super().__init__(parent)
        self._gap = gap
        self._items: list = []

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + QSize(left + right, top + bottom)

    def _do_layout(self, rect, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(left, top, -right, -bottom)
        max_w = max(1, effective.width())

        lines: list[tuple[list, int, int]] = []
        current: list = []
        cur_w = 0
        cur_h = 0
        for item in self._items:
            hint = item.sizeHint()
            added_w = hint.width() + (self._gap if current else 0)
            if current and cur_w + added_w > max_w:
                lines.append((current, cur_w, cur_h))
                current, cur_w, cur_h = [], 0, 0
                added_w = hint.width()
            current.append((item, hint))
            cur_w += added_w
            cur_h = max(cur_h, hint.height())
        if current:
            lines.append((current, cur_w, cur_h))

        y = effective.y()
        total_h = 0
        for items_hints, line_w, line_h in lines:
            if not test_only:
                x = effective.x() + max(0, (max_w - line_w) // 2)
                for item, hint in items_hints:
                    item.setGeometry(QRect(QPoint(x, y), hint))
                    x += hint.width() + self._gap
            y += line_h + self._gap
            total_h += line_h + self._gap
        if lines:
            total_h -= self._gap
        return top + bottom + total_h


class GameBannerCard(QWidget):
    """One installed game's banner card: full-bleed banner image (or an
    accent-gradient fallback when the banner asset is missing) with a bottom
    scrim, over a footer band (identity dot + title/subtitle + "Edit ›")."""

    def __init__(self, view: "GamePickerView", key: str, count: int, parent=None):
        super().__init__(parent)
        self._view = view
        self._key = key
        self._count = count
        self._meta = GAME_META[key]
        self._hovered = False

        pix = QPixmap(asset_path(self._meta.banner_asset))
        self._banner_pix = pix if not pix.isNull() else None

        self.setFixedSize(_CARD_W, _CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, _BANNER_H, 0, 0)
        outer.setSpacing(0)

        footer = QHBoxLayout()
        footer.setContentsMargins(14, 11, 14, 11)
        footer.setSpacing(10)

        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        self._dot.setStyleSheet(
            f"background-color: {self._meta.accent_b}; border-radius: 4px;"
        )
        footer.addWidget(self._dot, 0, Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        title_lbl = QLabel(self._meta.title)
        title_lbl.setStyleSheet(
            "background: transparent; border: none; color: #ffffff; "
            "font-size: 13.5px; font-weight: 700;"
        )
        text_col.addWidget(title_lbl)
        self._sub_lbl = QLabel(self.subtitle_text())
        self._sub_lbl.setStyleSheet(
            "background: transparent; border: none; "
            "color: rgba(255,255,255,0.6); font-size: 11px;"
        )
        text_col.addWidget(self._sub_lbl)
        footer.addLayout(text_col, 1)

        edit_lbl = QLabel("Edit ›")
        edit_lbl.setStyleSheet(
            "background: transparent; border: none; "
            "color: rgba(255,255,255,0.7); font-size: 11.5px; font-weight: 600;"
        )
        footer.addWidget(edit_lbl, 0, Qt.AlignVCenter)

        outer.addLayout(footer)
        outer.addStretch(1)

    # ── public API ───────────────────────────────────────────────────────
    def subtitle_text(self) -> str:
        return f"{self._count} movement sets"

    # ── input ────────────────────────────────────────────────────────────
    def _emit_click(self) -> None:
        self._view.game_chosen.emit(self._key)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self._emit_click()
        e.accept()

    def enterEvent(self, e) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(e)

    # ── paint ────────────────────────────────────────────────────────────
    def paintEvent(self, _e) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, _CARD_RADIUS, _CARD_RADIUS)

        p.save()
        p.setClipPath(path)
        p.fillPath(path, QColor("#0d0f13"))

        banner_rect = QRectF(0, 0, self.width(), _BANNER_H)
        if self._banner_pix is not None:
            scaled = self._banner_pix.scaled(
                banner_rect.size().toSize(),
                Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
            )
            sx = (scaled.width() - banner_rect.width()) / 2
            sy = (scaled.height() - banner_rect.height()) / 2
            p.drawPixmap(
                banner_rect.topLeft(), scaled,
                QRectF(sx, sy, banner_rect.width(), banner_rect.height()),
            )
        else:
            c = QColor(self._meta.accent_c)
            grad = QLinearGradient(banner_rect.topLeft(), banner_rect.bottomRight())
            grad.setColorAt(0.0, c)
            grad.setColorAt(1.0, darken_rgb(c, 0.5))
            p.fillRect(banner_rect, grad)

        scrim = QLinearGradient(banner_rect.topLeft(), banner_rect.bottomLeft())
        scrim.setColorAt(0.0, QColor(0, 0, 0, 0))
        scrim.setColorAt(0.44, QColor(0, 0, 0, 0))
        scrim.setColorAt(1.0, QColor(0, 0, 0, 184))
        p.fillRect(banner_rect, scrim)

        footer_rect = QRectF(0, _BANNER_H, self.width(), self.height() - _BANNER_H)
        fgrad = QLinearGradient(footer_rect.topLeft(), footer_rect.bottomLeft())
        fgrad.setColorAt(0.0, with_alpha(self._meta.accent_c, 0.16))
        fgrad.setColorAt(1.0, QColor(0, 0, 0, 71))
        p.fillRect(footer_rect, fgrad)

        p.setPen(QPen(with_alpha(self._meta.accent_b, 0.3), 1))
        p.drawLine(footer_rect.topLeft(), footer_rect.topRight())
        p.restore()

        border_col = (
            QColor(self._meta.accent_b) if self._hovered
            else with_alpha(self._meta.accent_b, 0.5)
        )
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(border_col, 2))
        p.drawPath(path)
        p.end()


class GamePickerView(QWidget):
    """Title + subtitle over a wrapping row of `GameBannerCard`s, one per
    installed game. Rebuilt whenever `set_games` is called."""

    game_chosen = Signal(str)

    def __init__(self, is_dark: bool = True, parent=None):
        super().__init__(parent)
        self._is_dark = is_dark
        self._cards: dict[str, GameBannerCard] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 40, 24, 40)
        outer.setSpacing(22)

        self._title = QLabel("Choose a game")
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet(
            "background: transparent; border: none; color: #ffffff; "
            "font-size: 18px; font-weight: 700;"
        )
        outer.addWidget(self._title, 0, Qt.AlignHCenter)

        self._subtitle = QLabel("")
        self._subtitle.setAlignment(Qt.AlignCenter)
        self._subtitle.setStyleSheet(
            "background: transparent; border: none; "
            "color: rgba(255,255,255,0.55); font-size: 12.5px;"
        )
        outer.addWidget(self._subtitle, 0, Qt.AlignHCenter)

        # The flow-layout row must fill the available width so its cards lay
        # out side-by-side and center within it; a hugging (sizeHint) width
        # would force every card onto its own row. heightForWidth lets the
        # column reserve the wrapped height.
        self._row_widget = QWidget()
        row_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row_policy.setHeightForWidth(True)
        self._row_widget.setSizePolicy(row_policy)
        self._row_layout = _CenteredFlowLayout(_ROW_GAP, self._row_widget)
        outer.addWidget(self._row_widget)
        outer.addStretch(1)

    # ── public API ───────────────────────────────────────────────────────
    def set_games(self, entries: list[tuple[str, int]]) -> None:
        """entries = [(game_key, set_count), ...] in display order."""
        while self._row_layout.count():
            item = self._row_layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._cards = {}

        n = len(entries)
        self._subtitle.setText(
            f"You have {n} games installed. Pick which one's keysets to edit."
        )

        for key, count in entries:
            card = GameBannerCard(self, key, count)
            self._row_layout.addWidget(card)
            self._cards[key] = card

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()
