"""LogsCard — the whole Logs tab surface. v0 = CardSurface shell (purple,
gap 11) + pulsing status line + console pane. The toolbar (source segment,
search, follow button), tag chips, and header actions are added by the
follow-up tasks in the same plan."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from utils.icon_factory import make_nav_terminal
from utils.theme_manager import get_v2_tokens
from utils.widgets.card_surface import CardSurface
from utils.widgets.logs_console._tokens import get_logs_tokens
from utils.widgets.logs_console.model import LogLineModel
from utils.widgets.logs_console.pane import LogConsolePane
from utils.widgets.logs_console.proxy import LogFilterProxy
from utils.widgets.logs_console.records import make_line
from utils.widgets.pill_controls import SegmentedPill
from utils.widgets.portrait_badge import _qcolor_from_rgba

PULSE_MS = 2800


class _StatusDot(QWidget):
    """8px breathing activity dot (opacity 1 -> 0.45 -> 1, 2.8s ease-in-out).
    Animates only while visible (the Spinner precedent) — the Logs tab is
    hidden almost always, and an infinite-loop QVariantAnimation on a hidden
    widget would tick Python callbacks forever.
    Painted glow — no QGraphicsEffect (kit law). Static under reduce-motion."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.setStyleSheet("background: transparent;")
        self._color = QColor("#56d66a")
        self._glow_alpha = 0.7
        self._opacity = 1.0
        self._anim = None

    def set_colors(self, dot_hex: str, glow_alpha: float) -> None:
        self._color = QColor(dot_hex)
        self._glow_alpha = glow_alpha
        self.update()

    def start(self) -> None:
        """Idempotent and gated: no-op while hidden, already running, or
        under reduce-motion. showEvent covers the visible-later path."""
        import utils.motion as motion
        if self._anim is not None or not self.isVisible() or motion.is_reduced():
            return
        a = QVariantAnimation(self)
        a.setDuration(PULSE_MS)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setLoopCount(-1)
        a.setEasingCurve(QEasingCurve.InOutSine)
        a.valueChanged.connect(self._tick)
        self._anim = a
        a.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()   # stopped anims must not pile up as children
            self._anim = None
        self._opacity = 1.0
        self.update()

    def _tick(self, v) -> None:
        tri = 1.0 - abs(2.0 * float(v) - 1.0)     # 0 -> 1 -> 0 per loop
        self._opacity = 1.0 - 0.55 * tri           # 1 -> 0.45 -> 1
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setOpacity(self._opacity)
        center = QPointF(7.0, 7.0)
        p.setPen(Qt.NoPen)
        for radius, frac in ((7.0, 0.25), (5.5, 0.45)):
            halo = QColor(self._color)
            halo.setAlphaF(self._glow_alpha * frac)
            p.setBrush(halo)
            p.drawEllipse(center, radius, radius)
        p.setBrush(self._color)
        p.drawEllipse(center, 4.0, 4.0)
        p.end()


class LogsCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_dark = True
        self._t = get_logs_tokens(True)
        self.model = LogLineModel(self)
        self.proxy = LogFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self.surface = CardSurface(
            "purple", "Logs",
            icon=make_nav_terminal(20, QColor("#ffffff")), gap=11)
        outer = QVBoxLayout(self)
        # CardSurface reserves EDGE_PAD(10)/side for its painted shadow, so
        # these margins + 10 = the bundle's visible 12px 16px 16px padding.
        outer.setContentsMargins(6, 2, 6, 6)
        outer.addWidget(self.surface)

        status_row = QWidget()
        status_row.setStyleSheet("background: transparent;")
        srl = QHBoxLayout(status_row)
        srl.setContentsMargins(0, 0, 0, 0)
        srl.setSpacing(6)
        self.dot = _StatusDot(status_row)
        self.status = QLabel(status_row)
        srl.addWidget(self.dot)
        srl.addWidget(self.status)
        srl.addStretch()
        self.surface.set_sub_widget(status_row)

        # Toolbar: source scope · search · follow/pause (spec toolbar row).
        self.SCOPES = [("All", "all"), ("Terminal", "raw"),
                       ("Input", "input"), ("TTR API", "api")]
        toolbar = QWidget()
        toolbar.setStyleSheet("background: transparent;")
        tbl = QHBoxLayout(toolbar)
        tbl.setContentsMargins(0, 0, 0, 0)
        tbl.setSpacing(8)
        self.segment = SegmentedPill([label for label, _ in self.SCOPES])
        self.segment.index_changed.connect(self._on_scope_changed)
        tbl.addWidget(self.segment)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter…")
        self.search.setFixedHeight(30)
        self.search.setClearButtonEnabled(False)
        self.search.textChanged.connect(self._on_query_changed)
        tbl.addWidget(self.search, 1)
        self.follow_btn = QPushButton()
        self.follow_btn.setFixedSize(30, 30)
        self.follow_btn.setCursor(Qt.PointingHandCursor)
        self.follow_btn.clicked.connect(
            lambda: self.pane.set_following(not self.pane.is_following()))
        tbl.addWidget(self.follow_btn)
        self.surface.add_row(toolbar)

        self.pane = LogConsolePane(self.proxy)
        self.surface.add_row(self.pane, stretch=1)

        self.proxy.rowsInserted.connect(self._refresh_status)
        self.proxy.rowsRemoved.connect(self._refresh_status)
        self.proxy.modelReset.connect(self._refresh_status)
        self.pane.follow_changed.connect(self._refresh_status)
        self.pane.follow_changed.connect(self._refresh_follow_icon)

        self.apply_theme(True)
        self.dot.start()
        self._refresh_status()

    # ── public API ──────────────────────────────────────────────────────
    def append(self, message: str, level: str | None = None) -> None:
        self.model.append(make_line(message, level=level))

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self._t = get_logs_tokens(is_dark)
        self.surface.apply_theme(is_dark)
        self.pane.apply_theme(is_dark)
        self.dot.set_colors(self._t["dot"], self._t["dot_glow_alpha"])
        self.status.setStyleSheet(
            f"background: transparent; font-size: 11px; "
            f"color: {self._t['status_text']};")

        t = self._t
        self.segment.apply_theme(is_dark, accent_key="purple")
        self.search.setStyleSheet(
            "QLineEdit {"
            f" background: {t['search_bg']}; border: 1px solid {t['search_border']};"
            f" border-radius: 15px; color: {t['search_text']}; padding: 0 13px;"
            " font-family: 'Consolas','Menlo','DejaVu Sans Mono','Liberation Mono',monospace;"
            " font-size: 11.5px; }"
            f"QLineEdit:focus {{ border: 1px solid {t['search_focus']}; }}")
        pal = self.search.palette()
        pal.setColor(QPalette.PlaceholderText,
                     _qcolor_from_rgba(t["search_placeholder"]))
        self.search.setPalette(pal)
        tk = get_v2_tokens(is_dark)
        self.follow_btn.setStyleSheet(
            "QPushButton {"
            f" background: {tk['btn_bg']}; border: 1px solid {tk['btn_border']};"
            " border-radius: 15px; }"
            f"QPushButton:hover {{ background: {tk['ctrl_hover']}; }}")
        self._refresh_follow_icon()

    # ── internals ───────────────────────────────────────────────────────
    def _on_scope_changed(self, idx: int) -> None:
        self.proxy.set_scope(self.SCOPES[idx][1])
        self._refresh_status()
        self._refresh_empty_state()

    def _on_query_changed(self, text: str) -> None:
        self.proxy.set_query(text)
        self._refresh_status()
        self._refresh_empty_state()

    def _refresh_empty_state(self) -> None:
        q = self.search.text().strip()
        self.pane.set_empty_text(
            f'No matching lines for "{q}".' if q else "No matching lines.")
        self.pane.refresh_empty_state()

    def _narrowed(self) -> bool:
        return bool(self.search.text().strip())   # chips task ORs in active chips

    def _refresh_follow_icon(self, *_args) -> None:
        from utils.icon_factory import make_pause_icon, make_play_icon
        color = QColor("#ffffff" if self._is_dark else "#475569")
        icon = (make_pause_icon(11, color) if self.pane.is_following()
                else make_play_icon(11, color))
        self.follow_btn.setIcon(icon)
        self.follow_btn.setToolTip("Pause auto-scroll" if self.pane.is_following()
                                   else "Resume auto-scroll")

    def _refresh_status(self, *_args) -> None:
        n = self.proxy.rowCount()
        matching = " matching" if self._narrowed() else ""
        state = "following" if self.pane.is_following() else "paused"
        self.status.setText(
            f"Logging active · {n} line{'s' if n != 1 else ''}{matching} · {state}")
