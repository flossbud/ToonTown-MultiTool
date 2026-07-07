"""Per-game account reorder modal. A scrollable list of rows over an explicit
order model; drag a row by its handle, or use the per-row up/down arrows. Both
funnel through _move(src, dst). The caller reads ordered_ids() on Accepted.

Visual surface: the dialog paints the game's v2 rich-tint card gradient
(158deg, darken/lighten of V2_ACCENTS[game]["c"]) plus a 2px accent border
directly on its own client area (paintEvent), rather than wrapping content in
a separate CardSurface widget - CardSurface assumes a normal child layout and
fights the absolute-positioned drag layer's row.y()/row.pos() bookkeeping.
Native QDialog modality (setModal(True)) is kept as-is; a literal frameless
full-parent dimming scrim was intentionally not added; this project's own
history (KWin window-type/transient-for/black-band landmines) shows that
class of window-manager trick is high risk for a low-stakes utility dialog.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QPoint, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)

import utils.motion as motion
from utils.color_math import alpha as css_alpha
from utils.color_math import darken_rgb, lighten_rgb, with_alpha
from utils.theme_manager import V2_ACCENTS, get_theme_colors, get_v2_tokens
from utils.toon_silhouette import paint_race_silhouette

_GAME_NAMES = {"ttr": "Toontown Rewritten", "cc": "Corporate Clash"}
SWAP_DURATION_MS = 160

MODAL_WIDTH = 470
MODAL_RADIUS = 20
MODAL_PADDING = 16
ROW_HEIGHT = 56
ROW_GAP = 8
LOGO_SIZE = 40
BADGE_SIZE = 18
ARROW_SIZE = 26
MINI_SIZE = 30
MINI_SIL_FRACTION = 0.76
MINI_RING_W = 2.5

_logo_cache: dict[str, QPixmap] = {}


def _asset_path(name: str) -> str:
    """Resolve a bundled asset relative to repo root / PyInstaller _MEIPASS.
    Same idiom as tabs/settings_tab.py._asset_path, ported here (utils/widgets
    is one directory deeper than tabs/, hence the extra dirname())."""
    base = getattr(
        sys, "_MEIPASS",
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    )
    return os.path.join(base, "assets", name)


def _game_logo_pixmap(game: str) -> QPixmap:
    """40px circular game-logo portrait for the header, cached per game."""
    cached = _logo_cache.get(game)
    if cached is not None:
        return cached
    src = QPixmap(_asset_path(f"{game}.png"))
    pm = QPixmap(LOGO_SIZE, LOGO_SIZE)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    circle = QRectF(0, 0, LOGO_SIZE, LOGO_SIZE)
    clip = QPainterPath()
    clip.addEllipse(circle)
    p.setClipPath(clip)
    if not src.isNull():
        scaled = src.scaled(LOGO_SIZE, LOGO_SIZE, Qt.KeepAspectRatioByExpanding,
                             Qt.SmoothTransformation)
        dx = (scaled.width() - LOGO_SIZE) // 2
        dy = (scaled.height() - LOGO_SIZE) // 2
        p.drawPixmap(-dx, -dy, scaled)
    else:
        p.fillPath(clip, QColor(V2_ACCENTS.get(game, V2_ACCENTS["blue"])["c"]))
    p.end()
    _logo_cache[game] = pm
    return pm


def _mini_toon_pixmap(game: str, is_dark: bool, species: str | None,
                       accent_hex: str | None, *, toon_name: str | None = None,
                       dna: str | None = None, customizations=None) -> QPixmap:
    """30px mini primary-toon portrait for a reorder row: the account's real toon
    portrait (same radial-menu source + saved pose as the tiles/picker) when it is
    cached, else a tinted race silhouette, else a faint dashed circle with a
    generic person glyph. Mirrors the recipe in utils/widgets/primary_toon_slot.py
    and utils/widgets/toon_picker_popover.py's _face_pixmap."""
    pm = QPixmap(MINI_SIZE, MINI_SIZE)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    circle = QRectF(0, 0, MINI_SIZE, MINI_SIZE)
    base_hex = "#ffffff" if is_dark else "#0f172a"
    ring_accent = accent_hex or V2_ACCENTS.get(game, V2_ACCENTS["blue"])["c"]

    # Real toon portrait from the radial-menu source (disk-cache synchronous).
    if dna:
        try:
            from utils.overlay.radial_portrait import render_account_portrait
            render = render_account_portrait(game, toon_name, dna, customizations, MINI_SIZE)
            if render.status == "complete":
                p.drawPixmap(0, 0, render.pixmap)
                p.setBrush(Qt.NoBrush)
                pen = QPen(QColor(ring_accent))
                pen.setWidthF(MINI_RING_W)
                p.setPen(pen)
                p.drawEllipse(circle.adjusted(MINI_RING_W / 2, MINI_RING_W / 2,
                                              -MINI_RING_W / 2, -MINI_RING_W / 2))
                p.end()
                return pm
        except Exception:
            pass

    if species:
        accent = accent_hex or V2_ACCENTS.get(game, V2_ACCENTS["blue"])["c"]
        p.setPen(Qt.NoPen)
        p.setBrush(with_alpha("#000000" if is_dark else "#0f172a", 0.22 if is_dark else 0.06))
        p.drawEllipse(circle)
        inset = MINI_SIZE * (1 - MINI_SIL_FRACTION) / 2
        sil_rect = circle.adjusted(inset, inset, -inset, -inset).toRect()
        fill_hex = lighten_rgb(QColor(accent), 0.5).name()
        paint_race_silhouette(p, sil_rect, species, fill_hex)
        p.setBrush(Qt.NoBrush)
        pen = QPen(QColor(accent))
        pen.setWidthF(MINI_RING_W)
        p.setPen(pen)
        ring = circle.adjusted(MINI_RING_W / 2, MINI_RING_W / 2,
                                -MINI_RING_W / 2, -MINI_RING_W / 2)
        p.drawEllipse(ring)
    else:
        p.setBrush(Qt.NoBrush)
        dash_pen = QPen(with_alpha(base_hex, 0.35), 2, Qt.DashLine)
        p.setPen(dash_pen)
        ring = circle.adjusted(1, 1, -1, -1)
        p.drawEllipse(ring)
        # Generic person glyph (head + shoulders), clipped to the circle so
        # the shoulder rect doesn't spill past the ring.
        clip = QPainterPath()
        clip.addEllipse(circle)
        p.setClipPath(clip)
        p.setPen(Qt.NoPen)
        p.setBrush(with_alpha(base_hex, 0.40))
        cx = MINI_SIZE / 2
        head_r = MINI_SIZE * 0.14
        p.drawEllipse(QPointF(cx, MINI_SIZE * 0.36), head_r, head_r)
        shoulders = QPainterPath()
        shoulders.addRoundedRect(
            QRectF(cx - MINI_SIZE * 0.24, MINI_SIZE * 0.54,
                   MINI_SIZE * 0.48, MINI_SIZE * 0.34),
            MINI_SIZE * 0.16, MINI_SIZE * 0.16)
        p.drawPath(shoulders)
    p.end()
    return pm


