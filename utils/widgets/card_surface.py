"""CardSurface - the v2 kit's identity-tinted group card ("toon card" anatomy).

Surface (rich tint): 158deg gradient body (dark: darken(c,0.30)->darken(c,0.15);
light: lighten(c,0.80)->lighten(c,0.90)), 2px border (dark alpha(b,0.55) /
light alpha(c,0.50)), radius 20, plus a PAINTED dark under-shadow inside an
EDGE_PAD margin budget. The mock's accent glow was removed entirely by
operator decision (2026-07-06): border + drop shadow only.
Painted, never QGraphicsDropShadowEffect -
the effect clips on macOS (tabs/multitoon/_compact_layout.py:141) and
QGraphicsEffect on custom-painted widgets causes painter conflicts.

Header: PortraitBadge + title/sub column + optional right-aligned buttons.
Body: vertical stack (gap 12) filled via add_row().
Theme flips may animate (220ms lerp) via apply_theme(animate=True).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget, QFrame

from utils.card_dim import lerp_color
from utils.color_math import darken_rgb, lighten_rgb, with_alpha
from utils.theme_manager import V2_ACCENTS, get_v2_tokens
from utils.widgets.portrait_badge import PortraitBadge

EDGE_PAD = 10          # px reserved on each side for the drop shadow
HALO_STEPS = 8
THEME_FADE_MS = 220


class CardSurface(QFrame):
    def __init__(self, accent_key: str, title: str, sub: str | None = None,
                 icon=None, logo_path: str | None = None, parent=None):
        super().__init__(parent)
        self.accent_key = accent_key
        self._a = V2_ACCENTS.get(accent_key, V2_ACCENTS["blue"])
        self._is_dark = True
        self._t = get_v2_tokens(True)
        self._anim = None
        self._grad_top, self._grad_bot, self._border_col = self._target_colors(True)
        self.setStyleSheet("background: transparent;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(EDGE_PAD + 16, EDGE_PAD + 14, EDGE_PAD + 16, EDGE_PAD + 16)
        outer.setSpacing(12)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(12)
        self.badge = PortraitBadge(accent_key=accent_key, icon=icon,
                                   logo_path=logo_path, parent=self)
        head.addWidget(self.badge)
        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        self._text_col = text_col
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("background: transparent; border: none;")
        text_col.addWidget(self.title_label)
        self.sub_label = None
        self._sub_mono = False
        self._sub_color_override = None
        if sub:
            self._ensure_sub().setText(sub)
        head.addLayout(text_col, 1)
        self._header_button_row = QWidget(self)
        self._header_button_row.setStyleSheet("background: transparent;")
        btn_lay = QHBoxLayout(self._header_button_row)
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.setSpacing(6)
        self._header_button_slot = btn_lay
        self._header_button_row.hide()
        head.addWidget(self._header_button_row)
        outer.addLayout(head)

        self._body = QWidget(self)
        self._body.setStyleSheet("background: transparent;")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(12)
        outer.addWidget(self._body)

    # ── public API ──────────────────────────────────────────────────────
    def add_row(self, widget) -> None:
        widget.setParent(self._body)
        self._body_layout.addWidget(widget)

    def add_header_button(self, button) -> None:
        button.setParent(self._header_button_row)
        self._header_button_slot.addWidget(button)
        self._header_button_row.show()

    def set_sub(self, text: str, *, color_override: str | None = None,
                rich_text: bool = False, mono: bool = False) -> None:
        lbl = self._ensure_sub()
        lbl.setTextFormat(Qt.RichText if rich_text else Qt.PlainText)
        lbl.setText(text)
        self._sub_mono = mono
        self._sub_color_override = color_override
        self._style_text()

    def apply_theme(self, is_dark: bool, animate: bool = False) -> None:
        import utils.motion as motion
        self._is_dark = is_dark
        self._t = get_v2_tokens(is_dark)
        self.badge.apply_theme(is_dark)
        self._style_text()
        top, bot, border = self._target_colors(is_dark)
        if animate and not motion.is_reduced():
            start = (QColor(self._grad_top), QColor(self._grad_bot),
                     QColor(self._border_col))
            anim = QVariantAnimation(self)
            anim.setDuration(THEME_FADE_MS)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)

            def _tick(v, s=start, e=(top, bot, border)):
                self._grad_top = lerp_color(s[0], e[0], v)
                self._grad_bot = lerp_color(s[1], e[1], v)
                self._border_col = lerp_color(s[2], e[2], v)
                self.update()
            anim.valueChanged.connect(_tick)
            if self._anim is not None:
                self._anim.stop()
            self._anim = anim
            anim.start()
        else:
            self._grad_top, self._grad_bot, self._border_col = top, bot, border
            self.update()

    def pulse_highlight(self) -> None:
        """One-shot attention pulse: the border lerps to the bright accent
        and back (600ms triangle). Painted-state animation - QGraphicsEffects
        conflict with custom paintEvents in this codebase."""
        import utils.motion as motion
        if motion.is_reduced():
            return
        base = QColor(self._border_col)
        hot = QColor(self._a["b"])
        anim = QVariantAnimation(self)
        anim.setDuration(600)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _tick(v):
            try:
                tri = 1.0 - abs(2 * float(v) - 1.0)
                self._border_col = lerp_color(base, hot, tri)
                self.update()
            except RuntimeError:
                pass

        def _done():
            try:
                self._border_col = base
                self.update()
            except RuntimeError:
                pass
        anim.valueChanged.connect(_tick)
        anim.finished.connect(_done)
        self._pulse_anim = anim
        anim.start()

    # ── internals ───────────────────────────────────────────────────────
    def _ensure_sub(self) -> QLabel:
        if self.sub_label is None:
            self.sub_label = QLabel()
            self.sub_label.setWordWrap(True)
            self.sub_label.setStyleSheet("background: transparent; border: none;")
            self._text_col.addWidget(self.sub_label)
        return self.sub_label

    def _target_colors(self, is_dark: bool):
        c = QColor(self._a["c"])
        if is_dark:
            return (darken_rgb(c, 0.30), darken_rgb(c, 0.15),
                    with_alpha(self._a["b"], 0.55))
        return (lighten_rgb(c, 0.80), lighten_rgb(c, 0.90),
                with_alpha(self._a["c"], 0.50))

    def _style_text(self) -> None:
        t = self._t
        self.title_label.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {t['title']}; "
            "background: transparent; border: none;")
        if self.sub_label is not None:
            color = self._sub_color_override or t["sub"]
            self.sub_label.setStyleSheet(
                f"font-size: 11px; color: {color}; "
                "background: transparent; border: none;")
            f = QFont()
            if self._sub_mono:
                f.setFamilies(["JetBrains Mono", "Cascadia Mono", "monospace"])
                f.setStyleHint(QFont.Monospace)
            self.sub_label.setFont(f)

    def _body_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(EDGE_PAD, EDGE_PAD, -EDGE_PAD, -EDGE_PAD)

    def paintEvent(self, event):
        if self.width() <= 0 or self.height() <= 0:
            return
        t = self._t
        r = self._body_rect()
        radius = t["radius_card"]
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # Dark under-shadow (approx. `0 8px 22px rgba(0,0,0,0.4)`): layered
        # strokes around the body path shifted down 4px.
        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(r.translated(0, 4), radius, radius)
        self._paint_halo(p, shadow_path, QColor(0, 0, 0), 9,
                         0.40 if self._is_dark else 0.10)

        # Body gradient (~158deg: down + slightly right, pinwheel convention).
        grad = QLinearGradient(r.topLeft().x(), r.topLeft().y(),
                               r.x() + r.width() * 0.38, r.y() + r.height())
        grad.setColorAt(0.0, self._grad_top)
        grad.setColorAt(1.0, self._grad_bot)
        p.fillPath(path, grad)

        # 2px border, stroked at double width clipped to the path (inner half
        # survives) - the pinwheel card's border technique.
        p.save()
        p.setClipPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(self._border_col, 4))
        p.drawPath(path)
        p.restore()
        p.end()

    @staticmethod
    def _paint_halo(p: QPainter, path: QPainterPath, color: QColor,
                    spread: int, peak_alpha: float) -> None:
        """Layered-alpha stroke halo: HALO_STEPS strokes of growing width and
        quadratically-fading alpha approximate a gaussian glow. Painted BEFORE
        the body fill, so the inner stroke halves are covered by it. No alpha
        floor: the outermost strokes must fade to nothing, or the halo reads
        as a wide colored band instead of a glow."""
        p.setBrush(Qt.NoBrush)
        for i in range(HALO_STEPS, 0, -1):
            frac = i / HALO_STEPS
            col = QColor(color)
            col.setAlphaF(peak_alpha * (1.0 - frac) ** 2)
            pen = QPen(col, spread * 2 * frac)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawPath(path)
