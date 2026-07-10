"""Console pane: near-black (dark) / near-white (light) inset terminal
surface hosting a QListView of LogLineDelegate rows, plus the follow/pause
scroll contract, the jump-to-live pill, the feedback toast, and the
empty-state label. Overlays are plain children of this frame (the
update-banner pattern) — no QGraphicsEffect anywhere (kit law)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFontMetrics, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import (QApplication, QFrame, QLabel, QListView,
                               QPushButton, QVBoxLayout)

from utils.icon_factory import make_arrow_down_icon
from utils.theme_manager import V2_ACCENTS
from utils.widgets import install_modern_scrollbar
from utils.widgets.logs_console._tokens import get_logs_tokens
from utils.widgets.logs_console.delegate import LogLineDelegate
from utils.widgets.logs_console.model import LINE_ROLE
from utils.widgets.logs_console.records import format_line
from utils.widgets.portrait_badge import _qcolor_from_rgba

FOLLOW_SLOP = 40          # px from bottom that still counts as "at bottom"
RADIUS = 13
COPIED_MS = 1300
TOAST_MS = 1700
_ACCENT = V2_ACCENTS["purple"]


class LogConsolePane(QFrame):
    follow_changed = Signal(bool)

    def __init__(self, proxy, parent=None):
        super().__init__(parent)
        self._proxy = proxy
        self._t = get_logs_tokens(True)
        self._following = True
        self._pending = 0
        self._last_scroll = -1
        self.setStyleSheet("background: transparent;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 7, 4, 7)      # bundle pane padding 7px 4px
        self.view = QListView(self)
        self.view.setModel(proxy)
        self.delegate = LogLineDelegate(self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setStyleSheet(
            "QListView { background: transparent; border: none; }")
        self.view.viewport().setAutoFillBackground(False)
        self.view.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setSelectionMode(QListView.NoSelection)
        self.view.setUniformItemSizes(False)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setMouseTracking(True)
        self.view.setCursor(Qt.PointingHandCursor)
        self.view.setToolTip("Click to copy line")
        # Kit scrollbar (house pattern — same call as settings_tab.py /
        # launch_tab.py): replaces the vertical bar in place, so grabbing
        # it AFTER this call is required to bind the follow FSM to the
        # installed AutoHideScrollBar, not the QScrollBar it replaced.
        install_modern_scrollbar(self.view, is_dark=True)
        lay.addWidget(self.view)

        sb = self.view.verticalScrollBar()
        sb.valueChanged.connect(self._on_scroll_value)
        proxy.rowsInserted.connect(self._on_rows_inserted)
        proxy.modelReset.connect(self._on_model_reset)
        proxy.rowsRemoved.connect(self._on_rows_removed)
        self.view.clicked.connect(self._on_clicked)

        # Overlays (children of the frame; repositioned in resizeEvent).
        self.jump_pill = QPushButton(self)
        self.jump_pill.setCursor(Qt.PointingHandCursor)
        self.jump_pill.setIcon(make_arrow_down_icon(10, QColor("#ffffff")))
        self.jump_pill.clicked.connect(lambda: self.set_following(True))
        self.jump_pill.hide()
        self.toast = QLabel(self)
        self.toast.setAlignment(Qt.AlignCenter)
        self.toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast.hide)
        self.empty_label = QLabel(self)
        self.empty_label.setWordWrap(True)
        self.empty_label.hide()
        self._copied_timer = QTimer(self)
        self._copied_timer.setSingleShot(True)
        self._copied_timer.timeout.connect(self.delegate.clear_copied)
        self._style_overlays()

    # ── follow contract ─────────────────────────────────────────────────
    def is_following(self) -> bool:
        return self._following

    def pending_count(self) -> int:
        return self._pending

    def _at_bottom(self) -> bool:
        sb = self.view.verticalScrollBar()
        return sb.maximum() - sb.value() <= FOLLOW_SLOP

    def set_following(self, on: bool) -> None:
        if on:
            self.view.scrollToBottom()
            self._pending = 0
        if on != self._following:
            self._following = on
            self.follow_changed.emit(on)
        self._refresh_jump_pill()

    def _on_scroll_value(self, value: int) -> None:
        prev, self._last_scroll = self._last_scroll, value
        at = self._at_bottom()
        if at and not self._following:
            self.set_following(True)
        elif (not at) and self._following and prev >= 0 and value < prev:
            # User scrolled AWAY from the bottom (value decreased) — content
            # growth alone never decreases the value, so this is a real
            # scroll-up, not a rangeChanged artifact.
            self._following = False
            self._pending = 0
            self.follow_changed.emit(False)
            self._refresh_jump_pill()

    def _on_rows_inserted(self, _parent, first, last) -> None:
        if self._following:
            # Defer one event-loop turn so the view has laid the row out.
            QTimer.singleShot(0, self.view.scrollToBottom)
        else:
            self._pending += last - first + 1
            self._refresh_jump_pill()
        self.refresh_empty_state()

    def _on_rows_removed(self, *_) -> None:
        self.refresh_empty_state()

    def _on_model_reset(self) -> None:
        self._pending = 0
        self.delegate.clear_cache()   # drop heights for trimmed/cleared lines
        self._refresh_jump_pill()
        self.refresh_empty_state()

    # ── per-line copy ───────────────────────────────────────────────────
    def _on_clicked(self, index) -> None:
        line = index.data(LINE_ROLE)
        if line is None:
            return
        QApplication.clipboard().setText(format_line(line))
        self.delegate.set_copied(index)
        self._copied_timer.start(COPIED_MS)

    # ── overlays ────────────────────────────────────────────────────────
    def show_toast(self, text: str) -> None:
        # Elide BEFORE setText so the label is laid out exactly once.
        # 26 = the toast QSS horizontal padding (13px per side); 24 = 12px
        # of pane air on each side.
        max_w = self.width() - 24
        fm = QFontMetrics(self.toast.font())
        if fm.horizontalAdvance(text) + 26 > max_w:
            text = fm.elidedText(text, Qt.ElideRight, max_w - 26)
        self.toast.setText(text)
        self.toast.adjustSize()
        if self.toast.width() > max_w:
            self.toast.resize(max_w, self.toast.height())
        self._place_toast()
        self.toast.show()
        self.toast.raise_()
        self._toast_timer.start(TOAST_MS)

    def set_empty_text(self, text: str) -> None:
        self.empty_label.setText(text)

    def refresh_empty_state(self) -> None:
        empty = self._proxy.rowCount() == 0
        self.empty_label.setVisible(empty)
        if empty:
            self.empty_label.adjustSize()
            self.empty_label.move(12, 18)   # bundle empty-state padding 18px 12px
            self.empty_label.raise_()

    def _refresh_jump_pill(self) -> None:
        show = (not self._following) and self._pending > 0
        if show:
            n = self._pending
            self.jump_pill.setText(f"{n} new line{'s' if n != 1 else ''}")
            self.jump_pill.adjustSize()
            self._place_jump_pill()
        self.jump_pill.setVisible(show)
        if show:
            self.jump_pill.raise_()

    def _place_jump_pill(self) -> None:
        self.jump_pill.move((self.width() - self.jump_pill.width()) // 2,
                            self.height() - self.jump_pill.height() - 12)

    def _place_toast(self) -> None:
        self.toast.move((self.width() - self.toast.width()) // 2, 12)

    def _style_overlays(self) -> None:
        t = self._t
        self.jump_pill.setStyleSheet(
            "QPushButton {"
            f" background: {_ACCENT['c']}; border: 1px solid {_ACCENT['b']};"
            " color: #ffffff; border-radius: 13px; height: 26px;"
            " padding: 0 13px; font-size: 11.5px; font-weight: 700; }")
        self.jump_pill.setFixedHeight(26)
        self.toast.setStyleSheet(
            f"background: {t['toast_bg']}; border: 1px solid {t['toast_border']};"
            " color: #ffffff; border-radius: 13px; padding: 0 13px;"
            " font-size: 11.5px; font-weight: 600;")
        self.toast.setFixedHeight(26)
        self.empty_label.setStyleSheet(
            f"background: transparent; color: {t['empty']}; font-size: 11.5px;")

    # ── theme / geometry / paint ────────────────────────────────────────
    def apply_theme(self, is_dark: bool) -> None:
        self._t = get_logs_tokens(is_dark)
        self.delegate.apply_theme(is_dark)
        self._style_overlays()
        self.view.verticalScrollBar().set_theme(is_dark)
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Row heights depend on viewport width — invalidate the filter to
        # force a relayout with fresh sizeHints (cheap at <=500 rows).
        self._proxy.invalidate()
        if self.jump_pill.isVisible():
            self._place_jump_pill()
        if self.toast.isVisible():
            self._place_toast()
        if self._following:
            QTimer.singleShot(0, self.view.scrollToBottom)

    def paintEvent(self, event) -> None:
        t = self._t
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, RADIUS, RADIUS)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillPath(path, QColor(t["console_bg"]))
        # Inset top shadow (`inset 0 2px 10px`): a clipped vertical fade band.
        p.save()
        p.setClipPath(path)
        grad = QLinearGradient(r.x(), r.y(), r.x(), r.y() + 10)
        grad.setColorAt(0.0, _qcolor_from_rgba(t["inset_shadow"]))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(r.x(), r.y(), r.width(), 10), grad)
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_qcolor_from_rgba(t["console_border"]), 1))
        p.drawPath(path)
        p.end()