class _ReorderRow(QFrame):
    """One reorder list row: drag handle (drag source), position badge,
    mini primary-toon portrait, label-or-username text, and up/down buttons.
    Reordering is delegated to the owning dialog's _move() (arrows) or
    _begin_drag() (handle drag)."""
    def __init__(self, dialog: "AccountReorderDialog", index: int, account: dict,
                 is_first: bool, is_last: bool):
        super().__init__()
        self._dialog = dialog
        self._index = index
        self.setObjectName("reorder_row")
        self.setFixedHeight(ROW_HEIGHT)

        # Primary-toon fields (optional; absent -> the dashed/person placeholder).
        self._toon_is_set = bool(account.get("primary_is_set"))
        self._toon_species = account.get("primary_species")
        self._toon_accent = account.get("primary_accent")
        self._toon_name = account.get("primary_name")
        self._toon_dna = account.get("primary_dna")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        self.handle = QLabel("⠿")  # braille "grip" glyph (dot-grid look)
        self.handle.setObjectName("reorder_handle")
        self.handle.setCursor(Qt.OpenHandCursor)
        self.handle.setToolTip("Drag to reorder")
        self.handle.setAccessibleName("Drag to reorder")
        lay.addWidget(self.handle)

        self.badge = QLabel(str(index + 1))
        self.badge.setObjectName("reorder_badge")
        self.badge.setFixedSize(BADGE_SIZE, BADGE_SIZE)
        self.badge.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.badge)

        self.portrait = QLabel()
        self.portrait.setObjectName("reorder_portrait")
        self.portrait.setFixedSize(MINI_SIZE, MINI_SIZE)
        self.portrait.setStyleSheet("background: transparent;")
        lay.addWidget(self.portrait)

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
        self.up_btn.setFixedSize(ARROW_SIZE, ARROW_SIZE)
        self.up_btn.setCursor(Qt.PointingHandCursor)
        self.up_btn.setToolTip("Move up")
        self.up_btn.setAccessibleName("Move up")
        self.up_btn.setEnabled(not is_first)
        self.up_btn.clicked.connect(lambda: self._dialog._move_up(self._index))
        lay.addWidget(self.up_btn)

        self.down_btn = QToolButton()
        self.down_btn.setText("▼")
        self.down_btn.setFixedSize(ARROW_SIZE, ARROW_SIZE)
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

    def __init__(self, game: str, accounts: list[dict], parent=None,
                 customizations=None):
        super().__init__(parent)
        assert game in ("ttr", "cc")
        self._game = game
        # ToonCustomizationsManager so row portraits render the saved pose.
        self._customizations = customizations
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
        self.setFixedWidth(MODAL_WIDTH)

        # Card gradient/border colors, painted directly on the dialog's own
        # client area in paintEvent(). Real values are computed in
        # apply_theme(); these are just a safe pre-paint default.
        self._grad_top = QColor("#202020")
        self._grad_bot = QColor("#151515")
        self._border_col = QColor(255, 255, 255, 40)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(MODAL_PADDING, MODAL_PADDING, MODAL_PADDING, MODAL_PADDING)
        outer.setSpacing(12)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        self.logo_label = QLabel()
        self.logo_label.setFixedSize(LOGO_SIZE, LOGO_SIZE)
        self.logo_label.setStyleSheet("background: transparent;")
        self.logo_label.setPixmap(_game_logo_pixmap(game))
        head.addWidget(self.logo_label)
        head_text = QVBoxLayout()
        head_text.setSpacing(2)
        # Kept as "Reorder <Game> accounts" (rather than the design mock's
        # generic "Reorder accounts") because test_cc_game_title_and_accent
        # asserts the game name appears in title_label.text(); the logo
        # portrait to its left carries the same identity visually.
        self.title_label = QLabel(f"Reorder {_GAME_NAMES[game]} accounts")
        self.title_label.setObjectName("reorder_dialog_title")
        head_text.addWidget(self.title_label)
        self.help_label = QLabel("Drag a row or use the arrows. Numbers match the launcher order.")
        self.help_label.setObjectName("reorder_dialog_help")
        self.help_label.setWordWrap(True)
        head_text.addWidget(self.help_label)
        head.addLayout(head_text, 1)
        outer.addLayout(head)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._scroll.viewport().setStyleSheet("background: transparent;")
        self._rows_host = QWidget()
        self._rows_host.setStyleSheet("background: transparent;")
        self._rows_lay = QVBoxLayout(self._rows_host)
        self._rows_lay.setContentsMargins(0, 4, 0, 4)
        self._rows_lay.setSpacing(ROW_GAP)
        self._rows_lay.addStretch(1)
        self._scroll.setWidget(self._rows_host)
        outer.addWidget(self._scroll, 1)

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 4, 0, 0)
        foot.setSpacing(8)
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

    def _update_card_colors(self, is_dark: bool) -> None:
        """158deg rich-tint gradient + 2px border, exactly the recipe
        utils/widgets/card_surface.py's CardSurface._target_colors uses for
        the game group cards, so the reorder modal reads as the same surface
        family. Painted directly (see paintEvent) rather than via a nested
        CardSurface, which assumes a normal child layout and would fight the
        absolute-positioned drag layer's row.y()/row.pos() bookkeeping."""
        accent = V2_ACCENTS.get(self._game, V2_ACCENTS["blue"])
        c = QColor(accent["c"])
        if is_dark:
            self._grad_top = darken_rgb(c, 0.30)
            self._grad_bot = darken_rgb(c, 0.15)
            self._border_col = with_alpha(accent["b"], 0.55)
        else:
            self._grad_top = lighten_rgb(c, 0.80)
            self._grad_bot = lighten_rgb(c, 0.90)
            self._border_col = with_alpha(accent["c"], 0.50)

    def paintEvent(self, event):
        # Flat QSS background first (fills the tiny corner slivers outside
        # the rounded card - the dialog keeps its native OS window frame, so
        # this paints only the CONTENT area, not the title bar).
        super().paintEvent(event)
        if self.width() <= 0 or self.height() <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        path = QPainterPath()
        path.addRoundedRect(r, MODAL_RADIUS, MODAL_RADIUS)

        grad = QLinearGradient(r.topLeft().x(), r.topLeft().y(),
                                r.x() + r.width() * 0.38, r.y() + r.height())
        grad.setColorAt(0.0, self._grad_top)
        grad.setColorAt(1.0, self._grad_bot)
        p.fillPath(path, grad)

        p.save()
        p.setClipPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(self._border_col, 4))
        p.drawPath(path)
        p.restore()
        p.end()

    def apply_theme(self, c: dict) -> None:
        self._theme = c
        is_dark = QColor(c["text_primary"]).lightnessF() > 0.5
        v2 = get_v2_tokens(is_dark)
        accent = V2_ACCENTS.get(self._game, V2_ACCENTS["blue"])
        base_hex = "#ffffff" if is_dark else "#0f172a"

        self._update_card_colors(is_dark)
        self.setStyleSheet(f"QDialog {{ background: {c['bg_app']}; }}")
        self.update()

        self.title_label.setStyleSheet(
            f"color: {v2['title']}; font-size: 15px; font-weight: 700; background: transparent;")
        self.help_label.setStyleSheet(
            f"color: {v2['helper']}; font-size: 11px; background: transparent;")

        icon_color = css_alpha(base_hex, 0.62 if is_dark else 0.55)
        disabled_icon = css_alpha(base_hex, 0.35)
        disabled_border = css_alpha(base_hex, 0.35 * (0.14 if is_dark else 0.16))

        for r in self._rows:
            r.setStyleSheet(
                "QFrame#reorder_row {"
                f" background: {v2['row_bg']}; border: 1px solid {v2['row_border']};"
                f" border-radius: {v2['radius_row']}px; }}")
            r.handle.setStyleSheet(f"color: {v2['helper']}; font-size: 18px; background: transparent;")
            r.badge.setStyleSheet(
                f"background: {accent['b']}; color: #ffffff;"
                f" border: 2px solid {accent['c']}; border-radius: {BADGE_SIZE // 2}px;"
                " font-size: 9px; font-weight: 800;")
            r.portrait.setPixmap(_mini_toon_pixmap(
                self._game, is_dark,
                r._toon_species if r._toon_is_set else None,
                r._toon_accent,
                toon_name=r._toon_name if r._toon_is_set else None,
                dna=r._toon_dna if r._toon_is_set else None,
                customizations=self._customizations))
            r.title.setStyleSheet(f"color: {v2['title']}; font-size: 13px; font-weight: 700; background: transparent;")
            r.subtitle.setStyleSheet(f"color: {v2['sub']}; font-size: 10.5px; background: transparent;")
            for b in (r.up_btn, r.down_btn):
                b.setStyleSheet(
                    "QToolButton {"
                    f" background: {v2['ctrl_bg']}; border: 1px solid {v2['ctrl_border']};"
                    f" border-radius: {ARROW_SIZE // 2}px; color: {icon_color}; font-size: 10px; }}"
                    f"QToolButton:hover {{ background: {v2['ctrl_hover']}; }}"
                    "QToolButton:disabled {"
                    f" background: transparent; border: 1px solid {disabled_border};"
                    f" color: {disabled_icon}; }}")
        self.cancel_btn.setStyleSheet(
            "QPushButton {"
            f" background: {v2['btn_bg']}; border: 1px solid {v2['btn_border']};"
            f" color: {v2['title']}; border-radius: 17px; padding: 8px 18px;"
            " font-size: 12.5px; font-weight: 600; }"
            f"QPushButton:hover {{ background: {v2['ctrl_hover']}; }}")
        save_hover = lighten_rgb(QColor(accent["c"]), 0.12).name()
        self.save_btn.setStyleSheet(
            "QPushButton {"
            f" background: {accent['c']}; color: #ffffff; border: none;"
            " border-radius: 17px; padding: 8px 20px; font-size: 12.5px; font-weight: 700; }"
            f"QPushButton:hover {{ background: {save_hover}; }}")
