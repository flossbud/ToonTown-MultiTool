"""Per-line painter for the Logs console. One row = ts · [Tag] · message runs
in their colors; the MESSAGE wraps (continuations align under the message
start, mirroring the bundle's flex row); ts/tag never wrap. Hover shows a
copy glyph at the right edge; a just-copied row shows `copied ✓`.

All colors come from _tokens.get_logs_tokens — nothing hardcoded here."""
from __future__ import annotations

from PySide6.QtCore import QPersistentModelIndex, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QPainter, QTextLayout,
                           QTextOption)
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from utils.icon_factory import make_copy_icon
from utils.widgets.logs_console._tokens import get_logs_tokens
from utils.widgets.logs_console.model import LINE_ROLE
from utils.widgets.portrait_badge import _qcolor_from_rgba

FONT_PX = 13
LINE_H = round(FONT_PX * 1.45)     # 19 — compact density
PAD_V = 1
PAD_H = 8
GAP = 9
RADIUS = 4
COPY_ICON = 11
COPY_RESERVE = COPY_ICON + 10      # glyph + its left padding


def _mono(weight=QFont.Normal) -> QFont:
    f = QFont()
    f.setFamilies(["Consolas", "Menlo", "DejaVu Sans Mono",
                   "Liberation Mono", "monospace"])
    f.setStyleHint(QFont.Monospace)
    f.setPixelSize(FONT_PX)
    f.setWeight(weight)
    return f


class LogLineDelegate(QStyledItemDelegate):
    def __init__(self, view):
        super().__init__(view)
        self._view = view
        self._t = get_logs_tokens(True)
        self._font = _mono()
        self._font_tag = _mono(QFont.DemiBold)
        self._fm = QFontMetricsF(self._font)
        self._fm_tag = QFontMetricsF(self._font_tag)
        self._copied: QPersistentModelIndex | None = None
        self._copy_icon = make_copy_icon(COPY_ICON,
                                         _qcolor_from_rgba(self._t["copy_glyph"]))
        # Height cache keyed by the frozen LogLine VALUE (hashable), never
        # id(line): the model's ring trim frees lines whose ids CPython can
        # reuse, which would serve stale heights. Equal lines have equal
        # heights, so value collisions are harmless.
        self._heights: dict[tuple, int] = {}

    # ── theme / state ────────────────────────────────────────────────────
    def apply_theme(self, is_dark: bool) -> None:
        self._t = get_logs_tokens(is_dark)
        self._copy_icon = make_copy_icon(COPY_ICON,
                                         _qcolor_from_rgba(self._t["copy_glyph"]))
        self._view.viewport().update()

    def set_copied(self, index) -> None:
        self._copied = QPersistentModelIndex(index)
        self._view.viewport().update()

    def clear_copied(self) -> None:
        self._copied = None
        self._view.viewport().update()

    def clear_cache(self) -> None:
        """Drop cached row heights; the pane calls this on model reset so
        trimmed lines don't linger in the cache."""
        self._heights.clear()

    # ── geometry ─────────────────────────────────────────────────────────
    def _prefix_w(self, line) -> float:
        w = self._fm.horizontalAdvance(line.time.strftime("%H:%M:%S")) + GAP
        if line.tag:
            w += self._fm_tag.horizontalAdvance(line.tag) + GAP
        return w

    def _msg_w(self, line, avail_w: float) -> float:
        """Message wrap width inside a row of avail_w total: left pad +
        prefix before it, copy reserve + right pad after it. Single source
        of truth — sizeHint and paint MUST both use this or wrap counts
        drift and rows grow dead space."""
        return avail_w - 2 * PAD_H - self._prefix_w(line) - COPY_RESERVE

    def _msg_line_count(self, line, msg_w: float) -> int:
        if not line.message:
            return 1
        tl = QTextLayout(line.message, self._font)
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        tl.setTextOption(opt)
        tl.beginLayout()
        n = 0
        while True:
            ln = tl.createLine()
            if not ln.isValid():
                break
            ln.setLineWidth(max(20.0, msg_w))
            n += 1
        tl.endLayout()
        return max(1, n)

    def sizeHint(self, option, index) -> QSize:
        line = index.data(LINE_ROLE)
        if line is None:
            return super().sizeHint(option, index)
        vw = self._view.viewport().width()
        key = (line, vw)
        cached = self._heights.get(key)
        if cached is None:
            msg_w = self._msg_w(line, vw)
            cached = self._msg_line_count(line, msg_w) * LINE_H + 2 * PAD_V
            if len(self._heights) > 4096:
                self._heights.clear()
            self._heights[key] = cached
        return QSize(vw, cached)

    # ── paint ────────────────────────────────────────────────────────────
    def paint(self, p: QPainter, option, index) -> None:
        line = index.data(LINE_ROLE)
        if line is None:
            return
        t = self._t
        r = option.rect
        hovered = bool(option.state & QStyle.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        if hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(_qcolor_from_rgba(t["hover_row"]))
            p.drawRoundedRect(QRectF(r), RADIUS, RADIUS)

        x = r.x() + PAD_H
        first_baseline = r.y() + PAD_V + (LINE_H + self._fm.ascent()
                                          - self._fm.descent()) / 2.0
        p.setFont(self._font)
        p.setPen(_qcolor_from_rgba(t["ts"]))
        ts_text = line.time.strftime("%H:%M:%S")
        p.drawText(QPointF(x, first_baseline), ts_text)
        x += self._fm.horizontalAdvance(ts_text) + GAP

        if line.tag:
            p.setFont(self._font_tag)
            p.setPen(QColor(t["tags"].get(line.tag, t["tag_fallback"])))
            p.drawText(QPointF(x, first_baseline), line.tag)
            x += self._fm_tag.horizontalAdvance(line.tag) + GAP

        msg_w = self._msg_w(line, r.width())
        p.setFont(self._font)
        p.setPen(QColor(t["levels"].get(line.level, t["levels"]["info"])))
        tl = QTextLayout(line.message, self._font)
        topt = QTextOption()
        topt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        tl.setTextOption(topt)
        tl.beginLayout()
        i = 0
        while True:
            ln = tl.createLine()
            if not ln.isValid():
                break
            ln.setLineWidth(max(20.0, msg_w))
            ln.setPosition(QPointF(0, i * LINE_H))
            i += 1
        tl.endLayout()
        tl.draw(p, QPointF(x, r.y() + PAD_V + (LINE_H - self._fm.height()) / 2.0))

        is_copied = (self._copied is not None and self._copied.isValid()
                     and QPersistentModelIndex(index) == self._copied)
        if is_copied:
            p.setFont(self._font)
            p.setPen(QColor(t["copied"]))
            label = "copied ✓"
            lw = self._fm.horizontalAdvance(label)
            p.drawText(QPointF(r.right() - PAD_H - lw, first_baseline), label)
        elif hovered:
            self._copy_icon.paint(
                p, r.right() - PAD_H - COPY_ICON,
                int(r.y() + PAD_V + (LINE_H - COPY_ICON) / 2),
                COPY_ICON, COPY_ICON)
        p.restore()
