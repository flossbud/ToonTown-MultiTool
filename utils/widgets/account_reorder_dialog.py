"""Per-game account reorder modal. A scrollable list of rows over an explicit
order model; drag a row by its handle, or use the per-row up/down arrows. Both
funnel through _move(src, dst). The caller reads ordered_ids() on Accepted."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)

import utils.motion as motion
from utils.theme_manager import get_theme_colors

_ACCENT = {"ttr": "#4A8FE7", "cc": "#F26D21"}
_GAME_NAMES = {"ttr": "Toontown Rewritten", "cc": "Corporate Clash"}
SWAP_DURATION_MS = 160


class _ReorderRow(QFrame):
    """One reorder list row: drag handle (drag source), position badge,
    label-or-username text, and up/down buttons. Reordering is delegated to
    the owning dialog's _move() (arrows) or _begin_drag() (handle drag)."""
    def __init__(self, dialog: "AccountReorderDialog", index: int, account: dict,
                 is_first: bool, is_last: bool):
        super().__init__()
        self._dialog = dialog
        self._index = index
        self.setObjectName("reorder_row")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(11, 9, 11, 9)
        lay.setSpacing(11)

        self.handle = QLabel("⠇⠇")  # grip glyph
        self.handle.setObjectName("reorder_handle")
        self.handle.setCursor(Qt.OpenHandCursor)
        self.handle.setToolTip("Drag to reorder")
        self.handle.setAccessibleName("Drag to reorder")
        lay.addWidget(self.handle)

        self.badge = QLabel(str(index + 1))
        self.badge.setObjectName("reorder_badge")
        self.badge.setFixedSize(20, 20)
        self.badge.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.badge)

        label = (account.get("label") or "").strip()
        username = (account.get("username") or "").strip()
        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        self.title = QLabel(label or username or "(unnamed)")
        self.title.setObjectName("reorder_title")
        text_col.addWidget(self.title)
        self.subtitle = QLabel(username if label else "")
        self.subtitle.setObjectName("reorder_subtitle")
        self.subtitle.setVisible(bool(label and username))
        text_col.addWidget(self.subtitle)
        lay.addLayout(text_col, 1)

        self.up_btn = QToolButton()
        self.up_btn.setText("▲")
        self.up_btn.setCursor(Qt.PointingHandCursor)
        self.up_btn.setToolTip("Move up")
        self.up_btn.setAccessibleName("Move up")
        self.up_btn.setEnabled(not is_first)
        self.up_btn.clicked.connect(lambda: self._dialog._move_up(self._index))
        lay.addWidget(self.up_btn)

        self.down_btn = QToolButton()
        self.down_btn.setText("▼")
        self.down_btn.setCursor(Qt.PointingHandCursor)
        self.down_btn.setToolTip("Move down")
        self.down_btn.setAccessibleName("Move down")
        self.down_btn.setEnabled(not is_last)
        self.down_btn.clicked.connect(lambda: self._dialog._move_down(self._index))
        lay.addWidget(self.down_btn)

    def mousePressEvent(self, e):
        on_handle = (e.button() == Qt.LeftButton
                     and self.handle.geometry().contains(e.position().toPoint()))
        self._press_on_handle = on_handle
        self._press_pt = e.position().toPoint() if on_handle else None
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        # Only a press that started on the drag handle (not the row body or the
        # arrow buttons, which consume their own events) begins a drag.
        if not (getattr(self, "_press_on_handle", False) and (e.buttons() & Qt.LeftButton)):
            return
        if (e.position().toPoint() - self._press_pt).manhattanLength() < 8:
            return
        self._press_on_handle = False  # consume so we only begin once
        self._dialog._begin_drag(self._index, e.globalPosition().toPoint())


