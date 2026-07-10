"""LogsCard — the whole Logs tab surface. v0 = CardSurface shell (purple,
gap 11) + pulsing status line + console pane. The toolbar (source segment,
search, follow button) and the scope-aware tag filter chip row are wired in;
header actions are added by follow-up tasks in the same plan."""
from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QRect, QSize, Qt,
                            QVariantAnimation)
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLayout, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from utils.color_math import alpha
from utils.icon_factory import make_nav_terminal
from utils.theme_manager import get_v2_tokens
from utils.widgets.card_surface import CardSurface
from utils.widgets.logs_console._tokens import get_logs_tokens
from utils.widgets.logs_console.model import LINE_ROLE, LogLineModel
from utils.widgets.logs_console.pane import LogConsolePane
from utils.widgets.logs_console.proxy import LogFilterProxy
from utils.widgets.logs_console.records import format_line, make_line
from utils.widgets.pill_controls import PillButton, SegmentedPill
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


class _FlowLayout(QLayout):
    """Minimal left-aligned wrap layout (gap 5) for the tag chip row."""

    def __init__(self, gap=5, parent=None):
        super().__init__(parent)
        self._gap = gap
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do_layout(QRect(0, 0, w, 0), test=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do_layout(self, rect, test):
        x, y, row_h = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            if row_h and x + hint.width() > rect.right() + 1:
                x = rect.x()
                y += row_h + self._gap
                row_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._gap
            row_h = max(row_h, hint.height())
        return y + row_h - rect.y()


class _TagChip(QPushButton):
    """Mono 10.5/600 pill chip. Idle = neutral translucent; active = tag-tinted
    bg + tag border (bundle chips spec)."""

    def __init__(self, tag: str, parent=None):
        super().__init__(tag, parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)

    def restyle(self, tokens: dict) -> None:
        tag_color = tokens["tags"].get(self.text(), tokens["tag_fallback"])
        active_bg = alpha(tag_color, tokens["chip_active_bg_alpha"])
        self.setStyleSheet(
            "QPushButton {"
            f" background: {tokens['chip_idle_bg']};"
            f" border: 1px solid {tokens['chip_idle_border']};"
            f" color: {tokens['chip_idle_text']};"
            " border-radius: 11px; padding: 3px 10px;"
            " font-family: 'Consolas','Menlo','DejaVu Sans Mono','Liberation Mono',monospace;"
            " font-size: 10.5px; font-weight: 600; }"
            "QPushButton:checked {"
            f" background: {active_bg}; border: 1px solid {tag_color};"
            f" color: {tokens['chip_active_text']}; }}")


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

        self.copy_btn = PillButton("Copy")
        self.copy_btn.setToolTip("Copy visible lines")
        self.copy_btn.clicked.connect(self._on_copy)
        self.export_btn = PillButton("Export")
        self.export_btn.setToolTip("Save visible lines as a .log file")
        self.export_btn.clicked.connect(self._on_export)
        self.clear_btn = PillButton("Clear", tone="danger")
        self.clear_btn.setToolTip("Clear this view")
        self.clear_btn.clicked.connect(self._on_clear)
        for b in (self.copy_btn, self.export_btn, self.clear_btn):
            self.surface.add_header_button(b)

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

        self._chips_host = QWidget()
        self._chips_host.setStyleSheet("background: transparent;")
        self._chips_layout = _FlowLayout(5, self._chips_host)
        self._chip_tags: list[str] = []
        self.surface.add_row(self._chips_host)

        self.pane = LogConsolePane(self.proxy)
        self.surface.add_row(self.pane, stretch=1)

        self.proxy.rowsInserted.connect(self._refresh_status)
        self.proxy.rowsRemoved.connect(self._refresh_status)
        self.proxy.modelReset.connect(self._refresh_status)
        self.pane.follow_changed.connect(self._refresh_status)
        self.pane.follow_changed.connect(self._refresh_follow_icon)
        self.model.rowsInserted.connect(self._rebuild_chips)
        self.model.modelReset.connect(self._rebuild_chips)

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
        for b in (self.copy_btn, self.export_btn, self.clear_btn):
            b.apply_theme(is_dark)
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
        for c in self.chips():
            c.restyle(t)

    def chips(self) -> list:
        return [self._chips_layout.itemAt(i).widget()
                for i in range(self._chips_layout.count())]

    # ── header actions ──────────────────────────────────────────────────
    def _visible_lines(self) -> list:
        return [self.proxy.index(i, 0).data(LINE_ROLE)
                for i in range(self.proxy.rowCount())]

    def _on_copy(self) -> None:
        from PySide6.QtWidgets import QApplication
        lines = self._visible_lines()
        if not lines:
            self.pane.show_toast("Nothing to copy")
            return
        QApplication.clipboard().setText(
            "\n".join(format_line(ln) for ln in lines))
        n = len(lines)
        self.pane.show_toast(
            f"Copied {n} line{'s' if n != 1 else ''} to clipboard")

    def _on_export(self) -> None:
        from datetime import date
        from PySide6.QtWidgets import QFileDialog
        lines = self._visible_lines()
        if not lines:
            self.pane.show_toast("Nothing to export")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export logs", f"ttmt-logs-{date.today().isoformat()}.log",
            "Log files (*.log)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(format_line(ln) for ln in lines) + "\n")
        except OSError as e:
            # An unhandled exception in a Qt slot is fatal in PySide6 — a
            # read-only dir or full disk must toast, never crash the app.
            self.pane.show_toast(f"Export failed: {e.strerror or e}")
            return
        n = len(lines)
        self.pane.show_toast(
            f"Exported {n} line{'s' if n != 1 else ''} to .log")

    def _on_clear(self) -> None:
        idx = self.segment.currentIndex()
        label, scope = self.SCOPES[idx]
        self.model.clear_scope(None if scope == "all" else scope)
        self.pane.show_toast("Logs cleared" if scope == "all"
                             else f"{label} cleared")
        self._rebuild_chips()
        self._refresh_status()
        self._refresh_empty_state()

    # ── internals ───────────────────────────────────────────────────────
    def _on_scope_changed(self, idx: int) -> None:
        # setCurrentIndex is silent by contract (no index_changed re-emit),
        # so this sync is safe: it keeps segment.currentIndex() truthful for
        # programmatic scope changes (e.g. tests, _on_clear) that don't go
        # through the real mousePressEvent path.
        self.segment.setCurrentIndex(idx)
        self.proxy.set_scope(self.SCOPES[idx][1])
        self._rebuild_chips()
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
        return bool(self.search.text().strip()) or any(
            c.isChecked() for c in self.chips())

    def _scoped_tags(self) -> list[str]:
        scope = self.proxy.scope()
        seen: list[str] = []
        for line in self.model.lines():
            if scope != "all" and line.source != scope:
                continue
            if line.tag and line.tag not in seen:
                seen.append(line.tag)
        return seen

    def _rebuild_chips(self, *_args) -> None:
        scoped = self._scoped_tags()
        if set(scoped) == set(self._chip_tags):
            return
        # Survivors keep their positions; genuinely new tags append at the
        # end. First-seen order of the SESSION, not of the rotating ring
        # buffer — buffer rotation must never reshuffle or rebuild the row.
        alive = set(scoped)
        tags = [t for t in self._chip_tags if t in alive]
        tags += [t for t in scoped if t not in tags]
        active = {c.text() for c in self.chips() if c.isChecked()}
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            item.widget().deleteLater()
        for tag in tags:
            chip = _TagChip(tag, self._chips_host)
            chip.setChecked(tag in active)
            chip.restyle(self._t)
            chip.toggled.connect(self._on_chips_changed)
            self._chips_layout.addWidget(chip)
        self._chip_tags = tags
        self._chips_host.setVisible(bool(tags))
        self._on_chips_changed()

    def _on_chips_changed(self, *_args) -> None:
        active = {c.text() for c in self.chips() if c.isChecked()}
        self.proxy.set_active_tags(active)
        self._refresh_status()
        self._refresh_empty_state()

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