class AccountReorderDialog(QDialog):
    order_changed = Signal()

    def __init__(self, game: str, accounts: list[dict], parent=None):
        super().__init__(parent)
        assert game in ("ttr", "cc")
        self._game = game
        self._order: list[dict] = list(accounts)
        self._rows: list[_ReorderRow] = []
        # Manual drag state.
        self._dragging = False
        self._drag_src = -1
        self._placeholder_index = -1
        self._dragged_row: _ReorderRow | None = None
        self._ghost: QLabel | None = None
        self._ghost_offset = None
        self._placeholder: QWidget | None = None
        self._autoscroll_dir = 0
        self._autoscroll = QTimer(self)
        self._autoscroll.setInterval(15)
        self._autoscroll.timeout.connect(self._do_autoscroll)
        self._swap_anims: list[QPropertyAnimation] = []
        self.setModal(True)
        self.setWindowTitle(f"Reorder {_GAME_NAMES[game]} accounts")
        self.setMinimumWidth(440)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.accent_bar = QFrame()
        self.accent_bar.setFixedHeight(3)
        self.accent_bar.setStyleSheet(f"background: {_ACCENT[game]};")
        outer.addWidget(self.accent_bar)

        head = QVBoxLayout()
        head.setContentsMargins(20, 16, 20, 4)
        self.title_label = QLabel(f"Reorder {_GAME_NAMES[game]} accounts")
        self.title_label.setObjectName("reorder_dialog_title")
        head.addWidget(self.title_label)
        self.help_label = QLabel("Drag a row or use the arrows. Numbers match the launcher order.")
        self.help_label.setObjectName("reorder_dialog_help")
        head.addWidget(self.help_label)
        outer.addLayout(head)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._rows_host = QWidget()
        self._rows_lay = QVBoxLayout(self._rows_host)
        self._rows_lay.setContentsMargins(14, 8, 14, 8)
        self._rows_lay.setSpacing(8)
        self._rows_lay.addStretch(1)
        self._scroll.setWidget(self._rows_host)
        outer.addWidget(self._scroll, 1)

        foot = QHBoxLayout()
        foot.setContentsMargins(20, 12, 20, 16)
        foot.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        foot.addWidget(self.cancel_btn)
        self.save_btn = QPushButton("Save order")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self.accept)
        foot.addWidget(self.save_btn)
        outer.addLayout(foot)

        self._theme = get_theme_colors(True)
        self._rebuild()
        self.apply_theme(self._theme)

        # Size the scroll area to show several rows up front (it otherwise
        # collapses to ~1 row). Show up to 6 rows, then scroll; a small floor so
        # a 2-3 account list still reads as a list. ~52px per row (content +
        # margins) + the 8px inter-row spacing, plus the host's 8+8 margins.
        _ROW_H = 52 + 8
        visible = min(max(len(self._order), 3), 6)
        self._scroll.setMinimumHeight(visible * _ROW_H + 16)

    def ordered_ids(self) -> list[str]:
        return [a["id"] for a in self._order]

    def _move(self, src: int, dst: int, animate: bool = False) -> None:
        n = len(self._order)
        if not (0 <= src < n) or not (0 <= dst < n) or src == dst:
            return
        # Stop any in-flight swap animations BEFORE _rebuild deletes their rows
        # (prevents dangling-widget animations on rapid clicks).
        self._finalize_swap_anims()
        # Capture settled Y of each current row, keyed by account id (rows and
        # _order are parallel).
        old_y = {a["id"]: self._rows[i].y() for i, a in enumerate(self._order)}
        item = self._order.pop(src)
        self._order.insert(dst, item)
        self._rebuild()
        if animate and not motion.is_reduced():
            self._animate_swap(old_y)
        self.order_changed.emit()

    def _move_up(self, i: int) -> None:
        self._move(i, i - 1, animate=True)

    def _move_down(self, i: int) -> None:
        self._move(i, i + 1, animate=True)

    def _animate_swap(self, old_y: dict) -> None:
        # Slide every row whose position changed from its old Y to its new (final)
        # Y. For a one-step arrow swap that is exactly the two swapped rows, so
        # both glide past each other.
        # Deliberate truncation: a 0 scale (reduced-motion / tests) floors to 0
        # and takes the instant path. Unlike motion.py's max(1, int(...)) helpers,
        # we WANT duration 0 to mean "no animation" here, so don't clamp it up.
        duration = int(SWAP_DURATION_MS * motion._TEST_DURATION_SCALE)
        if duration <= 0:
            return  # test/instant path
        # _rebuild() adds the new rows but their parent hasn't shown/polished
        # them yet, so the layout assigns them no geometry (y() == 0). Show them
        # and activate the layout to settle final positions synchronously (no
        # event-loop re-entrancy), so we animate only the rows that moved.
        for row in self._rows:
            row.setVisible(True)
        self._rows_lay.activate()
        for i, acct in enumerate(self._order):
            row = self._rows[i]
            prev = old_y.get(acct["id"])
            if prev is None or prev == row.y():
                continue
            end = row.pos()
            anim = QPropertyAnimation(row, b"pos")
            anim.setDuration(duration)
            anim.setEasingCurve(motion.EASE_STANDARD)
            anim.setStartValue(QPoint(row.x(), prev))
            anim.setEndValue(end)
            anim.finished.connect(lambda r=row, e=end: r.move(e))  # snap to exact end
            self._swap_anims.append(anim)
            anim.start()

    def _finalize_swap_anims(self) -> None:
        # Jump each in-flight animation to its end before stopping so the row
        # lands at its settled position (stop() alone strands it mid-glide and
        # poisons the next move's old_y capture / final-position diff).
        for anim in self._swap_anims:
            end = anim.endValue()
            tgt = anim.targetObject()
            anim.stop()
            if end is not None and tgt is not None:
                tgt.move(end)
        self._swap_anims = []

    # ── manual live-reflow drag ───────────────────────────────────────────
    def _begin_drag(self, index: int, global_pos) -> None:
        if self._dragging or not (0 <= index < len(self._rows)):
            return
        self._dragging = True
        self._drag_src = index
        self._placeholder_index = index
        self._dragged_row = self._rows[index]
        row = self._dragged_row

        pm = row.grab()
        self._ghost = QLabel(self)
        self._ghost.setPixmap(pm)
        self._ghost.setFixedSize(pm.size())
        self._ghost.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._ghost_offset = row.mapFromGlobal(global_pos)
        self._ghost.move(self.mapFromGlobal(global_pos) - self._ghost_offset)
        self._ghost.show()
        self._ghost.raise_()

        self._placeholder = QWidget()
        self._placeholder.setFixedHeight(max(row.height(), 1))
        row.hide()
        self._relayout_during_drag()
        if self.isVisible():
            self.grabMouse()

    def _target_index_for_y(self, y: int) -> int:
        others = [r for r in self._rows if r is not self._dragged_row]
        for p, r in enumerate(others):
            if y < r.y() + r.height() / 2:
                return p
        return len(others)

    def _drag_to(self, target: int) -> None:
        if not self._dragging:
            return
        target = max(0, min(target, len(self._order) - 1))
        if target == self._placeholder_index:
            return
        self._placeholder_index = target
        self._relayout_during_drag()

    def _relayout_during_drag(self) -> None:
        while self._rows_lay.count():
            self._rows_lay.takeAt(0)
        others = [r for r in self._rows if r is not self._dragged_row]
        pos = min(self._placeholder_index, len(others))
        for i, r in enumerate(others):
            if i == pos:
                self._rows_lay.addWidget(self._placeholder)
            self._rows_lay.addWidget(r)
        if pos >= len(others):
            self._rows_lay.addWidget(self._placeholder)
        self._rows_lay.addStretch(1)

    def _end_drag(self) -> None:
        if not self._dragging:
            return
        src, dst = self._drag_src, self._placeholder_index
        self._teardown_drag()
        n = len(self._order)
        dst = max(0, min(dst, n - 1))
        if 0 <= src < n and src != dst:
            item = self._order.pop(src)
            self._order.insert(dst, item)
            self.order_changed.emit()
        self._rebuild()

    def _cancel_drag(self) -> None:
        if not self._dragging:
            return
        self._teardown_drag()
        self._rebuild()  # _order untouched -> restores the pre-drag list

    def _teardown_drag(self) -> None:
        self._finalize_swap_anims()
        if self._autoscroll.isActive():
            self._autoscroll.stop()
        self._autoscroll_dir = 0
        if self.isVisible():
            self.releaseMouse()
        if self._ghost is not None:
            self._ghost.hide()              # avoid a one-frame ghost flash before deletion
            self._ghost.deleteLater()
            self._ghost = None
        self._placeholder = None
        # The dragged row was removed from the layout during the drag, so the
        # upcoming _rebuild() (which only deletes widgets still in the layout)
        # won't reclaim it. Delete it here so repeated drags don't orphan a
        # hidden row per drag in _rows_host.
        if self._dragged_row is not None:
            self._dragged_row.setParent(None)
            self._dragged_row.deleteLater()
        self._dragged_row = None
        self._dragging = False

    def _update_autoscroll(self, global_pos) -> None:
        vp = self._scroll.viewport()
        y = vp.mapFromGlobal(global_pos).y()
        h = vp.height()
        if y < 28:
            self._autoscroll_dir = -1
        elif y > h - 28:
            self._autoscroll_dir = 1
        else:
            self._autoscroll_dir = 0
        if self._autoscroll_dir and not self._autoscroll.isActive():
            self._autoscroll.start()
        elif not self._autoscroll_dir and self._autoscroll.isActive():
            self._autoscroll.stop()

    def _do_autoscroll(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.value() + self._autoscroll_dir * 12)

    # ── input routed here while the mouse is grabbed during a drag ────────
    def mouseMoveEvent(self, e):
        if not self._dragging:
            return super().mouseMoveEvent(e)
        gp = e.globalPosition().toPoint()
        if self._ghost is not None:
            self._ghost.move(self.mapFromGlobal(gp) - self._ghost_offset)
        host_y = self._rows_host.mapFromGlobal(gp).y()
        self._drag_to(self._target_index_for_y(host_y))
        self._update_autoscroll(gp)

    def mouseReleaseEvent(self, e):
        if self._dragging and e.button() == Qt.LeftButton:
            self._end_drag()
            return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if self._dragging and e.key() == Qt.Key_Escape:
            self._cancel_drag()
            return
        super().keyPressEvent(e)

    def reject(self):
        if self._dragging:
            self._cancel_drag()
        super().reject()

    def _rebuild(self) -> None:
        while self._rows_lay.count():
            it = self._rows_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._rows = []
        n = len(self._order)
        for i, acct in enumerate(self._order):
            row = _ReorderRow(self, i, acct, is_first=(i == 0), is_last=(i == n - 1))
            self._rows_lay.addWidget(row)
            self._rows.append(row)
        self._rows_lay.addStretch(1)
        self.apply_theme(getattr(self, "_theme", get_theme_colors(True)))

    def apply_theme(self, c: dict) -> None:
        self._theme = c
        self.setStyleSheet(f"QDialog {{ background: {c['bg_app']}; }}")
        self.title_label.setStyleSheet(
            f"color: {c['text_primary']}; font-size: 16px; font-weight: 700;")
        self.help_label.setStyleSheet(f"color: {c['text_muted']}; font-size: 12px;")
        for r in self._rows:
            r.setStyleSheet(
                "QFrame#reorder_row {"
                f" background: {c['bg_card_inner']}; border: 1px solid {c['border_card']};"
                " border-radius: 9px; }")
            r.handle.setStyleSheet(f"color: {c['text_muted']}; font-size: 14px; background: transparent;")
            r.badge.setStyleSheet(
                f"background: {_ACCENT[self._game]}; color: {c['text_on_accent']};"
                " border-radius: 10px; font-size: 11px; font-weight: 700;")
            r.title.setStyleSheet(f"color: {c['text_primary']}; font-size: 13px; font-weight: 600; background: transparent;")
            r.subtitle.setStyleSheet(f"color: {c['text_muted']}; font-size: 11px; background: transparent;")
            for b in (r.up_btn, r.down_btn):
                b.setStyleSheet(
                    "QToolButton {"
                    f" border: 1px solid {c['border_muted']}; border-radius: 6px;"
                    f" color: {c['text_secondary']}; font-size: 10px; padding: 4px 6px; }}"
                    f"QToolButton:disabled {{ color: {c['border_card']}; border-color: {c['border_muted']}; }}")
        for btn, primary in ((self.cancel_btn, False), (self.save_btn, True)):
            if primary:
                btn.setStyleSheet(
                    "QPushButton {"
                    f" background: {c['accent_blue_btn']}; color: {c['text_on_accent']};"
                    " border: none; border-radius: 8px; padding: 8px 18px; font-weight: 600; }"
                    f"QPushButton:hover {{ background: {c['accent_blue_btn_hover']}; }}")
            else:
                btn.setStyleSheet(
                    "QPushButton {"
                    f" background: transparent; border: 1px solid {c['border_muted']};"
                    f" color: {c['text_secondary']}; border-radius: 8px; padding: 8px 18px; }}")
